"""Unit tests for edit jobs in the job runner, using a fake backend."""

import threading
from datetime import datetime, timezone

import pytest

from mcp_youtube_extract.shared.upload.backend import UploadOutcome
from mcp_youtube_extract.shared.upload.jobs import JobStore, format_status, new_job
from mcp_youtube_extract.shared.upload.runner import JobRunner

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
VIDEO = "-TdbFuCqIA0"


class FakeBackend:
    def __init__(self, outcome=None, session_reason=None):
        self.outcome = outcome
        self.session_reason = session_reason
        self.sessions, self.edits, self.uploads = [], [], []

    def ensure_session(self, channel, on_state):
        self.sessions.append(channel.name)
        return self.session_reason

    def upload(self, spec, on_video_id=None):
        self.uploads.append(spec)
        return UploadOutcome(status="done", video_id="vid00000001")

    def edit(self, spec):
        self.edits.append(spec)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome or UploadOutcome(status="done", video_id=spec.video_id, applied={"title": spec.title})


@pytest.fixture
def run_edit(tmp_path, cfg):
    def run(params, backend):
        pauses = []
        runner = JobRunner(JobStore(tmp_path / "jobs"), backend, cfg, pause=pauses.append, now=lambda: NOW)
        job = new_job("edit", [params], None, NOW)
        job.entries[0].video_id = params.get("video_id")
        runner.submit(job)
        final = runner.wait(job.job_id, 5)
        assert final.finished and pauses == []
        return final

    return run


def test_edit_job_runs_the_backend_edit(run_edit):
    backend = FakeBackend()
    final = run_edit({"video_id": VIDEO, "title": "New"}, backend)
    entry = final.entries[0]
    assert entry.state == "done" and entry.applied == {"title": "New"}
    assert [s.title for s in backend.edits] == ["New"] and backend.uploads == []
    assert backend.sessions == ["main"]


def test_edit_revalidated_before_studio(run_edit, tmp_path):
    backend = FakeBackend()
    final = run_edit({"video_id": VIDEO, "thumbnail_path": str(tmp_path / "gone.png")}, backend)
    entry = final.entries[0]
    assert entry.state == "failed" and "file not found" in entry.problems[0]
    assert backend.sessions == [] and backend.edits == []


def test_edit_session_failure(run_edit):
    backend = FakeBackend(session_reason="sign-in cancelled: the sign-in window was closed")
    final = run_edit({"video_id": VIDEO, "title": "New"}, backend)
    assert final.entries[0].state == "failed" and "sign-in cancelled" in final.entries[0].problems[0]
    assert backend.edits == []


def test_edit_backend_exception_needs_attention(run_edit):
    backend = FakeBackend(outcome=RuntimeError("browser crashed"))
    final = run_edit({"video_id": VIDEO, "title": "New"}, backend)
    entry = final.entries[0]
    assert entry.state == "needs_attention" and entry.video_id == VIDEO
    assert "browser crashed" in entry.problems[0] and "check the video in Studio" in entry.problems[0]


def test_edit_job_status_text(run_edit):
    outcome = UploadOutcome(status="needs_attention", video_id=VIDEO, studio_url="https://studio/x",
                            applied={"title": "New"}, problems=["captions not applied (upload captions: timeout)"])
    final = run_edit({"video_id": VIDEO, "title": "New", "captions_path": None}, FakeBackend(outcome=outcome))
    text = format_status(final, NOW)
    assert text.startswith(f"Edit job {final.job_id}: finished")
    assert f"Entry 1 (video {VIDEO}): needs_attention" in text
    assert "  title: New" in text and "problem: captions not applied" in text
    assert "Not done:" in text


def test_interrupted_edit_is_marked_on_startup(tmp_path):
    store = JobStore(tmp_path / "jobs")
    job = new_job("edit", [{"video_id": VIDEO, "title": "New"}], None, NOW)
    job.state, job.owner_pid = "running", 999_999_999
    job.entries[0].state = "editing"
    store.save(job)
    assert store.mark_interrupted_on_startup() == [job.job_id]
    assert store.load(job.job_id).entries[0].state == "interrupted"


def test_resume_reruns_an_interrupted_edit(tmp_path, cfg):
    store = JobStore(tmp_path / "jobs")
    job = new_job("edit", [{"video_id": VIDEO, "title": "New"}], None, NOW)
    job.entries[0].video_id = VIDEO
    job.state, job.owner_pid = "running", 999_999_999
    job.entries[0].state = "editing"
    store.save(job)
    store.mark_interrupted_on_startup()
    backend = FakeBackend()
    runner = JobRunner(store, backend, cfg, pause=lambda s: None, now=lambda: NOW)
    runner.resume(job.job_id)
    final = runner.wait(job.job_id, 5)
    assert final.finished and final.entries[0].state == "done"
    assert [s.title for s in backend.edits] == ["New"]


def test_edit_waits_for_a_running_upload(tmp_path, cfg):
    """An edit queued behind an upload starts only after it: one browser at a time."""
    release, started = threading.Event(), threading.Event()
    order = []

    class Blocking(FakeBackend):
        def upload(self, spec, on_video_id=None):
            order.append("upload")
            started.set()
            release.wait(5)
            return UploadOutcome(status="done", video_id="vid00000001")

        def edit(self, spec):
            order.append("edit")
            return super().edit(spec)

    folder = tmp_path / "v"; folder.mkdir()
    (folder / "v.mp4").write_bytes(b"x"); (folder / "title.txt").write_text("T")
    runner = JobRunner(JobStore(tmp_path / "jobs"), Blocking(), cfg, pause=lambda s: None, now=lambda: NOW)
    upload = new_job("video", [{"folder": str(folder)}], None, NOW)
    edit = new_job("edit", [{"video_id": VIDEO, "title": "New"}], None, NOW)
    runner.submit(upload)
    runner.submit(edit)
    assert started.wait(5)
    assert runner.get(edit.job_id).state == "queued"
    release.set()
    assert runner.wait(edit.job_id, 5).entries[0].state == "done"
    assert order == ["upload", "edit"]
