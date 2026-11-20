"use client";
import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { CheckCircle2, Mail, Search, Send, X } from "lucide-react";
import { Card, ErrorBox, Pagination, Pill, Skeleton, usePageSize } from "@/components/ui";
import VendorDrawer from "@/components/dashboard/VendorDrawer";
import { api } from "@/lib/api";
import { openBlankTab, showInGmail } from "@/lib/gmail";
import { useApp } from "@/lib/app-context";
import { inr, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { VendorList } from "@/lib/types";

const SORTS = [{ value: "at_risk", label: "Most credit at risk" }, { value: "spend", label: "Highest spend" }, { value: "matched_pct", label: "Lowest match rate" }];

/** Vendors, paged (5, 10, 15 or 20 rows). With automated email notices for defaulter suppliers. */
export default function TopVendors() {
  const { month } = useApp();
  const [sort, setSort] = useState("at_risk");
  const [windowM, setWindowM] = useState(1);
  const [risk, setRisk] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = usePageSize("vendors");
  const [open, setOpen] = useState<string | null>(null);
  const [noticeTarget, setNoticeTarget] = useState<{ gstin: string; name: string } | null>(null);
  const [noticeBusy, setNoticeBusy] = useState(false);
  const [noticeSent, setNoticeSent] = useState<string | null>(null);

  useEffect(() => setPage(1), [sort, windowM, risk, q, pageSize]);
  const { data, error, loading, reload } = useApi<VendorList>("/vendors", { sort, order: sort === "matched_pct" ? "asc" : "desc", limit: pageSize, offset: (page - 1) * pageSize, window: windowM, risk, q });

  const triggerNotice = async (gstin: string, name: string) => {
    setNoticeBusy(true);
    const tab = openBlankTab();
    try {
      const res = await api.post<{ success: boolean; message: string; notice: { at_risk_amount: number; recipient_email: string; subject: string; body: string } }>(`/vendors/${gstin}/notice`, {}, { month });
      const opened = showInGmail(tab, { subject: res.notice.subject, body: res.notice.body });
      setNoticeSent(`Notice for ${name} (₹${inr(res.notice?.at_risk_amount || 0)} at-risk ITC) is saved. ${opened ? "Gmail opened with the draft. Add the supplier's email address and press Send." : "Your browser blocked the Gmail tab. Allow pop-ups and try again."}`);
      setNoticeTarget(null);
      setTimeout(() => setNoticeSent(null), 5000);
      reload();
    } catch {
      tab?.close();
      alert("Could not prepare the notice. Please check the network connection.");
    } finally {
      setNoticeBusy(false);
    }
  };

  const triggerBulkNotices = async () => {
    if (!confirm(`Send automated GSTR-1 non-filing reminder notices to all defaulting suppliers for ${month}?`)) return;
    setNoticeBusy(true);
    const tab = openBlankTab();
    try {
      const res = await api.post<{ success: boolean; notices_sent: number; total_at_risk: number; vendors: { recipient_email: string }[] }>("/vendors/send-bulk-notices", {}, { month });
      const opened = showInGmail(tab, {
        subject: `GSTR-1 reminder: invoices missing from GSTR-2B (${month})`,
        body: `Dear supplier,\n\nSome of your invoices to us for ${month} do not appear in our GSTR-2B. Under Section 16(2)(aa) of the CGST Act we can claim input tax credit only on invoices you have reported in GSTR-1.\n\nPlease file or correct your GSTR-1 at the earliest and confirm once done. A separate statement with your invoice list will follow.\n\nThank you.`,
      });
      setNoticeSent(`${res.notices_sent} notices (₹${inr(res.total_at_risk)} at-risk ITC) are saved. ${opened ? "Gmail opened with a general reminder. Add the supplier addresses (use Bcc) and press Send." : "Your browser blocked the Gmail tab. Allow pop-ups and try again."}`);
      setTimeout(() => setNoticeSent(null), 6000);
      reload();
    } catch {
      tab?.close();
      alert("Could not complete bulk notices.");
    } finally {
      setNoticeBusy(false);
    }
  };

  return (
    <Card
      title="Vendors"
      subtitle={data ? `${data.total_matching} vendors · top 3 hold ${pct(data.top3_share, 0)} of the at-risk credit` : "Loading..."}
      action={
        <button
          onClick={triggerBulkNotices}
          disabled={noticeBusy || !data?.total_matching}
          className="btn btn-secondary !py-1 text-xs flex items-center gap-1.5 font-medium hover:border-warn-400"
          title="Automated email triggers to all suppliers with missing GSTR-2B invoices"
        >
          <Mail size={13} className="text-warn-600" />
          <span>Prepare notices for all defaulters</span>
        </button>
      }
    >
      {noticeSent && (
        <div className="mb-3 flex items-center justify-between rounded-xl bg-ok-50 border border-ok-200 p-2.5 text-xs text-ok-800">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} className="text-ok-600 shrink-0" />
            <span>{noticeSent}</span>
          </div>
          <button onClick={() => setNoticeSent(null)} className="text-ok-600 hover:text-ok-800"><X size={14} /></button>
        </div>
      )}

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
              <thead className="bg-slate-50">
                <tr>
                  <th className="th">Vendor</th>
                  <th className="th text-right">At risk</th>
                  <th className="th text-right">Matched</th>
                  <th className="th">Risk</th>
                  <th className="th text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((v) => (
                  <tr key={v.vendor_id} onClick={() => setOpen(v.gstin)} className="cursor-pointer hover:bg-brand-50/40">
                    <td className="td"><div className="font-medium">{v.name}</div><div className="text-[11px] text-ink-500">{v.gstin}</div></td>
                    <td className="td text-right font-medium text-warn-700">{inr(v.at_risk)}</td>
                    <td className="td text-right">{pct(v.matched_pct, 0)}</td>
                    <td className="td"><Pill kind={v.risk_level} /></td>
                    <td className="td text-right" onClick={(e) => e.stopPropagation()}>
                      {v.at_risk > 0 ? (
                        <button
                          onClick={() => triggerNotice(v.gstin, v.name)}
                          disabled={noticeBusy}
                          className="inline-flex items-center gap-1 rounded-lg border border-warn-300 bg-warn-50 px-2.5 py-1 text-xs font-medium text-warn-800 hover:bg-warn-100 transition shadow-sm"
                          title="Send automated GSTR-1 compliance reminder notice"
                        >
                          <Send size={11} />
                          <span>Notify</span>
                        </button>
                      ) : (
                        <span className="text-[11px] text-ink-400">Compliant</span>
                      )}
                    </td>
                  </tr>))}
                {!data.items.length && <tr><td className="td py-8 text-center text-ink-500" colSpan={5}>No vendors match.</td></tr>}
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
