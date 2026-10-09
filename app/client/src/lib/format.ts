// Display formatting + browser file helpers.

export const fmt = {
  int: (n: number) => Number(n).toLocaleString(),
  pct: (x: number, digits = 0) => `${(x * 100).toFixed(digits)}%`,
  ms: (ms: number) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`),
  time: (iso: string | null | undefined) => {
    if (!iso) return "–";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  },
};

/** Save text as a file. Example: download("results.csv", csvText, "text/csv") */
export function download(filename: string, text: string, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Example: fileBase("My Tickets.csv") -> "My_Tickets" */
export const fileBase = (name: string) => name.replace(/\.[^.]+$/, "").replace(/[^\w.-]+/g, "_") || "tickets";

export const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function newIdempotencyKey(): string {
  // crypto.randomUUID needs a secure context (HTTPS or localhost); fall back elsewhere.
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
