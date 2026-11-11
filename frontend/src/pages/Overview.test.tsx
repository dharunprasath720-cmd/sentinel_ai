import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import type { ModelsSummary, Overview as OverviewData, TxnListItem } from "../api/types";
import { SourceSelector } from "../components/Shell";
import { fakeClient, renderPage } from "../test-utils";
import { Overview } from "./Overview";

const overview = (total = 1234): OverviewData => ({
  source: "synthetic",
  transactions: { total, by_level: { LOW: total - 50, MODERATE: 30, HIGH: 12, CRITICAL: 8 } },
  open_alerts: 7, open_cases: 3, flagged_clusters: 2, suspicious_value: 56789.5,
  daily: total ? [{ date: "2026-01-01", transactions: total, high_plus: 20 }] : [],
});
const metric = { pr_auc: 0.739, roc_auc: 0.95, precision: 0.767, recall: 0.479, f1: 0.59, threshold: 0.4,
  n_positive: 100, calibrator: "isotonic", brier_raw: 0.02, brier_calibrated: 0.01 };
const models: ModelsSummary = {
  version: "demo-1", evaluation: "held-out test split",
  caveat: "These are held-out evaluation numbers on synthetic data; some suspicious activity is missed.",
  models: { lightgbm: metric, logreg: { ...metric, recall: 0.3 } },
};
const txn = (id: string, level: "HIGH" | "CRITICAL", ts: string): TxnListItem => ({
  external_id: id, ts, amount: 100, account_id: "ACC_1", merchant_id: "M_1", source: "synthetic",
  risk_level: level, risk_score: 0.9, action: "REVIEW", cluster_id: null });

function routes(over: Record<string, unknown> = {}) {
  return {
    "GET /metrics/overview": () => overview(),
    "GET /metrics/models": models,
    "GET /transactions": (c: { params?: { level?: string } }) =>
      c.params?.level === "CRITICAL" ? [txn("TXN-CRIT", "CRITICAL", "2026-01-02T10:00:00+00:00")]
                                      : [txn("TXN-HIGH", "HIGH", "2026-01-02T11:00:00+00:00")],
    ...over,
  };
}

describe("Overview page", () => {
  it("shows loading then the tiles from the response", async () => {
    renderPage(<Overview />, { client: fakeClient(routes()) });
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    expect(await screen.findByText("1,234")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("$56,790")).toBeInTheDocument();
    expect(screen.getByText(/suspicious value/i)).toBeInTheDocument();
    expect(screen.queryByText(/fraud loss/i)).toBeNull();
  });

  it("shows the empty state when there are no transactions, with no NaN", async () => {
    renderPage(<Overview />, { client: fakeClient(routes({ "GET /metrics/overview": () => overview(0) })) });
    expect(await screen.findByText(/no transactions for this data source/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/NaN/);
  });

  it("shows the error state with the server's detail on failure", async () => {
    const client = fakeClient(routes({ "GET /metrics/overview": () => { throw new ApiError(500, "database unavailable"); } }));
    renderPage(<Overview />, { client });
    expect(await screen.findByText("database unavailable")).toBeInTheDocument();
  });

  it("model panel shows recall next to PR-AUC and precision, plus the caveat", async () => {
    renderPage(<Overview />, { client: fakeClient(routes()) });
    const panel = await screen.findByRole("region", { name: /model quality/i });
    expect(await within(panel).findByText("0.479")).toBeInTheDocument();
    expect(within(panel).getAllByText(/pr-auc/i).length).toBeGreaterThan(0);
    expect(within(panel).getAllByText("0.767").length).toBe(2); // one per model
    expect(within(panel).getByText(/some suspicious activity is missed/i)).toBeInTheDocument();
  });

  it("a failing model endpoint does not hide the rest of the page", async () => {
    renderPage(<Overview />, { client: fakeClient(routes({ "GET /metrics/models": () => { throw new ApiError(503, "no model is loaded"); } })) });
    expect(await screen.findByText("1,234")).toBeInTheDocument();
    expect(await screen.findByText("no model is loaded")).toBeInTheDocument();
  });

  it("lists recent HIGH and CRITICAL transactions newest first, linking to Investigation", async () => {
    renderPage(<Overview />, { client: fakeClient(routes()) });
    const links = await screen.findAllByRole("link", { name: /TXN-/ });
    expect(links.map((l) => l.textContent)).toEqual(["TXN-HIGH", "TXN-CRIT"]);
    expect(links[0]).toHaveAttribute("href", "/investigation/TXN-HIGH");
  });

  it("changing the data source refetches with the new source", async () => {
    const client = fakeClient(routes());
    renderPage(<><SourceSelector /><Overview /></>, { client });
    await screen.findByText("1,234");
    await userEvent.selectOptions(screen.getByLabelText("Data source"), "paypal_sandbox");
    await waitFor(() => expect(client.calls.some((c) => c.path === "/metrics/overview" && c.params?.source === "paypal_sandbox")).toBe(true));
  });

  it("the daily chart has a legend naming both lines and a partial-day note", async () => {
    renderPage(<Overview />, { client: fakeClient(routes()) });
    const legend = await screen.findByRole("list", { name: /daily chart legend/i });
    expect(within(legend).getByText("All transactions")).toBeInTheDocument();
    expect(within(legend).getByText("HIGH + CRITICAL")).toBeInTheDocument();
    expect(screen.getByText(/last day may be partial/i)).toBeInTheDocument();
  });

  it("offers a linear or log scale for the distribution, log by default", async () => {
    renderPage(<Overview />, { client: fakeClient(routes()) });
    const log = await screen.findByRole("button", { name: "Log scale" });
    const linear = screen.getByRole("button", { name: "Linear scale" });
    expect(log).toHaveAttribute("aria-pressed", "true");
    expect(linear).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(linear);
    expect(linear).toHaveAttribute("aria-pressed", "true");
    expect(log).toHaveAttribute("aria-pressed", "false");
  });

  it("clicking a risk level filters the recent list to it, and clicking again clears the filter", async () => {
    const client = fakeClient(routes({
      "GET /transactions": (c: { params?: { level?: string } }) => c.params?.level === "MODERATE"
        ? [txn("TXN-MOD", "HIGH", "2026-01-02T09:00:00+00:00")]
        : c.params?.level === "CRITICAL" ? [txn("TXN-CRIT", "CRITICAL", "2026-01-02T10:00:00+00:00")]
        : [txn("TXN-HIGH", "HIGH", "2026-01-02T11:00:00+00:00")] }));
    renderPage(<Overview />, { client });
    const moderate = await screen.findByRole("button", { name: /MODERATE/ });
    await userEvent.click(moderate);
    expect(moderate).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByRole("link", { name: "TXN-MOD" })).toBeInTheDocument();
    expect(client.calls.some((c) => c.path === "/transactions" && c.params?.level === "MODERATE")).toBe(true);
    await userEvent.click(moderate);
    expect(moderate).toHaveAttribute("aria-pressed", "false");
    expect(await screen.findByRole("link", { name: "TXN-HIGH" })).toBeInTheDocument();
  });
});
