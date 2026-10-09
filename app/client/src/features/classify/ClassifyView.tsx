// Classify view (support agents, judges): one ticket in, routing decision out.

import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Card, EmptyState, FieldError, Note, PanelHead, Button } from "../../components/ui";
import { ApiError, apiKey, friendlyMessage, request } from "../../lib/api";
import { fmt, prefersReducedMotion } from "../../lib/format";
import { CHANNELS, CHANNEL_LABEL, LIMITS, SAMPLES, validateTicket } from "../../lib/tickets";
import type { Channel, Prediction, Ticket } from "../../lib/types";
import { PredictionCard } from "./PredictionCard";

type Result =
  | { kind: "empty" }
  | { kind: "loading" }
  | { kind: "ok"; prediction: Prediction; ms: number }
  | { kind: "error"; error: unknown };

export function ClassifyView() {
  const [channel, setChannel] = useState<Channel>("chat");
  const [subject, setSubject] = useState("");
  const [text, setText] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [result, setResult] = useState<Result>({ kind: "empty" });
  const textRef = useRef<HTMLTextAreaElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
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
      setResult({ kind: "ok", prediction: data, ms });
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
      <PanelHead title="Classify a ticket">
        Paste a ticket in English, Sinhala, Tamil, Singlish or Tanglish. You get the category, the team to route it to, urgency and how confident the model is.
      </PanelHead>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Card>
          <form onSubmit={onSubmit} onKeyDown={onKeyDown} noValidate>
            <fieldset className="mb-4 min-w-0">
              <legend className="mb-1 text-sm font-semibold">Channel</legend>
              <div role="radiogroup" className="inline-flex flex-wrap overflow-hidden rounded-md border border-border-strong">
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
                    <span className="block min-h-[42px] border-r border-border px-4 py-2.5 font-semibold text-text-2 peer-checked:bg-accent peer-checked:text-on-accent peer-focus-visible:outline-2 peer-focus-visible:-outline-offset-4 peer-focus-visible:outline-focus">
                      {CHANNEL_LABEL[c]}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>

            {channel === "email" && (
              <div className="mb-4">
                <label htmlFor="subject" className="mb-1 block text-sm font-semibold">
                  Email subject <span className="font-normal text-muted">(optional)</span>
                </label>
                <input id="subject" type="text" maxLength={LIMITS.subject} autoComplete="off" value={subject} onChange={(e) => setSubject(e.target.value)} className="control" />
              </div>
            )}

            <div className="mb-4">
              <div className="flex items-baseline justify-between gap-2">
                <label htmlFor="text" className="mb-1 block text-sm font-semibold">Ticket text</label>
                <span className="text-sm text-muted">{fmt.int(text.length)} / {fmt.int(LIMITS.text)}</span>
              </div>
              <textarea
                id="text"
                ref={textRef}
                rows={8}
                maxLength={LIMITS.text}
                required
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  if (fieldError && e.target.value.trim()) setFieldError(null);
                }}
                aria-invalid={Boolean(fieldError)}
                aria-describedby={`text-hint ${fieldError ? errorId : ""}`}
                className="control min-h-40 resize-y leading-relaxed"
              />
              <p id="text-hint" className="mt-1 text-[13px] text-muted">
                Tip: press <kbd className="rounded border border-b-2 border-border-strong px-1">Ctrl</kbd> +{" "}
                <kbd className="rounded border border-b-2 border-border-strong px-1">Enter</kbd> to classify.
              </p>
              <FieldError id={errorId}>{fieldError}</FieldError>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button type="submit" variant="primary" busy={result.kind === "loading"} busyLabel="Classifying…">Classify</Button>
              <Button
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
            </div>
          </form>

          <div className="mt-6 border-t border-border pt-4">
            <h2 className="mb-1 font-semibold">Try a sample ticket</h2>
            <p className="mb-3 text-sm text-muted">Real-style tickets from each supported language. Click one to fill the form and classify it.</p>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-2">
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
                  className="flex min-h-11 cursor-pointer flex-col gap-0.5 rounded-md border border-border bg-surface-2 px-3 py-2 text-left transition-colors hover:border-accent hover:bg-accent-soft"
                >
                  <span className="text-xs font-semibold uppercase tracking-wide text-accent">{s.lang} · {CHANNEL_LABEL[s.channel]}</span>
                  <span lang={s.code} className="line-clamp-2-safe text-[13px] text-text-2">{s.subject ? `${s.subject}: ${s.text}` : s.text}</span>
                </button>
              ))}
            </div>
          </div>
        </Card>

        <Card ref={resultRef} className="min-h-80 scroll-mt-4 lg:sticky lg:top-32" aria-live="polite" aria-busy={result.kind === "loading"}>
          {result.kind === "empty" && (
            <EmptyState icon="⇢" title="No ticket classified yet.">Write a ticket or pick a sample. The result appears here.</EmptyState>
          )}
          {result.kind === "loading" && (
            <div className="animate-pulse">
              <p className="sr-only">Classifying…</p>
              <div className="mb-3 h-8 w-3/5 rounded-md bg-surface-2" />
              <div className="mb-3 h-4 rounded-md bg-surface-2" />
              <div className="mb-3 h-4 rounded-md bg-surface-2" />
              <div className="h-4 w-2/3 rounded-md bg-surface-2" />
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
          {result.kind === "ok" && <PredictionCard p={result.prediction} ms={result.ms} />}
        </Card>
      </div>
    </>
  );
}
