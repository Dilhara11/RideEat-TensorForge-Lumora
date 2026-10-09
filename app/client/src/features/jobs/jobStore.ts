// Background-job tracking, outside React so polling continues whichever view is open.
//
// The contract has no "list jobs" endpoint, so the ids of jobs started here are remembered in
// localStorage (best effort). Any other job can be opened by id. Polling follows the server's
// Retry-After and pauses while the browser tab is hidden. React reads it via useSyncExternalStore.

import { useSyncExternalStore } from "react";
import { ApiError, apiKey, request } from "../../lib/api";
import type { JobResults, JobStatus, Prediction, TicketRow } from "../../lib/types";

const STORE_KEY = "tf.jobs";
const RESULTS_PAGE = 1000;

export type JobState = JobStatus["status"] | "unknown" | "gone" | "expired";
export const TERMINAL: ReadonlySet<JobState> = new Set(["succeeded", "failed", "cancelled", "gone", "expired"]);
export const isActive = (s: JobState) => s === "queued" || s === "running";

export interface TrackedJob {
  id: string;
  label: string;
  addedAt: string;
  state: JobState;
  status: JobStatus | null;
  lastError: unknown; // transient poll failure (shown, polling continues)
  items?: TicketRow[]; // the uploaded rows, when this browser session started the job
}

interface Persisted {
  id: string;
  label: string;
  addedAt: string;
  total?: number;
}

class JobStore {
  private jobs = new Map<string, TrackedJob>();
  private timers = new Map<string, number>();
  private listeners = new Set<() => void>();
  private snapshot: TrackedJob[] = [];

  constructor() {
    for (const p of this.load()) this.jobs.set(p.id, { id: p.id, label: p.label, addedAt: p.addedAt, state: "unknown", status: null, lastError: null });
    this.publish(false);
    document.addEventListener("visibilitychange", () => !document.hidden && this.pollAll());
    apiKey.subscribe(() => this.pollAll());
    this.pollAll();
  }

  // ---- external-store plumbing ----
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };
  getSnapshot = () => this.snapshot;

  private publish(persist = true) {
    // Newest first; a new array/object identity so React re-renders.
    this.snapshot = [...this.jobs.values()].map((j) => ({ ...j })).sort((a, b) => b.addedAt.localeCompare(a.addedAt));
    if (persist) this.save();
    this.listeners.forEach((fn) => fn());
  }

  private load(): Persisted[] {
    try {
      const raw: unknown = JSON.parse(localStorage.getItem(STORE_KEY) ?? "[]");
      return Array.isArray(raw) ? raw.filter((j): j is Persisted => typeof j?.id === "string" && typeof j?.label === "string") : [];
    } catch {
      return [];
    }
  }

  private save() {
    try {
      const data: Persisted[] = [...this.jobs.values()].map((j) => ({ id: j.id, label: j.label, addedAt: j.addedAt, total: j.status?.total }));
      localStorage.setItem(STORE_KEY, JSON.stringify(data));
    } catch {
      /* storage blocked: jobs are kept for this page view only */
    }
  }

  private patch(id: string, change: Partial<TrackedJob>) {
    const job = this.jobs.get(id);
    if (!job) return;
    Object.assign(job, change);
    this.publish();
  }

  // ---- polling ----
  private pollAll() {
    this.jobs.forEach((j) => void this.poll(j.id));
  }

  async poll(id: string) {
    window.clearTimeout(this.timers.get(id));
    const job = this.jobs.get(id);
    if (!job || TERMINAL.has(job.state) || document.hidden || !apiKey.get()) return;
    let delay = 2;
    try {
      const { data, headers } = await request<JobStatus>(`/batch/jobs/${encodeURIComponent(id)}`);
      this.patch(id, { status: data, state: data.status, lastError: null });
      const ra = Number.parseInt(headers.get("Retry-After") ?? "", 10);
      if (Number.isFinite(ra) && ra > 0) delay = Math.min(ra, 30);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) this.patch(id, { state: "gone", lastError: null });
      else if (err instanceof ApiError && err.status === 410) this.patch(id, { state: "expired", lastError: null });
      else {
        this.patch(id, { lastError: err });
        if (err instanceof ApiError && err.status === 401) return; // resumes when a key is saved
        delay = 5;
      }
    }
    const after = this.jobs.get(id);
    if (after && !TERMINAL.has(after.state)) this.timers.set(id, window.setTimeout(() => void this.poll(id), delay * 1000));
  }

  // ---- actions ----
  /** Start tracking a job (from a 202 submit or "open by id"). items = uploaded rows when known. */
  track(status: JobStatus, label: string, items?: TicketRow[]) {
    const existing = this.jobs.get(status.job_id);
    if (existing) {
      this.patch(status.job_id, { status, state: status.status, ...(items ? { items } : {}) });
    } else {
      this.jobs.set(status.job_id, { id: status.job_id, label, addedAt: new Date().toISOString(), state: status.status, status, lastError: null, items });
      this.publish();
    }
    void this.poll(status.job_id);
  }

  forget(id: string) {
    window.clearTimeout(this.timers.get(id));
    this.jobs.delete(id);
    this.publish();
  }

  /** DELETE /batch/jobs/{id}: cancel a running job or discard a finished one. */
  async remove(id: string) {
    try {
      await request<null>(`/batch/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) throw err;
    }
    this.forget(id);
  }

  /** Fetch every page of results (offset/limit) in request order. */
  async results(id: string, onProgress?: (got: number, total: number) => void): Promise<{ predictions: Prediction[]; modelVersion: string | null }> {
    const predictions: Prediction[] = [];
    let offset = 0;
    let modelVersion: string | null = null;
    try {
      for (;;) {
        const { data } = await request<JobResults>(`/batch/jobs/${encodeURIComponent(id)}/results?offset=${offset}&limit=${RESULTS_PAGE}`);
        predictions.push(...data.predictions);
        modelVersion = data.model_version ?? null;
        onProgress?.(predictions.length, data.total);
        if (data.next_offset === null || data.next_offset === undefined) break;
        offset = data.next_offset;
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 410) this.patch(id, { state: "expired" });
      if (err instanceof ApiError && err.status === 404) this.patch(id, { state: "gone" });
      throw err;
    }
    return { predictions, modelVersion };
  }
}

export const jobStore = new JobStore();

export function useJobs(): TrackedJob[] {
  return useSyncExternalStore(jobStore.subscribe, jobStore.getSnapshot);
}
