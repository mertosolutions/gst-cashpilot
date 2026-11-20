"use client";
import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { ChevronRight, Search } from "lucide-react";
import { Card, ErrorBox, ItcBadge, LayerChip, Pagination, Pill, Skeleton, usePageSize } from "@/components/ui";
import ItemDrawer from "@/components/reconciliation/ItemDrawer";
import { inr, MATCH_LABEL } from "@/lib/format";
import { useApp } from "@/lib/app-context";
import { useApi } from "@/lib/hooks";
import type { ReconList } from "@/lib/types";

const SECTIONS = ["", "matched", "amount_mismatch", "missing_in_2b", "missing_in_books"] as const;

export default function Reconciliation() {
  const { refresh } = useApp();
  const [section, setSection] = useState<string>("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = usePageSize("recon");
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { const t = sessionStorage.getItem("cashpilot.reconTab"); if (t) { setSection(t === "all" ? "" : t); sessionStorage.removeItem("cashpilot.reconTab"); } }, []);
  useEffect(() => setPage(1), [section, status, q, pageSize]);
  const { data, error, loading, reload } = useApi<ReconList>("/reconciliation", { match_type: section, itc_status: status, q, sort: "at_risk", page, page_size: pageSize });

  return (
    <div className="space-y-5">
      <Card title="Reconciliation" subtitle="Purchase register against GSTR-2B. Click a row for the detail and the rule." action={<LayerChip name="Match" />}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <select className="input !w-auto !py-1.5 text-sm" value={section} onChange={(e) => setSection(e.target.value)} aria-label="Section">
            {SECTIONS.map((s) => <option key={s || "all"} value={s}>{s ? MATCH_LABEL[s] : "All sections"}{data ? ` (${data.counts[s || "all"] ?? 0})` : ""}</option>)}
          </select>
          <select className="input !w-auto !py-1.5 text-sm" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="ITC status">
            <option value="">Any ITC status</option><option value="eligible">Eligible{data ? ` (${data.status_counts.eligible ?? 0})` : ""}</option><option value="at_risk">At risk{data ? ` (${data.status_counts.at_risk ?? 0})` : ""}</option><option value="blocked">Blocked{data ? ` (${data.status_counts.blocked ?? 0})` : ""}</option>
          </select>
          <div className="relative ml-auto"><Search size={14} className="absolute left-2.5 top-2.5 text-ink-500" /><input className="input !pl-8 !w-52 !py-1.5 text-sm" placeholder="Search vendor or invoice" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        </div>
        {error ? <ErrorBox message={error} onRetry={reload} /> : !data ? <Skeleton className="h-60" /> : (
          <>
            <div className={clsx("overflow-x-auto rounded-xl border border-slate-200 transition-opacity", loading && "opacity-60")}>
              <table className="w-full">
                <thead className="bg-slate-50"><tr><th className="th">Vendor / invoice</th><th className="th">Match</th><th className="th">ITC</th><th className="th text-right">At risk</th><th className="th w-8" /></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {data.items.map((i) => (
                    <tr key={i.match_id} onClick={() => setOpen(i.match_id)} className="cursor-pointer hover:bg-brand-50/40">
                      <td className="td"><div className="font-medium">{i.vendor}</div><div className="text-[11px] text-ink-500">{i.invoice_no}{i.source === "scan" && <span className="ml-1.5 chip bg-brand-50 text-brand-700">scanned</span>}</div></td>
                      <td className="td"><Pill kind={i.match_type} /></td>
                      <td className="td"><ItcBadge status={i.itc_status} partial={i.partial} /></td>
                      <td className="td text-right font-medium text-warn-700">{i.at_risk ? inr(i.at_risk) : "-"}</td>
                      <td className="td text-ink-300"><ChevronRight size={16} /></td>
                    </tr>))}
                  {!data.items.length && <tr><td className="td py-8 text-center text-ink-500" colSpan={5}>No items for these filters.</td></tr>}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={pageSize} total={data.total} onPage={setPage} onPageSize={setPageSize} />
          </>
        )}
      </Card>
      <ItemDrawer matchId={open} onClose={() => setOpen(null)} onChanged={refresh} />
    </div>
  );
}
