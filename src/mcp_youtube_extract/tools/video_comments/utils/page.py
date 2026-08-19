"""Paging + text-rendering helpers for the get_yt_video_comments tool."""

from ....shared.comments.walk import fetch_comments, fetch_comment_count, DEFAULT_SORT, DEFAULT_MAX_COMMENTS
from ....shared.comments.nesting import nest_comments
from ....shared.comments.coverage import _truncation_note


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
    comments = fetch_comments(video_id, sort, max_comments)
    threads = nest_comments(comments)
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
        "scanned": len(comments),
        "reported_total": fetch_comment_count(video_id),
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
    coverage = _truncation_note(page.get("scanned", 0), page.get("reported_total"))
    return (
        f"Showing threads {page['offset']}-{page['offset'] + page['returned'] - 1} "
        f"of {page['total_threads']} top-level threads\n"
        f"{coverage}\n\n{body}\n\n"
        f"has_more={page['has_more']}, {tail}"
    )
