export function inr(v: number | null | undefined, opts: { compact?: boolean; decimals?: number } = {}): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  const { compact = false, decimals = 0 } = opts;
  const abs = Math.abs(v);
  if (compact) {
    if (abs >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
    if (abs >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
    if (abs >= 1e3) return `₹${(v / 1e3).toFixed(1)} K`;
  }
  return "₹" + v.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
export const num = (v: number) => v.toLocaleString("en-IN");
export const pct = (v: number, d = 1) => `${v.toFixed(d)}%`;
export function fmtValue(v: number, unit: "inr" | "pct" | "count", compact = true): string {
  return unit === "inr" ? inr(v, { compact }) : unit === "pct" ? pct(v) : num(v);
}
export function monthLabel(m: string): string {
  const [y, mo] = m.split("-").map(Number);
  return new Date(y, mo - 1, 1).toLocaleString("en-IN", { month: "short", year: "numeric" });
}
export const shortMonth = (m: string) => new Date(Number(m.slice(0, 4)), Number(m.slice(5)) - 1, 1).toLocaleString("en-IN", { month: "short" });
export const MATCH_LABEL: Record<string, string> = { matched: "Matched", amount_mismatch: "Amount mismatch", missing_in_2b: "Missing in 2B", missing_in_books: "Missing in books" };
export const STATUS_LABEL: Record<string, string> = { eligible: "Eligible", at_risk: "At risk", blocked: "Blocked" };
