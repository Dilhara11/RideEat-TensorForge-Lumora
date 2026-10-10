// One classification: category, urgency, review state, routing panel, confidence meter, secondary issue.

import type { ReactNode } from "react";
import { Icon } from "../../components/icons";
import { Badge, Eyebrow, Note, ReviewBadge, UrgentBadge, cx } from "../../components/ui";
import { fmt } from "../../lib/format";
import { CATEGORY, REVIEW_THRESHOLD, categoryLabel } from "../../lib/tickets";
import type { Prediction } from "../../lib/types";

function ConfidenceMeter({ confidence, low }: { confidence: number; low: boolean }) {
  const pct = Math.round(confidence * 100);
  return (
    <div className="my-5">
      <div className="mb-2 flex items-baseline justify-between">
        <span id="conf-label" className="text-sm font-semibold">Confidence in the category</span>
        <span className="text-2xl font-semibold tabular-nums tracking-tight">{fmt.pct(confidence)}</span>
      </div>
      <div
        role="meter"
        aria-labelledby="conf-label"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-valuetext={`${fmt.pct(confidence)}${low ? ", below the review threshold" : ""}`}
        className={cx("relative h-2.5 rounded-full", low ? "bg-warning-soft" : "bg-accent-track")}
      >
        <div
          className={cx("h-full origin-left animate-grow-x rounded-full", low ? "bg-warning-fill" : "bg-mark")}
          style={{ width: `${Math.max(1, pct)}%` }}
        />
        <div
          className="absolute -bottom-1.5 -top-1.5 w-0.5 rounded-sm bg-text"
          style={{ left: `calc(${REVIEW_THRESHOLD * 100}% - 1px)` }}
          title={`Review threshold ${fmt.pct(REVIEW_THRESHOLD)}`}
        />
      </div>
      <div className="relative mt-1.5 h-4 text-xs text-muted">
        <span className="absolute left-0">0%</span>
        <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${REVIEW_THRESHOLD * 100}%` }}>
          review below {fmt.pct(REVIEW_THRESHOLD)}
        </span>
        <span className="absolute right-0">100%</span>
      </div>
    </div>
  );
}

/** routing: the routing panel, shown right under the category. */
export function PredictionCard({ p, ms, routing }: { p: Prediction; ms?: number; routing?: ReactNode }) {
  const review = p.needs_human_review ?? p.confidence < REVIEW_THRESHOLD;
  const secondary = p.secondary_category;

  return (
    <div className="animate-fade-up">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Eyebrow>Category</Eyebrow>
          <h2 className="text-[26px] font-semibold leading-tight tracking-tight">{categoryLabel(p.category)}</h2>
          <span className="font-mono text-[12.5px] text-muted">{p.category}</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {p.is_urgent ? <UrgentBadge /> : <Badge icon="clock">Not urgent</Badge>}
          {review ? <ReviewBadge /> : <Badge tone="ok" icon="checkCircle">Confident</Badge>}
        </div>
      </div>

      {routing}

      <ConfidenceMeter confidence={p.confidence} low={review} />

      <dl className="mb-4 grid grid-cols-2 gap-3">
        <div className="rounded-lg border border-border bg-surface-2 p-3">
          <dt className="text-[11.5px] font-semibold uppercase tracking-[0.08em] text-muted">Secondary issue</dt>
          <dd className="mt-0.5 font-semibold">{secondary ? categoryLabel(secondary) : "None"}</dd>
        </div>
        <div className="rounded-lg border border-border bg-surface-2 p-3">
          <dt className="text-[11.5px] font-semibold uppercase tracking-[0.08em] text-muted">Secondary team</dt>
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


      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border pt-3 text-[13px] text-muted">
        <span className="inline-flex items-center gap-1.5">
          <Icon name="cpu" size={14} /> Model <code className="rounded bg-surface-2 px-1">{p.model_version}</code>
        </span>
        {ms !== undefined && (
          <span className="inline-flex items-center gap-1.5">
            <Icon name="clock" size={14} /> Answered in {fmt.ms(ms)}
          </span>
        )}
      </div>
    </div>
  );
}
