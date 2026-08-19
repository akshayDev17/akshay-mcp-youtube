"""MCP tool: get_yt_paid_comments — Super Thanks list sorted by amount."""

from ..._app import app
from ...shared.logger import get_logger
from ...shared.comments.walk import DEFAULT_MAX_COMMENTS
from .utils.list import get_paid_comments, format_paid_comments

logger = get_logger(__name__)


@app.tool(
    description=(
        "Fetch only Super Thanks (paid) comments for a video, highest amount "
        "first. Amounts are rendered by YouTube and may be multi-currency. "
        "Paid comments cluster in the 'top' sort order. Output states how many "
        "comments were scanned against the video's reported total, and warns "
        "when max_comments truncated the scan — a truncated scan will "
        "under-report the number of Super Thanks."
    ),
)
def get_yt_paid_comments(
    video_id: str,
    sort: str = "top",
    max_comments: int = DEFAULT_MAX_COMMENTS,
) -> str:
    """
    Return Super Thanks comments for a video, sorted by amount.

    Args:
        video_id: The YouTube video ID.
        sort: Comment sort order, "top" or "new". Paid comments are
              concentrated in "top"; "new" surfaces very few.
        max_comments: Total comments to scan for paid ones.
    """
    logger.info(f"MCP tool called: get_yt_paid_comments with video_id: {video_id}")
    try:
        result = get_paid_comments(video_id, sort=sort, max_comments=max_comments)
        return format_paid_comments(result)
    except Exception as e:
        logger.error(f"Error fetching paid comments for {video_id}: {e}", exc_info=True)
        return f"Error fetching paid comments for {video_id}: {e}"
