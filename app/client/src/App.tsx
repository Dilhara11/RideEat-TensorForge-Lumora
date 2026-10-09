// App shell: header (health, key, theme), WAI-ARIA tabs synced with the URL hash, views, footer.

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { KeyDialog, type KeyDialogHandle } from "./components/KeyDialog";
import { cx } from "./components/ui";
import { ApiView } from "./features/api/ApiView";
import { BatchView } from "./features/batch/BatchView";
import { ClassifyView } from "./features/classify/ClassifyView";
import { JobsView } from "./features/jobs/JobsView";
import { isActive, useJobs } from "./features/jobs/jobStore";
import { useApiKey, useHealth, useTheme, type HealthState } from "./hooks/useAppState";
import { API_BASE, API_BASE_MISSING } from "./lib/api";

const TABS = [
  { id: "classify", label: "Classify" },
  { id: "batch", label: "Batch" },
  { id: "jobs", label: "Jobs" },
  { id: "api", label: "API" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const fromHash = (): TabId => {
  const h = window.location.hash.slice(1);
  return TABS.some((t) => t.id === h) ? (h as TabId) : "classify";
};

function HealthPill({ health }: { health: HealthState }) {
  const view = {
    unknown: { dot: "bg-muted", text: "Checking server…", title: "" },
    ok: { dot: "bg-success", text: health.state === "ok" ? `Model ready · ${health.modelVersion}` : "", title: health.state === "ok" ? `Server healthy. Model version ${health.modelVersion}` : "" },
    loading: { dot: "bg-warning-fill", text: "Model loading…", title: "The server is up and loading the model." },
    down: { dot: "bg-danger", text: "Server unreachable", title: "The health check failed." },
  }[health.state];
  return (
    <span role="status" aria-live="polite" title={view.title} className="inline-flex max-w-full items-center gap-2 rounded-full border border-border bg-surface-2 px-2.5 py-1 text-[13px]">
      <span aria-hidden="true" className={cx("size-2 shrink-0 rounded-full", view.dot)} />
      <span className="truncate">{view.text}</span>
    </span>
  );
}

function KeyIcon() {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="15" r="4" />
      <path d="M10.8 12.2 20 3M16 7l3 3M14 9l2 2" />
    </svg>
  );
}

export default function App() {
  const [tab, setTab] = useState<TabId>(fromHash);
  const health = useHealth();
  const key = useApiKey();
  const [theme, toggleTheme] = useTheme();
  const activeJobs = useJobs().filter((j) => isActive(j.state)).length;
  const keyDialog = useRef<KeyDialogHandle>(null);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const show = useCallback((id: TabId, focus = false) => {
    setTab(id);
    if (window.location.hash !== `#${id}`) window.history.replaceState(null, "", `#${id}`);
    if (focus) tabRefs.current[id]?.focus();
  }, []);

  useEffect(() => {
    const onHash = () => setTab(fromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const onTabKey = (e: KeyboardEvent) => {
    const idx = TABS.findIndex((t) => t.id === tab);
    const moves: Record<string, number> = { ArrowRight: idx + 1, ArrowLeft: idx - 1, Home: 0, End: TABS.length - 1 };
    const to = moves[e.key];
    if (to === undefined) return;
    e.preventDefault();
    show(TABS[(to + TABS.length) % TABS.length]!.id, true);
  };

  const nextTheme = theme === "dark" ? "light" : "dark";

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="absolute -left-[9999px] top-0 z-50 bg-surface px-3 py-2 focus:left-3 focus:top-3">Skip to content</a>

      <header className="top-0 z-10 border-b border-border bg-surface sm:sticky">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-4 pb-2 pt-3">
          <div className="flex items-center gap-3">
            <span aria-hidden="true" className="grid size-8 place-items-center rounded-[7px] bg-accent font-bold text-on-accent">T</span>
            <div>
              <span className="block font-semibold">TensorForge</span>
              <span className="hidden text-[13px] leading-tight text-muted sm:block">Support ticket classifier</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <HealthPill health={health} />
            <button
              type="button"
              aria-haspopup="dialog"
              onClick={() => keyDialog.current?.open()}
              className="inline-flex min-h-10 cursor-pointer items-center gap-1.5 rounded-md px-3 font-semibold hover:bg-surface-2"
            >
              <KeyIcon /> {key ? "API key set" : "Set API key"}
            </button>
            <button
              type="button"
              onClick={toggleTheme}
              aria-label={`Switch to ${nextTheme} theme`}
              title={`Switch to ${nextTheme} theme`}
              className="grid size-10 cursor-pointer place-items-center rounded-md text-lg hover:bg-surface-2"
            >
              <span aria-hidden="true">◐</span>
            </button>
          </div>
        </div>
        <nav aria-label="Sections" className="mx-auto w-full max-w-6xl px-4">
          <div role="tablist" aria-label="Sections" onKeyDown={onTabKey} className="flex gap-1 overflow-x-auto">
            {TABS.map((t) => (
              <button
                key={t.id}
                ref={(el) => {
                  tabRefs.current[t.id] = el;
                }}
                role="tab"
                id={`tab-${t.id}`}
                aria-controls={`panel-${t.id}`}
                aria-selected={tab === t.id}
                tabIndex={tab === t.id ? 0 : -1}
                onClick={() => show(t.id)}
                className={cx(
                  "min-h-11 cursor-pointer whitespace-nowrap border-b-2 px-4 py-3 font-semibold transition-colors",
                  tab === t.id ? "border-accent text-accent" : "border-transparent text-text-2 hover:text-text",
                )}
              >
                {t.label}
                {t.id === "jobs" && activeJobs > 0 && (
                  <span aria-label={`${activeJobs} active`} className="ml-1 inline-block min-w-5 rounded-full bg-accent-soft px-1.5 text-center text-xs leading-5 text-accent">
                    {activeJobs}
                  </span>
                )}
              </button>
            ))}
          </div>
        </nav>
      </header>

      {API_BASE_MISSING && (
        <div role="alert" className="mx-auto mt-4 w-full max-w-6xl px-4">
          <div className="rounded-md border border-danger bg-danger-soft px-4 py-3">
            <strong>Not configured. </strong>This build doesn't know where the API is. Set <code>VITE_API_BASE_URL</code> (for example in the Amplify
            environment variables) and rebuild.
          </div>
        </div>
      )}
      {health.state === "loading" && (
        <div role="alert" className="mx-auto mt-4 w-full max-w-6xl px-4">
          <div className="rounded-md border border-warning-fill bg-warning-soft px-4 py-3">
            The model is still loading. Classification will be available in a moment (usually under a minute).
          </div>
        </div>
      )}
      {health.state === "down" && !API_BASE_MISSING && (
        <div role="alert" className="mx-auto mt-4 w-full max-w-6xl px-4">
          <div className="rounded-md border border-danger bg-danger-soft px-4 py-3">
            Can't reach the classification API{API_BASE ? ` at ${API_BASE}` : ""}. Retrying automatically… If the API is running, check that its{" "}
            <code>CORS_ORIGINS</code> includes this site ({window.location.origin}).
          </div>
        </div>
      )}

      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 pb-8 pt-6">
        {/* Panels stay mounted (hidden) so form input and results survive tab switches. */}
        {TABS.map((t) => (
          <section key={t.id} id={`panel-${t.id}`} role="tabpanel" aria-labelledby={`tab-${t.id}`} tabIndex={0} hidden={tab !== t.id} className="focus:outline-none">
            {t.id === "classify" && <ClassifyView />}
            {t.id === "batch" && <BatchView onJobStarted={() => show("jobs")} />}
            {t.id === "jobs" && <JobsView />}
            {t.id === "api" && <ApiView />}
          </section>
        ))}
      </main>

      <footer className="mx-auto w-full max-w-6xl border-t border-border px-4 pb-6 pt-4 text-[13px] text-muted">
        Model <code className="rounded bg-surface-2 px-1">{health.state === "ok" ? health.modelVersion : "–"}</code> · Predictions are suggestions. Tickets flagged{" "}
        <em>needs review</em> should be checked by a person.
      </footer>

      <KeyDialog ref={keyDialog} />
    </div>
  );
}
