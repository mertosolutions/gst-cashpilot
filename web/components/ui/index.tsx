"use client";
import { ReactNode, useEffect } from "react";
import { clsx } from "clsx";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, X } from "lucide-react";
import { layerMeta } from "@/lib/layers";
import { MATCH_LABEL, STATUS_LABEL } from "@/lib/format";

export function Card({ children, className, title, subtitle, action }: { children: ReactNode; className?: string; title?: ReactNode; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <section className={clsx("card", className)}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 px-5 pt-4">
          <div>
            {title && <h3 className="text-[15px] font-semibold text-ink-900">{title}</h3>}
            {subtitle && <p className="text-xs text-ink-500 mt-0.5">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className="p-5 pt-4">{children}</div>
    </section>
  );
}

export function Skeleton({ className }: { className?: string }) { return <div className={clsx("skeleton", className)} />; }

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-bad-500/30 bg-bad-50 px-4 py-3 text-sm text-bad-700">
      <AlertTriangle size={16} /> <span className="flex-1">{message}</span>
      {onRetry && <button className="underline" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="text-center py-10">
      <p className="font-medium text-ink-700">{title}</p>
      {hint && <p className="text-sm text-ink-500 mt-1 max-w-md mx-auto">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

const STATUS_STYLE: Record<string, string> = {
  eligible: "bg-ok-50 text-ok-700", at_risk: "bg-warn-50 text-warn-700", blocked: "bg-bad-50 text-bad-700",
  matched: "bg-ok-50 text-ok-700", amount_mismatch: "bg-warn-50 text-warn-700", missing_in_2b: "bg-bad-50 text-bad-700", missing_in_books: "bg-brand-50 text-brand-700",
  low: "bg-ok-50 text-ok-700", medium: "bg-warn-50 text-warn-700", high: "bg-bad-50 text-bad-700",
  partial: "bg-warn-50 text-warn-700", ok: "bg-ok-50 text-ok-700", warn: "bg-warn-50 text-warn-700", fail: "bg-bad-50 text-bad-700", error: "bg-bad-50 text-bad-700",
};
export function Pill({ kind, children }: { kind: string; children?: ReactNode }) {
  const text = children ?? MATCH_LABEL[kind] ?? STATUS_LABEL[kind] ?? kind;
  return <span className={clsx("chip whitespace-nowrap", STATUS_STYLE[kind] ?? "bg-slate-100 text-ink-700")}>{text}</span>;
}
export function ItcBadge({ status, partial }: { status: string | null; partial?: boolean }) {
  if (!status) return <span className="text-ink-300">-</span>;
  return <Pill kind={partial ? "partial" : status}>{partial ? "Eligible + at risk" : STATUS_LABEL[status]}</Pill>;
}

/** Shows which processing layer produced a number. */
export function LayerChip({ name, compact }: { name: string; compact?: boolean }) {
  const m = layerMeta(name);
  return (
    <span className="chip border whitespace-nowrap" style={{ color: m.color, background: m.bg, borderColor: m.ring }} title={`Produced by processing layer ${m.n}: ${name}`}>
      <span className="font-bold">L{m.n}</span>{!compact && <span>{name}</span>}
    </span>
  );
}

export function Delta({ pct, good }: { pct: number | null; good: "up" | "down" | null }) {
  if (pct === null) return <span className="text-[11px] text-ink-300">no prior month</span>;
  const up = pct >= 0;
  const positive = good === null ? null : (good === "up") === up;
  const color = positive === null ? "text-ink-500 bg-slate-100" : positive ? "text-ok-700 bg-ok-50" : "text-bad-700 bg-bad-50";
  return (
    <span className={clsx("chip", color)}>
      {up ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}{Math.abs(pct)}%
    </span>
  );
}

export function Drawer({ open, onClose, title, subtitle, children, width = "max-w-2xl" }: { open: boolean; onClose: () => void; title: ReactNode; subtitle?: ReactNode; children: ReactNode; width?: string }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  return (
    <div className={clsx("fixed inset-0 z-50 transition", open ? "pointer-events-auto" : "pointer-events-none")} aria-hidden={!open}>
      <div className={clsx("absolute inset-0 bg-slate-900/30 transition-opacity", open ? "opacity-100" : "opacity-0")} onClick={onClose} />
      <aside className={clsx("absolute right-0 top-0 h-full w-full bg-white shadow-pop transition-transform overflow-y-auto", width, open ? "translate-x-0" : "translate-x-full")}>
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 bg-white/95 backdrop-blur px-6 py-4 border-b border-slate-100">
          <div><h2 className="text-lg font-semibold text-ink-900">{title}</h2>{subtitle && <div className="text-sm text-ink-500 mt-0.5">{subtitle}</div>}</div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100" aria-label="Close"><X size={18} /></button>
        </div>
        <div className="p-6">{open && children}</div>
      </aside>
    </div>
  );
}

export function Segmented<T extends string | number>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[] }) {
  return (
    <div className="inline-flex rounded-xl bg-slate-100 p-0.5">
      {options.map((o) => (
        <button key={String(o.value)} onClick={() => onChange(o.value)}
          className={clsx("px-3 py-1 text-xs font-medium rounded-[10px] transition", o.value === value ? "bg-white shadow-card text-ink-900" : "text-ink-500 hover:text-ink-700")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function StatusDot({ status, pulse }: { status: string; pulse?: boolean }) {
  const c = status === "ok" ? "bg-ok-500" : status === "warn" ? "bg-warn-500" : status === "idle" ? "bg-slate-300" : "bg-bad-500";
  return <span className={clsx("inline-block h-2.5 w-2.5 rounded-full", c, pulse && "pulse")} />;
}
