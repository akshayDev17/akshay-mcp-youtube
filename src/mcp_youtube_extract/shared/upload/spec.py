"""Upload specs: turn tool params, batch defaults and a video folder into one UploadSpec.

A video folder follows the explainer-video pipeline's convention: exactly one .mp4,
title.txt, description.md, captions.srt and thumbnail.png/.jpg. Explicit params win
over the folder; batch defaults fill only what an entry leaves out.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping

from .config import ConfigError, UploadConfig, Channel

FIELDS = (
    "channel", "folder", "video_path", "title", "description", "captions_path",
    "thumbnail_path", "visibility", "publish_at", "language", "audio_language",
    "captions_language", "made_for_kids",
)
VISIBILITIES = ("private", "unlisted", "public")
_PATH_FIELDS = ("folder", "video_path", "captions_path", "thumbnail_path")
_TEXT_FIELDS = ("channel", "title", "description", "language", "audio_language", "captions_language")
_THUMBNAIL_NAMES = ("thumbnail.png", "thumbnail.jpg", "thumbnail.jpeg")

Visibility = Literal["private", "unlisted", "public"]


@dataclass
class UploadSpec:
    channel: Channel
    video_path: Path
    title: str
    description: str = ""
    captions_path: Path | None = None
    thumbnail_path: Path | None = None
    visibility: Visibility | None = "public"
    publish_at: datetime | None = None
    language: str = "en"
    audio_language: str = "en"
    captions_language: str = "en"
    made_for_kids: bool = False


@dataclass
class SpecResult:
    spec: UploadSpec | None
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")


def _as_path(name: str, value: Any, problems: list[str]) -> Path | None:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        problems.append(f"{name} must be a non-empty path")
        return None
    path = Path(str(value).strip()).expanduser()
    if not path.is_absolute():
        problems.append(f"{name} '{value}' must be an absolute path")
        return None
    return path


def _parse_publish_at(value: Any, problems: list[str]) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).strip())
        except ValueError:
            problems.append(f"publish_at '{value}' is not an ISO 8601 date and time")
            return None
    if moment.tzinfo is None or moment.utcoffset() is None:
        problems.append(f"publish_at '{value}' must include a UTC offset, e.g. 2026-11-02T18:00:00+05:30")
        return None
    return moment.astimezone(timezone.utc)


def _from_folder(folder: Path, problems: list[str], warnings: list[str]) -> dict[str, Any]:
    """What the folder supplies, by convention."""
    if not folder.is_dir():
        problems.append(f"folder '{folder}' does not exist or is not a directory")
        return {}
    found: dict[str, Any] = {}
    videos = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".mp4")
    if len(videos) == 1:
        found["video_path"] = videos[0]
    elif not videos:
        found["_video_problem"] = f"folder '{folder}' has no .mp4 video file"
    else:
        names = ", ".join(p.name for p in videos)
        found["_video_problem"] = f"folder '{folder}' has more than one .mp4 ({names}); pass video_path"
    title_file = folder / "title.txt"
    if title_file.is_file():
        lines = _read_text(title_file).split("\n")
        found["title"] = lines[0].strip()
    description_file = folder / "description.md"
    if description_file.is_file():
        found["description"] = _read_text(description_file)
    captions_file = folder / "captions.srt"
    if captions_file.is_file():
        found["captions_path"] = captions_file
    for name in _THUMBNAIL_NAMES:
        if (folder / name).is_file():
            found["thumbnail_path"] = folder / name
            break
    else:
        if (folder / "thumbnail.svg").is_file():
            warnings.append("thumbnail.svg ignored: YouTube needs a PNG or JPG thumbnail")
    return found


def resolve_spec(
    params: Mapping[str, Any], defaults: Mapping[str, Any] | None, config: UploadConfig
) -> SpecResult:
    problems: list[str] = []
    warnings: list[str] = []
    defaults = dict(defaults or {})

    for source in (defaults, params):
        for key in source:
            if key not in FIELDS:
                problems.append(f"unknown field '{key}'")

    merged = {k: v for k, v in {**defaults, **params}.items() if k in FIELDS and v is not None}
    # A default visibility never applies to a scheduled entry; only its own does.
    if "publish_at" in merged:
        merged.pop("visibility", None)
        if params.get("visibility") is not None:
            merged["visibility"] = params["visibility"]

    for key in _TEXT_FIELDS:
        if key in merged and not isinstance(merged[key], str):
            problems.append(f"{key} must be text")
            merged.pop(key)

    paths: dict[str, Path | None] = {
        key: _as_path(key, merged[key], problems) for key in _PATH_FIELDS if key in merged
    }

    folder_found: dict[str, Any] = {}
    if paths.get("folder") is not None:
        folder_found = _from_folder(paths["folder"], problems, warnings)

    video_path = paths.get("video_path") or folder_found.get("video_path")
    if video_path is None and "video_path" not in merged:
        if "folder" not in merged:
            problems.append("either folder or video_path is required")
        elif "_video_problem" in folder_found:
            problems.append(folder_found["_video_problem"])

    title = merged.get("title", folder_found.get("title"))
    if title is None:
        if "folder" in merged:
            problems.append("no title: the folder has no title.txt, so pass title")
        else:
            problems.append("title is required without a folder")

    visibility = merged.get("visibility", None if "publish_at" in merged else "public")
    if visibility is not None and visibility not in VISIBILITIES:
        problems.append(f"visibility '{visibility}' must be one of: {', '.join(VISIBILITIES)}")

    publish_at = _parse_publish_at(merged["publish_at"], problems) if "publish_at" in merged else None

    made_for_kids = merged.get("made_for_kids", False)
    if not isinstance(made_for_kids, bool):
        problems.append(f"made_for_kids must be true or false, not '{made_for_kids}'")

    channel = None
    try:
        channel = config.resolve_channel(merged.get("channel"))
    except ConfigError as error:
        problems.append(str(error))

    if problems:
        return SpecResult(None, problems, warnings)

    language = merged.get("language", "en")
    spec = UploadSpec(
        channel=channel,
        video_path=video_path,
        title=title,
        description=merged.get("description", folder_found.get("description", "")),
        captions_path=paths.get("captions_path") or folder_found.get("captions_path"),
        thumbnail_path=paths.get("thumbnail_path") or folder_found.get("thumbnail_path"),
        visibility=visibility,
        publish_at=publish_at,
        language=language,
        audio_language=merged.get("audio_language", language),
        captions_language=merged.get("captions_language", language),
        made_for_kids=made_for_kids,
    )
    return SpecResult(spec, problems, warnings)
