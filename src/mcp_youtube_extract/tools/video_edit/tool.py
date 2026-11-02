"""MCP tool: edit_yt_video — change an existing video's title, description, thumbnail or captions."""

from datetime import datetime, timezone

from ..._app import app
from ...shared.logger import get_logger
from ...shared.upload import service
from ...shared.upload.config import ConfigError
from ...shared.upload.edit import build_edit_spec
from ...shared.upload.jobs import format_status, new_job

logger = get_logger(__name__)


@app.tool(
    description=(
        "Edit an existing video on one of the owner's configured YouTube channels, by video "
        "id. One call changes any combination of: title, description, thumbnail "
        "(thumbnail_path: an absolute path to a PNG or JPG of at most 2 MB) and captions "
        "(captions_path: an absolute path to an .srt or .vtt file, plus captions_language, "
        "which must be the video's own language, e.g. 'en'). Fields you leave out are not "
        "touched; description='' clears the description. Inputs are checked first, and "
        "nothing is changed if any of them is invalid. After saving, every changed field is "
        "read back from YouTube Studio and reported as applied or not: done (all applied), "
        "needs_attention (something did not apply or could not be confirmed) or failed "
        "(nothing on the video changed). The video file itself cannot be replaced: YouTube "
        "does not allow swapping an uploaded video's media in place, and this tool never "
        "re-uploads or deletes a video. Visibility, schedule and playlists are not edited "
        "here. `channel` is a configured name or channel id (default: the configured "
        "default channel) and must own the video. Edits run one at a time with uploads; if "
        "the channel needs signing in, a browser window opens on the owner's machine. If "
        "the edit has not finished within the call, the reply gives a job id: check it with "
        "get_yt_upload_status."
    ),
)
def edit_yt_video(
    video_id: str,
    channel: str | None = None,
    title: str | None = None,
    description: str | None = None,
    thumbnail_path: str | None = None,
    captions_path: str | None = None,
    captions_language: str | None = None,
) -> str:
    """
    Edit one existing video.

    Args:
        video_id: The 11-character YouTube video id.
        channel: Configured channel name or channel id that owns the video; default channel if omitted.
        title: New title (at most 100 characters, no < or >).
        description: New description (at most 5000 characters, no < or >); '' clears it.
        thumbnail_path: Absolute path of a new PNG or JPG thumbnail, at most 2 MB.
        captions_path: Absolute path of an .srt or .vtt caption file.
        captions_language: Language of the caption file, e.g. 'en'; required with captions_path.
    """
    params = {k: v for k, v in locals().items() if v is not None}
    logger.info(f"MCP tool called: edit_yt_video with {params}")
    try:
        runner = service.get_runner()
        result = build_edit_spec(params, runner.config)
        if result.spec is None:
            return "Not edited:\n" + "\n".join(f"- {p}" for p in result.problems)
        now = datetime.now(timezone.utc)
        job = new_job("edit", [params], None, now)
        job.entries[0].video_id = result.spec.video_id
        runner.submit(job)
        final = runner.wait(job.job_id, runner.config.call_wait_s)
        status = format_status(final, datetime.now(timezone.utc))
        if final.finished:
            return status
        return (
            f"Still running as edit job {job.job_id}; call get_yt_upload_status with "
            f"job_id='{job.job_id}' to follow it.\n\n{status}"
        )
    except ConfigError as e:
        return f"Upload tools are not configured: {e}"
    except Exception as e:
        logger.error(f"Error in edit_yt_video: {e}", exc_info=True)
        return f"Error editing video: {e}"
