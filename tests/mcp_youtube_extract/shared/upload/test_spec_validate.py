"""Unit tests for validating upload specs against YouTube's limits."""

from datetime import datetime, timedelta, timezone

import pytest

from mcp_youtube_extract.shared.upload.spec import UploadSpec, build_spec, check_publish_at, validate_spec

from .conftest import make_folder

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def spec(tmp_path, cfg):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")

    def build(**overrides):
        fields = dict(channel=cfg.resolve_channel(None), video_path=video, title="A title")
        fields.update(overrides)
        return UploadSpec(**fields)

    return build


@pytest.mark.parametrize("title, ok", [("x" * 100, True), ("x" * 101, False), ("", False), ("a < b", False), ("a > b", False)])
def test_title_rules(spec, title, ok):
    assert (validate_spec(spec(title=title), NOW) == []) is ok


@pytest.mark.parametrize("desc, ok", [("d" * 5000, True), ("d" * 5001, False), ("<b>", False)])
def test_description_rules(spec, desc, ok):
    assert (validate_spec(spec(description=desc), NOW) == []) is ok


def test_thumbnail_rules(spec, tmp_path):
    big = tmp_path / "big.png"; big.write_bytes(b"0" * (2_097_152 + 1))
    gif = tmp_path / "t.gif"; gif.write_bytes(b"0")
    exact = tmp_path / "ok.jpg"; exact.write_bytes(b"0" * 2_097_152)
    assert any("2 MB" in p for p in validate_spec(spec(thumbnail_path=big), NOW))
    assert any("PNG or JPG" in p for p in validate_spec(spec(thumbnail_path=gif), NOW))
    assert validate_spec(spec(thumbnail_path=exact), NOW) == []


def test_captions_must_be_srt(spec, tmp_path):
    vtt = tmp_path / "c.vtt"; vtt.write_text("WEBVTT")
    assert any(".srt" in p for p in validate_spec(spec(captions_path=vtt), NOW))


def test_missing_files(spec, tmp_path):
    assert any("not found" in p for p in validate_spec(spec(video_path=tmp_path / "gone.mp4"), NOW))


def test_publish_at_rules(spec):
    past = NOW - timedelta(minutes=1)
    assert "past" in check_publish_at(spec(publish_at=past, visibility=None), NOW)
    assert check_publish_at(spec(publish_at=NOW + timedelta(days=1), visibility=None), NOW) is None
    assert any("visibility" in p for p in validate_spec(spec(publish_at=NOW + timedelta(days=1), visibility="unlisted"), NOW))


def test_build_spec_combines(tmp_path, cfg):
    d = make_folder(tmp_path, files={"v.mp4": b"x", "title.txt": "x" * 101})
    r = build_spec({"folder": str(d)}, None, cfg, NOW)
    assert r.spec is None and any("100" in p for p in r.problems)
