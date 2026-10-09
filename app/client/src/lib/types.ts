// API contract types (TensorForge Phase 2 OpenAPI v2.1.0, see app/server/contract/).

export type Channel = "email" | "chat" | "call_transcript";

export type Category =
  | "payment_refund"
  | "ride_trip_issue"
  | "lost_item"
  | "order_missing_wrong"
  | "delivery_delay"
  | "food_quality"
  | "account_promo"
  | "safety_conduct"
  | "app_technical"
  | "general_inquiry"
  | "spam_irrelevant";

export interface Ticket {
  ticket_id?: string;
  channel: Channel;
  subject?: string;
  text: string;
}

export interface Prediction {
  ticket_id?: string | null;
  category: Category;
  secondary_category: Category | null;
  team: string;
  is_urgent: boolean;
  confidence: number;
  model_version: string;
  needs_human_review?: boolean;
}

export interface BatchResponse {
  predictions: Prediction[];
  meta?: { count: number; model_version: string; processing_time_ms: number };
}

export type JobStatusName = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface JobStatus {
  job_id: string;
  status: JobStatusName;
  total: number;
  processed: number;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  expires_at?: string | null;
  model_version?: string | null;
  error?: { code: string; message: string } | null;
}

export interface JobResults {
  job_id: string;
  status: "succeeded";
  total: number;
  offset: number;
  limit: number;
  next_offset: number | null;
  model_version?: string | null;
  predictions: Prediction[];
}

export interface Health {
  status: "ok" | "loading";
  model_version: string | null;
  model_loaded?: boolean;
}

export interface ErrorDetail {
  index?: number;
  field?: string;
  issue?: string;
}

/** A ticket loaded from a file: its file row, the API ticket and the original record (for export). */
export interface TicketRow {
  row: number;
  ticket: Ticket & { ticket_id: string };
  source: Record<string, unknown>;
}

/** One line in a results view. ticket/source are absent for jobs opened after a page reload. */
export interface ResultItem {
  row?: number;
  ticket?: Ticket;
  source?: Record<string, unknown>;
  prediction: Prediction;
}
