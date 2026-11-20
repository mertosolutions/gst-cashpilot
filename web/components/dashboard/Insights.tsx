"use client";
import Link from "next/link";
import { clsx } from "clsx";
import { AlertTriangle, ArrowRight, CheckCircle2, Info, Phone } from "lucide-react";
import { Card, LayerChip, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import type { Insight } from "@/lib/types";

const STYLE = {
  good: { icon: CheckCircle2, cls: "bg-ok-50 text-ok-700" }, info: { icon: Info, cls: "bg-brand-50 text-brand-700" },
  warn: { icon: AlertTriangle, cls: "bg-warn-50 text-warn-700" }, action: { icon: Phone, cls: "bg-bad-50 text-bad-700" },
} as const;
const HREF: Record<string, string> = { reconciliation: "/reconciliation/", vendors: "/vendors/", scanner: "/scanner/" };

export default function Insights() {
  const { data } = useApi<Insight[]>("/dashboard/insights");
  return (
    <Card title="Insights" subtitle="Generated from this month's numbers">
      {!data ? <Skeleton className="h-64" /> : (
        <ul className="space-y-3">
          {data.map((i, idx) => {
            const S = STYLE[i.severity];
            return (
              <li key={idx} className="flex gap-3">
                <span className={clsx("grid h-8 w-8 shrink-0 place-items-center rounded-lg", S.cls)}><S.icon size={16} /></span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap"><p className="text-sm font-semibold">{i.title}</p><LayerChip name={i.layer} compact /></div>
                  <p className="text-xs text-ink-500 mt-0.5">{i.detail}</p>
                  <Link href={HREF[i.action] ?? "/"} className="text-xs font-medium text-brand-600 inline-flex items-center gap-1 mt-1 hover:underline">Open <ArrowRight size={12} /></Link>
                </div>
              </li>
            );
          })}
          {!data.length && <p className="text-sm text-ink-500">Run the processing layers to get insights.</p>}
        </ul>
      )}
    </Card>
  );
}
