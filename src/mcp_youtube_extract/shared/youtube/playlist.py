"""
Playlist extraction and members-only classification via yt-dlp.

Gating is read from YouTube's own badge during a single flat extraction, so a
256-video playlist costs one request and no authentication. Per-video
extraction is deliberately NOT used here: fetching a members-only video raises
DownloadError rather than reporting its availability, so the flat listing is
the only path that can see gated videos at all.

Flat extraction cannot distinguish public from unlisted -- both arrive with
availability None (yt_dlp/extractor/youtube/_tab.py notes this explicitly).
Both are treated as "free", which matches "watchable by anyone with the link".
"""

import yt_dlp

from ..logger import get_logger

logger = get_logger(__name__)

# yt-dlp's term for members-only, set from YouTube's BADGE_MEMBERS_ONLY.
_MEMBERS_ONLY = "subscriber_only"

# Availability values meaning nobody can watch, regardless of membership.
_INACCESSIBLE = frozenset({"private", "needs_auth", "premium_only"})

STATUS_LABELS = {
    "free": "[free]",
    "members_only": "[members-only]",
    "unavailable": "[unavailable]",
}


def get_playlist_info(playlist_id: str) -> dict | None:
    """
    Fetch a playlist and its entries in one flat request.

    Args:
        playlist_id: A playlist ID (PL...), or a full playlist URL.

    Returns:
        dict: yt-dlp playlist info with an "entries" list, or None on error.
    """
    url = (
        playlist_id
        if playlist_id.startswith("http")
        else f"https://www.youtube.com/playlist?list={playlist_id}"
    )
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        # Keep deleted/private entries in the listing instead of aborting.
        "ignoreerrors": True,
    }
    try:
        logger.info(f"Fetching playlist: {playlist_id}")
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=False))
        if not info:
            logger.warning(f"Playlist not found: {playlist_id}")
            return None
        logger.info(
            f"Fetched playlist '{info.get('title')}' "
            f"with {len(info.get('entries') or [])} entries"
        )
        return info
    except Exception as e:
        logger.error(f"Error fetching playlist {playlist_id}: {e}")
        return None


def classify_entry(entry: dict) -> str:
    """
    Classify one flat playlist entry as free, members_only, or unavailable.

    Gating is checked before the title, since a members-only badge is the more
    informative signal when a title is also missing.
    """
    availability = entry.get("availability")
    if availability == _MEMBERS_ONLY:
        return "members_only"
    if availability in _INACCESSIBLE:
        return "unavailable"
    # Deleted and taken-down videos come back null except for id and url.
    if not entry.get("title"):
        return "unavailable"
    return "free"


def count_by_status(entries: list[dict]) -> dict[str, int]:
    """Tally entries by classification, plus a total."""
    counts = {"total": len(entries), "free": 0, "members_only": 0, "unavailable": 0}
    for entry in entries:
        counts[classify_entry(entry)] += 1
    return counts


def format_playlist_info(info: dict | None, include_videos: bool = True) -> str:
    """Format playlist metadata, gating counts, and optionally each video."""
    if not info:
        return "Playlist not found or unavailable."

    entries = info.get("entries") or []
    counts = count_by_status(entries)

    result = ["=== PLAYLIST INFORMATION ==="]
    result.append(f"Title: {info.get('title', 'N/A')}")
    result.append(f"Channel: {info.get('channel') or info.get('uploader') or 'N/A'}")
    result.append(f"Playlist visibility: {info.get('availability') or 'N/A'}")
    result.append(
        f"Videos: {counts['total']} total — {counts['free']} free, "
        f"{counts['members_only']} members-only, "
        f"{counts['unavailable']} unavailable"
    )

    if not include_videos:
        return "\n".join(result)

    result.append("")
    result.append("=== VIDEOS ===")
    if not entries:
        result.append("(no videos in this playlist)")
        return "\n".join(result)

    width = max(len(label) for label in STATUS_LABELS.values())
    for entry in entries:
        status = classify_entry(entry)
        title = entry.get("title") or "(unavailable)"
        result.append(
            f"{STATUS_LABELS[status]:<{width}}  {entry.get('id', 'N/A')}  {title}"
        )

    return "\n".join(result)
