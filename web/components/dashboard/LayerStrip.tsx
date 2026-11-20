"use client";
import Link from "next/link";
import { clsx } from "clsx";
import { ChevronRight } from "lucide-react";
import { Card, StatusDot } from "@/components/ui";
import { layerMeta } from "@/lib/layers";
import { useApi } from "@/lib/hooks";
import type { PipelineRun } from "@/lib/types";

export default function LayerStrip() {
  const { data, error } = useApi<PipelineRun>("/pipeline/latest");
  return (
    <Card title="Processing layers" subtitle={data ? `Last run ${new Date(data.started_at + "Z").toLocaleString("en-IN")} · ${data.total_ms} ms` : "Every number above is produced by one of these layers"}
      action={<Link href="/pipeline/" className="text-xs font-medium text-brand-600 hover:underline">Open details</Link>}>
      {error ? <p className="text-sm text-ink-500">The layers have not run for this month yet. <Link href="/pipeline/" className="text-brand-600 underline">Run them</Link>.</p> : (
        <div className="flex flex-col md:flex-row md:items-stretch gap-2">
          {(data?.stages ?? Array.from({ length: 6 }).map((_, i) => ({ layer: i + 1, name: "", status: "idle", duration_ms: 0, items_out: 0, engine: "" }))).map((s, i, arr) => {
            const m = layerMeta(s.name);
            return (
              <div key={i} className="flex items-center gap-2 md:flex-1">
                <div className="flex-1 rounded-xl border p-3 min-w-0" style={{ borderColor: m.ring, background: m.bg + "80" }}>
                  <div className="flex items-center justify-between"><span className="text-[11px] font-bold" style={{ color: m.color }}>L{s.layer}</span><StatusDot status={s.status} /></div>
                  <div className="text-[13px] font-semibold mt-0.5 truncate">{s.name || "..."}</div>
                  <div className="text-[11px] text-ink-500 truncate">{s.items_out} out · {s.duration_ms} ms</div>
                </div>
                {i < arr.length - 1 && <ChevronRight size={16} className={clsx("hidden md:block shrink-0 text-ink-300")} />}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
