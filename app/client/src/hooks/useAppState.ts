// App-level hooks: API key, live health, theme.

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { apiKey, getHealth } from "../lib/api";

/** Current API key (null when none); re-renders when it is set or cleared. */
export function useApiKey(): string | null {
  return useSyncExternalStore(apiKey.subscribe, apiKey.get);
}

export type HealthState =
  | { state: "unknown" }
  | { state: "ok"; modelVersion: string }
  | { state: "loading" }
  | { state: "down" };

/**
 * Polls the public /health endpoint: every 30 s when ready, 5 s while the model loads, 10 s when unreachable.
 * Refreshes immediately when the tab becomes visible again.
 */
export function useHealth(): HealthState {
  const [health, setHealth] = useState<HealthState>({ state: "unknown" });

  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;

    const poll = async () => {
      window.clearTimeout(timer);
      const { status, data } = await getHealth();
      if (cancelled) return;
      let next = 30_000;
      if (status === 200 && data?.status === "ok" && data.model_version) {
        setHealth({ state: "ok", modelVersion: data.model_version });
      } else if (status === 503) {
        setHealth({ state: "loading" });
        next = 5_000;
      } else {
        setHealth({ state: "down" });
        next = 10_000;
      }
      timer = window.setTimeout(poll, next);
    };

    const onVisible = () => !document.hidden && void poll();
    void poll();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  return health;
}

type Theme = "light" | "dark";

function effectiveTheme(): Theme {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Follows the OS until the user picks a theme; the pick is remembered (index.html applies it before paint). */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(effectiveTheme);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setTheme(effectiveTheme());
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const toggle = useCallback(() => {
    const next: Theme = effectiveTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("tf.theme", next);
    } catch {
      /* not persisted */
    }
    setTheme(next);
  }, []);

  return [theme, toggle];
}
