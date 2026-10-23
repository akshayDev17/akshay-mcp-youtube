"""MCP tool: upload_yt_series — upload several videos, one at a time, as a background job."""

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
        "Upload a batch of videos as one background job and return its job id at once. "
        "Each entry in `videos` takes the same fields as upload_yt_video (folder, video_path, "
        "title, description, captions_path, thumbnail_path, visibility, publish_at, language, "
        "audio_language, captions_language, made_for_kids, channel), so every video can have "
        "its own schedule, visibility and channel. `defaults` fills only fields an entry "
        "leaves out. Videos are PUBLIC BY DEFAULT; an entry's publish_at schedules it (a "
        "default visibility never applies to a scheduled entry). Videos upload one at a "
        "time in list order, with a random 1-10 minute pause between uploads; an invalid or "
        "failed entry is skipped and the rest carry on. If a channel needs signing in, a "
        "browser window opens on the owner's machine and the job waits. Follow the job "
        "with get_yt_upload_status. To retry a finished job's failed or interrupted "
        "entries, pass only resume_job_id."
    ),
)
def upload_yt_series(
    videos: list[dict] | None = None,
    defaults: dict | None = None,
    resume_job_id: str | None = None,
) -> str:
    """
    Upload several videos as one job.

    Args:
        videos: Ordered list of entries, each with upload_yt_video's fields.
        defaults: Fields applied to every entry that leaves them out.
        resume_job_id: Re-run a finished job's failed/interrupted entries (alone).
    """
    logger.info(f"MCP tool called: upload_yt_series with {len(videos or [])} videos, resume={resume_job_id}")
    try:
        if resume_job_id and (videos or defaults):
            return "Pass either resume_job_id alone, or videos (and defaults) — not both."
        runner = service.get_runner()
        now = datetime.now(timezone.utc)
        if resume_job_id:
            try:
                job = runner.resume(resume_job_id)
            except KeyError:
                return f"No upload job with id '{resume_job_id}'."
            return f"Resumed upload job {job.job_id}.\n\n{format_status(job, now)}"
        if not videos:
            return "Nothing to upload: pass videos, a list of entries."
        job = new_job("series", [v if isinstance(v, dict) else {} for v in videos], defaults, now)
        rejected = []
        seen: dict[str, int] = {}
        for entry, raw in zip(job.entries, videos):
            entry.problems = _entry_problems(entry, raw, job.defaults, runner, now, seen)
            if entry.problems:
                entry.state = "failed"
                rejected.append(f"- Entry {entry.index + 1} failed validation: {'; '.join(entry.problems)}")
        runner.submit(job)
        waiting = sum(e.state == "waiting" for e in job.entries)
        lines = [
            f"Started upload job {job.job_id}: {waiting} of {len(job.entries)} videos will upload, "
            "one at a time with 1-10 minute pauses. Follow it with get_yt_upload_status."
        ]
        lines += rejected
        return "\n".join(lines)
    except ConfigError as e:
        return f"Upload tools are not configured: {e}"
    except Exception as e:
        logger.error(f"Error in upload_yt_series: {e}", exc_info=True)
        return f"Error starting upload job: {e}"


def _entry_problems(entry, raw, defaults, runner, now, seen: dict[str, int]) -> list[str]:
    """Why this entry cannot upload, or [] (recording its file key); one bad entry never
    stops the others."""
    if not isinstance(raw, dict):
        return ["entry must be an object with upload fields (folder, title, ...)"]
    try:
        result = build_spec(entry.params, defaults, runner.config, now)
        if result.spec is None:
            return result.problems
        key = JobRunner.file_key(result.spec)
    except Exception as e:
        return [f"could not read this entry's files: {e}"]
    marker = repr(key)
    if marker in seen:
        return [f"same video and channel as entry {seen[marker] + 1} in this batch"]
    if duplicate := runner.find_duplicate(result.spec):
        return [f"already in upload job {duplicate} (same file and channel within 24 hours)"]
    seen[marker] = entry.index
    entry.file_key = key
    return []
