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

import base64
import json
import re
import urllib.parse
from pathlib import Path

import yt_dlp
from yt_dlp.extractor.youtube import YoutubeIE

from .logger import get_logger

logger = get_logger(__name__)

# Paid comments cluster in "top"; a "new" sort surfaces almost none.
DEFAULT_SORT = "top"
DEFAULT_MAX_COMMENTS = 300

_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "comments"

# Comment ids are the longest "Ug..." token in the decoded surface key.
_UG_TOKEN = re.compile(r"Ug[A-Za-z0-9_-]+")


def _cache_path(video_id: str, sort: str, max_comments: int) -> Path:
    return _CACHE_DIR / f"{video_id}.{sort}.{max_comments}.json"


def _comment_id_from_surface_key(key: str) -> str | None:
    """Decode a commentSurfaceEntityPayload key and pull out the comment id."""
    try:
        padded = urllib.parse.unquote(key) + "=="
        decoded = base64.b64decode(padded).decode("utf8", "replace")
    except Exception:
        return None

    tokens = _UG_TOKEN.findall(decoded)
    return max(tokens, key=len) if tokens else None


def _collect_paid_amounts(responses: list) -> dict[str, str]:
    """Walk captured innertube responses and map comment_id -> paid amount."""
    amounts: dict[str, str] = {}

    def walk(node):
        if isinstance(node, dict):
            payload = node.get("commentSurfaceEntityPayload")
            if isinstance(payload, dict):
                chip = payload.get("pdgCommentChip")
                key = payload.get("key")
                if isinstance(chip, dict) and key:
                    text = (
                        chip.get("pdgCommentChipRenderer", {})
                        .get("chipText", {})
                        .get("simpleText")
                    )
                    comment_id = _comment_id_from_surface_key(key)
                    if text and comment_id:
                        amounts[comment_id] = text
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(responses)
    return amounts


def _fetch_raw(video_id: str, sort: str, max_comments: int) -> tuple[list[dict], dict[str, str]]:
    """Fetch comments via yt-dlp while capturing raw responses for paid amounts."""
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
                "max_comments": [str(max_comments), "all", str(max_comments), "10"],
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


def _merge_paid(comments: list[dict], amounts: dict[str, str]) -> list[dict]:
    """Attach paid_amount to each comment (None when not a Super Thanks)."""
    merged = []
    for comment in comments:
        item = dict(comment)
        item["paid_amount"] = amounts.get(comment.get("id"))
        merged.append(item)
    return merged


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


def nest_comments(comments: list[dict]) -> list[dict]:
    """Group replies under their parents using yt-dlp's `parent` field."""
    by_parent: dict[str, list[dict]] = {}
    roots: list[dict] = []

    for comment in comments:
        parent = comment.get("parent", "root")
        if parent == "root":
            roots.append(comment)
        else:
            by_parent.setdefault(parent, []).append(comment)

    for root in roots:
        root["replies"] = by_parent.get(root.get("id"), [])

    return roots


def get_comments_page(
    video_id: str,
    offset: int = 0,
    limit: int = 20,
    sort: str = DEFAULT_SORT,
    max_comments: int = DEFAULT_MAX_COMMENTS,
) -> dict:
    """
    Return one page of nested top-level comments.

    Paging is over top-level threads; replies ride along with their parent.
    `has_more` is computed, never guessed, so callers can loop until it is False.
    """
    threads = nest_comments(fetch_comments(video_id, sort, max_comments))
    page = threads[offset : offset + limit]
    next_offset = offset + len(page)

    return {
        "video_id": video_id,
        "comments": page,
        "offset": offset,
        "returned": len(page),
        "total_threads": len(threads),
        "has_more": next_offset < len(threads),
        "next_cursor": next_offset if next_offset < len(threads) else None,
    }


def _amount_sort_key(amount: str | None) -> float:
    """Numeric value of a rendered amount, for ranking only (currency-blind)."""
    if not amount:
        return 0.0
    digits = re.sub(r"[^\d.]", "", amount.replace(",", ""))
    try:
        return float(digits)
    except ValueError:
        return 0.0


def get_paid_comments(
    video_id: str,
    sort: str = DEFAULT_SORT,
    max_comments: int = DEFAULT_MAX_COMMENTS,
) -> dict:
    """Return only Super Thanks comments, highest amount first."""
    comments = fetch_comments(video_id, sort, max_comments)
    paid = [c for c in comments if c.get("paid_amount")]
    paid.sort(key=lambda c: _amount_sort_key(c.get("paid_amount")), reverse=True)

    return {
        "video_id": video_id,
        "paid_count": len(paid),
        "scanned": len(comments),
        "comments": paid,
    }


def format_comment_thread(thread: dict, indent: int = 0) -> str:
    """Render one nested thread as indented text."""
    pad = "  " * indent
    paid = thread.get("paid_amount")
    badge = f" [SUPER THANKS {paid}]" if paid else ""
    likes = thread.get("like_count")
    likes_text = f" ({likes:,} likes)" if isinstance(likes, int) else ""

    lines = [
        f"{pad}{thread.get('author', 'unknown')}{badge}{likes_text}: "
        f"{(thread.get('text') or '').strip()}"
    ]
    for reply in thread.get("replies", []):
        lines.append(format_comment_thread(reply, indent + 1))
    return "\n".join(lines)


def format_comments_page(page: dict) -> str:
    """Render a page dict, ending with explicit paging state for the caller."""
    if not page.get("comments"):
        return f"No comments found for video {page.get('video_id')}."

    body = "\n".join(format_comment_thread(t) for t in page["comments"])
    tail = (
        f"next_cursor={page['next_cursor']}"
        if page.get("has_more")
        else "final page"
    )
    return (
        f"Showing threads {page['offset']}-{page['offset'] + page['returned'] - 1} "
        f"of {page['total_threads']}\n\n{body}\n\n"
        f"has_more={page['has_more']}, {tail}"
    )


def format_paid_comments(result: dict) -> str:
    """Render Super Thanks results as text."""
    if not result.get("comments"):
        return (
            f"No Super Thanks found for video {result.get('video_id')} "
            f"(scanned {result.get('scanned', 0)} comments)."
        )

    lines = [
        f"Found {result['paid_count']} Super Thanks "
        f"in {result['scanned']} scanned comments:",
        "",
    ]
    for comment in result["comments"]:
        lines.append(
            f"{comment['paid_amount']:>14}  {comment.get('author', 'unknown')}: "
            f"{(comment.get('text') or '').strip()[:100]}"
        )
    return "\n".join(lines)
