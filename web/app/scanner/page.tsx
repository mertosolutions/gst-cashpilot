"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { clsx } from "clsx";
import { Camera, CheckCircle2, CircleAlert, FileText, Loader2, ScanLine, Sparkles, Trash2, UploadCloud, XCircle } from "lucide-react";
import { Card, ErrorBox, LayerChip, Pagination, Pill, Skeleton, StatusDot, usePageSize } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { inr } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Check, MonthMetrics, Scan, ScanFields } from "@/lib/types";

interface Impact { warnings: string[]; invoice_id: string; month: string; match_type: string | null; itc_status: string | null; reason: string | null; citation: string | null; before: MonthMetrics; after: MonthMetrics; impact: { cash_safe: number; at_risk: number; eligible: number } }
type Draft = { supplier_name: string; supplier_gstin: string; invoice_no: string; invoice_date: string; taxable_value: number; igst: number; cgst: number; sgst: number; total: number; category: string };

const STEPS = [["Upload", "File reaches the API"], ["Read (OCR)", "Google Document AI & Gemini 3.8 Multimodal OCR"], ["Structure fields", "Entity mapping & confidence"], ["Validate (code)", "Plain-code checks, no model"], ["Confirm", "You approve before saving"]];
const toDraft = (f: ScanFields): Draft => ({ supplier_name: f.supplier_name ?? "", supplier_gstin: f.supplier_gstin ?? "", invoice_no: f.invoice_no ?? "", invoice_date: f.invoice_date ?? "", taxable_value: f.taxable_value, igst: f.igst, cgst: f.cgst, sgst: f.sgst, total: f.total, category: f.category ?? "General purchase" });

function Field({ label, k, d, set, conf, type = "text", readOnly }: { label: string; k: keyof Draft; d: Draft; set: (k: keyof Draft, v: string) => void; conf?: number; type?: string; readOnly?: boolean }) {
  const low = conf !== undefined && conf < 0.7;
  return (
    <label className="block">
      <span className="flex items-center justify-between text-[11px] font-medium text-ink-500">{label}{conf !== undefined && <span className={clsx("flex items-center gap-1", low ? "text-warn-700" : "text-ok-700")}><span className="h-1 w-10 rounded-full bg-slate-200 overflow-hidden"><span className={clsx("block h-full", low ? "bg-warn-500" : "bg-ok-500")} style={{ width: `${conf * 100}%` }} /></span>{Math.round(conf * 100)}%</span>}</span>
      <input className={clsx("input mt-1", low && "!border-warn-500", readOnly && "bg-slate-50")} type={type} value={String(d[k] ?? "")} readOnly={readOnly} step="any" onChange={(e) => set(k, e.target.value)} />
    </label>
  );
}

export default function ScannerPage() {
  const { refresh } = useApp();
  const [scan, setScan] = useState<Scan | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [checks, setChecks] = useState<Check[]>([]);
  const [preview, setPreview] = useState<{ url: string; pdf: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(-1);
  const [error, setError] = useState<string | null>(null);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const cam = useRef<HTMLInputElement>(null);
  const samples = useApi<{ name: string; title: string; description: string }[]>("/scans/samples", {}, { withMonth: false });
  const [sample, setSample] = useState("");
  const [recentPage, setRecentPage] = useState(1);
  const [recentSize, setRecentSize] = usePageSize("scans");
  const recent = useApi<Scan[]>("/scans", {}, { withMonth: false });

  const begin = () => { setBusy(true); setError(null); setScan(null); setDraft(null); setImpact(null); setStep(0); };
  const finish = useCallback(async (s: Scan, localUrl?: { url: string; pdf: boolean }) => {
    setScan(s); setDraft(s.fields ? toDraft(s.fields) : null); setChecks(s.checks); setStep(4);
    try { setPreview(localUrl ?? { url: await api.fileUrl(`/scans/${s.id}/file`), pdf: s.filename.toLowerCase().endsWith(".pdf") }); } catch { setPreview(null); }
    recent.reload();
  }, [recent]);

  async function run(job: () => Promise<Scan>, localUrl?: { url: string; pdf: boolean }) {
    begin();
    const t = setInterval(() => setStep((s) => Math.min(s + 1, 1)), 400); // Upload, then stay on Read (OCR) until the API answers
    try { await finish(await job(), localUrl); }
    catch (e) { setError((e as Error).message); setStep(-1); }
    finally { clearInterval(t); setBusy(false); }
  }
  const onFile = (f: File | undefined | null) => {
    if (!f) return;
    const url = URL.createObjectURL(f);
    run(() => { const form = new FormData(); form.append("file", f); return api.upload<Scan>("/scans", form); }, { url, pdf: f.type === "application/pdf" });
  };
  const onSample = (name: string) => run(() => api.post<Scan>(`/scans/samples/${encodeURIComponent(name)}`));

  const set = (k: keyof Draft, v: string) => setDraft((d) => d && { ...d, [k]: ["taxable_value", "igst", "cgst", "sgst", "total"].includes(k) ? Number(v) : v });
  useEffect(() => {
    if (!draft || !scan || scan.status === "confirmed") return;
    const t = setTimeout(async () => { try { setChecks(await api.post<Check[]>(`/scans/${scan.id}/validate`, draft)); } catch { /* keep last checks */ } }, 350);
    return () => clearTimeout(t);
  }, [draft, scan]);

  const failing = checks.filter((c) => c.status === "fail");
  const blocked = failing.length > 0 || checks.find((c) => c.key === "dup")?.status === "warn";
  async function confirm() {
    if (!scan || !draft) return;
    setBusy(true); setError(null);
    try {
      const { total, ...body } = draft; void total;
      const r = await api.post<Impact>(`/scans/${scan.id}/confirm`, body);
      setImpact(r); setScan({ ...scan, status: "confirmed" }); refresh(); recent.reload();
    } catch (e) { setError(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function undo() {
    if (!scan) return;
    setBusy(true); setError(null);
    try { await api.post(`/scans/${scan.id}/undo`); setImpact(null); setScan({ ...scan, status: "extracted" }); refresh(); recent.reload(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function removeScan(s: Scan) {
    const inBooks = s.status === "confirmed";
    if (!window.confirm(inBooks ? `Delete "${s.filename}"? It is already in your books, so that invoice will be removed too and the month re-processed.` : `Delete "${s.filename}"?`)) return;
    try {
      await api.del(`/scans/${s.id}`);
      if (scan?.id === s.id) { setScan(null); setDraft(null); setImpact(null); setPreview(null); setStep(-1); }
      if (inBooks) refresh();
      recent.reload();
    } catch (e) { setError((e as Error).message); }
  }
  const confirmed = scan?.status === "confirmed";

  return (
    <div className="space-y-5">
      <div className="card px-5 py-3.5">
        <ol className="flex items-center gap-2 overflow-x-auto" aria-label="Scan progress">
          {STEPS.map(([name, desc], i) => {
            const st = scan?.stages.find((x) => x.name === name);
            const done = step > i || (i === 4 && confirmed) || (!!st && step >= 4);
            const active = busy && step === i;
            const status = st?.status === "fail" ? "error" : st?.status === "warn" ? "warn" : done ? "ok" : "idle";
            return (
              <li key={name} className="flex items-center gap-2 flex-1 last:flex-none min-w-0" title={st?.detail ?? desc}>
                <span className="grid h-6 w-6 place-items-center rounded-full border border-slate-200 bg-white">
                  {active ? <Loader2 size={13} className="animate-spin text-brand-600" /> : status === "ok" ? <CheckCircle2 size={15} className="text-ok-500" /> : status === "warn" ? <CircleAlert size={15} className="text-warn-500" /> : status === "error" ? <XCircle size={15} className="text-bad-500" /> : <span className="h-2 w-2 rounded-full bg-slate-300" />}
                </span>
                <span className={clsx("text-sm font-medium whitespace-nowrap", status === "idle" && !active ? "text-ink-500" : "text-ink-900")}>{name}</span>
                {st && <span className="text-[11px] text-ink-500">{st.ms} ms</span>}
                {i < STEPS.length - 1 && <span className={clsx("mx-2 h-px flex-1 min-w-[12px]", done ? "bg-ok-500" : "bg-slate-200")} />}
              </li>
            );
          })}
        </ol>
        {scan?.notes?.map((n) => <p key={n} className="mt-2 text-xs text-warn-700 flex gap-1"><CircleAlert size={13} className="mt-0.5 shrink-0" />{n}</p>)}
      </div>
      <div className="grid xl:grid-cols-5 gap-5">
        <div className="xl:col-span-2 space-y-5">
          <Card title="Scan an invoice" subtitle="PDF or photo. Gemini reads it; plain code checks it; you confirm." action={<LayerChip name="Intake" />}>
            <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); onFile(e.dataTransfer.files[0]); }}
              onClick={() => input.current?.click()} role="button" tabIndex={0}
              className={clsx("grid place-items-center rounded-2xl border-2 border-dashed p-8 text-center cursor-pointer transition", drag ? "border-brand-500 bg-brand-50" : "border-slate-200 hover:border-brand-500/60 hover:bg-slate-50")}>
              <div><div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-brand-50 text-brand-600"><UploadCloud /></div>
                <p className="font-medium">Drop an invoice here or click to choose</p><p className="text-xs text-ink-500 mt-1">PDF, PNG or JPG · up to 10 MB</p></div>
            </div>
            <input ref={input} type="file" accept="application/pdf,image/*" hidden onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
            <input ref={cam} type="file" accept="image/*" capture="environment" hidden onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
            <button className="btn btn-ghost w-full justify-center mt-3 sm:hidden" onClick={() => cam.current?.click()}><Camera size={16} /> Use the camera</button>
            <div className="mt-5">
              <label className="text-xs font-semibold uppercase tracking-wide text-ink-500" htmlFor="sample">Or try a sample</label>
              {!samples.data ? <Skeleton className="mt-2 h-10" /> : (
                <div className="mt-2 flex gap-2">
                  <select id="sample" className="input" value={sample} onChange={(e) => setSample(e.target.value)} disabled={busy}>
                    <option value="">Choose a sample invoice...</option>
                    {samples.data.map((s) => <option key={s.name} value={s.name}>{s.title}</option>)}
                  </select>
                  <button className="btn btn-primary" disabled={busy || !sample} onClick={() => onSample(sample)}>Scan</button>
                </div>
              )}
              {sample && samples.data && <p className="mt-2 text-xs text-ink-500">{samples.data.find((s) => s.name === sample)?.description}</p>}
            </div>
          </Card>
        </div>

        <div className="xl:col-span-3 space-y-5">
          {error && <ErrorBox message={error} />}
          {!scan && !error && (
            <Card><div className="py-16 text-center"><div className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-slate-100 text-ink-500"><ScanLine /></div>
              <p className="font-medium">Nothing scanned yet</p><p className="text-sm text-ink-500 mt-1 max-w-sm mx-auto">Upload an invoice or pick a sample. You will see the original, the fields it found with confidence, the checks, and what it does to your cash payable.</p></div></Card>
          )}
          {scan && draft && (
            <>
              <div className="grid lg:grid-cols-2 gap-5">
                <Card title="Original" subtitle={scan.filename}>
                  <div className="h-[420px] overflow-hidden rounded-xl border border-slate-200 bg-slate-50 grid place-items-center">
                    {preview ? (preview.pdf ? <object data={preview.url + "#toolbar=0&view=FitH"} type="application/pdf" className="h-full w-full"><p className="p-4 text-sm">Preview not supported in this browser.</p></object> : /* eslint-disable-next-line @next/next/no-img-element */ <img src={preview.url} alt="Scanned invoice" className="max-h-full max-w-full object-contain" />) : <p className="text-sm text-ink-500">No preview</p>}
                  </div>
                </Card>
                <Card title="Extracted fields" subtitle={`${scan.engine ? "Engine: " + scan.engine + ". " : ""}Edit anything that is wrong. Low confidence fields are highlighted.`} action={<Sparkles size={16} className="text-brand-600" />}>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="col-span-2"><Field label="Supplier" k="supplier_name" d={draft} set={set} conf={scan.confidence?.supplier_name} /></div>
                    <div className="col-span-2"><Field label="Supplier GSTIN" k="supplier_gstin" d={draft} set={set} conf={scan.confidence?.supplier_gstin} /></div>
                    <Field label="Invoice no" k="invoice_no" d={draft} set={set} conf={scan.confidence?.invoice_no} />
                    <Field label="Date" k="invoice_date" d={draft} set={set} conf={scan.confidence?.invoice_date} type="date" />
                    <Field label="Taxable value" k="taxable_value" d={draft} set={set} conf={scan.confidence?.taxable_value} type="number" />
                    <Field label="Total (on invoice)" k="total" d={draft} set={set} conf={scan.confidence?.total} type="number" />
                    <Field label="IGST" k="igst" d={draft} set={set} conf={scan.confidence?.igst} type="number" />
                    <Field label="CGST" k="cgst" d={draft} set={set} conf={scan.confidence?.cgst} type="number" />
                    <Field label="SGST" k="sgst" d={draft} set={set} conf={scan.confidence?.sgst} type="number" />
                    <Field label="Category" k="category" d={draft} set={set} conf={scan.confidence?.category} />
                  </div>
                </Card>
              </div>
              <Card title="Checks (plain code)" subtitle="The model reads the invoice. These checks decide if it is safe to save." action={<LayerChip name="Normalize" />}>
                <ul className="grid sm:grid-cols-2 gap-2">
                  {checks.map((c) => (
                    <li key={c.key} className="flex items-start gap-2 rounded-xl border border-slate-100 p-2.5">
                      {c.status === "ok" ? <CheckCircle2 size={16} className="mt-0.5 text-ok-500" /> : c.status === "warn" ? <CircleAlert size={16} className="mt-0.5 text-warn-500" /> : <XCircle size={16} className="mt-0.5 text-bad-500" />}
                      <div><p className="text-sm font-medium">{c.label}</p><p className="text-xs text-ink-500">{c.detail}</p></div>
                    </li>))}
                </ul>
                <div className="mt-4 flex flex-wrap items-center gap-3">
                  <button className="btn btn-primary" disabled={busy || confirmed || blocked} onClick={confirm}><CheckCircle2 size={16} /> {confirmed ? "Added to your books" : "Confirm and add to books"}</button>
                  {blocked && !confirmed && <span className="text-xs text-bad-700">Cannot save yet: {failing.length ? failing.map((c) => c.label).join(", ") : "this invoice is already in your books"}.</span>}
                  <span className="text-xs text-ink-500">Nothing is saved until you confirm.</span>
                </div>
              </Card>
              {impact && (
                <Card title="What this invoice changed" subtitle="The processing layers ran again for the month" action={<LayerChip name="Tax and draft" />}>
                  <div className="flex flex-wrap items-center gap-2 mb-3"><Pill kind={impact.match_type ?? ""} />{impact.itc_status && <Pill kind={impact.itc_status} />}<span className="text-sm text-ink-700">{impact.reason}</span></div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {[["Missing in books", impact.before.missing_in_books, impact.after.missing_in_books, false], ["ITC eligible", impact.before.eligible, impact.after.eligible, true], ["ITC at risk", impact.before.at_risk, impact.after.at_risk, true], ["Cash payable (safe)", impact.before.cash_safe, impact.after.cash_safe, true]].map(([l, b, a, money]) => (
                      <div key={l as string} className="rounded-xl bg-slate-50 p-3"><div className="text-[11px] text-ink-500">{l as string}</div>
                        <div className="text-sm text-ink-500 line-through">{money ? inr(b as number, { compact: true }) : (b as number)}</div><div className="text-lg font-semibold">{money ? inr(a as number, { compact: true }) : (a as number)}</div></div>))}
                  </div>
                  {impact.warnings?.map((w) => <p key={w} className="mt-3 flex gap-2 rounded-xl bg-warn-50 p-3 text-sm text-warn-700"><CircleAlert size={16} className="mt-0.5 shrink-0" />{w}</p>)}
                  <div className="mt-3 flex items-center gap-4"><Link href="/reconciliation/" className="text-sm font-medium text-brand-600 hover:underline">See it in Reconciliation</Link>
                    <button className="text-sm font-medium text-bad-700 hover:underline" onClick={undo} disabled={busy}>Undo: remove this invoice from my books</button></div>
                </Card>
              )}
            </>
          )}
        </div>
      </div>

      <Card title="Recent scans">
        {!recent.data ? <Skeleton className="h-20" /> : (
          <div className="overflow-x-auto"><table className="w-full"><thead><tr><th className="th">File</th><th className="th">Supplier</th><th className="th">Invoice</th><th className="th text-right">Taxable</th><th className="th">Engine</th><th className="th">Status</th><th className="th"></th></tr></thead>
            <tbody className="divide-y divide-slate-100">{recent.data.slice((recentPage - 1) * recentSize, recentPage * recentSize).map((s) => (
              <tr key={s.id}><td className="td font-medium max-w-[220px] truncate">{s.filename}</td><td className="td">{s.fields?.supplier_name ?? "-"}</td><td className="td">{s.fields?.invoice_no ?? "-"}</td><td className="td text-right">{s.fields ? inr(s.fields.taxable_value) : "-"}</td><td className="td text-xs text-ink-500">{s.engine ?? "-"}</td>
                <td className="td"><Pill kind={s.status === "confirmed" ? "ok" : s.status === "failed" ? "fail" : "warn"}>{s.status}</Pill></td>
                <td className="td text-right whitespace-nowrap">
                  {s.status === "confirmed" && <button className="mr-3 text-xs font-medium text-warn-700 hover:underline" onClick={async () => { await api.post(`/scans/${s.id}/undo`); refresh(); recent.reload(); }}>Undo</button>}
                  <button className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-bad-700 hover:bg-bad-50" aria-label={`Delete ${s.filename}`} onClick={() => removeScan(s)}><Trash2 size={14} /> Delete</button></td></tr>))}
              {!recent.data.length && <tr><td className="td text-ink-500" colSpan={7}>No scans yet.</td></tr>}</tbody></table><Pagination page={recentPage} pageSize={recentSize} total={recent.data.length} onPage={setRecentPage} onPageSize={(n) => { setRecentSize(n); setRecentPage(1); }} /></div>)}
      </Card>
    </div>
  );
}
