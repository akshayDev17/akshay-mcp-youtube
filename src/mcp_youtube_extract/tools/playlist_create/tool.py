"""MCP tool: create_yt_playlist — preview, then create, a playlist on a configured channel."""

from datetime import datetime, timezone

from ..._app import app
from ...shared.logger import get_logger
from ...shared.upload import service
from ...shared.upload.config import ConfigError
from ...shared.upload.jobs import format_status, new_job
from ...shared.upload.playlist import build_playlist_spec

logger = get_logger(__name__)


@app.tool(
    description=(
        "Create a playlist on one of the owner's configured YouTube channels, through YouTube "
        "Studio in the channel's signed-in browser profile. Before calling, settle three things "
        "with the user: (1) visibility — 'public', 'unlisted' or 'private'; there is NO default, "
        "so ask the user if they did not say; (2) name — if the user gave none, propose one and "
        "use it; (3) videos — the channel's own 11-character video ids in playlist order; if the "
        "user did not name the videos, ask which ones they want. Public, unlisted and private "
        "videos can all be added. Call first with preview=true (the default): it creates "
        "nothing, and lists each video's title and visibility in the planned order. Show that "
        "to the user and confirm the name, visibility and order; only after they confirm, call "
        "again with the same arguments and preview=false to create the playlist. The result "
        "reads the created playlist back from Studio and reports status done, needs_attention "
        "(the playlist exists but something did not apply — fix it in Studio, do not create it "
        "again) or failed (nothing was created). A name the channel already uses is refused. "
        "Preview and create run as jobs, one at a time with uploads; each video takes a few "
        "seconds, and if the channel needs signing in, a browser window opens on the owner's "
        "machine. If the job has not finished within the call, the reply gives a job id: "
        "check it with get_yt_upload_status."
    ),
)
def create_yt_playlist(
    name: str,
    visibility: str,
    video_ids: list[str],
    channel: str | None = None,
    preview: bool = True,
) -> str:
    """
    Preview or create a playlist.

    Args:
        name: Playlist title (at most 150 characters). Propose one if the user gave none.
        visibility: 'public', 'unlisted' or 'private'. Required; ask the user if not stated.
        video_ids: The channel's 11-character video ids, in playlist order.
        channel: Configured channel name or channel id; default channel if omitted.
        preview: True (default) only shows what would be created; False creates it.
    """
    params = {"name": name, "visibility": visibility, "video_ids": video_ids, "channel": channel}
    logger.info(f"MCP tool called: create_yt_playlist with {params}, preview={preview}")
    try:
        runner = service.get_runner()
        spec, problems = build_playlist_spec(params, runner.config)
        if spec is None:
            return "Not created:\n" + "\n".join(f"- {p}" for p in problems)
        job = new_job("playlist", [{**params, "preview": preview}], None, datetime.now(timezone.utc))
        runner.submit(job)
        final = runner.wait(job.job_id, runner.config.call_wait_s)
        status = format_status(final, datetime.now(timezone.utc))
        if final.finished:
            return status
        return (
            f"Still running as playlist job {job.job_id}; call get_yt_upload_status with "
            f"job_id='{job.job_id}' to follow it.\n\n{status}"
        )
    except ConfigError as e:
        return f"Upload tools are not configured: {e}"
    except Exception as e:
        logger.error(f"Error in create_yt_playlist: {e}", exc_info=True)
        return f"Error creating playlist: {e}"
