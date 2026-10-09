"""API-key authentication (`X-API-Key: <key>` or `Authorization: Bearer <key>`).

Runs as the *first* dependency of every protected route, so an unauthorized request never
reaches content-type/size/JSON checks or the model (contract check order: 401 first).
"""

from __future__ import annotations

import hmac

from fastapi import Request

from .errors import Unauthorized


class ApiKeyAuthenticator:
    """Constant-time API key check. The key itself is never logged or echoed.

    Example:
        auth = ApiKeyAuthenticator("s3cret")
        headers {"X-API-Key": "s3cret"}              -> passes
        headers {"Authorization": "Bearer s3cret"}   -> passes
        headers {}                                   -> 401 "Missing API key..."
        headers {"X-API-Key": "nope"}                -> 401 "Invalid API key."
        ApiKeyAuthenticator(None) + any header       -> 401 (service refuses to run open)
    """

    MISSING = "Missing API key. Send X-API-Key or Authorization Bearer."
    INVALID = "Invalid API key."

    def __init__(self, expected_key: str | None):
        # Stored as bytes once; None/"" disables every protected route (never "open").
        self._expected = expected_key.encode("utf-8") if expected_key else None

    @staticmethod
    def _candidates(request: Request) -> list[str]:
        # Collect every key the client offered.
        # Example: "Authorization: bearer abc" -> ["abc"] (scheme is case-insensitive)
        found = []
        x_key = request.headers.get("x-api-key")
        if x_key is not None:
            found.append(x_key.strip())
        auth = request.headers.get("authorization")
        if auth:
            scheme, _, token = auth.strip().partition(" ")
            if scheme.lower() == "bearer" and token.strip():
                found.append(token.strip())
        return found

    def _matches(self, candidate: str) -> bool:
        # hmac.compare_digest -> timing does not reveal how many leading bytes matched.
        # Starlette decodes headers as latin-1, so re-encode the same way to get the raw bytes.
        try:
            raw = candidate.encode("latin-1")
        except UnicodeEncodeError:
            return False
        return hmac.compare_digest(raw, self._expected)

    def verify(self, request: Request) -> None:
        """Raise `Unauthorized` unless one offered key matches."""
        candidates = self._candidates(request)
        if not candidates:
            raise Unauthorized(self.MISSING)
        if self._expected is None:
            # Key not configured on the server: refuse rather than accept anything.
            raise Unauthorized(self.INVALID)
        # Evaluate all candidates (no short-circuit) to keep timing uniform.
        results = [self._matches(c) for c in candidates]
        if not any(results):
            raise Unauthorized(self.INVALID)

    async def __call__(self, request: Request) -> None:
        # FastAPI dependency entry point: Depends(authenticator)
        self.verify(request)
