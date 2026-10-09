"""ASGI entry point.

Example:
    API_KEY=dev-key uvicorn tfengine.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import ROUTERS
from .config import Settings
from .engine import Engine
from .errors import install_error_handlers
from .middleware import RequestContextMiddleware


def configure_logging(level: str) -> None:
    # Example line: 2026-10-09 10:00:00 INFO tfengine.access POST /predict 200 41.2ms rid=-
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # replaced by tfengine.access


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    """Application factory.

    Example (tests): create_app(engine=Engine(settings, classifier_factory=FakeClassifier, model_version="t-1"))
    """
    settings = settings or (engine.settings if engine else Settings.from_env())
    configure_logging(settings.log_level)
    engine = engine or Engine(settings)

    # Lifespan: start model loading + job worker after the socket is bound, stop them on shutdown.
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await engine.start()
        try:
            yield
        finally:
            await engine.stop()

    app = FastAPI(
        title="TensorForge 2.0 - Support Ticket Classification API",
        version=__version__,
        description="Multilingual RideEat ticket classifier (category, secondary category, urgency, team). "
                    "Contract: TensorForge Phase 2 OpenAPI v2.1.0.",
        lifespan=lifespan,
    )
    app.state.engine = engine

    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    for router in ROUTERS:
        app.include_router(router)

    # Optional frontend assets (only when a build exists; never a catch-all mount at "/").
    if settings.frontend_dir.is_dir():
        app.mount("/static", StaticFiles(directory=settings.frontend_dir), name="static")
    return app


def __getattr__(name: str):
    # `uvicorn tfengine.main:app` -> build the app lazily on first access (keeps imports side-effect free).
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
