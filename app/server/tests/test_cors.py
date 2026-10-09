"""CORS for the separately hosted web client (CORS_ORIGINS). Off by default; the contract must not change."""

import pytest

from conftest import AUTH, ticket
from tfengine.config import _env_origins

UI = "https://main.d1abc.amplifyapp.com"
PREFLIGHT = {"Origin": UI, "Access-Control-Request-Method": "POST",
             "Access-Control-Request-Headers": "x-api-key,content-type,idempotency-key"}


def test_env_origins_parsing(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", f" {UI}/ , http://localhost:5173,, ")
    assert _env_origins("CORS_ORIGINS") == (UI, "http://localhost:5173")
    monkeypatch.delenv("CORS_ORIGINS")
    assert _env_origins("CORS_ORIGINS") == ()


def test_cors_off_by_default_keeps_contract(client):
    # No CORS headers, and OPTIONS stays a JSON 405 like any unsupported method.
    r = client.post("/predict", json=ticket(), headers={**AUTH, "Origin": UI})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers
    r = client.options("/predict", headers=PREFLIGHT)
    assert r.status_code == 405 and r.json()["error"]["code"] == "method_not_allowed"


@pytest.fixture
def cors_client(make_client):
    return make_client(cors_origins=(UI,))


def test_preflight_allows_the_client_headers(cors_client):
    r = cors_client.options("/predict", headers=PREFLIGHT)
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == UI
    allowed = r.headers["access-control-allow-headers"].lower()
    for h in ("x-api-key", "authorization", "content-type", "idempotency-key"):
        assert h in allowed
    assert "DELETE" in r.headers["access-control-allow-methods"]


def test_job_headers_are_readable_from_the_browser(cors_client):
    # The client paces polling with Retry-After: it must be exposed cross-origin.
    r = cors_client.post("/batch/jobs", json={"tickets": [ticket("A")]}, headers={**AUTH, "Origin": UI})
    assert r.status_code == 202
    assert r.headers["access-control-allow-origin"] == UI
    exposed = r.headers["access-control-expose-headers"].lower()
    assert "retry-after" in exposed and "location" in exposed


def test_errors_carry_cors_headers_so_the_client_can_read_them(cors_client):
    r = cors_client.post("/predict", json=ticket(), headers={"Origin": UI})
    assert r.status_code == 401 and r.headers["access-control-allow-origin"] == UI
    r = cors_client.post("/predict", json={"channel": "fax", "text": "x"}, headers={**AUTH, "Origin": UI})
    assert r.status_code == 422 and r.headers["access-control-allow-origin"] == UI


def test_other_origins_get_no_cors_headers(cors_client):
    r = cors_client.post("/predict", json=ticket(), headers={**AUTH, "Origin": "https://evil.example"})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize("method,path,body,expected", [
    ("POST", "/predict", None, 401),              # auth still first
    ("POST", "/predict", b"{", 400),              # then JSON parse
    ("GET", "/no-such-route", None, 404),         # JSON 404
])
def test_contract_unchanged_without_origin_when_cors_on(cors_client, method, path, body, expected):
    headers = {} if expected == 401 else {**AUTH, "Content-Type": "application/json"}
    r = cors_client.request(method, path, content=body, headers=headers)
    assert r.status_code == expected
    assert "error" in r.json() and "access-control-allow-origin" not in r.headers
