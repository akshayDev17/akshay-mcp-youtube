# Channel upload tools — design

Status: draft for approval · 2026-10-23

## Why

The owner publishes long-form explainer videos (and sometimes Shorts) to one YouTube
channel they maintain. The videos are produced by the `explainer-video-from-coursework`
plugin (`~/github/explainer-video`), which already writes each finished video into its
own folder with a description (chapters included) and English captions. Uploading them
by hand in YouTube Studio is the remaining manual step. The goal is to let Claude upload
one video, or a whole batch, through this MCP server.

The official route — YouTube Data API v3 with OAuth — is blocked for now: the owner's
GCP project (created 2026-10-06) has not passed YouTube's API compliance audit, and until
it does, every API upload is locked to private. The owner is applying for the audit.
Until it passes, uploads go through YouTube Studio's own web upload dialog, driven by a
real browser profile that is logged in to the channel. When the audit passes, a second
backend using the official API replaces it behind the same tools.

## Goals

- Upload one video, or a batch, to the owner's channel from Claude.
- Per video: video file, title, description, captions file, thumbnail, languages,
  made-for-kids, and either a visibility or an exact scheduled publish time.
- Read the explainer-video plugin's per-video folder by convention, while still
  accepting explicit files for videos made elsewhere (e.g. Shorts).
- In a batch, every video carries its own settings, including its own arbitrary
  publish time. There is no interval or pattern.
- Login happens once, in a browser window, and persists. It is re-requested only when
  YouTube ends the session.
- Same tool inputs regardless of backend, so swapping to the official API later does not
  change how the tools are called.

## Non-goals

- The official Data API backend itself (designed for, not built now).
- An HTTP transport or Claude Code's "Authenticate" button — the server stays stdio.
- Generating any content: titles, descriptions, captions and thumbnails arrive finished.
- Playlists, tags, category, end screens, cards, editing or deleting existing videos.
- More than one channel.

## Anti-goals (failure even if it "works")

- Uploading to any channel other than the configured one.
- Making a video more public than asked: the default is private, always.
- Silently changing what was asked (e.g. rounding a publish time, dropping a caption
  track) and reporting success.
- Copying cookies out of the browser profile, or importing cookies from another
  browser. Tested: an exported Google session died within ~35 minutes.
- Duplicate uploads when a batch is retried.

## Decided with the owner

- One server: these tools live in `mcp_youtube_extract`, alongside the read-only tools.
- Three tools: one video, a batch, and batch status.
- Batch failures: skip the failed video, carry on, report all failures at the end.
- Per-video scheduling in batches, arbitrary times.
- The explainer-video plugin will additionally write `title.txt` and a PNG/JPG thumbnail
  into each video folder (the owner is making that change).
- Login is LinkedIn-style: the first call that needs a session opens the login window
  itself; no "Authenticate" button.
- The channel is verified (uploads over 15 minutes and custom thumbnails are allowed).

## Tools

All three follow the existing tool style: `@app.tool(description=...)`, one folder per
tool under `src/mcp_youtube_extract/tools/`, plain-text/markdown string results, and
errors returned as a string rather than raised.

### `upload_yt_video`

Uploads one video and returns when it is done (or failed).

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `folder` | str | — | A per-video folder; files below are found in it by convention |
| `video_path` | str | from `folder` | The video file |
| `title` | str | from `folder` | Title text |
| `description` | str | from `folder` | Description text (not a path) |
| `captions_path` | str | from `folder` | Caption file (SRT) |
| `thumbnail_path` | str | from `folder` | PNG or JPG |
| `visibility` | `private` / `unlisted` / `public` | `private` | Must be omitted when `publish_at` is set |
| `publish_at` | str, ISO 8601 with UTC offset | none | Scheduled: private until this moment, then public |
| `language` | str (BCP-47, e.g. `en`) | `en` | Language of title and description |
| `audio_language` | str | = `language` | Spoken language of the video |
| `captions_language` | str | = `language` | Language of the caption track |
| `made_for_kids` | bool | `false` | YouTube's required audience declaration |

Either `folder` or `video_path` is required. Explicit parameters override what the folder
supplies. Without a folder, `title` is required; the rest are optional.

Returns one of three outcomes:

- **done** — the watch link, the Studio edit link, whether YouTube classified it as a
  Short (alongside the file's orientation and duration), and exactly what was applied
  (title, visibility or schedule, languages, which files).
- **needs attention** — the video exists on the channel (links given) but something did
  not apply or did not read back as asked; lists what. The tool never re-uploads it.
- **failed** — nothing was created on the channel; the reason and failure evidence.

"Created" means Studio has assigned a video id. Any failure after that point is
"needs attention", never "failed", so a retry can never produce a duplicate.

### `upload_yt_series`

Starts a batch upload in the background and returns a job id immediately.

```json
{
  "videos": [
    { "folder": ".../01-what-is-a-harness",  "publish_at": "2026-11-02T18:00:00+05:30" },
    { "folder": ".../02-context-engineering", "publish_at": "2026-11-04T09:30:00+05:30" },
    { "folder": ".../03-instruction-layer",   "visibility": "unlisted" },
    { "folder": ".../04-memory-state" }
  ],
  "defaults": { "language": "en", "made_for_kids": false, "visibility": "private" },
  "resume_job_id": null
}
```

- `videos`: ordered list; each entry accepts exactly the parameters of `upload_yt_video`.
- `defaults`: fills only fields an entry leaves out. Any parameter may appear here.
- Every entry is validated before anything is uploaded; if any entry is invalid, the
  whole call is rejected with every problem listed, and nothing is uploaded.
- The session is checked before the job starts. If not logged in, the login window is
  opened and the call returns "login pending" without starting a job.
- Videos upload one at a time, in list order. A failed video is recorded and skipped.
  `publish_at` is re-checked just before each entry uploads, since a long batch can push
  a near time into the past; that entry then fails instead of publishing at once.
- If the session ends mid-batch, the remaining entries fail as "not logged in" and the
  login window is opened once.
- `resume_job_id`: given alone (no `videos` or `defaults`), re-runs that job's stored
  entries, retrying only `failed` and `interrupted` ones that have no video id.

### `get_yt_upload_status`

Takes a job id. Reports per video: `waiting`, `uploading`, `done` (with links),
`needs_attention` (links and what did not apply), `failed` (reason and failure-evidence
paths), or `interrupted` (the server stopped mid-job; includes the video id if Studio had
already created it). Ends with totals and, once finished, every non-`done` entry.

## Folder convention

For a folder `<dest>/<NN>-<slug>/` written by the explainer-video plugin:

| File | Rule |
|---|---|
| video | exactly one `*.mp4` |
| `title.txt` | first line, stripped |
| `description.md` | whole file, used verbatim (it is plain text despite the extension) |
| `captions.srt` | used if present |
| thumbnail | `thumbnail.png` or `thumbnail.jpg`/`.jpeg`, if present; `thumbnail.svg` is ignored with a warning |

Missing optional files are fine; a missing or ambiguous video file is an error. Batch
folders are always listed explicitly by the caller; the tool does not scan a parent.

## Validation (before any upload)

- Title: 1–100 characters, no `<` or `>`.
- Description: ≤ 5000 characters, no `<` or `>`.
- Thumbnail: PNG or JPG, ≤ 2 MB.
- Captions: `.srt` (other formats Studio accepts may be allowed later).
- `publish_at`: must carry a UTC offset (naive times are rejected), must be in the
  future, and requires `visibility` to be absent. If Studio's scheduler cannot express the
  exact time, the upload fails validation rather than rounding.
- Shorts: no validation — YouTube decides (square or vertical, ≤ 3 minutes). The result
  reports YouTube's classification (a `/shorts/…` link) next to the file's orientation and
  duration, read with `ffprobe` if it is on `PATH` (omitted if not).

## Session and login

**Profile.** A dedicated Brave user-data directory, default
`~/.mcp-youtube-extract/profile`, created with mode 700. Cookies never leave it. The spike's
logged-in profile at `~/yt-spike/profile` can be moved there to avoid a re-login.

**Session check** (first step of every upload, and of each batch entry): open the profile
headless, go to `https://youtube.com/upload`, click Studio's "Skip to YouTube Studio" on
the unsupported-browser notice if shown, then:

- lands on `studio.youtube.com/channel/<id>/…` and `<id>` equals the configured channel →
  proceed;
- lands on another channel id → refuse: "profile is signed in to <other>, expected <id>";
- lands on `accounts.google.com` → not logged in → start login.

**Login.** Launch Brave as a plain subprocess — not under Playwright — with
`--user-data-dir=<profile>` at YouTube's sign-in page continuing to Studio upload. Google
refuses sign-in inside automated browsers, so this window must not be automated. The tool
returns at once: "A Brave window has opened. Sign in with the channel's Google account,
confirm Studio shows the channel, then close that window and retry." While that window
is open the profile is locked; any call in that state returns "login window still open —
finish signing in and close it" instead of failing. (Detect via Chromium's
`SingletonLock` in the profile, or the process list.)

**CLI.** `mcp_youtube_extract --login` does the same from a terminal and waits until the
window is closed and the session check passes.

## Backend: Studio upload dialog (now)

Playwright (Python) driving the installed Brave via `launch_persistent_context(profile,
executable_path=<brave>, headless=True, ignore_default_args=["--use-mock-keychain"])`.
The mock-keychain default must be dropped, or the profile's Keychain-encrypted cookies
are unreadable.

**Proven by the spike** (`~/yt-spike/spike.py`, 2026-10-23, headed and headless):
opening the dialog at `https://youtube.com/upload`; the "Skip to YouTube Studio" click in
headless; `input[type='file']` for the video; title via `#title-textarea #textbox`
(select-all, type); made-for-kids radio `VIDEO_MADE_FOR_KIDS_NOT_MFK`; `#next-button` ×3;
visibility radio `PRIVATE`; waiting until `ytcp-video-upload-progress` no longer says
uploading; reading the video link; `#done-button`.

**Not yet proven — the builder must discover each against live Studio, with a private
test upload:** description, thumbnail upload, video language and title/description
language (under "Show more"; map BCP-47 codes to Studio's language names), caption upload
(Video elements → Subtitles → upload file with timing, in the given language),
unlisted/public, and scheduling (date and time picker, in the browser's local time zone —
convert `publish_at` accordingly).

**Failure evidence.** On any failed step: the step name, a screenshot and the page's
visible text saved under `~/.mcp-youtube-extract/failures/<timestamp>-<step>.png|.txt`,
paths returned in the result. Studio's markup will change; this is how breakage gets
diagnosed.

**After the upload**, re-open the video's Studio page and read back title, visibility or
schedule, and caption tracks; any mismatch makes the outcome "needs attention", never a
silent success.

## Backend: Data API (later)

Same tool inputs. `videos.insert` (status.privacyStatus private + status.publishAt for
schedules; snippet.defaultLanguage, snippet.defaultAudioLanguage), `captions.insert`,
`thumbnails.set`; OAuth scopes `youtube.upload` and `youtube.force-ssl`; token stored
outside the repo with mode 600. Selected by configuration. Only the interface needs to
exist now: a backend protocol with `ensure_session()` and `upload(spec) -> result`.

## Configuration

Environment variables, set in the MCP server's `env` (as `YOUTUBE_API_KEY` already is):

| Variable | Default | Notes |
|---|---|---|
| `YT_UPLOAD_CHANNEL_ID` | none — upload tools refuse to run without it | `UCDzx6hNPpuha4fCwYA5WAyg` |
| `YT_UPLOAD_PROFILE_DIR` | `~/.mcp-youtube-extract/profile` | |
| `YT_UPLOAD_BROWSER` | `/Applications/Brave Browser.app/Contents/MacOS/Brave Browser` | must be the browser that created the profile |
| `YT_UPLOAD_HEADLESS` | `true` | `false` shows the window, for debugging |

## Concurrency and lifecycle

- One browser on the profile at a time: uploads are serialized by a process-wide lock.
  A `upload_yt_video` call while a batch is running waits its turn (or returns "busy"
  — builder's call, but it must not fail obscurely).
- The batch runs in a background thread of the server process. Job state is written to
  `~/.mcp-youtube-extract/jobs/<job_id>.json` after every change, so status survives.
- This is a stdio server: Claude Code owns its process. If the session ends, a running
  batch stops. On next start, jobs left `uploading` are marked `interrupted`;
  `resume_job_id` finishes them without re-uploading done entries.

## Code layout

```
src/mcp_youtube_extract/
  tools/video_upload/tool.py      upload_yt_video
  tools/series_upload/tool.py     upload_yt_series
  tools/upload_status/tool.py     get_yt_upload_status
  shared/upload/spec.py           UploadSpec, folder resolution, defaults merge, validation
  shared/upload/backend.py        backend protocol + selection
  shared/upload/session.py        profile, session check, login launch, lock detection
  shared/upload/studio.py         Studio dialog steps (Playwright)
  shared/upload/jobs.py           batch runner, persisted job state, resume
server.py                          register the three tools; `--login` flag in main()
```

New dependency: `playwright` (Python). No Playwright browser download — it drives the
installed Brave. Update the server's `instructions` and name, and the README, to mention
uploads.

## Testing

- Unit tests (no browser, no network): folder resolution, defaults merge, every
  validation rule, time-zone handling of `publish_at`, job state transitions, resume
  skipping done entries, lock/busy behaviour.
- Studio steps: live smoke tests that each perform one private upload, run only when
  `YT_UPLOAD_LIVE_TESTS=1`. Each one's test video must be deleted afterwards (manually
  is acceptable).

## Risks

- **Terms of Service.** Automating Studio is outside YouTube's terms; the channel carries
  that risk until the official backend replaces this one.
- **Studio markup changes** break selectors without notice; mitigated by step-level
  failure evidence and read-back verification.
- **Visible automation.** `navigator.webdriver` is true and headless reports
  `HeadlessChrome`. YouTube accepted it on 2026-10-23; no disguise is to be added.
- **Session lifetime** in the dedicated profile is unmeasured beyond one day.

## Calls made by the designer (not discussed with the owner)

Defaults (`private`, `en`, made-for-kids `false`); the three-outcome result
(done / needs attention / failed); validating a whole batch before starting; checking the
session before starting a batch; read-back verification after upload; the profile, job and
failure-evidence locations under `~/.mcp-youtube-extract/`; configuration by environment
variable; the login tool call returning at once rather than waiting inline; thumbnail file
names `thumbnail.png` / `thumbnail.jpg`.

## Left to the builder

Studio selectors for the unproven steps; how busy calls behave during a batch; how the
login window's closing is detected; exact result wording.
