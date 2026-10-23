"""Unit tests for comparing what Studio shows after an upload with what was asked."""

from datetime import datetime, timezone

import pytest

from mcp_youtube_extract.shared.upload.spec import UploadSpec
from mcp_youtube_extract.shared.upload.studio import compare_readback


@pytest.fixture
def make(tmp_path, cfg):
    video = tmp_path / "v.mp4"; video.write_bytes(b"x")
    srt = tmp_path / "c.srt"; srt.write_text("1\n")

    def build(**kw):
        return UploadSpec(channel=cfg.resolve_channel(None), video_path=video, title="The Title", **kw)

    build.srt = srt
    return build


def test_readback_match(make):
    spec = make()
    assert compare_readback(spec, {"title": "The Title", "visibility": "public", "publish_at": None, "caption_languages": []}) == []


def test_readback_scheduled_with_captions_match(make):
    when = datetime(2026, 11, 2, 12, 30, tzinfo=timezone.utc)
    spec = make(visibility=None, publish_at=when, captions_path=make.srt)
    observed = {"title": "The Title", "visibility": "scheduled", "publish_at": when, "caption_languages": ["en"]}
    assert compare_readback(spec, observed) == []


def test_readback_mismatches(make):
    when = datetime(2026, 11, 2, 12, 30, tzinfo=timezone.utc)
    spec = make(visibility=None, publish_at=when, captions_path=make.srt)
    lines = compare_readback(spec, {"title": "Other", "visibility": "private", "publish_at": None, "caption_languages": []})
    assert any("title" in l for l in lines) and any("schedule" in l for l in lines) and any("caption" in l for l in lines)


def test_readback_visibility_mismatch(make):
    lines = compare_readback(make(visibility="unlisted"), {"title": "The Title", "visibility": "public", "publish_at": None, "caption_languages": []})
    assert lines == ["visibility is public, expected unlisted"]
