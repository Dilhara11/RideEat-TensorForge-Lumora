// Shared results view for Batch and Jobs (team leads / managers): KPI row, per-team load, filterable table, export.
// Every number shown is computed from the predictions actually returned. Nothing is invented.

import { useId, useMemo, useState } from "react";
import { Button, Card, Note, ReviewBadge, StatTile, UrgentBadge, cx } from "../../components/ui";
import { toCsv } from "../../lib/csv";
import { download, fmt } from "../../lib/format";
import { CHANNEL_LABEL, RESULT_COLUMNS, TEAMS, categoryLabel, flattenResult } from "../../lib/tickets";
import type { ResultItem } from "../../lib/types";

const PAGE = 50;

interface Props {
  title: string;
  fileBase: string;
  items: ResultItem[];
  processingMs?: number;
  modelVersion?: string | null;
  note?: string | null;
}

export function ResultsView({ title, fileBase, items, processingMs, modelVersion, note }: Props) {
  const [team, setTeam] = useState("");
  const [urgentOnly, setUrgentOnly] = useState(false);
  const [reviewOnly, setReviewOnly] = useState(false);
  const [page, setPage] = useState(0);
  const teamSelectId = useId();

  const stats = useMemo(() => {
    const preds = items.map((i) => i.prediction);
    const n = preds.length;
    const byTeam = new Map<string, number>(TEAMS.map((t) => [t, 0]));
    preds.forEach((p) => byTeam.set(p.team, (byTeam.get(p.team) ?? 0) + 1));
    return {
      n,
      urgent: preds.filter((p) => p.is_urgent).length,
      review: preds.filter((p) => p.needs_human_review).length,
      avgConf: n ? preds.reduce((s, p) => s + p.confidence, 0) / n : 0,
      teams: [...byTeam.entries()].filter(([, c]) => c > 0).sort((a, b) => b[1] - a[1]),
    };
  }, [items]);

  const filtered = useMemo(
    () => items.filter(({ prediction: p }) => (!team || p.team === team) && (!urgentOnly || p.is_urgent) && (!reviewOnly || p.needs_human_review)),
    [items, team, urgentOnly, reviewOnly],
  );
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE));
  const current = Math.min(page, pages - 1);
  const slice = filtered.slice(current * PAGE, current * PAGE + PAGE);
  const maxTeam = stats.teams[0]?.[1] ?? 1;

  const setFilter = (fn: () => void) => {
    fn();
    setPage(0);
  };

  const exportCsv = (rows: ResultItem[]) => {
    const records = rows.map(({ source, ticket, prediction }) => flattenResult(source ?? ticket, prediction));
    const inputCols: string[] = [];
    for (const r of records) for (const k of Object.keys(r)) if (!inputCols.includes(k) && !RESULT_COLUMNS.includes(k)) inputCols.push(k);
    download(`${fileBase}-classified.csv`, toCsv([...inputCols, ...RESULT_COLUMNS], records), "text/csv");
  };

  const { n } = stats;
  return (
    <section aria-label={title}>
      <h2 className="mb-3 text-lg font-semibold">{title}</h2>
      {note && <Note tone="info">{note}</Note>}

      <div className="mb-6 grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
        <StatTile label="Tickets classified" value={fmt.int(n)} />
        <StatTile label="Urgent" icon="▲" value={fmt.int(stats.urgent)} sub={n ? `${fmt.pct(stats.urgent / n)} of tickets` : null} />
        <StatTile label="Need human review" icon="●" value={fmt.int(stats.review)} sub={n ? `${fmt.pct(stats.review / n)} of tickets` : null} />
        <StatTile label="Average confidence" value={fmt.pct(stats.avgConf)} />
        {processingMs !== undefined && <StatTile label="Server time" value={fmt.ms(processingMs)} sub={modelVersion ? `model ${modelVersion}` : null} />}
      </div>

      {/* Tickets per team: one series, one hue, value at the tip, rounded data-end, square at the baseline. */}
      <Card>
        <h3 className="mb-1 font-semibold">Tickets per team</h3>
        <p className="mb-3 text-sm text-muted">Click a team to filter the table below.</p>
        <ul aria-label="Tickets per team">
          {stats.teams.map(([t, count]) => {
            const active = team === t;
            return (
              <li key={t}>
                <button
                  type="button"
                  aria-pressed={active}
                  title={`${t}: ${fmt.int(count)} tickets (${fmt.pct(count / n)}). Click to filter the table.`}
                  onClick={() => setFilter(() => setTeam(active ? "" : t))}
                  className="group grid w-full cursor-pointer grid-cols-[110px_minmax(0,1fr)] items-center gap-3 rounded-md py-1.5 text-left sm:grid-cols-[190px_minmax(0,1fr)]"
                >
                  <span className={cx("truncate text-right text-sm", active ? "font-semibold text-text" : "text-text-2")}>{t}</span>
                  <span className="flex min-w-0 items-center gap-2">
                    <span
                      className={cx("h-3.5 min-w-0.5 rounded-r transition-colors", active ? "bg-accent-hover" : "bg-mark group-hover:bg-accent-hover")}
                      style={{ width: `${(count / maxTeam) * 85}%` }}
                    />
                    <span className="whitespace-nowrap text-[13px] tabular-nums">
                      {fmt.int(count)} · {fmt.pct(count / n)}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </Card>

      <Card>
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor={teamSelectId} className="mb-1 block text-sm font-semibold">Team</label>
            <select id={teamSelectId} value={team} onChange={(e) => setFilter(() => setTeam(e.target.value))} className="control min-w-52">
              <option value="">All teams</option>
              {stats.teams.map(([t, c]) => (
                <option key={t} value={t}>{t} ({fmt.int(c)})</option>
              ))}
            </select>
          </div>
          <label className="flex min-h-11 cursor-pointer items-center gap-2">
            <input type="checkbox" className="size-4.5 accent-accent" checked={urgentOnly} onChange={(e) => setFilter(() => setUrgentOnly(e.target.checked))} />
            Urgent only
          </label>
          <label className="flex min-h-11 cursor-pointer items-center gap-2">
            <input type="checkbox" className="size-4.5 accent-accent" checked={reviewOnly} onChange={(e) => setFilter(() => setReviewOnly(e.target.checked))} />
            Needs review only
          </label>
          <span className="flex-1" />
          <Button onClick={() => exportCsv(filtered)}>Download filtered CSV</Button>
          <Button variant="primary" onClick={() => exportCsv(items)}>Download all (CSV)</Button>
        </div>

        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">Classification results for {title}</caption>
            <thead>
              <tr>
                {["Ticket", "Channel", "Text", "Category", "Team", "Secondary", "Urgent", "Confidence", "Review"].map((c) => (
                  <th key={c} scope="col" className={cx("sticky top-0 whitespace-nowrap border-b border-border bg-surface-2 px-3 py-2 text-left text-[13px] font-semibold text-text-2", c === "Confidence" && "text-right")}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {slice.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-3 text-muted">No tickets match these filters.</td>
                </tr>
              )}
              {slice.map(({ row, ticket, prediction: p }, i) => (
                <tr key={`${p.ticket_id ?? row ?? i}`} className="border-b border-border align-top last:border-b-0 hover:bg-surface-2">
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-[13px]">{p.ticket_id ?? (row ? `row ${row}` : "–")}</td>
                  <td className="px-3 py-2">{ticket ? CHANNEL_LABEL[ticket.channel] : "–"}</td>
                  <td className="px-3 py-2">
                    {ticket ? (
                      <div className="line-clamp-2-safe min-w-52 max-w-90" title={ticket.text}>
                        {ticket.subject ? `${ticket.subject}: ${ticket.text}` : ticket.text}
                      </div>
                    ) : (
                      <span className="text-muted">–</span>
                    )}
                  </td>
                  <td className="px-3 py-2">{categoryLabel(p.category)}</td>
                  <td className="px-3 py-2">{p.team}</td>
                  <td className="px-3 py-2">{p.secondary_category ? categoryLabel(p.secondary_category) : <span className="text-muted">–</span>}</td>
                  <td className="px-3 py-2">{p.is_urgent ? <UrgentBadge /> : <span className="text-muted">No</span>}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{fmt.pct(p.confidence)}</td>
                  <td className="px-3 py-2">{p.needs_human_review ? <ReviewBadge short /> : <span className="text-muted">–</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm text-muted" aria-live="polite">
            Showing {fmt.int(filtered.length ? current * PAGE + 1 : 0)}–{fmt.int(current * PAGE + slice.length)} of {fmt.int(filtered.length)}
            {filtered.length !== n && ` (filtered from ${fmt.int(n)})`}
          </span>
          <div className="flex gap-2">
            <Button size="sm" disabled={current === 0} onClick={() => setPage(current - 1)}>← Previous</Button>
            <Button size="sm" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>Next →</Button>
          </div>
        </div>
      </Card>
    </section>
  );
}
