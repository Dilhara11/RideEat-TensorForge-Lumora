"""End-to-end with the real ONNX bundle (skipped when the bundle is absent/incomplete).

Point it at a bundle with:  TFENGINE_TEST_MODEL_DIR=/path/to/models/winner pytest -m model
Default: training/models/winner.
"""

import json
import os
from pathlib import Path

import pytest

from conftest import AUTH, FIXTURES, REPO_ROOT, make_settings, wait_until
from tfengine.engine import Engine
from tfengine.inference import CONTRACT_TEAM_MAP, ModelBundle
from tfengine.main import create_app

pytestmark = pytest.mark.model

MODEL_DIR = Path(os.getenv("TFENGINE_TEST_MODEL_DIR", REPO_ROOT / "training" / "models" / "winner"))


@pytest.fixture(scope="module")
def real_client(tmp_path_factory):
    try:
        ModelBundle.open(MODEL_DIR)
    except Exception as e:
        pytest.skip(f"model bundle not usable: {e}")
    from fastapi.testclient import TestClient

    settings = make_settings(tmp_path_factory.mktemp("model"), model_dir=MODEL_DIR)
    client = TestClient(create_app(engine=Engine(settings)), raise_server_exceptions=False)
    with client:
        wait_until(lambda: client.get("/health").status_code == 200, timeout=120)
        yield client


def _fixture_tickets():
    return json.loads((FIXTURES / "multilingual_tickets.json").read_text(encoding="utf-8"))


def test_health_reports_bundle_version(real_client):
    body = real_client.get("/health").json()
    assert body == {"status": "ok", "model_version": ModelBundle.open(MODEL_DIR).model_version, "model_loaded": True}


@pytest.mark.parametrize("case", _fixture_tickets(), ids=lambda c: c["ticket_id"])
def test_multilingual_edge_cases(real_client, validate, case):
    req = {k: case[k] for k in ("ticket_id", "channel", "subject", "text") if k in case}
    r = real_client.post("/predict", json=req, headers=AUTH)
    assert r.status_code == 200, r.text
    p = r.json()
    validate("predict_response", p)
    assert p["team"] == CONTRACT_TEAM_MAP[p["category"]] and p["secondary_category"] != p["category"]
    if p["category"] == "spam_irrelevant":
        assert not p["is_urgent"] and p["secondary_category"] is None


def test_batch_invariance_and_determinism(real_client):
    reqs = [{k: c[k] for k in ("ticket_id", "channel", "subject", "text") if k in c} for c in _fixture_tickets()]
    batch = real_client.post("/predict/batch", json={"tickets": reqs}, headers=AUTH).json()["predictions"]
    singles = [real_client.post("/predict", json=t, headers=AUTH).json() for t in reqs]
    assert batch == singles
    again = real_client.post("/predict/batch", json={"tickets": list(reversed(reqs))}, headers=AUTH).json()
    assert list(reversed(again["predictions"])) == batch


def test_long_subject_does_not_crash(real_client):
    # Header alone exceeds max_length -> tokenizer fallback path (must be 200, never 5xx).
    subject = "මගේ ඇණවුම " * 50
    r = real_client.post("/predict", json={"channel": "email", "subject": subject[:500], "text": "help"}, headers=AUTH)
    assert r.status_code == 200, r.text
