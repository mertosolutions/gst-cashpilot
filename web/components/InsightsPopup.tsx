"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { clsx } from "clsx";
import { AlertTriangle, ArrowRight, Bell, CheckCircle2, Info, Phone, X } from "lucide-react";
import { LayerChip, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import type { Insight } from "@/lib/types";

const STYLE = {
  good: { icon: CheckCircle2, cls: "bg-ok-50 text-ok-700" }, info: { icon: Info, cls: "bg-brand-50 text-brand-700" },
  warn: { icon: AlertTriangle, cls: "bg-warn-50 text-warn-700" }, action: { icon: Phone, cls: "bg-bad-50 text-bad-700" },
} as const;
const HREF: Record<string, string> = { reconciliation: "/reconciliation/", vendors: "/", scanner: "/scanner/" };

/** Bell button in the top bar. The insights open as a popup, not as a panel on the page. */
export default function InsightsPopup() {
  const [open, setOpen] = useState(false);
  const { data } = useApi<Insight[]>("/dashboard/insights");
  const urgent = (data ?? []).filter((i) => i.severity === "warn" || i.severity === "action").length;
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    if (open) window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open]);
  return (
    <>
      <button onClick={() => setOpen(true)} className="btn btn-ghost !px-3 relative" aria-label={`Insights${urgent ? `, ${urgent} need attention` : ""}`}>
        <Bell size={16} /><span className="hidden sm:inline">Insights</span>
        {urgent > 0 && <span className="absolute -right-1 -top-1 grid h-5 min-w-5 place-items-center rounded-full bg-bad-500 px-1 text-[10px] font-bold text-white">{urgent}</span>}
      </button>
      {open && (
        <div className="fixed inset-0 z-50 grid place-items-start justify-items-center p-4 pt-20" onClick={() => setOpen(false)}>
          <div role="dialog" aria-label="Insights" className="w-full max-w-lg overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-pop" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div><h2 className="text-base font-semibold">Insights</h2><p className="text-xs text-ink-500">From this month's numbers</p></div>
              <button onClick={() => setOpen(false)} className="rounded-lg p-1.5 hover:bg-slate-100" aria-label="Close"><X size={18} /></button>
            </div>
            <ul className="max-h-[60vh] space-y-4 overflow-y-auto p-5">
              {!data ? <Skeleton className="h-40" /> : data.map((i, idx) => {
                const S = STYLE[i.severity];
                return (
                  <li key={idx} className="flex gap-3">
                    <span className={clsx("grid h-8 w-8 shrink-0 place-items-center rounded-lg", S.cls)}><S.icon size={16} /></span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2"><p className="text-sm font-semibold">{i.title}</p><LayerChip name={i.layer} compact /></div>
                      <p className="mt-0.5 text-xs text-ink-500">{i.detail}</p>
                      <Link href={HREF[i.action] ?? "/"} onClick={() => setOpen(false)} className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline">Open <ArrowRight size={12} /></Link>
                    </div>
                  </li>
                );
              })}
              {data && !data.length && <p className="text-sm text-ink-500">Nothing needs attention.</p>}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}
