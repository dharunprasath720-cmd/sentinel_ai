import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type { ClusterSummary, GraphPayload } from "../api/types";
import { fakeClient, renderPage } from "../test-utils";
import { GraphExplorer } from "./GraphExplorer";

// React Flow needs a real layout engine; here the canvas is replaced by a plain list.
vi.mock("./graph/GraphCanvas", () => ({
  GraphCanvas: ({ graph, onExpand }: { graph: GraphPayload; onExpand: (id: string) => void }) => (
    <div data-testid="canvas">
      {graph.nodes.map((n) => (
        <div key={n.id}>
          <span>{n.label}</span> <span>{n.risk_level ?? "NO RISK"}</span>
          {n.kind === "account" ? <button onClick={() => onExpand(n.label)}>expand {n.label}</button> : null}
        </div>
      ))}
    </div>
  ),
}));

const clusters: ClusterSummary[] = [{ cluster_id: "CL_1", n_accounts: 4, n_devices: 1, n_merchants: 2, signals: ["shared_device"], risk_indicator: 0.9 }];
const graph = (over: Partial<GraphPayload> = {}): GraphPayload => ({
  nodes: [
    { id: "account:ACC_1", kind: "account", label: "ACC_1", risk_level: "HIGH", txn_count: 3 },
    { id: "device:D_1", kind: "device", label: "D_1", risk_level: "HIGH", txn_count: 3 },
  ],
  edges: [{ source: "account:ACC_1", target: "device:D_1", kind: "uses_device", weight: 3 }],
  truncated: false, ...over });

function setup(routes: Record<string, unknown> = {}) {
  const client = fakeClient({ "GET /graph/clusters": clusters, "GET /graph": () => graph(), ...routes });
  renderPage(<GraphExplorer />, { client });
  return client;
}

describe("Graph Explorer", () => {
  it("shows the clusters and loads one on click", async () => {
    const client = setup();
    await userEvent.click(await screen.findByRole("button", { name: /CL_1/ }));
    expect(await screen.findByText("ACC_1")).toBeInTheDocument();
    expect(client.calls.find((c) => c.path === "/graph")?.params).toMatchObject({ cluster: "CL_1" });
  });

  it("an account search loads its neighbourhood for the chosen window", async () => {
    const client = setup();
    await userEvent.type(await screen.findByLabelText(/account id/i), "ACC_1");
    await userEvent.selectOptions(screen.getByLabelText(/time window/i), "72");
    await userEvent.click(screen.getByRole("button", { name: /load account/i }));
    await screen.findByText("D_1");
    expect(client.calls.find((c) => c.path === "/graph")?.params).toEqual({ account: "ACC_1", hours: 72, source: "synthetic" });
  });

  it("an unknown account shows the server's detail", async () => {
    setup({ "GET /graph": () => { throw new ApiError(404, "Not found"); } });
    await userEvent.type(await screen.findByLabelText(/account id/i), "NOPE");
    await userEvent.click(screen.getByRole("button", { name: /load account/i }));
    expect(await screen.findByText("Not found")).toBeInTheDocument();
  });

  it("shows the truncation notice when the server cut the graph", async () => {
    setup({ "GET /graph": () => graph({ truncated: true }) });
    await userEvent.click(await screen.findByRole("button", { name: /CL_1/ }));
    expect(await screen.findByText(/truncated at 200 nodes/i)).toBeInTheDocument();
  });

  it("clicking an account node expands it and merges the neighbours", async () => {
    let n = 0;
    const client = setup({ "GET /graph": () => (n++ === 0 ? graph() : graph({
      nodes: [{ id: "account:ACC_2", kind: "account", label: "ACC_2", risk_level: "LOW", txn_count: 1 }], edges: [] })) });
    await userEvent.click(await screen.findByRole("button", { name: /CL_1/ }));
    await userEvent.click(await screen.findByRole("button", { name: "expand ACC_1" }));
    expect(await screen.findByText("ACC_2")).toBeInTheDocument();
    expect(screen.getByText("ACC_1")).toBeInTheDocument(); // still there after the merge
    await waitFor(() => expect(client.calls.filter((c) => c.path === "/graph").length).toBe(2));
    expect(client.calls[client.calls.length - 1].params).toMatchObject({ account: "ACC_1" });
  });

  it("an empty cluster list shows the empty state", async () => {
    setup({ "GET /graph/clusters": [] });
    expect(await screen.findByText(/no flagged clusters/i)).toBeInTheDocument();
  });

  it("a failing cluster list shows the error with its detail", async () => {
    setup({ "GET /graph/clusters": () => { throw new ApiError(500, "clusters unavailable"); } });
    expect(await screen.findByText("clusters unavailable")).toBeInTheDocument();
  });
});
