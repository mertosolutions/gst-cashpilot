"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, ReactNode } from "react";
import { api } from "./api";
import { useAuth } from "./auth";
import type { Me, SystemStatus } from "./types";

interface AppState {
  month: string | null; months: { month: string; label: string }[]; setMonth: (m: string) => void;
  me: Me | null; status: SystemStatus | null; loading: boolean; error: string | null;
  version: number; refresh: () => void; // bump after data changes so every view refetches
}
const Ctx = createContext<AppState>(null as unknown as AppState);
export const useApp = () => useContext(Ctx);

export function AppProvider({ children }: { children: ReactNode }) {
  const { ready, uid, mode } = useAuth();
  const [months, setMonths] = useState<{ month: string; label: string }[]>([]);
  const [month, setMonthState] = useState<string | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!ready) return;
    if (mode === "firebase" && !uid) {  // signed out: nothing to load, and no token to send
      setMonths([]); setMonthState(null); setMe(null); setStatus(null); setError(null); setLoading(false);
      return;
    }
    setLoading(true);
    (async () => {
      try {
        const [m, who, st] = await Promise.all([
          api.get<{ months: { month: string; label: string }[]; latest: string | null }>("/months"),
          api.get<Me>("/me"), api.get<SystemStatus>("/system/status"),
        ]);
        setMonths(m.months); setMe(who); setStatus(st);
        const saved = localStorage.getItem("cashpilot.month");
        setMonthState(saved && m.months.some((x) => x.month === saved) ? saved : m.latest);
        setError(null);
      } catch (e) { setError((e as Error).message); }
      finally { setLoading(false); }
    })();
  }, [ready, uid, mode, version]);

  const setMonth = useCallback((m: string) => { localStorage.setItem("cashpilot.month", m); setMonthState(m); }, []);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);
  const value = useMemo(() => ({ month, months, setMonth, me, status, loading, error, version, refresh }), [month, months, setMonth, me, status, loading, error, version, refresh]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
