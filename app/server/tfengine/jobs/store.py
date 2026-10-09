"""SQLite job repository: the single source of truth for async batch jobs.

Why SQLite (WAL): no extra service in the container, survives process restarts when `DATA_DIR`
is on a volume, and every worker/replica pointing at the same file sees the same jobs
(contract: "state must be shared"). All methods are synchronous and short; the async layer
calls them through `asyncio.to_thread` so the event loop never blocks on disk I/O.

Tables
    jobs(job_id, status, total, processed, timestamps, model_version, error, idempotency_key,
         worker_id, heartbeat_at)
    job_items(job_id, idx, ticket, result)   -- one row per ticket, `idx` = request order
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED = "queued", "running", "succeeded", "failed", "cancelled"
ACTIVE = (QUEUED, RUNNING)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id          TEXT PRIMARY KEY,
    status          TEXT    NOT NULL,
    total           INTEGER NOT NULL,
    processed       INTEGER NOT NULL DEFAULT 0,
    created_at      REAL    NOT NULL,
    started_at      REAL,
    finished_at     REAL,
    expires_at      REAL,
    model_version   TEXT,
    error_code      TEXT,
    error_message   TEXT,
    idempotency_key TEXT UNIQUE,
    worker_id       TEXT,
    heartbeat_at    REAL
);
CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs(status, created_at);
CREATE TABLE IF NOT EXISTS job_items (
    job_id TEXT    NOT NULL,
    idx    INTEGER NOT NULL,
    ticket TEXT    NOT NULL,
    result TEXT,
    PRIMARY KEY (job_id, idx)
) WITHOUT ROWID;
"""


class CapacityExceeded(Exception):
    """Already `max_active` queued+running jobs (-> 429)."""


@dataclass(frozen=True)
class JobRecord:
    """One row of `jobs`.

    Example: JobRecord(job_id="7c9e...", status="running", total=2000, processed=840, ...)
    """

    job_id: str
    status: str
    total: int
    processed: int
    created_at: float
    started_at: float | None
    finished_at: float | None
    expires_at: float | None
    model_version: str | None
    error_code: str | None
    error_message: str | None
    idempotency_key: str | None
    worker_id: str | None
    heartbeat_at: float | None

    def is_expired(self, now: float) -> bool:
        # Example: finished 09:06, retention 6 h -> expired from 15:06 on (status/results -> 410)
        return self.expires_at is not None and now >= self.expires_at


class SQLiteJobStore:
    """Example:
        store = SQLiteJobStore(Path("var/jobs.sqlite3"), retention_s=21600)
        job, created = store.create_job("id1", ['{"i":"T1",...}'], "v1.0-abc", None, max_active=4)
        store.claim_next("worker-a", max_running=1)   -> job now 'running'
        store.save_results("id1", "worker-a", [(0, '{"category": ...}')])  -> True
        store.finish("id1", "worker-a", "succeeded")
        store.page_results("id1", 0, 100)            -> ['{"category": ...}']
    """

    def __init__(self, path: Path, retention_s: int, tombstone_retention_s: int = 7 * 24 * 3600):
        self.path = Path(path)
        self.retention_s = retention_s
        self.tombstone_retention_s = tombstone_retention_s
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")  # readers never block the writer (polling during a job)
            c.executescript(_SCHEMA)

    # --- connection helpers --------------------------------------------------------------
    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        # Short-lived connection per call: thread-safe with asyncio.to_thread and multi-process safe.
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        # BEGIN IMMEDIATE takes the write lock up front -> check-then-write sequences are atomic
        # across threads *and* processes (e.g. capacity check + insert, claim of the next job).
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    @staticmethod
    def _record(row: sqlite3.Row | None) -> JobRecord | None:
        return None if row is None else JobRecord(**dict(row))

    # --- submit / read -------------------------------------------------------------------
    def create_job(self, job_id: str, tickets: list[str], model_version: str | None,
                   idempotency_key: str | None, max_active: int) -> tuple[JobRecord, bool]:
        """Insert a queued job with its tickets. Returns (job, created).

        Example: same Idempotency-Key twice -> second call returns (existing_job, False).
        Example: 4 active jobs and max_active=4 -> CapacityExceeded (-> 429).
        """
        now = time.time()
        with self._tx() as c:
            if idempotency_key is not None:
                existing = c.execute("SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
                if existing is not None:
                    return self._record(existing), False
            active = c.execute(
                f"SELECT COUNT(*) FROM jobs WHERE status IN ({','.join('?' * len(ACTIVE))})", ACTIVE
            ).fetchone()[0]
            if active >= max_active:
                raise CapacityExceeded()
            c.execute(
                "INSERT INTO jobs (job_id, status, total, processed, created_at, model_version, idempotency_key) "
                "VALUES (?, ?, ?, 0, ?, ?, ?)",
                (job_id, QUEUED, len(tickets), now, model_version, idempotency_key),
            )
            c.executemany(
                "INSERT INTO job_items (job_id, idx, ticket) VALUES (?, ?, ?)",
                ((job_id, i, t) for i, t in enumerate(tickets)),
            )
            row = c.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._record(row), True

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._conn() as c:
            return self._record(c.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone())

    def count_active(self) -> int:
        with self._conn() as c:
            return c.execute(
                f"SELECT COUNT(*) FROM jobs WHERE status IN ({','.join('?' * len(ACTIVE))})", ACTIVE
            ).fetchone()[0]

    def page_results(self, job_id: str, offset: int, limit: int) -> list[str]:
        # Stable paging: ordered by request index. Example: offset=1000, limit=1000 -> items 1000..1999
        with self._conn() as c:
            rows = c.execute(
                "SELECT result FROM job_items WHERE job_id = ? ORDER BY idx LIMIT ? OFFSET ?",
                (job_id, limit, offset),
            ).fetchall()
        return [r[0] for r in rows]

    # --- worker side ---------------------------------------------------------------------
    def claim_next(self, worker_id: str, max_running: int) -> JobRecord | None:
        """Atomically move the oldest queued job to running (FIFO). None if nothing to do."""
        now = time.time()
        with self._tx() as c:
            running = c.execute("SELECT COUNT(*) FROM jobs WHERE status = ?", (RUNNING,)).fetchone()[0]
            if running >= max_running:
                return None
            row = c.execute(
                "SELECT job_id FROM jobs WHERE status = ? ORDER BY created_at, job_id LIMIT 1", (QUEUED,)
            ).fetchone()
            if row is None:
                return None
            c.execute(
                "UPDATE jobs SET status = ?, started_at = ?, worker_id = ?, heartbeat_at = ? WHERE job_id = ?",
                (RUNNING, now, worker_id, now, row["job_id"]),
            )
            return self._record(c.execute("SELECT * FROM jobs WHERE job_id = ?", (row["job_id"],)).fetchone())

    def load_tickets(self, job_id: str) -> list[str]:
        with self._conn() as c:
            rows = c.execute("SELECT ticket FROM job_items WHERE job_id = ? ORDER BY idx", (job_id,)).fetchall()
        return [r[0] for r in rows]

    def save_results(self, job_id: str, worker_id: str, results: Iterable[tuple[int, str]]) -> bool:
        """Persist a chunk and bump `processed`. False -> job was deleted/cancelled/taken over: stop.

        Example: chunk of 8 -> processed 840 -> 848 (monotonic, never decreases)
        """
        results = list(results)
        now = time.time()
        with self._tx() as c:
            owned = c.execute(
                "SELECT 1 FROM jobs WHERE job_id = ? AND status = ? AND worker_id = ?", (job_id, RUNNING, worker_id)
            ).fetchone()
            if owned is None:
                return False
            c.executemany(
                "UPDATE job_items SET result = ? WHERE job_id = ? AND idx = ?",
                ((res, job_id, idx) for idx, res in results),
            )
            c.execute(
                "UPDATE jobs SET processed = processed + ?, heartbeat_at = ? WHERE job_id = ?",
                (len(results), now, job_id),
            )
        return True

    def heartbeat(self, job_id: str, worker_id: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE jobs SET heartbeat_at = ? WHERE job_id = ? AND status = ? AND worker_id = ?",
                (time.time(), job_id, RUNNING, worker_id),
            )

    def finish(self, job_id: str, worker_id: str, status: str, error_code: str | None = None,
               error_message: str | None = None) -> bool:
        """running -> succeeded/failed/cancelled; sets finished_at and expires_at (= +retention)."""
        now = time.time()
        with self._conn() as c:
            cur = c.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, expires_at = ?, error_code = ?, error_message = ? "
                "WHERE job_id = ? AND status = ? AND worker_id = ?",
                (status, now, now + self.retention_s, error_code, error_message, job_id, RUNNING, worker_id),
            )
            return cur.rowcount == 1

    # --- client delete -------------------------------------------------------------------
    def delete(self, job_id: str) -> bool:
        """Cancel (queued/running) or discard (finished). Afterwards the id is unknown (404).

        A running worker notices on its next `save_results` (returns False) and stops.
        """
        with self._tx() as c:
            cur = c.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            c.execute("DELETE FROM job_items WHERE job_id = ?", (job_id,))
        return cur.rowcount == 1

    # --- maintenance ---------------------------------------------------------------------
    def mark_stale_interrupted(self, stale_s: float) -> int:
        """Running jobs whose worker stopped heart-beating (crash/restart) -> failed/interrupted.

        Example: container restarted mid-job -> within `stale_s` the job shows
                 {"status": "failed", "error": {"code": "interrupted", ...}} instead of vanishing.
        """
        now = time.time()
        with self._conn() as c:
            cur = c.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, expires_at = ?, error_code = 'interrupted', "
                "error_message = 'Service restarted while the job was running.' "
                "WHERE status = ? AND (heartbeat_at IS NULL OR heartbeat_at < ?)",
                (FAILED, now, now + self.retention_s, RUNNING, now - stale_s),
            )
            return cur.rowcount

    def purge_expired(self) -> tuple[int, int]:
        """Drop result rows of expired jobs (job row kept -> 410), then drop very old tombstones (-> 404)."""
        now = time.time()
        with self._tx() as c:
            items = c.execute(
                "DELETE FROM job_items WHERE job_id IN (SELECT job_id FROM jobs WHERE expires_at IS NOT NULL "
                "AND expires_at <= ?)", (now,),
            ).rowcount
            jobs = c.execute(
                "DELETE FROM jobs WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now - self.tombstone_retention_s,),
            ).rowcount
        return items, jobs
