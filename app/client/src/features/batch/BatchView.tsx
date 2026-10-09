// Batch view (team leads / managers): file → validated tickets → /predict/batch (≤ 100) or /batch/jobs (101–5,000).

import { useRef, useState, type DragEvent } from "react";
import { useFeedback } from "../../components/feedback";
import { Badge, Button, Card, Note, PanelHead } from "../../components/ui";
import { ApiError, friendlyMessage, request } from "../../lib/api";
import { download, fileBase, fmt, newIdempotencyKey, prefersReducedMotion } from "../../lib/format";
import { LIMITS, TEMPLATE_CSV, loadTickets, type Problem } from "../../lib/tickets";
import type { BatchResponse, JobStatus, ResultItem, TicketRow } from "../../lib/types";
import { jobStore } from "../jobs/jobStore";
import { ResultsView } from "../results/ResultsView";

const MAX_FILE_BYTES = 30 * 1024 * 1024; // a little above the 25 MB job body (JSON is larger than CSV)
const SHOW_PROBLEMS = 100;

interface Loaded {
  name: string;
  rows: TicketRow[];
  problems: Problem[];
  total: number;
  idemKey: string; // one per loaded file: retrying never starts a duplicate job
}

type FileState = { kind: "none" } | { kind: "error"; name: string; message: string } | { kind: "loaded"; file: Loaded };

interface SyncResult {
  title: string;
  fileBase: string;
  items: ResultItem[];
  processingMs?: number;
  modelVersion?: string;
}

function ProblemList({ problems }: { problems: Problem[] }) {
  return (
    <>
      <ul className="mt-2 max-h-56 list-disc overflow-y-auto pl-6 text-sm">
        {problems.slice(0, SHOW_PROBLEMS).map((p, i) => (
          <li key={i}>
            {p.row ? `Row ${p.row}: ` : ""}
            <code className="rounded bg-surface px-1">{p.field}</code> {p.issue}
          </li>
        ))}
      </ul>
      {problems.length > SHOW_PROBLEMS && <p className="mt-1 text-sm text-muted">…and {fmt.int(problems.length - SHOW_PROBLEMS)} more.</p>}
    </>
  );
}

export function BatchView({ onJobStarted }: { onJobStarted: () => void }) {
  const { toast } = useFeedback();
  const [file, setFile] = useState<FileState>({ kind: "none" });
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<unknown>(null);
  const [dragOver, setDragOver] = useState(false);
  const [result, setResult] = useState<SyncResult | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  const handleFile = async (f: File | undefined) => {
    setResult(null);
    setRunError(null);
    if (!f) return;
    if (f.size > MAX_FILE_BYTES) {
      return setFile({ kind: "error", name: f.name, message: `It is ${fmt.int(Math.round(f.size / 1024 / 1024))} MB. The limit is about 25 MB. Split it into smaller files.` });
    }
    let text: string;
    try {
      text = await f.text();
    } catch {
      return setFile({ kind: "error", name: f.name, message: "The browser couldn't read it." });
    }
    try {
      const parsed = loadTickets(f.name, text);
      if (!parsed.total) return setFile({ kind: "error", name: f.name, message: "It has no ticket rows." });
      setFile({ kind: "loaded", file: { name: f.name, ...parsed, idemKey: newIdempotencyKey() } });
    } catch (err) {
      setFile({ kind: "error", name: f.name, message: err instanceof Error ? err.message : String(err) });
    }
  };

  const reset = () => {
    setFile({ kind: "none" });
    setResult(null);
    setRunError(null);
    if (input.current) input.current.value = "";
    input.current?.focus();
  };

  const run = async (loaded: Loaded) => {
    const { name, rows } = loaded;
    const tickets = rows.map((r) => r.ticket);
    setRunning(true);
    setRunError(null);
    try {
      if (rows.length <= LIMITS.batch) {
        const { data } = await request<BatchResponse>("/predict/batch", { method: "POST", body: { tickets } });
        setResult({
          title: `Results: ${name}`,
          fileBase: fileBase(name),
          items: rows.map((r, i) => ({ ...r, prediction: data.predictions[i]! })),
          processingMs: data.meta?.processing_time_ms,
          modelVersion: data.meta?.model_version,
        });
        window.setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" }), 0);
      } else {
        const { data } = await request<JobStatus>("/batch/jobs", { method: "POST", body: { tickets }, headers: { "Idempotency-Key": loaded.idemKey } });
        jobStore.track(data, name, rows);
        toast(`Job started for ${fmt.int(rows.length)} tickets`);
        onJobStarted();
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 422 && err.details.length) {
        // Server-side row errors: index = position in the sent list → map back to file rows, drop those rows.
        const bad = new Set(err.details.map((d) => d.index));
        const extra = err.details.map((d) => ({ row: d.index !== undefined ? rows[d.index]?.row : null, field: d.field ?? "ticket", issue: d.issue ?? "" }));
        setFile({ kind: "loaded", file: { ...loaded, rows: rows.filter((_, i) => !bad.has(i)), problems: [...loaded.problems, ...extra] } });
        toast("The server rejected some rows. They are listed above.");
      } else {
        setRunError(err);
      }
    } finally {
      setRunning(false);
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    void handleFile(e.dataTransfer.files[0]);
  };

  return (
    <>
      <PanelHead title="Batch classification">
        Upload a CSV, JSON or JSONL file with up to 5,000 tickets. Up to 100 tickets are classified straight away. Larger files run as a background job that you can follow in <em>Jobs</em>.
      </PanelHead>

      <Card>
        <label
          htmlFor="file-input"
          onDragEnter={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragOver={(e) => e.preventDefault()}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className={`flex cursor-pointer flex-col items-center gap-2 rounded-card border-2 border-dashed px-4 py-8 text-center transition-colors focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-focus hover:border-accent hover:bg-accent-soft ${
            dragOver ? "border-accent bg-accent-soft" : "border-border-strong bg-surface-2"
          }`}
        >
          <input
            id="file-input"
            ref={input}
            type="file"
            accept=".csv,.json,.jsonl,.ndjson,.txt,text/csv,application/json"
            className="sr-only"
            onChange={(e) => void handleFile(e.target.files?.[0])}
          />
          <span aria-hidden="true" className="text-3xl text-accent">⇪</span>
          <span className="font-semibold">
            Drop a file here or <span className="text-accent underline">choose a file</span>
          </span>
          <span className="text-sm text-muted">
            Columns: <code>channel</code> (chat, email, call_transcript) and <code>text</code> are required. <code>subject</code> and <code>ticket_id</code> are optional. Other
            columns are kept in the export.
          </span>
        </label>
        <p className="mt-2 text-sm">
          <button type="button" className="cursor-pointer text-accent underline" onClick={() => download("tickets-template.csv", "﻿" + TEMPLATE_CSV, "text/csv")}>
            Download a CSV template
          </button>
        </p>

        {file.kind === "error" && (
          <div className="mt-4 border-t border-border pt-4">
            <span className="break-all font-semibold">{file.name}</span>
            <Note tone="danger" role="alert">
              <strong>Can't read this file. </strong>
              {file.message}
            </Note>
          </div>
        )}

        {file.kind === "loaded" && <LoadedFile file={file.file} running={running} onRun={run} onReset={reset} runError={runError} />}
      </Card>

      <div ref={resultsRef} className="scroll-mt-32">
        {result && <ResultsView {...result} />}
      </div>
    </>
  );
}

function LoadedFile({ file, running, onRun, onReset, runError }: { file: Loaded; running: boolean; onRun: (f: Loaded) => void; onReset: () => void; runError: unknown }) {
  const valid = file.rows.length;
  const asJob = valid > LIMITS.batch;
  const tooMany = valid > LIMITS.job;
  const badRows = new Set(file.problems.map((p) => p.row)).size;

  return (
    <div className="mt-4 border-t border-border pt-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="break-all font-semibold">{file.name}</span>
        <Badge>{fmt.int(file.total)} rows</Badge>
        {valid > 0 && <Badge tone="ok">{fmt.int(valid)} ready</Badge>}
        {badRows > 0 && <Badge tone="review">{fmt.int(badRows)} with problems</Badge>}
        <span className="flex-1" />
        <Button variant="ghost" onClick={onReset}>Choose another file</Button>
        <Button variant="primary" disabled={valid === 0 || tooMany} busy={running} busyLabel={asJob ? "Submitting…" : "Classifying…"} onClick={() => onRun(file)}>
          {asJob ? `Start background job (${fmt.int(valid)} tickets)` : `Classify ${fmt.int(valid)} ticket${valid === 1 ? "" : "s"}`}
        </Button>
      </div>

      {file.problems.length > 0 && (
        <Note tone="warning">
          <p>
            <strong>{fmt.int(badRows)} row{badRows === 1 ? "" : "s"} can't be sent. </strong>
            {valid ? "They are skipped. Fix them in the file and upload it again if you need them classified." : "Fix the file and upload it again."}
          </p>
          <ProblemList problems={file.problems} />
        </Note>
      )}
      {tooMany ? (
        <Note tone="danger">A job can hold at most {fmt.int(LIMITS.job)} tickets. Split the file into smaller parts.</Note>
      ) : (
        valid > 0 && (
          <p className="mt-2 text-sm text-muted">
            {asJob
              ? `More than ${LIMITS.batch} tickets: they run as a background job on the server. You can follow progress in Jobs and leave this page.`
              : "Up to 100 tickets are classified straight away."}
          </p>
        )
      )}
      {runError !== null && (
        <Note tone="danger" role="alert">
          {friendlyMessage(runError)}
        </Note>
      )}
    </div>
  );
}
