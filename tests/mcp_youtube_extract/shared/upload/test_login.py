"""Unit tests for the server-run sign-in flow, with a fake browser process and clock."""

import sqlite3

import pytest

from mcp_youtube_extract.shared.upload.config import load_config
from mcp_youtube_extract.shared.upload.session import (
    LOGIN_URL,
    SessionCheck,
    ensure_session,
    login_command,
    login_cookies_present,
    run_login_flow,
)

from .conftest import MAIN


def chromium_us(unix_s):
    return int((unix_s + 11644473600) * 1_000_000)


def make_cookie_db(path, rows, columns=("host_key", "name", "creation_utc", "last_update_utc")):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(f"CREATE TABLE cookies ({', '.join(columns)})")
    con.executemany(f"INSERT INTO cookies VALUES ({', '.join('?' for _ in columns)})", rows)
    con.commit()
    con.close()


def test_cookies_present_requires_both_fresh(tmp_path):
    since = 1_800_000_000
    make_cookie_db(tmp_path / "Default" / "Cookies", [
        (".youtube.com", "LOGIN_INFO", chromium_us(since + 5), 0),
        (".youtube.com", "SAPISID", chromium_us(since - 5), chromium_us(since + 9)),
    ])
    assert login_cookies_present(tmp_path, since)
    assert not login_cookies_present(tmp_path, since + 60)


def test_cookies_network_path_and_creation_only_schema(tmp_path):
    make_cookie_db(tmp_path / "Default" / "Network" / "Cookies", [
        (".youtube.com", "LOGIN_INFO", chromium_us(10)),
        (".youtube.com", "SAPISID", chromium_us(10)),
    ], columns=("host_key", "name", "creation_utc"))
    assert login_cookies_present(tmp_path, 5)


def test_cookies_absent_when_no_database_or_google_only(tmp_path):
    assert not login_cookies_present(tmp_path, 0)
    make_cookie_db(tmp_path / "Default" / "Cookies", [
        (".google.com", "LOGIN_INFO", chromium_us(10), 0),
        (".google.com", "SAPISID", chromium_us(10), 0),
    ])
    assert not login_cookies_present(tmp_path, 5)


def test_login_command(cfg):
    cmd = login_command(cfg.resolve_channel("main"), cfg)
    assert cmd[0] == str(cfg.browser_path) and cmd[-1] == LOGIN_URL and "--no-first-run" in cmd
    assert f"--user-data-dir={cfg.resolve_channel('main').profile_dir}" in cmd


class FakeProc:
    def __init__(self, exit_after):
        self.exit_after, self.polls, self.terminated, self.killed = exit_after, 0, False, False

    def poll(self):
        self.polls += 1
        if self.terminated or (self.exit_after is not None and self.polls > self.exit_after):
            return 0
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class Fakes:
    def __init__(self, tmp_path):
        self.cfg = load_config({"YT_UPLOAD_CHANNELS": f"main={MAIN}"}, home=tmp_path / "home")
        self.channel = self.cfg.resolve_channel("main")
        self.states, self.procs, self.t = [], [], 0.0

    def cfg_timeout(self, seconds):
        return load_config({"YT_UPLOAD_CHANNELS": f"main={MAIN}", "YT_UPLOAD_LOGIN_TIMEOUT": str(seconds)},
                           home=self.cfg.home)

    def on_state(self, state, message):
        self.states.append((state, message))

    def inject(self, cookies_after=None, exit_after=None, checks=(), in_use_polls=0):
        checks = list(checks)
        busy = {"left": in_use_polls}

        def launch(cmd):
            proc = FakeProc(exit_after)
            proc.cookie_polls = 0
            self.procs.append(proc)
            return proc

        def cookies_present(profile_dir, since):
            proc = self.procs[-1]
            proc.cookie_polls += 1
            return cookies_after is not None and proc.cookie_polls >= cookies_after

        def check(channel, config):
            kind = checks.pop(0)
            other = "UCbbbbbbbbbbbbbbbbbbbbbb" if kind == "wrong_channel" else None
            return SessionCheck(kind, other or (MAIN if kind == "ok" else None), "")

        def sleep(seconds):
            self.t += seconds

        def in_use(path):
            if busy["left"]:
                busy["left"] -= 1
                return True
            return False

        return dict(launch=launch, cookies_present=cookies_present, check=check,
                    clock=lambda: self.t, sleep=sleep, in_use=in_use)


@pytest.fixture
def fakes(tmp_path):
    return Fakes(tmp_path)


def test_flow_success_closes_window_itself(fakes):
    reason = run_login_flow(fakes.channel, fakes.cfg, fakes.on_state, **fakes.inject(cookies_after=3, checks=["ok"]))
    assert reason is None and fakes.procs[0].terminated
    assert fakes.states[0][0] == "waiting_for_sign_in" and "'main'" in fakes.states[0][1]


def test_flow_window_closed_early(fakes):
    assert "closed" in run_login_flow(fakes.channel, fakes.cfg, fakes.on_state, **fakes.inject(exit_after=2))


def test_flow_timeout(fakes):
    reason = run_login_flow(fakes.channel, fakes.cfg_timeout(60), fakes.on_state, **fakes.inject())
    assert reason == "sign-in not completed within 1 minute" and fakes.procs[0].terminated


def test_flow_wrong_channel_relaunches(fakes):
    reason = run_login_flow(fakes.channel, fakes.cfg, fakes.on_state,
                            **fakes.inject(cookies_after=1, checks=["wrong_channel", "ok"]))
    assert reason is None and len(fakes.procs) == 2
    assert f"switch to {MAIN}" in fakes.states[-1][1]


def test_ensure_session_ok_launches_nothing(fakes):
    assert ensure_session(fakes.channel, fakes.cfg, fakes.on_state, **fakes.inject(checks=["ok"])) is None
    assert fakes.procs == []


def test_ensure_session_not_logged_in_runs_flow(fakes):
    reason = ensure_session(fakes.channel, fakes.cfg, fakes.on_state,
                            **fakes.inject(cookies_after=1, checks=["not_logged_in", "ok"]))
    assert reason is None and len(fakes.procs) == 1


def test_ensure_session_waits_for_profile_in_use(fakes):
    reason = ensure_session(fakes.channel, fakes.cfg, fakes.on_state,
                            **fakes.inject(checks=["in_use", "ok"]))
    assert reason is None and fakes.procs == []


def test_ensure_session_in_use_times_out(fakes):
    checks = ["in_use"] * 1000
    reason = ensure_session(fakes.channel, fakes.cfg_timeout(10), fakes.on_state, **fakes.inject(checks=checks))
    assert "in use" in reason
