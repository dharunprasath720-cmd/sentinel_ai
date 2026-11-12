import type { ICellRendererParams } from "ag-grid-community";
import { Link } from "react-router-dom";
import { LEVELS, type Level } from "../../api/types";
import { RiskBadge } from "../RiskBadge";

export const LEVEL_COLOUR: Record<Level, string> = { LOW: "#3ecf8e", MODERATE: "#f5b942", HIGH: "#ff8a4c", CRITICAL: "#ff5d6c" };

/** Sorts risk levels by severity, not alphabetically. */
export const levelComparator = (a: Level | null, b: Level | null) =>
  (a ? LEVELS.indexOf(a) : -1) - (b ? LEVELS.indexOf(b) : -1);

export function TxnLinkCell({ value }: ICellRendererParams<unknown, string>) {
  if (!value) return null;
  return <Link to={`/investigation/${encodeURIComponent(value)}`}>{value}</Link>;
}

export function LevelCell({ value }: ICellRendererParams<unknown, Level | null>) {
  return <RiskBadge level={value ?? null} />;
}

/** A small in-cell bar for a 0 to 1 risk score, coloured by the row's level. */
export function ScoreCell({ value, data }: ICellRendererParams<{ level: Level | null }, number | null>) {
  if (value == null) return <span className="muted">—</span>;
  const colour = data?.level ? LEVEL_COLOUR[data.level] : "#5b9dff";
  return (
    <span className="meter" aria-label={`risk score ${value.toFixed(2)}`}>
      <span className="meter-track"><span className="meter-fill" style={{ width: `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%`, background: colour }} /></span>
      <span className="meter-num">{value.toFixed(2)}</span>
    </span>
  );
}
