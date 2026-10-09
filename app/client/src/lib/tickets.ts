// Domain data shared by all views: category labels, the fixed team table, sample tickets,
// file → ticket loading and client-side validation that mirrors the API contract.

import { csvRecords } from "./csv";
import type { Category, Channel, Prediction, Ticket, TicketRow } from "./types";

export const CHANNELS: Channel[] = ["chat", "email", "call_transcript"];
export const CHANNEL_LABEL: Record<Channel, string> = { chat: "Chat", email: "Email", call_transcript: "Call transcript" };

// Contract limits (OpenAPI v2.1.0).
export const LIMITS = { text: 10_000, subject: 500, ticketId: 64, batch: 100, job: 5_000 } as const;

// The server flags needs_human_review below this confidence (inference_config.json review_threshold).
export const REVIEW_THRESHOLD = 0.7;

// Fixed category → team table from the contract. Example: CATEGORY.delivery_delay.team -> "Delivery Operations"
export const CATEGORY: Record<Category, { label: string; team: string }> = {
  payment_refund: { label: "Payment or refund", team: "Payments & Refunds" },
  ride_trip_issue: { label: "Ride or trip issue", team: "Ride Operations" },
  lost_item: { label: "Lost item", team: "Lost & Found" },
  order_missing_wrong: { label: "Order missing or wrong", team: "Food Operations" },
  delivery_delay: { label: "Delivery delay", team: "Delivery Operations" },
  food_quality: { label: "Food quality", team: "Restaurant Quality" },
  account_promo: { label: "Account or promo", team: "Account Services" },
  safety_conduct: { label: "Safety or conduct", team: "Trust & Safety" },
  app_technical: { label: "App technical problem", team: "Tech Support" },
  general_inquiry: { label: "General inquiry", team: "Front-line Support" },
  spam_irrelevant: { label: "Spam or irrelevant", team: "Auto-close / Spam Filter" },
};

export const TEAMS: string[] = Object.values(CATEGORY).map((c) => c.team);

export const categoryLabel = (code: Category | null | undefined): string => (code ? (CATEGORY[code]?.label ?? code) : "None");

export interface Sample {
  lang: string;
  code: string; // BCP 47 hint for screen readers
  channel: Channel;
  subject: string;
  text: string;
}

// One-click samples (judges, quick checks). Hand-written, in the style of the dataset.
// The last one is deliberately borderline so the needs-review path can be seen too.
export const SAMPLES: Sample[] = [
  { lang: "Sinhala", code: "si", channel: "chat", subject: "", text: "කාර් එකේ මගේ බෑග් එක අමතක වුණා, ඩ්‍රයිවර්ට කතා කරන්න පුළුවන්ද?" },
  { lang: "Tamil", code: "ta", channel: "chat", subject: "", text: "என் பையை டாக்சியில் மறந்துவிட்டேன், டிரைவரை தொடர்பு கொள்ள முடியுமா?" },
  { lang: "Singlish", code: "en", channel: "chat", subject: "", text: "bro mage order eka hour ekakata wada late, driver call ganne na. refund ekak denna" },
  { lang: "Tanglish", code: "en", channel: "chat", subject: "", text: "anna en food romba cold ah irundhuchu, taste um sari illa" },
  { lang: "English", code: "en", channel: "call_transcript", subject: "", text: "customer: hello hello yes uh the driver he is um he took a wrong turn and he's not stopping the car i am scared please" },
  { lang: "Mixed script", code: "si", channel: "chat", subject: "", text: "රිසිට් එකේ ගානට වඩා වැඩිපුර අය කරලා. I checked the receipt on my phone, please refund the extra amount." },
  { lang: "Tamil", code: "ta", channel: "call_transcript", subject: "", text: "agent: வணக்கம் customer: டிரைவர் ரொம்ப மோசமா பேசினார், பயமா இருக்கு" },
  { lang: "Spam", code: "en", channel: "email", subject: "Hello", text: "Purple umbrella dances under a quiet number. I am just typing to test this box. Nothing else to add." },
  { lang: "Ambiguous · shows review", code: "en", channel: "chat", subject: "", text: "Hi, the driver was rude and drove very fast, I felt unsafe during the ride yesterday." },
];

export interface Problem {
  row?: number | null;
  field: string;
  issue: string;
}

/** Validate one ticket like the server does. Example: validateTicket({channel: "fax", text: " "}) -> 2 problems */
export function validateTicket(t: { channel: string; text: string; subject?: string; ticket_id?: string }): Problem[] {
  const problems: Problem[] = [];
  if (!(CHANNELS as string[]).includes(t.channel)) {
    problems.push({ field: "channel", issue: t.channel ? `"${t.channel}" is not chat, email or call_transcript` : "is missing" });
  }
  if (typeof t.text !== "string" || !t.text.trim()) problems.push({ field: "text", issue: "is empty" });
  else if (t.text.length > LIMITS.text) problems.push({ field: "text", issue: `is longer than ${LIMITS.text.toLocaleString()} characters` });
  if (t.subject && t.subject.length > LIMITS.subject) problems.push({ field: "subject", issue: `is longer than ${LIMITS.subject} characters` });
  if (t.ticket_id && t.ticket_id.length > LIMITS.ticketId) problems.push({ field: "ticket_id", issue: `is longer than ${LIMITS.ticketId} characters` });
  return problems;
}

const str = (v: unknown): string => (v === null || v === undefined ? "" : typeof v === "string" ? v : String(v));
const INPUT_KEYS = new Set(["channel", "text", "subject", "ticket_id"]);

function isJsonName(name: string) {
  return /\.(jsonl|ndjson|json)$/i.test(name);
}

function parseRecords(name: string, text: string): unknown[] {
  const trimmed = text.replace(/^﻿/, "").trim();
  if (/\.(jsonl|ndjson)$/i.test(name)) {
    return trimmed
      .split(/\r?\n/)
      .filter((l) => l.trim())
      .map((line, i) => {
        try {
          return JSON.parse(line) as unknown;
        } catch {
          throw new Error(`Line ${i + 1} is not valid JSON.`);
        }
      });
  }
  if (isJsonName(name) || trimmed.startsWith("[") || trimmed.startsWith("{")) {
    let data: unknown;
    try {
      data = JSON.parse(trimmed);
    } catch {
      throw new Error("The file is not valid JSON.");
    }
    if (Array.isArray(data)) return data;
    const tickets = (data as { tickets?: unknown } | null)?.tickets;
    if (Array.isArray(tickets)) return tickets;
    throw new Error('JSON must be a list of tickets or an object with a "tickets" list.');
  }
  const { header, records } = csvRecords(trimmed);
  const cols = header.map((h) => h.toLowerCase());
  if (!cols.includes("text") || !cols.includes("channel")) {
    throw new Error('The CSV needs a header row with at least "channel" and "text" columns.');
  }
  // Normalise header case so "Text"/"Channel" work too.
  return records.map((r) => Object.fromEntries(Object.entries(r).map(([k, v]) => [INPUT_KEYS.has(k.toLowerCase()) ? k.toLowerCase() : k, v])));
}

export interface LoadedFile {
  rows: TicketRow[];
  problems: Problem[];
  total: number;
}

/**
 * Turn an uploaded file into API tickets + a per-row problem list.
 * Row numbers are file rows (header = row 1 for CSV, line 1 for JSONL, item 1 for JSON).
 * Example: loadTickets("t.csv", "channel,text\nchat,hi\nfax,") -> { rows: [row 2], problems: [row 3 ×2], total: 2 }
 */
export function loadTickets(name: string, text: string): LoadedFile {
  const records = parseRecords(name, text);
  const isCsv = !isJsonName(name) && !/^\s*[[{]/.test(text.replace(/^﻿/, ""));
  const rowOffset = isCsv ? 2 : 1;
  const hasIds = records.some((r) => str((r as Record<string, unknown> | null)?.ticket_id).trim());
  const seen = new Map<string, number>();
  const rows: TicketRow[] = [];
  const problems: Problem[] = [];

  records.forEach((rec, i) => {
    const row = i + rowOffset;
    if (!rec || typeof rec !== "object" || Array.isArray(rec)) {
      problems.push({ row, field: "row", issue: "is not a ticket object" });
      return;
    }
    const r = rec as Record<string, unknown>;
    const ticket = {
      ticket_id: hasIds ? str(r.ticket_id).trim() : `row-${row}`,
      channel: str(r.channel).trim().toLowerCase(),
      subject: str(r.subject),
      text: str(r.text),
    };
    const p = validateTicket(ticket);
    if (hasIds && !ticket.ticket_id) p.push({ field: "ticket_id", issue: "is empty (other rows have one)" });
    const firstRow = seen.get(ticket.ticket_id);
    if (ticket.ticket_id && firstRow !== undefined) p.push({ field: "ticket_id", issue: `"${ticket.ticket_id}" repeats row ${firstRow}` });
    else if (ticket.ticket_id) seen.set(ticket.ticket_id, row);
    if (p.length) p.forEach((x) => problems.push({ row, ...x }));
    else rows.push({ row, ticket: ticket as TicketRow["ticket"], source: r });
  });

  return { rows, problems, total: records.length };
}

/** Prediction columns appended to the export. */
export const RESULT_COLUMNS = ["category", "secondary_category", "team", "is_urgent", "confidence", "needs_human_review", "model_version"];

/** Example: flattenResult(source, prediction) -> { ...source columns, category, team, ..., confidence: "0.8231" } */
export function flattenResult(source: Record<string, unknown> | Ticket | undefined, p: Prediction): Record<string, unknown> {
  const out: Record<string, unknown> = { ...(source ?? {}) };
  if (!("ticket_id" in out)) out.ticket_id = p.ticket_id ?? "";
  out.category = p.category;
  out.secondary_category = p.secondary_category ?? "";
  out.team = p.team;
  out.is_urgent = p.is_urgent ? "true" : "false";
  out.confidence = p.confidence.toFixed(4);
  out.needs_human_review = p.needs_human_review === undefined ? "" : String(Boolean(p.needs_human_review));
  out.model_version = p.model_version;
  return out;
}

export const TEMPLATE_CSV =
  "ticket_id,channel,subject,text\r\n" +
  'T-001,chat,,"bro mage order eka late, refund ekak denna"\r\n' +
  'T-002,email,Payment issue,"I was charged twice for the same ride. Please refund."\r\n' +
  'T-003,call_transcript,,"agent: hello customer: என் ஆர்டர்ல ஒரு ஐட்டம் வரல"\r\n';
