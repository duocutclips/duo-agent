"""Background jobs for long operations (rendering, batch generation, analysis)."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .errors import AppError
from .logging_setup import get_logger, log_event

log = get_logger("jobs")
Progress = Callable[[str, float], None]


class JobManager:
    def __init__(self, workers: int = 2):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cf-job")
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, fn: Callable[[Progress], Any], *, ref: str | None = None) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        job: dict[str, Any] = {"id": job_id, "kind": kind, "ref": ref, "status": "queued", "message": "Queued", "progress": 0.0,
               "result": None, "error": None, "created": time.time(), "finished": None}
        with self._lock:
            self._jobs[job_id] = job

        def progress(msg: str, frac: float) -> None:
            with self._lock:
                job["message"], job["progress"] = msg, round(max(0.0, min(1.0, frac)), 3)

        def run() -> None:
            with self._lock:
                job["status"] = "running"
                job["message"] = "Running"
            try:
                result = fn(progress)
                with self._lock:
                    job.update(status="succeeded", result=result, progress=1.0, message="Done")
            except AppError as exc:
                log_event(log, "job failed", level=40, job=job_id, kind=kind, error=exc.message, detail=exc.detail)
                with self._lock:
                    job.update(status="failed", error=exc.to_dict(), message=exc.message)
            except Exception as exc:  # never swallow: record and log the full traceback
                log_event(log, "job crashed", level=40, job=job_id, kind=kind, traceback=traceback.format_exc())
                with self._lock:
                    job.update(status="failed", message="Unexpected error",
                               error={"code": "internal_error", "message": f"Unexpected error: {exc}",
                                      "detail": traceback.format_exc()[-1500:]})
            finally:
                with self._lock:
                    job["finished"] = time.time()

        self._pool.submit(run)
        return dict(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            j = self._jobs.get(job_id)
            return dict(j) if j else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: -j["created"])[:limit]
            return [dict(j) for j in jobs]

    def wait(self, job_id: str, timeout: float = 600) -> dict[str, Any]:
        end = time.time() + timeout
        while time.time() < end:
            j = self.get(job_id)
            if j and j["status"] in ("succeeded", "failed"):
                return j
            time.sleep(0.1)
        raise TimeoutError(job_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
