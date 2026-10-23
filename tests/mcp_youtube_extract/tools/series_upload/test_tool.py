"""Tests for the upload_yt_series tool over a fake backend."""

import asyncio
import re

from mcp_youtube_extract._app import app
from mcp_youtube_extract.shared.upload import service
from mcp_youtube_extract.tools.series_upload.tool import upload_yt_series
from mcp_youtube_extract.tools.video_upload import tool as _video_tool  # noqa: F401  (registers it)


def test_series_skips_invalid_entries(fake_service, folders):
    out = upload_yt_series(videos=[{"folder": str(folders[0])}, {"folder": "relative"}, {"folder": str(folders[1])}])
    job_id = re.search(r"\b[0-9a-f]{12}\b", out).group(0)
    assert "Entry 2" in out and "absolute path" in out
    final = service.get_runner().wait(job_id, 5)
    assert [e.state for e in final.entries] == ["done", "failed", "done"]


def test_series_resume_conflicts_with_videos(fake_service):
    assert "either" in upload_yt_series(videos=[{"folder": "/a"}], resume_job_id="0123456789ab").lower()


def test_series_needs_videos(fake_service):
    assert "videos" in upload_yt_series()


def test_descriptions_state_public_default():
    tools = {t.name: t for t in asyncio.run(app.list_tools())}
    for name in ("upload_yt_video", "upload_yt_series"):
        assert "public by default" in tools[name].description.lower()
