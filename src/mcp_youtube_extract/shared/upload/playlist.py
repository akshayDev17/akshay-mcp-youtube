"""Creating a playlist on a configured channel: the request, its preview, and the report.

Everything here is plain data in, plain data or text out. The Studio steps that act on
the channel live in studio_playlist.py.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from .backend import OutcomeStatus
from .config import Channel, ConfigError, UploadConfig

PLAYLIST_VISIBILITIES = ("public", "unlisted", "private")
PLAYLIST_TITLE_LIMIT = 150

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


@dataclass(frozen=True)
class PlaylistSpec:
    channel: Channel
    name: str
    visibility: str
    video_ids: tuple[str, ...]


@dataclass(frozen=True)
class VideoFacts:
    """What Studio shows for one video: its title and visibility, or why it could not be read."""

    video_id: str
    title: str | None = None
    visibility: str | None = None
    problem: str | None = None


@dataclass
class PlaylistOutcome:
    """done: created as asked. needs_attention: something needs a person to look; when
    created, the playlist exists on the channel but something did not apply, otherwise
    nothing was created. failed: nothing was created on the channel."""

    status: OutcomeStatus
    created: bool = False
    playlist_id: str | None = None
    applied: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


def build_playlist_spec(params: dict[str, Any], config: UploadConfig) -> tuple[PlaylistSpec | None, list[str]]:
    """Validate a create-playlist request before anything touches Studio."""
    problems: list[str] = []

    name = params.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        problems.append("name is required; propose one to the user if they did not give one")
    elif len(name) > PLAYLIST_TITLE_LIMIT:
        problems.append(f"name is {len(name)} characters; YouTube allows at most {PLAYLIST_TITLE_LIMIT}")
    elif "<" in name or ">" in name:
        problems.append("name must not contain '<' or '>'; YouTube rejects them in playlist titles")

    visibility = params.get("visibility")
    visibility = visibility.strip().lower() if isinstance(visibility, str) else ""
    if not visibility:
        problems.append(
            f"visibility is required ({', '.join(PLAYLIST_VISIBILITIES)}); ask the user, there is no default"
        )
    elif visibility not in PLAYLIST_VISIBILITIES:
        problems.append(f"visibility '{visibility}' must be one of: {', '.join(PLAYLIST_VISIBILITIES)}")

    raw_ids = params.get("video_ids")
    video_ids: list[str] = []
    if not raw_ids:
        problems.append("video_ids is required: ask the user which videos to add, in which order")
    else:
        for position, video_id in enumerate(raw_ids, start=1):
            if not (isinstance(video_id, str) and _VIDEO_ID.fullmatch(video_id)):
                problems.append(f"video {position}: '{video_id}' is not an 11-character YouTube video id")
                continue
            if video_id in video_ids:
                problems.append(
                    f"video {position}: {video_id} is already at position {video_ids.index(video_id) + 1}; "
                    f"a video can be in the playlist once"
                )
                continue
            video_ids.append(video_id)

    channel = None
    try:
        channel = config.resolve_channel(params.get("channel"))
    except ConfigError as error:
        problems.append(str(error))

    if problems:
        return None, problems
    return PlaylistSpec(channel=channel, name=name, visibility=visibility, video_ids=tuple(video_ids)), []


def preview_problems(spec: PlaylistSpec, facts: list[VideoFacts], existing_names: list[str] | None) -> list[str]:
    """What would stop this playlist being created as asked, found from the preview reads.
    existing_names is None when the channel's playlists with similar names could not all be read."""
    problems = [f"video {i} ({f.video_id}): {f.problem}" for i, f in enumerate(facts, start=1) if f.problem]
    if existing_names is None:
        problems.append(
            f"could not read every playlist Studio's Playlists picker lists for '{spec.name}', so the "
            f"channel may already have a playlist with this name; nothing was created — check the "
            f"channel's playlists in Studio, or try again"
        )
    elif spec.name in existing_names:
        problems.append(
            f"the channel already has a playlist named '{spec.name}'; choose another name "
            f"(videos are added by picking the playlist by name)"
        )
    return problems


def _video_line(position: int, fact: VideoFacts) -> str:
    if fact.problem:
        return f"{position}. {fact.video_id} — cannot add: {fact.problem}"
    return f"{position}. {fact.video_id} [{fact.visibility or 'visibility unknown'}] {fact.title}"


def format_preview(spec: PlaylistSpec, facts: list[VideoFacts], problems: list[str]) -> str:
    lines = [
        "=== PLAYLIST PREVIEW (nothing created) ===",
        f"Channel: {spec.channel.name} ({spec.channel.channel_id})",
        f"Name: {spec.name}",
        f"Visibility: {spec.visibility}",
        f"Videos, in playlist order ({len(facts)}):",
    ]
    lines += [f"  {_video_line(i, f)}" for i, f in enumerate(facts, start=1)]
    if problems:
        lines += ["", "Cannot create as asked:"] + [f"- {p}" for p in problems]
    else:
        lines += [
            "",
            "Show this to the user and confirm the name, visibility and video order. "
            "Once they confirm, call again with the same arguments and preview=false to create it.",
        ]
    return "\n".join(lines)


def compare_playlist_readback(spec: PlaylistSpec, observed: dict) -> list[str]:
    """One line per difference between the request and the playlist Studio shows."""
    lines = []
    if observed.get("name") != spec.name:
        lines.append(f"name is '{observed.get('name')}', expected '{spec.name}'")
    if observed.get("visibility") != spec.visibility:
        lines.append(f"visibility is {observed.get('visibility')}, expected {spec.visibility}")
    seen = list(observed.get("video_ids") or [])
    wanted = list(spec.video_ids)
    if seen != wanted:
        missing = [v for v in wanted if v not in seen]
        extra = [v for v in seen if v not in wanted]
        if missing:
            lines.append(f"missing from the playlist: {', '.join(missing)}")
        if extra:
            lines.append(f"in the playlist but not asked for: {', '.join(extra)}")
        if not missing and not extra:
            lines.append(f"video order is {', '.join(seen)}, expected {', '.join(wanted)}")
    return lines


def playlist_url(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def format_outcome(spec: PlaylistSpec, outcome: PlaylistOutcome) -> str:
    headline = {
        "done": "Playlist created",
        "needs_attention": "Playlist created, but needs attention" if outcome.created
        else "Playlist not created; needs attention",
        "failed": "Playlist not created",
    }[outcome.status]
    lines = [f"{headline} (status: {outcome.status})"]
    if outcome.playlist_id:
        lines.append(f"Playlist: {playlist_url(outcome.playlist_id)}")
    if outcome.applied:
        lines.append("Applied:")
        lines += [f"  {key}: {value}" for key, value in outcome.applied.items()]
    if outcome.problems:
        lines.append("Problems:")
        lines += [f"- {p}" for p in outcome.problems]
    if outcome.evidence:
        lines.append("Evidence:")
        lines += [f"  {path}" for path in outcome.evidence]
    if outcome.status == "needs_attention" and outcome.created:
        lines.append(
            "The playlist exists on the channel; fix what is listed in YouTube Studio "
            "rather than creating it again."
        )
    return "\n".join(lines)
