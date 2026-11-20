"use client";
import { useState } from "react";
import { clsx } from "clsx";
import { CheckCircle2, Download, History, MessageSquare, RotateCcw, Send, ShieldCheck, Sparkles } from "lucide-react";
import { Card, ErrorBox, LayerChip, Segmented, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { inr } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Draft, DraftVersion, Heads } from "@/lib/types";

const HEADS: (keyof Heads)[] = ["igst", "cgst", "sgst"];
const Row = ({ label, h, total = true }: { label: string; h: Heads; total?: boolean }) => (
  <tr className="border-t border-slate-100"><td className="td">{label}</td>{HEADS.map((k) => <td key={k} className="td text-right tabular-nums">{inr(h[k], { decimals: 2 })}</td>)}{total && <td className="td text-right font-semibold tabular-nums">{inr(h.igst + h.cgst + h.sgst, { decimals: 2 })}</td>}</tr>
);

export default function DraftPage() {
  const { month } = useApp();
  const { data, error, reload } = useApi<Draft>("/draft");
  const [caseKey, setCaseKey] = useState<"A" | "B">("A");
  const [chatPrompt, setChatPrompt] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatAnswer, setChatAnswer] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Skeleton className="h-96" />;

  const t = data.tables;
  const cases = t.table_6.cases;
  const sel = cases.find((c) => c.key === caseKey)!;
  const versions = data.versions || [];
  const currentVer = data.current_version || 1;

  const handleDraftChat = async (msgText?: string) => {
    const text = (msgText || chatPrompt).trim();
    if (!text || chatBusy) return;
    setChatBusy(true);
    setChatPrompt("");
    try {
      const res = await api.post<{ answer: string; version_created: boolean; current_version: number; tables: Draft["tables"] }>(
        "/draft/chat",
        { message: text },
        { month }
      );
      setChatAnswer(res.answer);
      reload();
    } catch {
      alert("Could not process draft adjustment.");
    } finally {
      setChatBusy(false);
    }
  };

  const restoreVersion = async (verNum: number) => {
    if (!confirm(`Restore draft to version v${verNum}?`)) return;
    try {
      await api.post(`/draft/versions/${verNum}/restore`, {}, { month });
      reload();
    } catch {
      alert("Failed to restore version");
    }
  };

  return (
    <div className="space-y-5">
      {/* Version Header Banner */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-white border border-slate-200/80 p-4 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-brand-50 text-brand-700">
            <History size={20} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm">GSTR-3B Draft Version v{currentVer}</span>
              <span className="chip bg-ok-50 text-ok-700 text-[11px] font-medium">Active Draft</span>
            </div>
            <p className="text-xs text-ink-500 mt-0.5">
              {versions.find((v) => v.version_number === currentVer)?.change_summary || "Auto-drafted from reconciled GSTR-2B"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="btn btn-secondary !py-1.5 text-xs flex items-center gap-1.5"
          >
            <History size={13} />
            <span>Version History ({versions.length})</span>
          </button>
          <button className="btn btn-ghost !py-1.5 text-xs" onClick={() => api.download("/draft/pdf", { month }, `gstr3b-draft-${month}.pdf`)}>
            <Download size={14} /> PDF
          </button>
        </div>
      </div>

      {/* Version History Drawer / Dropdown */}
      {showHistory && (
        <Card title="Draft Version History" subtitle="Audited changelog of all GSTR-3B draft versions generated or adjusted">
          <div className="divide-y divide-slate-100 rounded-xl border border-slate-200 overflow-hidden">
            {versions.map((ver) => (
              <div key={ver.version_number} className={clsx("p-3.5 text-xs flex items-center justify-between", ver.version_number === currentVer ? "bg-brand-50/40" : "bg-white")}>
                <div>
                  <div className="flex items-center gap-2 font-medium text-ink-900">
                    <span>{ver.label}</span>
                    {ver.version_number === currentVer && <span className="chip bg-brand-100 text-brand-800 text-[10px]">Active</span>}
                  </div>
                  <p className="text-ink-600 mt-1">{ver.change_summary}</p>
                  <p className="text-[11px] text-ink-400 mt-0.5">Created by {ver.created_by} · {ver.created_at ? new Date(ver.created_at).toLocaleTimeString() : ""}</p>
                </div>
                {ver.version_number !== currentVer && (
                  <button
                    onClick={() => restoreVersion(ver.version_number)}
                    className="btn btn-secondary !py-1 text-xs flex items-center gap-1 text-ink-700 hover:text-brand-700"
                  >
                    <RotateCcw size={12} />
                    <span>Restore</span>
                  </button>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Interactive GSTR-3B Copilot Assistant */}
      <div className="rounded-2xl border border-brand-200 bg-gradient-to-br from-brand-50/70 via-white to-purple-50/50 p-4 shadow-card">
        <div className="flex items-center gap-2 text-sm font-semibold text-brand-900">
          <Sparkles size={16} className="text-brand-600" />
          <span>Ask CashPilot to Adjust or Explain GSTR-3B Draft</span>
        </div>
        <p className="text-xs text-ink-600 mt-1">
          Simulate audit adjustments, switch filing strategies, or create a new draft version.
        </p>

        <div className="mt-3 flex flex-wrap gap-2">
          {[
            { label: "Switch to Conservative (Case A: Zero notice risk)", q: "Switch to conservative mode to hold back at-risk credit" },
            { label: "Switch to Aggressive (Case B: Save cash now)", q: "Switch to aggressive mode and claim full working capital credit" },
            { label: "Explain Table 4 eligible & blocked credit", q: "Explain the calculation of Table 4 eligible and blocked ITC" },
          ].map((s) => (
            <button
              key={s.label}
              onClick={() => handleDraftChat(s.q)}
              disabled={chatBusy}
              className="rounded-lg border border-brand-200/80 bg-white px-2.5 py-1 text-xs font-medium text-brand-800 hover:bg-brand-50 transition shadow-sm"
            >
              {s.label}
            </button>
          ))}
        </div>

        {chatAnswer && (
          <div className="mt-3.5 rounded-xl border border-slate-200 bg-white p-3.5 text-xs text-ink-800 whitespace-pre-wrap shadow-sm">
            {chatAnswer}
          </div>
        )}

        <form
          onSubmit={(e) => { e.preventDefault(); handleDraftChat(); }}
          className="mt-3 flex items-center gap-2"
        >
          <input
            className="input !py-1.5 text-xs flex-1"
            placeholder="Ask Copilot: e.g., 'Switch to conservative mode', 'Explain cash difference'..."
            value={chatPrompt}
            onChange={(e) => setChatPrompt(e.target.value)}
            disabled={chatBusy}
          />
          <button className="btn btn-primary !py-1.5 text-xs flex items-center gap-1.5" disabled={chatBusy || !chatPrompt.trim()}>
            <Send size={13} />
            <span>{chatBusy ? "Working..." : "Ask"}</span>
          </button>
        </form>
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        {cases.map((c) => (
          <button key={c.key} onClick={() => setCaseKey(c.key as "A" | "B")} className={clsx("card p-5 text-left transition", caseKey === c.key && "ring-2 ring-brand-500/60")}>
            <div className="flex items-center justify-between"><span className="text-xs font-medium text-ink-500">{c.label}</span><span className={clsx("chip", c.key === "A" ? "bg-ok-50 text-ok-700" : "bg-warn-50 text-warn-700")}>{c.key === "A" ? "Safe" : "Notice risk"}</span></div>
            <div className="mt-2 text-3xl font-semibold tracking-tight">{inr(c.total)}</div>
            <p className="mt-1 text-xs text-ink-500">Cash payable · ITC claimed {inr(c.itc_claimed.igst + c.itc_claimed.cgst + c.itc_claimed.sgst, { compact: true })}</p>
          </button>
        ))}
        <div className="card p-5 bg-warn-50/60 border-warn-500/30">
          <span className="text-xs font-medium text-warn-700">Cash you could defer</span>
          <div className="mt-2 text-3xl font-semibold tracking-tight text-warn-700">{inr(t.summary.cash_saved_by_case_b)}</div>
          <p className="mt-1 text-xs text-warn-700/80">This is the ITC at risk. If the vendors do not file, it comes back as tax, interest and a notice.</p>
        </div>
      </div>

      <Card title="GSTR-3B draft" subtitle={`${data.business.name} · ${data.business.gstin} · amounts in ₹`} action={
        <div className="flex items-center gap-2"><LayerChip name="Tax and draft" /><button className="btn btn-ghost" onClick={() => api.download("/draft/pdf", { month }, `gstr3b-draft-${month}.pdf`)}><Download size={15} /> PDF</button></div>}>
        <div className="space-y-6 overflow-x-auto">
          <section><h4 className="font-semibold text-sm mb-2">{t.table_3_1.title}</h4>
            <table className="w-full"><thead className="bg-slate-50"><tr><th className="th">Nature of supply</th><th className="th text-right">IGST</th><th className="th text-right">CGST</th><th className="th text-right">SGST</th><th className="th text-right">Total tax</th></tr></thead>
              <tbody><tr><td className="td">(a) Outward taxable supplies · taxable value {inr(t.table_3_1.taxable_value)}</td>{HEADS.map((k) => <td key={k} className="td text-right tabular-nums">{inr(t.table_3_1.tax[k], { decimals: 2 })}</td>)}<td className="td text-right font-semibold">{inr(t.table_3_1.tax.igst + t.table_3_1.tax.cgst + t.table_3_1.tax.sgst, { decimals: 2 })}</td></tr></tbody></table></section>
          <section><h4 className="font-semibold text-sm mb-2">{t.table_4.title}</h4>
            <table className="w-full"><thead className="bg-slate-50"><tr><th className="th">Item</th><th className="th text-right">IGST</th><th className="th text-right">CGST</th><th className="th text-right">SGST</th><th className="th text-right">Total</th></tr></thead>
              <tbody>{t.table_4.rows.map((r) => <Row key={r.label} label={r.label} h={r.tax} />)}</tbody></table></section>
          <section><h4 className="font-semibold text-sm mb-2">{t.table_6.title}: {sel.label}</h4>
            <table className="w-full"><thead className="bg-slate-50"><tr><th className="th">Head</th><th className="th text-right">Output tax</th><th className="th text-right">ITC claimed</th><th className="th text-right">Cash payable</th></tr></thead>
              <tbody>{HEADS.map((k) => <tr key={k} className="border-t border-slate-100"><td className="td font-medium uppercase">{k}</td><td className="td text-right tabular-nums">{inr(t.table_3_1.tax[k], { decimals: 2 })}</td><td className="td text-right tabular-nums">{inr(sel.itc_claimed[k], { decimals: 2 })}</td><td className="td text-right font-semibold tabular-nums">{inr(sel.cash[k], { decimals: 2 })}</td></tr>)}
                <tr className="border-t-2 border-slate-200 bg-slate-50"><td className="td font-semibold" colSpan={3}>Total cash payable</td><td className="td text-right font-bold tabular-nums">{inr(sel.total, { decimals: 2 })}</td></tr></tbody></table>
            <p className="mt-2 text-xs text-ink-500">Cash payable = max(0, output tax − ITC claimed) for each head. No credit moves between heads in this prototype.</p></section>
        </div>
        {!t.summary.has_sales && <p className="mt-4 text-sm text-warn-700">No sales summary uploaded for this month, so output tax is zero.</p>}
        <p className="mt-5 flex items-center gap-2 text-xs text-ink-500"><ShieldCheck size={14} /> {data.disclaimer}</p>
      </Card>
    </div>
  );
}
