"""Tests for the create_yt_playlist tool with Studio and the session faked."""

import pytest

from mcp_youtube_extract.shared.upload import service, session, studio_playlist
from mcp_youtube_extract.shared.upload.playlist import PlaylistOutcome, VideoFacts
from mcp_youtube_extract.tools.playlist_create.tool import create_yt_playlist

MAIN = "UCDzx6hNPpuha4fCwYA5WAyg"
A, B = "aaaaaaaaaaa", "bbbbbbbbbbb"


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("YT_UPLOAD_CHANNELS", f"main={MAIN}")
    monkeypatch.setattr(service, "HOME", tmp_path / "home")
    seen = {"preview": [], "create": [], "session": []}

    def preview(spec, config):
        seen["preview"].append(spec)
        return [VideoFacts(v, title=f"T{v[0]}", visibility="unlisted") for v in spec.video_ids], []

    def create(spec, config):
        seen["create"].append(spec)
        return PlaylistOutcome("done", playlist_id="PLnew0000001", applied={"name": spec.name})

    monkeypatch.setattr(studio_playlist, "preview", preview)
    monkeypatch.setattr(studio_playlist, "create", create)
    monkeypatch.setattr(session, "ensure_session", lambda ch, cfg, on_state: seen["session"].append(ch.name))
    return seen


def test_invalid_request_touches_nothing(studio):
    out = create_yt_playlist(name="", visibility="", video_ids=[])
    assert out.startswith("Not created:") and "visibility is required" in out
    assert studio == {"preview": [], "create": [], "session": []}


def test_preview_is_the_default_and_creates_nothing(studio):
    out = create_yt_playlist(name="Mine", visibility="Private", video_ids=[B, A])
    assert "nothing created" in out and out.index(f"1. {B}") < out.index(f"2. {A}")
    assert studio["create"] == [] and studio["session"] == ["main"]
    assert studio["preview"][0].video_ids == (B, A) and studio["preview"][0].visibility == "private"


def test_preview_false_creates(studio):
    out = create_yt_playlist(name="Mine", visibility="public", video_ids=[A], preview=False)
    assert "Playlist created (status: done)" in out and "list=PLnew0000001" in out
    assert studio["preview"] == [] and len(studio["create"]) == 1


def test_sign_in_failure_is_reported(studio, monkeypatch):
    monkeypatch.setattr(session, "ensure_session", lambda ch, cfg, on_state: "sign-in cancelled")
    out = create_yt_playlist(name="Mine", visibility="public", video_ids=[A], preview=False)
    assert "not signed in: sign-in cancelled" in out and studio["create"] == []


def test_busy_profile_is_reported(studio, monkeypatch):
    def busy(config):
        raise studio_playlist.ProfileBusy("an upload is using the channel's browser profile")

    monkeypatch.setattr(studio_playlist, "profile_lock", busy)
    out = create_yt_playlist(name="Mine", visibility="public", video_ids=[A], preview=False)
    assert out.startswith("Not created: an upload is using") and studio["create"] == []


def test_config_error_is_text(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "HOME", tmp_path)
    monkeypatch.delenv("YT_UPLOAD_CHANNELS", raising=False)
    out = create_yt_playlist(name="Mine", visibility="public", video_ids=[A])
    assert out.startswith("Upload tools are not configured") and "YT_UPLOAD_CHANNELS" in out
