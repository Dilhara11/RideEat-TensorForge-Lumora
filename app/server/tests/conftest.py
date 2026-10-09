"""Shared fixtures: a deterministic fake classifier + an app factory wired to a temp data dir.

The fake exercises the *real* decoder (business rules) on pseudo-logits derived from a hash of the
ticket, so contract tests run in milliseconds without the ONNX model.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

SERVER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_DIR.parents[1]
sys.path.insert(0, str(SERVER_DIR))

from tfengine.config import Settings  # noqa: E402
from tfengine.engine import Engine  # noqa: E402
from tfengine.inference import DecodeConfig, LabelSpace, PredictionDecoder, TicketClassifier  # noqa: E402
from tfengine.main import create_app  # noqa: E402

API_KEY = "test-key-123"
AUTH = {"X-API-Key": API_KEY}
SCHEMA_DIR = SERVER_DIR / "contract"  # organizers' OpenAPI spec + JSON Schemas (copied from the competition pack)
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeClassifier(TicketClassifier):
    """Deterministic stand-in for the ONNX model.

    Example: the same (channel, subject, text) always yields the same prediction; text containing
             "SPAMTEST" is forced to spam_irrelevant with high urgency/secondary logits, so the
             spam rule (is_urgent=False, secondary=None) is exercised.
    """

    model_version = "test-v1"

    def __init__(self, delay_s: float = 0.0, gate: threading.Event | None = None):
        self.delay_s = delay_s  # per-ticket sleep to simulate a slow model
        self.gate = gate  # when set, predict() blocks until the event is set (keeps jobs "running")
        self.decoder = PredictionDecoder(
            LabelSpace.contract_default(),
            DecodeConfig(temperature=1.0, urgency_threshold=0.5, secondary_threshold=0.3, review_threshold=0.4),
        )
        self.calls = 0

    @staticmethod
    def _logits(t):
        seed = int.from_bytes(hashlib.sha256(f"{t.channel}|{t.subject}|{t.text}".encode()).digest()[:8], "little")
        rng = np.random.default_rng(seed)
        cat, sec, urg = rng.normal(size=11) * 2, rng.normal(size=12) * 2, rng.normal(size=2)
        if "SPAMTEST" in t.text:
            cat[10] += 20  # spam_irrelevant
            urg[1] += 20  # model "thinks" urgent -> rule must force False
            sec[:10] += 20  # model "thinks" there is a secondary -> rule must force None
        return cat, sec, urg

    def predict(self, tickets):
        self.calls += 1
        if self.gate is not None:
            self.gate.wait(30)
        if self.delay_s:
            time.sleep(self.delay_s * len(tickets))
        rows = [self._logits(t) for t in tickets]
        return self.decoder.decode(np.stack([r[0] for r in rows]), np.stack([r[1] for r in rows]),
                                   np.stack([r[2] for r in rows]), [t.ticket_id for t in tickets],
                                   self.model_version)


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = Settings(
        api_key=API_KEY,
        data_dir=tmp_path / "data",
        sweep_interval_s=0.2,
        heartbeat_stale_s=30.0,
        predict_ready_timeout_s=5.0,
        log_level="WARNING",
    )
    return replace(base, **overrides)


@pytest.fixture
def make_client(tmp_path):
    """Factory: make_client(classifier=FakeClassifier(delay_s=0.01), max_queued_jobs=1) -> TestClient."""
    clients = []

    def _make(classifier: TicketClassifier | None = None, **overrides) -> TestClient:
        clf = classifier or FakeClassifier()
        settings = make_settings(tmp_path, **overrides)
        engine = Engine(settings, classifier_factory=lambda: clf, model_version=clf.model_version)
        client = TestClient(create_app(engine=engine), raise_server_exceptions=False)
        client.__enter__()  # runs lifespan: model "load" + job worker
        clients.append(client)
        wait_until(lambda: client.get("/health").status_code == 200)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


def wait_until(predicate, timeout: float = 10.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    raise AssertionError("condition not met in time")


def ticket(i: int | str = 0, **kw) -> dict:
    # Example: ticket(3) -> {"ticket_id": "T3", "channel": "chat", "subject": "", "text": "order 3 is late"}
    return {"ticket_id": f"T{i}", "channel": "chat", "subject": "", "text": f"order {i} is late", **kw}


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def validate():
    """validate("predict_response", body) -> raises jsonschema.ValidationError on contract violations."""
    jsonschema = pytest.importorskip("jsonschema")
    cache: dict[str, object] = {}

    def _validate(name: str, instance) -> None:
        if name not in cache:
            cache[name] = jsonschema.Draft202012Validator(load_schema(name))
        cache[name].validate(instance)

    return _validate
