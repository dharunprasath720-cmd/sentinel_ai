import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import type { Alert, CaseSummary } from "../api/types";
import { canAct } from "../auth/roles";
import { useSession } from "../auth/session";
import { PageHeader } from "../components/PageHeader";
import { useSource } from "../source";
import { RiskBadge } from "../components/RiskBadge";
import { EmptyState, ErrorState, Spinner } from "../components/states";
import { AlertsGrid } from "./investigation/AlertsGrid";
import { CasePanel } from "./investigation/CasePanel";
import { TransactionPanel } from "./investigation/TransactionPanel";

export function Investigation() {
  const { client, role } = useSession();
  const { source } = useSource();
  const qc = useQueryClient();
  const { txnId } = useParams();
  const [tab, setTab] = useState<"alerts" | "cases">("alerts");
  const [selected, setSelected] = useState<number[]>([]);
  const [caseId, setCaseId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const alerts = useQuery({ queryKey: ["alerts", "open", source], queryFn: () => client.get<Alert[]>("/alerts", { status: "open", source }) });
  const cases = useQuery({ queryKey: ["cases", source], queryFn: () => client.get<CaseSummary[]>("/cases", { source }) });

  const open = useMutation({
    mutationFn: () => client.post<{ id: number }>("/cases", { alert_ids: selected }),
    onSuccess: (r) => {
      setError(null); setSelected([]); setCaseId(r.id); setTab("cases");
      void qc.invalidateQueries({ queryKey: ["cases"] });
      void qc.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.detail : "Could not open the case"),
  });

  const toggle = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  return (
    <div className="grid">
      <PageHeader title="Investigation Workspace" subtitle="Work alerts into cases, with the evidence beside you" />
      <div className="split">
        <section className="panel list-panel" aria-label="Alerts and cases">
          <div className="row" role="tablist">
            <button role="tab" aria-selected={tab === "alerts"} className="btn" onClick={() => setTab("alerts")}>Alerts</button>
            <button role="tab" aria-selected={tab === "cases"} className="btn" onClick={() => setTab("cases")}>Cases</button>
          </div>
          {error ? <div role="alert" className="muted">{error}</div> : null}
          {tab === "alerts" ? (
            alerts.isPending ? <Spinner /> : alerts.isError ? <ErrorState error={alerts.error} onRetry={() => alerts.refetch()} /> :
              alerts.data.length === 0 ? <EmptyState title="No open alerts" /> : (
                <>
                  <AlertsGrid alerts={alerts.data} selectable={canAct(role)} onSelectionChange={setSelected} />
                  {canAct(role) ? (
                    <button className="btn btn-primary" disabled={selected.length === 0 || open.isPending} onClick={() => open.mutate()}>
                      {selected.length ? `Open case from ${selected.length} selected` : "Open case from selected"}
                    </button>
                  ) : null}
                </>
              )
          ) : cases.isPending ? <Spinner /> : cases.isError ? <ErrorState error={cases.error} onRetry={() => cases.refetch()} /> :
            cases.data.length === 0 ? <EmptyState title="No cases yet" hint="Select alerts and open a case." /> : (
              <ul>
                {cases.data.map((c) => (
                  <li key={c.id}>
                    <button className="btn" onClick={() => setCaseId(c.id)}>
                      {`Case #${c.id} · ${c.status} · ${c.n_alerts} alert${c.n_alerts === 1 ? "" : "s"}`}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          <div className="muted">Alerts and cases shown are for the selected data source.</div>
        </section>

        <div className="grid">
          {txnId ? <TransactionPanel key={txnId} txnId={txnId} /> : null}
          {caseId !== null ? <CasePanel key={caseId} caseId={caseId} /> : null}
          {!txnId && caseId === null ? (
            <EmptyState title="Nothing selected" hint="Choose an alert to inspect a transaction, or a case to work on it." />
          ) : null}
        </div>
      </div>
    </div>
  );
}
