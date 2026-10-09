// The routing decision for one ticket: category, team, urgency, review state, confidence meter.

import { Badge, Eyebrow, Note, ReviewBadge, UrgentBadge } from "../../components/ui";
import { fmt } from "../../lib/format";
import { CATEGORY, REVIEW_THRESHOLD, categoryLabel } from "../../lib/tickets";
import type { Prediction } from "../../lib/types";

function ConfidenceMeter({ confidence, low }: { confidence: number; low: boolean }) {
  const pct = Math.round(confidence * 100);
  return (
    <div className="my-4">
      <div className="mb-1 flex items-baseline justify-between">
        <span id="conf-label" className="text-sm font-semibold">Confidence in the category</span>
        <span className="text-xl font-semibold">{fmt.pct(confidence)}</span>
      </div>
      <div
        role="meter"
        aria-labelledby="conf-label"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-valuetext={`${fmt.pct(confidence)}${low ? ", below the review threshold" : ""}`}
        className={`relative h-2.5 rounded-full ${low ? "bg-warning-soft" : "bg-accent-track"}`}
      >
        <div className={`h-full rounded-full transition-[width] duration-300 ${low ? "bg-warning-fill" : "bg-mark"}`} style={{ width: `${Math.max(1, pct)}%` }} />
        <div
          className="absolute -top-1 -bottom-1 w-0.5 rounded-sm bg-text"
          style={{ left: `calc(${REVIEW_THRESHOLD * 100}% - 1px)` }}
          title={`Review threshold ${fmt.pct(REVIEW_THRESHOLD)}`}
        />
      </div>
      <div className="mt-1 flex justify-between text-xs text-muted">
        <span>0%</span>
        <span>review below {fmt.pct(REVIEW_THRESHOLD)}</span>
        <span>100%</span>
      </div>
    </div>
  );
}

export function PredictionCard({ p, ms }: { p: Prediction; ms?: number }) {
  const review = p.needs_human_review ?? p.confidence < REVIEW_THRESHOLD;
  const secondary = p.secondary_category;

  return (
    <div>
      <Eyebrow>Category</Eyebrow>
      <h2 className="text-[26px] font-semibold leading-tight">{categoryLabel(p.category)}</h2>
      <span className="font-mono text-[13px] text-muted">{p.category}</span>

      <div className="my-4 flex items-center gap-3 rounded-md bg-accent-soft px-4 py-3">
        <span aria-hidden="true" className="text-xl text-accent">➜</span>
        <div>
          <Eyebrow>Route to</Eyebrow>
          <div className="text-lg font-semibold">{p.team}</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {p.is_urgent ? <UrgentBadge /> : <Badge>Not urgent</Badge>}
        {review ? <ReviewBadge /> : <Badge tone="ok" icon="✓">Safe to auto-route</Badge>}
      </div>

      <ConfidenceMeter confidence={p.confidence} low={review} />

      <dl className="mb-4 grid grid-cols-2 gap-3">
        <div className="rounded-md bg-surface-2 p-3">
          <dt className="text-xs font-semibold uppercase tracking-wide text-muted">Secondary issue</dt>
          <dd className="mt-0.5 font-semibold">{secondary ? categoryLabel(secondary) : "None"}</dd>
        </div>
        <div className="rounded-md bg-surface-2 p-3">
          <dt className="text-xs font-semibold uppercase tracking-wide text-muted">Secondary team</dt>
          <dd className="mt-0.5 font-semibold">{secondary ? CATEGORY[secondary].team : "–"}</dd>
        </div>
      </dl>

      {p.is_urgent && (
        <Note tone="danger">
          <strong>Urgent. </strong>Handle this ticket first: the customer may be in danger, facing fraud, or about to suffer a serious time-critical problem.
        </Note>
      )}
      {review ? (
        <Note tone="warning">
          <strong>Check before routing. </strong>The model is less than {fmt.pct(REVIEW_THRESHOLD)} sure about the category. A person should confirm it.
        </Note>
      ) : (
        p.category === "spam_irrelevant" && <Note tone="info">Looks like spam or not a support request. It can be closed automatically.</Note>
      )}

      <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted">
        <span>
          Model <code className="rounded bg-surface-2 px-1">{p.model_version}</code>
        </span>
        {ms !== undefined && <span>Answered in {fmt.ms(ms)}</span>}
      </div>
      <details className="mt-3">
        <summary className="flex min-h-8 cursor-pointer items-center text-sm text-text-2">Show API response (JSON)</summary>
        <pre className="mt-2 overflow-x-auto rounded-md border border-border bg-surface-2 p-3 font-mono text-[13px]">{JSON.stringify(p, null, 2)}</pre>
      </details>
    </div>
  );
}
