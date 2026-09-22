"""In-process job runner with progress events (SSE)."""

from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued | running | done | failed
    progress: float = 0.0
    message: str = ""
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    events: list[dict] = field(default_factory=list)
    _subscribers: list[queue.Queue] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def emit(self, message: str, progress: Optional[float] = None, **extra) -> None:
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        self.message = message
        ev = {"job_id": self.id, "status": self.status, "progress": round(self.progress, 3), "message": message, "t": round(time.time() - self.created_at, 2), **extra}
        # append + fan-out under the lock so a subscriber that is replaying history never misses an event
        with self._lock:
            self.events.append(ev)
            for q in list(self._subscribers):
                q.put(ev)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            for ev in self.events[-50:]:
                q.put(ev)
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status, "progress": round(self.progress, 3), "message": self.message, "error": self.error, "created_at": self.created_at, "finished_at": self.finished_at, "result": self.result if isinstance(self.result, (dict, list, str, int, float)) or self.result is None else str(self.result)}


class JobRunner:
    def __init__(self, max_jobs: int = 200) -> None:
        self.jobs: dict[str, Job] = {}
        self.max_jobs = max_jobs
        self._lock = threading.Lock()

    def _evict_locked(self) -> None:
        """Drop the oldest finished jobs once the registry exceeds max_jobs (running jobs are never evicted)."""
        if len(self.jobs) <= self.max_jobs:
            return
        finished = sorted((j for j in self.jobs.values() if j.status in ("done", "failed")), key=lambda j: j.finished_at or j.created_at)
        for old in finished:
            if len(self.jobs) <= self.max_jobs:
                break
            self.jobs.pop(old.id, None)

    def submit(self, kind: str, fn: Callable[[Job], Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self.jobs[job.id] = job
            self._evict_locked()

        def run() -> None:
            job.status = "running"
            job.emit("started", 0.0)
            try:
                job.result = fn(job)
                job.status = "done"
                job.finished_at = time.time()
                job.emit("done", 1.0)
            except Exception as e:  # noqa: BLE001
                job.status = "failed"
                job.error = f"{e}\n{traceback.format_exc()[-1200:]}"
                job.finished_at = time.time()
                job.emit(f"failed: {e}", job.progress)

        threading.Thread(target=run, daemon=True, name=f"job-{job.id}").start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)
