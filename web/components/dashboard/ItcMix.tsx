"use client";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { Card, LayerChip, Skeleton } from "@/components/ui";
import { inr, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { DashboardSummary } from "@/lib/types";

export default function ItcMix() {
  const { data } = useApi<DashboardSummary>("/dashboard/summary");
  const c = data?.current;
  const parts = c ? [
    { name: "Eligible", value: c.eligible, color: "#34a853", note: "Safe to claim" },
    { name: "At risk", value: c.at_risk, color: "#f9ab00", note: "Not confirmed in GSTR-2B" },
    { name: "Blocked", value: c.blocked, color: "#ea4335", note: "Cannot be claimed" },
  ] : [];
  const total = parts.reduce((s, p) => s + p.value, 0);
  return (
    <Card title="ITC composition" subtitle="Where your input credit stands" action={<LayerChip name="ITC decision" />}>
      {!c ? <Skeleton className="h-64" /> : (
        <>
          <div className="relative h-44">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart><Pie data={parts} dataKey="value" innerRadius={56} outerRadius={78} paddingAngle={3} stroke="none" isAnimationActive={false}>{parts.map((p) => <Cell key={p.name} fill={p.color} />)}</Pie></PieChart>
            </ResponsiveContainer>
            <div className="absolute inset-0 grid place-items-center pointer-events-none"><div className="text-center"><div className="text-[11px] text-ink-500">Total ITC</div><div className="text-lg font-semibold">{inr(total, { compact: true })}</div></div></div>
          </div>
          <ul className="mt-2 space-y-2">
            {parts.map((p) => (
              <li key={p.name} className="flex items-center gap-2 text-sm">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: p.color }} /><span className="font-medium">{p.name}</span><span className="text-xs text-ink-500 hidden sm:inline">{p.note}</span>
                <span className="ml-auto text-right"><b>{inr(p.value, { compact: true })}</b> <span className="text-xs text-ink-500">{total ? pct((p.value / total) * 100, 0) : "0%"}</span></span>
              </li>
            ))}
          </ul>
          <div className="mt-4 rounded-xl bg-slate-50 p-3 text-xs text-ink-700">
            <div className="flex justify-between"><span>Cash payable (safe)</span><b>{inr(c.cash_safe)}</b></div>
            <div className="flex justify-between mt-1"><span>If at-risk is claimed</span><b>{inr(c.cash_full)}</b></div>
            <div className="flex justify-between mt-1 text-warn-700"><span>Cash you could defer, at a risk</span><b>{inr(c.cash_gap)}</b></div>
          </div>
        </>
      )}
    </Card>
  );
}
