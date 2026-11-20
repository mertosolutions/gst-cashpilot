"use client";
import { clsx } from "clsx";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";
import { Card, Delta, ErrorBox, LayerChip, Skeleton } from "@/components/ui";
import { fmtValue, inr } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { DashboardSummary, Kpi } from "@/lib/types";

const TONE: Record<string, string> = { at_risk: "#f9ab00", blocked: "#ea4335", eligible: "#34a853", cash_safe: "#1a73e8" };

function KpiCard({ k, hero, active, onPick }: { k: Kpi; hero?: boolean; active: boolean; onPick: () => void }) {
  const color = hero ? "#ffffff" : TONE[k.key] ?? "#4285f4";
  return (
    <button onClick={onPick} title={k.unit === "inr" ? `${inr(k.value, { decimals: 2 })} · ${k.hint}` : k.hint}
      className={clsx("card text-left p-4 transition hover:shadow-pop focus:outline-none focus:ring-2 focus:ring-brand-500/50 relative overflow-hidden",
        hero && "!bg-gradient-to-br from-brand-600 to-brand-700 !border-brand-700 text-white", active && !hero && "ring-2 ring-brand-500/60")}>
      <div className="flex items-start justify-between gap-2">
        <span className={clsx("text-[12px] font-medium", hero ? "text-white/85" : "text-ink-500")}>{k.label}</span>
        {hero ? <span className="chip bg-white/15 text-white"><b>L{1}</b></span> : <LayerChip name={k.layer} compact />}
      </div>
      <div className={clsx("mt-1.5 text-[26px] leading-8 font-semibold tracking-tight", hero ? "text-white" : "text-ink-900")}>{fmtValue(k.value, k.unit)}</div>
      <div className="mt-1 flex items-center gap-2">
        {hero ? (
          <span className="chip bg-white/15 text-white">{k.delta_pct === null ? "no prior month" : `${k.delta_pct >= 0 ? "▲" : "▼"} ${Math.abs(k.delta_pct)}% vs last month`}</span>
        ) : (<><Delta pct={k.delta_pct} good={k.good_when} /><span className="text-[11px] text-ink-300">vs last month</span></>)}
      </div>
      <div className="mt-2 h-9 -mx-1">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={k.series} margin={{ top: 4, bottom: 2, left: 4, right: 4 }}>
            <YAxis hide domain={["dataMin", "dataMax"]} />
            <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </button>
  );
}

export default function KpiGrid({ active, onPick }: { active: string; onPick: (key: string) => void }) {
  const { data, error, loading, reload } = useApi<DashboardSummary>("/dashboard/summary");
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4">{Array.from({ length: 10 }).map((_, i) => <Skeleton key={i} className="h-36" />)}</div>;
  return (
    <div className={clsx("grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4 transition-opacity", loading && "opacity-60")}>
      {data.kpis.map((k, i) => <KpiCard key={k.key} k={k} hero={i === 0} active={active === k.key} onPick={() => onPick(k.key)} />)}
    </div>
  );
}
