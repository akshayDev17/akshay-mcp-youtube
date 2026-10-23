"""Per-channel browser profiles and their YouTube Studio session.

Each configured channel has its own Brave profile. The login lives there and its
cookies never leave it. Automated launches go through Playwright; the sign-in window
does not, because Google refuses sign-in inside automated browsers.
"""

import os
import re
import sqlite3
import subprocess
import time
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


# -- sign-in ------------------------------------------------------------------

LOGIN_URL = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2Fupload"

_POLL_S = 2
_FLUSH_S = 5
_CHROMIUM_EPOCH_OFFSET_S = 11644473600  # 1601-01-01 to 1970-01-01
_COOKIE_DB_PATHS = (Path("Default") / "Network" / "Cookies", Path("Default") / "Cookies")


def login_command(channel: Channel, config: UploadConfig) -> list[str]:
    return [
        str(config.browser_path),
        f"--user-data-dir={channel.profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        LOGIN_URL,
    ]


def login_cookies_present(profile_dir: Path, since: float) -> bool:
    """True once YouTube's login cookies were written after `since` (unix seconds).

    Reads names and timestamps only, read-only, ignoring the browser's locks; cookie
    values are never selected.
    """
    threshold = int((since + _CHROMIUM_EPOCH_OFFSET_S) * 1_000_000)
    for relative in _COOKIE_DB_PATHS:
        db = Path(profile_dir) / relative
        if not db.is_file():
            continue
        try:
            con = sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True)
            try:
                columns = {row[1] for row in con.execute("PRAGMA table_info(cookies)")}
                times = [c for c in ("creation_utc", "last_update_utc") if c in columns]
                if not times:
                    return False
                newest = f"max({', '.join(f'coalesce({c}, 0)' for c in times)})" if len(times) > 1 else times[0]
                rows = con.execute(
                    f"SELECT host_key, name, {newest} FROM cookies WHERE name IN ('LOGIN_INFO', 'SAPISID')"
                ).fetchall()
            finally:
                con.close()
        except sqlite3.Error:
            return False
        fresh = {name for host, name, t in rows if host.endswith("youtube.com") and (t or 0) > threshold}
        return {"LOGIN_INFO", "SAPISID"} <= fresh
    return False


def _minutes(seconds: int) -> str:
    minutes = max(1, round(seconds / 60))
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"


def _close(proc) -> None:
    proc.terminate()
    try:
        proc.wait(10)
    except Exception:
        proc.kill()


def run_login_flow(
    channel: Channel,
    config: UploadConfig,
    on_state,
    *,
    launch=subprocess.Popen,
    cookies_present=login_cookies_present,
    check=None,
    clock=time.monotonic,
    sleep=time.sleep,
    in_use=profile_in_use,
) -> str | None:
    """Open a plain (not automated) Brave window for the person to sign in, notice when
    they have, close the window, and confirm the channel. None on success, else why not."""
    check = check or check_session
    deadline = clock() + config.login_timeout_s
    ensure_profile_dir(channel)
    message = f"A Brave window has opened to sign in to the YouTube channel '{channel.name}' ({channel.channel_id})."

    while True:
        since = time.time()
        proc = launch(login_command(channel, config))
        on_state("waiting_for_sign_in", message)
        signed_in = False
        while clock() < deadline:
            if cookies_present(channel.profile_dir, since):
                signed_in = True
                break
            if proc.poll() is not None:
                return "sign-in cancelled: the sign-in window was closed"
            sleep(_POLL_S)
        if not signed_in:
            _close(proc)
            return f"sign-in not completed within {_minutes(config.login_timeout_s)}"

        sleep(_FLUSH_S)  # let the browser finish writing the session
        _close(proc)
        while in_use(channel.profile_dir) and clock() < deadline:
            sleep(_POLL_S)

        result = check(channel, config)
        if result.kind == "ok":
            return None
        if clock() >= deadline:
            return f"sign-in not completed within {_minutes(config.login_timeout_s)}"
        if result.kind == "wrong_channel":
            message = (
                f"A Brave window has opened to sign in to the YouTube channel '{channel.name}'. "
                f"It is signed in to {result.channel_id}; switch to {channel.channel_id}."
            )
        logger.info(f"sign-in for {channel.name} landed on {result.kind}; reopening the window")


def ensure_session(channel: Channel, config: UploadConfig, on_state, **injected) -> str | None:
    """None when the channel's profile reaches its own Studio; runs the sign-in flow if not."""
    check = injected.get("check") or check_session
    clock = injected.get("clock", time.monotonic)
    sleep = injected.get("sleep", time.sleep)
    deadline = clock() + config.login_timeout_s
    result = check(channel, config)
    while result.kind == "in_use":
        if clock() >= deadline:
            return f"the profile for '{channel.name}' is in use by another window"
        sleep(_POLL_S)
        result = check(channel, config)
    if result.kind == "ok":
        return None
    return run_login_flow(channel, config, on_state, **injected)
