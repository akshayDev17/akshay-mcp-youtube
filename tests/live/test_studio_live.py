"""Live tests against YouTube Studio. They need a signed-in channel profile and the
YT_UPLOAD_* environment, and run only with YT_UPLOAD_LIVE_TESTS=1. Uploads are private
(unlisted where visibility itself is under test); each prints the video id to delete."""

import os

import pytest

from mcp_youtube_extract.shared.upload.config import load_config
from mcp_youtube_extract.shared.upload.session import check_session

pytestmark = pytest.mark.skipif(os.environ.get("YT_UPLOAD_LIVE_TESTS") != "1", reason="live Studio tests")


def test_live_session_check_main():
    cfg = load_config()
    channel = cfg.resolve_channel(None)
    assert check_session(channel, cfg).kind == "ok"


def make_clip(tmp_path, width, height, seconds):
    import subprocess

    clip = tmp_path / f"clip-{width}x{height}.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size={width}x{height}:rate=30",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)],
        check=True,
    )
    return clip


def upload_live(tmp_path, **fields):
    from mcp_youtube_extract.shared.upload.spec import UploadSpec
    from mcp_youtube_extract.shared.upload.studio import StudioBackend

    cfg = load_config()
    spec = UploadSpec(channel=cfg.resolve_channel(None), **fields)
    outcome = StudioBackend(cfg).upload(spec)
    print(f"\nLIVE UPLOAD {outcome.status}: video id {outcome.video_id} — delete it in Studio. {outcome.problems} {outcome.evidence}")
    return outcome


def test_live_private_short_upload(tmp_path):
    clip = make_clip(tmp_path, 1080, 1920, seconds=5)
    outcome = upload_live(tmp_path, video_path=clip, title="live test private short", visibility="private")
    assert outcome.status == "done" and outcome.is_short is True


def make_thumbnail(tmp_path):
    import subprocess

    png = tmp_path / "thumbnail.png"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc=size=1280x720:rate=1", "-frames:v", "1", str(png)], check=True)
    return png


def test_live_private_full_fields(tmp_path):
    clip = make_clip(tmp_path, 1280, 720, seconds=5)
    srt = tmp_path / "captions.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:04,000\nHello from the live test.\n")
    outcome = upload_live(
        tmp_path, video_path=clip, title="live test full fields", visibility="private",
        description="Line one of the description.\n\n0:00 Start\n0:02 Middle\n",
        captions_path=srt, thumbnail_path=make_thumbnail(tmp_path),
    )
    assert outcome.status == "done" and outcome.is_short is False


def test_live_unlisted(tmp_path):
    outcome = upload_live(tmp_path, video_path=make_clip(tmp_path, 1280, 720, seconds=3),
                          title="live test unlisted", visibility="unlisted")
    assert outcome.status == "done"


def test_live_scheduled_odd_minute(tmp_path):
    from datetime import datetime, timedelta, timezone

    when = (datetime.now(timezone.utc) + timedelta(days=30)).replace(minute=7, second=0, microsecond=0)
    outcome = upload_live(tmp_path, video_path=make_clip(tmp_path, 1280, 720, seconds=3),
                          title="live test scheduled", visibility=None, publish_at=when)
    assert outcome.status == "done", outcome.problems
