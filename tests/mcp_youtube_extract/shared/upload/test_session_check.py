"""Unit tests for per-channel profiles and classifying where Studio landed."""

import os
import stat

import pytest

from mcp_youtube_extract.shared.upload.session import (
    classify_landing,
    ensure_profile_dir,
    persistent_context_args,
    profile_in_use,
)

from .conftest import MAIN


@pytest.mark.parametrize("url, kind, cid", [
    (f"https://studio.youtube.com/channel/{MAIN}/videos/upload?d=ud", "ok", MAIN),
    ("https://studio.youtube.com/channel/UCbbbbbbbbbbbbbbbbbbbbbb/content", "wrong_channel", "UCbbbbbbbbbbbbbbbbbbbbbb"),
    ("https://accounts.google.com/v3/signin/identifier?continue=x", "not_logged_in", None),
    ("https://www.youtube.com/", "unknown", None),
])
def test_classify_landing(url, kind, cid):
    c = classify_landing(url, MAIN)
    assert (c.kind, c.channel_id) == (kind, cid)


def test_profile_dir_is_private(cfg):
    path = ensure_profile_dir(cfg.resolve_channel("main"))
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    path.chmod(0o755)
    assert stat.S_IMODE(ensure_profile_dir(cfg.resolve_channel("main")).stat().st_mode) == 0o700


def test_profile_in_use_detects_dangling_singleton_lock(tmp_path):
    os.symlink("host-123", tmp_path / "SingletonLock")
    assert profile_in_use(tmp_path) and not profile_in_use(tmp_path / "missing")


def test_launch_args(cfg):
    ch = cfg.resolve_channel("main")
    a = persistent_context_args(ch, cfg, headless=True)
    assert a["user_data_dir"] == str(ch.profile_dir) and a["executable_path"] == str(cfg.browser_path)
    assert a["ignore_default_args"] == ["--use-mock-keychain"] and a["headless"] is True
    assert a["viewport"] == {"width": 1440, "height": 900}
    assert persistent_context_args(ch, cfg, headless=False)["viewport"] is None
