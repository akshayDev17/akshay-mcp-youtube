"""
YouTube search via yt-dlp, split into videos-only and playlists-only modes.

Search is delegated entirely to YouTube: the website's own `sp=` filter token
is passed through, so ranking and filtering match what the site returns. No
ranking logic lives here.

Results are heterogeneous -- one query returns videos, playlists, channels and
Shorts mixed together -- so entries are filtered by kind after the fetch:

  videos     ie_key "Youtube", excluding /shorts/ urls
  playlists  ie_key "YoutubeTab" with a /playlist?list= url
  channels   ie_key "YoutubeTab" with a /channel/ url  (never returned)

Shorts are identified by their url path, not by duration. A short is any video
served under /shorts/; a legitimately brief full video keeps a /watch?v= url,
so duration would misclassify it.
"""

import urllib.parse

import yt_dlp

from ..logger import get_logger

logger = get_logger(__name__)

# YouTube's own search filter tokens, as used by the website's sp= parameter.
# Each encodes sort order crossed with result type.
_SEARCH_FILTERS = {
    ("video", "relevance"): "EgIQAQ%3D%3D",
    ("video", "date"): "CAISAhAB",
    ("video", "views"): "CAMSAhAB",
    ("playlist", "relevance"): "EgIQAw%3D%3D",
    ("playlist", "date"): "CAISAhAD",
    ("playlist", "views"): "CAMSAhAD",
}

VALID_MODES = ("video", "playlist")
VALID_SORTS = ("relevance", "date", "views")


def build_search_url(query: str, mode: str, sort: str) -> str:
    """Build a YouTube search URL carrying the right sp= filter token."""
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}, got {mode!r}")
    if sort not in VALID_SORTS:
        raise ValueError(f"sort must be one of {VALID_SORTS}, got {sort!r}")
    encoded = urllib.parse.quote_plus(query)
    return (
        f"https://www.youtube.com/results?search_query={encoded}"
        f"&sp={_SEARCH_FILTERS[(mode, sort)]}"
    )


def is_short(entry: dict) -> bool:
    """True if the entry is a Short, judged by its url path rather than length."""
    return "/shorts/" in (entry.get("url") or "")


def keep_videos(entries: list[dict]) -> list[dict]:
    """Full-length videos only: drops Shorts, playlists and channels."""
    return [e for e in entries if e.get("ie_key") == "Youtube" and not is_short(e)]


def keep_playlists(entries: list[dict]) -> list[dict]:
    """Playlists only: channels share ie_key YoutubeTab, so the url decides."""
    return [
        e
        for e in entries
        if e.get("ie_key") == "YoutubeTab" and "list=" in (e.get("url") or "")
    ]


def _fetch(query: str, mode: str, sort: str, limit: int) -> list[dict]:
    """One flat search request, over-fetched so filtering can still fill `limit`."""
    url = build_search_url(query, mode, sort)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
        # Shorts and channels are dropped after the fetch, so ask for extra.
        "playlistend": limit * 3,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=False))
        return (info or {}).get("entries") or []
    except Exception as e:
        logger.error(f"Search failed for {query!r} ({mode}): {e}")
        return []


def search_youtube(
    query: str, limit: int = 10, sort: str = "relevance"
) -> dict:
    """
    Search YouTube for full-length videos and playlists.

    Runs one request per category so each returns up to `limit` results,
    rather than the two competing for slots in a single ranked list.
    """
    logger.info(f"Searching YouTube for {query!r} (limit={limit}, sort={sort})")
    videos = keep_videos(_fetch(query, "video", sort, limit))[:limit]
    playlists = keep_playlists(_fetch(query, "playlist", sort, limit))[:limit]
    logger.info(f"Found {len(videos)} videos and {len(playlists)} playlists")
    return {"query": query, "sort": sort, "videos": videos, "playlists": playlists}


def _duration(seconds: int | None) -> str:
    """Seconds as H:MM:SS or M:SS."""
    if not seconds:
        return "N/A"
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _views(count: int | None) -> str:
    return f"{count:,}" if isinstance(count, int) else "N/A"


def format_search_results(results: dict) -> str:
    """Format videos and playlists into two labelled sections."""
    out = ["=== SEARCH RESULTS ==="]
    out.append(f"Query: {results.get('query', 'N/A')}")
    out.append(f"Sorted by: {results.get('sort', 'relevance')}")

    videos = results.get("videos") or []
    out.append("")
    out.append(f"=== VIDEOS ({len(videos)}) ===")
    if not videos:
        out.append("(no videos found)")
    for v in videos:
        out.append(
            f"{v.get('id', 'N/A')}  [{_duration(v.get('duration'))}]  "
            f"{_views(v.get('view_count'))} views  "
            f"{v.get('channel') or v.get('uploader') or 'N/A'}"
        )
        out.append(f"    {v.get('title') or '(untitled)'}")

    playlists = results.get("playlists") or []
    out.append("")
    out.append(f"=== PLAYLISTS ({len(playlists)}) ===")
    if not playlists:
        out.append("(no playlists found)")
    for p in playlists:
        out.append(
            f"{p.get('id', 'N/A')}  "
            f"{p.get('channel') or p.get('uploader') or 'N/A'}"
        )
        out.append(f"    {p.get('title') or '(untitled)'}")

    return "\n".join(out)
