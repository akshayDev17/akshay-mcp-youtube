"""MCP tool: upload_yt_video — upload one video to a configured channel."""

from datetime import datetime, timezone

from ..._app import app
from ...shared.logger import get_logger
from ...shared.upload import service
from ...shared.upload.config import ConfigError
from ...shared.upload.jobs import format_status, new_job
from ...shared.upload.runner import JobRunner
from ...shared.upload.spec import build_spec

logger = get_logger(__name__)


@app.tool(
    description=(
        "Upload one video to one of the owner's configured YouTube channels. Videos are "
        "PUBLIC BY DEFAULT: pass visibility='private' or 'unlisted' to keep one hidden, or "
        "publish_at (ISO 8601 with a UTC offset, e.g. 2026-11-02T18:00:00+05:30) to schedule "
        "it; publish_at and visibility cannot be combined. Point `folder` at a video folder "
        "(one .mp4 plus title.txt, description.md, captions.srt, thumbnail.png/.jpg — the "
        "explainer-video pipeline's layout) or pass video_path and title directly; explicit "
        "values override the folder. Paths must be absolute. `channel` is a configured name "
        "or channel id (default: the configured default channel). language/audio_language/"
        "captions_language default to 'en'. Uploads run one at a time on the server; if the "
        "channel needs signing in, a browser window opens on the owner's machine and the "
        "upload continues once they sign in. If the upload has not finished within the "
        "call, the reply gives a job id: check it with get_yt_upload_status."
    ),
)
def upload_yt_video(
    channel: str | None = None,
    folder: str | None = None,
    video_path: str | None = None,
    title: str | None = None,
    description: str | None = None,
    captions_path: str | None = None,
    thumbnail_path: str | None = None,
    visibility: str | None = None,
    publish_at: str | None = None,
    language: str | None = None,
    audio_language: str | None = None,
    captions_language: str | None = None,
    made_for_kids: bool | None = None,
) -> str:
    """
    Upload one video.

    Args:
        channel: Configured channel name or channel id; default channel if omitted.
        folder: Absolute path of a video folder (one .mp4, title.txt, description.md, ...).
        video_path: Absolute path of the video file (overrides the folder's).
        title: Video title (overrides title.txt; required without a folder).
        description: Description text (overrides description.md).
        captions_path: Absolute path of an .srt caption file.
        thumbnail_path: Absolute path of a PNG or JPG thumbnail.
        visibility: 'public' (default), 'unlisted' or 'private'.
        publish_at: Scheduled public time, ISO 8601 with UTC offset.
        language: Language of title and description (default 'en').
        audio_language: Spoken language (default: language).
        captions_language: Language of the caption track (default: language).
        made_for_kids: YouTube's audience declaration (default false).
    """
    params = {k: v for k, v in locals().items() if v is not None}
    logger.info(f"MCP tool called: upload_yt_video with {params}")
    try:
        runner = service.get_runner()
        now = datetime.now(timezone.utc)
        result = build_spec(params, None, runner.config, now)
        if result.spec is None:
            return "Not uploaded:\n" + "\n".join(f"- {p}" for p in result.problems)
        duplicate = runner.find_duplicate(result.spec)
        if duplicate:
            return (
                f"Not uploaded: this video is already in upload job {duplicate} (same file and "
                f"channel within 24 hours). Check it with get_yt_upload_status."
            )
        job = new_job("video", [params], None, now)
        job.entries[0].file_key = JobRunner.file_key(result.spec)
        runner.submit(job)
        final = runner.wait(job.job_id, runner.config.call_wait_s)
        status = format_status(final, datetime.now(timezone.utc))
        if final.finished:
            return status
        return (
            f"Still running as upload job {job.job_id}; call get_yt_upload_status with "
            f"job_id='{job.job_id}' to follow it.\n\n{status}"
        )
    except ConfigError as e:
        return f"Upload tools are not configured: {e}"
    except Exception as e:
        logger.error(f"Error in upload_yt_video: {e}", exc_info=True)
        return f"Error uploading video: {e}"
