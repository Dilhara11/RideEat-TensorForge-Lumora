// Thin client for the TensorForge API + API-key storage.
//
// The UI is hosted separately from the API (e.g. AWS Amplify), so every call goes to API_BASE, which is
// baked in at build time from VITE_API_BASE_URL. Empty means same origin: `npm run dev` proxies to :8000.
//
// The key is never part of the built files: the user enters it, it lives in sessionStorage
// (or localStorage when "remember on this device" is ticked) and is sent as X-API-Key.

import type { ErrorDetail, Health } from "./types";

const KEY_NAME = "tf.apiKey";

// Example: VITE_API_BASE_URL="https://api.example.com/" -> "https://api.example.com"
export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/+$/, "");

/** A production build without an API address can't work (it would call the static host). */
export const API_BASE_MISSING = import.meta.env.PROD && !API_BASE;

/** Absolute API URL for a path. Example: apiUrl("/health") -> "https://api.example.com/health" */
export const apiUrl = (path: string) => `${API_BASE}${path}`;

function safeStorage(kind: "sessionStorage" | "localStorage"): Storage | null {
  try {
    const s = window[kind];
    s.setItem("__tf_probe__", "1");
    s.removeItem("__tf_probe__");
    return s;
  } catch {
    return null; // private mode / blocked site data: fall back to memory only
  }
}

const session = safeStorage("sessionStorage");
const local = safeStorage("localStorage");

/** Tiny external store, read in React with useSyncExternalStore (see hooks/useApiKey). */
class ApiKeyStore {
  private memory: string | null = session?.getItem(KEY_NAME) ?? local?.getItem(KEY_NAME) ?? null;
  private listeners = new Set<() => void>();

  get = (): string | null => this.memory;
  isRemembered = (): boolean => Boolean(local?.getItem(KEY_NAME));

  set(key: string, remember: boolean) {
    session?.removeItem(KEY_NAME);
    local?.removeItem(KEY_NAME);
    (remember ? local : session)?.setItem(KEY_NAME, key);
    this.memory = key;
    this.emit();
  }

  clear() {
    session?.removeItem(KEY_NAME);
    local?.removeItem(KEY_NAME);
    this.memory = null;
    this.emit();
  }

  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };

  private emit() {
    this.listeners.forEach((fn) => fn());
  }
}

export const apiKey = new ApiKeyStore();

/** Fired when a protected call has no key or the server rejects it (the key dialog listens). */
export const unauthorizedEvents = new EventTarget();

/** Error with the contract's {error: {code, message, details}} body flattened onto it. status 0 = network failure. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: ErrorDetail[] = [],
    readonly retryAfter: number | null = null,
  ) {
    super(message);
  }
}

// Plain-language explanation + next step for each contract status (UI copy, not server text).
const FRIENDLY: Record<number, string> = {
  0: `Can't reach the API${API_BASE ? ` at ${API_BASE}` : ""}. Check that it is running and that it allows this site (CORS_ORIGINS), then try again.`,
  401: "The API key is missing or wrong. Enter the service API key to continue.",
  404: "Not found. The job may have been deleted or never existed.",
  409: "The job hasn't finished yet, so results aren't available.",
  410: "This job's results have expired (they are kept for 6 hours after the job finishes).",
  413: "The upload is too large. Split the file into smaller parts.",
  415: "The request was not sent as JSON. Please reload the page.",
  422: "Some tickets are not valid. See the details below.",
  429: "The job queue is full right now.",
  503: "The model is still loading. This usually takes under a minute.",
};

export function friendlyMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return "Something went wrong. Please try again.";
  let msg = FRIENDLY[err.status] ?? `The server returned an error (${err.status}): ${err.message}`;
  if (err.status === 429 && err.retryAfter) msg += ` Try again in about ${err.retryAfter} s.`;
  return msg;
}

interface RequestOptions {
  method?: "GET" | "POST" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

export interface ApiResult<T> {
  data: T;
  status: number;
  headers: Headers;
  ms: number;
}

/**
 * Example: await request<Prediction>("/predict", { method: "POST", body: { channel: "chat", text: "hi" } })
 * Throws ApiError. A 401 also notifies `unauthorizedEvents` so the key dialog can open.
 */
export async function request<T>(path: string, { method = "GET", body, signal, headers = {} }: RequestOptions = {}): Promise<ApiResult<T>> {
  const key = apiKey.get();
  if (!key) {
    unauthorizedEvents.dispatchEvent(new Event("unauthorized"));
    throw new ApiError(401, "unauthorized", "No API key set.");
  }
  const h: Record<string, string> = { Accept: "application/json", "X-API-Key": key, ...headers };
  if (body !== undefined) h["Content-Type"] = "application/json";

  const t0 = performance.now();
  let res: Response;
  try {
    res = await fetch(apiUrl(path), { method, headers: h, body: body === undefined ? undefined : JSON.stringify(body), signal, cache: "no-store" });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "network_error", "Network request failed.");
  }
  const ms = Math.round(performance.now() - t0);

  let data: unknown = null;
  if (res.status !== 204) {
    const text = await res.text();
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = null;
    }
  }

  if (!res.ok) {
    const e = (data as { error?: { code?: string; message?: string; details?: ErrorDetail[] } } | null)?.error ?? {};
    const retry = Number.parseInt(res.headers.get("Retry-After") ?? "", 10);
    if (res.status === 401) unauthorizedEvents.dispatchEvent(new Event("unauthorized"));
    throw new ApiError(res.status, e.code ?? "http_error", e.message ?? res.statusText, Array.isArray(e.details) ? e.details : [], Number.isFinite(retry) ? retry : null);
  }
  return { data: data as T, status: res.status, headers: res.headers, ms };
}

/** Health is public and must never open the key dialog. status 0 = unreachable. */
export async function getHealth(): Promise<{ status: number; data: Health | null }> {
  try {
    const res = await fetch(apiUrl("/health"), { cache: "no-store", headers: { Accept: "application/json" } });
    const data = (await res.json().catch(() => null)) as Health | null;
    return { status: res.status, data };
  } catch {
    return { status: 0, data: null };
  }
}

/**
 * Check a key without running the model: an unknown job id answers 404 for a valid key, 401 otherwise.
 * Example: await verifyKey("s3cret") -> true | false   (throws ApiError(0) when offline)
 */
export async function verifyKey(key: string): Promise<boolean> {
  try {
    const res = await fetch(apiUrl("/batch/jobs/key-check"), { headers: { "X-API-Key": key, Accept: "application/json" }, cache: "no-store" });
    return res.status !== 401;
  } catch {
    throw new ApiError(0, "network_error", "Network request failed.");
  }
}
