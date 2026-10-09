"""Composition root: builds every collaborator once and wires them together.

Routes reach it via `request.app.state.engine`; tests build it with a fake classifier factory.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .config import Settings
from .http import JsonBodyReader
from .inference import BundleError, InferenceService, ModelBundle, OnnxTicketClassifier, TicketClassifier
from .jobs import JobManager, JobWorker, SQLiteJobStore
from .security import ApiKeyAuthenticator
from .validation import TicketValidator

log = logging.getLogger("tfengine")


def onnx_factory(settings: Settings) -> tuple[Callable[[], TicketClassifier], str | None]:
    """Return (lazy classifier factory, model_version known from the manifest or None).

    Example: complete bundle   -> (factory, "v1.0-1a8163c34f54")
             missing tokenizer -> (factory that raises BundleError, None); /health stays 503 and
                                  the log names the missing files.
    """
    try:
        bundle = ModelBundle.open(settings.model_dir)
    except Exception as e:  # BundleError, bad JSON, label mismatch...
        err = e

        def failing() -> TicketClassifier:
            raise BundleError(str(err))

        return failing, None

    def build() -> TicketClassifier:
        if settings.verify_model_hash:
            bundle.verify_hash()
        return OnnxTicketClassifier(bundle, n_threads=settings.onnx_threads)

    return build, bundle.model_version


class Engine:
    """Example:
        engine = Engine(Settings.from_env())                   # real ONNX model
        engine = Engine(settings, classifier_factory=fake, model_version="test-v1")   # tests
        await engine.start(); ...; await engine.stop()
    """

    def __init__(self, settings: Settings, classifier_factory: Callable[[], TicketClassifier] | None = None,
                 model_version: str | None = None):
        self.settings = settings
        if classifier_factory is None:
            classifier_factory, model_version = onnx_factory(settings)

        # Request pipeline pieces (auth -> 415/413/400 -> 422).
        self.auth = ApiKeyAuthenticator(settings.api_key)
        self.body_reader = JsonBodyReader()
        self.validator = TicketValidator()

        # Model lane + job subsystem.
        self.inference = InferenceService(classifier_factory, expected_version=model_version,
                                          chunk_size=settings.job_chunk_size,
                                          ready_timeout_s=settings.predict_ready_timeout_s)
        self.store = SQLiteJobStore(settings.db_path, settings.job_retention_s, settings.tombstone_retention_s)
        self.jobs = JobManager(self.store, lambda: self.inference.expected_version,
                               settings.max_running_jobs, settings.max_queued_jobs)
        self.worker = JobWorker(self.store, self.inference, self.jobs.wakeup, chunk_size=settings.job_chunk_size,
                                max_running=settings.max_running_jobs, sweep_interval_s=settings.sweep_interval_s,
                                heartbeat_stale_s=settings.heartbeat_stale_s)

    async def start(self) -> None:
        if not self.settings.api_key:
            log.warning("API_KEY is not set: every protected endpoint will answer 401")
        self.inference.start()  # returns immediately; /health is 503 until the model is ready
        self.worker.start()

    async def stop(self) -> None:
        await self.worker.stop()
        self.inference.shutdown()
