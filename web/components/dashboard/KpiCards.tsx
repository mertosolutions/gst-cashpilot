"use client";
import { useEffect, useState } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChevronDown } from "lucide-react";
import { Delta, ErrorBox, LayerChip, Skeleton } from "@/components/ui";
import { fmtValue, inr } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { DashboardSummary, Kpi } from "@/lib/types";

const DEFAULTS = ["purchase_total", "cash_safe"];
const TONE: Record<string, string> = { at_risk: "#f9ab00", blocked: "#ea4335", eligible: "#34a853", cash_safe: "#1a73e8", cash_full: "#1a73e8" };

function KpiCard({ k, all, onPick, hero }: { k: Kpi; all: Kpi[]; onPick: (key: string) => void; hero?: boolean }) {
  const color = hero ? "#ffffff" : TONE[k.key] ?? "#4285f4";
  return (
    <div className={hero ? "card p-5 !bg-gradient-to-br from-brand-600 to-brand-700 !border-brand-700 text-white" : "card p-5"}>
      <div className="flex items-center justify-between gap-3">
        <label className="relative inline-flex items-center">
          <span className="sr-only">Choose the number to show</span>
          <select value={k.key} onChange={(e) => onPick(e.target.value)}
            className={`appearance-none cursor-pointer rounded-lg bg-transparent py-1 pl-0 pr-6 text-[13px] font-medium focus:outline-none focus:ring-2 focus:ring-brand-500/40 ${hero ? "text-white [&>option]:text-ink-900" : "text-ink-700"}`}>
            {all.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
          </select>
          <ChevronDown size={14} className={`pointer-events-none absolute right-0 ${hero ? "text-white/80" : "text-ink-500"}`} />
        </label>
        {hero ? <span className="chip bg-white/15 text-white"><b>L1</b></span> : <LayerChip name={k.layer} compact />}
      </div>
      <div className="mt-2 flex items-end justify-between gap-4">
        <div>
          <div className={`text-4xl font-semibold tracking-tight ${hero ? "text-white" : "text-ink-900"}`} title={k.unit === "inr" ? inr(k.value, { decimals: 2 }) : undefined}>{fmtValue(k.value, k.unit)}</div>
          <div className="mt-1.5 flex items-center gap-2">
            {hero ? <span className="chip bg-white/15 text-white">{k.delta_pct === null ? "no prior month" : `${k.delta_pct >= 0 ? "▲" : "▼"} ${Math.abs(k.delta_pct)}% vs last month`}</span>
              : <><Delta pct={k.delta_pct} good={k.good_when} /><span className="text-[11px] text-ink-300">vs last month</span></>}
          </div>
        </div>
        <div className="h-16 w-40 shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={k.series} margin={{ top: 4, bottom: 0, left: 0, right: 0 }}>
              <defs><linearGradient id={`g-${k.key}-${hero ? 1 : 0}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={0.35} /><stop offset="100%" stopColor={color} stopOpacity={0} /></linearGradient></defs>
              <XAxis dataKey="label" hide /><YAxis hide domain={["dataMin", "dataMax"]} />
              <Tooltip cursor={false} contentStyle={{ fontSize: 11, borderRadius: 10 }} labelFormatter={(l) => String(l)} formatter={(v) => [fmtValue(Number(v), k.unit, false), k.label]} />
              <Area type="monotone" dataKey="value" stroke={color} strokeWidth={2} fill={`url(#g-${k.key}-${hero ? 1 : 0})`} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
      <p className={`mt-2 text-xs ${hero ? "text-white/75" : "text-ink-500"}`}>{k.hint}</p>
    </div>
  );
}

/** Two cards. Each has a drop-down to choose which number it shows; the choice is remembered. */
export default function KpiCards() {
  const { data, error, reload } = useApi<DashboardSummary>("/dashboard/summary");
  const [keys, setKeys] = useState<string[]>(DEFAULTS);
  useEffect(() => { try { const s = JSON.parse(localStorage.getItem("cashpilot.kpis") || "null"); if (Array.isArray(s) && s.length === 2) setKeys(s); } catch { /* ignore */ } }, []);
  const pick = (i: number, key: string) => setKeys((cur) => { const n = [...cur]; n[i] = key; try { localStorage.setItem("cashpilot.kpis", JSON.stringify(n)); } catch { /* ignore */ } return n; });
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <div className="grid md:grid-cols-2 gap-4"><Skeleton className="h-44" /><Skeleton className="h-44" /></div>;
  const find = (k: string) => data.kpis.find((x) => x.key === k) ?? data.kpis[0];
  return (
    <div className="grid md:grid-cols-2 gap-4">
      {keys.map((k, i) => <KpiCard key={i} k={find(k)} all={data.kpis} onPick={(v) => pick(i, v)} hero={i === 0} />)}
    </div>
  );
}
