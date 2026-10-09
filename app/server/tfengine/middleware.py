"""Pure-ASGI middleware: `X-Request-ID` echo + one access-log line per request.

Pure ASGI (not BaseHTTPMiddleware) so request bodies stream straight through to the handlers,
which enforce the size limit themselves, and so it adds no measurable latency.
"""

from __future__ import annotations

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("tfengine.access")

MAX_REQUEST_ID_LEN = 128


class RequestContextMiddleware:
    """Example:
        request  -> headers {"X-Request-ID": "abc-123"}
        response -> headers {"X-Request-ID": "abc-123"} (on every status, errors included)
        log      -> 'POST /predict 200 41.2ms rid=abc-123'   (never the API key or body)
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Read the client id from raw headers (bytes); ignore over-long values (contract maxLength 128).
        request_id = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                if len(value) <= MAX_REQUEST_ID_LEN:
                    request_id = value
                break

        start = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                if request_id is not None:
                    headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                    headers.append((b"x-request-id", request_id))
                    message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            ms = (time.perf_counter() - start) * 1000
            rid = request_id.decode("latin-1") if request_id else "-"
            # /health is polled constantly by load balancers: keep it at DEBUG.
            level = logging.DEBUG if scope.get("path") == "/health" else logging.INFO
            log.log(level, "%s %s %d %.1fms rid=%s", scope.get("method"), scope.get("path"),
                    status_holder["status"], ms, rid)
