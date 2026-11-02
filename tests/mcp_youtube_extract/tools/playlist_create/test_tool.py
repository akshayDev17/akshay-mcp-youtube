"""Tests for the create_yt_playlist tool over the real job runner and a fake backend."""

import re

from mcp_youtube_extract.shared.upload import service
from mcp_youtube_extract.tools.playlist_create.tool import create_yt_playlist
from mcp_youtube_extract.tools.upload_status.tool import get_yt_upload_status

A, B = "aaaaaaaaaaa", "bbbbbbbbbbb"


def test_invalid_request_submits_nothing(fake_service):
    out = create_yt_playlist(name="", visibility="", video_ids=[])
    assert out.startswith("Not created:") and "visibility is required" in out
    assert fake_service.backend.playlists == [] and fake_service.store.all() == []


def test_links_are_refused(fake_service):
    out = create_yt_playlist(name="Mine", visibility="public", video_ids=[f"https://youtu.be/{A}"])
    assert "is not an 11-character YouTube video id" in out and fake_service.backend.playlists == []


def test_preview_is_the_default_and_creates_nothing(fake_service):
    out = create_yt_playlist(name="Mine", visibility="Private", video_ids=[B, A])
    assert "(preview): finished" in out and "nothing created" in out
    assert out.index(f"1. {B}") < out.index(f"2. {A}")
    [(mode, spec)] = fake_service.backend.playlists
    assert mode == "preview" and spec.video_ids == (B, A) and spec.visibility == "private"


def test_preview_false_creates(fake_service):
    out = create_yt_playlist(name="Mine", visibility="public", video_ids=[A], preview=False)
    assert "(create): finished" in out
    assert "Playlist created (status: done)" in out and "list=PLnew0000001" in out
    assert [mode for mode, _ in fake_service.backend.playlists] == ["create"]


def test_unfinished_create_returns_a_job_id_whose_outcome_status_reports(fake_service):
    fake_service.backend.block_first = True
    fake_service.call_wait(0)
    out = create_yt_playlist(name="Mine", visibility="public", video_ids=[A], preview=False)
    assert "get_yt_upload_status" in out
    job_id = re.search(r"\b[0-9a-f]{12}\b", out).group(0)
    fake_service.backend.release.set()
    fake_service.runner.wait(job_id, 5)
    status = get_yt_upload_status(job_id)
    assert f"Playlist job {job_id} (create): finished" in status and "list=PLnew0000001" in status


def test_sign_in_failure_is_reported(fake_service):
    fake_service.backend.session_reason = "sign-in cancelled"
    out = create_yt_playlist(name="Mine", visibility="public", video_ids=[A], preview=False)
    assert "not signed in: sign-in cancelled" in out and fake_service.backend.playlists == []


def test_config_error_is_text(monkeypatch, tmp_path):
    service._reset_for_tests()
    monkeypatch.setattr(service, "HOME", tmp_path / "home")
    monkeypatch.delenv("YT_UPLOAD_CHANNELS", raising=False)
    out = create_yt_playlist(name="Mine", visibility="public", video_ids=[A])
    assert out.startswith("Upload tools are not configured") and "YT_UPLOAD_CHANNELS" in out
