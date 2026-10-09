"""`GET /health` (public)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..schemas import HealthResponseDoc
from .deps import get_engine

router = APIRouter(tags=["Core"])


@router.api_route(
    "/health", methods=["GET", "HEAD"], response_model=HealthResponseDoc,
    responses={503: {"model": HealthResponseDoc, "description": "Model not loaded yet"}},
)
async def health(request: Request) -> JSONResponse:
    """Readiness probe. No API key, no model call: answers in microseconds even during a job.

    Example: during startup -> 503 {"status": "loading", "model_version": null, "model_loaded": false}
             once ready     -> 200 {"status": "ok", "model_version": "v1.0-1a8163c34f54", "model_loaded": true}
    """
    svc = get_engine(request).inference
    if svc.is_ready:
        return JSONResponse({"status": "ok", "model_version": svc.model_version, "model_loaded": True})
    return JSONResponse({"status": "loading", "model_version": None, "model_loaded": False}, status_code=503,
                        headers={"Retry-After": "5"})
