"""Upload jobs: one or more entries, persisted as JSON so status survives a restart."""

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from .backend import UploadOutcome

EntryState = Literal["waiting", "uploading", "done", "needs_attention", "failed", "interrupted"]
JobState = Literal["queued", "running", "waiting_for_sign_in", "pausing", "finished", "interrupted"]

_UNFINISHED_JOB = ("queued", "running", "waiting_for_sign_in", "pausing")


@dataclass
class Entry:
    index: int
    params: dict[str, Any]
    state: EntryState = "waiting"
    file_key: list | None = None
    video_id: str | None = None
    watch_url: str | None = None
    studio_url: str | None = None
    is_short: bool | None = None
    applied: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def apply(self, outcome: UploadOutcome) -> None:
        self.state = outcome.status
        self.video_id = outcome.video_id or self.video_id
        self.watch_url = outcome.watch_url
        self.studio_url = outcome.studio_url
        self.is_short = outcome.is_short
        self.applied = dict(outcome.applied)
        self.problems = list(outcome.problems)
        self.warnings = self.warnings + [w for w in outcome.warnings if w not in self.warnings]
        self.evidence = list(outcome.evidence)


@dataclass
class Job:
    job_id: str
    kind: Literal["video", "series"]
    created_at: datetime
    state: JobState
    entries: list[Entry]
    defaults: dict[str, Any]
    pause_until: datetime | None = None
    message: str | None = None

    @property
    def finished(self) -> bool:
        return self.state in ("finished", "interrupted")


def new_job(kind, entries_params: list[dict], defaults: dict | None, now: datetime) -> Job:
    return Job(
        job_id=uuid.uuid4().hex[:12],
        kind=kind,
        created_at=now,
        state="queued",
        entries=[Entry(index=i, params=dict(p)) for i, p in enumerate(entries_params)],
        defaults=dict(defaults or {}),
    )


def _to_json(job: Job) -> dict:
    data = asdict(job)
    data["created_at"] = job.created_at.isoformat()
    data["pause_until"] = job.pause_until.isoformat() if job.pause_until else None
    return data


def _from_json(data: dict) -> Job:
    data = dict(data)
    data["created_at"] = datetime.fromisoformat(data["created_at"])
    data["pause_until"] = datetime.fromisoformat(data["pause_until"]) if data.get("pause_until") else None
    data["entries"] = [Entry(**e) for e in data["entries"]]
    return Job(**data)


class JobStore:
    def __init__(self, jobs_dir: Path):
        self.jobs_dir = Path(jobs_dir)

    def _path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def save(self, job: Job) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path(job.job_id).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_to_json(job), indent=2), encoding="utf-8")
        os.replace(tmp, self._path(job.job_id))

    def load(self, job_id: str) -> Job:
        path = self._path(job_id)
        if not path.is_file():
            raise KeyError(job_id)
        return _from_json(json.loads(path.read_text(encoding="utf-8")))

    def all(self) -> list[Job]:
        if not self.jobs_dir.is_dir():
            return []
        return [self.load(p.stem) for p in sorted(self.jobs_dir.glob("*.json"))]

    def recent(self, since: datetime) -> list[Job]:
        return [job for job in self.all() if job.created_at >= since]

    def mark_interrupted_on_startup(self) -> list[str]:
        """Jobs left unfinished by a previous server process: they can no longer run."""
        marked = []
        for job in self.all():
            if job.state not in _UNFINISHED_JOB:
                continue
            for entry in job.entries:
                if entry.state in ("waiting", "uploading"):
                    entry.state = "interrupted"
            job.state = "interrupted"
            job.message = "the server stopped before this job finished; resume it with resume_job_id"
            self.save(job)
            marked.append(job.job_id)
        return marked


def _local(moment: datetime) -> str:
    return moment.astimezone().strftime("%H:%M")


def _entry_label(entry: Entry) -> str:
    source = entry.params.get("folder") or entry.params.get("video_path") or "?"
    return Path(str(source)).name or str(source)


def _entry_lines(entry: Entry) -> list[str]:
    lines = [f"- Entry {entry.index + 1} ({_entry_label(entry)}): {entry.state}"]
    if entry.watch_url:
        lines.append(f"  watch: {entry.watch_url}")
    if entry.studio_url:
        lines.append(f"  studio: {entry.studio_url}")
    if entry.video_id and not entry.watch_url:
        lines.append(f"  video id: {entry.video_id}")
    if entry.is_short is not None:
        lines.append(f"  short: {'yes' if entry.is_short else 'no'}")
    lines += [f"  {key}: {value}" for key, value in entry.applied.items()]
    lines += [f"  problem: {p}" for p in entry.problems]
    lines += [f"  warning: {w}" for w in entry.warnings]
    lines += [f"  evidence: {e}" for e in entry.evidence]
    return lines


def format_status(job: Job, now: datetime) -> str:
    state = job.state.replace("_", " ")
    if job.state == "pausing" and job.pause_until:
        state = f"pausing until {_local(job.pause_until)} before the next upload"
    lines = [f"Upload job {job.job_id} ({job.kind}): {state}"]
    if job.message:
        lines.append(job.message)
    counts: dict[str, int] = {}
    for entry in job.entries:
        counts[entry.state] = counts.get(entry.state, 0) + 1
    lines.append("Totals: " + ", ".join(f"{n} {s}" for s, n in counts.items()))
    for entry in job.entries:
        lines += _entry_lines(entry)
    if job.finished:
        not_done = [e for e in job.entries if e.state != "done"]
        if not_done:
            lines.append("Not done:")
            for entry in not_done:
                reason = "; ".join(entry.problems) or entry.state
                lines.append(f"- Entry {entry.index + 1} ({_entry_label(entry)}): {entry.state} — {reason}")
    return "\n".join(lines)
