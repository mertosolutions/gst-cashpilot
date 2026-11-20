"use client";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Drawer, ErrorBox, ItcBadge, Pill, Skeleton } from "@/components/ui";
import { inr, pct, shortMonth } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { ReconItem, VendorRow } from "@/lib/types";

interface Detail { vendor: { name: string; gstin: string }; summary: VendorRow | null; series: { month: string; label: string; spend: number; at_risk: number; matched_pct: number | null; invoices: number }[]; invoices: ReconItem[] }

export default function VendorDrawer({ gstin, onClose }: { gstin: string | null; onClose: () => void }) {
  const { data, error } = useApi<Detail>(gstin ? `/vendors/${gstin}` : null, { window: 6 });
  const s = data?.summary;
  return (
    <Drawer open={!!gstin} onClose={onClose} title={data?.vendor.name ?? "Vendor"} subtitle={gstin ?? ""} width="max-w-3xl">
      {error ? <ErrorBox message={error} /> : !data ? <Skeleton className="h-96" /> : (
        <div className="space-y-6">
          {s && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[["Spend (6M)", inr(s.spend, { compact: true })], ["ITC at risk", inr(s.at_risk, { compact: true })], ["Blocked", inr(s.blocked, { compact: true })], ["Match rate", pct(s.matched_pct, 0)]].map(([l, v]) => (
                <div key={l} className="rounded-xl bg-slate-50 p-3"><div className="text-[11px] text-ink-500">{l}</div><div className="text-lg font-semibold">{v}</div></div>
              ))}
            </div>
          )}
          {s && <div className="flex items-center gap-2 text-sm"><Pill kind={s.risk_level}>{s.risk_level} risk</Pill><span className="text-ink-500">{s.issues} of {s.invoices} invoices have an issue · {s.missing_in_2b} missing in GSTR-2B · {s.amount_mismatch} amount mismatch</span></div>}
          <div>
            <h4 className="text-sm font-semibold mb-2">Six month trend</h4>
            <div className="h-52">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data.series.map((x) => ({ ...x, name: shortMonth(x.month) }))}>
                  <CartesianGrid vertical={false} stroke="#eef2f7" /><XAxis dataKey="name" fontSize={11} tickLine={false} axisLine={false} />
                  <YAxis yAxisId="l" tickFormatter={(v) => inr(v, { compact: true })} fontSize={11} width={60} tickLine={false} axisLine={false} />
                  <YAxis yAxisId="r" orientation="right" unit="%" domain={[0, 100]} fontSize={11} width={40} tickLine={false} axisLine={false} />
                  <Tooltip formatter={(v, n) => (n === "Match rate" ? `${v}%` : inr(Number(v)))} />
                  <Bar isAnimationActive={false} yAxisId="l" dataKey="spend" name="Spend" fill="#aecbfa" radius={[6, 6, 0, 0]} />
                  <Bar isAnimationActive={false} yAxisId="l" dataKey="at_risk" name="ITC at risk" fill="#f9ab00" radius={[6, 6, 0, 0]} />
                  <Line isAnimationActive={false} yAxisId="r" dataKey="matched_pct" name="Match rate" stroke="#9334e6" strokeWidth={2} connectNulls dot />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div>
            <h4 className="text-sm font-semibold mb-2">Invoices this month</h4>
            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="w-full"><thead className="bg-slate-50"><tr><th className="th">Invoice</th><th className="th">Match</th><th className="th">ITC</th><th className="th text-right">At risk</th></tr></thead>
                <tbody className="divide-y divide-slate-100">{data.invoices.map((i) => (
                  <tr key={i.match_id}><td className="td font-medium">{i.invoice_no}</td><td className="td"><Pill kind={i.match_type} /></td><td className="td"><ItcBadge status={i.itc_status} partial={i.partial} /></td><td className="td text-right">{inr(i.at_risk)}</td></tr>
                ))}{!data.invoices.length && <tr><td className="td text-ink-500" colSpan={4}>No invoices this month.</td></tr>}</tbody></table>
            </div>
          </div>
        </div>
      )}
    </Drawer>
  );
}
