"use client";
import { useRef, useState } from "react";
import { Play, UploadCloud } from "lucide-react";
import { Card, ErrorBox, Skeleton } from "@/components/ui";
import LayerFlow from "@/components/pipeline/LayerFlow";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { useApi } from "@/lib/hooks";
import type { PipelineRun } from "@/lib/types";

export default function PipelinePage() {
  const { month, months, refresh } = useApp();
  const { data, error, reload } = useApi<PipelineRun>("/pipeline/latest");
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const reg = useRef<HTMLInputElement>(null), g2b = useRef<HTMLInputElement>(null), sales = useRef<HTMLInputElement>(null);

  async function run() {
    setRunning(true); setMsg(null);
    try { await api.post("/pipeline/run", undefined, { month }); refresh(); reload(); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setRunning(false); }
  }
  async function upload() {
    const f = new FormData();
    if (reg.current?.files?.[0]) f.append("purchase_register", reg.current.files[0]);
    if (g2b.current?.files?.[0]) f.append("gstr2b", g2b.current.files[0]);
    if (sales.current?.files?.[0]) f.append("sales", sales.current.files[0]);
    if (![...f.keys()].length) { setMsg({ ok: false, text: "Choose at least one file." }); return; }
    setRunning(true); setMsg(null);
    try {
      const r = await api.upload<{ months: string[] }>("/ingest", f);
      setMsg({ ok: true, text: `Loaded ${r.months.length} month(s) and ran the processing layers: ${r.months.join(", ")}` });
      refresh();
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setRunning(false); }
  }

  return (
    <div className="space-y-5">
      <Card title="Processing layers" subtitle={`${months.find((m) => m.month === month)?.label ?? ""}: every figure in the app comes from one of these six layers`}
        action={<button className="btn btn-primary" onClick={run} disabled={running}><Play size={15} /> {running ? "Running..." : "Run layers again"}</button>}>
        {msg && <div className={msg.ok ? "mb-4 rounded-xl bg-ok-50 text-ok-700 px-4 py-2 text-sm" : "mb-4"}>{msg.ok ? msg.text : <ErrorBox message={msg.text} />}</div>}
        {error ? <ErrorBox message={error} onRetry={reload} /> : !data ? <Skeleton className="h-72" /> : (
          <>
            <LayerFlow stages={data.stages} running={running} />
            <p className="mt-4 text-xs text-ink-500">Run {new Date(data.started_at + "Z").toLocaleString("en-IN")} · total {data.total_ms} ms · status <b>{data.status}</b>. Matching and tax maths are plain Python so amounts are exact. Gemini only reads scans and writes explanations.</p>
          </>
        )}
      </Card>
      <Card title="Upload data" subtitle="Intake layer: send the three files a business exports each month">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[["Purchase register (.csv / .xlsx)", reg, ".csv,.xlsx"], ["GSTR-2B (.xlsx with a B2B sheet)", g2b, ".xlsx"], ["Sales summary (.csv)", sales, ".csv"]].map(([label, ref, accept]) => (
            <label key={label as string} className="block text-sm"><span className="font-medium">{label as string}</span>
              <input ref={ref as React.RefObject<HTMLInputElement>} type="file" accept={accept as string} className="mt-1.5 block w-full text-xs file:mr-3 file:rounded-lg file:border-0 file:bg-brand-50 file:px-3 file:py-1.5 file:text-brand-700" /></label>
          ))}
        </div>
        <button className="btn btn-primary mt-4" onClick={upload} disabled={running}><UploadCloud size={15} /> Upload and run layers</button>
        <p className="mt-2 text-xs text-ink-500">Re-uploading a month replaces that month's register, GSTR-2B and sales rows. Scanned invoices you confirmed are kept.</p>
      </Card>
    </div>
  );
}
