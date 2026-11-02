"""Tests for playlist request validation, preview and read-back comparison (no Studio)."""

import pytest

from mcp_youtube_extract.shared.upload.playlist import (
    PlaylistOutcome,
    VideoFacts,
    build_playlist_spec,
    compare_playlist_readback,
    format_outcome,
    format_preview,
    preview_problems,
    unread_names_problem,
)

from .conftest import SECOND

A, B, C = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"


def build(cfg, **overrides):
    params = {"name": "My list", "visibility": "private", "video_ids": [A, B, C]}
    params.update(overrides)
    return build_playlist_spec(params, cfg)


def test_valid_request_keeps_the_asked_order(cfg):
    spec, problems = build(cfg, video_ids=[C, A, B])
    assert problems == [] and spec.video_ids == (C, A, B)
    assert spec.name == "My list" and spec.visibility == "private" and spec.channel.name == "main"


@pytest.mark.parametrize("visibility", ["public", "unlisted", "private", " Unlisted "])
def test_every_studio_visibility_is_accepted(cfg, visibility):
    spec, _ = build(cfg, visibility=visibility)
    assert spec.visibility == visibility.strip().lower()


@pytest.mark.parametrize("visibility", [None, "", "  "])
def test_visibility_has_no_default(cfg, visibility):
    spec, problems = build(cfg, visibility=visibility)
    assert spec is None and any("visibility is required" in p and "ask the user" in p for p in problems)


def test_unknown_visibility_is_refused(cfg):
    spec, problems = build(cfg, visibility="scheduled")
    assert spec is None and "must be one of: public, unlisted, private" in problems[0]


@pytest.mark.parametrize("name", [None, "", "   "])
def test_name_is_required(cfg, name):
    spec, problems = build(cfg, name=name)
    assert spec is None and any("name is required" in p for p in problems)


def test_name_is_stripped_and_limited(cfg):
    spec, _ = build(cfg, name="  Trimmed  ")
    assert spec.name == "Trimmed"
    spec, problems = build(cfg, name="x" * 151)
    assert spec is None and "at most 150" in problems[0]
    assert build(cfg, name="x" * 150)[0] is not None


def test_angle_brackets_are_refused(cfg):
    spec, problems = build(cfg, name="a <b> c")
    assert spec is None and "'<' or '>'" in problems[0]


@pytest.mark.parametrize("ids", [None, []])
def test_videos_are_required(cfg, ids):
    spec, problems = build(cfg, video_ids=ids)
    assert spec is None and any("ask the user which videos" in p for p in problems)


@pytest.mark.parametrize(
    "value", ["short", f"https://youtu.be/{A}", f"https://www.youtube.com/watch?v={A}", f" {A}", f"{A}\n", "", None, A + "x"]
)
def test_only_bare_ids_are_accepted(cfg, value):
    spec, problems = build(cfg, video_ids=[value])
    assert spec is None and problems == [f"video 1: '{value}' is not an 11-character YouTube video id"]


def test_bad_ids_are_reported_by_position(cfg):
    spec, problems = build(cfg, video_ids=[A, "nope", B])
    assert spec is None and problems == ["video 2: 'nope' is not an 11-character YouTube video id"]


def test_duplicates_are_refused(cfg):
    spec, problems = build(cfg, video_ids=[A, B, A])
    assert spec is None and "already at position 1" in problems[0]


def test_channel_by_name_or_id_and_unknown(cfg):
    assert build(cfg, channel="second")[0].channel.channel_id == SECOND
    assert build(cfg, channel=SECOND)[0].channel.name == "second"
    spec, problems = build(cfg, channel="nope")
    assert spec is None and "unknown channel 'nope'" in problems[0]


def test_all_problems_reported_together(cfg):
    spec, problems = build_playlist_spec({}, cfg)
    assert spec is None and len(problems) == 3


# -- preview --------------------------------------------------------------------


def facts_for(*ids):
    return [VideoFacts(v, title=f"Title {v[0]}", visibility=vis) for v, vis in zip(ids, ["public", "unlisted", "private"])]


def test_preview_lists_videos_in_order_with_visibility(cfg):
    spec, _ = build(cfg, video_ids=[C, A, B])
    facts = facts_for(C, A, B)
    text = format_preview(spec, facts, preview_problems(spec, facts, ["Other list"]))
    lines = text.splitlines()
    assert "nothing created" in lines[0]
    assert lines.index(f"  1. {C} [public] Title c") < lines.index(f"  2. {A} [unlisted] Title a")
    assert f"  3. {B} [private] Title b" in lines
    assert "Visibility: private" in text and "preview=false" in text and "Cannot create" not in text


def test_preview_problems_for_unreadable_video_and_taken_name(cfg):
    spec, _ = build(cfg)
    facts = [VideoFacts(A, "T", "public"), VideoFacts(B, problem="not this channel's"), VideoFacts(C, "T", "private")]
    problems = preview_problems(spec, facts, ["My list"])
    assert problems[0] == f"video 2 ({B}): not this channel's"
    assert "already has a playlist named 'My list'" in problems[1]
    text = format_preview(spec, facts, problems)
    assert "Cannot create as asked" in text and f"2. {B} — cannot add" in text and "preview=false" not in text


# -- read-back ------------------------------------------------------------------


def observed(spec, **overrides):
    seen = {"name": spec.name, "visibility": spec.visibility, "video_ids": list(spec.video_ids)}
    seen.update(overrides)
    return seen


def test_readback_matches(cfg):
    spec, _ = build(cfg)
    assert compare_playlist_readback(spec, observed(spec)) == []


def test_readback_reports_order(cfg):
    spec, _ = build(cfg)
    assert compare_playlist_readback(spec, observed(spec, video_ids=[B, A, C])) == [
        f"video order is {B}, {A}, {C}, expected {A}, {B}, {C}"
    ]


def test_readback_reports_missing_extra_visibility(cfg):
    spec, _ = build(cfg)
    lines = compare_playlist_readback(spec, observed(spec, visibility="public", video_ids=[A, "zzzzzzzzzzz"]))
    assert lines == [
        "visibility is public, expected private",
        f"missing from the playlist: {B}, {C}",
        "in the playlist but not asked for: zzzzzzzzzzz",
    ]


def test_outcome_text(cfg):
    spec, _ = build(cfg)
    done = format_outcome(spec, PlaylistOutcome("done", playlist_id="PLabcdefghij", applied={"name": "My list"}))
    assert "Playlist created (status: done)" in done and "list=PLabcdefghij" in done and "name: My list" in done
    attention = format_outcome(
        spec, PlaylistOutcome("needs_attention", created=True, problems=["x"], evidence=["/tmp/e.png"])
    )
    assert attention.startswith("Playlist created, but needs attention")
    assert "needs attention" in attention and "- x" in attention and "rather than creating it again" in attention
    failed = format_outcome(spec, PlaylistOutcome("failed", problems=["y"]))
    assert failed.startswith("Playlist not created (status: failed)")


def test_unreadable_names_problem_says_why_and_that_nothing_was_created(cfg):
    spec, _ = build(cfg)
    problem = unread_names_problem("My list", "Timeout 30000ms exceeded.", ["/tmp/e.png"])
    assert "for 'My list' (Timeout 30000ms exceeded.)" in problem and "nothing was created" in problem
    assert problem.endswith("(evidence: /tmp/e.png)")
    not_created = format_outcome(spec, PlaylistOutcome("needs_attention", problems=[problem]))
    assert not_created.startswith("Playlist not created; needs attention")
    assert "rather than creating it again" not in not_created
