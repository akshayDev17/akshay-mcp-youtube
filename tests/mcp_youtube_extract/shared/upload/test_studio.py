"""Unit tests for the Studio backend's pure parts: links, failure evidence, media probing."""

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from mcp_youtube_extract.shared.upload.media import probe_video
from mcp_youtube_extract.shared.upload.studio import parse_video_link, save_evidence


@pytest.mark.parametrize("href, vid, short", [
    ("https://youtube.com/shorts/pRdqMdicoEU", "pRdqMdicoEU", True),
    ("https://youtu.be/L-r3uBBHZQQ", "L-r3uBBHZQQ", False),
    ("https://www.youtube.com/watch?v=L-r3uBBHZQQ&t=1", "L-r3uBBHZQQ", False),
])
def test_parse_video_link(href, vid, short):
    assert parse_video_link(href) == (vid, short)


def test_parse_video_link_rejects_other_urls():
    with pytest.raises(ValueError):
        parse_video_link("https://studio.youtube.com/channel/UC/videos")


class FakePage:
    def __init__(self, text):
        self.text = text

    def screenshot(self, path):
        Path(path).write_bytes(b"png")

    def evaluate(self, script):
        return self.text


def test_save_evidence(tmp_path):
    paths = save_evidence(FakePage("Something went wrong"), tmp_path, "set title", datetime(2026, 10, 23, 11, 5, 9))
    assert [Path(p).name for p in paths] == ["20261023-110509-set-title.png", "20261023-110509-set-title.txt"]
    assert "Something went wrong" in Path(paths[1]).read_text()


def test_save_evidence_survives_a_dead_page(tmp_path):
    class Dead:
        def screenshot(self, path):
            raise RuntimeError("target closed")

        def evaluate(self, script):
            raise RuntimeError("target closed")

    paths = save_evidence(Dead(), tmp_path, "read link", datetime(2026, 10, 23, 11, 5, 9))
    assert [Path(p).suffix for p in paths] == [".txt"]
    assert "target closed" in Path(paths[0]).read_text()


def make_clip(tmp_path, width, height, seconds):
    clip = tmp_path / f"clip-{width}x{height}.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size={width}x{height}:rate=30",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)],
        check=True,
    )
    return clip


@pytest.mark.skipif(shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_probe_video_vertical(tmp_path):
    info = probe_video(make_clip(tmp_path, 1080, 1920, seconds=2))
    assert (info["width"], info["height"], info["orientation"]) == (1080, 1920, "vertical")
    assert 1.5 < info["duration_s"] < 2.5


def test_probe_video_without_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert probe_video(tmp_path / "x.mp4") is None
