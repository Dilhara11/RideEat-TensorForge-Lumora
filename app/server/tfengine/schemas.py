"""Pydantic models used to *document* the API in /docs and /openapi.json.

Handlers build plain dicts (exact key control: `secondary_category` is always present, even when
null) and return them directly; these models only describe the shapes for Swagger/Redoc.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "payment_refund", "ride_trip_issue", "lost_item", "order_missing_wrong", "delivery_delay", "food_quality",
    "account_promo", "safety_conduct", "app_technical", "general_inquiry", "spam_irrelevant",
]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class PredictRequestDoc(BaseModel):
    # Example: {"ticket_id": "TF-TE-000001", "channel": "chat", "subject": "", "text": "order eka late, refund ekak denna"}
    ticket_id: str | None = Field(None, max_length=64)
    channel: Literal["email", "chat", "call_transcript"]
    subject: str = Field("", max_length=500)
    text: str = Field(..., min_length=1, max_length=10_000)


class BatchRequestDoc(BaseModel):
    tickets: list[PredictRequestDoc] = Field(..., min_length=1)


class PredictResponseDoc(BaseModel):
    # Example: {"category": "delivery_delay", "secondary_category": "payment_refund", "team": "Delivery Operations", ...}
    ticket_id: str | None = None
    category: Category
    secondary_category: Category | None
    team: str
    is_urgent: bool
    confidence: float = Field(..., ge=0, le=1)
    model_version: str
    needs_human_review: bool | None = None


class BatchMetaDoc(BaseModel):
    count: int
    model_version: str
    processing_time_ms: int


class BatchResponseDoc(BaseModel):
    predictions: list[PredictResponseDoc]
    meta: BatchMetaDoc | None = None


class JobErrorDoc(BaseModel):
    code: str
    message: str


class BatchJobStatusDoc(BaseModel):
    job_id: str
    status: JobStatus
    total: int
    processed: int
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    expires_at: str | None = None
    model_version: str | None = None
    error: JobErrorDoc | None = None


class BatchJobResultsDoc(BaseModel):
    job_id: str
    status: Literal["succeeded"]
    total: int
    offset: int
    limit: int
    next_offset: int | None
    model_version: str | None = None
    predictions: list[PredictResponseDoc]


class HealthResponseDoc(BaseModel):
    status: Literal["ok", "loading"]
    model_version: str | None
    model_loaded: bool | None = None


class ErrorDetailDoc(BaseModel):
    index: int | None = None
    field: str | None = None
    issue: str | None = None


class ErrorBodyDoc(BaseModel):
    code: str
    message: str
    details: list[ErrorDetailDoc] | None = None


class ErrorResponseDoc(BaseModel):
    error: ErrorBodyDoc


def error_responses(*codes: int) -> dict:
    # Example: error_responses(401, 422) -> {401: {"model": ErrorResponseDoc, ...}, 422: {...}}
    text = {
        400: "Request body is not valid JSON", 401: "API key missing or invalid", 404: "Unknown job id",
        409: "Job has not succeeded", 410: "Job expired", 413: "Payload too large",
        415: "Content-Type must be application/json", 422: "Validation failed", 429: "Too many active jobs",
        503: "Model not loaded yet",
    }
    return {c: {"model": ErrorResponseDoc, "description": text.get(c, "Error")} for c in codes}
