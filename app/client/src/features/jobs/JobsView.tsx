// Jobs view (team leads, engineers): live progress, cancel/delete, view and download results.

import { useId, useRef, useState, type FormEvent } from "react";
import { useFeedback } from "../../components/feedback";
import { Icon, type IconName } from "../../components/icons";
import { Badge, Button, Card, EmptyState, FieldError, Note, PanelHead, cx } from "../../components/ui";
import { ApiError, friendlyMessage, request } from "../../lib/api";
import { download, fileBase, fmt, prefersReducedMotion } from "../../lib/format";
import type { JobStatus, ResultItem } from "../../lib/types";
import { ResultsView } from "../results/ResultsView";
import { isActive, jobStore, useJobs, type JobState, type TrackedJob } from "./jobStore";

const STATUS: Record<JobState, { label: string; tone: "info" | "ok" | "danger" | "neutral"; icon: IconName }> = {
  unknown: { label: "Checking…", tone: "neutral", icon: "clock" },
  queued: { label: "Queued", tone: "info", icon: "clock" },
  running: { label: "Running", tone: "info", icon: "activity" },
  succeeded: { label: "Finished", tone: "ok", icon: "checkCircle" },
  failed: { label: "Failed", tone: "danger", icon: "alert" },
  cancelled: { label: "Cancelled", tone: "neutral", icon: "stop" },
  gone: { label: "Not found", tone: "neutral", icon: "search" },
  expired: { label: "Expired", tone: "neutral", icon: "clock" },
};

interface Shown {
  jobId: string;
  title: string;
  fileBase: string;
  items: ResultItem[];
  modelVersion: string | null;
  note: string | null;
}

function JobCard({ job, onShow }: { job: TrackedJob; onShow: (s: Shown) => void }) {
  const { toast, confirm } = useFeedback();
  const [loading, setLoading] = useState<string | null>(null);
  const s = job.status;
  const total = s?.total ?? 0;
  const processed = job.state === "succeeded" ? total : (s?.processed ?? 0);
  const pct = total ? processed / total : 0;
  const status = STATUS[job.state];

  const fetchAll = async () => {
    setLoading("Loading…");
    try {
      return await jobStore.results(job.id, (got, t) => setLoading(`Loading ${fmt.int(got)} / ${fmt.int(t)}…`));
    } catch (err) {
      toast(friendlyMessage(err));
      return null;
    } finally {
      setLoading(null);
    }
  };

  const view = async () => {
    const res = await fetchAll();
    if (!res) return;
    const byId = new Map((job.items ?? []).map((i) => [i.ticket.ticket_id, i]));
    onShow({
      jobId: job.id,
      title: `Results: ${job.label}`,
      fileBase: fileBase(job.label),
      modelVersion: res.modelVersion,
      items: res.predictions.map((p) => ({ ...(byId.get(p.ticket_id ?? "") ?? {}), prediction: p })),
      note: job.items ? null : "The original ticket text isn't available in this browser (the page was reloaded), so the table and export show the predictions with their ticket IDs.",
    });
  };

  const downloadJson = async () => {
    const res = await fetchAll();
    if (res) {
      const body = { job_id: job.id, status: "succeeded", total: res.predictions.length, model_version: res.modelVersion, predictions: res.predictions };
      download(`job-${job.id}-results.json`, JSON.stringify(body, null, 2), "application/json");
    }
  };

  const remove = async () => {
    const running = isActive(job.state);
    const ok = await confirm(
      running
        ? { title: "Cancel this job?", body: "Tickets that are not processed yet won't be classified. This can't be undone.", okLabel: "Cancel job" }
        : { title: "Delete these results from the server?", body: "Anyone using this job ID will no longer be able to download the results. This can't be undone.", okLabel: "Delete results" },
    );
    if (!ok) return;
    try {
      await jobStore.remove(job.id);
      toast(running ? "Job cancelled" : "Results deleted");
    } catch (err) {
      toast(friendlyMessage(err));
    }
  };

  let message = null;
  if (job.state === "failed") {
    message = (
      <Note tone="danger">
        {s?.error?.code === "interrupted" ? "The server restarted while this job was running. Upload the file again to rerun it." : (s?.error?.message ?? "The job failed.")}
      </Note>
    );
  } else if (job.state === "gone") {
    message = <Note tone="warning">The server doesn't know this job. It was deleted, or the ID is wrong.</Note>;
  } else if (job.state === "expired") {
    message = <Note tone="warning">The results have expired (kept for 6 hours after the job finished).</Note>;
  } else if (job.lastError) {
    message = <Note tone="warning">{friendlyMessage(job.lastError)}</Note>;
  }

  return (
    <article aria-label={job.label} className="animate-fade-up rounded-card border border-border bg-surface p-4 shadow-card sm:p-5">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <span aria-hidden="true" className="grid size-10 shrink-0 place-items-center rounded-lg bg-surface-2 text-text-2">
          <Icon name="file" size={19} />
        </span>
        <div className="mr-auto min-w-0">
          <div className="break-all font-semibold">{job.label}</div>
          <div className="break-all font-mono text-[12.5px] text-muted">{job.id}</div>
        </div>
        <Badge tone={status.tone} icon={status.icon}>{status.label}</Badge>
      </div>

      <div className="mt-4">
        <div
          role="progressbar"
          aria-label={`Progress of ${job.label}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(pct * 100)}
          className="h-2 overflow-hidden rounded-full bg-accent-track"
        >
          <div
            className={cx(
              "h-full rounded-full transition-[width] duration-500 ease-out",
              job.state === "succeeded" ? "bg-success" : "bg-mark",
              job.state === "running" && "progress-stripes animate-stripes",
            )}
            style={{ width: `${pct * 100}%` }}
          />
        </div>
        <div className="mt-1 flex justify-between text-[13px] tabular-nums text-text-2">
          <span>{s ? `${fmt.int(processed)} of ${fmt.int(total)} tickets` : ""}</span>
          <span>{total ? fmt.pct(pct) : ""}</span>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted">
        <span>{s?.created_at ? `Started ${fmt.time(s.created_at)}` : `Added ${fmt.time(job.addedAt)}`}</span>
        {s?.finished_at && <span>Finished {fmt.time(s.finished_at)}</span>}
        {s?.expires_at && <span>Results kept until {fmt.time(s.expires_at)}</span>}
        {s?.model_version && (
          <span>
            Model <code className="rounded bg-surface-2 px-1">{s.model_version}</code>
          </span>
        )}
      </div>
      {message}

      <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-3">
        {job.state === "succeeded" && (
          <>
            <Button size="sm" variant="primary" icon="eye" busy={loading !== null} busyLabel={loading ?? undefined} onClick={view}>View results</Button>
            <Button size="sm" icon="download" disabled={loading !== null} onClick={downloadJson}>Download JSON</Button>
          </>
        )}
        {isActive(job.state) && <Button size="sm" variant="danger-ghost" icon="stop" onClick={remove}>Cancel job</Button>}
        {(job.state === "succeeded" || job.state === "failed" || job.state === "cancelled") && (
          <Button size="sm" variant="danger-ghost" icon="trash" onClick={remove}>Delete from server</Button>
        )}
        <Button size="sm" variant="ghost" title="Remove from this list only. The job stays on the server." onClick={() => jobStore.forget(job.id)}>
          Remove from list
        </Button>
      </div>
    </article>
  );
}

export function JobsView() {
  const jobs = useJobs();
  const [jobId, setJobId] = useState("");
  const [openError, setOpenError] = useState<string | null>(null);
  const [shown, setShown] = useState<Shown | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const errorId = useId();

  const openById = async (e: FormEvent) => {
    e.preventDefault();
    const id = jobId.trim();
    if (!id) return setOpenError("Enter a job ID.");
    setOpenError(null);
    try {
      const { data } = await request<JobStatus>(`/batch/jobs/${encodeURIComponent(id)}`);
      jobStore.track(data, `Job ${id.slice(0, 8)}`);
      setJobId("");
    } catch (ex) {
      setOpenError(ex instanceof ApiError && ex.status === 404 ? "No job with this ID. Check it and try again." : friendlyMessage(ex));
    }
  };

  const show = (s: Shown) => {
    setShown(s);
    window.setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" }), 0);
  };

  const visibleShown = shown && jobs.some((j) => j.id === shown.jobId) ? shown : null;

  return (
    <>
      <PanelHead eyebrow="Large files" title="Background jobs">
        Jobs started from this browser, with live progress. Results stay on the server for 6 hours after a job finishes. To follow a job started elsewhere, open it by its ID.
      </PanelHead>

      <Card>
        <form onSubmit={openById} noValidate>
          <label htmlFor="job-id-input" className="mb-1.5 block text-sm font-semibold">Open a job by ID</label>
          <div className="flex max-w-2xl gap-2">
            <input
              id="job-id-input"
              type="text"
              maxLength={128}
              autoComplete="off"
              spellCheck={false}
              placeholder="e.g. 7c9e6679-7425-40de-944b-e07fc1f90ae7"
              value={jobId}
              onChange={(e) => setJobId(e.target.value)}
              aria-invalid={Boolean(openError)}
              aria-describedby={openError ? errorId : undefined}
              className="control min-w-0 flex-1"
            />
            <Button type="submit" icon="search">Open</Button>
          </div>
          <FieldError id={errorId}>{openError}</FieldError>
        </form>
      </Card>

      <div className="mb-6 grid gap-3" aria-live="polite">
        {jobs.length === 0 ? (
          <Card>
            <EmptyState icon="layers" title="No jobs yet">Upload more than 100 tickets in Batch and the job shows up here.</EmptyState>
          </Card>
        ) : (
          jobs.map((j) => <JobCard key={j.id} job={j} onShow={show} />)
        )}
      </div>

      <div ref={resultsRef} className="scroll-mt-32">
        {visibleShown && (
          <ResultsView
            key={visibleShown.jobId}
            title={visibleShown.title}
            fileBase={visibleShown.fileBase}
            items={visibleShown.items}
            modelVersion={visibleShown.modelVersion}
            note={visibleShown.note}
          />
        )}
      </div>
    </>
  );
}
