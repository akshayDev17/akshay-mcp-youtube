"""Tests for server wiring: tool registration, instructions and the --login flag."""

import asyncio

import pytest

from mcp_youtube_extract import server
from mcp_youtube_extract._app import app


def test_tools_registered():
    names = {t.name for t in asyncio.run(app.list_tools())}
    assert {"upload_yt_video", "upload_yt_series", "get_yt_upload_status"} <= names


def test_login_flag_dispatches(monkeypatch):
    seen = []
    monkeypatch.setattr(server, "run_cli_login", lambda name: seen.append(name) or 0)
    with pytest.raises(SystemExit) as e:
        server.main(["--login", "main"])
    assert seen == ["main"] and e.value.code == 0


def test_instructions_mention_uploads():
    assert "upload" in app.instructions.lower() and "public by default" in app.instructions.lower()


def test_cli_login_reports_config_error(monkeypatch, capsys, tmp_path):
    from mcp_youtube_extract.shared.upload import service

    monkeypatch.setattr(service, "HOME", tmp_path)
    monkeypatch.delenv("YT_UPLOAD_CHANNELS", raising=False)
    assert server.run_cli_login("main") == 1
    assert "YT_UPLOAD_CHANNELS" in capsys.readouterr().out
