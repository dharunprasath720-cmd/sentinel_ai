import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { LEVELS, type Level, type ModelsSummary, type Overview as OverviewData, type TxnListItem } from "../api/types";
import { useSession } from "../auth/session";
import { CountUp } from "../components/CountUp";
import { MetricTile } from "../components/MetricTile";
import { PageHeader } from "../components/PageHeader";
import { RiskBadge } from "../components/RiskBadge";
import { EmptyState, ErrorState, Spinner } from "../components/states";
import { fmt3, fmtInt, fmtMoney, fmtTime } from "../format";
import { SOURCE_LABELS, useSource } from "../source";

const LEVEL_COLOUR: Record<Level, string> = { LOW: "#3ecf8e", MODERATE: "#f5b942", HIGH: "#ff8a4c", CRITICAL: "#ff5d6c" };
type Scale = "log" | "linear";

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

function RecentTransactions({ level }: { level: Level | null }) {
  const { client } = useSession();
  const { source } = useSource();
  const q = useQuery({
    queryKey: ["recent-transactions", source, level],
    queryFn: async () => {
      if (level) return client.get<TxnListItem[]>("/transactions", { source, level, limit: 10 });
      const [crit, high] = await Promise.all(
        (["CRITICAL", "HIGH"] as const).map((l) =>
          client.get<TxnListItem[]>("/transactions", { source, level: l, limit: 10 })));
      return [...crit, ...high].sort((a, b) => b.ts.localeCompare(a.ts)).slice(0, 10);
    },
  });
  const title = level ? `Recent ${level} transactions` : "Recent HIGH and CRITICAL transactions";
  return (
    <section className="panel" aria-label="Recent transactions">
      <h2>{title}</h2>
      {q.isPending ? <Spinner /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> :
        q.data.length === 0 ? <EmptyState title={level ? `Nothing rated ${level} for this data source` : "Nothing rated HIGH or CRITICAL for this data source"} /> : (
          <div className="table-scroll short"><table>
            <thead><tr><th>Transaction</th><th>Time</th><th>Amount</th><th>Level</th></tr></thead>
            <tbody>
              {q.data.map((t) => (
                <tr key={t.external_id}>
                  <td><Link to={`/investigation/${encodeURIComponent(t.external_id)}`}>{t.external_id}</Link></td>
                  <td>{fmtTime(t.ts)}</td><td>{fmtMoney(t.amount)}</td><td><RiskBadge level={t.risk_level} /></td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
    </section>
  );
}

export function Overview() {
  const { client } = useSession();
  const { source } = useSource();
  const [scale, setScale] = useState<Scale>("log");
  const [level, setLevel] = useState<Level | null>(null);
  const q = useQuery({
    queryKey: ["overview", source],
    queryFn: () => client.get<OverviewData>("/metrics/overview", { source }),
  });
  const toggleLevel = (l: Level) => setLevel((cur) => (cur === l ? null : l));

  return (
    <div className="grid">
      <PageHeader title="Overview" subtitle={`Portfolio health at a glance · Data source: ${SOURCE_LABELS[source]}`} />
      {q.isPending ? <Spinner /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : (
        <>
          <div className="grid grid-5">
            <MetricTile label="Transactions" value={<CountUp value={q.data.transactions.total} format={fmtInt} />} />
            <MetricTile label="Open alerts" value={<CountUp value={q.data.open_alerts} format={fmtInt} />} />
            <MetricTile label="Open cases" value={<CountUp value={q.data.open_cases} format={fmtInt} />} />
            <MetricTile label="Flagged clusters" value={<CountUp value={q.data.flagged_clusters} format={fmtInt} />} />
            <MetricTile label="Suspicious value" value={<CountUp value={q.data.suspicious_value} format={fmtMoney} />}
              hint="Suspicious, not confirmed fraud" tooltip="Amounts of HIGH and CRITICAL transactions. Suspicious, not confirmed fraud." />
          </div>
          {q.data.transactions.total === 0 ? (
            <EmptyState title="No transactions for this data source yet"
              hint="Pick another data source, or start the simulator on Live Monitoring." />
          ) : (
            <div className="grid grid-2">
              <section className="panel" aria-label="Risk level distribution">
                <div className="row spread">
                  <h2>Risk level distribution</h2>
                  <div className="row" role="group" aria-label="Chart scale">
                    {(["log", "linear"] as const).map((s) => (
                      <button key={s} className={`btn btn-small${scale === s ? " btn-active" : ""}`}
                              aria-label={s === "log" ? "Log scale" : "Linear scale"} aria-pressed={scale === s}
                              onClick={() => setScale(s)}>{s === "log" ? "Log" : "Linear"}</button>
                    ))}
                  </div>
                </div>
                <div className="row" role="group" aria-label="Filter by risk level">
                  {LEVELS.map((l) => (
                    <button key={l} className={`level-chip${level === l ? " selected" : ""}`} aria-pressed={level === l}
                            style={{ borderColor: LEVEL_COLOUR[l] }} onClick={() => toggleLevel(l)}>
                      <span className="swatch" style={{ background: LEVEL_COLOUR[l] }} aria-hidden /> {l} {fmtInt(q.data.transactions.by_level[l])}
                    </button>
                  ))}
                </div>
                <div className="muted small">
                  {scale === "log" ? "Log scale keeps small groups visible. " : ""}Click a level to filter the list below.
                </div>
                <ResponsiveContainer width="100%" height={150}>
                  <BarChart data={LEVELS.map((l) => ({ level: l, count: q.data.transactions.by_level[l] || undefined }))}
                            margin={{ top: 18 }}>
                    <CartesianGrid stroke="#243252" /><XAxis dataKey="level" stroke="#94a3c0" />
                    <YAxis stroke="#94a3c0" scale={scale} domain={scale === "log" ? [1, "dataMax"] : [0, "dataMax"]} allowDataOverflow />
                    <Tooltip />
                    <Bar dataKey="count" cursor="pointer" onClick={(d: unknown) => toggleLevel((d as { level: Level }).level)}>
                      {LEVELS.map((l) => <Cell key={l} fill={LEVEL_COLOUR[l]} fillOpacity={level && level !== l ? 0.3 : 1} />)}
                      <LabelList dataKey="count" position="top" fill="#e8edf7" formatter={(v: unknown) => fmtInt(Number(v))} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </section>
              <section className="panel" aria-label="Daily volume">
                <h2>Daily volume and HIGH+ count</h2>
                <ul className="legend" aria-label="Daily chart legend">
                  <li><span className="swatch" style={{ background: "#38bdf8" }} aria-hidden /> All transactions</li>
                  <li><span className="swatch" style={{ background: "#ff5d6c" }} aria-hidden /> HIGH + CRITICAL</li>
                </ul>
                <ResponsiveContainer width="100%" height={165}>
                  <LineChart data={q.data.daily}>
                    <CartesianGrid stroke="#243252" /><XAxis dataKey="date" stroke="#94a3c0" />
                    <YAxis stroke="#94a3c0" /><Tooltip />
                    <Line dataKey="transactions" name="All transactions" stroke="#38bdf8" dot={false} />
                    <Line dataKey="high_plus" name="HIGH + CRITICAL" stroke="#ff5d6c" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
                <div className="muted small">The last day may be partial, so its drop is not a real fall in volume.</div>
              </section>
            </div>
          )}
        </>
      )}
      <div className="grid grid-2"><ModelPanel /><RecentTransactions level={level} /></div>
    </div>
  );
}
