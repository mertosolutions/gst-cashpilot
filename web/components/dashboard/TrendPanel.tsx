"use client";
import { useState } from "react";
import { Area, Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, ErrorBox, Segmented, Skeleton } from "@/components/ui";
import { inr, pct, shortMonth } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { MonthMetrics } from "@/lib/types";

type View = "spend" | "cash" | "itc" | "match";
const VIEWS: { value: View; label: string }[] = [
  { value: "spend", label: "Spend" }, { value: "cash", label: "Cash & tax" }, { value: "itc", label: "ITC mix" }, { value: "match", label: "Match quality" },
];
const C = { blue: "#1a73e8", green: "#34a853", amber: "#f9ab00", red: "#ea4335", violet: "#9334e6", slate: "#9aa0a6" };

function money(v: number | string) { const n = Number(v); return n >= 1e5 ? `₹${+(n / 1e5).toFixed(1)}L` : n >= 1e3 ? `₹${Math.round(n / 1e3)}K` : `₹${n}`; }
function Tip({ active, payload, label, unitPct }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string; unitPct?: boolean }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-pop text-xs">
      <p className="font-semibold mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.name} className="flex items-center gap-2"><span className="h-2 w-2 rounded-full" style={{ background: p.color }} />{p.name}<b className="ml-auto pl-4">{unitPct && p.name.includes("rate") ? pct(p.value) : p.name.includes("nvoice") || p.name.match(/^(Matched|Amount|Missing)/) ? p.value : inr(p.value, { decimals: 0 })}</b></p>
      ))}
    </div>
  );
}

const KPI_TO_VIEW: Record<string, View> = { purchase_total: "spend", invoices: "spend", output_tax: "cash", cash_safe: "cash", cash_full: "cash", eligible: "itc", at_risk: "itc", blocked: "itc", match_rate: "match", flagged: "match" };
export const viewForKpi = (k: string): View => KPI_TO_VIEW[k] ?? "spend";

export default function TrendPanel({ focus }: { focus: string }) {
  const [view, setView] = useState<View>(viewForKpi(focus));
  const [range, setRange] = useState(6);
  const [lastFocus, setLastFocus] = useState(focus);
  if (focus !== lastFocus) { setLastFocus(focus); setView(viewForKpi(focus)); }
  const { data, error, reload } = useApi<MonthMetrics[]>("/dashboard/trends", { months: range });
  const rows = (data ?? []).map((m) => ({ ...m, name: shortMonth(m.month) }));
  const axis = { tick: { fill: "#6b7280", fontSize: 11 }, tickLine: false, axisLine: false } as const;

  return (
    <Card title="Trends and detailed analysis" subtitle="Click a card above to jump to its view"
      action={<div className="flex flex-wrap items-center gap-2 justify-end"><Segmented value={view} onChange={setView} options={VIEWS} /><Segmented value={range} onChange={setRange} options={[{ value: 3, label: "3M" }, { value: 6, label: "6M" }]} /></div>}>
      {error ? <ErrorBox message={error} onRetry={reload} /> : !data ? <Skeleton className="h-72" /> : rows.length < 2 ? <p className="text-sm text-ink-500 py-10 text-center">Trends need at least two months of data.</p> : (
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            {view === "spend" ? (
              <ComposedChart data={rows} margin={{ left: 0, right: 8, top: 8 }}>
                <CartesianGrid vertical={false} stroke="#eef2f7" /><XAxis dataKey="name" {...axis} /><YAxis yAxisId="l" tickFormatter={money} width={64} {...axis} /><YAxis yAxisId="r" orientation="right" width={36} {...axis} />
                <Tooltip content={<Tip />} /><Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                <Bar isAnimationActive={false} yAxisId="l" dataKey="purchase_taxable" name="Purchases (taxable)" stackId="a" fill={C.blue} radius={[0, 0, 0, 0]} />
                <Bar isAnimationActive={false} yAxisId="l" dataKey="purchase_tax" name="GST paid on purchases" stackId="a" fill="#aecbfa" radius={[6, 6, 0, 0]} />
                <Line isAnimationActive={false} yAxisId="r" dataKey="invoices" name="Invoices" stroke={C.violet} strokeWidth={2} dot />
              </ComposedChart>
            ) : view === "cash" ? (
              <ComposedChart data={rows} margin={{ left: 0, right: 8, top: 8 }}>
                <CartesianGrid vertical={false} stroke="#eef2f7" /><XAxis dataKey="name" {...axis} /><YAxis tickFormatter={money} width={64} {...axis} />
                <Tooltip content={<Tip />} /><Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                <Area isAnimationActive={false} dataKey="output_tax" name="Output tax" fill="#d2e3fc" stroke={C.blue} strokeWidth={2} />
                <Line isAnimationActive={false} dataKey="eligible" name="ITC eligible" stroke={C.green} strokeWidth={2.5} dot />
                <Line isAnimationActive={false} dataKey="cash_safe" name="Cash payable (safe)" stroke={C.red} strokeWidth={2.5} dot />
                <Line isAnimationActive={false} dataKey="cash_full" name="Cash if at-risk claimed" stroke={C.amber} strokeWidth={2} strokeDasharray="5 4" dot />
              </ComposedChart>
            ) : view === "itc" ? (
              <ComposedChart data={rows} margin={{ left: 0, right: 8, top: 8 }}>
                <CartesianGrid vertical={false} stroke="#eef2f7" /><XAxis dataKey="name" {...axis} /><YAxis tickFormatter={money} width={64} {...axis} />
                <Tooltip content={<Tip />} /><Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                <Bar isAnimationActive={false} dataKey="eligible" name="Eligible" stackId="i" fill={C.green} />
                <Bar isAnimationActive={false} dataKey="at_risk" name="At risk" stackId="i" fill={C.amber} />
                <Bar isAnimationActive={false} dataKey="blocked" name="Blocked" stackId="i" fill={C.red} radius={[6, 6, 0, 0]} />
              </ComposedChart>
            ) : (
              <ComposedChart data={rows} margin={{ left: 0, right: 8, top: 8 }}>
                <CartesianGrid vertical={false} stroke="#eef2f7" /><XAxis dataKey="name" {...axis} /><YAxis yAxisId="l" width={36} {...axis} /><YAxis yAxisId="r" orientation="right" unit="%" domain={[0, 100]} width={44} {...axis} />
                <Tooltip content={<Tip unitPct />} /><Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                <Bar isAnimationActive={false} yAxisId="l" dataKey="matched" name="Matched" stackId="m" fill={C.green} />
                <Bar isAnimationActive={false} yAxisId="l" dataKey="amount_mismatch" name="Amount mismatch" stackId="m" fill={C.amber} />
                <Bar isAnimationActive={false} yAxisId="l" dataKey="missing_in_2b" name="Missing in 2B" stackId="m" fill={C.red} />
                <Bar isAnimationActive={false} yAxisId="l" dataKey="missing_in_books" name="Missing in books" stackId="m" fill={C.blue} radius={[6, 6, 0, 0]} />
                <Line isAnimationActive={false} yAxisId="r" dataKey="match_rate" name="Match rate" stroke={C.violet} strokeWidth={2.5} dot />
              </ComposedChart>
            )}
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
