"""Unit tests for the single-worker upload job runner, using a fake backend."""

import itertools
import random
import threading
from datetime import datetime, timedelta, timezone

import pytest

from mcp_youtube_extract.shared.upload.backend import UploadOutcome
from mcp_youtube_extract.shared.upload.jobs import JobStore, new_job
from mcp_youtube_extract.shared.upload.runner import JobRunner
from mcp_youtube_extract.shared.upload.spec import build_spec

from .conftest import make_folder

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.t = NOW

    def now(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class FakeBackend:
    def __init__(self, clock, outcomes, session_reasons=None, sign_in_hold=False, block_first=False, upload_takes=None):
        self.clock = clock
        self.outcomes = list(outcomes)
        self.session_reasons = list(session_reasons or [])
        self.sign_in_hold = sign_in_hold
        self.block_first = block_first
        self.upload_takes = upload_takes
        self.titles = []
        self.started, self.release, self.in_sign_in = threading.Event(), threading.Event(), threading.Event()

    def ensure_session(self, channel, on_state):
        if self.sign_in_hold:
            on_state("waiting_for_sign_in", "A Brave window has opened")
            self.in_sign_in.set()
            self.release.wait(5)
        return self.session_reasons.pop(0) if self.session_reasons else None

    def upload(self, spec):
        self.titles.append(spec.title)
        if self.block_first and len(self.titles) == 1:
            self.started.set()
            self.release.wait(5)
        if self.upload_takes:
            self.clock.advance(**self.upload_takes)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        n = len(self.titles)
        if outcome == "done":
            return UploadOutcome(status="done", video_id=f"vid{n}", watch_url=f"https://youtu.be/vid{n}")
        return UploadOutcome(status=outcome, problems=["scripted failure"])


class Harness:
    _jobs = itertools.count()

    def __init__(self, tmp_path, cfg, **backend_kw):
        self.tmp_path, self.cfg = tmp_path, cfg
        self.clock = Clock()
        self.pauses = []
        self.backend = FakeBackend(self.clock, **backend_kw)
        self.store = JobStore(tmp_path / "jobs")
        self.runner = JobRunner(self.store, self.backend, cfg, rng=random.Random(7),
                                pause=self._pause, now=self.clock.now)

    def _pause(self, seconds):
        self.pauses.append(seconds)
        self.clock.advance(seconds=seconds)

    def entries(self, n, invalid=(), publish_at=None):
        k = next(self._jobs)
        params = []
        for i in range(n):
            if i in invalid:
                params.append({"folder": "relative"})
                continue
            d = make_folder(self.tmp_path, name=f"j{k}-{i}", files={"v.mp4": b"x", "title.txt": f"j{k}-{i}"})
            p = {"folder": str(d)}
            if publish_at is not None:
                p["publish_at"] = publish_at.isoformat()
            params.append(p)
        return params

    def submit_series(self, n, **kw):
        job = new_job("series", self.entries(n, **kw), None, self.clock.now())
        self.runner.submit(job)
        return job

    @property
    def uploaded(self):
        return [int(t.split("-")[1]) for t in self.backend.titles]


@pytest.fixture
def harness(tmp_path, cfg):
    return lambda **kw: Harness(tmp_path, cfg, **kw)


def test_sequential_skip_and_continue(harness):
    h = harness(outcomes=["done", "failed", "done"])
    final = h.runner.wait(h.submit_series(3).job_id, 5)
    assert [e.state for e in final.entries] == ["done", "failed", "done"] and final.state == "finished"
    assert h.uploaded == [0, 1, 2]


def test_gaps_between_attempts_only(harness):
    h = harness(outcomes=["done", "done"])
    h.runner.wait(h.submit_series(4, invalid={0, 2}).job_id, 5)
    assert len(h.pauses) == 1 and 60 <= h.pauses[0] <= 600


def test_gap_count_for_three_attempts(harness):
    h = harness(outcomes=["done", "failed", "done"])
    h.runner.wait(h.submit_series(3).job_id, 5)
    assert len(h.pauses) == 2 and all(60 <= p <= 600 for p in h.pauses)


def test_publish_at_rechecked_before_upload(harness):
    # Entry 2 is still in the future when its turn comes, but the gap pushes it past.
    h = harness(outcomes=["done", "done"], upload_takes={"minutes": 1})
    params = h.entries(1) + h.entries(1, publish_at=NOW + timedelta(seconds=90))
    job = new_job("series", params, None, NOW)
    h.runner.submit(job)
    final = h.runner.wait(job.job_id, 5)
    assert final.entries[1].state == "failed" and "past" in final.entries[1].problems[0]
    assert len(h.backend.titles) == 1


def test_session_failure_fails_entry_and_continues(harness):
    h = harness(outcomes=["done"], session_reasons=["sign-in not completed within 10 minutes", None])
    final = h.runner.wait(h.submit_series(2).job_id, 5)
    assert [e.state for e in final.entries] == ["failed", "done"]
    assert "sign-in not completed" in final.entries[0].problems[0]


def test_waiting_for_sign_in_is_reported(harness):
    h = harness(outcomes=["done"], sign_in_hold=True)
    job = h.submit_series(1)
    assert h.backend.in_sign_in.wait(5)
    assert h.runner.get(job.job_id).state == "waiting_for_sign_in"
    h.backend.release.set()
    assert h.runner.wait(job.job_id, 5).state == "finished"


def test_one_upload_at_a_time_fifo(harness):
    h = harness(outcomes=["done"] * 3, block_first=True)
    a = h.submit_series(2)
    b = h.submit_series(1)
    assert h.backend.started.wait(5)
    assert h.runner.get(b.job_id).state == "queued"
    h.backend.release.set()
    assert h.runner.wait(b.job_id, 5).finished
    assert [t.split("-")[0] for t in h.backend.titles] == [h.backend.titles[0].split("-")[0]] * 2 + [h.backend.titles[2].split("-")[0]]
    assert h.runner.get(a.job_id).finished


def test_wait_times_out_with_unfinished_job(harness):
    h = harness(outcomes=["done"], block_first=True)
    job = h.submit_series(1)
    assert not h.runner.wait(job.job_id, 0.2).finished
    h.backend.release.set()
    assert h.runner.wait(job.job_id, 5).finished


def test_backend_exception_becomes_failed_entry(harness):
    h = harness(outcomes=[RuntimeError("selector vanished"), "done"])
    final = h.runner.wait(h.submit_series(2).job_id, 5)
    assert final.entries[0].state == "failed" and "selector vanished" in final.entries[0].problems[0]
    assert final.entries[1].state == "done"


def test_resume_retries_only_unfinished_without_video_id(harness):
    h = harness(outcomes=["done", "done"])
    job = new_job("series", h.entries(5), None, NOW)
    for entry, (state, vid) in zip(job.entries, [("done", "a"), ("failed", None), ("interrupted", "b"),
                                                ("interrupted", None), ("needs_attention", "c")]):
        entry.state, entry.video_id = state, vid
    job.state = "interrupted"
    h.store.save(job)
    final = h.runner.wait(h.runner.resume(job.job_id).job_id, 5)
    assert h.uploaded == [1, 3]
    assert [e.state for e in final.entries] == ["done", "done", "interrupted", "done", "needs_attention"]


def test_find_duplicate(harness):
    h = harness(outcomes=["done"])
    job = h.submit_series(1)
    h.runner.wait(job.job_id, 5)
    spec = build_spec(job.entries[0].params, None, h.cfg, h.clock.now()).spec
    assert h.runner.find_duplicate(spec) == job.job_id


def test_failed_entries_are_not_duplicates(harness):
    h = harness(outcomes=["failed"])
    job = h.submit_series(1)
    h.runner.wait(job.job_id, 5)
    spec = build_spec(job.entries[0].params, None, h.cfg, h.clock.now()).spec
    assert h.runner.find_duplicate(spec) is None
