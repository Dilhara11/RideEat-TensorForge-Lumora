// Classify view (support agents, judges): one ticket in, routing decision out.

import { useEffect, useId, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Icon } from "../../components/icons";
import { Button, Card, EmptyState, FieldError, Kbd, Note, PanelHead, cx } from "../../components/ui";
import { ApiError, apiKey, friendlyMessage, request } from "../../lib/api";
import { fmt, prefersReducedMotion } from "../../lib/format";
import { CHANNELS, CHANNEL_LABEL, LIMITS, SAMPLES, validateTicket } from "../../lib/tickets";
import type { Channel, Prediction, Ticket } from "../../lib/types";
import { AutoRouteSwitch, RoutePanel } from "../routing/RoutingControls";
import { useAutoRoute, useRouting } from "../routing/routing";
import { CHANNEL_ICON } from "../routing/teams";
import { PredictionCard } from "./PredictionCard";

type Result =
  | { kind: "empty" }
  | { kind: "loading" }
  | { kind: "ok"; prediction: Prediction; ms: number; n: number }
  | { kind: "error"; error: unknown };

export function ClassifyView() {
  const [channel, setChannel] = useState<Channel>("chat");
  const [subject, setSubject] = useState("");
  const [text, setText] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [result, setResult] = useState<Result>({ kind: "empty" });
  const [auto] = useAutoRoute();
  const preds = useMemo(() => (result.kind === "ok" ? [result.prediction] : []), [result]);
  const routing = useRouting(preds, auto);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const runs = useRef(0);
  const inFlight = useRef<AbortController | null>(null);
  const retryAfterKey = useRef<Ticket | null>(null); // a 401 opened the key dialog: resume once a key is saved
  const errorId = useId();

  const classify = async (ticket: Ticket) => {
    const textProblem = validateTicket(ticket).find((p) => p.field === "text");
    if (textProblem) {
      setFieldError(textProblem.issue === "is empty" ? "Enter the ticket text." : `Ticket text ${textProblem.issue}.`);
      textRef.current?.focus();
      return;
    }
    setFieldError(null);
    inFlight.current?.abort();
    const ctrl = new AbortController();
    inFlight.current = ctrl;
    setResult({ kind: "loading" });
    // Single-column layout (phones, narrow windows): the result card is below the form, so bring it into view.
    if (window.matchMedia("(max-width: 1023px)").matches) {
      window.setTimeout(() => resultRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" }), 0);
    }
    try {
      const { data, ms } = await request<Prediction>("/predict", { method: "POST", body: ticket, signal: ctrl.signal });
      setResult({ kind: "ok", prediction: data, ms, n: ++runs.current });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      retryAfterKey.current = err instanceof ApiError && err.status === 401 ? ticket : null;
      setResult({ kind: "error", error: err });
    }
  };

  useEffect(
    () =>
      apiKey.subscribe(() => {
        const pending = retryAfterKey.current;
        if (pending && apiKey.get()) {
          retryAfterKey.current = null;
          void classify(pending);
        }
      }),
    [], // classify only uses refs and state setters: subscribe once
  );

  const current = (): Ticket => ({ channel, text, subject: channel === "email" ? subject : "" });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void classify(current());
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void classify(current());
    }
  };

  return (
    <>
      <PanelHead eyebrow="Single ticket" title="Classify & route a ticket" actions={<AutoRouteSwitch />}>
        Paste a ticket in English, Sinhala, Tamil, Singlish or Tanglish. Get its category, urgency and confidence, then route it to the right department.
      </PanelHead>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card className="mb-0">
          <form onSubmit={onSubmit} onKeyDown={onKeyDown} noValidate>
            <fieldset className="mb-5 min-w-0">
              <legend className="mb-1.5 text-sm font-semibold">Channel</legend>
              <div role="radiogroup" className="inline-flex max-w-full flex-wrap gap-1 rounded-xl border border-border bg-surface-2 p-1">
                {CHANNELS.map((c) => (
                  <label key={c} className="relative">
                    <input
                      type="radio"
                      name="channel"
                      value={c}
                      checked={channel === c}
                      onChange={() => setChannel(c)}
                      className="peer absolute inset-0 m-0 cursor-pointer opacity-0"
                    />
                    <span className="flex min-h-9 items-center gap-2 rounded-lg px-3.5 py-1.5 text-sm font-semibold text-text-2 transition-colors peer-checked:bg-surface peer-checked:text-accent peer-checked:shadow-card peer-hover:text-text peer-focus-visible:outline-2 peer-focus-visible:outline-focus">
                      <Icon name={CHANNEL_ICON[c]} size={15} />
                      {CHANNEL_LABEL[c]}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>

            {channel === "email" && (
              <div className="mb-4 animate-fade-up">
                <label htmlFor="subject" className="mb-1.5 block text-sm font-semibold">
                  Email subject <span className="font-normal text-muted">(optional)</span>
                </label>
                <input id="subject" type="text" maxLength={LIMITS.subject} autoComplete="off" value={subject} onChange={(e) => setSubject(e.target.value)} className="control" />
              </div>
            )}

            <div className="mb-5">
              <div className="flex items-baseline justify-between gap-2">
                <label htmlFor="text" className="mb-1.5 block text-sm font-semibold">Ticket text</label>
                <span className={cx("text-[13px] tabular-nums", text.length > LIMITS.text * 0.9 ? "text-warning" : "text-muted")}>
                  {fmt.int(text.length)} / {fmt.int(LIMITS.text)}
                </span>
              </div>
              <textarea
                id="text"
                ref={textRef}
                rows={8}
                maxLength={LIMITS.text}
                required
                placeholder="e.g. bro mage order eka hour ekakata wada late, refund ekak denna"
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  if (fieldError && e.target.value.trim()) setFieldError(null);
                }}
                aria-invalid={Boolean(fieldError)}
                aria-describedby={`text-hint ${fieldError ? errorId : ""}`}
                className="control min-h-44 resize-y leading-relaxed placeholder:text-muted/70"
              />
              <FieldError id={errorId}>{fieldError}</FieldError>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button type="submit" variant="primary" icon="tag" busy={result.kind === "loading"} busyLabel="Classifying…">Classify ticket</Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setText("");
                  setSubject("");
                  setChannel("chat");
                  setFieldError(null);
                  textRef.current?.focus();
                }}
              >
                Clear
              </Button>
              <p id="text-hint" className="ml-auto hidden text-[13px] text-muted sm:block">
                <Kbd>Ctrl</Kbd> + <Kbd>Enter</Kbd> to classify
              </p>
            </div>
          </form>

          <div className="mt-6 border-t border-border pt-5">
            <h2 className="mb-0.5 text-sm font-semibold">Try a sample ticket</h2>
            <p className="mb-3 text-[13px] text-muted">Real-style tickets in each supported language. Click one to fill the form and classify it.</p>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(210px,1fr))] gap-2">
              {SAMPLES.map((s, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => {
                    setChannel(s.channel);
                    setSubject(s.subject);
                    setText(s.text);
                    void classify({ channel: s.channel, subject: s.subject, text: s.text });
                  }}
                  className="group flex min-h-11 cursor-pointer flex-col gap-1 rounded-lg border border-border bg-surface px-3 py-2.5 text-left transition-[border-color,background-color,box-shadow] duration-150 hover:border-accent/50 hover:bg-accent-soft/60 hover:shadow-card"
                >
                  <span className="flex items-center gap-1.5 text-[11.5px] font-semibold uppercase tracking-[0.06em] text-accent">
                    <Icon name={CHANNEL_ICON[s.channel]} size={12} />
                    {s.lang}
                  </span>
                  <span lang={s.code} className="line-clamp-2-safe text-[13px] text-text-2 group-hover:text-text">{s.subject ? `${s.subject}: ${s.text}` : s.text}</span>
                </button>
              ))}
            </div>
          </div>
        </Card>

        <Card ref={resultRef} className="mb-0 min-h-80 scroll-mt-20 lg:sticky lg:top-6" aria-live="polite" aria-busy={result.kind === "loading"}>
          {result.kind === "empty" && (
            <EmptyState icon="route" title="No ticket classified yet">Write a ticket or pick a sample. The category, team and routing decision appear here.</EmptyState>
          )}
          {result.kind === "loading" && (
            <div className="animate-pulse">
              <p className="sr-only">Classifying…</p>
              <div className="mb-2 h-3 w-24 rounded bg-surface-3" />
              <div className="mb-6 h-8 w-3/5 rounded-md bg-surface-3" />
              <div className="mb-6 h-[78px] rounded-xl bg-surface-2" />
              <div className="mb-2 h-4 w-1/2 rounded bg-surface-3" />
              <div className="mb-6 h-2.5 rounded-full bg-surface-3" />
              <div className="grid grid-cols-2 gap-3">
                <div className="h-16 rounded-lg bg-surface-2" />
                <div className="h-16 rounded-lg bg-surface-2" />
              </div>
            </div>
          )}
          {result.kind === "error" && (
            <Note tone="danger" role="alert">
              <p>
                <strong>Couldn't classify this ticket. </strong>
                {friendlyMessage(result.error)}
              </p>
              {result.error instanceof ApiError && result.error.details.length > 0 && (
                <ul className="mt-2 list-disc pl-5 text-sm">
                  {result.error.details.map((d, i) => (
                    <li key={i}>{d.field ?? "ticket"}: {d.issue}</li>
                  ))}
                </ul>
              )}
            </Note>
          )}
          {result.kind === "ok" && (
            <PredictionCard
              key={result.n}
              p={result.prediction}
              ms={result.ms}
              routing={<RoutePanel p={result.prediction} routed={routing.get(0)} onRoute={(team) => routing.route(0, team)} onChange={() => routing.change(0)} />}
            />
          )}
        </Card>
      </div>

    </>
  );
}
