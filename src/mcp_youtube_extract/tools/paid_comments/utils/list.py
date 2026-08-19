"""Paid-only comment listing helpers for the get_yt_paid_comments tool."""

import re

from ....shared.comments.walk import fetch_comments, fetch_comment_count, DEFAULT_SORT, DEFAULT_MAX_COMMENTS
from ....shared.comments.coverage import _truncation_note


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
        "reported_total": fetch_comment_count(video_id),
        "comments": paid,
    }


def format_paid_comments(result: dict) -> str:
    """Render Super Thanks results as text."""
    coverage = _truncation_note(result.get("scanned", 0), result.get("reported_total"))

    if not result.get("comments"):
        return (
            f"No Super Thanks found for video {result.get('video_id')}.\n{coverage}"
        )

    lines = [
        f"Found {result['paid_count']} Super Thanks.",
        coverage,
        "",
    ]
    for comment in result["comments"]:
        lines.append(
            f"{comment['paid_amount']:>14}  {comment.get('author', 'unknown')}: "
            f"{(comment.get('text') or '').strip()[:100]}"
        )
    return "\n".join(lines)
