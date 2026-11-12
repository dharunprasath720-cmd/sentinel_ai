import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../api/client";
import type { Action, AuditEntry, CaseDetail } from "../../api/types";
import { canAct } from "../../auth/roles";
import { useSession } from "../../auth/session";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { RiskBadge } from "../../components/RiskBadge";
import { ErrorState, Spinner } from "../../components/states";
import { actionLabel, fmtTime } from "../../format";

const ACTIONS: Action[] = ["ALLOW", "MONITOR", "REVIEW", "VERIFY", "HOLD_RECOMMENDED"];
type Pending = { kind: "resolve"; outcome: "suspicious" | "cleared" } | { kind: "approve"; action: Action } | null;

export function CasePanel({ caseId }: { caseId: number }) {
  const { client, role } = useSession();
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [action, setAction] = useState<Action>("REVIEW");
  const [pending, setPending] = useState<Pending>(null);
  const [error, setError] = useState<string | null>(null);

  const c = useQuery({ queryKey: ["case", caseId], queryFn: () => client.get<CaseDetail>(`/cases/${caseId}`) });
  const isAdmin = role === "admin"; // the audit log is admin-only on the server
  const audit = useQuery({ queryKey: ["audit"], enabled: isAdmin, queryFn: () => client.get<AuditEntry[]>("/audit") });

  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body: unknown }) => client.post(path, body),
    onSuccess: () => {
      setError(null);
      for (const key of [["case", caseId], ["cases"], ["audit"], ["alerts"]]) void qc.invalidateQueries({ queryKey: key });
    },
    onError: (e) => setError(e instanceof ApiError ? e.detail : "The action failed"),
  });

  if (c.isPending) return <Spinner label="Loading case" />;
  if (c.isError) return <ErrorState error={c.error} onRetry={() => c.refetch()} />;
  const data = c.data;
  const resolved = data.status.startsWith("resolved");
  const mine = (audit.data ?? []).filter((e) => e.target === `case:${caseId}`);

  function confirm() {
    if (!pending) return;
    if (pending.kind === "resolve") act.mutate({ path: `/cases/${caseId}/resolve`, body: { outcome: pending.outcome } });
    else act.mutate({ path: `/cases/${caseId}/approve-action`, body: { action: pending.action } });
    setPending(null);
  }

  return (
    <div className="grid grid-3 case-grid">
      <section className="panel" aria-label="Case">
        <h2>Case #{data.id}</h2>
        <div className="row">
          <span className="pill">Status: {data.status}</span>
          <span className="pill">Approved action: {data.approved_action ? actionLabel(data.approved_action) : "none yet"}</span>
        </div>
        {resolved ? <div className="muted">This case is resolved; it can no longer be changed.</div> : null}
        <h3>Alerts in this case</h3>
        <ul>
          {data.alerts.map((a) => (
            <li key={a.id}>
              <Link to={`/investigation/${encodeURIComponent(a.txn_external_id)}`}>{a.txn_external_id}</Link>{" "}
              <RiskBadge level={a.assessment?.risk_level ?? a.level} />
              {a.assessment ? <span className="muted"> score {a.assessment.risk_score.toFixed(2)} · {a.assessment.factors.join("; ")}</span> : null}
            </li>
          ))}
        </ul>
        {error ? <div role="alert" className="error panel">{error}</div> : null}
        {canAct(role) && !resolved ? (
          <div className="grid">
            <div className="row">
              <label>Action to approve{" "}
                <select value={action} onChange={(e) => setAction(e.target.value as Action)}>
                  {ACTIONS.map((a) => <option key={a} value={a}>{actionLabel(a)}</option>)}
                </select>
              </label>
              <button className="btn" onClick={() => setPending({ kind: "approve", action })}>Approve action</button>
            </div>
            <div className="row">
              <button className="btn" onClick={() => setPending({ kind: "resolve", outcome: "suspicious" })}>Resolve as suspicious</button>
              <button className="btn" onClick={() => setPending({ kind: "resolve", outcome: "cleared" })}>Resolve as cleared</button>
            </div>
          </div>
        ) : null}
      </section>

      <section className="panel" aria-label="Notes">
        <h2>Notes</h2>
        {data.notes.length === 0 ? <div className="muted">No notes yet.</div> : (
          <ul>{data.notes.map((n, i) => (
            <li key={i}><strong>{n.author}</strong> <span className="muted">{fmtTime(n.ts)}</span><div>{n.body}</div></li>
          ))}</ul>
        )}
        {canAct(role) && !resolved ? (
          <form className="grid" onSubmit={(e) => { e.preventDefault(); act.mutate({ path: `/cases/${caseId}/notes`, body: { body: note } }); setNote(""); }}>
            <label>New note<textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} maxLength={5000} /></label>
            <div><button className="btn" disabled={!note.trim()}>Add note</button></div>
          </form>
        ) : null}
      </section>

      <section className="panel" aria-label="Audit timeline">
        <h2>Audit timeline</h2>
        {!isAdmin ? <div className="muted">The audit timeline is available to admins.</div> :
          audit.isPending ? <Spinner /> : audit.isError ? <ErrorState error={audit.error} onRetry={() => audit.refetch()} /> :
          mine.length === 0 ? <div className="muted">No audit entries for this case.</div> : (
            <ul>{mine.map((e) => <li key={e.id}>{fmtTime(e.ts)} · {e.actor} · {e.action}</li>)}</ul>
          )}
      </section>

      <ConfirmDialog open={pending !== null} confirmLabel="Confirm" onConfirm={confirm} onCancel={() => setPending(null)}
        title={pending?.kind === "resolve" ? `Resolve case as ${pending.outcome}?` : "Approve this action?"}>
        {pending?.kind === "resolve" ? (
          <p>{pending.outcome === "suspicious"
            ? `This closes case #${caseId} as suspicious. It does not confirm fraud. A resolved case cannot be reopened.`
            : `This closes case #${caseId} as cleared. A resolved case cannot be reopened.`}</p>
        ) : pending?.kind === "approve" ? (
          <p>Approve {actionLabel(pending.action)} for case #{caseId}? This records the approved action only; nothing is blocked automatically.</p>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}
