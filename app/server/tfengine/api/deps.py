"""FastAPI dependencies shared by the routers."""

from __future__ import annotations

from fastapi import Request

from ..engine import Engine


def get_engine(request: Request) -> Engine:
    # Example: engine = get_engine(request); engine.inference.is_ready -> True
    return request.app.state.engine


async def require_api_key(request: Request) -> None:
    """Router-level dependency: runs before the handler touches the body (401 first)."""
    get_engine(request).auth.verify(request)
