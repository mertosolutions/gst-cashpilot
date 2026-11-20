"use client";
import { useState } from "react";
import { clsx } from "clsx";
import { Download, ShieldCheck } from "lucide-react";
import { Card, ErrorBox, LayerChip, Segmented, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { inr } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Draft, Heads } from "@/lib/types";

const HEADS: (keyof Heads)[] = ["igst", "cgst", "sgst"];
const Row = ({ label, h, total = true }: { label: string; h: Heads; total?: boolean }) => (
  <tr className="border-t border-slate-100"><td className="td">{label}</td>{HEADS.map((k) => <td key={k} className="td text-right tabular-nums">{inr(h[k], { decimals: 2 })}</td>)}{total && <td className="td text-right font-semibold tabular-nums">{inr(h.igst + h.cgst + h.sgst, { decimals: 2 })}</td>}</tr>
);

export default function DraftPage() {
  const { month } = useApp();
  const { data, error, reload } = useApi<Draft>("/draft");
  const [caseKey, setCaseKey] = useState<"A" | "B">("A");
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Skeleton className="h-96" />;
  const t = data.tables;
  const cases = t.table_6.cases;
  const sel = cases.find((c) => c.key === caseKey)!;
  return (
    <div className="space-y-5">
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
