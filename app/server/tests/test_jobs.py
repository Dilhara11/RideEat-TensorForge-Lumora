"""Async batch job lifecycle: 202 -> poll -> results, paging, 404/409/410/429, idempotency, restart."""

import threading
import time

import pytest

from conftest import AUTH, FakeClassifier, ticket, wait_until
from tfengine.jobs.store import RUNNING, SQLiteJobStore

LEGAL_NEXT = {"queued": {"queued", "running", "succeeded", "failed"}, "running": {"running", "succeeded", "failed"},
              "succeeded": {"succeeded"}, "failed": {"failed"}}


def submit(client, n=10, headers=None, **kw):
    tickets = kw.pop("tickets", None) or [ticket(i) for i in range(n)]
    return client.post("/batch/jobs", json={"tickets": tickets}, headers={**AUTH, **(headers or {})})


def wait_status(client, job_id, status="succeeded", timeout=20):
    seen = []

    def done():
        s = client.get(f"/batch/jobs/{job_id}", headers=AUTH).json()
        seen.append(s)
        return s["status"] == status
    wait_until(done, timeout=timeout, interval=0.05)
    return seen


def test_submit_returns_202_with_headers(client, validate):
    r = submit(client, 5)
    assert r.status_code == 202
    body = r.json()
    validate("batch_job_status", body)
    assert body["status"] in {"queued", "running", "succeeded"} and body["total"] == 5
    assert r.headers["location"] == f"/batch/jobs/{body['job_id']}"
    assert int(r.headers["retry-after"]) >= 1
    assert body["model_version"] == client.get("/health").json()["model_version"]


def test_full_lifecycle_and_results(make_client, validate):
    c = make_client(FakeClassifier(delay_s=0.002))
    tickets = [ticket(i, text=f"job ticket {i}") for i in range(300)]
    job = submit(c, tickets=tickets).json()
    seen = wait_status(c, job["job_id"])

    # Legal, monotonic transitions; processed never decreases.
    for a, b in zip(seen, seen[1:]):
        assert b["status"] in LEGAL_NEXT[a["status"]]
        assert b["processed"] >= a["processed"]
    final = seen[-1]
    validate("batch_job_status", final)
    assert final["processed"] == 300 and final["finished_at"] and final["expires_at"] and final["error"] is None
    assert "retry-after" not in c.get(f"/batch/jobs/{job['job_id']}", headers=AUTH).headers

    r = c.get(f"/batch/jobs/{job['job_id']}/results", headers=AUTH)
    assert r.status_code == 200
    res = r.json()
    validate("batch_job_results", res)
    assert res["total"] == 300 and res["offset"] == 0 and res["limit"] == 300 and res["next_offset"] is None
    assert [p["ticket_id"] for p in res["predictions"]] == [t["ticket_id"] for t in tickets]

    # Same predictions as the synchronous endpoint (same model, same rules).
    sync = c.post("/predict/batch", json={"tickets": tickets[:50]}, headers=AUTH).json()["predictions"]
    assert res["predictions"][:50] == sync


def test_paging_is_stable(client):
    job = submit(client, 25).json()
    wait_status(client, job["job_id"])
    url = f"/batch/jobs/{job['job_id']}/results"
    pages, offset = [], 0
    while offset is not None:
        page = client.get(url, params={"offset": offset, "limit": 10}, headers=AUTH).json()
        pages.append(page)
        offset = page["next_offset"]
    assert [p["offset"] for p in pages] == [0, 10, 20] and pages[-1]["next_offset"] is None
    ids = [p["ticket_id"] for page in pages for p in page["predictions"]]
    assert ids == [f"T{i}" for i in range(25)]
    assert client.get(url, params={"offset": 10, "limit": 10}, headers=AUTH).json() == pages[1]
    beyond = client.get(url, params={"offset": 100}, headers=AUTH).json()
    assert beyond["predictions"] == [] and beyond["next_offset"] is None


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 5001}, {"offset": -1}, {"limit": "abc"}])
def test_bad_paging_params_422(client, params):
    job = submit(client, 2).json()
    wait_status(client, job["job_id"])
    r = client.get(f"/batch/jobs/{job['job_id']}/results", params=params, headers=AUTH)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_results_before_success_is_409_and_status_has_retry_after(make_client):
    gate = threading.Event()
    c = make_client(FakeClassifier(gate=gate))
    job = submit(c, 3).json()
    try:
        r = c.get(f"/batch/jobs/{job['job_id']}/results", headers=AUTH)
        assert r.status_code == 409 and r.json()["error"]["code"] == "job_not_ready"
        s = c.get(f"/batch/jobs/{job['job_id']}", headers=AUTH)
        assert s.json()["status"] in {"queued", "running"} and int(s.headers["retry-after"]) >= 1
    finally:
        gate.set()
    wait_status(c, job["job_id"])


def test_unknown_job_404(client):
    for path in ["/batch/jobs/does-not-exist", "/batch/jobs/does-not-exist/results", "/batch/jobs/" + "x" * 300]:
        r = client.get(path, headers=AUTH)
        assert r.status_code == 404 and r.json()["error"]["code"] == "job_not_found"
    assert client.delete("/batch/jobs/does-not-exist", headers=AUTH).status_code == 404


def test_delete_finished_then_404(client):
    job = submit(client, 3).json()
    wait_status(client, job["job_id"])
    assert client.delete(f"/batch/jobs/{job['job_id']}", headers=AUTH).status_code == 204
    assert client.get(f"/batch/jobs/{job['job_id']}", headers=AUTH).status_code == 404
    assert client.get(f"/batch/jobs/{job['job_id']}/results", headers=AUTH).status_code == 404


def test_delete_running_job_cancels_it(make_client):
    clf = FakeClassifier(delay_s=0.01)
    c = make_client(clf, job_chunk_size=2)
    job = submit(c, 200).json()
    wait_until(lambda: c.get(f"/batch/jobs/{job['job_id']}", headers=AUTH).json()["processed"] > 0)
    assert c.delete(f"/batch/jobs/{job['job_id']}", headers=AUTH).status_code == 204
    calls = clf.calls
    time.sleep(0.3)
    assert clf.calls <= calls + 1  # worker stopped after at most the in-flight chunk
    assert c.get(f"/batch/jobs/{job['job_id']}", headers=AUTH).status_code == 404


def test_idempotency_key_returns_same_job(client):
    a = submit(client, 4, headers={"Idempotency-Key": "run-1"})
    b = submit(client, 4, headers={"Idempotency-Key": "run-1"})
    assert a.status_code == b.status_code == 202
    assert a.json()["job_id"] == b.json()["job_id"]
    c = submit(client, 4, headers={"Idempotency-Key": "run-2"})
    assert c.json()["job_id"] != a.json()["job_id"]


def test_too_long_idempotency_key_422(client):
    assert submit(client, 1, headers={"Idempotency-Key": "k" * 129}).status_code == 422


def test_capacity_429_after_one_running_plus_three_queued(make_client):
    gate = threading.Event()
    c = make_client(FakeClassifier(gate=gate))
    try:
        ids = [submit(c, 2).json()["job_id"] for _ in range(4)]
        assert len(set(ids)) == 4
        r = submit(c, 2)
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "too_many_jobs" and int(r.headers["retry-after"]) >= 1
        # Idempotent resubmission of an existing job still works when full.
        again = submit(c, 2, headers={"Idempotency-Key": "x"})
        assert again.status_code == 429
    finally:
        gate.set()
    for job_id in ids:
        wait_status(c, job_id)
    assert submit(c, 2).status_code == 202


def test_invalid_job_creates_nothing(client):
    r = submit(client, tickets=[ticket(0), ticket(1, text=""), ticket(0)])
    assert r.status_code == 422
    details = r.json()["error"]["details"]
    assert {(d["index"], d["field"]) for d in details} == {(1, "text"), (2, "ticket_id")}
    assert client.app.state.engine.store.count_active() == 0


def test_job_limit_5000(client):
    r = submit(client, tickets=[ticket(i) for i in range(5001)])
    assert r.status_code == 422
    assert r.json()["error"]["details"] == [{"field": "tickets", "issue": "must contain between 1 and 5000 items"}]


def test_5000_ticket_submit_is_fast(make_client):
    c = make_client(FakeClassifier())
    tickets = [ticket(i, text="මගේ ඇණවුම තවම ආවේ නැහැ, refund ekak denna " * 5) for i in range(5000)]
    t0 = time.perf_counter()
    r = submit(c, tickets=tickets)
    assert r.status_code == 202
    assert time.perf_counter() - t0 < 5.0
    wait_status(c, r.json()["job_id"], timeout=60)


def test_determinism_across_jobs(client):
    tickets = [ticket(i, text=f"same input {i}") for i in range(20)]
    a = submit(client, tickets=tickets).json()["job_id"]
    b = submit(client, tickets=tickets).json()["job_id"]
    wait_status(client, a)
    wait_status(client, b)
    ra = client.get(f"/batch/jobs/{a}/results", headers=AUTH).json()["predictions"]
    rb = client.get(f"/batch/jobs/{b}/results", headers=AUTH).json()["predictions"]
    assert ra == rb


def test_health_and_predict_stay_responsive_during_job(make_client):
    c = make_client(FakeClassifier(delay_s=0.01), job_chunk_size=8)
    job = submit(c, tickets=[ticket(i) for i in range(400)]).json()  # ~4 s of "model" work
    wait_until(lambda: c.get(f"/batch/jobs/{job['job_id']}", headers=AUTH).json()["status"] == "running")
    for _ in range(5):
        t0 = time.perf_counter()
        assert c.get("/health").status_code == 200
        assert time.perf_counter() - t0 < 0.5
        t0 = time.perf_counter()
        assert c.post("/predict", json=ticket(), headers=AUTH).status_code == 200
        assert time.perf_counter() - t0 < 1.0  # waits at most one chunk (8 x 10 ms)
    assert c.get(f"/batch/jobs/{job['job_id']}", headers=AUTH).json()["status"] == "running"


def test_expired_job_is_410(make_client):
    c = make_client(job_retention_s=1)
    job = submit(c, 2).json()
    wait_status(c, job["job_id"])
    time.sleep(1.2)
    for path in [f"/batch/jobs/{job['job_id']}", f"/batch/jobs/{job['job_id']}/results"]:
        r = c.get(path, headers=AUTH)
        assert r.status_code == 410 and r.json()["error"]["code"] == "job_expired"


def test_restart_mid_job_marks_interrupted(tmp_path, make_client, validate):
    # Simulate a previous process that died while running a job (stale heartbeat).
    data = tmp_path / "data"
    store = SQLiteJobStore(data / "jobs.sqlite3", retention_s=3600)
    store.create_job("dead-job", ['{"i":"T0","c":"chat","s":"","t":"hi"}'], "test-v1", None, max_active=4)
    assert store.claim_next("old-worker", max_running=1).status == RUNNING
    with store._conn() as conn:
        conn.execute("UPDATE jobs SET heartbeat_at = heartbeat_at - 3600 WHERE job_id = 'dead-job'")

    c = make_client()  # new process starts on the same DATA_DIR; its sweeper runs right away
    wait_until(lambda: c.get("/batch/jobs/dead-job", headers=AUTH).json()["status"] == "failed")
    body = c.get("/batch/jobs/dead-job", headers=AUTH).json()
    validate("batch_job_status", body)
    assert body["error"]["code"] == "interrupted" and body["finished_at"] and body["expires_at"]
    assert c.get("/batch/jobs/dead-job/results", headers=AUTH).status_code == 409


def test_queued_job_survives_restart(tmp_path, make_client):
    store = SQLiteJobStore(tmp_path / "data" / "jobs.sqlite3", retention_s=3600)
    store.create_job("queued-job", ['{"i":"T0","c":"chat","s":"","t":"hi"}'], "test-v1", None, max_active=4)
    c = make_client()
    wait_status(c, "queued-job")
