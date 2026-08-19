"""
YouTube comment utilities: nested comments and Super Thanks (paid) amounts.

yt-dlp exposes comments but drops paid amounts. The amount lives in a sibling
entity, `commentSurfaceEntityPayload`, which yt-dlp never reads:

    commentSurfaceEntityPayload.pdgCommentChip.pdgCommentChipRenderer
        .chipText.simpleText     ->  e.g. "$25.00", "₹10,000.00"

The two entities share no key, but base64-decoding the surface key reveals the
comment id inside it, which joins to commentEntityPayload.properties.commentId.

This module captures the surface payloads during a normal yt-dlp fetch, builds
{comment_id: amount}, and merges the amount onto yt-dlp's comment dicts.
"""

import json
from pathlib import Path

import yt_dlp
from yt_dlp.extractor.youtube import YoutubeIE

from ..logger import get_logger
from .paid_join import _collect_paid_amounts, _merge_paid

logger = get_logger(__name__)

# Paid comments cluster in "top"; a "new" sort surfaces almost none.
DEFAULT_SORT = "top"

# 300 silently under-reported on real videos (a 2435-comment video yielded 35
# paid comments at 300 but 301 at 3000). Default high enough to cover most
# videos; callers scanning very large ones should raise it and check the
# truncation warning in the output.
DEFAULT_MAX_COMMENTS = 5000

_CACHE_DIR = Path(__file__).resolve().parents[4] / ".cache" / "comments"


def _cache_path(video_id: str, sort: str, max_comments: int) -> Path:
    return _CACHE_DIR / f"{video_id}.{sort}.{max_comments}.json"


def fetch_comment_count(video_id: str) -> int | None:
    """
    YouTube's reported comment count, without fetching any comment text.

    One metadata request with getcomments off. The value counts top-level
    comments plus replies, and YouTube truncates it to two significant figures
    (a real 1,265 is reported as 1,200), so treat it as approximate. It is
    reliable for detecting that a walk fell short, not for certifying that one
    was complete.

    Returns None if the field is unavailable.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=False))
        count = info.get("comment_count")
        logger.info(f"Reported comment_count for {video_id}: {count}")
        return count
    except Exception as e:
        logger.warning(f"Could not fetch comment count for {video_id}: {e}")
        return None


def _fetch_raw(
    video_id: str,
    sort: str,
    max_comments: int,
    replies_per_thread: str = "10",
) -> tuple[list[dict], dict[str, str]]:
    """Fetch comments via yt-dlp while capturing raw responses for paid amounts.

    replies_per_thread="0" skips replies entirely (right choice for Super Thanks,
    which YouTube only allows on top-level comments).
    """
    responses: list = []
    original = YoutubeIE._extract_response

    def capture(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        responses.append(result)
        return result

    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "getcomments": True,
        "extractor_args": {
            "youtube": {
                "comment_sort": [sort],
                # total, parent-limit, top-level, replies-per-thread
                "max_comments": [
                    str(max_comments), "all", str(max_comments), replies_per_thread,
                ],
            }
        },
    }

    YoutubeIE._extract_response = capture
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=False))
    finally:
        YoutubeIE._extract_response = original

    comments = info.get("comments") or []

    # The paid join walks undocumented internals; never let it break the fetch.
    try:
        amounts = _collect_paid_amounts(responses)
    except Exception as e:
        logger.warning(f"Paid amount extraction failed for {video_id}: {e}")
        amounts = {}

    logger.info(
        f"Fetched {len(comments)} comments for {video_id} "
        f"(sort={sort}), {len(amounts)} paid"
    )
    return comments, amounts


def fetch_comments(
    video_id: str,
    sort: str = DEFAULT_SORT,
    max_comments: int = DEFAULT_MAX_COMMENTS,
    refresh: bool = False,
) -> list[dict]:
    """Fetch comments with paid_amount merged, caching the result on disk."""
    path = _cache_path(video_id, sort, max_comments)

    if not refresh and path.exists():
        try:
            cached = json.loads(path.read_text())
            logger.info(f"Cache hit for {video_id} ({len(cached)} comments)")
            return cached
        except Exception as e:
            logger.warning(f"Ignoring unreadable cache {path}: {e}")

    comments, amounts = _fetch_raw(video_id, sort, max_comments)
    merged = _merge_paid(comments, amounts)

    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged))
    except Exception as e:
        logger.warning(f"Could not write cache {path}: {e}")

    return merged


# Cap high enough to cover the largest YouTube video in practice. yt-dlp stops
# on its own when the source is exhausted; this is only an upper bound.
_EXHAUSTIVE_CAP = 10_000_000


def fetch_top_level_paid_exhaustive(
    video_id: str,
    sort: str = DEFAULT_SORT,
    refresh: bool = False,
) -> list[dict]:
    """
    Walk EVERY top-level comment of a video (no replies) and return them with
    paid_amount merged. Cached under a distinct key from get_comments_page's
    partial scans.

    Super Thanks are always top-level (YouTube UI enforces this), so skipping
    replies is both correct and much faster on videos with long reply threads.
    """
    path = _CACHE_DIR / f"{video_id}.{sort}.top-level-exhaustive.json"

    if not refresh and path.exists():
        try:
            cached = json.loads(path.read_text())
            logger.info(
                f"Cache hit (top-level exhaustive) for {video_id} "
                f"({len(cached)} comments)"
            )
            return cached
        except Exception as e:
            logger.warning(f"Ignoring unreadable cache {path}: {e}")

    comments, amounts = _fetch_raw(
        video_id, sort, _EXHAUSTIVE_CAP, replies_per_thread="0"
    )
    # Belt-and-braces: the extractor should return only top-level with "0" replies,
    # but filter defensively so downstream summaries never mistake a reply for a
    # top-level thread.
    top_level = [c for c in comments if c.get("parent") in (None, "root")]
    merged = _merge_paid(top_level, amounts)

    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged))
    except Exception as e:
        logger.warning(f"Could not write cache {path}: {e}")

    return merged
