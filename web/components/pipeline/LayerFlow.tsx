"use client";
import { useState } from "react";
import { clsx } from "clsx";
import { BookOpen, Check, CircleAlert, Cpu, Eraser, FileText, GitCompare, Inbox, Scale } from "lucide-react";
import { layerMeta } from "@/lib/layers";
import { num } from "@/lib/format";
import type { Stage } from "@/lib/types";

const ICON = { intake: Inbox, normalize: Eraser, match: GitCompare, retrieve: BookOpen, decide: Scale, draft: FileText } as const;
const SHORT: Record<string, string> = { intake: "Intake", normalize: "Normalize", match: "Match", retrieve: "Rules (RAG)", decide: "ITC decision", draft: "Draft" };

/** The six layers as one connected row. Details open below when a layer is selected. */
export default function LayerFlow({ stages, running }: { stages: Stage[]; running: boolean }) {
  const first = stages.findIndex((s) => s.status !== "ok");
  const [sel, setSel] = useState<number | null>(null);
  const cur = sel ?? (first >= 0 ? first : stages.length - 1);
  const st = stages[cur];
  const m = layerMeta(st.name);

  return (
    <div>
      <ol className="relative grid grid-cols-3 gap-y-6 md:grid-cols-6">
        <span className="pointer-events-none absolute left-[8.3%] right-[8.3%] top-7 hidden h-0.5 bg-slate-200 md:block" aria-hidden />
        {stages.map((s, i) => {
          const meta = layerMeta(s.name);
          const Icon = ICON[s.key as keyof typeof ICON] ?? Inbox;
          const active = i === cur;
          const ring = s.status === "error" ? "#ea4335" : s.status === "warn" ? "#f9ab00" : "#34a853";
          return (
            <li key={s.key} className="relative flex justify-center">
              <button onClick={() => setSel(i)} aria-pressed={active} className="group flex w-full flex-col items-center text-center focus:outline-none">
                <span className={clsx("relative grid h-14 w-14 place-items-center rounded-2xl border-2 bg-white transition", running && "animate-pulse", active ? "scale-105 shadow-pop" : "group-hover:scale-105")}
                  style={{ borderColor: active ? meta.color : "#e5e7eb", color: meta.color, background: active ? meta.bg : "#fff", animationDelay: `${i * 140}ms` }}>
                  <Icon size={22} />
                  <span className="absolute -right-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full text-white" style={{ background: ring }}>
                    {s.status === "ok" ? <Check size={12} strokeWidth={3} /> : <CircleAlert size={12} />}
                  </span>
                </span>
                <span className={clsx("mt-2 text-[13px] font-semibold", active ? "text-ink-900" : "text-ink-700")}>{SHORT[s.key] ?? s.name}</span>
                <span className="text-2xl font-semibold tracking-tight text-ink-900">{num(s.items_out)}</span>
                <span className="text-[11px] text-ink-500">{s.duration_ms < 1000 ? `${s.duration_ms} ms` : `${(s.duration_ms / 1000).toFixed(1)} s`}</span>
              </button>
            </li>
          );
        })}
      </ol>

      <div className="mt-6 rounded-2xl border p-5" style={{ borderColor: m.ring, background: m.bg + "55" }}>
        <div className="flex flex-wrap items-center gap-3">
          <span className="chip border bg-white" style={{ color: m.color, borderColor: m.ring }}><b>L{st.layer}</b> {SHORT[st.key] ?? st.name}</span>
          <span className="text-sm text-ink-700">{st.description}</span>
          <span className="ml-auto flex items-center gap-1.5 text-xs text-ink-500"><Cpu size={13} />{st.engine}</span>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <div className="rounded-xl bg-white p-3"><dt className="text-[11px] text-ink-500">In → out</dt><dd className="text-lg font-semibold">{num(st.items_in)} → {num(st.items_out)}</dd></div>
          {Object.entries(st.metrics).map(([k, v]) => (
            <div key={k} className="rounded-xl bg-white p-3"><dt className="text-[11px] capitalize text-ink-500">{k.replace(/_/g, " ")}</dt><dd className="text-lg font-semibold">{typeof v === "number" ? num(v) : v}</dd></div>
          ))}
        </dl>
        {st.notes.map((n) => <p key={n} className="mt-3 flex gap-1.5 text-xs text-warn-700"><CircleAlert size={13} className="mt-0.5 shrink-0" />{n}</p>)}
      </div>
    </div>
  );
}
