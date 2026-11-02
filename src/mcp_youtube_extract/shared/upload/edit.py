"""Edit specs: turn edit_yt_video's params into one validated EditSpec, and judge the
read-back of an edit field by field.

Only the fields a request names are touched. Everything here runs before Studio
opens, so a request that fails validation changes nothing on the channel.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .backend import OutcomeStatus
from .config import Channel, ConfigError, UploadConfig
from .spec import DESCRIPTION_LIMIT, THUMBNAIL_LIMIT_BYTES, TITLE_LIMIT
from .studio import studio_language_label

EDIT_FIELDS = (
    "channel", "video_id", "title", "description", "thumbnail_path", "captions_path", "captions_language",
)
# The fields that change something on the video, in the order Studio applies them.
CHANGE_FIELDS = ("title", "description", "thumbnail", "captions")
CAPTION_SUFFIXES = (".srt", ".vtt")

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_TIMING = re.compile(r"(?:\d+:)?\d{2}:\d{2}[,.]\d{3}\s*-->\s*(?:\d+:)?\d{2}:\d{2}[,.]\d{3}")
_IMAGE_SIGNATURES = {
    ".png": (b"\x89PNG\r\n\x1a\n", "PNG"),
    ".jpg": (b"\xff\xd8\xff", "JPEG"),
    ".jpeg": (b"\xff\xd8\xff", "JPEG"),
}


@dataclass
class EditSpec:
    channel: Channel
    video_id: str
    title: str | None = None
    description: str | None = None
    thumbnail_path: Path | None = None
    captions_path: Path | None = None
    captions_language: str | None = None

    @property
    def requested(self) -> list[str]:
        """The fields this edit changes, in CHANGE_FIELDS order."""
        given = {
            "title": self.title is not None,
            "description": self.description is not None,
            "thumbnail": self.thumbnail_path is not None,
            "captions": self.captions_path is not None,
        }
        return [name for name in CHANGE_FIELDS if given[name]]


@dataclass
class EditSpecResult:
    spec: EditSpec | None
    problems: list[str] = field(default_factory=list)


def _absolute_file(name: str, value: Any, problems: list[str]) -> Path | None:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        problems.append(f"{name} must be a non-empty path")
        return None
    path = Path(str(value).strip()).expanduser()
    if not path.is_absolute():
        problems.append(f"{name} '{value}' must be an absolute path")
        return None
    if not path.is_file():
        problems.append(f"{name}: file not found: {path}")
        return None
    return path


def _text_problems(name: str, value: str, limit: int) -> list[str]:
    problems = []
    if len(value) > limit:
        problems.append(f"{name} is {len(value)} characters; the limit is {limit}")
    if "<" in value or ">" in value:
        problems.append(f"{name} must not contain < or >")
    return problems


def thumbnail_problems(path: Path) -> list[str]:
    """A thumbnail must be a real PNG or JPEG of at most 2 MB; the extension alone is not trusted."""
    expected = _IMAGE_SIGNATURES.get(path.suffix.lower())
    if expected is None:
        return [f"thumbnail must be a .png, .jpg or .jpeg file, not {path.name}"]
    size = path.stat().st_size
    if size == 0:
        return [f"thumbnail {path.name} is empty"]
    if size > THUMBNAIL_LIMIT_BYTES:
        return [f"thumbnail {path.name} is {size / 1024 / 1024:.1f} MB; the limit is 2 MB"]
    signature, kind = expected
    with path.open("rb") as handle:
        if not handle.read(len(signature)).startswith(signature):
            return [f"thumbnail {path.name} is not a {kind} image despite its extension"]
    return []


def _read_captions(path: Path) -> tuple[str | None, list[str]]:
    """(text, problems) for a caption file: UTF-8 with at least one timed cue."""
    if path.suffix.lower() not in CAPTION_SUFFIXES:
        return None, [f"captions must be an .srt or .vtt file, not {path.name}"]
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return None, [f"captions file {path.name} is not UTF-8 text"]
    if not _TIMING.search(text):
        return None, [f"captions file {path.name} has no timed cues (lines like 00:00:01,000 --> 00:00:04,000)"]
    return text, []


def first_caption_text(text: str) -> str:
    """The first cue's words, whitespace collapsed: what Studio's subtitle editor shows first."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for i, line in enumerate(lines):
        if _TIMING.search(line):
            words = []
            for cue_line in lines[i + 1:]:
                if not cue_line.strip():
                    break
                words.append(cue_line.strip())
            return collapse_spaces(" ".join(words))
    return ""


def collapse_spaces(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").replace(" ", " ").split())


def build_edit_spec(params: Mapping[str, Any], config: UploadConfig) -> EditSpecResult:
    """Resolve and validate edit params; spec is None if anything is wrong."""
    problems: list[str] = []
    for key in params:
        if key not in EDIT_FIELDS:
            problems.append(f"unknown field '{key}'")
    given = {k: v for k, v in params.items() if k in EDIT_FIELDS and v is not None}

    for key in ("channel", "video_id", "title", "description", "captions_language"):
        if key in given and not isinstance(given[key], str):
            problems.append(f"{key} must be text")
            given.pop(key)

    video_id = given.get("video_id", "").strip()
    if not video_id:
        problems.append("video_id is required")
    elif not _VIDEO_ID.match(video_id):
        problems.append(f"video_id '{video_id}' is not a YouTube video id (11 letters, digits, - or _)")

    if not any(key in given for key in ("title", "description", "thumbnail_path", "captions_path")):
        problems.append("nothing to change: pass at least one of title, description, thumbnail_path, captions_path")

    title = given.get("title")
    if title is not None:
        if not title.strip():
            problems.append("title is empty")
        problems += _text_problems("title", title, TITLE_LIMIT)

    description = given.get("description")
    if description is not None:
        description = description.replace("\r\n", "\n").replace("\r", "\n")
        problems += _text_problems("description", description, DESCRIPTION_LIMIT)

    thumbnail = None
    if "thumbnail_path" in given:
        thumbnail = _absolute_file("thumbnail_path", given["thumbnail_path"], problems)
        if thumbnail is not None:
            problems += thumbnail_problems(thumbnail)

    captions = None
    captions_language = given.get("captions_language")
    if "captions_path" in given:
        captions = _absolute_file("captions_path", given["captions_path"], problems)
        if captions is not None:
            problems += _read_captions(captions)[1]
        if captions_language is None:
            problems.append("captions_language is required with captions_path (e.g. 'en')")
    elif captions_language is not None:
        problems.append("captions_language was given without captions_path")
    if captions_language is not None:
        try:
            studio_language_label(captions_language)
        except ValueError as error:
            problems.append(f"captions_language: {error}")

    channel = None
    try:
        channel = config.resolve_channel(given.get("channel"))
    except ConfigError as error:
        problems.append(str(error))

    if problems:
        return EditSpecResult(None, problems)
    return EditSpecResult(
        EditSpec(
            channel=channel,
            video_id=video_id,
            title=title,
            description=description,
            thumbnail_path=thumbnail,
            captions_path=captions,
            captions_language=captions_language,
        )
    )


# -- judging an edit ------------------------------------------------------------


def _shorten(text: str, limit: int = 60) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def judge_edit(spec: EditSpec, observed: Mapping[str, Any], errors: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    """(applied, problems) per requested field.

    observed holds what Studio shows after saving: "title", "description",
    "thumbnail_before" / "thumbnail_after" (the thumbnail image URL around the edit) and
    "captions_first_cue". errors maps a field to a verdict and reason, e.g. "not applied
    (set title: timeout)"; such a field is reported as a problem whatever observed says.
    """
    applied: dict[str, str] = {}
    problems: list[str] = []
    for name in spec.requested:
        if name in errors:
            problems.append(f"{name} {errors[name]}")
            continue
        if name == "title":
            seen = observed.get("title")
            if seen is not None and collapse_spaces(seen) == collapse_spaces(spec.title):
                applied["title"] = spec.title
            else:
                problems.append(f"title not applied: Studio shows '{seen}', expected '{spec.title}'")
        elif name == "description":
            seen = observed.get("description")
            if seen is not None and collapse_spaces(seen) == collapse_spaces(spec.description):
                applied["description"] = f"{len(spec.description)} characters" if spec.description else "cleared"
            else:
                shown = "nothing" if seen is None else f"'{_shorten(seen)}'"
                problems.append(f"description not applied: Studio shows {shown}, expected '{_shorten(spec.description)}'")
        elif name == "thumbnail":
            before, after = observed.get("thumbnail_before"), observed.get("thumbnail_after")
            if after and after != before:
                applied["thumbnail"] = spec.thumbnail_path.name
            else:
                problems.append("thumbnail not applied: Studio still shows the previous thumbnail")
        elif name == "captions":
            expected = first_caption_text(spec.captions_path.read_text(encoding="utf-8-sig"))
            seen = observed.get("captions_first_cue")
            if seen is not None and collapse_spaces(seen) == expected:
                applied["captions"] = f"{spec.captions_path.name} ({spec.captions_language})"
            else:
                shown = "no subtitles" if seen is None else f"'{_shorten(seen)}'"
                problems.append(f"captions not applied: Studio's subtitle editor shows {shown}, expected '{_shorten(expected)}'")
    return applied, problems


def edit_status(spec: EditSpec, applied: Mapping[str, str], touched: bool) -> OutcomeStatus:
    """done: every requested field reads back as asked. needs_attention: the video may
    have changed, but not every field did. failed: nothing on the video was changed."""
    if all(name in applied for name in spec.requested):
        return "done"
    return "needs_attention" if touched or applied else "failed"
