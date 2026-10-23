"""Unit tests for resolving an upload spec from params, defaults and a video folder."""

from datetime import datetime, timezone

import pytest

from mcp_youtube_extract.shared.upload.spec import resolve_spec

from .conftest import make_folder


def test_folder_convention(tmp_path, cfg):
    d = make_folder(tmp_path, files={
        "talk.mp4": b"x",
        "title.txt": "﻿The Title  \nignored\n",
        "description.md": "line one\r\nline two\r\n",
        "captions.srt": "1\n",
        "thumbnail.png": b"png",
    })
    r = resolve_spec({"folder": str(d)}, None, cfg)
    assert r.problems == []
    s = r.spec
    assert s.video_path == d / "talk.mp4" and s.title == "The Title"
    assert s.description == "line one\nline two\n"
    assert s.captions_path == d / "captions.srt" and s.thumbnail_path == d / "thumbnail.png"
    assert (s.channel.name, s.visibility, s.language, s.audio_language, s.captions_language, s.made_for_kids) == \
           ("main", "public", "en", "en", "en", False)


def test_explicit_params_override_folder_and_defaults_fill_gaps(tmp_path, cfg):
    d = make_folder(tmp_path, files={"v.mp4": b"x", "title.txt": "Folder title"})
    r = resolve_spec(
        {"folder": str(d), "title": "Mine", "language": "hi"},
        {"language": "en", "channel": "second", "made_for_kids": True},
        cfg,
    )
    s = r.spec
    assert (s.title, s.language, s.audio_language, s.channel.name, s.made_for_kids) == ("Mine", "hi", "hi", "second", True)


def test_publish_at_suppresses_default_visibility(tmp_path, cfg):
    d = make_folder(tmp_path, files={"v.mp4": b"x", "title.txt": "T"})
    r = resolve_spec({"folder": str(d), "publish_at": "2030-01-02T18:00:00+05:30"}, {"visibility": "public"}, cfg)
    assert r.spec.visibility is None
    assert r.spec.publish_at == datetime(2030, 1, 2, 12, 30, tzinfo=timezone.utc)


def test_explicit_visibility_kept_alongside_publish_at_for_validation(tmp_path, cfg):
    d = make_folder(tmp_path, files={"v.mp4": b"x", "title.txt": "T"})
    r = resolve_spec({"folder": str(d), "publish_at": "2030-01-02T18:00:00+05:30", "visibility": "unlisted"}, None, cfg)
    assert r.spec.visibility == "unlisted"


def test_svg_thumbnail_ignored_with_warning(tmp_path, cfg):
    d = make_folder(tmp_path, files={"v.mp4": b"x", "title.txt": "T", "thumbnail.svg": "<svg/>"})
    r = resolve_spec({"folder": str(d)}, None, cfg)
    assert r.spec.thumbnail_path is None and any("thumbnail.svg" in w for w in r.warnings)


def _folder_for(kind, tmp_path):
    if kind == "<two-mp4>":
        return str(make_folder(tmp_path, name="two", files={"a.mp4": b"x", "b.mp4": b"x", "title.txt": "T"}))
    if kind == "<no-mp4>":
        return str(make_folder(tmp_path, name="none", files={"title.txt": "T"}))
    if kind == "<ok>":
        return str(make_folder(tmp_path, name="ok", files={"v.mp4": b"x", "title.txt": "T"}))
    return kind


@pytest.mark.parametrize("params, needle", [
    ({}, "folder or video_path"),
    ({"video_path": "/abs/v.mp4"}, "title"),
    ({"folder": "relative/dir"}, "absolute path"),
    ({"folder": "<two-mp4>"}, "a.mp4"),
    ({"folder": "<no-mp4>"}, ".mp4"),
    ({"folder": "<ok>", "titel": "x"}, "unknown field 'titel'"),
    ({"folder": "<ok>", "publish_at": "2030-01-02T18:00:00"}, "UTC offset"),
    ({"folder": "<ok>", "publish_at": "next tuesday"}, "publish_at"),
    ({"folder": "<ok>", "visibility": "secret"}, "visibility"),
    ({"folder": "<ok>", "made_for_kids": "no"}, "made_for_kids"),
    ({"folder": "<ok>", "channel": "nope"}, "nope"),
])
def test_resolution_problems(tmp_path, cfg, params, needle):
    if "folder" in params:
        params = {**params, "folder": _folder_for(params["folder"], tmp_path)}
    r = resolve_spec(params, None, cfg)
    assert r.spec is None and any(needle in p for p in r.problems), r.problems


def test_tilde_is_expanded(tmp_path, cfg, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    make_folder(tmp_path, name="vid", files={"v.mp4": b"x", "title.txt": "T"})
    assert resolve_spec({"folder": "~/vid"}, None, cfg).spec.video_path == tmp_path / "vid" / "v.mp4"
