"use client";
import { useRef, useState } from "react";
import { clsx } from "clsx";
import { FileSpreadsheet, FileText, Play, Table2, UploadCloud } from "lucide-react";
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
    setRunning(true); setMsg(null);
    try {
      const r = await api.upload<{ months: string[] }>("/ingest", f);
      setMsg({ ok: true, text: `Loaded ${r.months.join(", ")} and ran the layers.` });
      setFiles({}); refresh();
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setRunning(false); }
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

      <Card title="Upload data" subtitle={empty ? "Start here: add your files for a month and the layers run on them." : undefined} action={chosen > 0 ? <button className="btn btn-primary" onClick={upload} disabled={running}><UploadCloud size={15} /> Upload {chosen} file{chosen > 1 ? "s" : ""}</button> : undefined}>
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
        <p className="mt-3 text-xs text-ink-500">Uploading a month replaces that month's files. Confirmed scans are kept.</p>
      </Card>
    </div>
  );
}
