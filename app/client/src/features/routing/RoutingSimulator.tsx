// Routing replay: walks one prediction through intake → classifier → priority → confidence gate → dispatch,
// then lands it on the dispatch board. It is a visual replay of the real API answer: every outcome shown is
// derived from the returned prediction (category, team, is_urgent, confidence, needs_human_review, secondary).

import { forwardRef, useCallback, useEffect, useImperativeHandle, useState, type CSSProperties } from "react";
import { Icon, type IconName } from "../../components/icons";
import { Badge, Button, cx } from "../../components/ui";
import { fmt, prefersReducedMotion } from "../../lib/format";
import { CATEGORY, CHANNEL_LABEL, REVIEW_THRESHOLD, categoryLabel } from "../../lib/tickets";
import type { Prediction, Ticket } from "../../lib/types";
import { CHANNEL_ICON, DESTINATIONS, SPAM_TEAM, teamIcon } from "./teams";

const STEP_MS = 900;

type Tone = "accent" | "danger" | "warning" | "success" | "neutral";

interface Stage {
  title: string;
  icon: IconName;
  outcome: string;
  detail: string;
  tone: Tone;
}

interface Decision {
  review: boolean;
  closed: boolean; // spam, confidently: closed without a person
  ccTeam: string | null; // secondary issue owned by a different team
  stages: Stage[];
}

/** Derive every step of the replay from the prediction. Example: decide(p, ticket).stages.length -> 5 */
function decide(p: Prediction, ticket?: Ticket): Decision {
  const review = p.needs_human_review ?? p.confidence < REVIEW_THRESHOLD;
  const closed = p.team === SPAM_TEAM && !review;
  const secondTeam = p.secondary_category ? CATEGORY[p.secondary_category]?.team : null;
  const ccTeam = secondTeam && secondTeam !== p.team ? secondTeam : null;

  const stages: Stage[] = [
    {
      title: "Intake",
      icon: ticket ? CHANNEL_ICON[ticket.channel] : "inbox",
      outcome: ticket ? `${CHANNEL_LABEL[ticket.channel]} received` : "Ticket received",
      detail: p.ticket_id ? `ID ${p.ticket_id}` : ticket ? `${fmt.int(ticket.text.length)} characters` : "From the batch",
      tone: "accent",
    },
    {
      title: "Classifier",
      icon: "cpu",
      outcome: categoryLabel(p.category),
      detail: `${fmt.pct(p.confidence)} confident`,
      tone: "accent",
    },
    {
      title: "Priority check",
      icon: p.is_urgent ? "zap" : "clock",
      outcome: p.is_urgent ? "Urgent: priority lane" : "Standard queue",
      detail: p.is_urgent ? "Handled before everything else" : "No time-critical signal",
      tone: p.is_urgent ? "danger" : "neutral",
    },
    {
      title: "Confidence gate",
      icon: review ? "userCheck" : "checkCircle",
      outcome: review ? "Held for human review" : "Cleared to auto-route",
      detail: `${fmt.pct(p.confidence)} ${review ? "<" : "≥"} ${fmt.pct(REVIEW_THRESHOLD)} threshold`,
      tone: review ? "warning" : "success",
    },
    {
      title: "Dispatch",
      icon: teamIcon(p.team),
      outcome: closed ? "Auto-closed" : p.team,
      detail: closed ? "Not a support request" : review ? "After a person confirms" : ccTeam ? `CC ${ccTeam}` : "Assigned",
      tone: closed ? "neutral" : review ? "warning" : "accent",
    },
  ];
  return { review, closed, ccTeam, stages };
}

const DONE_NODE: Record<Tone, string> = {
  accent: "border-accent bg-accent text-on-accent",
  danger: "border-danger bg-danger text-on-danger",
  warning: "border-warning-fill bg-warning-fill text-[#1c1405]",
  success: "border-success bg-success text-surface",
  neutral: "border-border-strong bg-surface-3 text-text-2",
};

export interface RoutingSimulatorHandle {
  play: () => void;
}

interface Props {
  prediction: Prediction;
  ticket?: Ticket;
  autoPlay?: boolean;
}

export const RoutingSimulator = forwardRef<RoutingSimulatorHandle, Props>(function RoutingSimulator({ prediction: p, ticket, autoPlay = false }, ref) {
  const { review, closed, ccTeam, stages } = decide(p, ticket);
  const DONE = stages.length;
  const [step, setStep] = useState(-1); // -1 = not started, 0..DONE-1 = stage in progress, DONE = routed
  const [run, setRun] = useState(0); // restarts packet animations on replay

  const play = useCallback(() => {
    setRun((r) => r + 1);
    setStep(prefersReducedMotion() ? DONE : 0);
  }, [DONE]);

  useImperativeHandle(ref, () => ({ play }), [play]);

  useEffect(() => {
    if (autoPlay) play();
  }, [autoPlay, play]);

  useEffect(() => {
    if (step < 0 || step >= DONE) return;
    const t = window.setTimeout(() => setStep(step + 1), STEP_MS);
    return () => window.clearTimeout(t);
  }, [step, run, DONE]);

  const done = step >= DONE;
  const playing = step >= 0 && !done;
  const status = done
    ? closed
      ? "Closed automatically as spam."
      : `Routed to ${p.team}${review ? " after human review" : ""}${p.is_urgent ? " on the priority lane" : ""}.`
    : playing
      ? `Step ${step + 1} of ${DONE}: ${stages[step]!.title}…`
      : "Ready. Press Simulate routing to replay how this ticket is triaged.";

  return (
    <div>
      {/* Toolbar: what is being routed + controls */}
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-3 rounded-lg border border-border bg-surface-2 px-3 py-2">
          <span aria-hidden="true" className="grid size-8 shrink-0 place-items-center rounded-md bg-surface text-accent shadow-card">
            <Icon name={ticket ? CHANNEL_ICON[ticket.channel] : "inbox"} size={16} />
          </span>
          <div className="min-w-0">
            <div className="text-xs font-semibold text-muted">
              {p.ticket_id ? <span className="font-mono">{p.ticket_id}</span> : "This ticket"}
              {ticket && ` · ${CHANNEL_LABEL[ticket.channel]}`}
            </div>
            <div className="truncate text-sm text-text-2" title={ticket?.text}>
              {ticket ? (ticket.subject ? `${ticket.subject}: ${ticket.text}` : ticket.text) : `${categoryLabel(p.category)} → ${p.team}`}
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          {playing ? (
            <Button icon="skip" onClick={() => setStep(DONE)}>Skip to result</Button>
          ) : (
            <Button variant="primary" icon={done ? "replay" : "play"} onClick={play}>
              {done ? "Replay" : "Simulate routing"}
            </Button>
          )}
        </div>
      </div>

      <p role="status" aria-live="polite" className={cx("mb-5 flex items-center gap-2 text-sm", done ? "font-semibold text-text" : "text-muted")}>
        <span
          aria-hidden="true"
          className={cx("size-2 rounded-full", done ? (review ? "bg-warning-fill" : closed ? "bg-muted" : "bg-success") : playing ? "animate-pulse bg-accent" : "bg-border-strong")}
        />
        {status}
      </p>

      {/* Pipeline: vertical on phones, horizontal from md */}
      <ol aria-label="Routing steps" className="grid md:grid-cols-5">
        {stages.map((s, i) => {
          const state = i < step ? "done" : i === step ? "active" : "pending";
          const last = i === stages.length - 1;
          return (
            <li key={s.title} className={cx("relative flex gap-4 md:flex-col md:items-center md:gap-3 md:px-2 md:text-center", !last && "pb-7 md:pb-0")}>
              {!last && (
                <span
                  aria-hidden="true"
                  className="absolute bottom-0 left-[23px] top-[52px] w-0.5 rounded-full bg-border md:bottom-auto md:left-[calc(50%+30px)] md:right-[calc(-50%+30px)] md:top-[23px] md:h-0.5 md:w-auto"
                >
                  <span className="route-fill absolute inset-0 rounded-full bg-accent" style={{ "--p": step > i ? 1 : 0 } as CSSProperties} />
                  {step === i + 1 && (
                    <span
                      key={`${run}-${i}`}
                      className="route-packet absolute left-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent shadow-[0_0_0_4px_var(--accent-track),0_0_14px_var(--accent)] md:top-1/2"
                    />
                  )}
                </span>
              )}
              <span
                aria-hidden="true"
                className={cx(
                  "relative z-[1] grid size-12 shrink-0 place-items-center rounded-full border-2 transition-[background-color,border-color,color] duration-300",
                  state === "done" && DONE_NODE[s.tone],
                  state === "active" && "animate-ring border-accent bg-accent-soft text-accent",
                  state === "pending" && "border-border bg-surface text-muted",
                )}
              >
                <Icon name={s.icon} size={20} />
              </span>
              <div className="min-w-0 pt-1 md:pt-0">
                <div className={cx("text-[11.5px] font-semibold uppercase tracking-[0.08em]", state === "pending" ? "text-muted" : "text-text-2")}>
                  {s.title}
                  <span className="sr-only">{state === "done" ? ": done" : state === "active" ? ": in progress" : ": waiting"}</span>
                </div>
                {state === "done" ? (
                  <div key={`o-${run}`} className="animate-fade-up">
                    <div className="mt-0.5 font-semibold leading-snug">{s.outcome}</div>
                    <div className="text-[13px] text-muted">{s.detail}</div>
                  </div>
                ) : (
                  <div className="mt-0.5 text-[13px] text-muted">{state === "active" ? "Processing…" : "Waiting"}</div>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {/* Dispatch board: every destination queue; the chosen one lights up when the ticket lands. */}
      <div className="mt-8">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold">Dispatch board</h3>
          <span className="text-[13px] text-muted">{DESTINATIONS.length} team queues + human review desk</span>
        </div>
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
          <BoardTile
            name="Human review desk"
            icon="userCheck"
            state={done ? (review ? "review" : "idle-done") : "idle"}
            label={done && review ? "Holding" : undefined}
            run={run}
          />
          {DESTINATIONS.map((team) => {
            const target = team === p.team;
            const cc = team === ccTeam;
            return (
              <BoardTile
                key={team}
                name={team}
                icon={teamIcon(team)}
                state={done ? (target ? (review ? "tentative" : "target") : cc ? "cc" : "idle-done") : "idle"}
                label={done ? (target ? (closed ? "Closed" : review ? "Pending review" : "Assigned") : cc ? "CC · secondary" : undefined) : undefined}
                urgent={done && target && p.is_urgent}
                run={run}
              />
            );
          })}
        </ul>
      </div>
    </div>
  );
});

type TileState = "idle" | "idle-done" | "target" | "tentative" | "review" | "cc";

function BoardTile({ name, icon, state, label, urgent = false, run }: { name: string; icon: IconName; state: TileState; label?: string; urgent?: boolean; run: number }) {
  const hit = state === "target" || state === "tentative" || state === "review";
  return (
    <li
      key={hit ? `hit-${run}` : "idle"}
      className={cx(
        "relative flex min-h-[74px] flex-col justify-between gap-2 rounded-lg border p-3 transition-[opacity,border-color,background-color] duration-300",
        state === "idle" && "border-border bg-surface",
        state === "idle-done" && "border-border bg-surface opacity-45",
        state === "target" && "animate-pop-in border-accent bg-accent-soft shadow-lift ring-4 ring-accent/15",
        state === "tentative" && "animate-pop-in border-warning-fill bg-warning-soft shadow-lift",
        state === "review" && "animate-pop-in border-warning-fill bg-warning-soft shadow-lift ring-4 ring-warning-fill/15",
        state === "cc" && "border-dashed border-accent/70 bg-surface",
      )}
    >
      <div className="flex items-start gap-2">
        <span
          aria-hidden="true"
          className={cx(
            "grid size-7 shrink-0 place-items-center rounded-md",
            state === "target" ? "bg-accent text-on-accent" : hit ? "bg-warning-fill text-[#1c1405]" : state === "cc" ? "bg-accent-soft text-accent" : "bg-surface-2 text-muted",
          )}
        >
          <Icon name={icon} size={15} />
        </span>
        <span className={cx("text-[13px] leading-tight", hit || state === "cc" ? "font-semibold text-text" : "text-text-2")}>{name}</span>
      </div>
      {(label || urgent) && (
        <div className="flex flex-wrap gap-1">
          {label && (
            <Badge tone={state === "target" ? "info" : state === "cc" ? "neutral" : "review"} icon={state === "target" ? "check" : state === "cc" ? "arrowRight" : "clock"} small>
              {label}
            </Badge>
          )}
          {urgent && (
            <Badge tone="urgent" icon="zap" small>
              Priority
            </Badge>
          )}
        </div>
      )}
    </li>
  );
}
