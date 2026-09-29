import { backendConfig, type PickedFile } from "./platform";
import type { ApiErrorBody, Job } from "./types";

export class ApiError extends Error {
  body: ApiErrorBody;
  status: number;
  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.status = status;
    this.body = body;
  }
}

const TIMEOUT_MS = 180_000;

async function request<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  let cfg: Awaited<ReturnType<typeof backendConfig>>;
  try {
    cfg = await backendConfig();
  } catch (e) {
    throw new ApiError(0, { code: "backend_unavailable", message: "The local backend could not be started.", detail: String(e) });
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  const headers: Record<string, string> = {};
  if (cfg.token) headers["X-CF-Token"] = cfg.token;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(cfg.url + path, {
      method,
      headers,
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
      signal: ctrl.signal,
    });
  } catch (e) {
    const aborted = e instanceof DOMException && e.name === "AbortError";
    throw new ApiError(0, {
      code: aborted ? "timeout" : "backend_unreachable",
      message: aborted ? "The request took too long and was cancelled." : "Cannot reach the local backend.",
      hint: aborted ? undefined : "The app's Python backend is not running. Restart the app, or run `npm run backend` in development.",
      detail: String(e),
    });
  } finally {
    clearTimeout(timer);
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new ApiError(res.status, (data && data.error) || { code: "http_" + res.status, message: `Request failed (HTTP ${res.status}).` });
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body: unknown = {}) => request<T>("POST", path, body),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
  form: <T>(path: string, form: FormData) => request<T>("POST", path, undefined, form),
};

/** URL for media/render files (used by <video>/<audio>/<img>, which cannot send headers). */
export async function fileUrl(path: string, bust?: string): Promise<string> {
  const cfg = await backendConfig();
  const qs = new URLSearchParams();
  if (cfg.token) qs.set("token", cfg.token);
  if (bust) qs.set("v", bust);
  const q = qs.toString();
  return cfg.url + path + (q ? "?" + q : "");
}

export async function waitForJob(id: string, onProgress?: (j: Job) => void, timeoutMs = 30 * 60_000): Promise<Job> {
  const end = Date.now() + timeoutMs;
  for (;;) {
    const job = await api.get<Job>(`/api/jobs/${id}`);
    onProgress?.(job);
    if (job.status === "succeeded") return job;
    if (job.status === "failed") throw new ApiError(500, job.error ?? { code: "job_failed", message: job.message });
    if (Date.now() > end) throw new ApiError(0, { code: "timeout", message: "The background job is taking too long." });
    await new Promise((r) => setTimeout(r, 700));
  }
}

/** Import a picked file: by reference in the desktop app, by upload in the browser. */
export async function importPicked<T>(picked: PickedFile, fields: Record<string, string | undefined>): Promise<T> {
  if (picked.path) {
    return api.post<T>("/api/media/import-path", { path: picked.path, ...fields });
  }
  const form = new FormData();
  form.append("file", picked.file as File);
  for (const [k, v] of Object.entries(fields)) if (v) form.append(k, v);
  return api.form<T>("/api/media/upload", form);
}

export function errorMessage(e: unknown): ApiErrorBody {
  if (e instanceof ApiError) return e.body;
  return { code: "client_error", message: e instanceof Error ? e.message : String(e) };
}
