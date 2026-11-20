"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import { clsx } from "clsx";
import { Cpu, Database, FileText, GitCompare, Layers, LayoutDashboard, LogIn, Menu, ScanLine, ShieldCheck, Sparkles } from "lucide-react";
import { useApp } from "@/lib/app-context";
import { pendingRequests, watchPending } from "@/lib/api";
import { DEMO_USERS, useAuth } from "@/lib/auth";
import { ErrorBox, PageLoader, Skeleton } from "@/components/ui";
import ChatWidget from "@/components/ChatWidget";
import InsightsPopup from "@/components/InsightsPopup";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/scanner/", label: "Invoice scanner", icon: ScanLine },
  { href: "/reconciliation/", label: "Reconciliation", icon: GitCompare },
  { href: "/draft/", label: "GSTR-3B draft", icon: FileText },
  { href: "/pipeline/", label: "Processing layers", icon: Layers },
];

function EngineChip({ icon: Icon, label, value, on }: { icon: typeof Cpu; label: string; value: string; on: boolean }) {
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <Icon size={13} className={on ? "text-ok-500" : "text-ink-300"} />
      <span className="text-ink-500">{label}</span>
      <span className={clsx("ml-auto font-medium", on ? "text-ink-900" : "text-ink-500")}>{value}</span>
    </div>
  );
}

export default function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const { month, months, setMonth, me, status, loading, error, refresh } = useApp();
  const auth = useAuth();
  const [open, setOpen] = useState(false);
  // Keep the loader up until every request of this page (and month) has finished, not only the first one.
  const [settled, setSettled] = useState(false);
  const loadKey = `${path}|${month}`;
  useEffect(() => {
    setSettled(false);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = (n: number) => { clearTimeout(timer); if (n === 0) timer = setTimeout(() => setSettled(true), 400); };
    const stop = watchPending(check);
    check(pendingRequests());
    const cap = setTimeout(() => setSettled(true), 90000);  // never hide the page forever
    return () => { stop(); clearTimeout(timer); clearTimeout(cap); };
  }, [loadKey]);
  const current = NAV.find((n) => (n.href === "/" ? path === "/" : path.startsWith(n.href.replace(/\/$/, ""))));

  if (auth.mode === "firebase" && auth.ready && !auth.uid) {
    return (
      <div className="min-h-screen grid place-items-center">
        <div className="card p-8 text-center max-w-sm">
          <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-brand-600 text-white"><Sparkles /></div>
          <h1 className="text-xl font-semibold">GST CashPilot</h1>
          <p className="text-sm text-ink-500 mt-1 mb-5">Know your GST cash before you file.</p>
          <button className="btn btn-primary w-full justify-center" onClick={auth.signIn}><LogIn size={16} /> Sign in with Google</button>
          <div className="mt-5 rounded-xl bg-brand-50 px-4 py-3 text-left text-sm text-ink-700">
            <p className="font-semibold text-ink-900">Need sample data?</p>
            <p className="mt-0.5">Download the sample files, then upload them after you sign in.</p>
            <a className="mt-1.5 inline-block font-semibold text-brand-700 underline underline-offset-2" href="https://drive.google.com/drive/folders/1od3jVwg9Y83ScqZs45hLVBxdC07irhQZ?usp=sharing" target="_blank" rel="noopener noreferrer">Click here for sample data</a>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen lg:pl-64">
      {/* sidebar */}
      <aside className={clsx("fixed inset-y-0 left-0 z-40 w-64 bg-white border-r border-slate-200/70 flex flex-col transition-transform lg:translate-x-0", open ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex items-center gap-2.5 px-5 h-16 border-b border-slate-100">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white"><Sparkles size={18} /></div>
          <div><div className="font-semibold leading-tight">GST CashPilot</div><div className="text-[11px] text-ink-500 leading-tight">Pre-filing cash view</div></div>
        </div>
        <nav className="p-3 space-y-0.5">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? path === "/" : path.startsWith(href.replace(/\/$/, ""));
            return (
              <Link key={href} href={href} onClick={() => setOpen(false)}
                className={clsx("flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition", active ? "bg-brand-50 text-brand-700" : "text-ink-700 hover:bg-slate-50")}>
                <Icon size={17} /> {label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto p-4 space-y-2 border-t border-slate-100">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">Engines</p>
          {status ? (
            <>
              <EngineChip icon={Cpu} label="Gemini" value={status.gemini_configured ? status.gemini_model : "offline mode"} on={status.gemini_configured} />
              <EngineChip icon={Sparkles} label="Google ADK" value={status.adk_version} on={status.adk_version !== "not installed"} />
              <EngineChip icon={Database} label="Database" value={status.database.split(" ")[0]} on />
              <EngineChip icon={ShieldCheck} label="Embeddings" value={status.embedding_engine} on />
            </>
          ) : <Skeleton className="h-16" />}
        </div>
      </aside>

      <div className="flex min-h-screen flex-col">
        {/* top bar */}
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-slate-200/70 bg-white/85 backdrop-blur px-4 lg:px-8">
          <button className="lg:hidden p-2 rounded-lg hover:bg-slate-100" onClick={() => setOpen(true)} aria-label="Menu"><Menu size={20} /></button>
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold text-ink-900">{current?.label ?? "GST CashPilot"}</h1>
            <p className="truncate text-xs text-ink-500">{me ? `${me.legal_name} · ${me.gstin || "GSTIN comes from your GSTR-2B"}` : "Loading business..."}</p>
          </div>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <span className="chip hidden lg:inline-flex bg-warn-50 text-warn-700"><ShieldCheck size={12} /> Draft only · nothing is filed</span>
            {months.length > 0 && <InsightsPopup />}
            <select className="input !w-auto !py-1.5 font-medium" value={month ?? ""} onChange={(e) => setMonth(e.target.value)} aria-label="Month">
              {months.map((m) => <option key={m.month} value={m.month}>{m.label}</option>)}
              {!months.length && <option>No data</option>}
            </select>
            {auth.mode === "demo" ? (
              <select className="input !w-auto !py-1.5 hidden sm:block" value={auth.uid ?? ""} onChange={(e) => auth.switchDemo(e.target.value)} aria-label="Demo user">
                {DEMO_USERS.map((u) => <option key={u.uid} value={u.uid}>{u.label}</option>)}
              </select>
            ) : <button className="btn btn-ghost" onClick={auth.signOut}>Sign out</button>}
          </div>
        </header>
        <main className="flex-1 px-4 pt-6 pb-28 lg:px-8 max-w-[1500px] w-full mx-auto">
          {error ? <ErrorBox message={error} onRetry={refresh} /> : loading || !me ? <PageLoader /> : !months.length && !path.startsWith("/pipeline") ? (
            <div className="card p-10 text-center"><p className="font-medium">Your workspace is empty.</p><p className="text-sm text-ink-500 mt-1">Upload your purchase register, GSTR-2B and sales summary. Everything here is built from your own files.</p><Link href="/pipeline/" className="btn btn-primary mt-4 inline-flex">Upload data</Link></div>
          ) : (
            <>
              {!settled && <PageLoader label="Loading your data" />}
              <div className={settled ? undefined : "hidden"}>{children}</div>
            </>
          )}
        </main>
      </div>
      {open && <div className="fixed inset-0 z-30 bg-slate-900/30 lg:hidden" onClick={() => setOpen(false)} />}
      {!error && !loading && months.length > 0 && <ChatWidget />}
    </div>
  );
}
