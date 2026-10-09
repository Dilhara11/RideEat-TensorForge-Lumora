"""/predict and /predict/batch behaviour and schema compliance."""

import pytest

from conftest import AUTH, ticket
from tfengine.inference import CONTRACT_TEAM_MAP


def _consistent(p: dict) -> None:
    # Harness consistency rules.
    assert p["secondary_category"] != p["category"]
    assert p["team"] == CONTRACT_TEAM_MAP[p["category"]]
    if p["category"] == "spam_irrelevant":
        assert p["is_urgent"] is False and p["secondary_category"] is None
    assert 0.0 <= p["confidence"] <= 1.0


def test_predict_shape(client, validate):
    r = client.post("/predict", json=ticket(1), headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    validate("predict_response", body)
    _consistent(body)
    assert body["ticket_id"] == "T1"
    assert "secondary_category" in body  # key always present, even when null


def test_ticket_id_optional_and_not_invented(client):
    body = client.post("/predict", json={"channel": "chat", "text": "hi"}, headers=AUTH).json()
    assert "ticket_id" not in body


def test_model_version_identical_everywhere(client):
    v = client.get("/health").json()["model_version"]
    assert v and client.post("/predict", json=ticket(), headers=AUTH).json()["model_version"] == v
    b = client.post("/predict/batch", json={"tickets": [ticket(1), ticket(2)]}, headers=AUTH).json()
    assert {p["model_version"] for p in b["predictions"]} == {v} and b["meta"]["model_version"] == v


def test_spam_rule_enforced(client, validate):
    body = client.post("/predict", json=ticket(text="SPAMTEST buy cheap followers"), headers=AUTH).json()
    validate("predict_response", body)
    assert body["category"] == "spam_irrelevant"
    assert body["is_urgent"] is False and body["secondary_category"] is None
    assert body["team"] == "Auto-close / Spam Filter"


def test_deterministic(client):
    a = client.post("/predict", json=ticket(5), headers=AUTH).json()
    b = client.post("/predict", json=ticket(5), headers=AUTH).json()
    assert a == b


def test_batch_order_ids_and_schema(client, validate):
    tickets = [ticket(i, text=f"ticket number {i} " + "x" * i) for i in range(100)]
    r = client.post("/predict/batch", json={"tickets": tickets}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    validate("batch_response", body)
    assert [p["ticket_id"] for p in body["predictions"]] == [t["ticket_id"] for t in tickets]
    assert body["meta"]["count"] == 100
    for p in body["predictions"]:
        _consistent(p)


def test_batch_matches_single_predictions(client):
    tickets = [ticket(i, text=f"issue {i}") for i in range(10)]
    batch = client.post("/predict/batch", json={"tickets": tickets}, headers=AUTH).json()["predictions"]
    singles = [client.post("/predict", json=t, headers=AUTH).json() for t in tickets]
    assert batch == singles


@pytest.mark.parametrize("body,expected", [
    ({}, [{"field": "tickets", "issue": "is required"}]),
    ({"tickets": "nope"}, [{"field": "tickets", "issue": "must be an array"}]),
    ({"tickets": []}, [{"field": "tickets", "issue": "must contain between 1 and 100 items"}]),
    ({"tickets": [ticket(i) for i in range(101)]}, [{"field": "tickets", "issue": "must contain between 1 and 100 items"}]),
])
def test_batch_envelope_422(client, body, expected):
    r = client.post("/predict/batch", json=body, headers=AUTH)
    assert r.status_code == 422
    assert r.json()["error"]["details"] == expected


def test_batch_lists_every_failing_item(client, validate):
    tickets = [ticket(0), ticket(1, text="  "), ticket(2), ticket(3, channel="sms"), {"channel": "chat", "text": "no id"}]
    r = client.post("/predict/batch", json={"tickets": tickets}, headers=AUTH)
    assert r.status_code == 422
    validate("error_response", r.json())
    details = r.json()["error"]["details"]
    assert {(d["index"], d["field"]) for d in details} == {(1, "text"), (3, "channel"), (4, "ticket_id")}
    assert next(d for d in details if d["index"] == 4)["issue"] == "is required"


def test_batch_duplicate_ids(client):
    r = client.post("/predict/batch", json={"tickets": [ticket(1), ticket(2), ticket(1)]}, headers=AUTH)
    assert r.status_code == 422
    assert r.json()["error"]["details"] == [{"index": 2, "field": "ticket_id", "issue": "duplicate of an earlier item"}]


def test_batch_item_not_object(client):
    r = client.post("/predict/batch", json={"tickets": [ticket(1), "oops"]}, headers=AUTH)
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["index"] == 1
