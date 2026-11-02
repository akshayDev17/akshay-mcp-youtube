"""MCP tool: get_yt_upload_status — report an upload job's progress and results."""

from datetime import datetime, timezone

from ..._app import app
from ...shared.logger import get_logger
from ...shared.upload import service
from ...shared.upload.jobs import format_status

logger = get_logger(__name__)


@app.tool(
    description=(
        "Report a job started by upload_yt_video, upload_yt_series or edit_yt_video: the "
        "job's state (queued, running, waiting for sign-in, pausing between uploads, "
        "finished, interrupted) and, per video, its state with watch and Studio links, what "
        "was applied, problems and failure-evidence paths. Once finished it lists every "
        "video that is not done. Also reports a playlist job started by create_yt_playlist: "
        "its state and, once finished, the preview or the created playlist's result."
    ),
)
def get_yt_upload_status(job_id: str) -> str:
    """
    Report an upload job.

    Args:
        job_id: The 12-character id returned by an upload or edit tool.
    """
    logger.info(f"MCP tool called: get_yt_upload_status with job_id: {job_id}")
    try:
        job = service.get_job(job_id)
    except KeyError:
        return f"No upload job with id '{job_id}'."
    except Exception as e:
        logger.error(f"Error reading upload job {job_id}: {e}", exc_info=True)
        return f"Error reading upload job {job_id}: {e}"
    return format_status(job, datetime.now(timezone.utc))
