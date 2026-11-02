"""Unit tests for resolving and validating edit_yt_video's params, before Studio opens."""

import pytest

from mcp_youtube_extract.shared.upload.edit import build_edit_spec, first_caption_text

from .conftest import SECOND

VIDEO = "-TdbFuCqIA0"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
SRT = "1\n00:00:00,500 --> 00:00:04,000\nHello there,\nworld.\n\n2\n00:00:04,500 --> 00:00:06,000\nBye.\n"
VTT = "WEBVTT\n\n00:00.500 --> 00:04.000\nHello from VTT.\n"


@pytest.fixture
def files(tmp_path):
    def write(name, content):
        path = tmp_path / name
        path.write_bytes(content) if isinstance(content, bytes) else path.write_text(content, encoding="utf-8")
        return str(path)

    return write


def problems(cfg, **params):
    result = build_edit_spec({"video_id": VIDEO, **params}, cfg)
    assert result.spec is None
    return result.problems


def test_title_and_description_request(cfg):
    spec = build_edit_spec({"video_id": VIDEO, "title": "New title", "description": "Line 1\r\nLine 2"}, cfg).spec
    assert spec.requested == ["title", "description"]
    assert spec.description == "Line 1\nLine 2"
    assert spec.thumbnail_path is None and spec.captions_path is None
    assert spec.channel.name == "main"


def test_thumbnail_and_captions_request(cfg, files):
    spec = build_edit_spec(
        {"video_id": VIDEO, "thumbnail_path": files("t.png", PNG), "captions_path": files("c.srt", SRT),
         "captions_language": "en"},
        cfg,
    ).spec
    assert spec.requested == ["thumbnail", "captions"]
    assert spec.title is None and spec.description is None


def test_every_field_request(cfg, files):
    spec = build_edit_spec(
        {"video_id": VIDEO, "channel": "second", "title": "T", "description": "D",
         "thumbnail_path": files("t.jpg", JPEG), "captions_path": files("c.vtt", VTT), "captions_language": "hi"},
        cfg,
    ).spec
    assert spec.requested == ["title", "description", "thumbnail", "captions"]
    assert spec.channel.channel_id == SECOND and spec.captions_language == "hi"


def test_empty_description_clears(cfg):
    spec = build_edit_spec({"video_id": VIDEO, "description": ""}, cfg).spec
    assert spec.requested == ["description"] and spec.description == ""


def test_none_values_are_left_out(cfg):
    spec = build_edit_spec({"video_id": VIDEO, "title": "T", "description": None, "thumbnail_path": None}, cfg).spec
    assert spec.requested == ["title"]


def test_video_id_is_required_and_checked(cfg):
    assert "video_id is required" in build_edit_spec({"title": "T"}, cfg).problems
    assert any("not a YouTube video id" in p for p in problems(cfg, video_id="https://youtu.be/x", title="T"))
    assert any("not a YouTube video id" in p for p in problems(cfg, video_id="short", title="T"))


def test_nothing_to_change(cfg):
    assert any(p.startswith("nothing to change") for p in problems(cfg))
    assert any(p.startswith("nothing to change") for p in problems(cfg, channel="main"))


def test_title_rules(cfg):
    assert "title is empty" in problems(cfg, title="   ")
    assert any("101 characters" in p for p in problems(cfg, title="x" * 101))
    assert "title must not contain < or >" in problems(cfg, title="a <b>")


def test_description_rules(cfg):
    assert any("5001 characters" in p for p in problems(cfg, description="x" * 5001))
    assert "description must not contain < or >" in problems(cfg, description="1 > 0")


def test_thumbnail_rules(cfg, files, tmp_path):
    assert any("absolute path" in p for p in problems(cfg, thumbnail_path="t.png"))
    assert any("file not found" in p for p in problems(cfg, thumbnail_path=str(tmp_path / "missing.png")))
    assert any(".png, .jpg or .jpeg" in p for p in problems(cfg, thumbnail_path=files("t.svg", "<svg/>")))
    assert any("is empty" in p for p in problems(cfg, thumbnail_path=files("e.png", b"")))
    assert any("not a PNG image" in p for p in problems(cfg, thumbnail_path=files("fake.png", JPEG)))
    assert any("not a JPEG image" in p for p in problems(cfg, thumbnail_path=files("fake.jpg", PNG)))
    big = files("big.png", PNG + b"\x00" * (2 * 1024 * 1024))
    assert any("limit is 2 MB" in p for p in problems(cfg, thumbnail_path=big))


def test_thumbnail_at_the_limit_is_accepted(cfg, files):
    exact = files("exact.png", PNG + b"\x00" * (2 * 1024 * 1024 - len(PNG)))
    assert build_edit_spec({"video_id": VIDEO, "thumbnail_path": exact}, cfg).spec is not None


def test_captions_rules(cfg, files):
    srt = files("c.srt", SRT)
    assert any(".srt or .vtt" in p for p in problems(cfg, captions_path=files("c.txt", SRT), captions_language="en"))
    assert any("not UTF-8" in p for p in problems(cfg, captions_path=files("l.srt", b"\xff\xfe\x00bad"), captions_language="en"))
    assert any("no timed cues" in p for p in problems(cfg, captions_path=files("n.srt", "just words\n"), captions_language="en"))
    assert any("captions_language is required" in p for p in problems(cfg, captions_path=srt))
    assert any("without captions_path" in p for p in problems(cfg, title="T", captions_language="en"))
    assert any("xx" in p and "Studio" in p for p in problems(cfg, captions_path=srt, captions_language="xx"))


def test_unknown_field_and_channel(cfg):
    assert "unknown field 'visibility'" in problems(cfg, title="T", visibility="private")
    assert any("unknown channel 'nope'" in p for p in problems(cfg, title="T", channel="nope"))


def test_non_text_values(cfg):
    assert "title must be text" in problems(cfg, title=5)


def test_all_problems_are_reported_together(cfg, tmp_path):
    found = problems(cfg, title="", thumbnail_path=str(tmp_path / "x.png"), captions_language="xx")
    assert len(found) >= 3


def test_first_caption_text():
    assert first_caption_text(SRT) == "Hello there, world."
    assert first_caption_text(VTT) == "Hello from VTT."
    assert first_caption_text("1\r\n00:00:01,000 --> 00:00:02,000\r\nCRLF  cue\r\n") == "CRLF cue"
    assert first_caption_text("no cues") == ""
