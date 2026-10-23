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
