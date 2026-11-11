import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import type { Alert, AuditEntry, CaseDetail, CaseSummary, InvestigationReport, TxnDetail } from "../api/types";
import { fakeClient, renderPage } from "../test-utils";
import { Investigation } from "./Investigation";

const HTML = "<img src=x onerror=alert(1)>";
const alerts: Alert[] = [
  { id: 1, txn_external_id: "T-1", level: "HIGH", status: "open" },
  { id: 2, txn_external_id: "T-2", level: "CRITICAL", status: "open" },
];
const cases: CaseSummary[] = [{ id: 5, status: "open", approved_action: null, n_alerts: 1, created_at: "2026-01-02T10:00:00+00:00" }];
const caseDetail = (over: Partial<CaseDetail> = {}): CaseDetail => ({
  id: 5, status: "open", approved_action: null,
  alerts: [{ ...alerts[0], assessment: { risk_score: 0.81, risk_level: "HIGH", action: "REVIEW",
    calibrated_fraud_probability: 0.4, factors: ["Shared device across accounts"], model_version: "m", policy_version: "p" } }],
  notes: [{ author: "ana", body: "first note", ts: "2026-01-02T11:00:00+00:00" }], ...over });
const txn = (over: Partial<TxnDetail> = {}): TxnDetail => ({
  details: { transaction: { external_id: "T-1", account_id: "ACC_9", amount: 250, merchant_id: "M_3", ts: "2026-01-02T10:00:00+00:00",
    status: "completed", source: "synthetic", currency: "USD" }, missing_fields: [], data_provenance: "synthetic" },
  risk: { risk_score: 0.81, risk_level: "HIGH", recommended_action: "HOLD_RECOMMENDED", calibrated_fraud_probability: 0.4,
    risk_factors: ["Unusual transaction pattern (anomaly score)"], component_inputs: { ml_prob: 0.4 },
    behaviour_reasons: ["Amount far above this account's typical spend"], cluster_id: "CL_1", model_version: "m",
    policy_version: "p", note: "Neither is a confirmed outcome.", alert: { id: 1, status: "open", level: "HIGH" } },
  explanation: { contributions: [{ feature: "txn_count_1h", value: 6, shap: 1.2 }, { feature: "amount_zscore", value: 2, shap: -0.4 }] },
  explanation_unavailable: null,
  related: { account_id: "ACC_9", note: "A shared device is a relationship to examine, not evidence of wrongdoing.",
    related: [{ account_id: "ACC_10", links: [{ type: "shared_device", device_id: "D_1" }] }] }, ...over });
const report = (over: Partial<InvestigationReport> = {}): InvestigationReport => ({
  case_id: "CASE-T-1", transaction: {}, risk_assessment: {}, summary: "Suspicious and worth analyst review.",
  model_findings: [{ claim: "Model rates it HIGH", evidence_ids: ["txn:T-1"] }], behavioural_findings: [], graph_findings: [],
  supporting_evidence: [], contradictory_evidence: [{ claim: "Amount is small", evidence_ids: ["txn:T-1"] }],
  missing_information: ["No outcome data"], recommended_next_steps: ["Review the device history"], confidence: "medium",
  classification: "suspicious", llm_narrative: true, evidence_ids: ["txn:T-1"], notes: [], ...over });
const audit: AuditEntry[] = [
  { id: 1, ts: "2026-01-02T10:05:00+00:00", actor: "ana", action: "open_case", target: "case:5", before: null, after: null },
  { id: 2, ts: "2026-01-02T10:06:00+00:00", actor: "ana", action: "add_note", target: "case:6", before: null, after: null },
];

function setup(opts: { role?: "viewer" | "analyst" | "admin"; route?: string; routes?: Record<string, unknown> } = {}) {
  const client = fakeClient({
    "GET /alerts": alerts, "GET /cases": cases, "GET /cases/5": () => caseDetail(), "GET /audit": audit,
    "GET /transactions/T-1": () => txn(), "POST /cases": { id: 5, status: "open" },
    "POST /cases/5/notes": { id: 9 }, "POST /cases/5/resolve": { id: 5, status: "resolved_suspicious" },
    "POST /cases/5/approve-action": { id: 5, status: "in_review", approved_action: "HOLD_RECOMMENDED" },
    "POST /agent/report/T-1": () => report(), ...opts.routes,
  });
  renderPage(
    <Routes>
      <Route path="/investigation" element={<Investigation />} />
      <Route path="/investigation/:txnId" element={<Investigation />} />
    </Routes>,
    { client, role: opts.role, route: opts.route ?? "/investigation" });
  return client;
}

async function openCase5() {
  await userEvent.click(await screen.findByRole("tab", { name: /cases/i }));
  await userEvent.click(await screen.findByText(/case #5/i));
  await screen.findByText("first note");
}

describe("Investigation workspace", () => {
  it("lists alerts and opens a case from the selected ones", async () => {
    const client = setup();
    await screen.findByText("T-1");
    await userEvent.click(screen.getByRole("checkbox", { name: /T-1/ }));
    await userEvent.click(screen.getByRole("button", { name: /open case/i }));
    await waitFor(() => expect(client.calls.find((c) => c.path === "/cases" && c.method === "POST")?.body).toEqual({ alert_ids: [1] }));
  });

  it("the transaction panel shows risk factors and SHAP bars", async () => {
    setup({ route: "/investigation/T-1" });
    expect(await screen.findByText("Unusual transaction pattern (anomaly score)")).toBeInTheDocument();
    expect(screen.getByText("txn_count_1h")).toBeInTheDocument();
    expect(screen.getByText("amount_zscore")).toBeInTheDocument();
    expect(screen.getByText(/hold recommended/i)).toBeInTheDocument();
    expect(screen.getByText(/ACC_10/)).toBeInTheDocument();
    expect(screen.getByText(/neither is a confirmed outcome/i)).toBeInTheDocument();
  });

  it("an unavailable explanation shows a notice", async () => {
    setup({ route: "/investigation/T-1", routes: {
      "GET /transactions/T-1": () => txn({ explanation: null, explanation_unavailable: "no model is loaded, so explanations are unavailable" }) } });
    expect(await screen.findByText(/explanations are unavailable/i)).toBeInTheDocument();
  });

  it("an unknown transaction shows the server's not-found message", async () => {
    setup({ route: "/investigation/T-404", routes: { "GET /transactions/T-404": () => { throw new ApiError(404, "Not found"); } } });
    expect(await screen.findByText("Not found")).toBeInTheDocument();
  });

  it("viewers see no action controls", async () => {
    setup({ role: "viewer", route: "/investigation/T-1" });
    await screen.findByText("T-1", { selector: "a, td, span, div" });
    expect(screen.queryByRole("button", { name: /open case/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /generate ai report/i })).toBeNull();
    await openCase5();
    expect(screen.queryByRole("button", { name: /resolve as/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /add note/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /approve action/i })).toBeNull();
  });

  it("resolving requires a confirmation naming the outcome", async () => {
    const client = setup();
    await openCase5();
    await userEvent.click(screen.getByRole("button", { name: /resolve as suspicious/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/does not confirm fraud/i)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: /cancel/i }));
    expect(client.calls.some((c) => c.path === "/cases/5/resolve")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: /resolve as suspicious/i }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(client.calls.find((c) => c.path === "/cases/5/resolve")?.body).toEqual({ outcome: "suspicious" }));
  });

  it("a 409 from the server is shown with its detail", async () => {
    setup({ routes: { "POST /cases/5/resolve": () => { throw new ApiError(409, "case is already resolved"); } } });
    await openCase5();
    await userEvent.click(screen.getByRole("button", { name: /resolve as cleared/i }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("case is already resolved")).toBeInTheDocument();
  });

  it("approving an action posts the chosen action after confirmation", async () => {
    const client = setup();
    await openCase5();
    await userEvent.selectOptions(screen.getByLabelText(/action to approve/i), "HOLD_RECOMMENDED");
    await userEvent.click(screen.getByRole("button", { name: /approve action/i }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(client.calls.find((c) => c.path === "/cases/5/approve-action")?.body).toEqual({ action: "HOLD_RECOMMENDED" }));
  });

  it("adds a note", async () => {
    const client = setup();
    await openCase5();
    await userEvent.type(screen.getByLabelText(/new note/i), "looks like a ring");
    await userEvent.click(screen.getByRole("button", { name: /add note/i }));
    await waitFor(() => expect(client.calls.find((c) => c.path === "/cases/5/notes")?.body).toEqual({ body: "looks like a ring" }));
  });

  it("the report shows the model-written badge, findings with evidence, and contradictory evidence", async () => {
    setup({ route: "/investigation/T-1" });
    await userEvent.click(await screen.findByRole("button", { name: /generate ai report/i }));
    expect(await screen.findByText(/model-written narrative/i)).toBeInTheDocument();
    expect(screen.getByText("Model rates it HIGH")).toBeInTheDocument();
    expect(screen.getAllByText("txn:T-1").length).toBeGreaterThan(0);
    expect(screen.getByText("Amount is small")).toBeInTheDocument();
    expect(screen.getByText("No outcome data")).toBeInTheDocument();
  });

  it("the report says when it is the deterministic fallback", async () => {
    setup({ route: "/investigation/T-1", routes: { "POST /agent/report/T-1": () => report({ llm_narrative: false }) } });
    await userEvent.click(await screen.findByRole("button", { name: /generate ai report/i }));
    expect(await screen.findByText(/deterministic fallback/i)).toBeInTheDocument();
  });

  it("renders HTML in a note and in a report summary as literal text", async () => {
    const { container } = (() => {
      setup({ route: "/investigation/T-1", routes: {
        "GET /cases/5": () => caseDetail({ notes: [{ author: "ana", body: HTML, ts: "2026-01-02T11:00:00+00:00" }] }),
        "POST /agent/report/T-1": () => report({ summary: HTML }) } });
      return { container: document.body };
    })();
    await userEvent.click(await screen.findByRole("button", { name: /generate ai report/i }));
    await waitFor(() => expect(screen.getAllByText(HTML).length).toBe(1)); // the summary
    await userEvent.click(screen.getByRole("tab", { name: /cases/i }));
    await userEvent.click(await screen.findByText(/case #5/i));
    await waitFor(() => expect(screen.getAllByText(HTML).length).toBe(2)); // summary + note
    expect(container.querySelector("img")).toBeNull();
  });

  it("analysts are told the audit timeline is admin-only, not shown a false empty list", async () => {
    const client = setup({ role: "analyst" });
    await openCase5();
    const timeline = await screen.findByRole("region", { name: /audit timeline/i });
    expect(within(timeline).getByText(/available to admins/i)).toBeInTheDocument();
    expect(within(timeline).queryByText(/no audit entries/i)).toBeNull();
    expect(client.calls.some((c) => c.path === "/audit")).toBe(false);
  });

  it("the audit timeline shows only this case (admin)", async () => {
    setup({ role: "admin" });
    await openCase5();
    const timeline = await screen.findByRole("region", { name: /audit timeline/i });
    expect(await within(timeline).findByText(/open_case/)).toBeInTheDocument();
    expect(within(timeline).queryByText(/add_note/)).toBeNull();
  });
});
