"use client";
import { useState } from "react";
import { clsx } from "clsx";
import { ChevronDown } from "lucide-react";
import { Card, ErrorBox, Segmented, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/hooks";

type DecisionRule = { order: number; key: string; label: string; when: string; outcome: string; detail: string; used: number; citations: { id: string; citation: string }[] };
type Passage = { id: string; citation: string; topic: string; body: string; used: number };
type RulesData = { engine: string; invoices_checked: number; decision_rules: DecisionRule[]; passages: Passage[]; needs_ca_review: boolean; note: string };

const OUTCOME: Record<string, { text: string; cls: string }> = {
  eligible: { text: "Eligible", cls: "bg-ok-50 text-ok-700" },
  eligible_partial: { text: "Eligible + at risk", cls: "bg-warn-50 text-warn-700" },
  at_risk: { text: "At risk", cls: "bg-warn-50 text-warn-700" },
  blocked: { text: "Blocked", cls: "bg-bad-50 text-bad-700" },
};

export default function RulesPanel() {
  const { data, error, reload } = useApi<RulesData>("/pipeline/rules");
  const [view, setView] = useState<"decision" | "passages">("decision");
  const [open, setOpen] = useState<string | null>(null);

  return (
    <Card title="Rules the tool applies"
      action={<Segmented value={view} onChange={setView} options={[{ value: "decision", label: "Decision rules" }, { value: "passages", label: "GST passages" }]} />}>
      {error ? <ErrorBox message={error} onRetry={reload} /> : !data ? <Skeleton className="h-48" /> : (
        <>
          <p className="mb-3 text-xs text-ink-500">
            {view === "decision" ? "Checked in this order for every invoice. The first rule that fits decides." : `Passages found by ${data.engine}. The count is how many invoices cited it this month.`}
          </p>
          {view === "decision" ? (
            <ol className="space-y-2">
              {data.decision_rules.map((r) => {
                const o = OUTCOME[r.outcome] ?? OUTCOME.at_risk;
                return (
                  <li key={r.key} className="flex items-start gap-3 rounded-xl border border-slate-100 p-3">
                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-brand-50 text-xs font-semibold text-brand-600">{r.order}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold">{r.when}</span>
                        <span className={clsx("chip", o.cls)}>{o.text}</span>
                        <span className="chip bg-slate-100 text-ink-500">{r.used} invoice{r.used === 1 ? "" : "s"}</span>
                      </div>
                      <p className="mt-0.5 text-xs text-ink-500">{r.detail}</p>
                      {r.citations.length > 0 && <p className="mt-1 text-xs text-ink-500">{r.citations.map((c) => c.citation).join(" · ")}</p>}
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : (
            <ul className="divide-y divide-slate-100 rounded-xl border border-slate-100">
              {data.passages.map((p) => (
                <li key={p.id}>
                  <button type="button" className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-slate-50" onClick={() => setOpen(open === p.id ? null : p.id)}>
                    <span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold">{p.citation}</span><span className="block truncate text-xs text-ink-500">{p.topic}</span></span>
                    {p.used > 0 && <span className="chip bg-brand-50 text-brand-600">{p.used}</span>}
                    <ChevronDown size={16} className={clsx("shrink-0 text-ink-500 transition", open === p.id && "rotate-180")} />
                  </button>
                  {open === p.id && <p className="px-3 pb-3 text-sm text-ink-700">{p.body}</p>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}
