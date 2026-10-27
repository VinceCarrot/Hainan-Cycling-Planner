"""SQLite-backed job queue with a single background worker thread.

Jobs are idempotent by design (handlers upsert) and safe to retry. A job records
progress JSON and log lines; cancellation is cooperative via `cancel_requested`.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .common import dumps, loads, now_iso, row_to_dict, rows_to_dicts
from .context import AppContext

log = logging.getLogger(__name__)

JobHandler = Callable[["JobRun"], dict[str, Any] | None]


class JobCancelled(Exception):
    pass


class JobRun:
    """Handle passed to job handlers for progress/log/cancel checks."""

    def __init__(self, service: "JobService", job_id: int, job_type: str, payload: dict[str, Any]):
        self.service = service
        self.job_id = job_id
        self.job_type = job_type
        self.payload = payload
        self.ctx = service.ctx
        self._last_progress = 0.0

    def log(self, message: str, level: str = "info") -> None:
        log.log(logging.WARNING if level == "warning" else logging.INFO, "[job %s] %s", self.job_id, message)
        with self.ctx.db.transaction() as conn:
            conn.execute("INSERT INTO job_logs (job_id, level, message) VALUES (?,?,?)", (self.job_id, level, message[:2000]))

    def progress(self, **fields: Any) -> None:
        now = time.monotonic()
        with self.ctx.db.transaction() as conn:
            row = conn.execute("SELECT progress_json FROM jobs WHERE id=?", (self.job_id,)).fetchone()
            current = loads(row["progress_json"] if row else None, {})
            current.update(fields)
            current["updated_at"] = now_iso()
            conn.execute("UPDATE jobs SET progress_json=? WHERE id=?", (dumps(current), self.job_id))
        self._last_progress = now

    def check_cancelled(self) -> None:
        row = self.ctx.db.conn().execute("SELECT cancel_requested FROM jobs WHERE id=?", (self.job_id,)).fetchone()
        if row and row["cancel_requested"]:
            raise JobCancelled()


class JobService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.handlers: dict[str, JobHandler] = {}
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()

    def register(self, job_type: str, handler: JobHandler) -> None:
        self.handlers[job_type] = handler

    # ----------------------------------------------------------------- queue
    def enqueue(self, job_type: str, payload: dict[str, Any] | None = None, *, priority: int = 5,
                max_attempts: int = 3, dedupe_key: str | None = None) -> int:
        payload = payload or {}
        with self.ctx.db.transaction() as conn:
            if dedupe_key:
                existing = conn.execute(
                    "SELECT id FROM jobs WHERE dedupe_key=? AND status IN ('queued','running','retry_wait')", (dedupe_key,)
                ).fetchone()
                if existing:
                    return int(existing["id"])
            cur = conn.execute(
                "INSERT INTO jobs (job_type, status, priority, payload_json, dedupe_key, max_attempts) VALUES (?,?,?,?,?,?)",
                (job_type, "queued", priority, dumps(payload), dedupe_key, max_attempts),
            )
            job_id = int(cur.lastrowid)
        self._wake.set()
        return job_id

    def cancel(self, job_id: int) -> bool:
        with self.ctx.db.transaction() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return False
            if row["status"] in ("queued", "retry_wait"):
                conn.execute("UPDATE jobs SET status='cancelled', finished_at=?, cancel_requested=1 WHERE id=?", (now_iso(), job_id))
            else:
                conn.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,))
        return True

    def retry(self, job_id: int) -> bool:
        with self.ctx.db.transaction() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["status"] not in ("failed", "cancelled"):
                return False
            conn.execute(
                "UPDATE jobs SET status='queued', cancel_requested=0, attempt_count=0, last_error=NULL, finished_at=NULL, next_run_at=NULL WHERE id=?",
                (job_id,),
            )
        self._wake.set()
        return True

    def retry_failed(self) -> int:
        with self.ctx.db.transaction() as conn:
            cur = conn.execute("UPDATE jobs SET status='queued', cancel_requested=0, attempt_count=0, last_error=NULL, finished_at=NULL WHERE status='failed'")
            n = cur.rowcount
        self._wake.set()
        return n

    def list_jobs(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        conn = self.ctx.db.conn()
        if status:
            rows = conn.execute("SELECT * FROM jobs WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs ORDER BY (status IN ('running','queued','retry_wait')) DESC, id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = row_to_dict(r) or {}
            d["payload"] = loads(d.pop("payload_json", "{}"), {})
            d["progress"] = loads(d.pop("progress_json", "{}"), {})
            out.append(d)
        return out

    def get_job(self, job_id: int, with_logs: int = 50) -> dict[str, Any] | None:
        conn = self.ctx.db.conn()
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        d = row_to_dict(row)
        if not d:
            return None
        d["payload"] = loads(d.pop("payload_json", "{}"), {})
        d["progress"] = loads(d.pop("progress_json", "{}"), {})
        d["logs"] = rows_to_dicts(conn.execute("SELECT * FROM job_logs WHERE job_id=? ORDER BY id DESC LIMIT ?", (job_id, with_logs)).fetchall())
        return d

    def counts(self) -> dict[str, int]:
        conn = self.ctx.db.conn()
        return {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")}

    # ---------------------------------------------------------------- worker
    STALE_RUNNING_SECONDS = 900

    def recover_interrupted(self) -> int:
        """Jobs left 'running' by a crash are re-queued (idempotent handlers).

        Only *stale* jobs are recovered: a job whose progress or start time was updated within
        STALE_RUNNING_SECONDS may be owned by another live process (e.g. the CLI runner).
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=self.STALE_RUNNING_SECONDS)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        with self.ctx.db.transaction() as conn:
            cur = conn.execute(
                """UPDATE jobs SET status='queued', last_error='recovered after restart'
                   WHERE status='running' AND COALESCE(json_extract(progress_json, '$.updated_at'), started_at, created_at) < ?""",
                (cutoff,),
            )
            return cur.rowcount

    def start_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self.recover_interrupted()
        self._stop.clear()
        self._worker = threading.Thread(target=self._loop, name="job-worker", daemon=True)
        self._worker.start()

    def stop_worker(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._worker:
            self._worker.join(timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self._claim_next()
            if job is None:
                self._wake.wait(timeout=2.0)
                self._wake.clear()
                continue
            self._execute(job)

    def _claim_next(self) -> dict[str, Any] | None:
        now = now_iso()
        with self.ctx.db.transaction() as conn:
            row = conn.execute(
                """SELECT * FROM jobs WHERE (status='queued' OR (status='retry_wait' AND next_run_at <= ?))
                   ORDER BY priority ASC, id ASC LIMIT 1""",
                (now,),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE jobs SET status='running', started_at=COALESCE(started_at, ?), attempt_count=attempt_count+1 WHERE id=?",
                (now, row["id"]),
            )
            d = row_to_dict(row) or {}
        d["payload"] = loads(d.get("payload_json"), {})
        return d

    def run_one(self, job_id: int) -> dict[str, Any] | None:
        """Run a specific queued job synchronously (CLI use)."""
        with self.ctx.db.transaction() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=? AND status IN ('queued','retry_wait')", (job_id,)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE jobs SET status='running', started_at=COALESCE(started_at, ?), attempt_count=attempt_count+1 WHERE id=?", (now_iso(), job_id))
            d = row_to_dict(row) or {}
        d["payload"] = loads(d.get("payload_json"), {})
        self._execute(d)
        return self.get_job(job_id)

    def run_pending(self, max_jobs: int | None = None) -> int:
        """Drain the queue synchronously (CLI use)."""
        n = 0
        while max_jobs is None or n < max_jobs:
            job = self._claim_next()
            if job is None:
                break
            self._execute(job)
            n += 1
        return n

    def _execute(self, job: dict[str, Any]) -> None:
        handler = self.handlers.get(job["job_type"])
        run = JobRun(self, job["id"], job["job_type"], job["payload"])
        if handler is None:
            self._finish(job["id"], "failed", f"no handler for {job['job_type']}")
            return
        try:
            result = handler(run) or {}
            run.progress(result=result)
            self._finish(job["id"], "succeeded", None)
        except JobCancelled:
            self._finish(job["id"], "cancelled", "cancelled by user")
        except Exception as exc:  # noqa: BLE001 - job boundary
            err = f"{exc.__class__.__name__}: {exc}"[:1000]
            log.error("job %s failed: %s\n%s", job["id"], err, traceback.format_exc(limit=5))
            run.log(err, level="error")
            attempt = job.get("attempt_count", 0) + 1
            if attempt < job.get("max_attempts", 3):
                delay = min(600, 30 * (2 ** attempt))
                next_run = (datetime.now(timezone.utc) + timedelta(seconds=delay)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                with self.ctx.db.transaction() as conn:
                    conn.execute("UPDATE jobs SET status='retry_wait', next_run_at=?, last_error=? WHERE id=?", (next_run, err, job["id"]))
            else:
                self._finish(job["id"], "failed", err)

    def _finish(self, job_id: int, status: str, error: str | None) -> None:
        with self.ctx.db.transaction() as conn:
            conn.execute("UPDATE jobs SET status=?, finished_at=?, last_error=? WHERE id=?", (status, now_iso(), error, job_id))
