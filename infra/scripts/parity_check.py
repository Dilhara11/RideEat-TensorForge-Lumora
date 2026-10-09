"""Compare predictions of two running API instances on the same tickets (e.g. local amd64 vs hosted arm64).

Same image tag on two CPU architectures runs different ONNX Runtime kernels, so confidences can differ in the
last decimals. This check proves the LABELS are identical and reports how far confidences drift and how long
each /predict/batch call takes on each side.

Run with the server venv (needs httpx), from the repo root:
    python infra/scripts/parity_check.py --a http://localhost:8000 --b https://dxxxx.cloudfront.net \
        app/server/tests/fixtures/multilingual_tickets.json app/client/test-data/05_large_job.csv
API key: --api-key, or API_KEY from the environment / app/server/.env. Exit code 1 if any label differs.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
FIELDS = ("ticket_id", "channel", "subject", "text")
LABELS = ("category", "secondary_category", "team", "is_urgent", "needs_human_review")


def load_tickets(path: Path) -> list[dict]:
    # Accepts a JSON list, {"tickets": [...]}, JSONL, or CSV with ticket_id,channel,subject,text columns.
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix == ".csv":
        rows = list(csv.DictReader(text.splitlines()))
    elif path.suffix == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        data = json.loads(text)
        rows = data["tickets"] if isinstance(data, dict) else data
    out = []
    for i, r in enumerate(rows):
        t = {k: r[k] for k in FIELDS if r.get(k) not in (None, "")}
        t.setdefault("ticket_id", f"{path.stem}-{i}")
        t.setdefault("subject", "")
        out.append(t)
    return out


def api_key_from_env() -> str:
    if os.environ.get("API_KEY"):
        return os.environ["API_KEY"]
    env = REPO / "app/server/.env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def predict_all(client: httpx.Client, base: str, key: str, tickets: list[dict], chunk: int):
    preds, times = {}, []
    for i in range(0, len(tickets), chunk):
        part = tickets[i : i + chunk]
        t0 = time.perf_counter()
        r = client.post(f"{base}/predict/batch", json={"tickets": part}, headers={"X-API-Key": key})
        times.append(time.perf_counter() - t0)
        r.raise_for_status()
        for p in r.json()["predictions"]:
            preds[p["ticket_id"]] = p
    return preds, times


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--a", default="http://localhost:8000", help="reference instance (local container)")
    ap.add_argument("--b", required=True, help="instance under test (hosted URL)")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--chunk", type=int, default=100, help="tickets per /predict/batch call (contract max 100)")
    a = ap.parse_args()

    key = a.api_key or api_key_from_env()
    if not key:
        print("API key missing: --api-key, API_KEY env or app/server/.env")
        return 2
    tickets = [t for f in a.files for t in load_tickets(f)]
    print(f"{len(tickets)} tickets from {len(a.files)} file(s), batches of {a.chunk}")

    with httpx.Client(timeout=120) as client:
        for base in (a.a, a.b):
            h = client.get(f"{base.rstrip('/')}/health").json()
            print(f"  {base}: {h.get('status')} {h.get('model_version')}")
        pa, ta = predict_all(client, a.a.rstrip("/"), key, tickets, a.chunk)
        pb, tb = predict_all(client, a.b.rstrip("/"), key, tickets, a.chunk)

    mismatches = [(tid, f, pa[tid].get(f), pb[tid].get(f)) for tid in pa for f in LABELS if pa[tid].get(f) != pb[tid].get(f)]
    drift = [abs(pa[t]["confidence"] - pb[t]["confidence"]) for t in pa]
    for name, ts in (("A", ta), ("B", tb)):
        print(f"  {name} /predict/batch seconds: median {statistics.median(ts):.1f}, max {max(ts):.1f} (target < 30)")
    print(f"  confidence |A-B|: max {max(drift):.2e}, mean {statistics.fmean(drift):.2e}")
    if mismatches:
        print(f"LABEL MISMATCHES: {len(mismatches)}")
        for tid, f, va, vb in mismatches[:20]:
            print(f"  {tid} {f}: A={va!r} B={vb!r}")
        return 1
    print(f"OK: all {len(LABELS)} label fields identical on {len(pa)} tickets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
