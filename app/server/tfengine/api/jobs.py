"""Async batch job endpoints under `/batch/jobs` (API key required)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from ..errors import ErrorDetail, JobNotFound, ValidationFailed
from ..schemas import BatchJobResultsDoc, BatchJobStatusDoc, PredictRequestDoc, error_responses
from .deps import get_engine, require_api_key

router = APIRouter(prefix="/batch/jobs", tags=["Evaluation"], dependencies=[Depends(require_api_key)])

MAX_ID_LEN = 128  # contract: job_id and Idempotency-Key are at most 128 chars

_JOB_BODY = {"requestBody": {"required": True, "content": {"application/json": {"schema": {
    "type": "object", "required": ["tickets"],
    "properties": {"tickets": {"type": "array", "minItems": 1, "maxItems": 5000,
                               "items": PredictRequestDoc.model_json_schema()}},
}}}}}


def _check_job_id(job_id: str) -> None:
    # Example: a 300-char id can never exist -> 404 straight away.
    if len(job_id) > MAX_ID_LEN:
        raise JobNotFound()


@router.post("", status_code=202, response_model=BatchJobStatusDoc, openapi_extra=_JOB_BODY,
             responses=error_responses(400, 401, 413, 415, 422, 429))
async def submit_job(request: Request) -> JSONResponse:
    """Validate all tickets up front, store them, return 202 immediately.

    Example: 5,000 tickets -> 202 {"job_id": "7c9e...", "status": "queued", "total": 5000, "processed": 0, ...}
             headers Location: /batch/jobs/7c9e..., Retry-After: 2
    """
    engine = get_engine(request)
    body = await engine.body_reader.read(request, engine.settings.max_job_bytes)
    tickets = engine.validator.many(body, max_items=engine.settings.max_job_items)

    # Optional Idempotency-Key: same key -> same job (202 again), no duplicate work.
    idem = request.headers.get("idempotency-key")
    if idem is not None and (not idem.strip() or len(idem) > MAX_ID_LEN):
        raise ValidationFailed(details=[ErrorDetail(field="Idempotency-Key", issue="must be 1 to 128 characters")])

    status, _created = await engine.jobs.submit(tickets, idem)
    headers = {"Location": f"/batch/jobs/{status['job_id']}", "Retry-After": str(engine.jobs.SUBMIT_RETRY_AFTER_S)}
    return JSONResponse(status, status_code=202, headers=headers)


@router.get("/{job_id}", response_model=BatchJobStatusDoc, responses=error_responses(401, 404, 410))
async def get_job(job_id: str, request: Request) -> JSONResponse:
    """Poll progress. `Retry-After` is set while the job is queued/running.

    Example: {"status": "running", "total": 2000, "processed": 840, ...} + Retry-After: 2
    """
    _check_job_id(job_id)
    status, retry_after = await get_engine(request).jobs.status(job_id)
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    return JSONResponse(status, headers=headers)


@router.get("/{job_id}/results", response_model=BatchJobResultsDoc,
            responses=error_responses(401, 404, 409, 410, 422))
async def get_job_results(
    job_id: str,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1, le=5000),
) -> Response:
    """Predictions in request order; page with offset/limit (next_offset is null on the last page).

    Example: GET /batch/jobs/7c9e.../results?offset=0&limit=1000 -> 1000 predictions, next_offset=1000
    """
    _check_job_id(job_id)
    payload = await get_engine(request).jobs.results_json(job_id, offset, limit)
    return Response(content=payload.encode("utf-8"), media_type="application/json")


@router.delete("/{job_id}", status_code=204, responses=error_responses(401, 404))
async def delete_job(job_id: str, request: Request) -> Response:
    """Cancel a queued/running job or discard a finished one; afterwards the id returns 404."""
    _check_job_id(job_id)
    await get_engine(request).jobs.delete(job_id)
    return Response(status_code=204)
