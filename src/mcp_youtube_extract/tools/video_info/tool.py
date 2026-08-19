"""MCP tool: get_yt_video_info — fetch metadata (+ optional transcript) + comment count."""

import os

from ..._app import app
from ...shared.logger import get_logger
from ...shared.youtube.metadata import get_video_info, format_video_info
from ...shared.youtube.transcript import get_video_transcript
from ...shared.comments.walk import fetch_comment_count

logger = get_logger(__name__)


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

    api_key = os.getenv("YOUTUBE_API_KEY", "")
    result = []

    try:
        video_info = get_video_info(api_key, video_id)
        result.append("=== VIDEO INFORMATION ===")
        result.append(format_video_info(video_info))

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
