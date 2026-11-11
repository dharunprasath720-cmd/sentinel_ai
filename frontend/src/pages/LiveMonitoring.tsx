import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { HIGH_PLUS, type Action, type Level, type LiveMetrics, type TxnListItem } from "../api/types";
import { canAct } from "../auth/roles";
import { useSession } from "../auth/session";
import { MetricTile } from "../components/MetricTile";
import { RiskBadge } from "../components/RiskBadge";
import { EmptyState, ErrorState, Spinner } from "../components/states";
import { fmtInt, fmtMoney, fmtMs, fmtTime } from "../format";
import { useLiveStream, type StreamState } from "../live/useLiveStream";
import { SOURCE_LABELS, useSource } from "../source";

interface Row {
  id: string; ts: string; account: string; amount: number; level: Level | null;
  action: Action | null; cluster: string | null;
}

const STATE_TEXT: Record<StreamState, string> = {
  connecting: "Connecting", open: "Connected", reconnecting: "Reconnecting", closed: "Disconnected",
};

function SimulatorPanel() {
  const { client, role } = useSession();
  const [speed, setSpeed] = useState("10");
  const [limit, setLimit] = useState("200");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!canAct(role)) {
    return <section className="panel" aria-label="Simulator">
      <h2>Replay simulator</h2>
      <div className="muted">Simulator controls are available to analysts and admins.</div>
    </section>;
  }

  async function call(path: string, body?: unknown) {
    setBusy(true);
    try { await client.post(path, body); setMessage(null); }
    catch (err) {
      setMessage(err instanceof ApiError && err.status === 409
        ? "A replay is already running. Stop it first."
        : err instanceof ApiError ? err.detail : "The request failed");
    } finally { setBusy(false); }
  }
  function start() {
    const s = Number(speed), l = Number(limit);
    if (!(Number.isFinite(s) && s > 0 && s <= 1000)) return setMessage("Speed must be between 0 and 1000 events per second");
    if (!(Number.isInteger(l) && l >= 1 && l <= 100000)) return setMessage("Limit must be a whole number from 1 to 100000");
    void call("/simulate/start", { speed: s, limit: l });
  }

  return (
    <section className="panel" aria-label="Simulator">
      <h2>Replay simulator</h2>
      <div className="row">
        <label>Speed (events per second) <input value={speed} onChange={(e) => setSpeed(e.target.value)} size={6} /></label>
        <label>Limit (events) <input value={limit} onChange={(e) => setLimit(e.target.value)} size={8} /></label>
        <button className="btn btn-primary" disabled={busy} onClick={start}>Start replay</button>
        <button className="btn" disabled={busy} onClick={() => void call("/simulate/stop")}>Stop replay</button>
      </div>
      {message ? <div role="alert" className="muted">{message}</div> : null}
    </section>
  );
}

export function LiveMonitoring({ streamFetch }: { streamFetch?: typeof fetch }) {
  const { client, token, logout } = useSession();
  const { source } = useSource();
  const navigate = useNavigate();
  const stream = useLiveStream({ token, onUnauthorized: logout, fetchImpl: streamFetch });

  const initial = useQuery({
    queryKey: ["live-initial", source],
    queryFn: () => client.get<TxnListItem[]>("/transactions", { source, limit: 50 }),
  });
  const metrics = useQuery({
    queryKey: ["live-metrics"], refetchInterval: 2000,
    queryFn: () => client.get<LiveMetrics>("/metrics/live"),
  });

  const rows = useMemo<Row[]>(() => {
    const fromLive: Row[] = stream.events
      .filter((e) => (e.source ?? "synthetic") === source)
      .map((e) => ({ id: e.external_id, ts: e.ts, account: e.account_id, amount: e.amount,
                     level: e.risk_level, action: e.recommended_action, cluster: e.cluster_id }));
    const seen = new Set(fromLive.map((r) => r.id));
    const fromDb: Row[] = (initial.data ?? []).filter((t) => !seen.has(t.external_id))
      .map((t) => ({ id: t.external_id, ts: t.ts, account: t.account_id, amount: t.amount,
                     level: t.risk_level, action: t.action, cluster: t.cluster_id }));
    return [...fromLive, ...fromDb].slice(0, 200);
  }, [stream.events, initial.data, source]);

  const m = metrics.data;
  return (
    <div className="grid">
      <div>
        <h1>Live Monitoring</h1>
        <div className="muted">Data source: {SOURCE_LABELS[source]}</div>
      </div>
      <div className="row">
        <span className="pill">{STATE_TEXT[stream.state]}</span>
        <button className="btn" onClick={() => stream.setPaused(!stream.paused)}>{stream.paused ? "Resume" : "Pause"}</button>
        {stream.paused ? <span className="muted">Paused: new events are not shown</span> : null}
      </div>

      <h2>Live counters (all data sources)</h2>
      {metrics.isError ? <ErrorState error={metrics.error} /> : (
        <div className="grid grid-5">
          <MetricTile label="Processed" value={m ? fmtInt(m.processed) : "—"} />
          <MetricTile label="Alerts" value={m ? fmtInt(m.alerts) : "—"} />
          <MetricTile label="Latency p50" value={fmtMs(m?.p50_ms)} />
          <MetricTile label="Latency p95" value={fmtMs(m?.p95_ms)} />
          <MetricTile label="Dropped events" value={m ? fmtInt(m.dropped) : "—"} />
          <MetricTile label="Replay" value={m ? (m.simulator.running ? "Replay running" : "Replay idle") : "—"}
            hint={m ? `${fmtInt(m.simulator.sent)} sent · ${fmtInt(m.simulator.errors)} errors` : undefined} />
        </div>
      )}

      <SimulatorPanel />

      <section className="panel" aria-label="Scored events">
        <h2>Scored events</h2>
        {initial.isPending ? <Spinner /> : initial.isError ? <ErrorState error={initial.error} onRetry={() => initial.refetch()} /> :
          rows.length === 0 ? <EmptyState title="No events yet for this data source" hint="Start the replay simulator to stream scored events." /> : (
            <table>
              <thead><tr><th>Transaction</th><th>Time</th><th>Account</th><th>Amount</th><th>Level</th><th>Action</th><th>Cluster</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={`clickable${r.level && HIGH_PLUS.includes(r.level) ? " row-high-plus" : ""}`}
                      onClick={(e) => { if (!(e.target as HTMLElement).closest("a")) navigate(`/investigation/${encodeURIComponent(r.id)}`); }}>
                    <td><Link to={`/investigation/${encodeURIComponent(r.id)}`}>{r.id}</Link></td>
                    <td>{fmtTime(r.ts)}</td><td>{r.account}</td><td>{fmtMoney(r.amount)}</td>
                    <td><RiskBadge level={r.level} /></td>
                    <td>{r.action === "HOLD_RECOMMENDED" ? "Hold recommended" : (r.action ?? "—")}</td>
                    <td>{r.cluster ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </section>
    </div>
  );
}
