"use client";
import { useState } from "react";
import { clsx } from "clsx";
import { BookOpen, Sparkles } from "lucide-react";
import { Drawer, ErrorBox, ItcBadge, LayerChip, Pill, Skeleton, StatusDot } from "@/components/ui";
import { api } from "@/lib/api";
import { inr } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { LAYER_META } from "@/lib/layers";

interface Side { invoice_no: string; clean: string; date: string; taxable: number; igst: number; cgst: number; sgst: number; tax_total: number }
interface Detail {
  match: { id: string; type: string; diff: number }; vendor: { name: string; gstin: string }; category: string | null; books: Side | null; gstr2b: Side | null;
  decision: null | { status: string; rule_key: string; rule_label: string; reason: string; citation: string | null; engine: string; llm_explanation: string | null; claimable: number; at_risk: number; blocked: number; claim_deadline: string | null; by_head: Record<string, Record<string, number>> };
  passages: { id: string; citation: string; topic: string; body: string; score: number }[];
  trace: { layer: number; name: string; status: string; summary: string }[];
}

const FIELDS: [string, keyof Side][] = [["Invoice number", "invoice_no"], ["Cleaned key", "clean"], ["Date", "date"], ["Taxable value", "taxable"], ["IGST", "igst"], ["CGST", "cgst"], ["SGST", "sgst"], ["Total tax", "tax_total"]];
const money = (k: keyof Side) => !["invoice_no", "clean", "date"].includes(k as string);
const LAYER_BY_N = Object.fromEntries(Object.entries(LAYER_META).map(([name, m]) => [m.n, name]));

export default function ItemDrawer({ matchId, onClose, onChanged }: { matchId: string | null; onClose: () => void; onChanged: () => void }) {
  const { data, error, reload } = useApi<Detail>(matchId ? `/reconciliation/${matchId}` : null, {}, { withMonth: false });
  const [busy, setBusy] = useState(false);
  const [aiErr, setAiErr] = useState<string | null>(null);
  async function explain() {
    if (!matchId) return;
    setBusy(true); setAiErr(null);
    try { await api.post(`/reconciliation/${matchId}/explain`); reload(); onChanged(); } catch (e) { setAiErr((e as Error).message); } finally { setBusy(false); }
  }
  const d = data?.decision;
  return (
    <Drawer open={!!matchId} onClose={onClose} width="max-w-3xl"
      title={data ? <span className="flex items-center gap-2">{data.vendor.name} <Pill kind={data.match.type} /></span> : "Item"} subtitle={data ? `${data.vendor.gstin}${data.category ? " · " + data.category : ""}` : ""}>
      {error ? <ErrorBox message={error} /> : !data ? <Skeleton className="h-96" /> : (
        <div className="space-y-6">
          {d && (
            <section className={clsx("rounded-2xl p-4 border", d.status === "eligible" ? "bg-ok-50 border-ok-500/30" : d.status === "at_risk" ? "bg-warn-50 border-warn-500/30" : "bg-bad-50 border-bad-500/30")}>
              <div className="flex items-center justify-between gap-2"><div className="flex items-center gap-2"><ItcBadge status={d.status} partial={d.status === "eligible" && d.at_risk > 0} /><span className="text-sm font-semibold">{d.rule_label}</span></div><LayerChip name="ITC decision" /></div>
              <p className="mt-2 text-sm text-ink-900">{d.reason}</p>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                {[["Claimable", d.claimable, "text-ok-700"], ["At risk", d.at_risk, "text-warn-700"], ["Blocked", d.blocked, "text-bad-700"]].map(([l, v, c]) => (
                  <div key={l as string} className="rounded-xl bg-white/70 py-2"><div className="text-ink-500">{l as string}</div><div className={clsx("text-base font-semibold", c as string)}>{inr(v as number, { decimals: 2 })}</div></div>))}
              </div>
              {d.claim_deadline && <p className="mt-2 text-[11px] text-ink-500">Last date to claim this invoice (Section 16(4)): {new Date(d.claim_deadline).toLocaleDateString("en-IN", { dateStyle: "medium" })}</p>}
            </section>
          )}

          <section>
            <h4 className="text-sm font-semibold mb-2">Your books vs GSTR-2B</h4>
            <div className="overflow-hidden rounded-xl border border-slate-200">
              <table className="w-full text-sm"><thead className="bg-slate-50"><tr><th className="th">Field</th><th className="th">Your books</th><th className="th">GSTR-2B</th></tr></thead>
                <tbody className="divide-y divide-slate-100">{FIELDS.map(([label, k]) => {
                  const a = data.books?.[k], b = data.gstr2b?.[k];
                  const differs = a !== undefined && b !== undefined && a !== b && money(k) && Math.abs(Number(a) - Number(b)) > 1;
                  const show = (v: unknown) => (v === undefined || v === null ? <span className="text-ink-300">not present</span> : money(k) ? inr(Number(v), { decimals: 2 }) : String(v));
                  return <tr key={label} className={differs ? "bg-warn-50/60" : ""}><td className="td text-ink-500">{label}</td><td className="td font-medium">{show(a)}</td><td className="td font-medium">{show(b)}</td></tr>;
                })}</tbody></table>
            </div>
          </section>

          <section>
            <h4 className="text-sm font-semibold mb-2 flex items-center gap-2"><BookOpen size={15} /> Rule found by RAG</h4>
            {data.passages.length ? (
              <ul className="space-y-2">{data.passages.map((p, i) => (
                <li key={p.id} className={clsx("rounded-xl border p-3", i === 0 ? "border-brand-500/40 bg-brand-50/50" : "border-slate-200")}>
                  <div className="flex items-center justify-between gap-2"><span className="text-sm font-semibold">{p.citation}</span><span className="chip bg-slate-100 text-ink-700">score {p.score.toFixed(2)}{i === 0 ? " · used" : ""}</span></div>
                  <p className="text-xs text-ink-500 mt-1">{p.topic}</p><p className="text-sm mt-1">{p.body}</p>
                </li>))}</ul>
            ) : <p className="text-sm text-ink-500">No rule found for this case.</p>}
            <p className="text-[11px] text-ink-500 mt-2">Passages are simplified paraphrases for the prototype. A CA must verify the exact wording.</p>
          </section>

          {d && (
            <section>
              <h4 className="text-sm font-semibold mb-2 flex items-center gap-2"><Sparkles size={15} /> Plain-words explanation (Gemini)</h4>
              {d.llm_explanation ? <p className="rounded-xl bg-slate-50 p-3 text-sm">{d.llm_explanation}</p> : <button className="btn btn-ghost" onClick={explain} disabled={busy}>{busy ? "Asking Gemini..." : "Explain with Gemini"}</button>}
              {aiErr && <p className="mt-2 text-xs text-warn-700">{aiErr}</p>}
            </section>
          )}

          <section>
            <h4 className="text-sm font-semibold mb-3">Decision trace through the processing layers</h4>
            <ol className="relative border-l-2 border-slate-100 ml-2 space-y-4">
              {data.trace.map((t) => (
                <li key={t.layer} className="ml-5 relative">
                  <span className="absolute -left-[27px] top-0.5 rounded-full bg-white p-0.5"><StatusDot status={t.status} /></span>
                  <div className="flex items-center gap-2"><LayerChip name={LAYER_BY_N[t.layer] ?? t.name} compact /><span className="text-sm font-medium">{t.name}</span></div>
                  <p className="text-xs text-ink-500 mt-0.5">{t.summary}</p>
                </li>))}
            </ol>
          </section>
        </div>
      )}
    </Drawer>
  );
}
