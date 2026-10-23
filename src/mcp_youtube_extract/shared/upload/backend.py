"""What an upload backend promises: a session per channel, and one upload at a time.

The Studio browser backend implements this now; a YouTube Data API backend can
implement the same protocol once the API project passes its audit.
"""

from dataclasses import dataclass, field
from typing import Callable, Literal, Protocol

from .config import Channel
from .spec import UploadSpec

OutcomeStatus = Literal["done", "needs_attention", "failed"]


@dataclass
class UploadOutcome:
    """done: uploaded as asked. needs_attention: the video exists on the channel but
    something did not apply. failed: nothing was created on the channel."""

    status: OutcomeStatus
    video_id: str | None = None
    watch_url: str | None = None
    studio_url: str | None = None
    is_short: bool | None = None
    applied: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


def failure_outcome(video_id: str | None, reason: str, evidence: list[str]) -> UploadOutcome:
    """Once Studio has assigned a video id, a failure is never 'failed' — a retry
    would upload a duplicate."""
    status: OutcomeStatus = "needs_attention" if video_id else "failed"
    return UploadOutcome(status=status, video_id=video_id, problems=[reason], evidence=list(evidence))


class Backend(Protocol):
    def ensure_session(self, channel: Channel, on_state: Callable[[str, str | None], None]) -> str | None:
        """None when the channel's session is ready, else the reason it is not."""

    def upload(self, spec: UploadSpec) -> UploadOutcome: ...
