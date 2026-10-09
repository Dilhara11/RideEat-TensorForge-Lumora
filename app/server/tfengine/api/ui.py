"""`GET /`: the demo UI if a frontend build is present, otherwise a JSON service card.

The frontend itself is out of scope for the engine plan (see `architecture_frontend.md`); this is
only the integration point: put `index.html` in `FRONTEND_DIR` (assets are served under `/static`).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from .. import __version__
from .deps import get_engine

router = APIRouter(include_in_schema=False)


@router.get("/")
async def index(request: Request) -> Response:
    # Example: FRONTEND_DIR/index.html exists -> HTML page; otherwise
    #          {"service": "TensorForge ticket classifier", "docs": "/docs", "health": "/health", ...}
    engine = get_engine(request)
    page = engine.settings.frontend_dir / "index.html"
    if page.is_file():
        return FileResponse(page, media_type="text/html")
    return JSONResponse({
        "service": "TensorForge ticket classifier",
        "engine_version": __version__,
        "model_version": engine.inference.model_version,
        "health": "/health",
        "docs": "/docs",
        "endpoints": ["/predict", "/predict/batch", "/batch/jobs"],
    })
