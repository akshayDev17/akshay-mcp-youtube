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


# Studio's "Video language" dropdown lists languages by name; these are the names it shows.
STUDIO_LANGUAGE_LABELS = {
    "en": "English",
    "en-US": "English (United States)",
    "en-GB": "English (United Kingdom)",
    "en-IN": "English (India)",
    "en-AU": "English (Australia)",
    "en-CA": "English (Canada)",
    "en-IE": "English (Ireland)",
    "hi": "Hindi",
    "bn": "Bengali",
    "mr": "Marathi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "ur": "Urdu",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ar": "Arabic",
    "ru": "Russian",
}


def studio_language_label(code: str) -> str:
    try:
        return STUDIO_LANGUAGE_LABELS[code]
    except KeyError:
        raise ValueError(f"language '{code}' has no known YouTube Studio name") from None


def picker_values(publish_at: datetime, tz) -> tuple[str, str]:
    """Date and time text as Studio's scheduler shows them, e.g. ("Nov 2, 2026", "6:00 PM")."""
    local = publish_at.astimezone(tz)
    hour = local.hour % 12 or 12
    return (
        f"{local.strftime('%b')} {local.day}, {local.year}",
        f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}",
    )


def precheck(spec: UploadSpec) -> list[str]:
    """What Studio's upload dialog cannot do for this spec, found before anything uploads.

    The dialog sets only the video's spoken language ("Video language"), and adds
    captions in that same language; there is no separate title/description language.
    """
    problems = []
    for name in ("language", "audio_language", "captions_language"):
        try:
            studio_language_label(getattr(spec, name))
        except ValueError as error:
            problems.append(f"{name}: {error}")
    if spec.language != spec.audio_language:
        problems.append(
            f"title/description language '{spec.language}' differs from audio_language "
            f"'{spec.audio_language}'; Studio's upload dialog sets only the spoken language"
        )
    if spec.captions_path is not None and spec.captions_language != spec.audio_language:
        problems.append(
            f"captions_language '{spec.captions_language}' differs from audio_language "
            f"'{spec.audio_language}'; Studio adds captions in the video's spoken language"
        )
    return problems


def compare_readback(spec: UploadSpec, observed: dict) -> list[str]:
    """One line per difference between the spec and what Studio shows after saving."""
    lines = []
    if observed.get("title") != spec.title:
        lines.append(f"title is '{observed.get('title')}', expected '{spec.title}'")
    if spec.publish_at is not None:
        seen_at = observed.get("publish_at")
        same_minute = seen_at is not None and seen_at.replace(second=0, microsecond=0) == spec.publish_at.replace(
            second=0, microsecond=0
        )
        if observed.get("visibility") != "scheduled" or not same_minute:
            seen = f"{observed.get('visibility')}" + (f" at {seen_at.isoformat()}" if seen_at else "")
            lines.append(f"schedule is {seen}, expected public at {spec.publish_at.isoformat()}")
    elif observed.get("visibility") != spec.visibility:
        lines.append(f"visibility is {observed.get('visibility')}, expected {spec.visibility}")
    if spec.captions_path is not None and spec.captions_language not in observed.get("caption_languages", []):
        lines.append(f"caption track '{spec.captions_language}' is missing")
    return lines


_SCHEDULE_TEXT = re.compile(r"([A-Z][a-z]{2} \d{1,2}, \d{4}),? (\d{1,2}:\d{2} [AP]M)")


def _parse_schedule(text: str, tz) -> datetime | None:
    match = _SCHEDULE_TEXT.search(text)
    if not match:
        return None
    try:
        local = datetime.strptime(f"{match.group(1)} {match.group(2)}", "%b %d, %Y %I:%M %p")
    except ValueError:
        return None
    return local.replace(tzinfo=tz)


def upload_blocker(page_text: str) -> str | None:
    """A reason Studio will not accept this upload at all, read from the dialog's text."""
    if "daily upload limit reached" in page_text.lower():
        return (
            "YouTube's daily upload limit for this channel was reached; Studio offers a one-time "
            "verification to raise it, otherwise wait 24 hours"
        )
    return None


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

        problems = precheck(spec)
        if problems:
            return UploadOutcome(status="failed", problems=problems)

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                **session.persistent_context_args(spec.channel, self.config, headless=self.config.headless)
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(_STEP_TIMEOUT_MS)
            try:
                return self._run_steps(page, context, spec)
            finally:
                context.close()

    def _run_steps(self, page, context, spec: UploadSpec) -> UploadOutcome:
        """Run every step; once Studio has a video id, a failure is 'needs attention'."""
        self._video_id: str | None = None
        self._is_short: bool | None = None
        self._watch_url: str | None = None
        step = "open Studio"
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
            ("capture video id", self._capture_video_id),
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

    def _capture_video_id(self, page) -> None:
        """Studio creates the video as soon as the file is chosen; learn its id at once so a
        later failure is reported against it rather than as 'nothing created'."""
        link = page.locator("a[href*='youtu.be'], a[href*='/shorts/'], a[href*='watch?v=']").first
        limit = page.get_by_text("Daily upload limit reached", exact=False).first
        link.or_(limit).wait_for(state="visible")
        blocker = upload_blocker(page.evaluate("document.body ? document.body.innerText : ''"))
        if blocker and not link.is_visible():
            raise StepFailed(blocker)
        self._video_id, _ = parse_video_link(link.get_attribute("href"))

    def _set_title(self, page, spec: UploadSpec) -> None:
        box = page.locator("#title-textarea #textbox")
        box.click()
        page.keyboard.press("Meta+A")
        page.keyboard.type(spec.title)

    def _set_description(self, page, spec: UploadSpec) -> None:
        if not spec.description:
            return
        box = page.locator("#textbox[aria-label^='Tell viewers']")
        box.click()
        page.keyboard.press("Meta+A")
        page.keyboard.type(spec.description)

    def _set_thumbnail(self, page, spec: UploadSpec) -> None:
        if spec.thumbnail_path is not None:
            page.locator("input#file-loader").set_input_files(str(spec.thumbnail_path))

    def _set_made_for_kids(self, page, spec: UploadSpec) -> None:
        name = "VIDEO_MADE_FOR_KIDS_MFK" if spec.made_for_kids else "VIDEO_MADE_FOR_KIDS_NOT_MFK"
        page.locator(f"tp-yt-paper-radio-button[name='{name}']").click()

    def _set_languages(self, page, spec: UploadSpec) -> None:
        label = studio_language_label(spec.audio_language)
        page.locator("#toggle-button").click()  # "Show more"
        trigger = page.get_by_text("Video language", exact=False).first
        option = page.locator("tp-yt-paper-item:visible").filter(
            has_text=re.compile(rf"^\s*{re.escape(label)}\s*$")
        ).first
        # The list sometimes opens before it is filled; reopen it once if so.
        for attempt in range(2):
            trigger.scroll_into_view_if_needed()
            trigger.click()
            try:
                option.wait_for(state="visible", timeout=10_000)
                break
            except Exception:
                page.keyboard.press("Escape")
                if attempt:
                    raise
        option.click()

    def _set_captions(self, page, spec: UploadSpec) -> None:
        if spec.captions_path is None:
            return
        page.locator("#subtitles-button").click()
        page.locator("#choose-upload-file").click()
        with page.expect_file_chooser() as chooser:
            page.get_by_text("Continue", exact=True).first.click()  # "With timing" is preselected
        chooser.value.set_files(str(spec.captions_path))
        page.locator("#publish-button").click()
        page.locator("#publish-button").wait_for(state="hidden")

    def _set_visibility(self, page, spec: UploadSpec) -> None:
        if spec.publish_at is None:
            page.locator(f"tp-yt-paper-radio-button[name='{spec.visibility.upper()}']").click()
            return
        date_text, time_text = picker_values(spec.publish_at, datetime.now().astimezone().tzinfo)
        page.locator("#second-container-expand-button").click()  # "Schedule"
        page.locator("#datepicker-trigger").click()
        date_input = page.locator("ytcp-date-picker input:visible, tp-yt-paper-dialog input:visible").first
        date_input.fill(date_text)
        date_input.press("Enter")
        page.keyboard.press("Escape")
        time_input = page.locator("ytcp-uploads-dialog input:visible").filter(
            has_not=page.locator("[type='file']")
        ).last
        time_input.fill(time_text)
        time_input.press("Enter")
        shown_date = page.locator("#datepicker-trigger").inner_text().strip()
        shown_time = time_input.input_value().strip()
        if (shown_date, shown_time) != (date_text, time_text):
            raise StepFailed(f"Studio shows {shown_date} {shown_time}, expected {date_text} {time_text}")

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
        """Reopen the saved video in Studio and compare title, visibility or schedule, and captions."""
        page = context.new_page()
        page.set_default_timeout(_STEP_TIMEOUT_MS)
        try:
            page.goto(f"https://studio.youtube.com/video/{self._video_id}/edit")
            session.skip_unsupported_notice(page)
            title_box = page.locator("#title-textarea #textbox").first
            title_box.wait_for(state="visible")
            visibility_text = page.locator("ytcp-video-metadata-visibility").first.inner_text()
            lowered = visibility_text.lower()
            visibility = next((v for v in ("scheduled", "unlisted", "private", "public") if v in lowered), None)
            observed = {
                "title": title_box.inner_text().strip(),
                "visibility": visibility,
                "publish_at": _parse_schedule(visibility_text, datetime.now().astimezone().tzinfo),
                "caption_languages": [],
            }
            if spec.captions_path is not None:
                page.goto(f"https://studio.youtube.com/video/{self._video_id}/translations")
                session.skip_unsupported_notice(page)
                page.get_by_text("(video language)", exact=False).first.wait_for(state="visible", timeout=60_000)
                labels = {label: code for code, label in STUDIO_LANGUAGE_LABELS.items()}
                body = page.evaluate("document.body ? document.body.innerText : ''")
                for line in body.splitlines():
                    found = re.match(r"^\s*(.+?) \(video language\)\s*$", line)
                    if found and found.group(1) in labels:
                        observed["caption_languages"].append(labels[found.group(1)])
            return compare_readback(spec, observed)
        finally:
            page.close()
