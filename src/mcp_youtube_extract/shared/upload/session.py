"""Per-channel browser profiles and their YouTube Studio session.

Each configured channel has its own Brave profile. The login lives there and its
cookies never leave it. Automated launches go through Playwright; the sign-in window
does not, because Google refuses sign-in inside automated browsers.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..logger import get_logger
from .config import Channel, UploadConfig

logger = get_logger(__name__)

STUDIO_UPLOAD_URL = "https://youtube.com/upload"

_STUDIO_CHANNEL = re.compile(r"^https://studio\.youtube\.com/channel/(UC[A-Za-z0-9_-]{22})")
_SETTLE_MS = 30_000

SessionKind = Literal["ok", "not_logged_in", "wrong_channel", "in_use", "unknown"]


@dataclass
class SessionCheck:
    kind: SessionKind
    channel_id: str | None
    url: str


def classify_landing(url: str, expected_channel_id: str) -> SessionCheck:
    match = _STUDIO_CHANNEL.match(url)
    if match:
        found = match.group(1)
        return SessionCheck("ok" if found == expected_channel_id else "wrong_channel", found, url)
    if url.startswith("https://accounts.google.com/"):
        return SessionCheck("not_logged_in", None, url)
    return SessionCheck("unknown", None, url)


def ensure_profile_dir(channel: Channel) -> Path:
    channel.profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    channel.profile_dir.chmod(0o700)
    return channel.profile_dir


def profile_in_use(profile_dir: Path) -> bool:
    """Chromium keeps a SingletonLock symlink in the profile while a browser has it open."""
    return os.path.lexists(Path(profile_dir) / "SingletonLock")


def persistent_context_args(channel: Channel, config: UploadConfig, headless: bool) -> dict:
    return {
        "user_data_dir": str(channel.profile_dir),
        "executable_path": str(config.browser_path),
        "headless": headless,
        # The profile's cookies are encrypted with the browser's real Keychain key;
        # Playwright's mock keychain would make the login unreadable.
        "ignore_default_args": ["--use-mock-keychain"],
        "viewport": {"width": 1440, "height": 900} if headless else None,
    }


def skip_unsupported_notice(page) -> bool:
    """Studio shows an 'unsupported browser' notice to headless Chromium, with its own
    'Skip to YouTube Studio' button. Click it if it appears."""
    skip = page.get_by_text("Skip to YouTube Studio", exact=False).first
    try:
        skip.wait_for(state="visible", timeout=10_000)
    except Exception:
        return False
    skip.click()
    return True


def check_session(channel: Channel, config: UploadConfig) -> SessionCheck:
    """Open the channel's profile headless and see where Studio's upload page lands."""
    if profile_in_use(channel.profile_dir):
        return SessionCheck("in_use", None, "")
    ensure_profile_dir(channel)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(**persistent_context_args(channel, config, headless=True))
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(STUDIO_UPLOAD_URL)
            try:
                page.wait_for_url(
                    re.compile(r"^https://(studio\.youtube\.com/channel/|accounts\.google\.com/)"),
                    timeout=_SETTLE_MS,
                )
            except Exception:
                pass
            skip_unsupported_notice(page)
            result = classify_landing(page.url, channel.channel_id)
            logger.info(f"session check for {channel.name}: {result.kind} ({result.url})")
            return result
        finally:
            context.close()
