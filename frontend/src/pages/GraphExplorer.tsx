import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../api/client";
import type { ClusterSummary, GraphPayload } from "../api/types";
import { useSession } from "../auth/session";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, Spinner } from "../components/states";
import { SOURCE_LABELS, useSource } from "../source";
import { GraphCanvas } from "./graph/GraphCanvas";
import { mergeGraphs } from "./graph/layout";

type View = { kind: "cluster"; id: string } | { kind: "account"; id: string; hours: number };
const HOURS = [1, 6, 24, 72, 168];

export function GraphExplorer() {
  const { client } = useSession();
  const { source } = useSource();
  const [view, setView] = useState<View | null>(null);
  const [extras, setExtras] = useState<GraphPayload[]>([]);
  const [expandError, setExpandError] = useState<string | null>(null);
  const [account, setAccount] = useState("");
  const [hours, setHours] = useState(24);
  const generation = useRef(0); // bumped whenever the view changes, so a late expand cannot land in a newer view

  const clusters = useQuery({
    queryKey: ["clusters", source],
    queryFn: () => client.get<ClusterSummary[]>("/graph/clusters", { source }),
  });
  const base = useQuery({
    queryKey: ["graph", view, source],
    enabled: view !== null,
    queryFn: () => view!.kind === "cluster"
      ? client.get<GraphPayload>("/graph", { cluster: view!.id })
      : client.get<GraphPayload>("/graph", { account: view!.id, hours: view!.hours, source }),
  });

  const graph = useMemo(
    () => (base.data ? extras.reduce(mergeGraphs, base.data) : null),
    [base.data, extras]);

  function show(next: View) { generation.current += 1; setView(next); setExtras([]); setExpandError(null); }

  // Never carry a graph (or accounts expanded into it) across a change of data source.
  useEffect(() => { generation.current += 1; setView(null); setExtras([]); setExpandError(null); }, [source]);

  async function expand(accountId: string) {
    setExpandError(null);
    const mine = generation.current;
    try {
      const more = await client.get<GraphPayload>("/graph", {
        account: accountId, hours: view?.kind === "account" ? view.hours : 24, source });
      if (mine === generation.current) setExtras((e) => [...e, more]);
    } catch (err) {
      setExpandError(err instanceof ApiError ? err.detail : "Could not expand this account");
    }
  }

  return (
    <div className="grid">
      <PageHeader title="Graph Explorer" subtitle={`Linked accounts, devices and merchants · Data source: ${SOURCE_LABELS[source]}`} />
      <div className="split">
        <div className="grid">
          <section className="panel list-panel list-short" aria-label="Flagged clusters">
            <h2>Flagged clusters</h2>
            {clusters.isPending ? <Spinner /> : clusters.isError ? <ErrorState error={clusters.error} onRetry={() => clusters.refetch()} /> :
              clusters.data.length === 0 ? <EmptyState title="No flagged clusters for this data source" /> : (
                <ul>
                  {clusters.data.map((c) => (
                    <li key={c.cluster_id}>
                      <button className="btn" onClick={() => show({ kind: "cluster", id: c.cluster_id })}>
                        <span title={c.signals.join(", ") || "no signals"}>{c.cluster_id} · {c.n_accounts} accounts · {c.signals.length} signals</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
          </section>
          <form className="panel grid" aria-label="Find an account"
                onSubmit={(e) => { e.preventDefault(); if (account.trim()) show({ kind: "account", id: account.trim(), hours }); }}>
            <h2>Find an account</h2>
            <label>Account id<input value={account} onChange={(e) => setAccount(e.target.value)} /></label>
            <label>Time window (hours)
              <select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
                {HOURS.map((h) => <option key={h} value={h}>{h}</option>)}
              </select>
            </label>
            <div><button className="btn btn-primary" disabled={!account.trim()}>Load account</button></div>
          </form>
        </div>

        <section className="panel" aria-label="Graph">
          {view === null ? <EmptyState title="Choose a cluster or search for an account" hint="Click an account node to expand its neighbours." /> :
            base.isPending ? <Spinner label="Loading graph" /> :
            base.isError ? <ErrorState error={base.error} onRetry={() => base.refetch()} /> :
            graph && graph.nodes.length === 0 ? <EmptyState title="Nothing to show for this selection" /> : graph ? (
              <>
                {graph.truncated ? (
                  <div role="status" className="muted">Graph truncated at 200 nodes. Narrow the time window or open a smaller cluster.</div>
                ) : null}
                {expandError ? <div role="alert" className="muted">{expandError}</div> : null}
                <GraphCanvas graph={graph} onExpand={(id) => void expand(id)} />
              </>
            ) : null}
        </section>
      </div>
    </div>
  );
}
