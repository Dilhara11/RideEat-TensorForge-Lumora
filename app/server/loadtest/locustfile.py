"""Latency checks against the contract targets (p95: /predict < 1 s, 100-ticket batch < 30 s).

Run (needs `pip install locust`, not part of the image):
    API_KEY=<key> locust -f loadtest/locustfile.py --host http://localhost:8000 \
        --users 4 --spawn-rate 2 --run-time 2m --headless

Optionally start a 5,000-ticket job first (JOB_TICKETS=5000) to check that /health and /predict
stay under 1 s p95 while the job runs.
"""

import json
import os
import random
from pathlib import Path

from locust import HttpUser, between, events, task

API_KEY = os.environ.get("API_KEY", "")
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
# Validation tickets if the dataset is present locally (it is not committed); otherwise synthetic tickets.
DATA = Path(__file__).resolve().parents[3] / "training" / "data" / "validation.jsonl"

# Example ticket: {"ticket_id": "TF-VA-000001", "channel": "chat", "subject": "", "text": "..."}
TICKETS = [
    {k: r[k] for k in ("ticket_id", "channel", "subject", "text")}
    for r in (json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines())
] if DATA.is_file() else [{"ticket_id": f"T{i}", "channel": "chat", "subject": "", "text": "my order is late"}
                          for i in range(200)]


@events.test_start.add_listener
def _start_background_job(environment, **_):
    # Example: JOB_TICKETS=5000 -> one async job running in the background during the test.
    n = int(os.environ.get("JOB_TICKETS", "0"))
    if n:
        import requests

        tickets = [{**random.choice(TICKETS), "ticket_id": f"J{i}"} for i in range(n)]
        r = requests.post(f"{environment.host}/batch/jobs", json={"tickets": tickets}, headers=HEADERS, timeout=30)
        print("background job:", r.status_code, r.json().get("job_id"))


class ApiUser(HttpUser):
    wait_time = between(0.2, 1.0)

    @task(10)
    def predict(self):
        t = random.choice(TICKETS)
        self.client.post("/predict", data=json.dumps(t), headers=HEADERS, name="/predict")

    @task(1)
    def predict_batch_100(self):
        batch = random.sample(TICKETS, k=min(100, len(TICKETS)))
        self.client.post("/predict/batch", data=json.dumps({"tickets": batch}), headers=HEADERS,
                         name="/predict/batch [100]")

    @task(5)
    def health(self):
        self.client.get("/health", name="/health")
