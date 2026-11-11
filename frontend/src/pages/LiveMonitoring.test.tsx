import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useParams } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type { LiveEvent, LiveMetrics, TxnListItem } from "../api/types";
import { fakeClient, renderPage } from "../test-utils";
import { LiveMonitoring } from "./LiveMonitoring";

const initial = (id: string, level: TxnListItem["risk_level"], ts: string): TxnListItem => ({
  external_id: id, ts, amount: 50, account_id: `ACC_${id}`, merchant_id: "M_1", source: "synthetic",
  risk_level: level, risk_score: 0.5, action: "MONITOR", cluster_id: null });
const live = (id: string, over: Partial<LiveEvent> = {}): LiveEvent => ({
  external_id: id, business_id: "demo_biz", ts: "2026-01-05T10:00:00+00:00", amount: 75, account_id: `ACC_${id}`,
  merchant_id: "M_2", source: "synthetic", risk_score: 0.7, risk_level: "HIGH", recommended_action: "REVIEW",
  calibrated_fraud_probability: 0.5, risk_factors: [], cluster_id: null, alert: true, late: false,
  latency_ms: 80, emitted_at: 0, ...over });
const metrics: LiveMetrics = { processed: 42, alerts: 5, p50_ms: 81.2, p95_ms: 162.4, max_ms: 300, dropped: 1,
  simulator: { running: true, sent: 10, errors: 0 } };

function stream() {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({ start(c) { ctrl = c; } });
  const fetchImpl = vi.fn(async () => new Response(body, { status: 200 })) as unknown as typeof fetch;
  return { fetchImpl, push: (o: object) => ctrl.enqueue(enc.encode(`data: ${JSON.stringify(o)}\n\n`)) };
}

function Opened() { const { txnId } = useParams(); return <div>Opened {txnId}</div>; }
function setup(opts: { role?: "viewer" | "analyst"; routes?: Record<string, unknown> } = {}) {
  const s = stream();
  const client = fakeClient({
    "GET /transactions": [initial("OLD-HIGH", "HIGH", "2026-01-01T10:00:00+00:00"), initial("OLD-LOW", "LOW", "2026-01-01T09:00:00+00:00")],
    "GET /metrics/live": metrics,
    "POST /simulate/start": { started: true },
    "POST /simulate/stop": { running: false, sent: 10, errors: 0 },
    ...opts.routes,
  });
  renderPage(
    <Routes>
      <Route path="/" element={<LiveMonitoring streamFetch={s.fetchImpl} />} />
      <Route path="/investigation/:txnId" element={<Opened />} />
    </Routes>,
    { client, role: opts.role });
  return { s, client };
}

describe("LiveMonitoring page", () => {
  it("shows initial transactions, then live events on top", async () => {
    const { s } = setup();
    await screen.findByText("OLD-HIGH");
    await waitFor(() => expect(screen.getByText(/connected/i)).toBeInTheDocument());
    act(() => s.push(live("NEW-1")));
    await screen.findByText("NEW-1");
    const rows = screen.getAllByRole("row");
    expect(within(rows[1]).getByText("NEW-1")).toBeInTheDocument(); // rows[0] is the header
  });

  it("marks HIGH+ rows and a click opens the investigation", async () => {
    setup();
    const high = (await screen.findByText("OLD-HIGH")).closest("tr")!;
    const low = screen.getByText("OLD-LOW").closest("tr")!;
    expect(high).toHaveClass("row-high-plus");
    expect(low).not.toHaveClass("row-high-plus");
    await userEvent.click(within(high).getByText("ACC_OLD-HIGH"));
    expect(await screen.findByText("Opened OLD-HIGH")).toBeInTheDocument();
  });

  it("viewers see no simulator controls", async () => {
    setup({ role: "viewer" });
    await screen.findByText("OLD-HIGH");
    expect(screen.queryByRole("button", { name: /start replay/i })).toBeNull();
    expect(screen.getByText(/analysts and admins/i)).toBeInTheDocument();
  });

  it("an analyst's start posts the speed and limit", async () => {
    const { client } = setup();
    await screen.findByText("OLD-HIGH");
    const speed = screen.getByLabelText(/speed/i);
    await userEvent.clear(speed); await userEvent.type(speed, "50");
    const limit = screen.getByLabelText(/limit/i);
    await userEvent.clear(limit); await userEvent.type(limit, "300");
    await userEvent.click(screen.getByRole("button", { name: /start replay/i }));
    await waitFor(() => expect(client.calls.find((c) => c.path === "/simulate/start")?.body).toEqual({ speed: 50, limit: 300 }));
  });

  it("an invalid speed blocks the request", async () => {
    const { client } = setup();
    await screen.findByText("OLD-HIGH");
    const speed = screen.getByLabelText(/speed/i);
    await userEvent.clear(speed); await userEvent.type(speed, "0");
    await userEvent.click(screen.getByRole("button", { name: /start replay/i }));
    expect(await screen.findByText(/speed must be/i)).toBeInTheDocument();
    expect(client.calls.some((c) => c.path === "/simulate/start")).toBe(false);
  });

  it("a 409 shows that a replay is already running", async () => {
    setup({ routes: { "POST /simulate/start": () => { throw new ApiError(409, "a replay is already running"); } } });
    await screen.findByText("OLD-HIGH");
    await userEvent.click(screen.getByRole("button", { name: /start replay/i }));
    expect(await screen.findByText(/already running/i)).toBeInTheDocument();
  });

  it("pausing stops new rows from appearing", async () => {
    const { s } = setup();
    await screen.findByText("OLD-HIGH");
    await waitFor(() => expect(screen.getByText(/connected/i)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /pause/i }));
    act(() => s.push(live("HIDDEN-1")));
    await new Promise((r) => setTimeout(r, 40));
    expect(screen.queryByText("HIDDEN-1")).toBeNull();
    expect(screen.getByRole("button", { name: /resume/i })).toBeInTheDocument();
  });

  it("labels the live counters as covering all data sources", async () => {
    setup();
    expect(await screen.findByText(/live counters \(all data sources\)/i)).toBeInTheDocument();
  });

  it("shows the counters from /metrics/live", async () => {
    setup();
    expect(await screen.findByText("42")).toBeInTheDocument();
    expect(screen.getByText("81.2 ms")).toBeInTheDocument();
    expect(screen.getByText("162.4 ms")).toBeInTheDocument();
    expect(screen.getByText(/replay running/i)).toBeInTheDocument();
  });

  it("shows dashes, not a crash, before any event has been scored (latency is null)", async () => {
    setup({ routes: { "GET /metrics/live": { processed: 0, alerts: 0, p50_ms: null, p95_ms: null, max_ms: null, dropped: 0,
      simulator: { running: false, sent: 0, errors: 0 } } } });
    expect(await screen.findByText("Latency p50")).toBeInTheDocument();
    await screen.findByText("OLD-HIGH");
    expect(document.body.textContent).not.toMatch(/null|NaN/);
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("does not show live events from another data source", async () => {
    const { s } = setup();
    await screen.findByText("OLD-HIGH");
    await waitFor(() => expect(screen.getByText(/connected/i)).toBeInTheDocument());
    act(() => { s.push(live("PP-1", { source: "paypal_sandbox" })); s.push(live("SYN-1")); });
    await screen.findByText("SYN-1");
    expect(screen.queryByText("PP-1")).toBeNull();
  });
});
