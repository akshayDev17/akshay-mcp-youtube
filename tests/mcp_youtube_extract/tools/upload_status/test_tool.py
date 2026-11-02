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


def _interrupted_playlist(tmp_path, monkeypatch, preview):
    left = new_job("playlist", [{"name": "Mine", "visibility": "public", "video_ids": ["a" * 11], "preview": preview}],
                   None, NOW)
    left.state = "running"; left.entries[0].state = "uploading"
    JobStore(tmp_path / "jobs").save(left)
    service._reset_for_tests()
    monkeypatch.setattr(service, "HOME", tmp_path)
    return left.job_id


def test_interrupted_playlist_create_says_check_studio_not_resume(tmp_path, monkeypatch):
    status = get_yt_upload_status(_interrupted_playlist(tmp_path, monkeypatch, preview=False))
    assert "(create): interrupted" in status and "check Studio before creating it again" in status
    assert "resume" not in status
    service._reset_for_tests()


def test_interrupted_playlist_preview_says_preview_again(tmp_path, monkeypatch):
    status = get_yt_upload_status(_interrupted_playlist(tmp_path, monkeypatch, preview=True))
    assert "Call create_yt_playlist again to preview it." in status and "resume" not in status
    service._reset_for_tests()


def test_resume_does_not_rerun_an_interrupted_playlist_create(fake_service, tmp_path):
    job = new_job("playlist", [{"name": "Mine", "visibility": "public", "video_ids": ["a" * 11]}], None, NOW)
    job.state, job.entries[0].state = "interrupted", "interrupted"
    fake_service.store.save(job)
    fake_service.runner.resume(job.job_id)
    final = fake_service.runner.wait(job.job_id, 5)
    assert fake_service.backend.playlists == [] and final.entries[0].state == "interrupted"
    assert "check Studio before creating it again" in get_yt_upload_status(job.job_id)
