// App shell: sidebar (desktop) / top bar (phones) with navigation, live health, API key and theme;
// views synced with the URL hash; status banners; footer.

import { useCallback, useEffect, useRef, useState } from "react";
import { Icon, type IconName } from "./components/icons";
import { KeyDialog, type KeyDialogHandle } from "./components/KeyDialog";
import { cx } from "./components/ui";
import { BatchView } from "./features/batch/BatchView";
import { ClassifyView } from "./features/classify/ClassifyView";
import { JobsView } from "./features/jobs/JobsView";
import { isActive, useJobs } from "./features/jobs/jobStore";
import { useApiKey, useHealth, useTheme, type HealthState } from "./hooks/useAppState";
import { API_BASE, API_BASE_MISSING } from "./lib/api";

const VIEWS: { id: string; label: string; hint: string; icon: IconName }[] = [
  { id: "classify", label: "Classify", hint: "One ticket, routed", icon: "tag" },
  { id: "batch", label: "Batch", hint: "Upload a file", icon: "upload" },
  { id: "jobs", label: "Jobs", hint: "Background work", icon: "layers" },
];
type ViewId = "classify" | "batch" | "jobs";

const fromHash = (): ViewId => {
  const h = window.location.hash.slice(1);
  return VIEWS.some((v) => v.id === h) ? (h as ViewId) : "classify";
};

const HEALTH_VIEW = {
  unknown: { dot: "bg-nav-muted", text: "Checking server…", short: "Checking" },
  ok: { dot: "bg-[#34d399]", text: "Model ready", short: "Ready" },
  loading: { dot: "bg-[#fbbf24]", text: "Model loading…", short: "Loading" },
  down: { dot: "bg-[#f87171]", text: "Server unreachable", short: "Offline" },
} as const;

function HealthStatus({ health, compact = false }: { health: HealthState; compact?: boolean }) {
  const v = HEALTH_VIEW[health.state];
  const version = health.state === "ok" ? health.modelVersion : null;
  const dot = (
    <span aria-hidden="true" className="relative flex size-2.5 shrink-0">
      {health.state === "ok" && <span className={cx("absolute inset-0 animate-ping rounded-full opacity-50", v.dot)} />}
      <span className={cx("relative size-2.5 rounded-full", v.dot)} />
    </span>
  );
  if (compact) {
    return (
      <span role="status" aria-live="polite" title={version ? `${v.text} · ${version}` : v.text} className="inline-flex items-center gap-2 rounded-full bg-nav-hover px-2.5 py-1 text-[12.5px] font-medium">
        {dot}
        <span>{v.short}</span>
        <span className="sr-only">{version ? `, model ${version}` : ""}</span>
      </span>
    );
  }
  return (
    <div role="status" aria-live="polite" className="rounded-xl border border-nav-border bg-nav-hover/70 p-3">
      <div className="flex items-center gap-2 text-[13px] font-semibold">
        {dot}
        {v.text}
      </div>
      <div className="mt-1 truncate pl-[18px] font-mono text-[11.5px] text-nav-muted" title={version ?? undefined}>
        {version ?? (health.state === "loading" ? "warming up" : "–")}
      </div>
    </div>
  );
}

function Brand({ sub = true }: { sub?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <span aria-hidden="true" className="grid size-9 place-items-center rounded-[10px] bg-brand text-white shadow-[0_4px_14px_-4px_var(--accent)]">
        <Icon name="route" size={18} />
      </span>
      <div className="leading-tight">
        <span className="block font-semibold tracking-tight">TensorForge</span>
        {sub && <span className="block text-[12px] text-nav-muted">Ticket routing console</span>}
      </div>
    </div>
  );
}

export default function App() {
  const [view, setView] = useState<ViewId>(fromHash);
  const health = useHealth();
  const key = useApiKey();
  const [theme, toggleTheme] = useTheme();
  const activeJobs = useJobs().filter((j) => isActive(j.state)).length;
  const keyDialog = useRef<KeyDialogHandle>(null);

  const show = useCallback((id: ViewId) => {
    setView(id);
    if (window.location.hash !== `#${id}`) window.history.replaceState(null, "", `#${id}`);
    window.scrollTo({ top: 0 });
  }, []);

  useEffect(() => {
    const onHash = () => setView(fromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const nextTheme = theme === "dark" ? "light" : "dark";
  const themeButton = (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={`Switch to ${nextTheme} theme`}
      title={`Switch to ${nextTheme} theme`}
      className="grid size-9 shrink-0 cursor-pointer place-items-center rounded-lg text-nav-muted transition-colors hover:bg-nav-hover hover:text-nav-text"
    >
      <Icon name={theme === "dark" ? "sun" : "moon"} size={17} />
    </button>
  );
  const jobsBadge = (id: string, onDark = true) =>
    id === "jobs" &&
    activeJobs > 0 && (
      <span
        aria-label={`${activeJobs} active`}
        className={cx("ml-auto inline-block min-w-5 rounded-full px-1.5 text-center text-[11.5px] font-semibold leading-5", onDark ? "bg-accent text-on-accent" : "bg-accent-soft text-accent")}
      >
        {activeJobs}
      </span>
    );

  return (
    <div className="min-h-screen lg:pl-64">
      <a href="#main" className="absolute -left-[9999px] top-0 z-50 rounded-md bg-surface px-3 py-2 focus:left-3 focus:top-3">Skip to content</a>

      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 flex-col border-r border-nav-border bg-nav-bg px-4 py-5 text-nav-text lg:flex">
        <div className="px-2">
          <Brand />
        </div>
        <nav aria-label="Sections" className="mt-8">
          <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[0.1em] text-nav-muted">Workspace</p>
          <ul className="space-y-1">
            {VIEWS.map((v) => {
              const on = view === v.id;
              return (
                <li key={v.id}>
                  <a
                    href={`#${v.id}`}
                    aria-current={on ? "page" : undefined}
                    onClick={(e) => {
                      e.preventDefault();
                      show(v.id as ViewId);
                    }}
                    className={cx(
                      "group relative flex items-center gap-3 rounded-lg px-3 py-2.5 no-underline transition-colors",
                      on ? "bg-nav-active text-nav-text" : "text-nav-muted hover:bg-nav-hover hover:text-nav-text",
                    )}
                  >
                    <span aria-hidden="true" className={cx("absolute inset-y-2 left-0 w-[3px] rounded-r-full bg-brand transition-opacity", on ? "opacity-100" : "opacity-0")} />
                    <Icon name={v.icon} size={18} className={on ? "text-[#a5b4fc]" : ""} />
                    <span className="min-w-0">
                      <span className="block text-[14.5px] font-semibold leading-tight">{v.label}</span>
                      <span className="block text-[12px] leading-tight text-nav-muted">{v.hint}</span>
                    </span>
                    {jobsBadge(v.id)}
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="mt-auto space-y-3">
          <HealthStatus health={health} />
          <div className="flex items-center gap-1">
            <button
              type="button"
              aria-haspopup="dialog"
              onClick={() => keyDialog.current?.open()}
              className="flex min-h-9 flex-1 cursor-pointer items-center gap-2 rounded-lg px-3 text-[13.5px] font-semibold text-nav-muted transition-colors hover:bg-nav-hover hover:text-nav-text"
            >
              <Icon name="key" size={16} />
              {key ? "API key set" : "Set API key"}
              {key ? <span aria-hidden="true" className="ml-auto size-1.5 rounded-full bg-[#34d399]" /> : <span aria-hidden="true" className="ml-auto size-1.5 rounded-full bg-[#fbbf24]" />}
            </button>
            {themeButton}
          </div>
        </div>
      </aside>

      {/* Phones / tablets: top bar */}
      <header className="sticky top-0 z-20 border-b border-nav-border bg-nav-bg text-nav-text lg:hidden">
        <div className="flex items-center gap-2 px-4 pb-2 pt-3">
          <Brand sub={false} />
          <span className="flex-1" />
          <HealthStatus health={health} compact />
          <button
            type="button"
            aria-haspopup="dialog"
            aria-label={key ? "API key set. Change it" : "Set API key"}
            title={key ? "API key set" : "Set API key"}
            onClick={() => keyDialog.current?.open()}
            className="relative grid size-9 cursor-pointer place-items-center rounded-lg text-nav-muted hover:bg-nav-hover hover:text-nav-text"
          >
            <Icon name="key" size={17} />
            <span aria-hidden="true" className={cx("absolute right-1.5 top-1.5 size-1.5 rounded-full", key ? "bg-[#34d399]" : "bg-[#fbbf24]")} />
          </button>
          {themeButton}
        </div>
        <nav aria-label="Sections" className="flex gap-1 overflow-x-auto px-3 pb-2">
          {VIEWS.map((v) => {
            const on = view === v.id;
            return (
              <a
                key={v.id}
                href={`#${v.id}`}
                aria-current={on ? "page" : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  show(v.id as ViewId);
                }}
                className={cx(
                  "flex min-h-10 items-center gap-2 whitespace-nowrap rounded-lg px-3.5 text-sm font-semibold no-underline transition-colors",
                  on ? "bg-nav-active text-nav-text" : "text-nav-muted hover:text-nav-text",
                )}
              >
                <Icon name={v.icon} size={16} />
                {v.label}
                {jobsBadge(v.id)}
              </a>
            );
          })}
        </nav>
      </header>

      <div className="mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-10">
        {API_BASE_MISSING && (
          <div role="alert" className="mt-6 flex gap-3 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3">
            <Icon name="alert" size={18} className="mt-0.5 text-danger" />
            <p>
              <strong>Not configured. </strong>This build doesn't know where the API is. Set <code>VITE_API_BASE_URL</code> (for example in the Amplify
              environment variables) and rebuild.
            </p>
          </div>
        )}
        {health.state === "loading" && (
          <div role="alert" className="mt-6 flex gap-3 rounded-xl border border-warning-fill/40 bg-warning-soft px-4 py-3">
            <Icon name="clock" size={18} className="mt-0.5 text-warning" />
            <p>The model is still loading. Classification will be available in a moment (usually under a minute).</p>
          </div>
        )}
        {health.state === "down" && !API_BASE_MISSING && (
          <div role="alert" className="mt-6 flex gap-3 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3">
            <Icon name="alert" size={18} className="mt-0.5 text-danger" />
            <p>
              Can't reach the classification API{API_BASE ? ` at ${API_BASE}` : ""}. Retrying automatically… If the API is running, check that its{" "}
              <code>CORS_ORIGINS</code> includes this site ({window.location.origin}).
            </p>
          </div>
        )}

        <main id="main" className="pb-10 pt-8 lg:pt-10">
          {/* Views stay mounted (hidden) so form input and results survive switching. */}
          {VIEWS.map((v) => (
            <section key={v.id} id={`panel-${v.id}`} data-view aria-label={v.label} hidden={view !== v.id}>
              {v.id === "classify" && <ClassifyView />}
              {v.id === "batch" && <BatchView onJobStarted={() => show("jobs")} />}
              {v.id === "jobs" && <JobsView />}
            </section>
          ))}
        </main>

        <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pb-8 pt-5 text-[13px] text-muted">
          <span className="inline-flex items-center gap-1.5">
            <Icon name="cpu" size={14} /> Model <code className="rounded bg-surface-2 px-1">{health.state === "ok" ? health.modelVersion : "–"}</code>
          </span>
          <span aria-hidden="true">·</span>
          <span>
            Predictions are suggestions. Tickets flagged <em>needs review</em> should be checked by a person.
          </span>
        </footer>
      </div>

      <KeyDialog ref={keyDialog} />
    </div>
  );
}
