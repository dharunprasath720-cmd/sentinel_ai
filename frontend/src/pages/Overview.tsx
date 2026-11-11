import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { LEVELS, type ModelsSummary, type Overview as OverviewData, type TxnListItem } from "../api/types";
import { useSession } from "../auth/session";
import { MetricTile } from "../components/MetricTile";
import { RiskBadge } from "../components/RiskBadge";
import { EmptyState, ErrorState, Spinner } from "../components/states";
import { fmt3, fmtInt, fmtMoney, fmtTime } from "../format";
import { SOURCE_LABELS, useSource } from "../source";

function ModelPanel() {
  const { client } = useSession();
  const q = useQuery({ queryKey: ["models"], queryFn: () => client.get<ModelsSummary>("/metrics/models") });
  return (
    <section className="panel" aria-label="Model quality">
      <h2>Model quality</h2>
      {q.isPending ? <Spinner /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : (
        <>
          <div className="muted">Version {q.data.version} · {q.data.evaluation}</div>
          <table>
            <thead><tr><th>Model</th><th>PR-AUC</th><th>Recall</th><th>Precision</th></tr></thead>
            <tbody>
              {Object.entries(q.data.models).map(([name, m]) => (
                <tr key={name}><td>{name}</td><td>{fmt3(m.pr_auc)}</td><td>{fmt3(m.recall)}</td><td>{fmt3(m.precision)}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="muted">{q.data.caveat}</p>
        </>
      )}
    </section>
  );
}

function RecentHighRisk() {
  const { client } = useSession();
  const { source } = useSource();
  const q = useQuery({
    queryKey: ["recent-high-plus", source],
    queryFn: async () => {
      const [crit, high] = await Promise.all(
        (["CRITICAL", "HIGH"] as const).map((level) =>
          client.get<TxnListItem[]>("/transactions", { source, level, limit: 10 })));
      return [...crit, ...high].sort((a, b) => b.ts.localeCompare(a.ts)).slice(0, 10);
    },
  });
  return (
    <section className="panel" aria-label="Recent high-risk transactions">
      <h2>Recent HIGH and CRITICAL transactions</h2>
      {q.isPending ? <Spinner /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> :
        q.data.length === 0 ? <EmptyState title="Nothing rated HIGH or CRITICAL for this data source" /> : (
          <table>
            <thead><tr><th>Transaction</th><th>Time</th><th>Amount</th><th>Level</th></tr></thead>
            <tbody>
              {q.data.map((t) => (
                <tr key={t.external_id}>
                  <td><Link to={`/investigation/${encodeURIComponent(t.external_id)}`}>{t.external_id}</Link></td>
                  <td>{fmtTime(t.ts)}</td><td>{fmtMoney(t.amount)}</td><td><RiskBadge level={t.risk_level} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </section>
  );
}

export function Overview() {
  const { client } = useSession();
  const { source } = useSource();
  const q = useQuery({
    queryKey: ["overview", source],
    queryFn: () => client.get<OverviewData>("/metrics/overview", { source }),
  });

  return (
    <div className="grid">
      <div><h1>Overview</h1><div className="muted">Data source: {SOURCE_LABELS[source]}</div></div>
      {q.isPending ? <Spinner /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : (
        <>
          <div className="grid grid-5">
            <MetricTile label="Transactions" value={fmtInt(q.data.transactions.total)} />
            <MetricTile label="Open alerts" value={fmtInt(q.data.open_alerts)} />
            <MetricTile label="Open cases" value={fmtInt(q.data.open_cases)} />
            <MetricTile label="Flagged clusters" value={fmtInt(q.data.flagged_clusters)} />
            <MetricTile label="Suspicious value" value={fmtMoney(q.data.suspicious_value)}
              hint="Amounts of HIGH and CRITICAL transactions. Suspicious, not confirmed fraud." />
          </div>
          {q.data.transactions.total === 0 ? (
            <EmptyState title="No transactions for this data source yet"
              hint="Pick another data source, or start the simulator on Live Monitoring." />
          ) : (
            <div className="grid grid-2">
              <section className="panel" aria-label="Risk level distribution">
                <h2>Risk level distribution</h2>
                <div className="row muted">
                  {LEVELS.map((l) => <span key={l}>{l} {fmtInt(q.data.transactions.by_level[l])}</span>)}
                </div>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={LEVELS.map((l) => ({ level: l, count: q.data.transactions.by_level[l] }))}>
                    <CartesianGrid stroke="#243252" /><XAxis dataKey="level" stroke="#94a3c0" />
                    <YAxis stroke="#94a3c0" /><Tooltip /><Bar dataKey="count" fill="#6aa5ff" />
                  </BarChart>
                </ResponsiveContainer>
              </section>
              <section className="panel" aria-label="Daily volume">
                <h2>Daily volume and HIGH+ count</h2>
                <ResponsiveContainer width="100%" height={250}>
                  <LineChart data={q.data.daily}>
                    <CartesianGrid stroke="#243252" /><XAxis dataKey="date" stroke="#94a3c0" />
                    <YAxis stroke="#94a3c0" /><Tooltip />
                    <Line dataKey="transactions" stroke="#6aa5ff" dot={false} />
                    <Line dataKey="high_plus" stroke="#ff5d6c" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </section>
            </div>
          )}
        </>
      )}
      <div className="grid grid-2"><ModelPanel /><RecentHighRisk /></div>
    </div>
  );
}
