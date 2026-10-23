"""Upload configuration: channels and settings, read from YT_UPLOAD_* environment variables.

Loaded at tool-call time rather than import, so a malformed variable surfaces as a
readable error from the tool instead of breaking the whole server.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_BROWSER = Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")
DEFAULT_HOME = Path.home() / ".mcp-youtube-extract"

_CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_TRUE = {"true", "1", "yes"}
_FALSE = {"false", "0", "no"}


class ConfigError(ValueError):
    """A YT_UPLOAD_* setting is missing or malformed, or a channel is unknown."""


@dataclass(frozen=True)
class Channel:
    name: str
    channel_id: str
    profile_dir: Path


@dataclass(frozen=True)
class UploadConfig:
    channels: dict[str, Channel]
    default_channel: str
    browser_path: Path
    headless: bool
    login_timeout_s: int
    call_wait_s: int
    home: Path

    @property
    def jobs_dir(self) -> Path:
        return self.home / "jobs"

    @property
    def failures_dir(self) -> Path:
        return self.home / "failures"

    def resolve_channel(self, name_or_id: str | None) -> Channel:
        """Channel by configured name, then by channel id; None means the default."""
        if name_or_id is None:
            return self.channels[self.default_channel]
        if name_or_id in self.channels:
            return self.channels[name_or_id]
        for channel in self.channels.values():
            if channel.channel_id == name_or_id:
                return channel
        known = ", ".join(self.channels)
        raise ConfigError(f"unknown channel '{name_or_id}'; configured channels: {known}")


def _parse_channels(raw: str, home: Path) -> dict[str, Channel]:
    channels: dict[str, Channel] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        name, sep, channel_id = (part.strip() for part in pair.partition("="))
        if not sep or not name or not channel_id:
            raise ConfigError(f"YT_UPLOAD_CHANNELS entry '{pair}' must look like name=UC…")
        if not _CHANNEL_ID.match(channel_id):
            raise ConfigError(
                f"YT_UPLOAD_CHANNELS: '{channel_id}' is not a channel id (UC followed by 22 characters)"
            )
        if name in channels:
            raise ConfigError(f"YT_UPLOAD_CHANNELS lists the name '{name}' twice")
        channels[name] = Channel(name, channel_id, home / "profiles" / name)
    if not channels:
        raise ConfigError("YT_UPLOAD_CHANNELS is not set; set it to name=channel_id pairs, e.g. main=UC…")
    return channels


def _parse_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigError(f"{key} must be true or false, not '{raw}'")


def _parse_seconds(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ConfigError(f"{key} must be a whole number of seconds, not '{raw}'") from None
    if value < 0:
        raise ConfigError(f"{key} must not be negative")
    return value


def load_config(env: Mapping[str, str] | None = None, home: Path | None = None) -> UploadConfig:
    env = os.environ if env is None else env
    home = DEFAULT_HOME if home is None else home
    channels = _parse_channels(env.get("YT_UPLOAD_CHANNELS", ""), home)
    default = env.get("YT_UPLOAD_DEFAULT_CHANNEL", "").strip() or next(iter(channels))
    if default not in channels:
        raise ConfigError(f"YT_UPLOAD_DEFAULT_CHANNEL '{default}' is not one of: {', '.join(channels)}")
    return UploadConfig(
        channels=channels,
        default_channel=default,
        browser_path=Path(env.get("YT_UPLOAD_BROWSER", "").strip() or DEFAULT_BROWSER),
        headless=_parse_bool(env, "YT_UPLOAD_HEADLESS", True),
        login_timeout_s=_parse_seconds(env, "YT_UPLOAD_LOGIN_TIMEOUT", 600),
        call_wait_s=_parse_seconds(env, "YT_UPLOAD_CALL_WAIT", 600),
        home=home,
    )
