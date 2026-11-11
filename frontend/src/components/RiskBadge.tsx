import type { Level } from "../api/types";

/** Colour is never the only signal: the level name is always printed. */
export function RiskBadge({ level }: { level: Level | null }) {
  if (!level) return <span className="badge badge-none">—</span>;
  return <span className={`badge badge-${level.toLowerCase()}`}>{level}</span>;
}
