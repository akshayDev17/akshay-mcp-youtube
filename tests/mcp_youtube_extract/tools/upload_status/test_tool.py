"""Tests for the get_yt_upload_status tool."""

from datetime import datetime, timezone

from mcp_youtube_extract.shared.upload import service
from mcp_youtube_extract.shared.upload.jobs import JobStore, new_job
from mcp_youtube_extract.tools.upload_status.tool import get_yt_upload_status

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def test_status_unknown_job(fake_service):
    assert "No upload job" in get_yt_upload_status("000000000000")


def test_status_after_restart_shows_interrupted(tmp_path, monkeypatch):
    left = new_job("video", [{"folder": "/a"}], None, NOW)
    left.state = "running"; left.entries[0].state = "uploading"
    JobStore(tmp_path / "jobs").save(left)
    service._reset_for_tests()
    monkeypatch.setattr(service, "HOME", tmp_path)
    assert "interrupted" in get_yt_upload_status(left.job_id)
    service._reset_for_tests()
