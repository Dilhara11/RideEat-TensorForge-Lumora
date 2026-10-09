"""`GET /`: a small JSON service card.

The web client is a separate app (`app/client/`, hosted on its own origin such as AWS Amplify), so the API
never serves HTML: every route, including `/`, answers JSON.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import __version__
from .deps import get_engine

router = APIRouter(include_in_schema=False)


@router.get("/")
async def index(request: Request) -> JSONResponse:
    # Example: {"service": "TensorForge ticket classifier", "model_version": "v1.2-...", "docs": "/docs", ...}
    engine = get_engine(request)
    return JSONResponse({
        "service": "TensorForge ticket classifier",
        "engine_version": __version__,
        "model_version": engine.inference.model_version,
        "health": "/health",
        "docs": "/docs",
        "endpoints": ["/predict", "/predict/batch", "/batch/jobs"],
    })
