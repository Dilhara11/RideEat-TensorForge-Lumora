"""Job service rules on top of the store: submit, status, results paging, delete.

This is what the HTTP routes call; it turns store states into contract responses/errors
(404 unknown, 410 expired, 409 not ready, 429 full) and formats `BatchJobStatus`.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone

from ..errors import JobExpired, JobNotFound, JobNotReady, TooManyJobs
from ..validation import Ticket
from .store import ACTIVE, FAILED, QUEUED, SUCCEEDED, CapacityExceeded, JobRecord, SQLiteJobStore


def iso(ts: float | None) -> str | None:
    # Example: 1790931600.0 -> "2026-10-03T09:00:00Z"; None -> None
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class JobManager:
    """Example:
        mgr = JobManager(store, model_version_fn=lambda: "v1.0-abc", max_running=1, max_queued=3)
        status, created = await mgr.submit(tickets, idempotency_key="run-42")
          -> ({"job_id": "...", "status": "queued", "total": 2000, "processed": 0, ...}, True)
        await mgr.status(job_id)               -> BatchJobStatus dict (404 / 410 raised as ApiError)
        await mgr.results_json(job_id, 0, 500) -> raw JSON text of BatchJobResults
    """

    POLL_RETRY_AFTER_S = {QUEUED: 3, "running": 2}  # Retry-After header while unfinished
    SUBMIT_RETRY_AFTER_S = 2
    FULL_RETRY_AFTER_S = 10

    def __init__(self, store: SQLiteJobStore, model_version_fn, max_running: int, max_queued: int):
        self.store = store
        self._model_version_fn = model_version_fn
        self.max_active = max_running + max_queued
        self.wakeup = asyncio.Event()  # set on submit so the worker starts without waiting a poll tick

    # --- formatting ----------------------------------------------------------------------
    @staticmethod
    def to_status(job: JobRecord) -> dict:
        # BatchJobStatus. `error` is an object only for failed jobs, otherwise null.
        return {
            "job_id": job.job_id,
            "status": job.status,
            "total": job.total,
            "processed": job.processed,
            "created_at": iso(job.created_at),
            "started_at": iso(job.started_at),
            "finished_at": iso(job.finished_at),
            "expires_at": iso(job.expires_at),
            "model_version": job.model_version,
            "error": (
                {"code": job.error_code or "failed", "message": job.error_message or "Job failed."}
                if job.status == FAILED else None
            ),
        }

    def retry_after(self, job: JobRecord) -> int | None:
        # Example: running -> 2, queued -> 3, succeeded -> None (no header)
        return self.POLL_RETRY_AFTER_S.get(job.status) if job.status in ACTIVE else None

    # --- operations ----------------------------------------------------------------------
    async def submit(self, tickets: list[Ticket], idempotency_key: str | None) -> tuple[dict, bool]:
        # Serialise compactly once; the worker reloads tickets from SQLite (state survives restarts).
        rows = [json.dumps(t.to_dict(), ensure_ascii=False, separators=(",", ":")) for t in tickets]
        job_id = str(uuid.uuid4())  # opaque + unguessable (contract)
        try:
            job, created = await asyncio.to_thread(
                self.store.create_job, job_id, rows, self._model_version_fn(), idempotency_key, self.max_active
            )
        except CapacityExceeded:
            raise TooManyJobs(self.FULL_RETRY_AFTER_S) from None
        if created:
            self.wakeup.set()
        return self.to_status(job), created

    async def _get_live(self, job_id: str) -> JobRecord:
        # Unknown/deleted -> 404, past retention -> 410.
        job = await asyncio.to_thread(self.store.get_job, job_id)
        if job is None:
            raise JobNotFound()
        if job.is_expired(time.time()):
            raise JobExpired()
        return job

    async def status(self, job_id: str) -> tuple[dict, int | None]:
        job = await self._get_live(job_id)
        return self.to_status(job), self.retry_after(job)

    async def results_json(self, job_id: str, offset: int, limit: int | None) -> str:
        """BatchJobResults as raw JSON text.

        Stored per-ticket results are already JSON, so the page is assembled by string joining
        instead of decode + re-encode (5,000 predictions stay cheap).
        Example: total=2000, offset=0, limit=500 -> next_offset=500; offset=1500, limit=500 -> next_offset=null
        """
        job = await self._get_live(job_id)
        if job.status != SUCCEEDED:
            raise JobNotReady(job.status)
        limit = job.total if limit is None else limit
        rows = await asyncio.to_thread(self.store.page_results, job_id, offset, limit)
        next_offset = offset + limit if offset + limit < job.total else None
        head = {
            "job_id": job.job_id, "status": job.status, "total": job.total, "offset": offset,
            "limit": limit, "next_offset": next_offset, "model_version": job.model_version,
        }
        head_json = json.dumps(head, ensure_ascii=False)
        return head_json[:-1] + ', "predictions": [' + ",".join(rows) + "]}"

    async def delete(self, job_id: str) -> None:
        if not await asyncio.to_thread(self.store.delete, job_id):
            raise JobNotFound()
