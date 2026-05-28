// Typed fetch wrapper for the TheoryY REST API. Zero proprietary logic.

import type {
  ApiKeyCreated,
  ApiKeyInfo,
  Health,
  MemoFormat,
  MemoJob,
  TickersResponse,
  TokenResponse,
  UsageResponse,
} from "./types";

const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let tokenGetter: () => string | null = () => null;
export function setTokenGetter(fn: () => string | null) {
  tokenGetter = fn;
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = tokenGetter();
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["X-API-Key"] = token;

  const resp = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const data = await resp.json();
      detail = data.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  const ct = resp.headers.get("content-type") ?? "";
  return (ct.includes("application/json") ? await resp.json() : await resp.text()) as T;
}

export const api = {
  base: BASE,
  health: () => req<Health>("GET", "/health"),

  // auth
  signup: (email: string, password: string) =>
    req<TokenResponse>("POST", "/api/v1/account/signup", { email, password }),
  login: (email: string, password: string) =>
    req<TokenResponse>("POST", "/api/v1/account/login", { email, password }),

  // research
  tickers: () => req<TickersResponse>("GET", "/api/v1/tickers"),
  createMemo: (ticker: string, format: MemoFormat) =>
    req<MemoJob>("POST", "/api/v1/memos", { ticker, format }),
  listMemos: () => req<MemoJob[]>("GET", "/api/v1/memos"),
  memoStatus: (jobId: string) => req<MemoJob>("GET", `/api/v1/memos/${jobId}`),
  downloadUrl: (jobId: string, format: string) =>
    `${BASE}/api/v1/memos/${jobId}/download?format=${format}`,

  // account
  usage: () => req<UsageResponse>("GET", "/api/v1/account/usage"),
  listKeys: () => req<ApiKeyInfo[]>("GET", "/api/v1/account/keys"),
  createKey: (name: string) => req<ApiKeyCreated>("POST", "/api/v1/account/keys", { name }),
  revokeKey: (prefix: string) => req<void>("DELETE", `/api/v1/account/keys/${prefix}`),

  // billing
  checkout: (plan: "pro" | "team") =>
    req<{ url: string }>("POST", "/api/v1/billing/checkout", { plan }),
};

// Authenticated file download (download endpoint needs the X-API-Key header).
export async function downloadMemo(jobId: string, format: string, filename: string) {
  const token = tokenGetter();
  const resp = await fetch(api.downloadUrl(jobId, format), {
    headers: token ? { "X-API-Key": token } : {},
  });
  if (!resp.ok) throw new ApiError(resp.status, "Download failed");
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
