import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import type { InvestigationReport, TxnDetail } from "../../api/types";
import { canAct } from "../../auth/roles";
import { useSession } from "../../auth/session";
import { RiskBadge } from "../../components/RiskBadge";
import { ErrorState, Spinner } from "../../components/states";
import { actionLabel, fmtMoney, fmtTime } from "../../format";
import { ReportPanel } from "./ReportPanel";

const SHOWN = ["account_id", "merchant_id", "amount", "ts", "status", "type", "payment_method", "geo", "source"];
const LINK_TEXT: Record<string, string> = { shared_device: "shared device", co_merchant_burst: "co-merchant burst" };

export function TransactionPanel({ txnId }: { txnId: string }) {
  const { client, role } = useSession();
  const q = useQuery({
    queryKey: ["txn", txnId],
    queryFn: () => client.get<TxnDetail>(`/transactions/${encodeURIComponent(txnId)}`),
  });
  const report = useMutation({
    mutationFn: () => client.post<InvestigationReport>(`/agent/report/${encodeURIComponent(txnId)}`),
  });

  if (q.isPending) return <Spinner label="Loading transaction" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const { details, risk, explanation, explanation_unavailable, related } = q.data;
  const t = details.transaction;
  const maxShap = Math.max(0.0001, ...(explanation?.contributions ?? []).map((c) => Math.abs(c.shap)));

  return (
    <div className="grid grid-2 txn-grid">
      <section className="panel" aria-label="Transaction">
        <h2>Transaction {txnId}</h2>
        <table><tbody>
          {SHOWN.filter((k) => t[k] != null).map((k) => (
            <tr key={k}><th>{k}</th><td>{k === "amount" ? fmtMoney(Number(t[k])) : k === "ts" ? fmtTime(String(t[k])) : String(t[k])}</td></tr>
          ))}
        </tbody></table>
        <div className="muted">Data source: {details.data_provenance}
          {details.missing_fields.length ? ` · missing: ${details.missing_fields.join(", ")}` : ""}</div>
      </section>

      <section className="panel" aria-label="Risk assessment">
        <h2>Risk assessment</h2>
        {risk === null ? <div className="muted">This transaction has not been scored.</div> : (
          <>
            <div className="row">
              <RiskBadge level={risk.risk_level} />
              <span>Score {risk.risk_score.toFixed(2)}</span>
              <span>Calibrated model probability {risk.calibrated_fraud_probability.toFixed(2)}</span>
              <span className="pill">{actionLabel(risk.recommended_action)}</span>
              {risk.cluster_id ? <span className="pill">Cluster {risk.cluster_id}</span> : null}
            </div>
            <h3>Risk factors</h3>
            <ul>{risk.risk_factors.map((f, i) => <li key={i}>{f}</li>)}</ul>
            {risk.behaviour_reasons.length ? (
              <><h3>Behaviour</h3><ul>{risk.behaviour_reasons.map((f, i) => <li key={i}>{f}</li>)}</ul></>
            ) : null}
            <div className="muted">{risk.note}</div>
          </>
        )}
      </section>

      <section className="panel" aria-label="Model explanation">
        <h2>Why the model scored it this way</h2>
        {explanation === null ? <div className="muted">{explanation_unavailable ?? "No explanation is available."}</div> : (
          <table><tbody>
            {explanation.contributions.map((c) => (
              <tr key={c.feature}>
                <td>{c.feature}</td><td>{Number(c.value).toFixed(2)}</td>
                <td style={{ width: "45%" }}>
                  <div className="bar" role="img" aria-label={`SHAP ${c.shap.toFixed(2)}`}
                       style={{ width: `${(Math.abs(c.shap) / maxShap) * 100}%`, background: c.shap >= 0 ? "var(--high)" : "var(--low)" }} />
                </td>
                <td>{c.shap >= 0 ? "+" : "−"}{Math.abs(c.shap).toFixed(2)}</td>
              </tr>
            ))}
          </tbody></table>
        )}
      </section>

      <section className="panel" aria-label="Related accounts">
        <h2>Related accounts</h2>
        {related === null || related.related.length === 0 ? <div className="muted">No related accounts found.</div> : (
          <ul>
            {related.related.map((r) => (
              <li key={r.account_id}>{r.account_id}{" "}
                {r.links.map((l, i) => <span key={i} className="pill">{LINK_TEXT[String(l.type)] ?? String(l.type)}</span>)}</li>
            ))}
          </ul>
        )}
        {related ? <div className="muted">{related.note}</div> : null}
      </section>

      {canAct(role) ? (
        <div className="grid span-all">
          <div className="row">
            <button className="btn btn-primary" disabled={report.isPending} onClick={() => report.mutate()}>Generate AI report</button>
            {report.isPending ? <Spinner label="Investigating" /> : null}
          </div>
          {report.isError ? <ErrorState error={report.error instanceof ApiError ? report.error : new Error("The report failed")} /> : null}
          {report.data ? <ReportPanel report={report.data} /> : null}
        </div>
      ) : null}
    </div>
  );
}
