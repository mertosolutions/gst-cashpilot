"use client";
import { clsx } from "clsx";
import { ItcBadge, Pill } from "@/components/ui";
import { inr } from "@/lib/format";
import type { ReconItem, VendorRow } from "@/lib/types";

export interface VoiceAnswer {
  transcript: string; english: string | null; language: string; month: string; intent: string; filters: Record<string, unknown>;
  answer: string; spoken: string; spoken_language: string; engine: string; notes: string[];
  results: { type: "invoices" | "vendors" | "cash" | "none"; items: unknown[] };
}

const FILTER_LABEL: Record<string, string> = { status: "Status", match: "Match", vendor: "Vendor", invoice: "Invoice", month: "Month" };

export function FilterChips({ filters }: { filters: Record<string, unknown> }) {
  const entries = Object.entries(filters).filter(([k]) => k !== "month");
  if (!entries.length) return null;
  return (
    <div className="mb-2 flex flex-wrap gap-1.5">
      {entries.map(([k, v]) => (
        <span key={k} className="chip bg-slate-100 text-ink-700">
          {FILTER_LABEL[k] ?? k}: {k === "amount" ? `${(v as { op: string }).op === "gte" ? "≥" : "≤"} ${inr((v as { value: number }).value)}` : String(v).replace(/_/g, " ")}
        </span>
      ))}
    </div>
  );
}

/** Compact result list inside the chat. Rows open the same detail drawers as the rest of the app. */
export function ChatResults({ a, onInvoice, onVendor }: { a: VoiceAnswer; onInvoice: (id: string) => void; onVendor: (gstin: string) => void }) {
  const r = a.results;
  if (r.type === "cash") {
    const items = r.items as { case: string; label: string; cash: number }[];
    return (
      <div className="mt-2 grid grid-cols-2 gap-2">
        {items.map((c) => (
          <div key={c.case} className={clsx("rounded-xl p-2.5", c.case === "A" ? "bg-ok-50" : "bg-warn-50")}>
            <div className="text-[10px] text-ink-500 leading-tight">Case {c.case}: {c.label}</div>
            <div className="text-lg font-semibold">{inr(c.cash)}</div>
          </div>
        ))}
      </div>
    );
  }
  if (r.type === "vendors") {
    const items = (r.items as VendorRow[]).slice(0, 5);
    if (!items.length) return null;
    return (
      <ul className="mt-2 divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
        {items.map((v) => (
          <li key={v.vendor_id}>
            <button onClick={() => onVendor(v.gstin)} className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-brand-50/40">
              <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium">{v.name}</span><span className="block text-[11px] text-ink-500">{v.matched_pct}% matched</span></span>
              <span className="text-right text-[13px] font-semibold text-warn-700">{inr(v.at_risk)}</span>
              <Pill kind={v.risk_level} />
            </button>
          </li>
        ))}
      </ul>
    );
  }
  if (r.type === "invoices") {
    const all = r.items as ReconItem[];
    const items = all.slice(0, 5);
    if (!items.length) return null;
    return (
      <div className="mt-2">
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
          {items.map((i) => (
            <li key={i.match_id}>
              <button onClick={() => onInvoice(i.match_id)} className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-brand-50/40">
                <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium">{i.vendor}</span><span className="block text-[11px] text-ink-500">{i.invoice_no} · {i.match_type.replace(/_/g, " ")}</span></span>
                <span className="text-right text-[13px] font-semibold">{inr(i.at_risk || i.blocked || i.claimable || i.taxable)}</span>
                <ItcBadge status={i.itc_status} partial={i.partial} />
              </button>
            </li>
          ))}
        </ul>
        {all.length > items.length && <p className="mt-1 text-[11px] text-ink-500">Showing {items.length} of {all.length}. Say “top 10” or open Reconciliation for all.</p>}
      </div>
    );
  }
  return null;
}
