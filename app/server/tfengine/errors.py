"""Contract-shaped errors.

Every non-2xx body is `{"error": {"code": str, "message": str, "details"?: [...]}}` and never
contains a stack trace. Raising an `ApiError` subclass anywhere in a request turns into exactly
that body (see `install_error_handlers`).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("tfengine.errors")


@dataclass(frozen=True)
class ErrorDetail:
    """One field-level problem.

    Example: ErrorDetail(index=1, field="text", issue="must contain at least one non-whitespace character")
             -> {"index": 1, "field": "text", "issue": "must contain ..."}
    """

    field: str | None = None
    issue: str | None = None
    index: int | None = None

    def to_dict(self) -> dict:
        # Drop unset keys so single-ticket errors have no "index".
        return {k: v for k, v in asdict(self).items() if v is not None}


class ApiError(Exception):
    """Base class: status + machine code + human message (+ optional details/headers).

    Example: raise ApiError()  -> 500 {"error": {"code": "internal_error", ...}}
    """

    status_code: int = 500
    code: str = "internal_error"
    message: str = "Internal server error."

    def __init__(self, message: str | None = None, *, details: list[ErrorDetail] | None = None,
                 headers: dict[str, str] | None = None):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details or []
        self.headers = headers or {}

    def to_body(self) -> dict:
        # Example: {"error": {"code": "malformed_json", "message": "Request body is not valid JSON."}}
        err: dict = {"code": self.code, "message": self.message}
        if self.details:
            err["details"] = [d.to_dict() for d in self.details]
        return {"error": err}

    def to_response(self) -> JSONResponse:
        return JSONResponse(self.to_body(), status_code=self.status_code, headers=self.headers)


# --- one subclass per contract status code ------------------------------------------------
# Example mapping: missing key -> Unauthorized (401), text/plain body -> UnsupportedMediaType (415)


class Unauthorized(ApiError):
    status_code, code, message = 401, "unauthorized", "Invalid API key."

    def __init__(self, message: str | None = None):
        # Contract: 401 always carries `WWW-Authenticate: Bearer`.
        super().__init__(message, headers={"WWW-Authenticate": "Bearer"})


class UnsupportedMediaType(ApiError):
    status_code, code, message = 415, "unsupported_media_type", "Content-Type must be application/json."


class PayloadTooLarge(ApiError):
    status_code, code, message = 413, "payload_too_large", "Request body exceeds the maximum allowed size."


class MalformedJson(ApiError):
    status_code, code, message = 400, "malformed_json", "Request body is not valid JSON."


class ValidationFailed(ApiError):
    status_code, code, message = 422, "validation_error", "Request failed validation."


class JobNotFound(ApiError):
    status_code, code, message = 404, "job_not_found", "No job with this id."


class JobNotReady(ApiError):
    status_code, code = 409, "job_not_ready"

    def __init__(self, status: str):
        # Example: JobNotReady("running") -> "Job status is 'running'. Results are available once it is 'succeeded'."
        super().__init__(f"Job status is '{status}'. Results are available once it is 'succeeded'.")


class JobExpired(ApiError):
    status_code, code, message = 410, "job_expired", "Job results have expired."


class TooManyJobs(ApiError):
    status_code, code, message = 429, "too_many_jobs", "Job queue is full. Retry later."

    def __init__(self, retry_after_s: int):
        super().__init__(headers={"Retry-After": str(max(1, int(retry_after_s)))})


class ModelUnavailable(ApiError):
    status_code, code, message = 503, "model_unavailable", "Model is not loaded yet. Retry shortly."

    def __init__(self, message: str | None = None):
        super().__init__(message, headers={"Retry-After": "5"})


# Starlette's own HTTP errors (unknown route, wrong method) mapped to contract codes.
# Example: GET /nope -> 404 {"error": {"code": "not_found", ...}}; GET /predict -> 405 method_not_allowed
_HTTP_CODES = {
    400: ("bad_request", "Bad request."),
    404: ("not_found", "Resource not found."),
    405: ("method_not_allowed", "Method not allowed for this endpoint."),
}


def install_error_handlers(app: FastAPI) -> None:
    """Make every error path return contract JSON (never HTML, never a traceback)."""

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return exc.to_response()

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        # Example: POST /health -> 405 + Allow header kept from Starlette.
        code, message = _HTTP_CODES.get(exc.status_code, ("http_error", str(exc.detail)))
        body = {"error": {"code": code, "message": message}}
        return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError):
        # Only query/path params reach here (bodies are validated by TicketValidator).
        # Example: GET /batch/jobs/x/results?limit=0 -> 422 details=[{"field": "limit", "issue": "..."}]
        details = [
            ErrorDetail(field=str(e["loc"][-1]) if e.get("loc") else None, issue=e.get("msg", "invalid"))
            for e in exc.errors()
        ]
        return ValidationFailed(details=details).to_response()

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):
        # Last line of defence: log server-side, return a generic body to the client.
        log.exception("unhandled error: %s", type(exc).__name__)
        return ApiError().to_response()
