# TensorForge 2.0: API Engine (`app/server`)

Implementation of the team's API engine plan, including its review and amendments (the design decisions are
summarised under *Architecture* and *Key behaviours* below). It is a FastAPI + ONNX Runtime (CPU) service that implements the
Phase 2 contract (OpenAPI v2.1.0): `/health`, `/predict`, `/predict/batch` and the async `/batch/jobs` API.

## Quick start

```bash
# Docker (build context = repo root, because the model lives in training/models/winner)
docker build -f app/server/Dockerfile -t tensorforge-api .
docker run -p 8000:8000 -e API_KEY=<key> tensorforge-api

# Local (Python 3.12)
cd app/server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
API_KEY=dev-key uvicorn tfengine.main:app --host 0.0.0.0 --port 8000
```

```bash
curl -s localhost:8000/health
curl -s -X POST localhost:8000/predict -H "X-API-Key: dev-key" -H "Content-Type: application/json" \
     -d '{"channel":"chat","text":"bro mage order eka late, refund ekak denna"}'
```

Interactive docs: `http://localhost:8000/docs`.

> **Model bundle required.** The engine loads `training/models/winner/` (`MODEL_DIR`), which must contain
> `model.onnx`, `inference_config.json`, `labels.json` and `tokenizer/tokenizer.json`. Use the files
> exported by notebook 04 on Drive, **including its tokenizer**. The Hugging Face hub copy of the e5
> tokenizer encodes the email header (`email </s> subject`) differently from the Colab export, which
> changes ~30% of predictions. If a file is missing, `/health` stays `503` and the log names the missing
> files. The Docker build fails early.

## Architecture

```
request ─► RequestContextMiddleware (X-Request-ID echo, access log)
        ─► ApiKeyAuthenticator         401  (before the body is touched)
        ─► JsonBodyReader              415 → 413 → 400
        ─► TicketValidator (Pydantic)  422 with details[index, field, issue]
        ─► InferenceService            one inference thread, small chunks (default 2 tickets), FIFO
              └─ OnnxTicketClassifier  TicketEncoder (tokenizers) → ONNX → PredictionDecoder (business rules)
        ─► JobManager / SQLiteJobStore / JobWorker   (async jobs, WAL SQLite in DATA_DIR)
```

| Module | Responsibility |
|---|---|
| `config.py` | `Settings.from_env()`: every knob below |
| `errors.py` | `ApiError` hierarchy → `{"error": {code, message, details}}`, JSON 404/405/500 handlers |
| `security.py` | `ApiKeyAuthenticator`: `X-API-Key` or `Authorization: Bearer`, constant-time, refuses all if `API_KEY` unset |
| `http.py` | `JsonBodyReader`: content type, declared + streamed size cap, JSON parse |
| `validation.py` | `TicketValidator` / `TicketIn`: strict schema rules, all failing batch items, duplicate ids |
| `inference/bundle.py` | `ModelBundle`: required files, `labels.json` vs contract, **sha256 of model.onnx == `model_sha256`** |
| `inference/preprocessing.py` | `TextPreprocessor` (NFC + whitespace) and `TicketEncoder` (pair input, `only_second` truncation with `longest_first` fallback) |
| `inference/decoder.py` | `PredictionDecoder`: temperature, thresholds, primary-masked secondary, spam rule, team table |
| `inference/classifier.py` | `TicketClassifier` interface, `OnnxTicketClassifier` (one ticket per forward pass) |
| `inference/service.py` | `InferenceService`: background load, readiness, single inference lane |
| `jobs/store.py` | `SQLiteJobStore`: atomic capacity check, claim, results, heartbeat, expiry |
| `jobs/manager.py` | `JobManager`: 202/404/409/410/429 rules, idempotency, paging |
| `jobs/worker.py` | `JobWorker`: run loop, heartbeat, stale-job sweeper, retention purge |
| `engine.py` | `Engine`: composition root (tests inject a fake classifier) |
| `main.py` / `api/root.py` | App factory (optional CORS for the separately hosted web client), JSON service card at `/` |

### Key behaviours

- **Check order:** 401 → 415 → 413 → 400 → 422, and never a 5xx for bad input. Unknown routes and wrong
  methods return JSON 404/405.
- **Batch-invariant and deterministic.** The INT8 model runs one ticket per forward pass, so a ticket's
  prediction is identical in `/predict`, `/predict/batch` and job results, in any order. The tests check this.
- **Responsive during jobs.** All model calls share one inference thread (ORT uses 2 intra-op threads),
  and jobs run in chunks of `JOB_CHUNK_SIZE` (2) tickets. A `/predict` waits at most one chunk, and `/health` never touches the model.
- **Jobs:** 1 running + 3 queued, then `429` with `Retry-After`. `Idempotency-Key` is supported. Results are
  kept for 6 h, then `410`. `DELETE` cancels or discards, after which the id returns `404`. If the process
  dies mid-job, the heartbeat goes stale and the job ends as `failed` / `interrupted` within 30 s. Queued
  jobs survive restarts.
- **`model_version`** comes from `inference_config.json` and is verified against the sha256 of `model.onnx`.
  It is the same on `/health`, `/predict`, batch responses and jobs.

### `needs_human_review`

`needs_human_review = confidence < review_threshold`. The threshold is taken from
`inference_config.json → decode.review_threshold`. Notebook 04 fits it on `val_cal`, half of the
validation set that is never used for reported scores. It is the smallest confidence threshold at which
the auto-routed (not flagged) tickets reach ≥ 97% category accuracy, with a **20% review budget**: if
97% would need more than 20% of tickets flagged, the threshold flagging at most 20% (the least confident
tickets) is used.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `API_KEY` | *(unset → every protected call is 401)* | Evaluation key |
| `MODEL_DIR` | `training/models/winner` (image: `/app/model`) | Model bundle |
| `DATA_DIR` | `app/server/var` (image: `/app/data`) | SQLite job store; mount a volume to keep jobs across re-creation |
| `ONNX_THREADS` | `2` | ORT intra-op threads |
| `JOB_CHUNK_SIZE` | `2` | Tickets per inference slot. A `/predict` arriving during a job waits for at most one slot |
| `MAX_RUNNING_JOBS` / `MAX_QUEUED_JOBS` | `1` / `3` | Capacity before `429` |
| `JOB_RETENTION_S` | `21600` | Retention after completion (then `410`) |
| `HEARTBEAT_STALE_S` | `30` | Running job without heartbeat → `failed/interrupted` |
| `PREDICT_READY_TIMEOUT_S` | `60` | How long a prediction waits for a model that is still loading |
| `VERIFY_MODEL_HASH` | `1` | Check sha256(model.onnx) against `inference_config.json` |
| `CORS_ORIGINS` | *(unset → CORS off)* | Comma-separated browser origins allowed to call the API, e.g. the web client on AWS Amplify (`https://main.<app-id>.amplifyapp.com`). Requests without an `Origin` header (curl, the evaluation harness) are unaffected |
| `LOG_LEVEL` | `INFO` | Logs never contain the API key or ticket text |

## Tests

```bash
cd app/server
pytest                       # 139 tests; contract tests use a fake classifier (seconds)
pytest -m model              # real ONNX bundle only (auto-skipped if the bundle is incomplete)
TFENGINE_TEST_MODEL_DIR=/path/to/winner pytest -m model
```

- **Contract:** auth, check order, every 4xx, JSON 404/405, `X-Request-ID`. Every response is validated
  against the organizers' official JSON Schemas, kept in [`contract/`](contract/) with the OpenAPI spec.
- **Business rules:** spam ⇒ not urgent and no secondary, secondary ≠ category, team table.
- **Jobs:** lifecycle with legal, monotonic transitions, paging, 404/409/410/429, idempotency, cancel,
  restart → `interrupted`, queued job survives a restart, 5,000-ticket submit < 5 s, `/health` and
  `/predict` latency while a job runs.
- **Parity:** the decoder matches `training/src/tfml/rules.py` exactly.
- **Real model:** multilingual / emoji / prompt-injection / long-text fixtures
  (`tests/fixtures/multilingual_tickets.json`), batch invariance, and the 500-char subject fallback.

Load test (optional, `pip install locust`):
`API_KEY=<key> locust -f loadtest/locustfile.py --host http://localhost:8000 --headless -u 4 -r 2 -t 2m`
(set `JOB_TICKETS=5000` to run a background job during the test).

## Measured (local WSL2, pinned to 2 cores with `taskset`, model `v1.2-558395869056`)

xlmr-base, FP16-stored weights computed in FP32 (`model.onnx` 530 MB), `JOB_CHUNK_SIZE=2`.

| Check | Contract target | Measured |
|---|---|---|
| `/health` 200 after start (includes sha256 check of the model) | ≤ 120 s | 17 s |
| `/predict` p50 / p95 (idle) | p95 < 1 s | 140 ms / 274 ms |
| `/predict/batch` (100) | < 30 s | 16.4 s |
| `POST /batch/jobs` 5,000 → 202 | < 5 s | 0.15 s |
| 5,000-ticket job | < 30 min | 15.1 min (907 s, ~5.5 tickets/s) |
| 2,000-ticket job (from the same rate) | < 15 min | ~6 min |
| `/health` p95 during job | < 1 s | 4 ms |
| `/predict` p95 / max during job | < 1 s | 564 ms / 793 ms |
| Validation category accuracy (end to end, via a job) | n/a | 0.80875 (= notebook 05 FP32 and FP16) |
| Process RSS after the 5,000-ticket job | 4 GB box | ~2.0 GB |
| `scripts/smoke_test.py` against the live server | n/a | 55/55 checks pass |

The reference box may be slower than this machine. Notebook 05 measured ~373 ms per ticket on Colab's CPU,
which would put a 5,000-ticket job at ~30 min. Check it on the deployed instance with
`python scripts/smoke_test.py --base-url <url> --job-size 2000` before submitting.
