import type { ReactNode } from "react";

export function MetricTile({ label, value, hint, tooltip }: { label: string; value: ReactNode; hint?: string; tooltip?: string }) {
  return (
    <div className="panel tile" title={tooltip}>
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {hint ? <div className="tile-hint">{hint}</div> : null}
    </div>
  );
}
