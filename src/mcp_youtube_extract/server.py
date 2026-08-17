"""
YouTube MCP Server

Exposes YouTube video metadata, transcripts, and comments (including Super
Thanks paid amounts) as MCP tools.

Written against the mcp 2.x MCPServer API: tools are registered with
@app.tool() and their input schemas are derived from type hints.
"""

import asyncio
import os

from mcp.server import MCPServer

from .youtube import get_video_info, get_video_transcript, format_video_info
from .comments_api import (
    DEFAULT_MAX_COMMENTS,
    fetch_comment_count,
    format_comments_page,
    format_paid_comments,
    get_comments_page,
    get_paid_comments,
)
from .logger import get_logger

logger = get_logger(__name__)

app = MCPServer(
    name="YouTube Video Analyzer",
    instructions=(
        "Extract YouTube video metadata, transcripts, and comments. "
        "Comment tools return explicit paging state; loop on next_cursor "
        "until has_more is false. Super Thanks amounts are reported when present."
    ),
)


@app.tool(
    description=(
        "Fetch YouTube video information (title, channel, date, views, "
        "description, comment count) and optionally its transcript. Pass "
        "include_transcript=false for a cheap metadata-only lookup, e.g. to "
        "read the comment count before deciding whether to fetch comments. "
        "The comment count is YouTube's reported figure: it covers top-level "
        "comments plus replies and is truncated to two significant figures, "
        "so treat it as approximate."
    ),
)
def get_yt_video_info(video_id: str, include_transcript: bool = True) -> str:
    """
    Fetch video metadata, and the transcript unless it is opted out of.

    Args:
        video_id: The YouTube video ID.
        include_transcript: Set False to skip the transcript, which is the
                            bulk of the response on long videos.
    """
    logger.info(
        f"MCP tool called: get_yt_video_info with video_id: {video_id}, "
        f"include_transcript={include_transcript}"
    )

    # yt-info-extract needs no API key; the key remains an optional fallback.
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    result = []

    try:
        video_info = get_video_info(api_key, video_id)
        result.append("=== VIDEO INFORMATION ===")
        result.append(format_video_info(video_info))

        # yt_info_extract drops comment_count, so source it directly.
        count = fetch_comment_count(video_id)
        result.append(
            f"Comments: ~{count:,} (approximate; includes replies)"
            if isinstance(count, int)
            else "Comments: N/A"
        )
        result.append("")

        if not include_transcript:
            logger.info(f"Skipping transcript for {video_id} on request")
            return "\n".join(result).rstrip()

        transcript = get_video_transcript(video_id)
        result.append("=== TRANSCRIPT ===")

        unavailable = (
            not transcript
            or transcript.startswith("Transcript error:")
            or transcript.startswith("Could not retrieve")
        )
        if not unavailable:
            result.append(transcript)
            logger.info(f"Successfully processed video {video_id} with transcript")
        elif transcript:
            result.append(f"Transcript issue: {transcript}")
            logger.warning(f"Transcript issue for video {video_id}: {transcript}")
        else:
            result.append("No transcript available for this video.")
            logger.warning(f"Video {video_id} processed but no transcript available")

        return "\n".join(result)

    except Exception as e:
        logger.error(f"Error processing video {video_id}: {e}", exc_info=True)
        return f"Error processing video {video_id}: {e}"


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


def main():
    """Main entry point for the MCP server."""
    logger.info("Starting YouTube MCP Server")
    try:
        asyncio.run(app.run_stdio_async())
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
