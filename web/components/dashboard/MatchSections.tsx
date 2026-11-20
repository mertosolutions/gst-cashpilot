"use client";
import { useRouter } from "next/navigation";
import { clsx } from "clsx";
import { CheckCircle2, CircleDashed, FileWarning, Scale } from "lucide-react";
import { Card, LayerChip, Skeleton } from "@/components/ui";
import { num, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { ReconList } from "@/lib/types";

const SECTIONS = [
  { key: "matched", label: "Matched", hint: "Same in books and GSTR-2B", icon: CheckCircle2, tone: "text-ok-700 bg-ok-50" },
  { key: "amount_mismatch", label: "Amount mismatch", hint: "Both have it, amounts differ", icon: Scale, tone: "text-warn-700 bg-warn-50" },
  { key: "missing_in_2b", label: "Missing in 2B", hint: "In books, supplier has not reported", icon: FileWarning, tone: "text-bad-700 bg-bad-50" },
  { key: "missing_in_books", label: "Missing in books", hint: "In GSTR-2B, not in your books", icon: CircleDashed, tone: "text-brand-700 bg-brand-50" },
];

export default function MatchSections() {
  const router = useRouter();
  const { data } = useApi<ReconList>("/reconciliation", { page_size: 1 });
  const go = (tab: string) => { sessionStorage.setItem("cashpilot.reconTab", tab); router.push("/reconciliation/"); };
  return (
    <Card title="Section by section" subtitle="Open any section for the invoice-level detail" action={<LayerChip name="Match" />}>
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        {SECTIONS.map(({ key, label, hint, icon: Icon, tone }) => {
          const n = data?.counts[key];
          const total = data?.counts.all ?? 0;
          return (
            <button key={key} onClick={() => go(key)} className="text-left rounded-xl border border-slate-200 p-4 hover:border-brand-500/50 hover:shadow-card transition">
              <div className="flex items-center gap-2"><span className={clsx("grid h-8 w-8 place-items-center rounded-lg", tone)}><Icon size={16} /></span><span className="font-medium text-sm">{label}</span></div>
              {data ? <div className="mt-3 text-2xl font-semibold">{num(n ?? 0)}<span className="text-xs font-normal text-ink-500 ml-1">{total ? pct(((n ?? 0) / total) * 100, 0) : ""}</span></div> : <Skeleton className="h-8 mt-3" />}
              <p className="text-xs text-ink-500 mt-1">{hint}</p>
            </button>
          );
        })}
      </div>
    </Card>
  );
}
