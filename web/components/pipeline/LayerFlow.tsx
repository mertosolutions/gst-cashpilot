"use client";
import { clsx } from "clsx";
import { ArrowRight, CheckCircle2, CircleAlert, Clock, Cpu } from "lucide-react";
import { LayerChip, StatusDot } from "@/components/ui";
import { layerMeta } from "@/lib/layers";
import { num } from "@/lib/format";
import type { Stage } from "@/lib/types";

const FEEDS: Record<string, string> = {
  intake: "Total purchase cost, output tax, invoices processed", normalize: "Clean invoice numbers, GSTIN checks", match: "Match rate, flagged invoices, section view",
  retrieve: "The rule shown next to each result", decide: "ITC eligible, at risk and blocked", draft: "Cash payable, GSTR-3B draft and PDF",
};

export default function LayerFlow({ stages, running }: { stages: Stage[]; running: boolean }) {
  const maxMs = Math.max(1, ...stages.map((s) => s.duration_ms));
  return (
    <ol className="grid grid-cols-1 lg:grid-cols-6 gap-3">
      {stages.map((s, i) => {
        const m = layerMeta(s.name);
        return (
          <li key={s.key} className="relative">
            <div className={clsx("h-full rounded-2xl border bg-white p-4 shadow-card transition", running && "opacity-60")} style={{ borderColor: m.ring }}>
              <div className="flex items-center justify-between">
                <LayerChip name={s.name} compact />
                <span className="flex items-center gap-1.5 text-[11px] font-medium text-ink-500"><StatusDot status={s.status} pulse={running} />{running ? "running" : s.status === "ok" ? "done" : s.status === "warn" ? "needs a look" : "error"}</span>
              </div>
              <p className="mt-2 text-sm font-semibold leading-tight">{s.name}</p><p className="mt-1 text-xs text-ink-500 min-h-[32px]">{s.description}</p>
              <div className="mt-3 flex items-center gap-2 text-sm"><b>{num(s.items_in)}</b><ArrowRight size={13} className="text-ink-300" /><b>{num(s.items_out)}</b><span className="text-[11px] text-ink-500">items</span></div>
              <div className="mt-2"><div className="h-1.5 rounded-full bg-slate-100 overflow-hidden"><div className="h-full rounded-full" style={{ width: `${Math.max(6, (s.duration_ms / maxMs) * 100)}%`, background: m.color }} /></div>
                <div className="mt-1 flex items-center gap-1 text-[11px] text-ink-500"><Clock size={11} />{s.duration_ms} ms</div></div>
              <div className="mt-3 flex items-start gap-1.5 text-[11px] text-ink-700"><Cpu size={12} className="mt-0.5 shrink-0 text-ink-500" /><span>{s.engine}</span></div>
              <dl className="mt-3 space-y-1">
                {Object.entries(s.metrics).map(([k, v]) => <div key={k} className="flex justify-between text-[11px]"><dt className="text-ink-500">{k.replace(/_/g, " ")}</dt><dd className="font-semibold">{typeof v === "number" ? num(v) : v}</dd></div>)}
              </dl>
              {s.notes.map((n) => <p key={n} className="mt-2 flex gap-1 text-[11px] text-warn-700"><CircleAlert size={12} className="mt-0.5 shrink-0" />{n}</p>)}
              <p className="mt-3 border-t border-slate-100 pt-2 text-[11px] text-ink-500"><span className="font-semibold text-ink-700">Feeds: </span>{FEEDS[s.key]}</p>
            </div>
            {i < stages.length - 1 && <ArrowRight size={16} className="hidden lg:block absolute -right-2.5 top-1/2 z-10 -translate-y-1/2 rounded-full bg-white text-ink-300" />}
          </li>
        );
      })}
    </ol>
  );
}
export { CheckCircle2 };
