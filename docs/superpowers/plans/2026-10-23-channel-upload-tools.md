# Channel Upload Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `upload_yt_video`, `upload_yt_series` and `get_yt_upload_status` to the `mcp_youtube_extract` server, uploading to one or more configured channels through YouTube Studio's upload dialog in a dedicated, logged-in Brave profile per channel.

**Architecture:** Pure modules (config, spec resolution/validation, job model) feed a single-worker job runner that calls a `Backend` protocol. The only backend now is `StudioBackend` (Playwright driving the installed Brave on a per-channel persistent profile); a Data API backend can implement the same protocol later. Tools are thin: build specs, submit jobs, format results.

**Tech Stack:** Python 3.13, `mcp>=2.0.0` (`MCPServer`), `playwright` (Python, no bundled browser download), stdlib `sqlite3`, `threading`, `zoneinfo`; pytest.

**Spec:** `docs/superpowers/specs/2026-10-23-channel-upload-tools-design.md` (layout refinements here: `config.py` replaces the spec's `channels.py` and also holds the other settings; `runner.py`, `media.py` and `service.py` are added.)

## Global Constraints

- Defaults: `visibility` **public**, `language` `en`, `audio_language`/`captions_language` = `language`, `made_for_kids` `false`. Every tool description states "public by default" plainly.
- A `visibility` from batch `defaults` or the built-in default never applies to an entry with `publish_at`; only an entry's own `visibility` conflicts with its `publish_at`.
- Title 1–100 characters, no `<` or `>`. Description ≤ 5000 characters, no `<` or `>`. Thumbnail PNG or JPG, ≤ 2 MB (2 097 152 bytes). Captions `.srt` only.
- `publish_at`: ISO 8601 **with** UTC offset, in the future when checked; re-checked just before each upload.
- Batch: skip invalid/failed entries and continue; report every non-`done` entry at the end. One upload at a time **server-wide**. Random gap `uniform(60, 600)` seconds between consecutive upload attempts in a job; none before the first or after the last; sign-in time excluded.
- Outcomes: `done` / `needs_attention` (Studio assigned a video id, then something failed or read back wrong — never re-uploaded) / `failed` (nothing created).
- Duplicate guard: refuse an entry whose (channel id, real path, size, mtime_ns) matches a non-`failed` entry of a job created in the last 24 h; point at that job.
- Home `~/.mcp-youtube-extract/`: `profiles/<name>/` (mode 700), `jobs/<job_id>.json`, `failures/<YYYYmmdd-HHMMSS>-<step>.png|.txt`.
- Environment: `YT_UPLOAD_CHANNELS` (required, `name=UC…` pairs, comma-separated), `YT_UPLOAD_DEFAULT_CHANNEL` (default: first listed), `YT_UPLOAD_BROWSER` (default `/Applications/Brave Browser.app/Contents/MacOS/Brave Browser`), `YT_UPLOAD_HEADLESS` (default `true`), `YT_UPLOAD_LOGIN_TIMEOUT` (default `600`), `YT_UPLOAD_CALL_WAIT` (default `600`).
- Never read cookie values; never copy cookies out of a profile; never automate the sign-in window; never disguise automation (no user-agent or fingerprint changes).
- Playwright launches: `launch_persistent_context(profile, executable_path=<browser>, headless=…, ignore_default_args=["--use-mock-keychain"])`.
- Tool results are strings; errors are returned as strings, never raised (existing tool style). Use `get_logger(__name__)`.
- Unit tests touch no network or browser. Live tests live in `tests/live/`, skip unless `YT_UPLOAD_LIVE_TESTS=1`, upload **private** (unlisted where visibility itself is under test) and print each video id for manual deletion.
- Run tests with `uv run pytest …` from the repo root. Commit on branch `feat/channel-upload-tools`; never push.

## Review Focus

1. A caller whose `upload_yt_video` call was cut off calls again with the same folder → no second upload; the reply names the existing job (Task 11).
2. Relative paths or `~` in `folder`/`*_path` → `~` expanded; relative paths rejected with "use an absolute path" (the server's working directory is not the caller's) (Task 2).
3. `title.txt` / `description.md` written by other tools with a UTF-8 BOM or CRLF endings → BOM stripped, line endings normalised to `\n` (Task 2).
4. `YT_UPLOAD_CHANNELS` with spaces or a trailing comma → tolerated; a pair without `=` or an id not shaped `UC` + 22 characters → clear `ConfigError` at tool-call time, not a crash at import (Task 1).
5. A `publish_at` that Studio's scheduler cannot express exactly → the entry fails before upload; never rounded (Task 9).

---

## File Structure

```
src/mcp_youtube_extract/shared/upload/
  __init__.py
  config.py      env → UploadConfig, Channel; channel resolution          (Task 1)
  spec.py        UploadSpec; params+defaults+folder → spec; validation   (Tasks 2–3)
  backend.py     UploadOutcome, Backend protocol, outcome helpers        (Task 4)
  jobs.py        Job/Entry model, JobStore, status formatting            (Task 4)
  runner.py      JobRunner: queue, worker, gaps, re-checks, resume       (Task 5)
  session.py     profile launch args, session check, login flow          (Tasks 6–7)
  media.py       ffprobe orientation/duration                            (Task 8)
  studio.py      StudioBackend: dialog steps, evidence, read-back        (Tasks 8–10)
  service.py     lazily built store/runner shared by the tools           (Task 11)
src/mcp_youtube_extract/tools/video_upload/tool.py     upload_yt_video   (Task 11)
src/mcp_youtube_extract/tools/series_upload/tool.py    upload_yt_series  (Task 11)
src/mcp_youtube_extract/tools/upload_status/tool.py    get_yt_upload_status (Task 11)
src/mcp_youtube_extract/server.py, src/mcp_youtube_extract/_app.py, README.md (Task 12)
tests/mcp_youtube_extract/shared/upload/test_*.py, tests/mcp_youtube_extract/tools/*/test_*.py
tests/live/test_studio_live.py
```

Every new package and test directory gets an empty `__init__.py`, matching the existing tree.

---

### Task 1: Channel and settings configuration

**Files:**
- Create: `src/mcp_youtube_extract/shared/upload/__init__.py`, `src/mcp_youtube_extract/shared/upload/config.py`
- Test: `tests/mcp_youtube_extract/shared/upload/__init__.py`, `tests/mcp_youtube_extract/shared/upload/test_config.py`

**Interfaces:**
- Produces:
  - `class ConfigError(ValueError)`
  - `@dataclass(frozen=True) class Channel: name: str; channel_id: str; profile_dir: Path`
  - `@dataclass(frozen=True) class UploadConfig: channels: dict[str, Channel]; default_channel: str; browser_path: Path; headless: bool; login_timeout_s: int; call_wait_s: int; home: Path` with properties `jobs_dir`, `failures_dir` and `def resolve_channel(self, name_or_id: str | None) -> Channel` (None → default; matches name, then channel id; else `ConfigError`)
  - `def load_config(env: Mapping[str, str] | None = None, home: Path | None = None) -> UploadConfig` (env defaults to `os.environ`, home to `Path.home() / ".mcp-youtube-extract"`)

- [ ] **Step 1: Write the failing tests**

```python
MAIN = "UCDzx6hNPpuha4fCwYA5WAyg"
SECOND = "UC" + "a" * 22

def test_parses_channels_default_and_profiles(tmp_path):
    cfg = load_config({"YT_UPLOAD_CHANNELS": f" main={MAIN}, second={SECOND}, "}, home=tmp_path)
    assert list(cfg.channels) == ["main", "second"]
    assert cfg.default_channel == "main"
    assert cfg.channels["second"].profile_dir == tmp_path / "profiles" / "second"
    assert cfg.jobs_dir == tmp_path / "jobs" and cfg.failures_dir == tmp_path / "failures"

def test_settings_defaults(tmp_path):
    cfg = load_config({"YT_UPLOAD_CHANNELS": f"main={MAIN}"}, home=tmp_path)
    assert cfg.browser_path == Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")
    assert (cfg.headless, cfg.login_timeout_s, cfg.call_wait_s) == (True, 600, 600)

def test_settings_overrides(tmp_path):
    cfg = load_config({"YT_UPLOAD_CHANNELS": f"main={MAIN},second={SECOND}",
                       "YT_UPLOAD_DEFAULT_CHANNEL": "second", "YT_UPLOAD_HEADLESS": "false",
                       "YT_UPLOAD_LOGIN_TIMEOUT": "30", "YT_UPLOAD_CALL_WAIT": "5"}, home=tmp_path)
    assert (cfg.default_channel, cfg.headless, cfg.login_timeout_s, cfg.call_wait_s) == ("second", False, 30, 5)

def test_resolve_by_none_name_and_id(tmp_path):
    cfg = load_config({"YT_UPLOAD_CHANNELS": f"main={MAIN},second={SECOND}"}, home=tmp_path)
    assert cfg.resolve_channel(None).name == "main"
    assert cfg.resolve_channel("second").channel_id == SECOND
    assert cfg.resolve_channel(SECOND).name == "second"

@pytest.mark.parametrize("env, needle", [
    ({}, "YT_UPLOAD_CHANNELS"),
    ({"YT_UPLOAD_CHANNELS": "main"}, "main"),
    ({"YT_UPLOAD_CHANNELS": "main=notachannel"}, "notachannel"),
    ({"YT_UPLOAD_CHANNELS": f"main={MAIN},main={SECOND}"}, "main"),
    ({"YT_UPLOAD_CHANNELS": f"main={MAIN}", "YT_UPLOAD_DEFAULT_CHANNEL": "other"}, "other"),
    ({"YT_UPLOAD_CHANNELS": f"main={MAIN}", "YT_UPLOAD_LOGIN_TIMEOUT": "soon"}, "YT_UPLOAD_LOGIN_TIMEOUT"),
])
def test_bad_config_raises_with_the_culprit_named(tmp_path, env, needle):
    with pytest.raises(ConfigError, match=needle):
        load_config(env, home=tmp_path)

def test_unknown_channel(tmp_path):
    cfg = load_config({"YT_UPLOAD_CHANNELS": f"main={MAIN}"}, home=tmp_path)
    with pytest.raises(ConfigError, match="nope"):
        cfg.resolve_channel("nope")
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/mcp_youtube_extract/shared/upload/test_config.py -v` → FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implement `config.py`** — channel id must match `^UC[A-Za-z0-9_-]{22}$`; empty pairs from stray commas are skipped; booleans accept `true/false/1/0/yes/no` (case-insensitive).
- [ ] **Step 4: Run to verify they pass** — same command → PASS.
- [ ] **Step 5: Commit** — `git add src/mcp_youtube_extract/shared/upload tests/mcp_youtube_extract/shared/upload && git commit -m "feat(upload): channel and settings configuration"`

---

### Task 2: Resolve an upload spec from params, defaults and a folder

**Files:**
- Create: `src/mcp_youtube_extract/shared/upload/spec.py`
- Test: `tests/mcp_youtube_extract/shared/upload/test_spec_resolve.py`

**Interfaces:**
- Consumes: `UploadConfig`, `Channel` (Task 1).
- Produces:
  - `FIELDS = ("channel", "folder", "video_path", "title", "description", "captions_path", "thumbnail_path", "visibility", "publish_at", "language", "audio_language", "captions_language", "made_for_kids")`
  - `@dataclass class UploadSpec: channel: Channel; video_path: Path; title: str; description: str = ""; captions_path: Path | None = None; thumbnail_path: Path | None = None; visibility: Literal["private", "unlisted", "public"] | None = "public"; publish_at: datetime | None = None; language: str = "en"; audio_language: str = "en"; captions_language: str = "en"; made_for_kids: bool = False`
  - `@dataclass class SpecResult: spec: UploadSpec | None; problems: list[str]; warnings: list[str]`
  - `def resolve_spec(params: Mapping[str, Any], defaults: Mapping[str, Any] | None, config: UploadConfig) -> SpecResult` — `spec` is None whenever `problems` is non-empty.

- [ ] **Step 1: Write the failing tests** (helper `make_folder(tmp_path, name="01-intro — RAG", files={...})` writes files; `cfg` fixture from Task 1 with `main` and `second`)

```python
def test_folder_convention(tmp_path, cfg):
    d = make_folder(tmp_path, files={"talk.mp4": b"x", "title.txt": "﻿The Title  \nignored\n",
                                     "description.md": "line one\r\nline two\r\n", "captions.srt": "1\n",
                                     "thumbnail.png": b"png"})
    r = resolve_spec({"folder": str(d)}, None, cfg)
    assert r.problems == []
    s = r.spec
    assert s.video_path == d / "talk.mp4" and s.title == "The Title"
    assert s.description == "line one\nline two\n"
    assert s.captions_path == d / "captions.srt" and s.thumbnail_path == d / "thumbnail.png"
    assert (s.channel.name, s.visibility, s.language, s.audio_language, s.captions_language, s.made_for_kids) == \
           ("main", "public", "en", "en", "en", False)

def test_explicit_params_override_folder_and_defaults_fill_gaps(tmp_path, cfg):
    d = make_folder(tmp_path, files={"v.mp4": b"x", "title.txt": "Folder title"})
    r = resolve_spec({"folder": str(d), "title": "Mine", "language": "hi"},
                     {"language": "en", "channel": "second", "made_for_kids": True}, cfg)
    s = r.spec
    assert (s.title, s.language, s.audio_language, s.channel.name, s.made_for_kids) == ("Mine", "hi", "hi", "second", True)

def test_publish_at_suppresses_default_visibility(tmp_path, cfg):
    d = make_folder(tmp_path, files={"v.mp4": b"x", "title.txt": "T"})
    r = resolve_spec({"folder": str(d), "publish_at": "2030-01-02T18:00:00+05:30"}, {"visibility": "public"}, cfg)
    assert r.spec.visibility is None
    assert r.spec.publish_at == datetime(2030, 1, 2, 12, 30, tzinfo=timezone.utc)

def test_svg_thumbnail_ignored_with_warning(tmp_path, cfg):
    d = make_folder(tmp_path, files={"v.mp4": b"x", "title.txt": "T", "thumbnail.svg": "<svg/>"})
    r = resolve_spec({"folder": str(d)}, None, cfg)
    assert r.spec.thumbnail_path is None and any("thumbnail.svg" in w for w in r.warnings)

@pytest.mark.parametrize("params, needle", [
    ({}, "folder or video_path"),
    ({"video_path": "/abs/v.mp4"}, "title"),
    ({"folder": "relative/dir"}, "absolute path"),
    ({"folder": "<two-mp4>"}, "a.mp4"),
    ({"folder": "<no-mp4>"}, ".mp4"),
    ({"folder": "<ok>", "titel": "x"}, "unknown field 'titel'"),
    ({"folder": "<ok>", "publish_at": "2030-01-02T18:00:00"}, "UTC offset"),
    ({"folder": "<ok>", "publish_at": "next tuesday"}, "publish_at"),
    ({"folder": "<ok>", "visibility": "secret"}, "visibility"),
    ({"folder": "<ok>", "made_for_kids": "no"}, "made_for_kids"),
    ({"folder": "<ok>", "channel": "nope"}, "nope"),
])
def test_resolution_problems(tmp_path, cfg, params, needle):
    ...  # "<two-mp4>" → folder holding a.mp4 + b.mp4; "<no-mp4>" → no video; "<ok>" → v.mp4 + title.txt
    r = resolve_spec(params, None, cfg)
    assert r.spec is None and any(needle in p for p in r.problems)

def test_tilde_is_expanded(tmp_path, cfg, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    make_folder(tmp_path, name="vid", files={"v.mp4": b"x", "title.txt": "T"})
    assert resolve_spec({"folder": "~/vid"}, None, cfg).spec.video_path == tmp_path / "vid" / "v.mp4"
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/mcp_youtube_extract/shared/upload/test_spec_resolve.py -v` → FAIL.
- [ ] **Step 3: Implement `resolve_spec`** — merge order: built-ins < `defaults` < `params` < (folder files fill only `video_path`/`title`/`description`/`captions_path`/`thumbnail_path` not given explicitly). Collect every problem rather than stopping at the first. Text files: `utf-8-sig`, `\r\n`→`\n`. Thumbnail lookup order `thumbnail.png`, `thumbnail.jpg`, `thumbnail.jpeg`. `publish_at` via `datetime.fromisoformat`, stored in UTC.
- [ ] **Step 4: Run to verify they pass** — same command → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(upload): resolve upload specs from params, defaults and folders"` (add the new files first).

---

### Task 3: Validate a spec

**Files:**
- Modify: `src/mcp_youtube_extract/shared/upload/spec.py`
- Test: `tests/mcp_youtube_extract/shared/upload/test_spec_validate.py`

**Interfaces:**
- Consumes: `UploadSpec`, `SpecResult`, `resolve_spec` (Task 2).
- Produces:
  - `def validate_spec(spec: UploadSpec, now: datetime) -> list[str]`
  - `def check_publish_at(spec: UploadSpec, now: datetime) -> str | None` — the "in the future" rule alone; used again just before upload (Task 5).
  - `def build_spec(params: Mapping[str, Any], defaults: Mapping[str, Any] | None, config: UploadConfig, now: datetime) -> SpecResult` — resolve, then validate; `spec` None if any problem.

- [ ] **Step 1: Write the failing tests** (fixture `spec(tmp_path, **overrides)` builds a valid `UploadSpec` with real files; `NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)`)

```python
@pytest.mark.parametrize("title, ok", [("x" * 100, True), ("x" * 101, False), ("", False), ("a < b", False), ("a > b", False)])
def test_title_rules(spec, title, ok):
    assert (validate_spec(spec(title=title), NOW) == []) is ok

@pytest.mark.parametrize("desc, ok", [("d" * 5000, True), ("d" * 5001, False), ("<b>", False)])
def test_description_rules(spec, desc, ok):
    assert (validate_spec(spec(description=desc), NOW) == []) is ok

def test_thumbnail_rules(spec, tmp_path):
    big = tmp_path / "big.png"; big.write_bytes(b"0" * (2_097_152 + 1))
    gif = tmp_path / "t.gif"; gif.write_bytes(b"0")
    exact = tmp_path / "ok.jpg"; exact.write_bytes(b"0" * 2_097_152)
    assert any("2 MB" in p for p in validate_spec(spec(thumbnail_path=big), NOW))
    assert any("PNG or JPG" in p for p in validate_spec(spec(thumbnail_path=gif), NOW))
    assert validate_spec(spec(thumbnail_path=exact), NOW) == []

def test_captions_must_be_srt(spec, tmp_path):
    vtt = tmp_path / "c.vtt"; vtt.write_text("WEBVTT")
    assert any(".srt" in p for p in validate_spec(spec(captions_path=vtt), NOW))

def test_missing_files(spec, tmp_path):
    assert any("not found" in p for p in validate_spec(spec(video_path=tmp_path / "gone.mp4"), NOW))

def test_publish_at_rules(spec):
    past = NOW - timedelta(minutes=1)
    assert "past" in check_publish_at(spec(publish_at=past, visibility=None), NOW)
    assert check_publish_at(spec(publish_at=NOW + timedelta(days=1), visibility=None), NOW) is None
    assert any("visibility" in p for p in validate_spec(spec(publish_at=NOW + timedelta(days=1), visibility="unlisted"), NOW))

def test_build_spec_combines(tmp_path, cfg):
    d = make_folder(tmp_path, files={"v.mp4": b"x", "title.txt": "x" * 101})
    r = build_spec({"folder": str(d)}, None, cfg, NOW)
    assert r.spec is None and any("100" in p for p in r.problems)
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/mcp_youtube_extract/shared/upload/test_spec_validate.py -v` → FAIL.
- [ ] **Step 3: Implement** the three functions; problem strings name the field and the limit (e.g. `"title is 101 characters; the limit is 100"`).
- [ ] **Step 4: Run to verify they pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(upload): validate specs against YouTube limits"`.

---

### Task 4: Outcomes, backend protocol, job model and store

**Files:**
- Create: `src/mcp_youtube_extract/shared/upload/backend.py`, `src/mcp_youtube_extract/shared/upload/jobs.py`
- Test: `tests/mcp_youtube_extract/shared/upload/test_jobs.py`

**Interfaces:**
- Consumes: `UploadSpec`, `Channel`.
- Produces (`backend.py`):
  - `@dataclass class UploadOutcome: status: Literal["done", "needs_attention", "failed"]; video_id: str | None = None; watch_url: str | None = None; studio_url: str | None = None; is_short: bool | None = None; applied: dict[str, str] = {}; problems: list[str] = []; warnings: list[str] = []; evidence: list[str] = []` (use `field(default_factory=…)`)
  - `def failure_outcome(video_id: str | None, reason: str, evidence: list[str]) -> UploadOutcome` — `needs_attention` if `video_id` else `failed`.
  - `class Backend(Protocol): def ensure_session(self, channel: Channel, on_state: Callable[[str, str | None], None]) -> str | None` (None = ready, else failure reason; `on_state(state, message)`), `def upload(self, spec: UploadSpec) -> UploadOutcome`
- Produces (`jobs.py`):
  - `EntryState = Literal["waiting", "uploading", "done", "needs_attention", "failed", "interrupted"]`; `JobState = Literal["queued", "running", "waiting_for_sign_in", "pausing", "finished", "interrupted"]`
  - `@dataclass class Entry: index: int; params: dict[str, Any]; state: EntryState = "waiting"; file_key: list | None = None; video_id: str | None = None; watch_url: str | None = None; studio_url: str | None = None; is_short: bool | None = None; applied: dict = {}; problems: list[str] = []; warnings: list[str] = []; evidence: list[str] = []` and `def apply(self, outcome: UploadOutcome) -> None`
  - `@dataclass class Job: job_id: str; kind: Literal["video", "series"]; created_at: datetime; state: JobState; entries: list[Entry]; defaults: dict[str, Any]; pause_until: datetime | None = None; message: str | None = None` and `finished` property
  - `def new_job(kind, entries_params: list[dict], defaults: dict | None, now: datetime) -> Job` — `job_id` is 12 lowercase hex chars.
  - `class JobStore: __init__(self, jobs_dir: Path); save(self, job: Job) -> None` (atomic: temp file + `os.replace`); `load(self, job_id: str) -> Job` (`KeyError` if absent); `recent(self, since: datetime) -> list[Job]`; `mark_interrupted_on_startup(self) -> list[str]`
  - `def format_status(job: Job, now: datetime) -> str`

- [ ] **Step 1: Write the failing tests**

```python
def test_failure_outcome_depends_on_video_id():
    assert failure_outcome(None, "boom", []).status == "failed"
    assert failure_outcome("abc", "boom", ["/x.png"]).status == "needs_attention"

def test_round_trip_and_atomic_save(tmp_path):
    store = JobStore(tmp_path)
    job = new_job("series", [{"folder": "/a"}, {"folder": "/b"}], {"language": "en"}, NOW)
    job.entries[0].apply(UploadOutcome(status="done", video_id="abc", watch_url="https://youtu.be/abc"))
    store.save(job)
    again = store.load(job.job_id)
    assert again == job and re.fullmatch(r"[0-9a-f]{12}", job.job_id)
    assert [p.name for p in tmp_path.iterdir()] == [f"{job.job_id}.json"]

def test_load_unknown_raises(tmp_path):
    with pytest.raises(KeyError):
        JobStore(tmp_path).load("000000000000")

def test_mark_interrupted_on_startup(tmp_path):
    store = JobStore(tmp_path)
    running = new_job("series", [{}, {}, {}], None, NOW); running.state = "running"
    running.entries[0].state = "done"
    running.entries[1].state = "uploading"; running.entries[1].video_id = "vid1"
    done = new_job("video", [{}], None, NOW); done.state = "finished"; done.entries[0].state = "done"
    store.save(running); store.save(done)
    assert store.mark_interrupted_on_startup() == [running.job_id]
    r = store.load(running.job_id)
    assert r.state == "interrupted"
    assert [e.state for e in r.entries] == ["done", "interrupted", "interrupted"]
    assert r.entries[1].video_id == "vid1"
    assert store.load(done.job_id).state == "finished"

def test_format_status(tmp_path):
    job = new_job("series", [{"folder": "/a"}, {"folder": "/b"}], None, NOW)
    job.state = "pausing"; job.pause_until = NOW + timedelta(minutes=5)
    job.entries[0].apply(UploadOutcome(status="done", video_id="abc", watch_url="https://youtu.be/abc"))
    text = format_status(job, NOW)
    assert job.job_id in text and "pausing until" in text and "https://youtu.be/abc" in text
    job.state = "finished"; job.entries[1].apply(UploadOutcome(status="failed", problems=["boom"]))
    assert "Not done" in format_status(job, NOW) and "boom" in format_status(job, NOW)
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/mcp_youtube_extract/shared/upload/test_jobs.py -v` → FAIL.
- [ ] **Step 3: Implement** both modules. JSON stores datetimes as ISO strings. `format_status` shows times in the machine's local time zone (`HH:MM`), lists every entry (index, folder or video file name, state, links, problems, evidence paths), and once finished ends with a "Not done" section listing every non-`done` entry.
- [ ] **Step 4: Run to verify they pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(upload): job model, persistent store and outcomes"`.

---

### Task 5: Job runner

**Files:**
- Create: `src/mcp_youtube_extract/shared/upload/runner.py`
- Test: `tests/mcp_youtube_extract/shared/upload/test_runner.py`

**Interfaces:**
- Consumes: `build_spec`, `check_publish_at` (Task 3); `Backend`, `UploadOutcome`, `failure_outcome`, `Job`, `Entry`, `JobStore` (Task 4); `UploadConfig` (Task 1).
- Produces: `class JobRunner:`
  - `__init__(self, store: JobStore, backend: Backend, config: UploadConfig, *, rng: random.Random | None = None, pause: Callable[[float], None] = time.sleep, now: Callable[[], datetime] = <utc now>)` — starts **one** daemon worker thread. (Marking leftovers interrupted is `service.get_store()`'s job, Task 11, so it happens even when the first call after a restart is a status check.)
  - `submit(self, job: Job) -> None` (FIFO; job state `queued` until the worker takes it)
  - `wait(self, job_id: str, timeout_s: float) -> Job` (returns the latest stored job, finished or not)
  - `get(self, job_id: str) -> Job`
  - `resume(self, job_id: str) -> Job` (resets `failed` entries and `interrupted` entries without `video_id` to `waiting`, resubmits the same job id)
  - `find_duplicate(self, spec: UploadSpec) -> str | None` (job id of a non-`failed` entry with the same `file_key` and channel in a job created in the last 24 h)
  - `@staticmethod file_key(spec: UploadSpec) -> list` → `[channel_id, str(realpath), size, mtime_ns]`

Worker loop per entry, in order: `build_spec(entry.params, job.defaults, config, now())` → problems mark the entry `failed` (not an attempt); `check_publish_at` → `failed` with "publish_at … is now in the past" (not an attempt); if an attempt already happened in this job, `job.state="pausing"`, `pause_until=now()+gap`, `pause(gap)` with `gap = rng.uniform(60, 600)`; `ensure_session(channel, on_state)` — `on_state("waiting_for_sign_in", msg)` sets job state/message — a reason marks the entry `failed`; entry `uploading`; `backend.upload(spec)` (any exception → `failure_outcome(None, f"internal error: {exc}", [])`); `entry.apply(outcome)`. Save the job after every change.

- [ ] **Step 1: Write the failing tests** — a `FakeBackend` records calls, returns scripted outcomes, optionally blocks on a `threading.Event`, and can return a session reason. `pause` is a recorder (no real sleeping). `now` is a settable clock.

```python
def test_sequential_skip_and_continue(runner_factory):
    r, backend, pauses = runner_factory(outcomes=["done", "failed", "done"])
    job = submit_series(r, 3)
    final = r.wait(job.job_id, 5)
    assert [e.state for e in final.entries] == ["done", "failed", "done"] and final.state == "finished"
    assert backend.uploaded == [0, 1, 2]

def test_gaps_between_attempts_only(runner_factory):
    r, backend, pauses = runner_factory(outcomes=["done", "done"])
    job = submit_series(r, 4, invalid={0, 2})          # entries 0 and 2 fail validation
    r.wait(job.job_id, 5)
    assert len(pauses) == 1 and 60 <= pauses[0] <= 600

def test_publish_at_rechecked_before_upload(runner_factory):
    r, backend, clock = runner_factory(outcomes=["done"], with_clock=True)
    job = submit_series(r, 1, publish_at=clock.now() + timedelta(minutes=1))
    clock.advance(minutes=2)                            # before the worker reaches it
    final = r.wait(job.job_id, 5)
    assert final.entries[0].state == "failed" and "past" in final.entries[0].problems[0]
    assert backend.uploaded == []

def test_session_failure_fails_entry_and_continues(runner_factory):
    r, backend, _ = runner_factory(outcomes=["done", "done"], session_reasons=["sign-in not completed within 10 minutes", None])
    final = r.wait(submit_series(r, 2).job_id, 5)
    assert [e.state for e in final.entries] == ["failed", "done"]

def test_waiting_for_sign_in_is_reported(runner_factory):
    r, backend, _ = runner_factory(outcomes=["done"], sign_in_hold=True)
    job = submit_series(r, 1)
    backend.in_sign_in.wait(5)
    assert r.get(job.job_id).state == "waiting_for_sign_in"
    backend.release.set()
    assert r.wait(job.job_id, 5).state == "finished"

def test_one_upload_at_a_time_fifo(runner_factory):
    r, backend, _ = runner_factory(outcomes=["done"] * 3, block_first=True)
    a = submit_series(r, 2); b = submit_series(r, 1)
    backend.started.wait(5)
    assert r.get(b.job_id).state == "queued"
    backend.release.set()
    r.wait(b.job_id, 5)
    assert backend.uploaded_jobs == [a.job_id, a.job_id, b.job_id]

def test_wait_times_out_with_unfinished_job(runner_factory):
    r, backend, _ = runner_factory(outcomes=["done"], block_first=True)
    job = submit_series(r, 1)
    assert not r.wait(job.job_id, 0.2).finished
    backend.release.set()

def test_backend_exception_becomes_failed_entry(runner_factory):
    r, backend, _ = runner_factory(outcomes=[RuntimeError("selector vanished"), "done"])
    final = r.wait(submit_series(r, 2).job_id, 5)
    assert final.entries[0].state == "failed" and "selector vanished" in final.entries[0].problems[0]
    assert final.entries[1].state == "done"

def test_resume_retries_only_unfinished_without_video_id(runner_factory):
    r, backend, _ = runner_factory(outcomes=["done", "done"])
    job = stored_job(r, states=[("done", "a"), ("failed", None), ("interrupted", "b"), ("interrupted", None), ("needs_attention", "c")])
    r.wait(r.resume(job.job_id).job_id, 5)
    assert backend.uploaded == [1, 3]

def test_find_duplicate(runner_factory, tmp_path):
    r, *_ = runner_factory(outcomes=["done"])
    job = submit_series(r, 1); r.wait(job.job_id, 5)
    assert r.find_duplicate(spec_for_entry(job, 0)) == job.job_id
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/mcp_youtube_extract/shared/upload/test_runner.py -v` → FAIL.
- [ ] **Step 3: Implement `JobRunner`** — a `queue.Queue` of job ids and a `threading.Condition` for `wait`. `file_key` is recorded on the entry when its spec is built, so `find_duplicate` works across restarts via `store.recent()`.
- [ ] **Step 4: Run to verify they pass** → PASS (whole suite: `uv run pytest -q`, still green).
- [ ] **Step 5: Commit** — `git commit -m "feat(upload): single-worker job runner with gaps, re-checks and resume"`.

---

### Task 6: Profile launch and session check

**Files:**
- Modify: `pyproject.toml` (`uv add playwright`; no `playwright install`)
- Create: `src/mcp_youtube_extract/shared/upload/session.py`
- Test: `tests/mcp_youtube_extract/shared/upload/test_session_check.py`, `tests/live/__init__.py`, `tests/live/test_studio_live.py`

**Interfaces:**
- Consumes: `Channel`, `UploadConfig`.
- Produces:
  - `@dataclass class SessionCheck: kind: Literal["ok", "not_logged_in", "wrong_channel", "in_use", "unknown"]; channel_id: str | None; url: str`
  - `def classify_landing(url: str, expected_channel_id: str) -> SessionCheck`
  - `def ensure_profile_dir(channel: Channel) -> Path` (creates with mode `0o700`, and `chmod`s an existing one to `0o700`)
  - `def profile_in_use(profile_dir: Path) -> bool` (`os.path.lexists(profile_dir / "SingletonLock")`)
  - `def persistent_context_args(channel: Channel, config: UploadConfig, headless: bool) -> dict` (kwargs for `launch_persistent_context`, `user_data_dir` included; `viewport={"width": 1440, "height": 900}` when headless, `None` otherwise)
  - `def skip_unsupported_notice(page) -> bool` (clicks "Skip to YouTube Studio" if visible within 10 s)
  - `def check_session(channel: Channel, config: UploadConfig) -> SessionCheck` (returns `in_use` without launching when the profile is locked)
  - `STUDIO_UPLOAD_URL = "https://youtube.com/upload"`

- [ ] **Step 1: Write the failing tests**

```python
MAIN = "UCDzx6hNPpuha4fCwYA5WAyg"

@pytest.mark.parametrize("url, kind, cid", [
    (f"https://studio.youtube.com/channel/{MAIN}/videos/upload?d=ud", "ok", MAIN),
    ("https://studio.youtube.com/channel/UCbbbbbbbbbbbbbbbbbbbbbb/content", "wrong_channel", "UCbbbbbbbbbbbbbbbbbbbbbb"),
    ("https://accounts.google.com/v3/signin/identifier?continue=x", "not_logged_in", None),
    ("https://www.youtube.com/", "unknown", None),
])
def test_classify_landing(url, kind, cid):
    c = classify_landing(url, MAIN)
    assert (c.kind, c.channel_id) == (kind, cid)

def test_profile_dir_is_private(tmp_path, cfg_with_home):
    ch = cfg_with_home(tmp_path).resolve_channel("main")
    path = ensure_profile_dir(ch)
    assert stat.S_IMODE(path.stat().st_mode) == 0o700

def test_profile_in_use_detects_dangling_singleton_lock(tmp_path):
    os.symlink("host-123", tmp_path / "SingletonLock")
    assert profile_in_use(tmp_path) and not profile_in_use(tmp_path / "missing")

def test_launch_args(tmp_path, cfg_with_home):
    cfg = cfg_with_home(tmp_path); ch = cfg.resolve_channel("main")
    a = persistent_context_args(ch, cfg, headless=True)
    assert a["user_data_dir"] == str(ch.profile_dir) and a["executable_path"] == str(cfg.browser_path)
    assert a["ignore_default_args"] == ["--use-mock-keychain"] and a["headless"] is True
    assert persistent_context_args(ch, cfg, headless=False)["viewport"] is None
```

Live (in `tests/live/test_studio_live.py`, module-level `pytestmark = pytest.mark.skipif(os.environ.get("YT_UPLOAD_LIVE_TESTS") != "1", reason="live")`; config from the real environment):

```python
def test_live_session_check_main():
    cfg = load_config(); ch = cfg.resolve_channel(None)
    assert check_session(ch, cfg).kind == "ok"
```

- [ ] **Step 2: Run to verify unit tests fail** — `uv run pytest tests/mcp_youtube_extract/shared/upload/test_session_check.py -v` → FAIL.
- [ ] **Step 3: Implement `session.py` (this task's part)**; `check_session` launches headless, goes to `STUDIO_UPLOAD_URL`, calls `skip_unsupported_notice`, waits for the URL to settle (`studio.youtube.com/channel/` or `accounts.google.com`, 30 s), classifies, closes.
- [ ] **Step 4: Run unit tests → PASS.** Then, with the owner's profile moved to `~/.mcp-youtube-extract/profiles/main` (`mv ~/yt-spike/profile ~/.mcp-youtube-extract/profiles/main`, owner's action) and `YT_UPLOAD_CHANNELS=main=UCDzx6hNPpuha4fCwYA5WAyg`: `YT_UPLOAD_LIVE_TESTS=1 uv run pytest tests/live -k session -v` → PASS.
- [ ] **Step 5: Commit** — `git add pyproject.toml uv.lock … && git commit -m "feat(upload): per-channel profiles and Studio session check"`.

---

### Task 7: Login flow

**Files:**
- Modify: `src/mcp_youtube_extract/shared/upload/session.py`
- Test: `tests/mcp_youtube_extract/shared/upload/test_login.py`

**Interfaces:**
- Consumes: Task 6 functions.
- Produces:
  - `LOGIN_URL = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2Fupload"`
  - `def login_command(channel: Channel, config: UploadConfig) -> list[str]` → `[browser, f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", LOGIN_URL]`
  - `def login_cookies_present(profile_dir: Path, since: float) -> bool` — read-only (`file:…?mode=ro&immutable=1`), checks `Default/Network/Cookies` then `Default/Cookies`; true when `LOGIN_INFO` on a `youtube.com` host **and** `SAPISID` have `max(creation_utc, last_update_utc)` (whichever columns exist; Chromium time = µs since 1601-01-01) after `since` (unix seconds). Selects only `host_key`, `name` and time columns.
  - `def run_login_flow(channel, config, on_state, *, launch=subprocess.Popen, cookies_present=login_cookies_present, check=check_session, clock=time.monotonic, sleep=time.sleep) -> str | None`
  - `def ensure_session(channel, config, on_state, **same_injectables) -> str | None` — `check` → `ok`: None; `in_use`: poll every 2 s until free or `login_timeout_s` (then reason "profile is in use by another window"); `not_logged_in`/`wrong_channel`/`unknown`: `run_login_flow`.

`run_login_flow`: launch; `on_state("waiting_for_sign_in", f"A Brave window has opened to sign in to the YouTube channel '{channel.name}' ({channel.channel_id}).")`; poll every 2 s: process exited and no cookies → return `"sign-in cancelled: the sign-in window was closed"`; cookies present → `sleep(5)`, `terminate()`, `wait(10)` (else `kill()`), wait until `profile_in_use` is false, then `check`: `ok` → None; `wrong_channel` → relaunch, with `on_state` message adding `"It is signed in to {other}; switch to {expected}."`; deadline `login_timeout_s` → terminate, return `f"sign-in not completed within {minutes} minutes"`.

- [ ] **Step 1: Write the failing tests** — `make_cookie_db(path, rows, columns=("host_key","name","creation_utc","last_update_utc"))` builds a SQLite file **without** a `value` or `encrypted_value` column, so any query selecting values errors.

```python
def chromium_us(unix_s): return int((unix_s + 11644473600) * 1_000_000)

def test_cookies_present_requires_both_fresh(tmp_path):
    since = 1_800_000_000
    db = tmp_path / "Default" / "Cookies"
    make_cookie_db(db, [(".youtube.com", "LOGIN_INFO", chromium_us(since + 5), 0),
                        (".youtube.com", "SAPISID", chromium_us(since - 5), chromium_us(since + 9))])
    assert login_cookies_present(tmp_path, since)
    assert not login_cookies_present(tmp_path, since + 60)

def test_cookies_network_path_and_creation_only_schema(tmp_path):
    db = tmp_path / "Default" / "Network" / "Cookies"
    make_cookie_db(db, [(".youtube.com", "LOGIN_INFO", chromium_us(10), None), (".youtube.com", "SAPISID", chromium_us(10), None)],
                   columns=("host_key", "name", "creation_utc"))
    assert login_cookies_present(tmp_path, 5)

def test_login_command(cfg_main):
    cmd = login_command(cfg_main.resolve_channel("main"), cfg_main)
    assert cmd[0] == str(cfg_main.browser_path) and cmd[-1] == LOGIN_URL and "--no-first-run" in cmd

def test_flow_success_closes_window_itself(fakes):
    reason = run_login_flow(fakes.channel, fakes.cfg, fakes.on_state, **fakes.inject(cookies_after=3, checks=["ok"]))
    assert reason is None and fakes.procs[0].terminated
    assert fakes.states[0][0] == "waiting_for_sign_in" and "'main'" in fakes.states[0][1]

def test_flow_window_closed_early(fakes):
    assert "closed" in run_login_flow(fakes.channel, fakes.cfg, fakes.on_state, **fakes.inject(exit_after=2))

def test_flow_timeout(fakes):
    reason = run_login_flow(fakes.channel, fakes.cfg_timeout(60), fakes.on_state, **fakes.inject())
    assert reason == "sign-in not completed within 1 minutes" and fakes.procs[0].terminated

def test_flow_wrong_channel_relaunches(fakes):
    reason = run_login_flow(fakes.channel, fakes.cfg, fakes.on_state,
                            **fakes.inject(cookies_after=1, checks=["wrong_channel", "ok"]))
    assert reason is None and len(fakes.procs) == 2
    assert "switch to UCDzx6hNPpuha4fCwYA5WAyg" in fakes.states[-1][1]

def test_ensure_session_paths(fakes):
    assert ensure_session(fakes.channel, fakes.cfg, fakes.on_state, **fakes.inject(checks=["ok"])) is None
    assert fakes.procs == []
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/mcp_youtube_extract/shared/upload/test_login.py -v` → FAIL.
- [ ] **Step 3: Implement** the four functions with the injectables above.
- [ ] **Step 4: Run → PASS.** Then a live check with the owner present: move `profiles/main` aside temporarily (or use a second configured channel with an empty profile), run `uv run python -c "from mcp_youtube_extract.shared.upload.config import load_config; from mcp_youtube_extract.shared.upload.session import ensure_session; c=load_config(); print(ensure_session(c.resolve_channel(None), c, lambda s,m: print(s,m)))"`; owner signs in; expected output ends with `None`. If the cookie signal fires too early or never, record what Chromium actually writes and adjust `login_cookies_present` (spec: fall back to closing the window and running `check_session`).
- [ ] **Step 5: Commit** — `git commit -m "feat(upload): server-run login flow per channel"`.

---

### Task 8: Studio backend — proven steps, evidence, outcomes

**Files:**
- Create: `src/mcp_youtube_extract/shared/upload/media.py`, `src/mcp_youtube_extract/shared/upload/studio.py`
- Test: `tests/mcp_youtube_extract/shared/upload/test_studio.py`, add to `tests/live/test_studio_live.py`

**Interfaces:**
- Consumes: `UploadSpec`, `UploadOutcome`, `failure_outcome`, `Backend` (Task 4); `persistent_context_args`, `skip_unsupported_notice`, `ensure_session`, `STUDIO_UPLOAD_URL` (Tasks 6–7).
- Produces:
  - `media.py`: `def probe_video(path: Path) -> dict | None` → `{"width": int, "height": int, "duration_s": float, "orientation": "vertical" | "horizontal" | "square"}`, None when `ffprobe` is not on `PATH`
  - `studio.py`: `def parse_video_link(href: str) -> tuple[str, bool]` (video id, is_short); `def save_evidence(page, failures_dir: Path, step: str, now: datetime) -> list[str]`; `class StudioBackend` (implements `Backend`): `__init__(self, config: UploadConfig)`, `ensure_session(...)` delegating to `session.ensure_session`, `upload(self, spec: UploadSpec) -> UploadOutcome`

`upload` runs named steps, each in its own small method, in this order (Task 9 fills the marked ones; until then they no-op when the spec field is empty and fail with "not implemented yet" otherwise): open profile (headless per config) → `STUDIO_UPLOAD_URL` → skip notice → `input[type='file']` ← video → title (`#title-textarea #textbox`, `Meta+A`, type) → **description** → **thumbnail** → made-for-kids (`tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']` or `…_MFK`) → **languages** → `#next-button` → **captions** (Video elements page) → `#next-button` ×2 → visibility (`tp-yt-paper-radio-button[name='PRIVATE']`; **unlisted/public/schedule**) → wait until `ytcp-video-upload-progress` text no longer matches `/uploading/i` (120 s plus 60 s per 100 MB) → read link (`a[href*='youtu.be'], a[href*='/shorts/'], a[href*='watch?v=']`) → `#done-button` → **read-back** (Task 10). Any exception: `save_evidence` then `failure_outcome(video_id_if_known, f"{step}: {first line of error}", evidence)`. Success: `done` with `applied` (title, visibility or schedule, languages, files) and `warnings` containing the `probe_video` summary when available.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("href, vid, short", [
    ("https://youtube.com/shorts/pRdqMdicoEU", "pRdqMdicoEU", True),
    ("https://youtu.be/L-r3uBBHZQQ", "L-r3uBBHZQQ", False),
    ("https://www.youtube.com/watch?v=L-r3uBBHZQQ&t=1", "L-r3uBBHZQQ", False),
])
def test_parse_video_link(href, vid, short):
    assert parse_video_link(href) == (vid, short)

def test_save_evidence(tmp_path):
    page = FakePage(text="Something went wrong")
    paths = save_evidence(page, tmp_path, "set title", datetime(2026, 10, 23, 11, 5, 9))
    assert [Path(p).name for p in paths] == ["20261023-110509-set-title.png", "20261023-110509-set-title.txt"]
    assert "Something went wrong" in Path(paths[1]).read_text()

@pytest.mark.skipif(shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_probe_video_vertical(tmp_path):
    clip = make_clip(tmp_path, 1080, 1920, seconds=2)      # ffmpeg testsrc + sine
    info = probe_video(clip)
    assert (info["width"], info["height"], info["orientation"]) == (1080, 1920, "vertical")
```

Live: `test_live_private_short_upload` — 5 s vertical clip, title `"live test private short"`, `visibility="private"` → `outcome.status == "done"` and `outcome.is_short is True`; print the video id.

- [ ] **Step 2: Run unit tests → FAIL.**
- [ ] **Step 3: Implement** `media.py` and `studio.py` as above.
- [ ] **Step 4: Run unit tests → PASS; live:** `YT_UPLOAD_LIVE_TESTS=1 uv run pytest tests/live -k private_short -v -s` → PASS; delete the printed video in Studio.
- [ ] **Step 5: Commit** — `git commit -m "feat(upload): Studio upload backend with failure evidence"`.

---

### Task 9: Studio backend — description, thumbnail, languages, captions, visibility, schedule

**Files:**
- Modify: `src/mcp_youtube_extract/shared/upload/studio.py`
- Test: `tests/mcp_youtube_extract/shared/upload/test_studio_fields.py`, add to `tests/live/test_studio_live.py`

**Interfaces:**
- Consumes: Task 8's step methods and `save_evidence`.
- Produces:
  - `STUDIO_LANGUAGE_LABELS: dict[str, str]` (BCP-47 → Studio dropdown label; at least `en`, `en-GB`, `en-US`, `hi`, filled in from the live dropdown)
  - `def studio_language_label(code: str) -> str` (`ValueError` naming the code when unmapped — the entry then fails **before** any upload)
  - `def picker_values(publish_at: datetime, tz: ZoneInfo) -> tuple[str, str]` (date text, time text exactly as Studio's picker accepts them; `ValueError` if Studio cannot express that minute)

Discovery, one step at a time, against live Studio with `YT_UPLOAD_HEADLESS=false` and private uploads; use the failure screenshots/text from `save_evidence` and `page.content()` snippets to find selectors. Studio's own labels, not guesses, decide the language table and the picker formats. Also confirm whether Studio's time field accepts any minute (if it offers 15-minute slots only, `picker_values` raises for other minutes).

- [ ] **Step 1: Write the failing tests** (fill the expected strings with what discovery observed; the ones shown are placeholders to be confirmed, and the test must assert the observed values)

```python
def test_language_labels():
    assert studio_language_label("en") == "English"
    with pytest.raises(ValueError, match="xx-YY"):
        studio_language_label("xx-YY")

def test_picker_values_local_time():
    ist = ZoneInfo("Asia/Kolkata")
    date_text, time_text = picker_values(datetime(2026, 11, 2, 12, 30, tzinfo=timezone.utc), ist)
    assert (date_text, time_text) == ("2 Nov 2026", "18:00")   # replace with observed formats

def test_picker_rejects_unrepresentable_minute_if_studio_restricts():
    ...  # only if discovery shows slot-restricted times: 18:07 → ValueError naming 18:07
```

Live tests (each prints the video id): description + thumbnail + languages + captions on a private 16:9 clip; `visibility="unlisted"`; `publish_at` = now + 30 days (scheduled). A public-visibility live test runs only when `YT_UPLOAD_LIVE_PUBLIC=1` as well.

- [ ] **Step 2: Run unit tests → FAIL.**
- [ ] **Step 3: Implement** each step method and the two helpers; the backend calls `studio_language_label` for all three languages and `picker_values` before opening the browser, so unmapped languages and unrepresentable times fail with nothing created.
- [ ] **Step 4: Run unit + live tests → PASS;** delete the test videos.
- [ ] **Step 5: Commit** — `git commit -m "feat(upload): description, thumbnail, languages, captions, visibility and scheduling in Studio"`.

---

### Task 10: Read-back verification

**Files:**
- Modify: `src/mcp_youtube_extract/shared/upload/studio.py`
- Test: `tests/mcp_youtube_extract/shared/upload/test_readback.py`, add to `tests/live/test_studio_live.py`

**Interfaces:**
- Produces:
  - `def compare_readback(spec: UploadSpec, observed: dict) -> list[str]` — `observed = {"title": str, "visibility": "private" | "unlisted" | "public" | "scheduled", "publish_at": datetime | None, "caption_languages": list[str]}`; returns one mismatch line per difference.
  - `StudioBackend._read_back(context, video_id) -> dict` (scrapes `https://studio.youtube.com/video/<id>/edit` and its subtitles page)

`upload` calls it after `#done-button`; mismatches → `needs_attention` with the mismatch lines (never `done`).

- [ ] **Step 1: Write the failing tests**

```python
def test_readback_match(spec_public):
    assert compare_readback(spec_public, {"title": spec_public.title, "visibility": "public", "publish_at": None, "caption_languages": []}) == []

def test_readback_mismatches(spec_scheduled_with_captions):
    s = spec_scheduled_with_captions
    lines = compare_readback(s, {"title": "Other", "visibility": "private", "publish_at": None, "caption_languages": []})
    assert any("title" in l for l in lines) and any("schedule" in l for l in lines) and any("caption" in l for l in lines)
```

Live: rerun Task 9's description/captions private test and assert `outcome.status == "done"` (read-back passed).

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** the comparison and scraping.
- [ ] **Step 4: Run unit + live → PASS;** delete the test video.
- [ ] **Step 5: Commit** — `git commit -m "feat(upload): read back uploads and flag mismatches"`.

---

### Task 11: The three tools

**Files:**
- Create: `src/mcp_youtube_extract/shared/upload/service.py`, `src/mcp_youtube_extract/tools/video_upload/{__init__,tool}.py`, `src/mcp_youtube_extract/tools/series_upload/{__init__,tool}.py`, `src/mcp_youtube_extract/tools/upload_status/{__init__,tool}.py`
- Test: `tests/mcp_youtube_extract/tools/{video_upload,series_upload,upload_status}/{__init__,test_tool}.py`

**Interfaces:**
- Consumes: `load_config`, `ConfigError` (1); `build_spec` (3); `new_job`, `JobStore`, `format_status` (4); `JobRunner` (5); `StudioBackend` (8).
- Produces:
  - `service.py`: `def get_store() -> JobStore` (no config needed; on first creation in this process calls `mark_interrupted_on_startup()`); `def get_runner() -> JobRunner` (lazy singleton; loads config — `ConfigError` propagates to the tool, which returns it as text); `def _reset_for_tests(runner: JobRunner | None = None, store: JobStore | None = None) -> None`
  - `upload_yt_video(channel: str | None = None, folder: str | None = None, video_path: str | None = None, title: str | None = None, description: str | None = None, captions_path: str | None = None, thumbnail_path: str | None = None, visibility: str | None = None, publish_at: str | None = None, language: str | None = None, audio_language: str | None = None, captions_language: str | None = None, made_for_kids: bool | None = None) -> str`
  - `upload_yt_series(videos: list[dict] | None = None, defaults: dict | None = None, resume_job_id: str | None = None) -> str`
  - `get_yt_upload_status(job_id: str) -> str`

Behaviour: `upload_yt_video` builds the spec (problems → `"Not uploaded: …"` listing all, no job); duplicate → `"Not uploaded: this video is already in job <id> …"`; else submit a one-entry job and `wait(call_wait_s)`: finished → the entry's outcome as text; unfinished → `"Still running as job <id> …; call get_yt_upload_status"` plus the current status (e.g. waiting for sign-in, with its message). `upload_yt_series` validates each entry (problems and duplicates mark that entry `failed`, not the call), submits, returns immediately with the job id and every entry that already failed. `resume_job_id` together with `videos`/`defaults` → error text. Descriptions follow the existing style and each states: public by default, `publish_at` schedules, one upload at a time, sign-in window behaviour, job/status flow.

- [ ] **Step 1: Write the failing tests** — inject a runner over a `FakeBackend` with `service._reset_for_tests`; set `YT_UPLOAD_CHANNELS` via `monkeypatch.setenv`.

```python
def test_video_validation_failure_submits_nothing(fake_service, tmp_path):
    out = upload_yt_video(video_path=str(tmp_path / "missing.mp4"), title="T")
    assert out.startswith("Not uploaded") and "not found" in out and fake_service.backend.uploaded == []

def test_video_happy_path(fake_service, folder):
    out = upload_yt_video(folder=str(folder))
    assert "https://youtu.be/" in out and "public" in out.lower()

def test_video_unfinished_returns_job_id(fake_service, folder):
    fake_service.backend.block_first = True; fake_service.call_wait(0.2)
    out = upload_yt_video(folder=str(folder))
    assert "get_yt_upload_status" in out and re.search(r"\b[0-9a-f]{12}\b", out)

def test_retry_after_cutoff_is_refused(fake_service, folder):
    first = upload_yt_video(folder=str(folder))
    again = upload_yt_video(folder=str(folder))
    assert again.startswith("Not uploaded") and "already" in again and len(fake_service.backend.uploaded) == 1

def test_config_error_is_text(monkeypatch):
    monkeypatch.delenv("YT_UPLOAD_CHANNELS", raising=False); service._reset_for_tests()
    assert "YT_UPLOAD_CHANNELS" in upload_yt_video(folder="/x")

def test_series_skips_invalid_entries(fake_service, folders):
    out = upload_yt_series(videos=[{"folder": str(folders[0])}, {"folder": "relative"}, {"folder": str(folders[1])}])
    job_id = re.search(r"\b[0-9a-f]{12}\b", out).group(0)
    assert "Entry 2" in out and "absolute path" in out
    final = service.get_runner().wait(job_id, 5)
    assert [e.state for e in final.entries] == ["done", "failed", "done"]

def test_series_resume_conflicts_with_videos(fake_service):
    assert "either" in upload_yt_series(videos=[{"folder": "/a"}], resume_job_id="0123456789ab").lower()

def test_status_unknown_job(fake_service):
    assert "No upload job" in get_yt_upload_status("000000000000")

def test_status_after_restart_shows_interrupted(tmp_path, monkeypatch):
    left = new_job("video", [{"folder": "/a"}], None, NOW); left.state = "running"; left.entries[0].state = "uploading"
    JobStore(tmp_path / "jobs").save(left)
    service._reset_for_tests(); monkeypatch.setattr(service, "HOME", tmp_path)
    assert "interrupted" in get_yt_upload_status(left.job_id)

def test_descriptions_state_public_default():
    for tool in asyncio.run(app.list_tools()):
        if tool.name in {"upload_yt_video", "upload_yt_series"}:
            assert "public by default" in tool.description.lower()
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** `service.py` and the three tool modules (`@app.tool(description=…)`, `logger.info` on call, `try/except Exception` → error string, as in `tools/playlist_info/tool.py`).
- [ ] **Step 4: Run → PASS**, then `uv run pytest -q` (whole suite green).
- [ ] **Step 5: Commit** — `git commit -m "feat(upload): upload_yt_video, upload_yt_series and get_yt_upload_status tools"`.

---

### Task 12: Server wiring, `--login` CLI and README

**Files:**
- Modify: `src/mcp_youtube_extract/server.py`, `src/mcp_youtube_extract/_app.py`, `README.md`
- Test: `tests/mcp_youtube_extract/test_server.py`

**Interfaces:**
- Consumes: the three tool modules (11); `load_config`, `ensure_session` (1, 7).
- Produces: `def main(argv: list[str] | None = None) -> None` — no args: stdio server as today; `--login NAME`: runs `ensure_session` for that channel, printing each `on_state` message, exit code 0 on success, 1 with the reason otherwise. `def run_cli_login(name: str) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
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
    assert "upload" in app.instructions.lower()
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** — side-effect imports for the three tools in `server.py`; argparse in `main`; `_app.py` name `"YouTube Analyzer & Uploader"` and instructions adding: uploads are public by default, uploads run as jobs (poll `get_yt_upload_status` with the job id), a sign-in window may open and only needs the person to sign in. README: an "Uploading to your channels" section — `YT_UPLOAD_*` variables with an example `claude mcp add-json` env block, first sign-in (automatic, or `mcp_youtube_extract --login main`), moving the spike profile (`mv ~/yt-spike/profile ~/.mcp-youtube-extract/profiles/main`), the job/status flow, live tests and that they leave private videos to delete, and the risk note (Studio automation is outside YouTube's terms until the Data API backend replaces it).
- [ ] **Step 4: Run → PASS**, `uv run pytest -q` green; then a manual end-to-end through Claude Code with the server's env set: `upload_yt_video` on a pipeline folder with `visibility="private"` → done; `get_yt_upload_status` on its job id → done.
- [ ] **Step 5: Commit** — `git commit -m "feat(upload): wire upload tools into the server, add --login and docs"`.
