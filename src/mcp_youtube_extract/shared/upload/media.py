"""Read a video file's shape and length with ffprobe, when it is installed."""

import json
import shutil
import subprocess
from pathlib import Path


def probe_video(path: Path) -> dict | None:
    """{"width", "height", "duration_s", "orientation"}, or None without ffprobe or on error."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout
        data = json.loads(out)
        stream = data["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        duration = float(data["format"]["duration"])
    except (subprocess.SubprocessError, OSError, KeyError, IndexError, ValueError):
        return None
    orientation = "square" if width == height else ("vertical" if height > width else "horizontal")
    return {"width": width, "height": height, "duration_s": duration, "orientation": orientation}


def describe(info: dict) -> str:
    minutes, seconds = divmod(round(info["duration_s"]), 60)
    return f"file: {info['width']}x{info['height']} ({info['orientation']}), {minutes}:{seconds:02d}"
