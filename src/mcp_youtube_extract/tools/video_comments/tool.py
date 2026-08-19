"""MCP tool: get_yt_video_comments — one page of nested comment threads."""

from ..._app import app
from ...shared.logger import get_logger
from ...shared.comments.walk import DEFAULT_MAX_COMMENTS
from .utils.page import get_comments_page, format_comments_page

logger = get_logger(__name__)


@app.tool(
    description=(
        "Fetch one page of nested YouTube comments, with replies grouped under "
        "their parent thread. Returns explicit has_more / next_cursor paging "
        "state so callers can loop until has_more is false. Super Thanks "
        "comments are marked with their paid amount. Output states how many "
        "comments were scanned against the video's reported total, and warns "
        "when max_comments truncated the scan."
    ),
)
def get_yt_video_comments(
    video_id: str,
    offset: int = 0,
    limit: int = 20,
    sort: str = "top",
    max_comments: int = DEFAULT_MAX_COMMENTS,
) -> str:
    """
    Return a page of nested top-level comment threads.

    Args:
        video_id: The YouTube video ID.
        offset: Index of the first top-level thread to return.
        limit: Number of top-level threads per page.
        sort: Comment sort order, "top" or "new".
        max_comments: Total comments to fetch and cache on the first call.
                      Larger values are slower but see more of the video.
    """
    logger.info(f"MCP tool called: get_yt_video_comments with video_id: {video_id}")
    try:
        page = get_comments_page(
            video_id,
            offset=offset,
            limit=limit,
            sort=sort,
            max_comments=max_comments,
        )
        return format_comments_page(page)
    except Exception as e:
        logger.error(f"Error fetching comments for {video_id}: {e}", exc_info=True)
        return f"Error fetching comments for {video_id}: {e}"
