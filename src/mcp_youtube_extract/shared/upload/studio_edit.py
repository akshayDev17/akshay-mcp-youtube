"""Edit an existing video in YouTube Studio, in the channel's browser profile.

Title, description and thumbnail are set on the video's Details page and saved
together; captions are uploaded from its Languages page ("Upload manual") in the
video's own language. Each group runs on its own, so one group failing does not
stop the other. Afterwards every changed field is read back from a fresh page.
The media file itself is never touched: YouTube cannot replace it in place.
"""

import re
from datetime import datetime
from typing import Callable

from ..logger import get_logger
from . import session
from .backend import UploadOutcome
from .config import UploadConfig
from .edit import EditSpec, edit_status, judge_edit
from .studio import STUDIO_LANGUAGE_LABELS, StepFailed, save_evidence, studio_language_label

logger = get_logger(__name__)

_STEP_TIMEOUT_MS = 30_000
_SAVE_TIMEOUT_MS = 60_000
_EDITOR_TIMEOUT_MS = 60_000
_ENABLE_TIMEOUT_MS = 5_000

_TITLE_BOX = "#title-textarea #textbox"
_DESCRIPTION_BOX = "#textbox[aria-label^='Tell viewers']"
_THUMBNAIL_INPUT = "input#file-loader"
_SAVE_BUTTON = "ytcp-button#save"
_UPLOAD_CAPTIONS_BUTTON = "#upload-default-language-button"
_EDIT_CAPTIONS_BUTTON = "#m2-editor-button"
_CAPTIONS_UPLOAD_DIALOG = "ytve-captions-editor-upload-dialog"
_CAPTIONS_EDITOR = "ytve-captions-editor-modal"
_SUBTITLE_LINE = "textarea[aria-label='Subtitle']"

# The custom thumbnail's preview; its URL changes when a new thumbnail is set.
_THUMBNAIL_SRC_JS = """() => {
    const img = document.querySelector('ytcp-video-custom-still-editor img');
    return img && img.src ? img.src : null;
}"""
_VIDEO_LANGUAGE = re.compile(r"Video language:\s*(.+)")
_DETAILS_FIELDS = ("title", "description", "thumbnail")
_UNCONFIRMED = "saved, but the read-back failed"


def edit_url(video_id: str) -> str:
    return f"https://studio.youtube.com/video/{video_id}/edit"


def languages_url(video_id: str) -> str:
    return f"https://studio.youtube.com/video/{video_id}/translations"


def video_language_code(page_text: str) -> str | None:
    """The language code of 'Video language: English' on the Languages page, or None."""
    match = _VIDEO_LANGUAGE.search(page_text)
    if not match:
        return None
    label = match.group(1).strip()
    return next((code for code, name in STUDIO_LANGUAGE_LABELS.items() if name == label), None)


def _first_line(error: Exception) -> str:
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__


class StudioEditor:
    """One edit, run against a Playwright browser context of the channel's profile."""

    def __init__(self, config: UploadConfig, spec: EditSpec, now: Callable[[], datetime] = datetime.now):
        self.config = config
        self.spec = spec
        self.now = now
        self.touched = False  # True once a Save or Publish was clicked
        self.errors: dict[str, str] = {}
        self.evidence: list[str] = []
        self.observed: dict = {}

    def run(self, context) -> UploadOutcome:
        context.set_default_timeout(_STEP_TIMEOUT_MS)
        page = context.pages[0] if context.pages else context.new_page()
        details = [name for name in self.spec.requested if name in _DETAILS_FIELDS]
        captions = [name for name in self.spec.requested if name == "captions"]
        self._group(page, details, self._edit_details)
        # A fresh page: a failed details save can leave unsaved changes that block navigation.
        self._group(context.new_page() if captions else page, captions, self._edit_captions)
        if self.touched:
            check = context.new_page()
            for fields, read in ((details, self._read_back_details), (captions, self._read_back_captions)):
                self._group(check, [n for n in fields if n not in self.errors], read, verdict=_UNCONFIRMED)
        return self.outcome()

    def outcome(self) -> UploadOutcome:
        applied, problems = judge_edit(self.spec, self.observed, self.errors)
        video_id = self.spec.video_id
        return UploadOutcome(
            status=edit_status(self.spec, applied, self.touched),
            video_id=video_id,
            watch_url=f"https://youtu.be/{video_id}",
            studio_url=edit_url(video_id),
            applied=applied,
            problems=problems,
            evidence=list(self.evidence),
        )

    def _group(self, page, fields: list[str], run: Callable, verdict: str | None = None) -> None:
        """Run one group of steps; a failure is recorded against each of its fields, as
        'not applied' if it came before any Save or Publish click in this group."""
        if not fields:
            return
        self._step = "start"
        touched_before = self.touched
        try:
            run(page, fields)
        except Exception as error:
            reason = f"{self._step}: {_first_line(error)}"
            logger.warning(f"edit of {self.spec.video_id}: {reason}")
            self.evidence += save_evidence(page, self.config.failures_dir, f"edit {self._step}", self.now())
            if verdict is None:
                verdict = "not applied" if self.touched == touched_before else "may not have applied"
            for name in fields:
                self.errors.setdefault(name, f"{verdict} ({reason})")

    def _at(self, step: str) -> None:
        self._step = step
        logger.info(f"edit {self.spec.video_id}: {step}")

    # -- Details page: title, description, thumbnail -------------------------------

    def _open_details(self, page) -> None:
        self._at("open the video's Details page")
        page.goto(edit_url(self.spec.video_id))
        session.skip_unsupported_notice(page)
        try:
            page.locator(_TITLE_BOX).first.wait_for(state="visible")
        except Exception:
            raise StepFailed(
                f"Studio did not open video {self.spec.video_id} for channel '{self.spec.channel.name}'; "
                "check the id and that the video belongs to this channel"
            ) from None

    def _edit_details(self, page, fields: list[str]) -> None:
        self._open_details(page)
        self.observed["thumbnail_before"] = page.evaluate(_THUMBNAIL_SRC_JS)
        if "title" in fields:
            self._at("set title")
            self._replace_text(page, _TITLE_BOX, self.spec.title)
        if "description" in fields:
            self._at("set description")
            self._replace_text(page, _DESCRIPTION_BOX, self.spec.description)
        if "thumbnail" in fields:
            self._at("set thumbnail")
            page.locator(_THUMBNAIL_INPUT).first.set_input_files(str(self.spec.thumbnail_path))
            page.wait_for_function(
                "(before) => { const img = document.querySelector('ytcp-video-custom-still-editor img');"
                " return img && img.src && img.src !== before; }",
                arg=self.observed["thumbnail_before"],
                timeout=_SAVE_TIMEOUT_MS,
            )
        self._at("save details")
        save = page.locator(_SAVE_BUTTON).first
        try:
            page.wait_for_function(
                "(el) => !el.hasAttribute('disabled')", arg=save.element_handle(), timeout=_ENABLE_TIMEOUT_MS
            )
        except Exception:
            # Studio saw no change: the video already shows these values. Read them from a
            # fresh load rather than trusting the boxes just typed into.
            self._read_back_details(page, fields)
            return
        save.click()
        self.touched = True
        page.wait_for_function(
            "(el) => el.hasAttribute('disabled')", arg=save.element_handle(), timeout=_SAVE_TIMEOUT_MS
        )

    def _replace_text(self, page, selector: str, text: str) -> None:
        box = page.locator(selector).first
        box.click()
        page.keyboard.press("Meta+A")
        if text:
            page.keyboard.type(text)
        else:
            page.keyboard.press("Backspace")

    # -- Languages page: captions ---------------------------------------------------

    def _open_languages(self, page) -> str:
        """Open the Languages page; returns its visible text."""
        self._at("open the video's Languages page")
        page.goto(languages_url(self.spec.video_id))
        session.skip_unsupported_notice(page)
        page.locator(_EDIT_CAPTIONS_BUTTON).first.wait_for(state="visible")
        page.get_by_text("Video language:", exact=False).first.wait_for(state="visible")
        return page.evaluate("document.body ? document.body.innerText : ''")

    def _edit_captions(self, page, fields: list[str]) -> None:
        text = self._open_languages(page)
        self._at("check the video's language")
        shown = video_language_code(text)
        wanted = self.spec.captions_language
        if shown != wanted:
            shown_label = _VIDEO_LANGUAGE.search(text)
            raise StepFailed(
                f"the video's language is {shown_label.group(1).strip() if shown_label else 'not set'}, but the "
                f"captions are {studio_language_label(wanted)}; this tool uploads captions only in the video's language"
            )
        self._at("upload captions")
        page.wait_for_timeout(2000)  # the buttons render before they respond
        page.locator(_UPLOAD_CAPTIONS_BUTTON).first.click()
        dialog = page.locator(_CAPTIONS_UPLOAD_DIALOG).first
        dialog.locator("tp-yt-paper-radio-button[name='with-timing']").click()
        with page.expect_file_chooser() as chooser:
            dialog.locator("#confirm-button").click()
        chooser.value.set_files(str(self.spec.captions_path))
        editor = page.locator(_CAPTIONS_EDITOR).first
        editor.locator(_SUBTITLE_LINE).first.wait_for(state="visible", timeout=_EDITOR_TIMEOUT_MS)
        self._at("publish captions")
        publish = editor.locator("#publish-button").first
        publish.click()
        self.touched = True
        publish.wait_for(state="hidden", timeout=_SAVE_TIMEOUT_MS)

    # -- read back ----------------------------------------------------------------

    def _read_back_details(self, page, fields: list[str]) -> None:
        self._open_details(page)
        self._at("read back details")
        page.wait_for_timeout(2000)
        self.observed["title"] = page.locator(_TITLE_BOX).first.inner_text().strip()
        self.observed["description"] = page.locator(_DESCRIPTION_BOX).first.inner_text()
        self.observed["thumbnail_after"] = page.evaluate(_THUMBNAIL_SRC_JS)

    def _read_back_captions(self, page, fields: list[str]) -> None:
        self._open_languages(page)
        self._at("read back captions")
        page.wait_for_timeout(2000)
        page.locator(_EDIT_CAPTIONS_BUTTON).first.click()
        line = page.locator(f"{_CAPTIONS_EDITOR} {_SUBTITLE_LINE}").first
        try:
            line.wait_for(state="visible", timeout=_EDITOR_TIMEOUT_MS)
            self.observed["captions_first_cue"] = line.input_value()
        finally:
            page.keyboard.press("Escape")  # close the editor without saving
