"""Model lifecycle + scheduling: the "inference singleton" of the plan.

* The model loads on a background thread, so the server answers `/health` (503 "loading")
  immediately and flips to 200 once the session is ready.
* Every model call runs on ONE dedicated thread. ORT already uses 2 intra-op threads, so a single
  inference lane matches the 2-vCPU box and keeps the asyncio event loop free for `/health`,
  job polling and request parsing.
* Large requests are split into small chunks that queue FIFO on that lane, so a `/predict`
  arriving during a 5,000-ticket job waits for at most one chunk.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

from ..errors import ModelUnavailable
from ..validation import Ticket
from .classifier import TicketClassifier

log = logging.getLogger("tfengine.inference")


class ModelState(str, Enum):
    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"


class InferenceService:
    """Owns the classifier and the single inference thread.

    Example:
        svc = InferenceService(lambda: OnnxTicketClassifier(bundle), expected_version="v1.0-1a81...")
        svc.start()                      # returns immediately; loading happens on the lane
        svc.state                        -> ModelState.LOADING ... then READY
        await svc.predict(tickets)       -> list of prediction dicts (same order as tickets)
    """

    def __init__(self, factory: Callable[[], TicketClassifier], expected_version: str | None = None,
                 chunk_size: int = 8, ready_timeout_s: float = 60.0):
        self._factory = factory
        self._expected_version = expected_version
        self.chunk_size = max(1, chunk_size)
        self.ready_timeout_s = ready_timeout_s
        self._classifier: TicketClassifier | None = None
        self._state = ModelState.LOADING
        self._error: str | None = None
        self._ready = threading.Event()
        self._lane = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inference")
        self.load_seconds: float | None = None

    # --- lifecycle -----------------------------------------------------------------------
    @property
    def state(self) -> ModelState:
        return self._state

    @property
    def is_ready(self) -> bool:
        return self._state is ModelState.READY

    @property
    def model_version(self) -> str | None:
        # Only reported once loaded (contract: /health model_version is null while loading).
        return self._classifier.model_version if self.is_ready else None

    @property
    def expected_version(self) -> str | None:
        # Known from the bundle manifest before the session loads; used to stamp new jobs.
        return self._expected_version or self.model_version

    def _load(self) -> None:
        # Runs on the inference lane, so any prediction submitted meanwhile simply queues behind it.
        t0 = time.perf_counter()
        try:
            clf = self._factory()
            self._classifier = clf
            self._state = ModelState.READY
            self.load_seconds = time.perf_counter() - t0
            log.info("model ready: version=%s load_s=%.1f", clf.model_version, self.load_seconds)
        except Exception as e:  # keep serving /health (503) and log the reason
            self._state = ModelState.FAILED
            self._error = f"{type(e).__name__}: {e}"
            log.error("model failed to load: %s", self._error)
        finally:
            self._ready.set()

    def start(self) -> None:
        self._lane.submit(self._load)

    def shutdown(self) -> None:
        self._lane.shutdown(wait=False, cancel_futures=True)

    async def wait_ready(self, timeout_s: float | None = None) -> TicketClassifier:
        # Example: request arrives 3 s after boot -> waits until the model is ready (bounded).
        if not self._ready.is_set():
            timeout = self.ready_timeout_s if timeout_s is None else timeout_s
            await asyncio.to_thread(self._ready.wait, timeout)
        if self._state is ModelState.READY:
            return self._classifier
        if self._state is ModelState.FAILED:
            raise ModelUnavailable("Model failed to load. See server logs.")
        raise ModelUnavailable()

    # --- inference -----------------------------------------------------------------------
    async def predict(self, tickets: Sequence[Ticket]) -> list[dict]:
        """Predict in request order; chunks interleave fairly with other callers.

        Example: 100 tickets, chunk_size=8 -> 13 lane slots; a /predict arriving mid-way runs
        after the current slot instead of after all 100 tickets.
        """
        clf = await self.wait_ready()
        loop = asyncio.get_running_loop()
        out: list[dict] = []
        for i in range(0, len(tickets), self.chunk_size):
            chunk = tickets[i : i + self.chunk_size]
            out.extend(await loop.run_in_executor(self._lane, clf.predict, chunk))
        return out

    async def predict_chunk(self, tickets: Sequence[Ticket]) -> list[dict]:
        # One lane slot (used by the job worker, which persists progress after every chunk).
        clf = await self.wait_ready()
        return await asyncio.get_running_loop().run_in_executor(self._lane, clf.predict, tickets)
