"use client";
import { useRef, useState } from "react";
import { clsx } from "clsx";
import { FileSpreadsheet, FileText, Play, Table2, Trash2, UploadCloud } from "lucide-react";
import { Card, ErrorBox, Skeleton } from "@/components/ui";
import LayerFlow from "@/components/pipeline/LayerFlow";
import RulesPanel from "@/components/pipeline/RulesPanel";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { useApi } from "@/lib/hooks";
import type { PipelineRun } from "@/lib/types";

const SLOTS = [
  { key: "purchase_register", title: "Purchase register", hint: ".csv or .xlsx", accept: ".csv,.xlsx", icon: Table2 },
  { key: "gstr2b", title: "GSTR-2B", hint: ".xlsx", accept: ".xlsx", icon: FileSpreadsheet },
  { key: "sales", title: "Sales summary", hint: ".csv", accept: ".csv", icon: FileText },
] as const;

export default function PipelinePage() {
  const { month, months, refresh } = useApp();
  const empty = months.length === 0;
  const { data, error, reload } = useApi<PipelineRun>(empty ? null : "/pipeline/latest");
  const [running, setRunning] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [confirmWipe, setConfirmWipe] = useState(false);
  const [wiping, setWiping] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const inputs = useRef<Record<string, HTMLInputElement | null>>({});

  async function run() {
    setRunning(true); setMsg(null);
    try { await api.post("/pipeline/run", undefined, { month }); refresh(); reload(); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setRunning(false); }
  }
  async function upload() {
    const f = new FormData();
    SLOTS.forEach((s) => { const file = files[s.key]; if (file) f.append(s.key, file); });
    if (![...f.keys()].length) { setMsg({ ok: false, text: "Choose at least one file." }); return; }
    setRunning(true); setUploading(true); setMsg(null);
    try {
      const r = await api.upload<{ months: string[] }>("/ingest", f);
      setMsg({ ok: true, text: `Loaded ${r.months.join(", ")} and ran the layers.` });
      setFiles({}); refresh();
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setRunning(false); setUploading(false); }
  }
  async function wipe() {
    setWiping(true); setMsg(null);
    try {
      await api.del("/ingest/all");
      setConfirmWipe(false); setFiles({}); refresh(); reload();
      setMsg({ ok: true, text: "All your data was deleted. Upload files to start again." });
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setWiping(false); }
  }
  const chosen = Object.values(files).filter(Boolean).length;

  return (
    <div className="space-y-5">
      {!empty && <>
      <Card title="Processing layers"
        action={<div className="flex items-center gap-2">
          {data && <span className={clsx("chip", data.status === "ok" ? "bg-ok-50 text-ok-700" : "bg-warn-50 text-warn-700")}>{data.status === "ok" ? "All done" : "Needs a look"} · {data.total_ms < 1000 ? `${data.total_ms} ms` : `${(data.total_ms / 1000).toFixed(1)} s`}</span>}
          <button className="btn btn-primary" onClick={run} disabled={running}><Play size={15} /> {running ? "Running..." : "Run again"}</button>
        </div>}>
        {msg && !msg.ok && <div className="mb-4"><ErrorBox message={msg.text} /></div>}
        {error ? <ErrorBox message={error} onRetry={reload} /> : !data ? <Skeleton className="h-72" /> : <LayerFlow stages={data.stages} running={running} />}
      </Card>

      <RulesPanel />
      </>}

      {!empty && (
        <Card title="Delete all data" subtitle="Removes every upload, invoice, match, decision, draft and scan in your workspace. Your sign-in stays.">
          {confirmWipe ? (
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-sm font-medium text-bad-700">This cannot be undone. Delete everything?</p>
              <button className="btn border border-bad-700 bg-bad-700 text-white" onClick={wipe} disabled={wiping}>
                {wiping && <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />} {wiping ? "Deleting..." : "Yes, delete all"}
              </button>
              <button className="btn" onClick={() => setConfirmWipe(false)} disabled={wiping}>Cancel</button>
            </div>
          ) : (
            <button className="btn border border-bad-500 text-bad-700" onClick={() => setConfirmWipe(true)}><Trash2 size={15} /> Delete all data</button>
          )}
        </Card>
      )}

      <Card title="Upload data" subtitle={empty ? "Start here: add your files for a month and the layers run on them." : undefined} action={chosen > 0 ? <button className="btn btn-primary" onClick={upload} disabled={running}>{uploading ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" /> : <UploadCloud size={15} />} {uploading ? "Uploading and processing..." : `Upload ${chosen} file${chosen > 1 ? "s" : ""}`}</button> : undefined}>
        {msg?.ok && <div className="mb-4 rounded-xl bg-ok-50 px-4 py-2 text-sm text-ok-700">{msg.text}</div>}
        <div className="grid gap-3 md:grid-cols-3">
          {SLOTS.map(({ key, title, hint, accept, icon: Icon }) => {
            const file = files[key];
            return (
              <button key={key} type="button" onClick={() => inputs.current[key]?.click()}
                className={clsx("flex items-center gap-3 rounded-2xl border-2 border-dashed p-4 text-left transition", file ? "border-ok-500/60 bg-ok-50/50" : "border-slate-200 hover:border-brand-500/60 hover:bg-brand-50/30")}>
                <span className={clsx("grid h-11 w-11 shrink-0 place-items-center rounded-xl", file ? "bg-ok-50 text-ok-700" : "bg-brand-50 text-brand-600")}><Icon size={20} /></span>
                <span className="min-w-0"><span className="block text-sm font-semibold">{title}</span><span className="block truncate text-xs text-ink-500">{file ? file.name : hint}</span></span>
                <input ref={(el) => { inputs.current[key] = el; }} type="file" accept={accept} hidden onChange={(e) => { const x = e.target.files?.[0] ?? null; setFiles((c) => ({ ...c, [key]: x })); e.target.value = ""; }} />
              </button>
            );
          })}
        </div>
        {uploading && <div role="status" className="mt-4 flex items-center gap-3 rounded-xl bg-brand-50 px-4 py-3 text-sm text-brand-700"><span className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-brand-100 border-t-brand-600" />Reading your files, matching invoices and running the layers. This can take a few seconds.</div>}
        <p className="mt-3 text-xs text-ink-500">Uploading a month replaces that month's files. Confirmed scans are kept.</p>
      </Card>
    </div>
  );
}
