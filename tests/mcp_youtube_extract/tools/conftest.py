"""Shared fixtures for the upload tools: a real JobRunner over a fake backend."""

import dataclasses

import pytest

from mcp_youtube_extract.shared.upload import service
from mcp_youtube_extract.shared.upload.backend import UploadOutcome
from mcp_youtube_extract.shared.upload.config import load_config
from mcp_youtube_extract.shared.upload.jobs import JobStore
from mcp_youtube_extract.shared.upload.runner import JobRunner

MAIN = "UCDzx6hNPpuha4fCwYA5WAyg"


class FakeBackend:
    def __init__(self):
        self.uploaded = []
        self.block_first = False
        import threading
        self.release = threading.Event()

    def ensure_session(self, channel, on_state):
        return None

    def upload(self, spec, on_video_id=None):
        self.uploaded.append(spec.title)
        if self.block_first and len(self.uploaded) == 1:
            self.release.wait(5)
        n = len(self.uploaded)
        return UploadOutcome(status="done", video_id=f"vid{n:08d}", watch_url=f"https://youtu.be/vid{n:08d}",
                             is_short=False, applied={"visibility": spec.visibility or "scheduled"})


class FakeService:
    def __init__(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YT_UPLOAD_CHANNELS", f"main={MAIN}")
        monkeypatch.setattr(service, "HOME", tmp_path / "home")
        self.cfg = load_config(home=tmp_path / "home")
        self.backend = FakeBackend()
        self.store = JobStore(self.cfg.jobs_dir)
        self.runner = JobRunner(self.store, self.backend, self.cfg, pause=lambda s: None)
        service._reset_for_tests(runner=self.runner, store=self.store)

    def call_wait(self, seconds):
        self.runner.config = dataclasses.replace(self.cfg, call_wait_s=seconds)


@pytest.fixture
def fake_service(tmp_path, monkeypatch):
    fake = FakeService(tmp_path, monkeypatch)
    yield fake
    fake.backend.release.set()
    service._reset_for_tests()


def make_video_folder(base, name):
    folder = base / name
    folder.mkdir(parents=True)
    (folder / "v.mp4").write_bytes(name.encode())
    (folder / "title.txt").write_text(f"Title {name}")
    return folder


@pytest.fixture
def folder(tmp_path):
    return make_video_folder(tmp_path, "01-intro")


@pytest.fixture
def folders(tmp_path):
    return [make_video_folder(tmp_path, f"0{i}-part") for i in (1, 2)]
