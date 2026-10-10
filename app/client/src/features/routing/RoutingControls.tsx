// Routing UI: the auto-routing switch, the routing panel under a classification, and the compact table cell.

import { useEffect, useId, useRef, useState } from "react";
import { Icon } from "../../components/icons";
import { Button, Eyebrow, cx } from "../../components/ui";
import { fmt, prefersReducedMotion } from "../../lib/format";
import { REVIEW_THRESHOLD } from "../../lib/tickets";
import type { Prediction } from "../../lib/types";
import { needsReview, useAutoRoute, type Routed } from "./routing";
import { DESTINATIONS, teamIcon } from "./teams";

const SEND_MS = 450; // brief "Routing…" beat so the hand-off reads as an action

export function AutoRouteSwitch({ className }: { className?: string }) {
  const [on, setOn] = useAutoRoute();
  const labelId = useId();
  return (
    <div className={cx("inline-flex items-center gap-3 rounded-xl border border-border bg-surface py-2 pl-3.5 pr-2.5 shadow-card", className)}>
      <span className="w-[12.5rem] min-w-0">
        <span id={labelId} className="flex items-center gap-1.5 text-sm font-semibold">
          <Icon name="route" size={15} className={on ? "text-accent" : "text-muted"} />
          Auto-routing
        </span>
        <span className="block text-xs text-muted">{on ? `On: auto-sends ≥ ${fmt.pct(REVIEW_THRESHOLD)} confident` : "Off: you route every ticket"}</span>
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-labelledby={labelId}
        onClick={() => setOn(!on)}
        className={cx("relative h-6 w-11 shrink-0 cursor-pointer rounded-full transition-colors duration-200", on ? "bg-accent" : "bg-border-strong")}
      >
        <span aria-hidden="true" className={cx("absolute left-0.5 top-0.5 size-5 rounded-full bg-white shadow-card transition-transform duration-200", on && "translate-x-5")} />
      </button>
    </div>
  );
}

function TeamSelect({ value, suggested, onChange, small = false, label }: { value: string; suggested: string; onChange: (t: string) => void; small?: boolean; label: string }) {
  return (
    <div className="relative min-w-0 flex-1">
      <Icon name={teamIcon(value)} size={small ? 14 : 17} className={cx("pointer-events-none absolute top-1/2 -translate-y-1/2 text-accent", small ? "left-2.5" : "left-3")} />
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cx(
          small
            ? "min-h-8 w-full cursor-pointer rounded-md border border-border-strong bg-surface py-1 pl-8 pr-2 text-[13px] text-text focus-visible:border-focus"
            : "control cursor-pointer pl-10 font-semibold",
        )}
      >
        {DESTINATIONS.map((t) => (
          <option key={t} value={t}>
            {t}
            {t === suggested && !small ? " (suggested)" : ""}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Delays onRoute by a short beat (skipped with reduced motion). Example: const [sending, send] = useSend(onRoute) */
function useSend(onRoute: (team: string) => void): [boolean, (team: string) => void] {
  const [sending, setSending] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const send = (team: string) => {
    if (prefersReducedMotion()) return onRoute(team);
    setSending(true);
    timer.current = window.setTimeout(() => {
      setSending(false);
      onRoute(team);
    }, SEND_MS);
  };
  return [sending, send];
}

/** Under a single classification: route / auto-routed state, department picker, change. */
export function RoutePanel({ p, routed, onRoute, onChange }: { p: Prediction; routed: Routed | null; onRoute: (team: string) => void; onChange: () => void }) {
  const [auto, setAuto] = useAutoRoute();
  const [pick, setPick] = useState(p.team);
  const [sending, send] = useSend(onRoute);
  const review = needsReview(p);

  if (routed) {
    const changed = routed.team !== p.team;
    return (
      <div className="mt-5 flex animate-pop-in flex-wrap items-center gap-4 rounded-xl border border-success/30 bg-success-soft p-4">
        <span aria-hidden="true" className="relative grid size-11 shrink-0 place-items-center rounded-lg bg-success text-surface">
          <Icon name={teamIcon(routed.team)} size={21} />
          <span className="absolute -bottom-1 -right-1 grid size-5 place-items-center rounded-full bg-surface text-success ring-2 ring-success-soft">
            <Icon name="check" size={12} />
          </span>
        </span>
        <div className="min-w-0 flex-1">
          <Eyebrow>{routed.by === "auto" ? "Auto-routed to" : "Routed to"}</Eyebrow>
          <div className="text-lg font-semibold leading-tight">{routed.team}</div>
          <div className="mt-0.5 text-[13px] text-text-2">
            {routed.by === "auto"
              ? `${fmt.pct(p.confidence)} confident, so it was sent without review.`
              : changed
                ? `By you. Changed from the suggested ${p.team}.`
                : "By you."}
          </div>
        </div>
        <Button
          size="sm"
          variant="ghost"
          icon="edit"
          onClick={() => {
            setPick(routed.team);
            onChange();
          }}
        >
          Change
        </Button>
      </div>
    );
  }

  return (
    <div className={cx("mt-5 rounded-xl border p-4", review ? "border-warning-fill/40 bg-warning-soft" : "border-accent/20 bg-accent-soft")}>
      <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <Eyebrow>{review ? "Needs a person to route" : "Ready to route"}</Eyebrow>
        <span className="text-[13px] text-text-2">
          Suggested: <strong>{p.team}</strong>
        </span>
      </div>
      <div className="flex flex-wrap gap-2 sm:flex-nowrap">
        <TeamSelect value={pick} suggested={p.team} onChange={setPick} label="Department to route this ticket to" />
        <Button variant="primary" icon="send" busy={sending} busyLabel="Routing…" onClick={() => send(pick)} className="w-full sm:w-auto">
          Route
        </Button>
      </div>
      <p className="mt-2.5 text-[13px] text-text-2">
        {review ? (
          <>Below {fmt.pct(REVIEW_THRESHOLD)} confidence, so a person picks the department{auto ? ", even with auto-routing on" : ""}.</>
        ) : auto ? (
          <>You reopened this ticket. Pick a department and route it.</>
        ) : (
          <>
            Manual routing is on.{" "}
            <button type="button" onClick={() => setAuto(true)} className="cursor-pointer font-semibold text-accent underline-offset-2 hover:underline">
              Turn on auto-routing
            </button>{" "}
            to send confident tickets automatically.
          </>
        )}
      </p>
    </div>
  );
}

/** One table row: compact picker + Route, or the routed team with Change. */
export function RouteCell({ p, routed, ticketName, onRoute, onChange }: { p: Prediction; routed: Routed | null; ticketName: string; onRoute: (team: string) => void; onChange: () => void }) {
  const [pick, setPick] = useState(p.team);

  if (routed) {
    return (
      <div className="flex animate-fade-in items-center gap-2">
        <span className="grid size-5 shrink-0 place-items-center rounded-full bg-success-soft text-success">
          <Icon name="check" size={12} />
        </span>
        <span className="min-w-0">
          <span className="block max-w-44 truncate font-semibold" title={routed.team}>{routed.team}</span>
          <span className="block text-xs text-muted">{routed.by === "auto" ? "Auto-routed" : routed.team !== p.team ? "By you · changed" : "By you"}</span>
        </span>
        <button
          type="button"
          aria-label={`Change department for ${ticketName}`}
          title="Change department"
          onClick={() => {
            setPick(routed.team);
            onChange();
          }}
          className="ml-auto grid size-8 shrink-0 cursor-pointer place-items-center rounded-md text-muted hover:bg-surface-3 hover:text-text"
        >
          <Icon name="edit" size={15} />
        </button>
      </div>
    );
  }

  return (
    <div className="flex w-72 items-center gap-1.5">
      <TeamSelect small value={pick} suggested={p.team} onChange={setPick} label={`Department for ${ticketName}`} />
      <Button size="sm" variant={needsReview(p) ? "default" : "primary"} onClick={() => onRoute(pick)} aria-label={`Route ${ticketName} to ${pick}`}>
        Route
      </Button>
    </div>
  );
}
