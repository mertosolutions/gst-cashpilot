const BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8010").replace(/\/$/, "") + "/api/v1";
let authProvider: () => Promise<Record<string, string>> = async () => ({});
export const setAuthProvider = (fn: () => Promise<Record<string, string>>) => { authProvider = fn; };
export const API_BASE = BASE;
/** Credentials sent as the first WebSocket message (browsers cannot set headers on one). */
export async function wsAuthQuery(): Promise<Record<string, string>> {
  const h = await authProvider();
  if (h.Authorization) return { token: h.Authorization.replace(/^Bearer\s+/i, "") };
  if (h["X-Demo-User"]) return { user: h["X-Demo-User"] };
  return {};
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function qs(params?: Record<string, unknown>): string {
  if (!params) return "";
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") p.set(k, String(v)); });
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** Count of GET requests in flight, so the shell can keep a loader up until a whole page has its data. */
let pending = 0;
const watchers = new Set<(n: number) => void>();
const bump = (d: number) => { pending += d; watchers.forEach((w) => w(pending)); };
export const pendingRequests = () => pending;
export function watchPending(fn: (n: number) => void): () => void { watchers.add(fn); return () => { watchers.delete(fn); }; }

async function request<T>(method: string, path: string, opts: { params?: Record<string, unknown>; json?: unknown; form?: FormData } = {}): Promise<T> {
  const track = method === "GET";
  if (track) bump(1);
  try { return await send<T>(method, path, opts); } finally { if (track) bump(-1); }
}

async function send<T>(method: string, path: string, opts: { params?: Record<string, unknown>; json?: unknown; form?: FormData }): Promise<T> {
  const headers: Record<string, string> = { ...(await authProvider()) };
  let body: BodyInit | undefined;
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.json); }
  if (opts.form) body = opts.form;
  let res: Response;
  try { res = await fetch(`${BASE}${path}${qs(opts.params)}`, { method, headers, body }); }
  catch { throw new ApiError(0, "Cannot reach the API. Is the FastAPI server running?"); }
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* ignore */ }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string, params?: Record<string, unknown>) => request<T>("GET", path, { params }),
  post: <T>(path: string, json?: unknown, params?: Record<string, unknown>) => request<T>("POST", path, { json, params }),
  del: <T>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, form: FormData, params?: Record<string, unknown>) => request<T>("POST", path, { form, params }),
  async fileUrl(path: string): Promise<string> {
    const res = await fetch(`${BASE}${path}`, { headers: await authProvider() });
    if (!res.ok) throw new ApiError(res.status, "Could not load the file");
    return URL.createObjectURL(await res.blob());
  },
  async download(path: string, params: Record<string, unknown>, filename: string) {
    const res = await fetch(`${BASE}${path}${qs(params)}`, { headers: await authProvider() });
    if (!res.ok) throw new ApiError(res.status, "Download failed");
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a"); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url);
  },
};
