"""Status-code order (401 -> 415 -> 413 -> 400 -> 422) and JSON-only errors for routing problems."""

import pytest

from conftest import AUTH, ticket

MB = 1024 * 1024


def _post(client, path, content, ctype="application/json"):
    headers = dict(AUTH)
    if ctype is not None:
        headers["Content-Type"] = ctype
    return client.post(path, content=content, headers=headers)


@pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", None])
def test_415_for_non_json(client, ctype):
    r = _post(client, "/predict", b'{"channel": "chat", "text": "hi"}', ctype)
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "unsupported_media_type"


def test_json_with_charset_is_accepted(client):
    r = _post(client, "/predict", b'{"channel": "chat", "text": "hi"}', "application/json; charset=utf-8")
    assert r.status_code == 200


@pytest.mark.parametrize("path,limit", [("/predict", 1 * MB), ("/predict/batch", 5 * MB), ("/batch/jobs", 25 * MB)])
def test_413_over_limit(client, path, limit):
    r = _post(client, path, b"{" + b" " * limit + b"}")
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


def test_413_for_chunked_body_without_content_length(client):
    def gen():
        for _ in range(3):
            yield b" " * (512 * 1024)
    r = client.post("/predict", content=gen(), headers={**AUTH, "Content-Type": "application/json"})
    assert r.status_code == 413


def test_415_wins_over_413(client):
    assert _post(client, "/predict", b"x" * (2 * MB), "text/plain").status_code == 415


def test_413_wins_over_400(client):
    assert _post(client, "/predict", b"{" * (2 * MB)).status_code == 413


@pytest.mark.parametrize("body", [b"{not json", b"", b"   ", b'{"channel": "chat",}', b"\xff\xfe\x00", b"[" * 100000])
def test_400_malformed_json(client, body):
    r = _post(client, "/predict", body)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "malformed_json"


def test_400_wins_over_422(client):
    assert _post(client, "/predict/batch", b'{"tickets": [}').status_code == 400


def test_unknown_route_is_json_404(client):
    r = client.get("/nope", headers=AUTH)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("method,path", [("GET", "/predict"), ("PUT", "/predict/batch"), ("POST", "/health"),
                                         ("PATCH", "/batch/jobs")])
def test_wrong_method_is_json_405(client, method, path):
    r = client.request(method, path, headers=AUTH)
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "method_not_allowed"


def test_request_id_is_echoed(client):
    r = client.post("/predict", json=ticket(), headers={**AUTH, "X-Request-ID": "rid-42"})
    assert r.headers["x-request-id"] == "rid-42"
    r = client.post("/predict", content=b"{", headers={**AUTH, "Content-Type": "application/json",
                                                        "X-Request-ID": "rid-err"})
    assert r.status_code == 400 and r.headers["x-request-id"] == "rid-err"


def test_root_without_frontend_is_json(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["health"] == "/health"
