"""Unit tests for upload outcomes, the job model, its store and status text."""

import re
from datetime import datetime, timedelta, timezone

import pytest

from mcp_youtube_extract.shared.upload.backend import UploadOutcome, failure_outcome
from mcp_youtube_extract.shared.upload.jobs import JobStore, format_status, new_job

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def test_failure_outcome_depends_on_video_id():
    assert failure_outcome(None, "boom", []).status == "failed"
    assert failure_outcome("abc", "boom", ["/x.png"]).status == "needs_attention"


def test_round_trip_and_atomic_save(tmp_path):
    store = JobStore(tmp_path)
    job = new_job("series", [{"folder": "/a"}, {"folder": "/b"}], {"language": "en"}, NOW)
    job.entries[0].apply(UploadOutcome(status="done", video_id="abc", watch_url="https://youtu.be/abc"))
    store.save(job)
    again = store.load(job.job_id)
    assert again == job and re.fullmatch(r"[0-9a-f]{12}", job.job_id)
    assert [p.name for p in tmp_path.iterdir()] == [f"{job.job_id}.json"]


def test_load_unknown_raises(tmp_path):
    with pytest.raises(KeyError):
        JobStore(tmp_path).load("000000000000")


def test_mark_interrupted_on_startup(tmp_path):
    store = JobStore(tmp_path)
    running = new_job("series", [{}, {}, {}], None, NOW); running.state = "running"
    running.entries[0].state = "done"
    running.entries[1].state = "uploading"; running.entries[1].video_id = "vid1"
    done = new_job("video", [{}], None, NOW); done.state = "finished"; done.entries[0].state = "done"
    store.save(running); store.save(done)
    assert store.mark_interrupted_on_startup() == [running.job_id]
    r = store.load(running.job_id)
    assert r.state == "interrupted"
    assert [e.state for e in r.entries] == ["done", "interrupted", "interrupted"]
    assert r.entries[1].video_id == "vid1"
    assert store.load(done.job_id).state == "finished"


def test_recent_filters_by_creation(tmp_path):
    store = JobStore(tmp_path)
    old = new_job("video", [{}], None, NOW - timedelta(days=2))
    fresh = new_job("video", [{}], None, NOW)
    store.save(old); store.save(fresh)
    assert [j.job_id for j in store.recent(NOW - timedelta(hours=24))] == [fresh.job_id]


def test_format_status(tmp_path):
    job = new_job("series", [{"folder": "/a"}, {"folder": "/b"}], None, NOW)
    job.state = "pausing"; job.pause_until = NOW + timedelta(minutes=5)
    job.entries[0].apply(UploadOutcome(status="done", video_id="abc", watch_url="https://youtu.be/abc"))
    text = format_status(job, NOW)
    assert job.job_id in text and "pausing until" in text and "https://youtu.be/abc" in text
    job.state = "finished"; job.entries[1].apply(UploadOutcome(status="failed", problems=["boom"]))
    assert "Not done" in format_status(job, NOW) and "boom" in format_status(job, NOW)
