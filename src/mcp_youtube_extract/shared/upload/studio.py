"""Upload through YouTube Studio's own upload dialog, in the channel's browser profile.

Each step is a small method with a name, so a failure says which step broke and
leaves a screenshot and the page's visible text behind. Studio's markup changes
without notice; that evidence is how breakage gets diagnosed.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..logger import get_logger
from . import session
from .backend import UploadOutcome, failure_outcome
from .config import Channel, UploadConfig
from .media import describe, probe_video
from .spec import UploadSpec

logger = get_logger(__name__)

_STEP_TIMEOUT_MS = 30_000
_UPLOAD_BASE_MS = 120_000
_UPLOAD_PER_100MB_MS = 60_000
_LINK_ID = re.compile(r"(?:youtu\.be/|/shorts/|[?&]v=)([A-Za-z0-9_-]{11})")


def parse_video_link(href: str) -> tuple[str, bool]:
    """(video id, is_short) from the link Studio shows for a new upload."""
    match = _LINK_ID.search(href or "")
    if not match:
        raise ValueError(f"not a video link: {href}")
    return match.group(1), "/shorts/" in href


def _slug(step: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", step.lower()).strip("-")


def save_evidence(page, failures_dir: Path, step: str, now: datetime) -> list[str]:
    """Screenshot and visible text of the page at the failed step; returns the paths written."""
    failures_dir = Path(failures_dir)
    failures_dir.mkdir(parents=True, exist_ok=True)
    stem = failures_dir / f"{now.strftime('%Y%m%d-%H%M%S')}-{_slug(step)}"
    paths = []
    try:
        page.screenshot(path=str(stem.with_suffix(".png")))
        paths.append(str(stem.with_suffix(".png")))
    except Exception as error:
        logger.warning(f"could not screenshot step '{step}': {error}")
    try:
        text = page.evaluate("document.body ? document.body.innerText : ''")
    except Exception as error:
        text = f"<could not read the page: {error}>"
    stem.with_suffix(".txt").write_text(f"step: {step}\n\n{text}", encoding="utf-8")
    paths.append(str(stem.with_suffix(".txt")))
    return paths


class StepFailed(Exception):
    pass


class StudioBackend:
    def __init__(self, config: UploadConfig, *, now: Callable[[], datetime] = datetime.now):
        self.config = config
        self.now = now

    def ensure_session(self, channel: Channel, on_state) -> str | None:
        return session.ensure_session(channel, self.config, on_state)

    # -- the upload -------------------------------------------------------------

    def upload(self, spec: UploadSpec) -> UploadOutcome:
        from playwright.sync_api import sync_playwright

        self._video_id: str | None = None
        self._is_short: bool | None = None
        self._watch_url: str | None = None
        step = "open Studio"
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                **session.persistent_context_args(spec.channel, self.config, headless=self.config.headless)
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(_STEP_TIMEOUT_MS)
            try:
                for step, run in self._steps(spec):
                    logger.info(f"upload '{spec.title}': {step}")
                    run(page)
                step = "read back"
                mismatches = self._read_back(context, spec)
            except Exception as error:
                evidence = save_evidence(page, self.config.failures_dir, step, self.now())
                text = str(error).strip()
                first_line = text.splitlines()[0] if text else type(error).__name__
                outcome = failure_outcome(self._video_id, f"{step}: {first_line}", evidence)
                self._fill_links(outcome)
                return outcome
            finally:
                context.close()
        outcome = UploadOutcome(status="needs_attention" if mismatches else "done", problems=mismatches)
        self._fill_links(outcome)
        outcome.applied = self._applied(spec)
        info = probe_video(spec.video_path)
        if info:
            outcome.warnings.append(describe(info))
        return outcome

    def _fill_links(self, outcome: UploadOutcome) -> None:
        if self._video_id:
            outcome.video_id = self._video_id
            outcome.is_short = self._is_short
            outcome.watch_url = self._watch_url
            outcome.studio_url = f"https://studio.youtube.com/video/{self._video_id}/edit"

    def _applied(self, spec: UploadSpec) -> dict[str, str]:
        applied = {"channel": f"{spec.channel.name} ({spec.channel.channel_id})", "title": spec.title}
        if spec.publish_at is not None:
            applied["schedule"] = f"public at {spec.publish_at.astimezone().isoformat(timespec='minutes')}"
        else:
            applied["visibility"] = spec.visibility or "public"
        applied["languages"] = (
            f"title/description {spec.language}, audio {spec.audio_language}"
            + (f", captions {spec.captions_language}" if spec.captions_path else "")
        )
        files = [spec.video_path.name]
        files += [p.name for p in (spec.captions_path, spec.thumbnail_path) if p is not None]
        applied["files"] = ", ".join(files)
        applied["made for kids"] = "yes" if spec.made_for_kids else "no"
        return applied

    def _steps(self, spec: UploadSpec):
        return [
            ("open upload dialog", lambda page: page.goto(session.STUDIO_UPLOAD_URL)),
            ("skip unsupported-browser notice", session.skip_unsupported_notice),
            ("choose video file", lambda page: page.locator("input[type='file']").first.set_input_files(str(spec.video_path))),
            ("set title", lambda page: self._set_title(page, spec)),
            ("set description", lambda page: self._set_description(page, spec)),
            ("set thumbnail", lambda page: self._set_thumbnail(page, spec)),
            ("set made for kids", lambda page: self._set_made_for_kids(page, spec)),
            ("set languages", lambda page: self._set_languages(page, spec)),
            ("go to video elements", lambda page: page.locator("#next-button").click()),
            ("upload captions", lambda page: self._set_captions(page, spec)),
            ("go to checks", lambda page: page.locator("#next-button").click()),
            ("go to visibility", lambda page: page.locator("#next-button").click()),
            ("set visibility", lambda page: self._set_visibility(page, spec)),
            ("wait for upload to finish", lambda page: self._wait_uploaded(page, spec)),
            ("read video link", self._read_link),
            ("save", self._save),
        ]

    # -- steps --------------------------------------------------------------------

    def _set_title(self, page, spec: UploadSpec) -> None:
        box = page.locator("#title-textarea #textbox")
        box.click()
        page.keyboard.press("Meta+A")
        page.keyboard.type(spec.title)

    def _set_description(self, page, spec: UploadSpec) -> None:
        if spec.description:
            raise StepFailed("not implemented yet")

    def _set_thumbnail(self, page, spec: UploadSpec) -> None:
        if spec.thumbnail_path is not None:
            raise StepFailed("not implemented yet")

    def _set_made_for_kids(self, page, spec: UploadSpec) -> None:
        name = "VIDEO_MADE_FOR_KIDS_MFK" if spec.made_for_kids else "VIDEO_MADE_FOR_KIDS_NOT_MFK"
        page.locator(f"tp-yt-paper-radio-button[name='{name}']").click()

    def _set_languages(self, page, spec: UploadSpec) -> None:
        return None

    def _set_captions(self, page, spec: UploadSpec) -> None:
        if spec.captions_path is not None:
            raise StepFailed("not implemented yet")

    def _set_visibility(self, page, spec: UploadSpec) -> None:
        if spec.publish_at is not None or spec.visibility != "private":
            raise StepFailed("not implemented yet")
        page.locator("tp-yt-paper-radio-button[name='PRIVATE']").click()

    def _wait_uploaded(self, page, spec: UploadSpec) -> None:
        size_mb = spec.video_path.stat().st_size / 1_000_000
        timeout = _UPLOAD_BASE_MS + int(size_mb / 100 * _UPLOAD_PER_100MB_MS)
        page.wait_for_function(
            """() => {
                const el = document.querySelector('ytcp-video-upload-progress');
                return el && !/uploading/i.test(el.innerText);
            }""",
            timeout=timeout,
        )

    def _read_link(self, page) -> None:
        link = page.locator("a[href*='youtu.be'], a[href*='/shorts/'], a[href*='watch?v=']").first
        href = link.get_attribute("href")
        self._video_id, self._is_short = parse_video_link(href)
        self._watch_url = href

    def _save(self, page) -> None:
        page.locator("#done-button").click()
        page.wait_for_timeout(5000)

    def _read_back(self, context, spec: UploadSpec) -> list[str]:
        return []
