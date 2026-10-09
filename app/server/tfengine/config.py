"""Runtime settings, read once from environment variables.

Every knob has a contract-safe default, so `docker run -p 8000:8000 -e API_KEY=<key> <image>`
is enough. The API key is kept out of `repr()` so it can never leak into logs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

def repo_root(config_file: Path) -> Path:
    """Base folder for the default paths (only used when MODEL_DIR/DATA_DIR are not set).

    Example: /home/me/TensorForge/app/server/tfengine/config.py -> /home/me/TensorForge  (repo checkout)
             /app/tfengine/config.py                            -> /app                  (Docker image; the
             image sets MODEL_DIR/DATA_DIR, so these defaults are never used there)
    """
    parents = Path(config_file).resolve().parents
    if len(parents) > 3 and parents[1].name == "server" and parents[2].name == "app":
        return parents[3]
    return parents[1]


_REPO_ROOT = repo_root(Path(__file__))

MB = 1024 * 1024


def _env_int(name: str, default: int) -> int:
    # Example: JOB_CHUNK_SIZE="16" -> 16; unset or "" -> default
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    # Example: PREDICT_READY_TIMEOUT_S="2.5" -> 2.5
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


def _env_origins(name: str) -> tuple[str, ...]:
    # Example: CORS_ORIGINS="https://main.d1abc.amplifyapp.com/, http://localhost:5173"
    #          -> ("https://main.d1abc.amplifyapp.com", "http://localhost:5173")   (browsers send no trailing slash)
    raw = os.getenv(name, "")
    return tuple(o.strip().rstrip("/") for o in raw.split(",") if o.strip())


def _env_path(name: str, default: Path) -> Path:
    # Example: MODEL_DIR="/app/model" -> Path("/app/model")
    raw = os.getenv(name, "").strip()
    return Path(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    """Immutable service configuration.

    Example:
        Settings.from_env().max_body_bytes["/predict/batch"]  -> 5 * 1024 * 1024
    """

    # --- auth -----------------------------------------------------------------------------
    # None/"" means "refuse every protected call with 401" (contract: never run open).
    api_key: str | None = field(default=None, repr=False)

    # --- model ----------------------------------------------------------------------------
    model_dir: Path = _REPO_ROOT / "training" / "models" / "winner"
    onnx_threads: int = 2  # matches the 2-vCPU reference box
    verify_model_hash: bool = True  # model_version must be tied to the artifact bytes
    predict_ready_timeout_s: float = 60.0  # how long /predict waits for a still-loading model

    # --- request limits (contract: ~1 MB / 5 MB / 25 MB) ------------------------------------
    max_predict_bytes: int = 1 * MB
    max_batch_bytes: int = 5 * MB
    max_job_bytes: int = 25 * MB
    max_batch_items: int = 100
    max_job_items: int = 5000

    # --- jobs -----------------------------------------------------------------------------
    data_dir: Path = _REPO_ROOT / "app" / "server" / "var"
    job_retention_s: int = 6 * 3600  # contract: keep results >= 6 h after completion
    tombstone_retention_s: int = 7 * 24 * 3600  # expired jobs answer 410 for a week, then 404
    max_running_jobs: int = 1
    max_queued_jobs: int = 3  # contract: >= 1 running + 3 queued, then 429
    job_chunk_size: int = 2  # tickets per inference slot -> /predict waits at most one chunk (~0.4 s, xlmr FP32 compute)
    heartbeat_stale_s: float = 30.0  # running job without heartbeat this long -> failed/interrupted
    worker_poll_s: float = 1.0
    sweep_interval_s: float = 5.0

    # --- browser access (the web client is hosted separately, e.g. AWS Amplify) ---------------
    # Origins allowed to call the API from a browser. Empty = CORS off (no CORS headers at all),
    # which is the default and what the evaluation harness sees.
    cors_origins: tuple[str, ...] = ()

    # --- logging --------------------------------------------------------------------------
    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        # Example: data_dir=/app/data -> /app/data/jobs.sqlite3
        return self.data_dir / "jobs.sqlite3"

    @property
    def max_body_bytes(self) -> dict[str, int]:
        # Route path -> byte limit, used by JsonBodyReader for the 413 check.
        return {
            "/predict": self.max_predict_bytes,
            "/predict/batch": self.max_batch_bytes,
            "/batch/jobs": self.max_job_bytes,
        }

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from the process environment.

        Example: API_KEY=s3cret MODEL_DIR=/app/model -> Settings(api_key='s3cret', model_dir=/app/model, ...)
        """
        d = cls()
        return cls(
            api_key=os.getenv("API_KEY") or None,
            model_dir=_env_path("MODEL_DIR", d.model_dir),
            onnx_threads=_env_int("ONNX_THREADS", d.onnx_threads),
            verify_model_hash=os.getenv("VERIFY_MODEL_HASH", "1").strip() not in {"0", "false", "no"},
            predict_ready_timeout_s=_env_float("PREDICT_READY_TIMEOUT_S", d.predict_ready_timeout_s),
            data_dir=_env_path("DATA_DIR", d.data_dir),
            job_retention_s=_env_int("JOB_RETENTION_S", d.job_retention_s),
            tombstone_retention_s=_env_int("TOMBSTONE_RETENTION_S", d.tombstone_retention_s),
            max_running_jobs=_env_int("MAX_RUNNING_JOBS", d.max_running_jobs),
            max_queued_jobs=_env_int("MAX_QUEUED_JOBS", d.max_queued_jobs),
            job_chunk_size=_env_int("JOB_CHUNK_SIZE", d.job_chunk_size),
            heartbeat_stale_s=_env_float("HEARTBEAT_STALE_S", d.heartbeat_stale_s),
            cors_origins=_env_origins("CORS_ORIGINS"),
            log_level=os.getenv("LOG_LEVEL", d.log_level).upper(),
        )
