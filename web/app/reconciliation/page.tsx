"use client";
import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { Card, ErrorBox, ItcBadge, LayerChip, Pill, Skeleton } from "@/components/ui";
import ItemDrawer from "@/components/reconciliation/ItemDrawer";
import { inr, MATCH_LABEL } from "@/lib/format";
import { useApp } from "@/lib/app-context";
import { useApi } from "@/lib/hooks";
import type { ReconList } from "@/lib/types";

const TABS = ["all", "matched", "amount_mismatch", "missing_in_2b", "missing_in_books"] as const;
const SORTS = [["at_risk", "At risk"], ["claimable", "Claimable"], ["blocked", "Blocked"], ["taxable", "Taxable value"], ["date", "Date"], ["vendor", "Vendor"]];

export default function Reconciliation() {
  const { refresh } = useApp();
  const [tab, setTab] = useState<string>("all");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("at_risk");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { const t = sessionStorage.getItem("cashpilot.reconTab"); if (t) { setTab(t); sessionStorage.removeItem("cashpilot.reconTab"); } }, []);
  useEffect(() => setPage(1), [tab, status, q, sort]);
  const { data, error, loading, reload } = useApi<ReconList>("/reconciliation", { match_type: tab === "all" ? "" : tab, itc_status: status, q, sort, page, page_size: 15 });
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="space-y-5">
      <Card title="Reconciliation" subtitle="Your purchase register against GSTR-2B, section by section" action={<div className="flex gap-1.5"><LayerChip name="Match" /><LayerChip name="Rule retrieval (RAG)" /><LayerChip name="ITC decision" /></div>}>
        <div className="flex flex-wrap gap-2 mb-4">
          {TABS.map((t) => (
            <button key={t} onClick={() => setTab(t)} className={clsx("rounded-xl border px-3.5 py-2 text-sm font-medium transition", tab === t ? "border-brand-600 bg-brand-50 text-brand-700" : "border-slate-200 bg-white text-ink-700 hover:bg-slate-50")}>
              {t === "all" ? "All" : MATCH_LABEL[t]} <span className="ml-1.5 rounded-full bg-white/80 px-1.5 text-xs text-ink-500">{data?.counts[t] ?? "·"}</span>
            </button>))}
        </div>
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <div className="flex gap-1">{["", "eligible", "at_risk", "blocked"].map((s) => (
            <button key={s || "any"} onClick={() => setStatus(s)} className={clsx("chip border", status === s ? "bg-brand-600 text-white border-brand-600" : "bg-white border-slate-200 text-ink-700 hover:bg-slate-50")}>
              {s ? `${s.replace("_", " ")} (${data?.status_counts[s] ?? 0})` : "Any ITC status"}</button>))}</div>
          <select className="input !w-auto !py-1" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">{SORTS.map(([v, l]) => <option key={v} value={v}>Sort: {l}</option>)}</select>
          <div className="relative ml-auto"><Search size={14} className="absolute left-2.5 top-2.5 text-ink-500" /><input className="input !pl-8 !w-56" placeholder="Search vendor or invoice no" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        </div>
        {error ? <ErrorBox message={error} onRetry={reload} /> : !data ? <Skeleton className="h-96" /> : (
          <>
            <div className={clsx("overflow-x-auto rounded-xl border border-slate-200 transition-opacity", loading && "opacity-60")}>
              <table className="w-full min-w-[900px]">
                <thead className="bg-slate-50"><tr><th className="th">Vendor / invoice</th><th className="th">Date</th><th className="th text-right">Tax in books</th><th className="th text-right">Tax in 2B</th><th className="th">Match</th><th className="th">ITC</th><th className="th text-right">Claimable</th><th className="th text-right">At risk</th><th className="th">Rule</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {data.items.map((i) => (
                    <tr key={i.match_id} onClick={() => setOpen(i.match_id)} className="cursor-pointer hover:bg-brand-50/40">
                      <td className="td"><div className="font-medium">{i.vendor}</div><div className="text-[11px] text-ink-500">{i.invoice_no}{i.source === "scan" && <span className="ml-1.5 chip bg-brand-50 text-brand-700">scanned</span>}</div></td>
                      <td className="td text-ink-500 whitespace-nowrap">{new Date(i.date).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</td>
                      <td className="td text-right tabular-nums">{i.tax_books === null ? <span className="text-ink-300">-</span> : inr(i.tax_books, { decimals: 2 })}</td>
                      <td className="td text-right tabular-nums">{i.tax_2b === null ? <span className="text-ink-300">-</span> : inr(i.tax_2b, { decimals: 2 })}</td>
                      <td className="td"><Pill kind={i.match_type} /></td>
                      <td className="td"><ItcBadge status={i.itc_status} partial={i.partial} /></td>
                      <td className="td text-right tabular-nums text-ok-700">{i.claimable ? inr(i.claimable, { decimals: 2 }) : "-"}</td>
                      <td className="td text-right tabular-nums text-warn-700">{i.at_risk ? inr(i.at_risk, { decimals: 2 }) : "-"}</td>
                      <td className="td text-xs text-ink-500 max-w-[190px] truncate" title={i.citation ?? ""}>{i.citation ?? (i.itc_status ? "no rule found" : "-")}</td>
                    </tr>))}
                  {!data.items.length && <tr><td className="td py-10 text-center text-ink-500" colSpan={9}>No items for these filters.</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-ink-500">
              <span>{data.total} items · page {data.page} of {pages}</span>
              <div className="flex gap-1"><button className="btn btn-ghost !px-2 !py-1" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={14} /></button><button className="btn btn-ghost !px-2 !py-1" disabled={page >= pages} onClick={() => setPage(page + 1)}><ChevronRight size={14} /></button></div>
            </div>
          </>
        )}
      </Card>
      <ItemDrawer matchId={open} onClose={() => setOpen(null)} onChanged={refresh} />
    </div>
  );
}
