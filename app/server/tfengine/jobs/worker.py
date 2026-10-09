"""Background job execution (one asyncio task per process) and periodic maintenance.

Flow for one job:
    claim (queued -> running) -> for each chunk of 8 tickets:
        predict on the inference lane -> save results + processed += 8 (+ heartbeat)
    -> succeeded (expires_at = now + 6 h)

If the job is deleted meanwhile, `save_results` returns False and the worker drops it.
If this process dies, the heartbeat goes stale and the sweeper marks the job failed/interrupted.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import socket
import uuid

from ..errors import ModelUnavailable
from ..inference.service import InferenceService
from ..validation import Ticket
from .store import FAILED, SUCCEEDED, JobRecord, SQLiteJobStore

log = logging.getLogger("tfengine.jobs")


class JobWorker:
    """Example:
        worker = JobWorker(store, inference, wakeup=manager.wakeup, chunk_size=8)
        worker.start()      # spawns the run loop + sweeper + heartbeat tasks
        ...
        await worker.stop()
    """

    def __init__(self, store: SQLiteJobStore, inference: InferenceService, wakeup: asyncio.Event,
                 chunk_size: int = 8, max_running: int = 1, poll_s: float = 1.0, sweep_interval_s: float = 5.0,
                 heartbeat_stale_s: float = 30.0):
        self.store = store
        self.inference = inference
        self.wakeup = wakeup
        self.chunk_size = max(1, chunk_size)
        self.max_running = max_running
        self.poll_s = poll_s
        self.sweep_interval_s = sweep_interval_s
        self.heartbeat_stale_s = heartbeat_stale_s
        # Unique per process. Example: "a1b2c3d4e5f6:7:9f8e7d6c"
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.current_job: str | None = None
        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()

    # --- lifecycle -----------------------------------------------------------------------
    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._run_loop(), name="job-worker"),
            asyncio.create_task(self._sweep_loop(), name="job-sweeper"),
            asyncio.create_task(self._heartbeat_loop(), name="job-heartbeat"),
        ]

    async def stop(self) -> None:
        self._stopping.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t

    # --- main loop -----------------------------------------------------------------------
    async def _run_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                # Don't claim while the model is still loading (a claimed job would sit 'running').
                # Example: job submitted 1 s after boot stays 'queued' until the model is ready.
                if self.inference.state.value == "loading":
                    await asyncio.sleep(min(self.poll_s, 0.5))
                    continue
                job = await asyncio.to_thread(self.store.claim_next, self.worker_id, self.max_running)
                if job is None:
                    # Idle: wake on submit (same process) or after poll_s (jobs submitted by siblings).
                    self.wakeup.clear()
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(self.wakeup.wait(), timeout=self.poll_s)
                    continue
                await self._process(job)
            except asyncio.CancelledError:
                raise
            except Exception:  # never let the loop die
                log.exception("job loop error")
                await asyncio.sleep(self.poll_s)

    async def _process(self, job: JobRecord) -> None:
        self.current_job = job.job_id
        log.info("job %s started: %d tickets", job.job_id, job.total)
        try:
            rows = await asyncio.to_thread(self.store.load_tickets, job.job_id)
            tickets = [Ticket.from_dict(json.loads(r)) for r in rows]
            for start in range(0, len(tickets), self.chunk_size):
                chunk = tickets[start : start + self.chunk_size]
                preds = await self.inference.predict_chunk(chunk)
                results = [(start + i, json.dumps(p, ensure_ascii=False, separators=(",", ":")))
                           for i, p in enumerate(preds)]
                still_ours = await asyncio.to_thread(self.store.save_results, job.job_id, self.worker_id, results)
                if not still_ours:
                    # Example: client sent DELETE mid-run -> stop, nothing left to finish.
                    log.info("job %s cancelled/removed after %d tickets", job.job_id, start)
                    return
            await asyncio.to_thread(self.store.finish, job.job_id, self.worker_id, SUCCEEDED)
            log.info("job %s succeeded", job.job_id)
        except ModelUnavailable as e:
            await asyncio.to_thread(self.store.finish, job.job_id, self.worker_id, FAILED, "model_unavailable",
                                    e.message)
        except asyncio.CancelledError:
            # Graceful shutdown mid-job: record it now instead of waiting for the stale-heartbeat sweep.
            with contextlib.suppress(Exception):
                self.store.finish(job.job_id, self.worker_id, FAILED, "interrupted",
                                  "Service restarted while the job was running.")
            raise
        except Exception as e:
            log.exception("job %s failed", job.job_id)
            await asyncio.to_thread(self.store.finish, job.job_id, self.worker_id, FAILED, "internal_error",
                                    f"Job failed: {type(e).__name__}")
        finally:
            self.current_job = None

    # --- maintenance ---------------------------------------------------------------------
    async def _heartbeat_loop(self) -> None:
        # Keeps the running job "alive" even if one chunk is slow (heartbeat every stale/4 s).
        interval = max(1.0, self.heartbeat_stale_s / 4)
        while not self._stopping.is_set():
            await asyncio.sleep(interval)
            if self.current_job:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(self.store.heartbeat, self.current_job, self.worker_id)

    async def sweep_once(self) -> None:
        # Example: a job left 'running' by a crashed process -> failed/interrupted; expired results purged.
        n = await asyncio.to_thread(self.store.mark_stale_interrupted, self.heartbeat_stale_s)
        if n:
            log.warning("marked %d stale running job(s) as failed/interrupted", n)
        await asyncio.to_thread(self.store.purge_expired)

    async def _sweep_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.sweep_once()
            except Exception:
                log.exception("sweep error")
            await asyncio.sleep(self.sweep_interval_s)
