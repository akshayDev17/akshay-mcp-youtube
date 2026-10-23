"""Unit tests for the Studio backend's language labels, scheduler values and pre-checks."""

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from mcp_youtube_extract.shared.upload.spec import UploadSpec
from mcp_youtube_extract.shared.upload.studio import picker_values, precheck, studio_language_label


def test_language_labels():
    assert studio_language_label("en") == "English"
    assert studio_language_label("en-GB") == "English (United Kingdom)"
    assert studio_language_label("hi") == "Hindi"
    with pytest.raises(ValueError, match="xx-YY"):
        studio_language_label("xx-YY")


def test_picker_values_local_time():
    ist = ZoneInfo("Asia/Kolkata")
    assert picker_values(datetime(2026, 11, 2, 12, 30, tzinfo=timezone.utc), ist) == ("Nov 2, 2026", "6:00 PM")
    assert picker_values(datetime(2026, 10, 23, 18, 30, tzinfo=timezone.utc), ist) == ("Oct 24, 2026", "12:00 AM")
    assert picker_values(datetime(2026, 12, 31, 6, 37, tzinfo=timezone.utc), ist) == ("Dec 31, 2026", "12:07 PM")


@pytest.fixture
def spec(tmp_path, cfg):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    return lambda **kw: UploadSpec(channel=cfg.resolve_channel(None), video_path=video, title="T", **kw)


def test_precheck_accepts_matching_languages(spec, tmp_path):
    srt = tmp_path / "c.srt"; srt.write_text("1\n")
    assert precheck(spec(language="hi", audio_language="hi", captions_language="hi", captions_path=srt)) == []


def test_precheck_rejects_what_studio_cannot_set(spec, tmp_path):
    srt = tmp_path / "c.srt"; srt.write_text("1\n")
    assert any("xx" in p for p in precheck(spec(language="xx", audio_language="xx", captions_language="xx")))
    assert any("title/description language" in p for p in precheck(spec(language="en", audio_language="hi", captions_language="hi")))
    assert any("captions" in p for p in precheck(spec(captions_path=srt, captions_language="hi")))
    # A caption language with no captions file is irrelevant.
    assert precheck(spec(captions_language="hi")) == []


def test_video_id_is_captured_right_after_choosing_the_file(spec, cfg):
    from mcp_youtube_extract.shared.upload.studio import StudioBackend

    names = [name for name, _ in StudioBackend(cfg)._steps(spec())]
    assert names.index("capture video id") == names.index("choose video file") + 1


def test_failure_after_capture_is_needs_attention(spec, cfg, tmp_path):
    from mcp_youtube_extract.shared.upload.studio import StudioBackend

    class Page:
        def screenshot(self, path): Path(path).write_bytes(b"png")
        def evaluate(self, script): return "page text"

    backend = StudioBackend(cfg)

    def boom(page):
        raise RuntimeError("selector vanished")

    backend._steps = lambda s: [("capture video id", lambda p: setattr(backend, "_video_id", "abcdefghijk")),
                                ("set languages", boom)]
    outcome = backend._run_steps(Page(), None, spec())
    assert outcome.status == "needs_attention" and outcome.video_id == "abcdefghijk"
    assert outcome.problems == ["set languages: selector vanished"]
    assert outcome.studio_url == "https://studio.youtube.com/video/abcdefghijk/edit"


def test_daily_upload_limit_is_recognised():
    from mcp_youtube_extract.shared.upload.studio import upload_blocker

    text = "Details ... Daily upload limit reached Upload more videos daily after a one-time verification or wait 24 hours. Verify"
    assert "daily upload limit" in upload_blocker(text).lower()
    assert upload_blocker("Details Title (required) Video link https://youtu.be/abcdefghijk") is None
