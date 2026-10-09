"""Authorization: X-API-Key or Bearer, 401 before anything else, /health public."""

import pytest

from conftest import API_KEY, AUTH, ticket

PROTECTED = [
    ("POST", "/predict"),
    ("POST", "/predict/batch"),
    ("POST", "/batch/jobs"),
    ("GET", "/batch/jobs/abc"),
    ("GET", "/batch/jobs/abc/results"),
    ("DELETE", "/batch/jobs/abc"),
]


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.parametrize("method,path", PROTECTED)
def test_missing_key_is_401_with_www_authenticate(client, method, path):
    r = client.request(method, path, json=ticket())
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("headers", [
    {"X-API-Key": "wrong"},
    {"Authorization": "Bearer wrong"},
    {"Authorization": f"Basic {API_KEY}"},  # wrong scheme
    {"X-API-Key": ""},
])
def test_wrong_key_is_401(client, headers):
    r = client.post("/predict", json=ticket(), headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("headers", [
    {"X-API-Key": API_KEY},
    {"Authorization": f"Bearer {API_KEY}"},
    {"Authorization": f"bearer {API_KEY}"},
    {"X-API-Key": "wrong", "Authorization": f"Bearer {API_KEY}"},
])
def test_valid_key_forms(client, headers):
    assert client.post("/predict", json=ticket(), headers=headers).status_code == 200


@pytest.mark.parametrize("content,ctype", [
    (b"{not json", "application/json"),  # would be 400
    (b"hello", "text/plain"),  # would be 415
    (b'{"channel": "fax", "text": ""}', "application/json"),  # would be 422
    (b"x" * (2 * 1024 * 1024), "application/json"),  # would be 413
])
def test_auth_checked_before_everything(client, content, ctype):
    # Unauthorized requests must never see 400/413/415/422.
    r = client.post("/predict", content=content, headers={"Content-Type": ctype})
    assert r.status_code == 401


def test_unset_api_key_refuses_everything(make_client):
    c = make_client(api_key=None)
    assert c.get("/health").status_code == 200
    r = c.post("/predict", json=ticket(), headers=AUTH)
    assert r.status_code == 401
    r = c.post("/predict", json=ticket(), headers={"X-API-Key": ""})
    assert r.status_code == 401
