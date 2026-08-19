"""MCP tool: get_yt_super_thanks_summary — aggregate paid/free + per-currency + INR total."""

from ..._app import app
from ...shared.logger import get_logger
from ...shared.comments.walk import fetch_top_level_paid_exhaustive, fetch_comment_count
from .utils.summarize import summarize_super_thanks
from .utils.format import format_super_thanks_summary

logger = get_logger(__name__)


@app.tool(
    description=(
        "Aggregate Super Thanks across an entire video: paid vs free comment "
        "counts, per-currency donation totals, and an INR grand total. Performs "
        "an exhaustive top-level scan (Super Thanks are always top-level per "
        "YouTube policy, so replies are skipped for speed). First call on a "
        "video is slow but the walk is cached; subsequent calls are instant. "
        "FX rates come from frankfurter.dev (ECB, no key); currencies outside "
        "ECB coverage stay in the per-currency breakdown but are excluded from "
        "the INR grand total, with a note."
    ),
)
def get_yt_super_thanks_summary(video_id: str, sort: str = "top") -> str:
    """
    Return the Super Thanks summary for a video.

    Args:
        video_id: The YouTube video ID.
        sort: Comment sort order ("top" or "new"). Super Thanks cluster in "top";
              "new" surfaces very few and can miss most donations.
    """
    logger.info(f"MCP tool called: get_yt_super_thanks_summary with video_id: {video_id}")
    try:
        comments = fetch_top_level_paid_exhaustive(video_id, sort=sort)
        result = summarize_super_thanks(comments)
        total_with_replies = fetch_comment_count(video_id)
        replies_note = (
            f" (video also has ~{total_with_replies:,} comments+replies total, "
            f"but replies cannot be Super Thanks and are skipped.)"
            if isinstance(total_with_replies, int) else ""
        )
        coverage = (
            f"Exhaustively scanned {result['scanned']:,} top-level comments."
            f"{replies_note}"
        )
        return format_super_thanks_summary(result, video_id, coverage)
    except Exception as e:
        logger.error(
            f"Error summarizing Super Thanks for {video_id}: {e}", exc_info=True
        )
        return f"Error summarizing Super Thanks for {video_id}: {e}"
