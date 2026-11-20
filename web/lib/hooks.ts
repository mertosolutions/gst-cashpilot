"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { useApp } from "./app-context";

/** Fetches `path` for the selected month and refetches when the month, the params or the global data version change. */
export function useApi<T>(path: string | null, params: Record<string, unknown> = {}, opts: { withMonth?: boolean } = {}) {
  const { month, version } = useApp();
  const withMonth = opts.withMonth ?? true;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const key = JSON.stringify([path, params, withMonth ? month : null, version]);
  const seq = useRef(0);

  const run = useCallback(async () => {
    if (!path || (withMonth && !month)) return;
    const id = ++seq.current;
    setLoading(true);
    try {
      const d = await api.get<T>(path, withMonth ? { month, ...params } : params);
      if (id === seq.current) { setData(d); setError(null); }
    } catch (e) { if (id === seq.current) setError((e as Error).message); }
    finally { if (id === seq.current) setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => { run(); }, [run]);
  return { data, error, loading, reload: run };
}
