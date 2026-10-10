// Ticket routing, done in the browser (the API classifies; it has no routing endpoint).
//
// Auto-routing ON:  confident tickets (no needs_human_review) are sent to the predicted team straight away;
//                   tickets below the review threshold wait for a person to pick the department.
// Auto-routing OFF: every ticket waits until someone clicks Route. The department can always be changed.
//
// The mode is a per-browser preference (localStorage, best effort), shared by every view.

import { useLayoutEffect, useState, useSyncExternalStore } from "react";
import { REVIEW_THRESHOLD } from "../../lib/tickets";
import type { Prediction } from "../../lib/types";

const MODE_KEY = "tf.autoRoute";

function readMode(): boolean {
  try {
    return localStorage.getItem(MODE_KEY) === "1";
  } catch {
    return false;
  }
}

let autoRoute = readMode();
const listeners = new Set<() => void>();

function setAutoRoute(on: boolean) {
  autoRoute = on;
  try {
    localStorage.setItem(MODE_KEY, on ? "1" : "0");
  } catch {
    /* not persisted */
  }
  listeners.forEach((fn) => fn());
}

const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
};

/** [auto-routing on?, setter]. Off by default: every ticket is routed by hand until it is switched on. */
export function useAutoRoute(): [boolean, (on: boolean) => void] {
  return [useSyncExternalStore(subscribe, () => autoRoute), setAutoRoute];
}

/** Example: needsReview({ confidence: 0.58, ... }) -> true */
export const needsReview = (p: Prediction) => p.needs_human_review ?? p.confidence < REVIEW_THRESHOLD;

export type Routed = { status: "routed"; team: string; by: "auto" | "manual" };
/** "hold" = someone pressed Change: it waits for a manual pick, and auto-routing leaves it alone. */
export type RouteEntry = Routed | { status: "hold" };

export interface Routing {
  /** Route of ticket i, or null while it waits for a person. */
  get: (i: number) => Routed | null;
  route: (i: number, team: string) => void;
  /** Reopen a routed ticket so its department can be changed. */
  change: (i: number) => void;
  routed: number;
  auto: number;
}

/**
 * Routing state for a list of predictions (index = position in the list). It resets when the list changes.
 * While auto-routing is on, confident tickets that nobody has touched are routed to their predicted team.
 */
export function useRouting(preds: Prediction[], auto: boolean): Routing {
  const [state, setState] = useState<{ preds: Prediction[]; map: Map<number, RouteEntry> }>({ preds, map: new Map() });
  const map = state.preds === preds ? state.map : new Map<number, RouteEntry>();

  // Layout effect: confident tickets show as routed on first paint, without flashing "Ready to route".
  useLayoutEffect(() => {
    setState((prev) => {
      const base = prev.preds === preds ? prev.map : new Map<number, RouteEntry>();
      if (!auto) return base === prev.map ? prev : { preds, map: base };
      let next: Map<number, RouteEntry> | null = null;
      for (let i = 0; i < preds.length; i++) {
        const p = preds[i]!;
        if (base.has(i) || needsReview(p)) continue;
        next ??= new Map(base);
        next.set(i, { status: "routed", team: p.team, by: "auto" });
      }
      if (next) return { preds, map: next };
      return base === prev.map ? prev : { preds, map: base };
    });
  }, [preds, auto]);

  const put = (i: number, entry: RouteEntry) =>
    setState((prev) => {
      const next = new Map(prev.preds === preds ? prev.map : undefined);
      next.set(i, entry);
      return { preds, map: next };
    });

  let routed = 0;
  let autoCount = 0;
  map.forEach((e) => {
    if (e.status === "routed") {
      routed++;
      if (e.by === "auto") autoCount++;
    }
  });

  return {
    get: (i) => {
      const e = map.get(i);
      return e?.status === "routed" ? e : null;
    },
    route: (i, team) => put(i, { status: "routed", team, by: "manual" }),
    change: (i) => put(i, { status: "hold" }),
    routed,
    auto: autoCount,
  };
}
