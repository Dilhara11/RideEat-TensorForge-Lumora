"""End-to-end contract smoke test against a running server (local container or hosted URL).

Checks every endpoint and error path from the OpenAPI contract and validates bodies against the
official JSON Schemas in app/server/contract/ (if `jsonschema` is installed).

Example:
    python scripts/smoke_test.py                                   # uses app/server/.env (API_KEY, BASE_URL)
    python scripts/smoke_test.py --base-url https://team.example.com
    python scripts/smoke_test.py --skip-jobs                        # quick run without async jobs
Exit code 0 = every check passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

SERVER_DIR = Path(__file__).resolve().parents[1]
SCHEMA_DIR = SERVER_DIR / "contract"


def load_env_file(path: Path) -> dict[str, str]:
    # Minimal .env reader. Example line: API_KEY=abc123  -> {"API_KEY": "abc123"}; comments/blank lines skipped.
    out = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


class Validator:
    """Validates a body against one of the official schema files; no-op if jsonschema/schemas are missing."""

    def __init__(self):
        try:
            import jsonschema
            self._js = jsonschema
        except ImportError:
            self._js = None
        self._cache = {}

    def __call__(self, name: str, body) -> str | None:
        path = SCHEMA_DIR / f"{name}.schema.json"
        if self._js is None or not path.is_file():
            return None
        if name not in self._cache:
            self._cache[name] = self._js.Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))
        errors = sorted(self._cache[name].iter_errors(body), key=str)
        return f"schema {name}: {errors[0].message}" if errors else None


class Smoke:
    def __init__(self, base_url: str, api_key: str):
        self.base = base_url.rstrip("/")
        self.key = api_key
        self.http = httpx.Client(timeout=120)
        self.validate = Validator()
        self.results: list[tuple[str, bool, str]] = []

    # --- helpers -------------------------------------------------------------------------
    def auth(self, extra: dict | None = None) -> dict:
        return {"X-API-Key": self.key, **(extra or {})}

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, bool(ok), detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
        return bool(ok)

    def expect(self, name: str, r: httpx.Response, status: int, schema: str | None = None, code: str | None = None):
        # One HTTP expectation: status code, JSON content type, optional schema + error code.
        problems = []
        if r.status_code != status:
            problems.append(f"status {r.status_code} != {status}")
        if r.status_code != 204 and "application/json" not in r.headers.get("content-type", ""):
            problems.append(f"content-type {r.headers.get('content-type')}")
        body = None
        if r.status_code != 204:
            try:
                body = r.json()
            except ValueError:
                problems.append("body is not JSON")
        if body is not None and schema:
            err = self.validate(schema, body)
            if err:
                problems.append(err)
        if body is not None and code and body.get("error", {}).get("code") != code:
            problems.append(f"error.code {body.get('error', {}).get('code')} != {code}")
        self.check(name, not problems, "; ".join(problems))
        return body

    # --- sections ------------------------------------------------------------------------
    def health(self):
        print("\n[1] /health (public)")
        deadline = time.time() + 120
        while True:  # the model may still be loading right after `docker run`
            r = self.http.get(f"{self.base}/health")
            if r.status_code == 200 or time.time() > deadline:
                break
            time.sleep(2)
        body = self.expect("GET /health -> 200", r, 200, "health_response")
        self.version = (body or {}).get("model_version")
        self.check("model_version present", bool(self.version), str(self.version))

    def auth_checks(self):
        print("\n[2] Authorization")
        t = {"channel": "chat", "text": "my order is late"}
        r = self.http.post(f"{self.base}/predict", json=t)
        self.expect("no key -> 401", r, 401, "error_response", "unauthorized")
        self.check("401 has WWW-Authenticate: Bearer", r.headers.get("www-authenticate") == "Bearer")
        self.expect("wrong key -> 401", self.http.post(f"{self.base}/predict", json=t, headers={"X-API-Key": "wrong"}), 401)
        self.expect("no key + bad JSON -> 401 (auth first)",
                    self.http.post(f"{self.base}/predict", content=b"{", headers={"Content-Type": "application/json"}), 401)
        self.expect("X-API-Key -> 200", self.http.post(f"{self.base}/predict", json=t, headers=self.auth()), 200)
        self.expect("Authorization: Bearer -> 200",
                    self.http.post(f"{self.base}/predict", json=t, headers={"Authorization": f"Bearer {self.key}"}), 200)

    def predict(self):
        print("\n[3] POST /predict")
        samples = [
            {"ticket_id": "S-SG", "channel": "chat", "subject": "",
             "text": "bro mage order eka hour ekakata wada late, driver call ganne na. refund ekak denna"},
            {"ticket_id": "S-EN", "channel": "call_transcript", "subject": "",
             "text": "customer: the driver took a wrong turn and he's not stopping the car i am scared please"},
            {"ticket_id": "S-TA", "channel": "chat", "text": "என் ஆர்டர்ல ஒரு ஐட்டம் வரல, பணம் திருப்பி தாங்க"},
            {"ticket_id": "S-SI", "channel": "chat", "text": "කාර් එකේ මගේ බෑග් එක අමතක වුණා, ඩ්‍රයිවර්ට කතා කරන්න පුළුවන්ද?"},
            {"ticket_id": "S-EM", "channel": "email", "subject": "Re: Order #48213",
             "text": "My father is diabetic and the insulin pack in my order has not arrived. The rider's phone is off."},
            {"ticket_id": "S-SPAM", "channel": "email", "subject": "WIN BIG", "text": "Click here to claim your free iPhone now!!!"},
        ]
        for s in samples:
            r = self.http.post(f"{self.base}/predict", json=s, headers=self.auth({"X-Request-ID": f"rid-{s['ticket_id']}"}))
            p = self.expect(f"{s['ticket_id']} -> 200 + schema", r, 200, "predict_response") or {}
            if p:
                print(f"        {p['category']:<20} sec={str(p['secondary_category']):<20} urgent={p['is_urgent']!s:<5} "
                      f"conf={p['confidence']:.2f} review={p.get('needs_human_review')} team={p['team']}")
                self.check(f"{s['ticket_id']} ticket_id echoed + same model_version",
                           p.get("ticket_id") == s["ticket_id"] and p["model_version"] == self.version)
                self.check(f"{s['ticket_id']} X-Request-ID echoed", r.headers.get("x-request-id") == f"rid-{s['ticket_id']}")

    def errors(self):
        print("\n[4] Error paths (check order: 401 -> 415 -> 413 -> 400 -> 422)")
        url = f"{self.base}/predict"
        self.expect("text/plain -> 415", self.http.post(url, content=b"hi", headers=self.auth({"Content-Type": "text/plain"})),
                    415, "error_response", "unsupported_media_type")
        big = b'{"channel": "chat", "text": "' + b"x" * (1024 * 1024 + 10) + b'"}'
        self.expect("> 1 MB body -> 413", self.http.post(url, content=big, headers=self.auth({"Content-Type": "application/json"})),
                    413, "error_response", "payload_too_large")
        self.expect("malformed JSON -> 400", self.http.post(url, content=b'{"channel": "chat",', headers=self.auth({"Content-Type": "application/json"})),
                    400, "error_response", "malformed_json")
        for name, body in [("blank text -> 422", {"channel": "chat", "text": "   "}),
                           ("unknown channel -> 422", {"channel": "fax", "text": "hi"}),
                           ("missing text -> 422", {"channel": "chat"}),
                           ("text not a string -> 422", {"channel": "chat", "text": 42}),
                           ("text > 10,000 chars -> 422", {"channel": "chat", "text": "x" * 10_001})]:
            self.expect(name, self.http.post(url, json=body, headers=self.auth()), 422, "error_response", "validation_error")
        self.expect("unknown route -> 404 JSON", self.http.get(f"{self.base}/does-not-exist", headers=self.auth()), 404, "error_response")
        self.expect("wrong method -> 405 JSON", self.http.get(url, headers=self.auth()), 405, "error_response")

    def batch(self):
        print("\n[5] POST /predict/batch")
        tickets = [{"ticket_id": f"B{i}", "channel": "chat", "subject": "", "text": f"order {i} arrived cold and late"}
                   for i in range(5)]
        r = self.http.post(f"{self.base}/predict/batch", json={"tickets": tickets}, headers=self.auth())
        body = self.expect("5 tickets -> 200 + schema", r, 200, "batch_response") or {}
        preds = body.get("predictions", [])
        self.check("same order + ids", [p["ticket_id"] for p in preds] == [t["ticket_id"] for t in tickets])
        single = self.http.post(f"{self.base}/predict", json=tickets[2], headers=self.auth()).json()
        self.check("batch item == single /predict", len(preds) > 2 and preds[2] == single)
        bad = [tickets[0], {**tickets[1], "text": " "}, tickets[0]]
        r = self.http.post(f"{self.base}/predict/batch", json={"tickets": bad}, headers=self.auth())
        err = self.expect("bad items -> 422", r, 422, "error_response", "validation_error") or {}
        idx = sorted(d.get("index") for d in err.get("error", {}).get("details", []))
        self.check("422 lists every bad item by index", idx == [1, 2], f"indexes {idx}")
        r = self.http.post(f"{self.base}/predict/batch", json={"tickets": tickets * 21}, headers=self.auth())
        self.expect("> 100 tickets -> 422", r, 422)

    def jobs(self, n: int):
        print(f"\n[6] Async jobs ({n} tickets)")
        tickets = [{"ticket_id": f"J{i}", "channel": "chat", "subject": "", "text": f"refund for order {i} please"}
                   for i in range(n)]
        idem = f"smoke-{uuid.uuid4().hex[:8]}"
        t0 = time.perf_counter()
        r = self.http.post(f"{self.base}/batch/jobs", json={"tickets": tickets}, headers=self.auth({"Idempotency-Key": idem}))
        job = self.expect("submit -> 202 + schema", r, 202, "batch_job_status") or {}
        self.check("202 within 5 s", time.perf_counter() - t0 < 5, f"{time.perf_counter() - t0:.2f} s")
        self.check("Location + Retry-After headers",
                   r.headers.get("location") == f"/batch/jobs/{job.get('job_id')}" and r.headers.get("retry-after"))
        again = self.http.post(f"{self.base}/batch/jobs", json={"tickets": tickets}, headers=self.auth({"Idempotency-Key": idem}))
        self.check("same Idempotency-Key -> same job", again.status_code == 202 and again.json().get("job_id") == job.get("job_id"))
        jid = job["job_id"]
        early = self.http.get(f"{self.base}/batch/jobs/{jid}/results", headers=self.auth())
        if early.status_code == 409:
            self.expect("results before success -> 409", early, 409, "error_response", "job_not_ready")

        last, status = -1, {}
        deadline = time.time() + max(120, n * 2)
        while time.time() < deadline:
            status = self.http.get(f"{self.base}/batch/jobs/{jid}", headers=self.auth()).json()
            if status["processed"] < last:
                self.check("processed never decreases", False)
            last = status["processed"]
            if status["status"] not in ("queued", "running"):
                break
            time.sleep(2)
        self.check("job succeeded", status.get("status") == "succeeded", f"{status.get('status')} {last}/{n}")
        err = self.validate("batch_job_status", status)
        self.check("status schema", err is None, err or "")

        res = self.expect("GET results -> 200 + schema", self.http.get(f"{self.base}/batch/jobs/{jid}/results", headers=self.auth()),
                          200, "batch_job_results") or {}
        self.check("results in request order", [p["ticket_id"] for p in res.get("predictions", [])] == [t["ticket_id"] for t in tickets])
        page = self.http.get(f"{self.base}/batch/jobs/{jid}/results", params={"offset": 0, "limit": 5}, headers=self.auth()).json()
        self.check("paging: limit=5 -> 5 items, next_offset=5", len(page["predictions"]) == 5 and page["next_offset"] == (5 if n > 5 else None))
        self.expect("DELETE -> 204", self.http.delete(f"{self.base}/batch/jobs/{jid}", headers=self.auth()), 204)
        self.expect("after DELETE -> 404", self.http.get(f"{self.base}/batch/jobs/{jid}", headers=self.auth()), 404, "error_response", "job_not_found")
        self.expect("unknown job -> 404", self.http.get(f"{self.base}/batch/jobs/{uuid.uuid4()}", headers=self.auth()), 404)

    def summary(self) -> int:
        failed = [r for r in self.results if not r[1]]
        print(f"\n{len(self.results) - len(failed)}/{len(self.results)} checks passed")
        for name, _, detail in failed:
            print(f"  FAILED: {name} {detail}")
        return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", default=str(SERVER_DIR / ".env"))
    ap.add_argument("--base-url")
    ap.add_argument("--api-key")
    ap.add_argument("--job-size", type=int, default=20)
    ap.add_argument("--skip-jobs", action="store_true")
    a = ap.parse_args()
    env = {**load_env_file(Path(a.env_file)), **{k: v for k, v in os.environ.items() if k in ("API_KEY", "BASE_URL")}}
    base_url = a.base_url or env.get("BASE_URL", "http://localhost:8000")
    api_key = a.api_key or env.get("API_KEY", "")
    if not api_key:
        print("API_KEY missing: set it in app/server/.env or pass --api-key")
        return 2
    print(f"Target: {base_url}")
    s = Smoke(base_url, api_key)
    s.health()
    s.auth_checks()
    s.predict()
    s.errors()
    s.batch()
    if not a.skip_jobs:
        s.jobs(a.job_size)
    return s.summary()


if __name__ == "__main__":
    sys.exit(main())
