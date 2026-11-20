"use client";
import { useState } from "react";
import { clsx } from "clsx";
import { ArrowDownUp, Search } from "lucide-react";
import { Card, ErrorBox, Pill, Segmented, Skeleton } from "@/components/ui";
import VendorDrawer from "@/components/dashboard/VendorDrawer";
import { inr, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { VendorList } from "@/lib/types";

const SORTS = [
  { value: "at_risk", label: "ITC at risk" }, { value: "spend", label: "Spend" }, { value: "invoices", label: "Invoices" },
  { value: "issues", label: "Issues" }, { value: "matched_pct", label: "Match rate" }, { value: "blocked", label: "Blocked" },
];

export default function TopVendors({ compact }: { compact?: boolean }) {
  const [sort, setSort] = useState("at_risk");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [limit, setLimit] = useState(compact ? 8 : 12);
  const [windowM, setWindowM] = useState(1);
  const [risk, setRisk] = useState<string>("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const { data, error, loading, reload } = useApi<VendorList>("/vendors", { sort, order, limit, window: windowM, risk, q });
  const maxSpend = Math.max(1, ...(data?.items ?? []).map((v) => v.spend));

  return (
    <Card title="Top vendors" subtitle={data ? `${data.shown} of ${data.total_vendors} vendors · top 3 hold ${pct(data.top3_share, 0)} of the at-risk credit` : "Loading..."}
      action={<Segmented value={windowM} onChange={setWindowM} options={[{ value: 1, label: "This month" }, { value: 3, label: "3M" }, { value: 6, label: "6M" }]} />}>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="flex items-center gap-1.5">
          <ArrowDownUp size={14} className="text-ink-500" />
          <select className="input !w-auto !py-1" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort vendors">{SORTS.map((s) => <option key={s.value} value={s.value}>Sort: {s.label}</option>)}</select>
          <button className="btn btn-ghost !px-2 !py-1 text-xs" onClick={() => setOrder(order === "desc" ? "asc" : "desc")}>{order === "desc" ? "High to low" : "Low to high"}</button>
        </div>
        <select className="input !w-auto !py-1" value={limit} onChange={(e) => setLimit(Number(e.target.value))} aria-label="How many vendors">{[5, 6, 8, 12, 20].map((n) => <option key={n} value={n}>Top {n}</option>)}</select>
        <div className="flex gap-1">{["", "high", "medium", "low"].map((r) => (
          <button key={r || "all"} onClick={() => setRisk(r)} className={clsx("chip border", risk === r ? "bg-brand-600 text-white border-brand-600" : "bg-white text-ink-700 border-slate-200 hover:bg-slate-50")}>{r ? r : "All risk"}</button>
        ))}</div>
        <div className="relative ml-auto"><Search size={14} className="absolute left-2.5 top-2.5 text-ink-500" /><input className="input !pl-8 !w-44" placeholder="Search vendor or GSTIN" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      </div>
      {error ? <ErrorBox message={error} onRetry={reload} /> : !data ? <Skeleton className="h-64" /> : (
        <ul className={clsx("divide-y divide-slate-100 transition-opacity", loading && "opacity-60")}>
          {data.items.map((v, i) => (
            <li key={v.vendor_id}>
              <button onClick={() => setOpen(v.gstin)} className="w-full text-left py-3 px-1 grid grid-cols-12 items-center gap-3 hover:bg-slate-50/70 rounded-lg transition">
                <span className="col-span-1 text-xs text-ink-300 font-semibold">{i + 1}</span>
                <span className="col-span-11 sm:col-span-4 min-w-0"><span className="block truncate font-medium text-sm">{v.name}</span><span className="block text-[11px] text-ink-500">{v.gstin} · {v.invoices} invoices</span></span>
                <span className="col-span-7 sm:col-span-4">
                  <span className="flex items-center justify-between text-[11px] text-ink-500"><span>Spend {inr(v.spend, { compact: true })}</span><span className="text-warn-700 font-medium">At risk {inr(v.at_risk, { compact: true })}</span></span>
                  <span className="mt-1 block h-2 rounded-full bg-slate-100 overflow-hidden relative"><span className="absolute inset-y-0 left-0 bg-brand-100 rounded-full" style={{ width: `${(v.spend / maxSpend) * 100}%` }} /><span className="absolute inset-y-0 left-0 bg-warn-500 rounded-full" style={{ width: `${(v.at_risk / maxSpend) * 100}%` }} /></span>
                </span>
                <span className="col-span-3 sm:col-span-1 text-right text-sm"><b>{pct(v.matched_pct, 0)}</b><span className="block text-[10px] text-ink-500">matched</span></span>
                <span className="col-span-2 text-right"><Pill kind={v.risk_level}>{v.risk_level}</Pill></span>
              </button>
            </li>
          ))}
          {!data.items.length && <li className="py-8 text-center text-sm text-ink-500">No vendors match these filters.</li>}
        </ul>
      )}
      <VendorDrawer gstin={open} onClose={() => setOpen(null)} />
    </Card>
  );
}
