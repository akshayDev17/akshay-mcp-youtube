"""MCP tool: get_yt_playlist_info — playlist metadata plus per-video gating."""

from ..._app import app
from ...shared.logger import get_logger
from ...shared.youtube.playlist import get_playlist_info, format_playlist_info

logger = get_logger(__name__)


@app.tool(
    description=(
        "Fetch a YouTube playlist and report, for every video in it, whether "
        "that video is members-only or freely available — plus totals for the "
        "playlist. A playlist can itself be public while individual videos "
        "inside it are gated behind channel membership, so the per-video "
        "status is reported separately from the playlist's own visibility. "
        "Costs a single request regardless of playlist size, and needs no "
        "authentication. Note that unlisted videos are reported as free, "
        "since flat extraction cannot distinguish them from public ones and "
        "both are watchable by anyone with the link. Videos that are deleted, "
        "taken down, or private are reported as unavailable. Pass "
        "include_videos=false for counts only on large playlists."
    ),
)
def get_yt_playlist_info(playlist_id: str, include_videos: bool = True) -> str:
    """
    Report per-video membership gating for a playlist.

    Args:
        playlist_id: The YouTube playlist ID (PL...), or a full playlist URL.
        include_videos: Set False to return only the header and counts,
                        omitting the per-video listing.
    """
    logger.info(
        f"MCP tool called: get_yt_playlist_info with playlist_id: {playlist_id}, "
        f"include_videos={include_videos}"
    )
    try:
        info = get_playlist_info(playlist_id)
        return format_playlist_info(info, include_videos=include_videos)
    except Exception as e:
        logger.error(f"Error processing playlist {playlist_id}: {e}", exc_info=True)
        return f"Error processing playlist {playlist_id}: {e}"
