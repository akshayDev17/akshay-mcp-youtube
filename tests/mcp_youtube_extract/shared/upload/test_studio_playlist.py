"""Tests for the Studio playlist steps' sequencing and outcomes, with the page steps faked."""

from datetime import datetime

import pytest

from mcp_youtube_extract.shared.upload import studio_playlist as sp
from mcp_youtube_extract.shared.upload.playlist import VideoFacts, build_playlist_spec

A, B, C = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"


@pytest.fixture
def spec(cfg):
    spec, _ = build_playlist_spec({"name": "Course", "visibility": "unlisted", "video_ids": [C, A, B]}, cfg)
    return spec


class Steps:
    """Records what the create flow does, standing in for the browser."""

    def __init__(self, monkeypatch, spec, existing=(), fail_at=None, playlist_order=None):
        self.calls = []
        self.fail_at = fail_at
        self.current = None
        self.order = list(spec.video_ids) if playlist_order is None else playlist_order
        facts = [VideoFacts(v, title=f"T{v[0]}", visibility="private") for v in spec.video_ids]
        fake = {
            "read_videos": lambda page, s: (facts, list(existing)),
            "open_edit_page": self.opener,
            "read_edit_page": lambda page: ("t", "private", "Private"),
            "open_picker": lambda page: self.step("picker") or "picker",
            "click_new_playlist": lambda page, picker: self.step("new"),
            "creation_form": lambda page: "form",
            "fill_creation_form": lambda page, form, s: self.step("fill"),
            "click_create": lambda page, form: self.step("create"),
            "tick": lambda page, picker, name: self.step(f"tick {name}"),
            "close_picker": lambda picker: self.step("done"),
            "save_edit_page": lambda page: self.step("save"),
            "find_playlist": lambda page, s: (self.step("find") or ("PLcreated123", s.visibility)),
            "read_playlist_videos": lambda page, pid, n: self.order,
            "save_evidence": lambda page, d, step, now: [f"/evidence/{step}"],
        }
        for name, fn in fake.items():
            monkeypatch.setattr(sp, name, fn)

    def opener(self, page, video_id):
        self.current = video_id
        self.step(f"open {video_id}")

    def step(self, label):
        self.calls.append(label)
        if self.fail_at and label == self.fail_at:
            raise RuntimeError(f"boom at {label}\nsecond line")


def run(spec, cfg):
    return sp._create_steps(object(), spec, cfg, lambda: datetime(2026, 11, 2))


def test_creates_from_first_video_and_adds_the_rest_in_order(monkeypatch, spec, cfg):
    steps = Steps(monkeypatch, spec)
    outcome = run(spec, cfg)
    assert outcome.status == "done" and outcome.playlist_id == "PLcreated123" and outcome.problems == []
    opened = [c.split()[1] for c in steps.calls if c.startswith("open ")]
    assert opened == [C, A, B]
    assert steps.calls.count("create") == 1
    assert steps.calls.index("create") < steps.calls.index(f"open {A}")
    assert steps.calls.count("tick Course") == 3 and steps.calls.count("save") == 3
    assert outcome.applied["visibility"] == "unlisted"
    assert outcome.applied["videos added, in order"] == f"1. {C} Tc; 2. {A} Ta; 3. {B} Tb"


def test_preview_problems_stop_before_anything_is_created(monkeypatch, spec, cfg):
    steps = Steps(monkeypatch, spec, existing=["Course"])
    outcome = run(spec, cfg)
    assert outcome.status == "failed" and "already has a playlist named 'Course'" in outcome.problems[0]
    assert steps.calls == []


def test_failure_before_create_is_failed(monkeypatch, spec, cfg):
    Steps(monkeypatch, spec, fail_at="fill")
    outcome = run(spec, cfg)
    assert outcome.status == "failed" and outcome.problems == ["fill new playlist form: boom at fill"]
    assert outcome.evidence == ["/evidence/playlist fill new playlist form"]


def test_failure_on_create_click_may_have_created(monkeypatch, spec, cfg):
    Steps(monkeypatch, spec, fail_at="create")
    outcome = run(spec, cfg)
    assert outcome.status == "needs_attention"
    assert any("may exist on the channel" in p for p in outcome.problems)


def test_failure_mid_way_stops_and_lists_what_was_not_added(monkeypatch, spec, cfg):
    steps = Steps(monkeypatch, spec, fail_at=f"open {B}")
    outcome = run(spec, cfg)
    assert outcome.status == "needs_attention"
    assert outcome.problems == [f"open video 3 ({B}): boom at open {B}", f"not added: {B}"]
    assert outcome.applied["videos added, in order"] == f"1. {C} Tc; 2. {A} Ta"
    assert "find" not in steps.calls


def test_readback_mismatch_is_needs_attention(monkeypatch, spec, cfg):
    Steps(monkeypatch, spec, playlist_order=[A, C, B])
    outcome = run(spec, cfg)
    assert outcome.status == "needs_attention" and outcome.playlist_id == "PLcreated123"
    assert outcome.problems == [f"video order is {A}, {C}, {B}, expected {C}, {A}, {B}"]


def test_unreadable_video_says_why_without_claiming_it_is_not_the_channels(monkeypatch):
    def slow(page):
        raise TimeoutError("Timeout 30000ms exceeded.\nCall log: ...")

    monkeypatch.setattr(sp, "open_edit_page", lambda page, video_id: None)
    monkeypatch.setattr(sp, "read_edit_page", slow)
    facts = sp.read_video_facts(object(), A)
    assert facts.title is None and "could not be read from Studio" in facts.problem
    assert facts.problem.endswith("(Timeout 30000ms exceeded.)")


class FakePicker:
    """Playlist names the picker shows on each read, before and after the search is typed."""

    def __init__(self, before_search, after_search):
        self.reads = {False: list(before_search), True: list(after_search)}
        self.searched = None

    def evaluate(self, js, *args):
        reads = self.reads[self.searched is not None]
        return reads.pop(0) if len(reads) > 1 else reads[0]

    def locator(self, selector):
        picker = self

        class SearchBox:
            def fill(self, value):
                picker.searched = value

        return SearchBox()


class FakePage:
    def wait_for_timeout(self, ms):
        pass


def test_search_waits_for_rows_then_for_a_settled_matching_result():
    picker = FakePicker(
        before_search=[[], [], ["Other", "Course", "Course 2"]],
        after_search=[[], ["Other", "Course"], ["Other", "Course"], ["Course", "course  2"]],
    )
    assert sp.search_picker(FakePage(), picker, "Course") == ["Course", "course  2"]
    assert picker.searched == "Course" and picker.reads[False] == [["Other", "Course", "Course 2"]]


def test_search_on_a_channel_with_no_playlists_settles_empty():
    assert sp.search_picker(FakePage(), FakePicker([[]], [[]]), "Course") == []


def test_search_that_never_filters_fails_the_step():
    with pytest.raises(sp.StepFailed, match="did not settle"):
        sp.search_picker(FakePage(), FakePicker([["Other"]], [["Other"]]), "Course")
