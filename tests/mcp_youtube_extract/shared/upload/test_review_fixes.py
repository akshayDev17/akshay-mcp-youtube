"""Regression tests for the final-review findings."""

import fcntl
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from mcp_youtube_extract.shared.upload.backend import UploadOutcome
from mcp_youtube_extract.shared.upload.jobs import JobStore, new_job
from mcp_youtube_extract.shared.upload.runner import JobRunner
from mcp_youtube_extract.shared.upload.session import profile_in_use
from mcp_youtube_extract.shared.upload.spec import UploadSpec, validate_spec

from .conftest import make_folder

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


class IdThenFail:
    """Reports a video id as Studio creates the draft, then fails or blocks."""

    def __init__(self, block=False):
        self.block, self.release, self.reached = block, threading.Event(), threading.Event()
        self.calls = 0

    def ensure_session(self, channel, on_state):
        return None

    def upload(self, spec, on_video_id=None):
        self.calls += 1
        on_video_id("draft000001")
        self.reached.set()
        if self.block:
            self.release.wait(5)
        raise RuntimeError("browser crashed")


def runner_for(tmp_path, cfg, backend, store=None):
    store = store or JobStore(tmp_path / "jobs")
    return JobRunner(store, backend, cfg, pause=lambda s: None, now=lambda: NOW), store


def one_entry(tmp_path, name="v1"):
    d = make_folder(tmp_path, name=name, files={"v.mp4": name.encode(), "title.txt": name})
    return [{"folder": str(d)}]


# 1 + 5: a captured id is saved at once and kept through any later failure.
def test_video_id_saved_as_soon_as_studio_creates_it(tmp_path, cfg):
    backend = IdThenFail(block=True)
    runner, store = runner_for(tmp_path, cfg, backend)
    job = new_job("video", one_entry(tmp_path), None, NOW)
    runner.submit(job)
    assert backend.reached.wait(5)
    time.sleep(0.05)
    assert store.load(job.job_id).entries[0].video_id == "draft000001"
    backend.release.set()
    final = runner.wait(job.job_id, 5)
    assert final.entries[0].state == "needs_attention" and final.entries[0].video_id == "draft000001"


def test_resume_never_reuploads_an_interrupted_draft(tmp_path, cfg):
    store = JobStore(tmp_path / "jobs")
    job = new_job("video", one_entry(tmp_path), None, NOW)
    job.state, job.entries[0].state, job.entries[0].video_id = "interrupted", "interrupted", "draft000001"
    store.save(job)
    backend = IdThenFail()
    runner, _ = runner_for(tmp_path, cfg, backend, store)
    runner.wait(runner.resume(job.job_id).job_id, 5)
    assert backend.calls == 0


# 2: no silent rounding of seconds.
def test_publish_at_must_be_a_whole_minute(tmp_path, cfg):
    video = tmp_path / "v.mp4"; video.write_bytes(b"x")
    spec = UploadSpec(channel=cfg.resolve_channel(None), video_path=video, title="T", visibility=None,
                      publish_at=NOW + timedelta(days=1, seconds=30))
    assert any("whole minute" in p for p in validate_spec(spec, NOW))


# 3: daylight saving — use the local zone's rules on the publish date, not today's offset.
@pytest.fixture
def new_york():
    old = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"; time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ")
    else:
        os.environ["TZ"] = old
    time.tzset()


def test_schedule_texts_use_the_publish_dates_offset(new_york, tmp_path, cfg):
    from mcp_youtube_extract.shared.upload.studio import schedule_texts

    winter = datetime(2027, 1, 15, 23, 0, tzinfo=timezone.utc)      # 6:00 PM EST (UTC-5)
    assert schedule_texts(winter) == ("Jan 15, 2027", "6:00 PM")


def test_parse_schedule_uses_the_dates_offset(new_york):
    from mcp_youtube_extract.shared.upload.studio import _parse_schedule

    assert _parse_schedule("Scheduled Jan 15, 2027, 6:00 PM") == datetime(2027, 1, 15, 23, 0, tzinfo=timezone.utc)


# 4: a second server process must not interrupt a live process's job, and uploads are one at a time across processes.
def test_jobs_owned_by_a_live_process_are_not_interrupted(tmp_path):
    store = JobStore(tmp_path / "jobs")
    job = new_job("video", [{}], None, NOW)
    job.state, job.entries[0].state, job.owner_pid = "running", "uploading", os.getppid()
    store.save(job)
    assert store.mark_interrupted_on_startup() == []
    job.owner_pid = 999_999_999
    store.save(job)
    assert store.mark_interrupted_on_startup() == [job.job_id]


def test_upload_waits_for_another_processes_upload_lock(tmp_path, cfg):
    class Done:
        calls = 0

        def ensure_session(self, channel, on_state):
            return None

        def upload(self, spec, on_video_id=None):
            Done.calls += 1
            return UploadOutcome(status="done", video_id="abc")

    store = JobStore(tmp_path / "jobs")
    store.jobs_dir.mkdir(parents=True)
    held = open(store.jobs_dir / ".upload.lock", "w")
    fcntl.flock(held, fcntl.LOCK_EX)
    runner, _ = runner_for(tmp_path, cfg, Done(), store)
    job = new_job("video", one_entry(tmp_path), None, NOW)
    runner.submit(job)
    time.sleep(0.3)
    assert Done.calls == 0
    fcntl.flock(held, fcntl.LOCK_UN); held.close()
    assert runner.wait(job.job_id, 5).entries[0].state == "done"


# 9: a lock left by a dead browser on this machine is stale.
def test_stale_singleton_lock_is_ignored(tmp_path):
    host = socket.gethostname()
    os.symlink(f"{host}-999999999", tmp_path / "SingletonLock")
    assert not profile_in_use(tmp_path)


def test_live_or_foreign_singleton_lock_counts(tmp_path):
    os.symlink(f"{socket.gethostname()}-{os.getpid()}", tmp_path / "SingletonLock")
    assert profile_in_use(tmp_path)
    other = tmp_path / "other"; other.mkdir()
    os.symlink("some-other-host-123", other / "SingletonLock")
    assert profile_in_use(other)


# 11: one unreadable job file must not break the store.
def test_corrupt_job_file_is_skipped(tmp_path):
    store = JobStore(tmp_path / "jobs")
    good = new_job("video", [{}], None, NOW); good.state = "running"
    store.save(good)
    (tmp_path / "jobs" / "deadbeef0000.json").write_text("{not json")
    assert [j.job_id for j in store.all()] == [good.job_id]
    assert store.mark_interrupted_on_startup() == [good.job_id]
