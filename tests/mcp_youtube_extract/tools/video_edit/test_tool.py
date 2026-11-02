"""Tests for the edit_yt_video tool over a fake backend."""

import asyncio
import re

from mcp_youtube_extract._app import app
from mcp_youtube_extract.tools.video_edit.tool import edit_yt_video

VIDEO = "-TdbFuCqIA0"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_invalid_request_changes_nothing(fake_service, tmp_path):
    fake = tmp_path / "t.png"; fake.write_bytes(b"not an image")
    out = edit_yt_video(video_id=VIDEO, title="New", thumbnail_path=str(fake))
    assert out.startswith("Not edited") and "not a PNG image" in out
    assert fake_service.backend.edited == [] and fake_service.store.all() == []


def test_nothing_to_change_is_refused(fake_service):
    out = edit_yt_video(video_id=VIDEO)
    assert out.startswith("Not edited") and "nothing to change" in out
    assert fake_service.backend.edited == []


def test_only_given_fields_are_sent(fake_service, tmp_path):
    thumb = tmp_path / "t.png"; thumb.write_bytes(PNG)
    out = edit_yt_video(video_id=VIDEO, thumbnail_path=str(thumb))
    spec = fake_service.backend.edited[0]
    assert spec.requested == ["thumbnail"] and spec.title is None and spec.description is None
    assert out.startswith("Edit job") and ": finished" in out and "done" in out


def test_title_and_description_edit(fake_service):
    out = edit_yt_video(video_id=VIDEO, title="New title", description="New description")
    spec = fake_service.backend.edited[0]
    assert spec.requested == ["title", "description"] and spec.video_id == VIDEO
    assert f"Entry 1 (video {VIDEO}): done" in out and "title: New title" in out


def test_unfinished_edit_returns_job_id(fake_service):
    fake_service.backend.block_first = True
    fake_service.call_wait(0)
    out = edit_yt_video(video_id=VIDEO, title="New")
    assert "get_yt_upload_status" in out and "edit job" in out
    job_id = re.search(r"\b[0-9a-f]{12}\b", out).group(0)
    fake_service.backend.release.set()
    assert fake_service.runner.wait(job_id, 5).entries[0].state == "done"


def test_config_error_is_text(monkeypatch, tmp_path):
    from mcp_youtube_extract.shared.upload import service

    service._reset_for_tests()
    monkeypatch.setattr(service, "HOME", tmp_path / "home")
    monkeypatch.delenv("YT_UPLOAD_CHANNELS", raising=False)
    assert "YT_UPLOAD_CHANNELS" in edit_yt_video(video_id=VIDEO, title="T")


def test_description_says_the_media_file_is_not_replaced():
    tool = next(t for t in asyncio.run(app.list_tools()) if t.name == "edit_yt_video")
    text = tool.description.lower()
    assert "cannot be replaced" in text and "never re-uploads or deletes" in text
    assert {"video_id", "title", "description", "thumbnail_path", "captions_path", "captions_language"} <= set(
        tool.input_schema["properties"]
    )
    assert tool.input_schema["required"] == ["video_id"]
