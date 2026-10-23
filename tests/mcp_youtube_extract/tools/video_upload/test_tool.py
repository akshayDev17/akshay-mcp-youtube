"""Tests for the upload_yt_video tool over a fake backend."""

import re

from mcp_youtube_extract.tools.video_upload.tool import upload_yt_video


def test_video_validation_failure_submits_nothing(fake_service, tmp_path):
    out = upload_yt_video(video_path=str(tmp_path / "missing.mp4"), title="T")
    assert out.startswith("Not uploaded") and "not found" in out and fake_service.backend.uploaded == []


def test_video_happy_path(fake_service, folder):
    out = upload_yt_video(folder=str(folder))
    assert "https://youtu.be/" in out and "public" in out.lower()


def test_video_unfinished_returns_job_id(fake_service, folder):
    fake_service.backend.block_first = True
    fake_service.call_wait(0)
    out = upload_yt_video(folder=str(folder))
    assert "get_yt_upload_status" in out and re.search(r"\b[0-9a-f]{12}\b", out)


def test_retry_after_cutoff_is_refused(fake_service, folder):
    fake_service.backend.block_first = True
    fake_service.call_wait(0)
    first = upload_yt_video(folder=str(folder))
    again = upload_yt_video(folder=str(folder))
    assert again.startswith("Not uploaded") and "already" in again
    job_id = re.search(r"\b[0-9a-f]{12}\b", first).group(0)
    assert job_id in again
    fake_service.backend.release.set()
    fake_service.runner.wait(job_id, 5)
    assert len(fake_service.backend.uploaded) == 1


def test_config_error_is_text(monkeypatch, tmp_path):
    from mcp_youtube_extract.shared.upload import service

    service._reset_for_tests()
    monkeypatch.setattr(service, "HOME", tmp_path / "home")
    monkeypatch.delenv("YT_UPLOAD_CHANNELS", raising=False)
    assert "YT_UPLOAD_CHANNELS" in upload_yt_video(folder="/x")
