"""Unit tests for judging an edit field by field, and for how the Studio editor groups
its steps (fake pages; no live Studio)."""

from pathlib import Path

import pytest

from mcp_youtube_extract.shared.upload.edit import EditSpec, edit_status, judge_edit
from mcp_youtube_extract.shared.upload.studio_edit import StudioEditor, video_language_code

VIDEO = "-TdbFuCqIA0"
SRT = "1\n00:00:00,500 --> 00:00:04,000\nHello there,\nworld.\n"


@pytest.fixture
def make(tmp_path, cfg):
    thumb = tmp_path / "new.png"; thumb.write_bytes(b"\x89PNG\r\n\x1a\n")
    srt = tmp_path / "c.srt"; srt.write_text(SRT)

    def build(*fields):
        values = {
            "title": {"title": "New title"},
            "description": {"description": "New description\nline two"},
            "thumbnail": {"thumbnail_path": thumb},
            "captions": {"captions_path": srt, "captions_language": "en"},
        }
        kwargs = {k: v for name in fields for k, v in values[name].items()}
        return EditSpec(channel=cfg.resolve_channel(None), video_id=VIDEO, **kwargs)

    return build


SEEN_OK = {
    "title": "New title",
    "description": "New description\nline two\n",
    "thumbnail_before": "https://i9.ytimg.com/vi/x/mq.jpg?v=1",
    "thumbnail_after": "https://i9.ytimg.com/vi/x/mq.jpg?v=2",
    "captions_first_cue": "Hello there,\nworld.",
}


def test_every_field_applied(make):
    spec = make("title", "description", "thumbnail", "captions")
    applied, problems = judge_edit(spec, SEEN_OK, {})
    assert problems == []
    assert applied == {"title": "New title", "description": "24 characters", "thumbnail": "new.png",
                       "captions": "c.srt (en)"}
    assert edit_status(spec, applied, touched=True) == "done"


def test_only_requested_fields_are_judged(make):
    spec = make("title")
    applied, problems = judge_edit(spec, {"title": "New title"}, {})
    assert applied == {"title": "New title"} and problems == []


def test_mismatches_are_reported_per_field(make):
    spec = make("title", "description", "thumbnail", "captions")
    seen = {"title": "Old", "description": "Old text", "thumbnail_before": "a", "thumbnail_after": "a",
            "captions_first_cue": None}
    applied, problems = judge_edit(spec, seen, {})
    assert applied == {}
    assert [p.split(" ")[0] for p in problems] == ["title", "description", "thumbnail", "captions"]
    assert "Studio shows 'Old'" in problems[0] and "no subtitles" in problems[3]
    assert edit_status(spec, applied, touched=True) == "needs_attention"


def test_partial_success_is_needs_attention(make):
    spec = make("title", "thumbnail")
    applied, problems = judge_edit(spec, {**SEEN_OK, "thumbnail_after": SEEN_OK["thumbnail_before"]}, {})
    assert list(applied) == ["title"] and problems[0].startswith("thumbnail not applied")
    assert edit_status(spec, applied, touched=True) == "needs_attention"


def test_errors_override_observations(make):
    spec = make("title", "captions")
    applied, problems = judge_edit(spec, SEEN_OK, {"captions": "not applied (upload captions: timeout)"})
    assert applied == {"title": "New title"}
    assert problems == ["captions not applied (upload captions: timeout)"]


def test_nothing_touched_is_failed(make):
    spec = make("title")
    applied, _ = judge_edit(spec, {}, {"title": "not applied (open the video's Details page: gone)"})
    assert edit_status(spec, applied, touched=False) == "failed"


def test_cleared_description(make, cfg):
    spec = EditSpec(channel=cfg.resolve_channel(None), video_id=VIDEO, description="")
    applied, problems = judge_edit(spec, {"description": "\n"}, {})
    assert applied == {"description": "cleared"} and problems == []


def test_video_language_code():
    assert video_language_code("Languages\nVideo language: English\nEnglish subtitles ...") == "en"
    assert video_language_code("Video language: Hindi") == "hi"
    assert video_language_code("Video language: Klingon") is None
    assert video_language_code("Languages") is None


# -- how the Studio editor groups its steps ----------------------------------------


class FakePage:
    def screenshot(self, path): Path(path).write_bytes(b"png")
    def evaluate(self, script): return "page text"
    def close(self): pass


class FakeContext:
    def __init__(self):
        self.pages = [FakePage()]
        self.opened = 0

    def set_default_timeout(self, ms): pass

    def new_page(self):
        self.opened += 1
        return FakePage()


def editor(cfg, spec, **steps):
    steps.setdefault("_open_languages", lambda self, page: "Languages\nVideo language: English\n")
    ed = StudioEditor(cfg, spec)
    for name, fn in steps.items():
        setattr(ed, name, fn.__get__(ed))
    return ed


def boom_before_save(self, page, fields):
    self._at("set title")
    raise RuntimeError("selector vanished")


def boom_after_save(self, page, fields):
    self._at("save details")
    self.touched = True
    raise RuntimeError("Timeout 60000ms exceeded.")


def publish_ok(self, page, fields):
    self.touched = True


def read_nothing(self, page, fields):
    pass


def test_captions_still_run_when_details_fail(make, cfg):
    calls = []

    def captions(self, page, fields):
        calls.append(fields)
        self.touched = True

    def read_captions(self, page, fields):
        self.observed["captions_first_cue"] = "Hello there, world."

    ed = editor(cfg, make("title", "captions"), _edit_details=boom_before_save, _edit_captions=captions,
                _read_back_details=read_nothing, _read_back_captions=read_captions)
    outcome = ed.run(FakeContext())
    assert calls == [["captions"]]
    assert outcome.status == "needs_attention"
    assert outcome.applied == {"captions": "c.srt (en)"}
    assert outcome.problems == ["title not applied (set title: selector vanished)"]
    assert any(p.endswith(".png") for p in outcome.evidence)
    assert outcome.studio_url == f"https://studio.youtube.com/video/{VIDEO}/edit"


def test_failure_before_any_save_is_failed_and_skips_read_back(make, cfg):
    reads = []
    ed = editor(cfg, make("title", "description"), _edit_details=boom_before_save,
                _read_back_details=lambda self, page, fields: reads.append(fields))
    outcome = ed.run(FakeContext())
    assert outcome.status == "failed" and reads == []
    assert all(p.endswith("not applied (set title: selector vanished)") for p in outcome.problems)


def test_failure_after_save_click_may_have_applied(make, cfg):
    ed = editor(cfg, make("title"), _edit_details=boom_after_save, _read_back_details=read_nothing)
    outcome = ed.run(FakeContext())
    assert outcome.status == "needs_attention"
    assert outcome.problems == ["title may not have applied (save details: Timeout 60000ms exceeded.)"]


def test_read_back_failure_is_unconfirmed(make, cfg):
    def read_fails(self, page, fields):
        self._at("read back details")
        raise RuntimeError("page did not load")

    ed = editor(cfg, make("title"), _edit_details=publish_ok, _read_back_details=read_fails)
    outcome = ed.run(FakeContext())
    assert outcome.status == "needs_attention"
    assert outcome.problems == ["title saved, but the read-back failed (read back details: page did not load)"]


def test_read_back_runs_on_a_fresh_page_only_for_unfailed_fields(make, cfg):
    seen = []

    def read_details(self, page, fields):
        seen.append(fields)
        self.observed.update({"title": "New title"})

    def captions_fail(self, page, fields):
        self._at("upload captions")
        raise RuntimeError("no file chooser")

    ctx = FakeContext()
    ed = editor(cfg, make("title", "captions"), _edit_details=publish_ok, _edit_captions=captions_fail,
                _read_back_details=read_details, _read_back_captions=read_nothing)
    outcome = ed.run(ctx)
    assert seen == [["title"]] and ctx.opened == 2  # one page for captions, one for the read-back
    assert outcome.applied == {"title": "New title"}
    assert outcome.problems == ["captions not applied (upload captions: no file chooser)"]


def test_caption_language_mismatch_changes_nothing(make, cfg):
    calls = []

    def record(self, page, fields):
        calls.append(fields)
        self.touched = True

    ed = editor(cfg, make("title", "captions"), _open_languages=lambda self, page: "Video language: Hindi",
                _edit_details=record, _edit_captions=record)
    outcome = ed.run(FakeContext())
    assert calls == []
    assert outcome.status == "failed" and outcome.applied == {}
    assert [p.split(" ")[0] for p in outcome.problems] == ["title", "captions"]
    assert all("not applied (check the video's language: the video's language is Hindi, but the captions are "
               "English" in p for p in outcome.problems)


def test_languages_page_failure_still_edits_details(make, cfg):
    calls = []

    def languages_fail(self, page):
        self._at("open the video's Languages page")
        raise RuntimeError("Timeout 30000ms exceeded.")

    def details(self, page, fields):
        calls.append(fields)
        self.touched = True

    ed = editor(cfg, make("title", "captions"), _open_languages=languages_fail, _edit_details=details,
                _edit_captions=lambda self, page, fields: calls.append(fields),
                _read_back_details=lambda self, page, fields: self.observed.update({"title": "New title"}))
    outcome = ed.run(FakeContext())
    assert calls == [["title"]]
    assert outcome.status == "needs_attention" and outcome.applied == {"title": "New title"}
    assert outcome.problems == ["captions not applied (open the video's Languages page: Timeout 30000ms exceeded.)"]
