"""The job store and runner the upload tools share, created on first use.

Creating them lazily keeps a missing or malformed YT_UPLOAD_* setting from breaking
the read-only tools: it surfaces as text from the upload tool that needed it.
"""

import threading

from .config import DEFAULT_HOME, UploadConfig, load_config
from .jobs import Job, JobStore
from .runner import JobRunner

HOME = DEFAULT_HOME

_lock = threading.Lock()
_store: JobStore | None = None
_runner: JobRunner | None = None


def get_store() -> JobStore:
    """The job store. On first use in this process, jobs a previous process left
    unfinished are marked interrupted: nothing can be running them any more."""
    global _store
    with _lock:
        if _store is None:
            _store = JobStore(HOME / "jobs")
            _store.mark_interrupted_on_startup()
        return _store


def get_config() -> UploadConfig:
    return load_config(home=HOME)


def get_runner() -> JobRunner:
    """Raises ConfigError when the YT_UPLOAD_* settings are missing or malformed."""
    global _runner
    if _runner is None:
        config = get_config()
        store = get_store()
        from .studio import StudioBackend

        with _lock:
            if _runner is None:
                _runner = JobRunner(store, StudioBackend(config), config)
    return _runner


def get_job(job_id: str) -> Job:
    """KeyError if there is no such job."""
    if _runner is not None:
        return _runner.get(job_id)
    return get_store().load(job_id)


def _reset_for_tests(runner: JobRunner | None = None, store: JobStore | None = None) -> None:
    global _runner, _store
    _runner, _store = runner, store
