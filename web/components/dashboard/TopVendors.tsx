"use client";
import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { Search } from "lucide-react";
import { Card, ErrorBox, Pagination, Pill, Skeleton, usePageSize } from "@/components/ui";
import VendorDrawer from "@/components/dashboard/VendorDrawer";
import { inr, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { VendorList } from "@/lib/types";

const SORTS = [{ value: "at_risk", label: "Most credit at risk" }, { value: "spend", label: "Highest spend" }, { value: "matched_pct", label: "Lowest match rate" }];

/** Vendors, paged (5, 10, 15 or 20 rows). One drop-down for the order, one for the period, one for risk. */
export default function TopVendors() {
  const [sort, setSort] = useState("at_risk");
  const [windowM, setWindowM] = useState(1);
  const [risk, setRisk] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = usePageSize("vendors");
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => setPage(1), [sort, windowM, risk, q, pageSize]);
  const { data, error, loading, reload } = useApi<VendorList>("/vendors", { sort, order: sort === "matched_pct" ? "asc" : "desc", limit: pageSize, offset: (page - 1) * pageSize, window: windowM, risk, q });

  return (
    <Card title="Vendors" subtitle={data ? `${data.total_matching} vendors · top 3 hold ${pct(data.top3_share, 0)} of the at-risk credit` : "Loading..."}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select className="input !w-auto !py-1.5 text-sm" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Order">{SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}</select>
        <select className="input !w-auto !py-1.5 text-sm" value={windowM} onChange={(e) => setWindowM(Number(e.target.value))} aria-label="Period"><option value={1}>This month</option><option value={3}>Last 3 months</option><option value={6}>Last 6 months</option></select>
        <select className="input !w-auto !py-1.5 text-sm" value={risk} onChange={(e) => setRisk(e.target.value)} aria-label="Risk"><option value="">All risk</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
        <div className="relative ml-auto"><Search size={14} className="absolute left-2.5 top-2.5 text-ink-500" /><input className="input !pl-8 !w-44 !py-1.5 text-sm" placeholder="Search vendor" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      </div>
      {error ? <ErrorBox message={error} onRetry={reload} /> : !data ? <Skeleton className="h-56" /> : (
        <>
          <div className={clsx("overflow-x-auto rounded-xl border border-slate-200 transition-opacity", loading && "opacity-60")}>
            <table className="w-full">
              <thead className="bg-slate-50"><tr><th className="th">Vendor</th><th className="th text-right">At risk</th><th className="th text-right">Matched</th><th className="th">Risk</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((v) => (
                  <tr key={v.vendor_id} onClick={() => setOpen(v.gstin)} className="cursor-pointer hover:bg-brand-50/40">
                    <td className="td"><div className="font-medium">{v.name}</div><div className="text-[11px] text-ink-500">{v.gstin}</div></td>
                    <td className="td text-right font-medium text-warn-700">{inr(v.at_risk)}</td>
                    <td className="td text-right">{pct(v.matched_pct, 0)}</td>
                    <td className="td"><Pill kind={v.risk_level} /></td>
                  </tr>))}
                {!data.items.length && <tr><td className="td py-8 text-center text-ink-500" colSpan={4}>No vendors match.</td></tr>}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={pageSize} total={data.total_matching} onPage={setPage} onPageSize={setPageSize} />
        </>
      )}
      <VendorDrawer gstin={open} onClose={() => setOpen(null)} />
    </Card>
  );
}
