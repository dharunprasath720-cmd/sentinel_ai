const int = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export const fmtInt = (n: number) => int.format(n);
export const fmtMoney = (n: number) => money.format(n);
/** Three decimals, or an em dash when the metric is missing (never "NaN"). */
export const fmt3 = (n: number | null | undefined) => (n == null || Number.isNaN(n) ? "—" : n.toFixed(3));
export const fmtTime = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("en-GB", { hour12: false });
};

export const ACTION_LABELS: Record<string, string> = {
  ALLOW: "Allow", MONITOR: "Monitor", REVIEW: "Review", VERIFY: "Verify", HOLD_RECOMMENDED: "Hold recommended",
};
export const actionLabel = (a: string) => ACTION_LABELS[a] ?? a;
