"""Raw request-body handling in contract order: 415 -> 413 -> 400.

FastAPI's built-in body parsing would run *before* auth and answer malformed JSON with 422,
so protected endpoints read the body through `JsonBodyReader` instead.
"""

from __future__ import annotations

import json

from fastapi import Request

from .errors import MalformedJson, PayloadTooLarge, UnsupportedMediaType


class JsonBodyReader:
    """Reads and parses a JSON body with a byte cap.

    Example:
        reader = JsonBodyReader()
        await reader.read(request, limit=5 * 1024 * 1024)
          Content-Type: text/plain                 -> 415
          Content-Length: 6000000                  -> 413 (before reading anything)
          chunked body growing past the limit      -> 413 (stops reading at the cap)
          b'{"text": '                              -> 400
          b'{"channel": "chat", "text": "hi"}'     -> {"channel": "chat", "text": "hi"}
    """

    ACCEPTED_TYPES = {"application/json"}

    def check_content_type(self, request: Request) -> None:
        # Example: "application/json; charset=utf-8" -> ok; "" or "text/plain" -> 415
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type not in self.ACCEPTED_TYPES:
            raise UnsupportedMediaType()

    @staticmethod
    def check_declared_size(request: Request, limit: int) -> None:
        # Example: Content-Length: 26214401 with a 25 MB limit -> 413 without reading the body.
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    raise PayloadTooLarge()
            except ValueError:
                pass  # bogus header: the streamed read below still enforces the cap

    @staticmethod
    async def read_capped(request: Request, limit: int) -> bytes:
        # Stream the body and stop as soon as it exceeds the cap (protects memory on a 2 GB upload).
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise PayloadTooLarge()
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def parse(raw: bytes):
        # Example: b"\xff\xfe" (not UTF-8) -> 400; b"" -> 400; b'[1, 2]' -> [1, 2] (shape checked later -> 422)
        if not raw.strip():
            raise MalformedJson("Request body is empty; a JSON object is required.")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise MalformedJson() from None

    async def read(self, request: Request, limit: int):
        """Full pipeline in contract order (auth already ran as a dependency)."""
        self.check_content_type(request)
        self.check_declared_size(request, limit)
        raw = await self.read_capped(request, limit)
        return self.parse(raw)
