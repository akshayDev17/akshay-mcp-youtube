"""The job runner: one worker thread, one upload at a time across all channels and jobs.

Within a job, entries run in order. An entry that fails is recorded and skipped; the
rest carry on. Between two consecutive upload attempts in a job the worker pauses a
random 1-10 minutes. Every change is saved, so status survives the server stopping.
"""

import os
import queue
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..logger import get_logger
from .backend import Backend, failure_outcome
from .config import UploadConfig
from .jobs import Job, JobStore
from .spec import UploadSpec, build_spec, check_publish_at

logger = get_logger(__name__)

GAP_MIN_S = 60
GAP_MAX_S = 600
DUPLICATE_WINDOW = timedelta(hours=24)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobRunner:
    def __init__(
        self,
        store: JobStore,
        backend: Backend,
        config: UploadConfig,
        *,
        rng: random.Random | None = None,
        pause: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = _utc_now,
    ):
        self.store = store
        self.backend = backend
        self.config = config
        self.rng = rng or random.Random()
        self.pause = pause
        self.now = now
        self._jobs: dict[str, Job] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._changed = threading.Condition()
        self._worker = threading.Thread(target=self._work, name="yt-upload-worker", daemon=True)
        self._worker.start()

    # -- public ---------------------------------------------------------------

    def submit(self, job: Job) -> None:
        job.state = "queued"
        self._save(job)
        self._queue.put(job.job_id)

    def get(self, job_id: str) -> Job:
        with self._changed:
            if job_id in self._jobs:
                return self._jobs[job_id]
        return self.store.load(job_id)

    def wait(self, job_id: str, timeout_s: float) -> Job:
        deadline = time.monotonic() + timeout_s
        with self._changed:
            while True:
                job = self._jobs.get(job_id) or self.store.load(job_id)
                remaining = deadline - time.monotonic()
                if job.finished or remaining <= 0:
                    return job
                self._changed.wait(remaining)

    def resume(self, job_id: str) -> Job:
        job = self.get(job_id)
        if not job.finished:
            return job
        for entry in job.entries:
            if entry.state == "failed" or (entry.state == "interrupted" and not entry.video_id):
                entry.state = "waiting"
                entry.problems, entry.evidence = [], []
        job.message = None
        self.submit(job)
        return job

    @staticmethod
    def file_key(spec: UploadSpec) -> list:
        stat = os.stat(spec.video_path)
        return [spec.channel.channel_id, os.path.realpath(spec.video_path), stat.st_size, stat.st_mtime_ns]

    def find_duplicate(self, spec: UploadSpec) -> str | None:
        key = self.file_key(spec)
        for job in self.store.recent(self.now() - DUPLICATE_WINDOW):
            for entry in job.entries:
                if entry.file_key == key and entry.state != "failed":
                    return job.job_id
        return None

    # -- worker ---------------------------------------------------------------

    def _save(self, job: Job) -> None:
        with self._changed:
            self._jobs[job.job_id] = job
            self.store.save(job)
            self._changed.notify_all()

    def _work(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                self._run(self._jobs.get(job_id) or self.store.load(job_id))
            except Exception:  # never let one job kill the worker
                logger.error(f"upload job {job_id} crashed", exc_info=True)

    def _run(self, job: Job) -> None:
        job.state = "running"
        self._save(job)
        attempted = False
        for entry in job.entries:
            if entry.state != "waiting":
                continue
            try:
                attempted = self._run_entry(job, entry, attempted) or attempted
            except Exception as error:
                logger.error(f"upload job {job.job_id} entry {entry.index} crashed", exc_info=True)
                entry.apply(failure_outcome(entry.video_id, f"internal error: {error}", []))
            job.state, job.message, job.pause_until = "running", None, None
            self._save(job)
        job.state = "finished"
        self._save(job)

    def _run_entry(self, job: Job, entry, attempted: bool) -> bool:
        """Returns True if the backend upload was attempted."""
        result = build_spec(entry.params, job.defaults, self.config, self.now())
        if result.spec is None:
            entry.state, entry.problems, entry.warnings = "failed", result.problems, result.warnings
            return False
        spec = result.spec
        entry.warnings = list(result.warnings)
        entry.file_key = self.file_key(spec)

        if attempted:
            gap = self.rng.uniform(GAP_MIN_S, GAP_MAX_S)
            job.state, job.pause_until = "pausing", self.now() + timedelta(seconds=gap)
            self._save(job)
            self.pause(gap)

        def on_state(state: str, message: str | None) -> None:
            job.state, job.message, job.pause_until = state, message, None
            self._save(job)

        job.state, job.pause_until = "running", None
        self._save(job)
        reason = self.backend.ensure_session(spec.channel, on_state)
        if reason:
            entry.state, entry.problems = "failed", [reason]
            return False

        late = check_publish_at(spec, self.now())
        if late:
            entry.state, entry.problems = "failed", [late]
            return False

        job.state, job.message = "running", None
        entry.state = "uploading"
        self._save(job)
        try:
            outcome = self.backend.upload(spec)
        except Exception as error:
            logger.error(f"upload of entry {entry.index} in job {job.job_id} raised", exc_info=True)
            outcome = failure_outcome(None, f"internal error: {error}", [])
        entry.apply(outcome)
        return True
