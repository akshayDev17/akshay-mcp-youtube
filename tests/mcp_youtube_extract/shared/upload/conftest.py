"""Shared fixtures for upload tests."""

import pytest

from mcp_youtube_extract.shared.upload.config import load_config

MAIN = "UCDzx6hNPpuha4fCwYA5WAyg"
SECOND = "UC" + "a" * 22


def make_folder(base, name="01-intro — RAG", files=None):
    """Create base/name holding files ({filename: str | bytes})."""
    folder = base / name
    folder.mkdir(parents=True, exist_ok=True)
    for filename, content in (files or {}).items():
        path = folder / filename
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return folder


@pytest.fixture
def cfg(tmp_path):
    return load_config({"YT_UPLOAD_CHANNELS": f"main={MAIN},second={SECOND}"}, home=tmp_path / "home")
