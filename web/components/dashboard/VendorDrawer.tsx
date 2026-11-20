"use client";
import { useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CheckCircle2, Mail, Send } from "lucide-react";
import { Drawer, ErrorBox, ItcBadge, Pill, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { openBlankTab, showInGmail } from "@/lib/gmail";
import { inr, pct, shortMonth } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { ReconItem, VendorRow } from "@/lib/types";

interface Notice { id: string; subject: string; recipient_email: string; sent_at: string; status: string; at_risk_amount: number }
interface Detail { vendor: { name: string; gstin: string }; summary: VendorRow | null; series: { month: string; label: string; spend: number; at_risk: number; matched_pct: number | null; invoices: number }[]; invoices: ReconItem[]; notices?: Notice[] }

export default function VendorDrawer({ gstin, onClose }: { gstin: string | null; onClose: () => void }) {
  const { data, error, reload } = useApi<Detail>(gstin ? `/vendors/${gstin}` : null, { window: 6 });
  const [sending, setSending] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const s = data?.summary;

  const sendNotice = async () => {
    if (!gstin) return;
    setSending(true);
    const tab = openBlankTab();
    try {
      const res = await api.post<{ success: boolean; message: string; notice: { at_risk_amount: number; recipient_email: string; subject: string; body: string } }>(`/vendors/${gstin}/notice`, {});
      const opened = showInGmail(tab, { subject: res.notice.subject, body: res.notice.body });
      setMsg(`Notice saved for ₹${inr(res.notice?.at_risk_amount || 0)} at-risk credit. ${opened ? "Gmail opened with the draft. Add the supplier's email address and press Send." : "Your browser blocked the Gmail tab. Allow pop-ups and try again."}`);
      reload();
    } catch {
      tab?.close();
      alert("Could not prepare the notice");
    } finally {
      setSending(false);
    }
  };

  return (
    <Drawer open={!!gstin} onClose={onClose} title={data?.vendor.name ?? "Vendor"} subtitle={gstin ?? ""} width="max-w-3xl">
      {error ? <ErrorBox message={error} /> : !data ? <Skeleton className="h-96" /> : (
        <div className="space-y-6">
          {msg && (
            <div className="flex items-center gap-2 rounded-xl bg-ok-50 border border-ok-200 p-3 text-xs text-ok-800">
              <CheckCircle2 size={16} className="text-ok-600" />
              <span>{msg}</span>
            </div>
          )}

          {s && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[["Spend (6M)", inr(s.spend, { compact: true })], ["ITC at risk", inr(s.at_risk, { compact: true })], ["Blocked", inr(s.blocked, { compact: true })], ["Match rate", pct(s.matched_pct, 0)]].map(([l, v]) => (
                <div key={l} className="rounded-xl bg-slate-50 p-3"><div className="text-[11px] text-ink-500">{l}</div><div className="text-lg font-semibold">{v}</div></div>
              ))}
            </div>
          )}

          {s && (
            <div className="flex flex-wrap items-center justify-between gap-3 p-3.5 rounded-xl bg-slate-50 border border-slate-200/70">
              <div className="flex items-center gap-2 text-sm">
                <Pill kind={s.risk_level}>{s.risk_level} risk</Pill>
                <span className="text-ink-500 text-xs sm:text-sm">{s.issues} of {s.invoices} invoices have an issue · {s.missing_in_2b} missing in GSTR-2B</span>
              </div>
              {s.at_risk > 0 && (
                <button
                  onClick={sendNotice}
                  disabled={sending}
                  className="btn btn-secondary !py-1.5 text-xs flex items-center gap-1.5 font-medium border-warn-300 bg-warn-50 text-warn-900 hover:bg-warn-100"
                >
                  <Send size={13} className="text-warn-600" />
                  <span>{sending ? "Preparing..." : "Notify in Gmail"}</span>
                </button>
              )}
            </div>
          )}

          {data.notices && data.notices.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold mb-2 flex items-center gap-1.5"><Mail size={14} className="text-ink-500" /> Notices Triggered</h4>
              <div className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
                {data.notices.map((n) => (
                  <div key={n.id} className="p-3 text-xs flex items-center justify-between">
                    <div>
                      <div className="font-medium text-ink-900">{n.subject}</div>
                      <div className="text-ink-500 text-[11px] mt-0.5">To: {n.recipient_email} · Amount: {inr(n.at_risk_amount)}</div>
                    </div>
                    <span className="chip bg-ok-50 text-ok-700 font-medium capitalize">{n.status}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

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
