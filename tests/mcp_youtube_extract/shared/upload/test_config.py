"""Unit tests for upload channel and settings configuration."""

from pathlib import Path

import pytest

from mcp_youtube_extract.shared.upload.config import ConfigError, load_config

MAIN = "UCDzx6hNPpuha4fCwYA5WAyg"
SECOND = "UC" + "a" * 22


def test_parses_channels_default_and_profiles(tmp_path):
    cfg = load_config({"YT_UPLOAD_CHANNELS": f" main={MAIN}, second={SECOND}, "}, home=tmp_path)
    assert list(cfg.channels) == ["main", "second"]
    assert cfg.default_channel == "main"
    assert cfg.channels["second"].profile_dir == tmp_path / "profiles" / "second"
    assert cfg.jobs_dir == tmp_path / "jobs" and cfg.failures_dir == tmp_path / "failures"


def test_settings_defaults(tmp_path):
    cfg = load_config({"YT_UPLOAD_CHANNELS": f"main={MAIN}"}, home=tmp_path)
    assert cfg.browser_path == Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")
    assert (cfg.headless, cfg.login_timeout_s, cfg.call_wait_s) == (True, 600, 600)


def test_settings_overrides(tmp_path):
    cfg = load_config(
        {
            "YT_UPLOAD_CHANNELS": f"main={MAIN},second={SECOND}",
            "YT_UPLOAD_DEFAULT_CHANNEL": "second",
            "YT_UPLOAD_HEADLESS": "false",
            "YT_UPLOAD_LOGIN_TIMEOUT": "30",
            "YT_UPLOAD_CALL_WAIT": "5",
        },
        home=tmp_path,
    )
    assert (cfg.default_channel, cfg.headless, cfg.login_timeout_s, cfg.call_wait_s) == ("second", False, 30, 5)


def test_resolve_by_none_name_and_id(tmp_path):
    cfg = load_config({"YT_UPLOAD_CHANNELS": f"main={MAIN},second={SECOND}"}, home=tmp_path)
    assert cfg.resolve_channel(None).name == "main"
    assert cfg.resolve_channel("second").channel_id == SECOND
    assert cfg.resolve_channel(SECOND).name == "second"


@pytest.mark.parametrize(
    "env, needle",
    [
        ({}, "YT_UPLOAD_CHANNELS"),
        ({"YT_UPLOAD_CHANNELS": "main"}, "main"),
        ({"YT_UPLOAD_CHANNELS": "main=notachannel"}, "notachannel"),
        ({"YT_UPLOAD_CHANNELS": f"main={MAIN},main={SECOND}"}, "main"),
        ({"YT_UPLOAD_CHANNELS": f"main={MAIN}", "YT_UPLOAD_DEFAULT_CHANNEL": "other"}, "other"),
        ({"YT_UPLOAD_CHANNELS": f"main={MAIN}", "YT_UPLOAD_LOGIN_TIMEOUT": "soon"}, "YT_UPLOAD_LOGIN_TIMEOUT"),
    ],
)
def test_bad_config_raises_with_the_culprit_named(tmp_path, env, needle):
    with pytest.raises(ConfigError, match=needle):
        load_config(env, home=tmp_path)


def test_unknown_channel(tmp_path):
    cfg = load_config({"YT_UPLOAD_CHANNELS": f"main={MAIN}"}, home=tmp_path)
    with pytest.raises(ConfigError, match="nope"):
        cfg.resolve_channel("nope")
