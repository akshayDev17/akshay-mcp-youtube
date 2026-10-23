# Channel upload tools — design

Status: draft for approval · 2026-10-23

## Why

The owner publishes long-form explainer videos (and sometimes Shorts) to one YouTube
channel they maintain. The videos are produced by the `explainer-video-from-coursework`
plugin (`~/github/explainer-video`), which already writes each finished video into its
own folder with a description (chapters included) and English captions. Uploading them
by hand in YouTube Studio is the remaining manual step. The goal is to let an AI
harness — Claude Code, dsh, Codex, Antigravity, whichever produced the video — upload
one video, or a whole batch, through this MCP server and have it go live.

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
- Several independent channels at once (any number), each addressed by a short name.
  The channel is chosen only by the call naming it, or else the configured default —
  never inferred from the video (shape, length, title).
- Login happens once per channel, in a browser window, and persists. It is re-requested
  only when YouTube ends that channel's session.
- Same tool inputs regardless of backend, so swapping to the official API later does not
  change how the tools are called.

## Non-goals

- The official Data API backend itself (designed for, not built now).
- An HTTP transport or Claude Code's "Authenticate" button — the server stays stdio.
- Generating any content: titles, descriptions, captions and thumbnails arrive finished.
- Playlists, tags, category, end screens, cards, editing or deleting existing videos.

## Anti-goals (failure even if it "works")

- Uploading to any channel other than the one the call named (or the default).
- Making a video more public than asked: an explicit `visibility` or `publish_at` is
  always honoured exactly, and read back to confirm.
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
- Login is handled by the server end to end: it opens the sign-in window itself, detects
  when sign-in completes, closes the window itself and continues the upload. The only
  human step is typing the Google credentials (and 2FA) into that window. No
  "Authenticate" button, and never "do X and retry" instructions for the user.
- Every upload, single or batch, runs as a server-side job, so a client-side tool-call
  timeout never interrupts an upload or a login.
- The channel is verified (uploads over 15 minutes and custom thumbnails are allowed).
- Default visibility is **public**: publishing is the point of the tool. Each tool's
  description must state this default plainly, since the callers are other agents.
- Multiple channels, maintained side by side; the caller names the channel, with a
  configured default. No routing by video type.
- Works with any MCP client, not only Claude Code: nothing may rely on Claude-specific
  behaviour (the job + status design already covers clients that cut long calls short).

## Tools

All three follow the existing tool style: `@app.tool(description=...)`, one folder per
tool under `src/mcp_youtube_extract/tools/`, plain-text/markdown string results, and
errors returned as a string rather than raised.

### `upload_yt_video`

Starts a one-video job and waits for it. If the job finishes within the wait, returns its
outcome. If not — or if the client cuts the call off — the job keeps running in the
server, and the result says so with its job id for `get_yt_upload_status`. Client-side
cancellation of the tool call must not cancel the job.

Claude Code's MCP tool-call time limit is not reliably documented (reports range from
~60 s in the desktop app to unbounded in the CLI), so nothing may depend on a long call
surviving. The wait defaults to 10 minutes and is configurable (`YT_UPLOAD_CALL_WAIT`).

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `channel` | str | `YT_UPLOAD_DEFAULT_CHANNEL` | A configured channel name (e.g. `main`), or its channel id |
| `folder` | str | — | A per-video folder; files below are found in it by convention |
| `video_path` | str | from `folder` | The video file |
| `title` | str | from `folder` | Title text |
| `description` | str | from `folder` | Description text (not a path) |
| `captions_path` | str | from `folder` | Caption file (SRT) |
| `thumbnail_path` | str | from `folder` | PNG or JPG |
| `visibility` | `private` / `unlisted` / `public` | `public` | Must be omitted when `publish_at` is set |
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
  "defaults": { "language": "en", "made_for_kids": false, "visibility": "public" },
  "resume_job_id": null
}
```

- `videos`: ordered list; each entry accepts exactly the parameters of `upload_yt_video`,
  `channel` included, so one batch may span several channels.
- `defaults`: fills only fields an entry leaves out. Any parameter may appear here.
- An unknown `channel` is a validation failure for that entry.
- Every entry is validated up front. An invalid entry is marked `failed` with every
  problem it has, and skipped; the valid entries upload. The call's immediate response
  already lists the entries that failed validation.
- Videos upload one at a time, in list order. A failed video is recorded and skipped; the
  rest carry on, and every non-`done` entry is reported at the end.
- `publish_at` is re-checked just before each entry uploads, since a long batch can push
  a near time into the past; that entry then fails instead of publishing at once.
- If there is no session at the start, or it ends mid-batch, the job runs the login flow
  (see Session and login), pausing while it waits, then continues where it left off.
- `resume_job_id`: given alone (no `videos` or `defaults`), re-runs that job's stored
  entries, retrying only `failed` and `interrupted` ones that have no video id.

### `get_yt_upload_status`

Takes a job id (from either upload tool). Reports the job's state — including
`waiting for sign-in` while the login window is open — and per video: `waiting`,
`uploading`, `done` (with links),
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

**Profiles.** One dedicated Brave user-data directory per configured channel, at
`~/.mcp-youtube-extract/profiles/<name>`, created with mode 700. Cookies never leave it.
One profile per channel works whether channels belong to different Google accounts or
are Brand Account channels under one account: each profile remembers its own channel, so
nothing ever has to switch channels inside a profile. The spike's logged-in profile at
`~/yt-spike/profile` can be moved to `profiles/main` to avoid a re-login.

**Session check** (first step of every upload, and of each batch entry), on the target
channel's profile: open it headless, go to `https://youtube.com/upload`, click Studio's
"Skip to YouTube Studio" on the unsupported-browser notice if shown, then:

- lands on `studio.youtube.com/channel/<id>/…` and `<id>` equals the target channel's id →
  proceed;
- lands on another channel id → refuse: "profile is signed in to <other>, expected <id>";
- lands on `accounts.google.com` → not logged in → run the login flow, then continue.

**Login flow** — the server does everything except type the credentials:

1. Launch Brave as a plain subprocess — **not** under Playwright — with
   `--user-data-dir=<profile>` at YouTube's sign-in page, continuing to Studio upload.
   Google refuses sign-in inside automated browsers, so this window must not be
   automated. Headless is impossible here: a person has to type into it.
2. Tell the caller once, as a progress message / job state (`waiting for sign-in`), that a
   Brave window has opened for signing in to the channel's Google account. That sentence
   is for Claude to relay; it asks nothing else of the person.
3. Watch for completion without touching the window: poll the profile's cookie database
   read-only (`Default/Cookies`, opened `mode=ro&immutable=1`) for fresh YouTube login
   cookies (`LOGIN_INFO` on `.youtube.com`, plus `SAPISID`). Names and timestamps only —
   values are never read.
4. On completion, wait a few seconds for Brave to flush, then terminate the Brave
   process the server launched (graceful first). The person does not close anything.
5. Run the session check. Right channel → continue the job. Wrong channel → reopen the
   sign-in window with the message that the expected channel is `<id>` (e.g. a Brand
   Account channel needs switching to); this repeats until it matches or times out.
6. Bounded by `YT_UPLOAD_LOGIN_TIMEOUT` (default 10 minutes). On expiry the window is
   closed and the affected entries fail with "sign-in not completed".

The login flow is per channel: the window opens on that channel's profile, and the
relayed sentence names the channel. Only one login flow runs at a time per channel; a
second job needing the same channel waits on the first. If the
person closes the window themselves before signing in, that counts as cancelling the
sign-in: affected entries fail with that reason.

**CLI.** `mcp_youtube_extract --login <name>` runs the same flow from a terminal, for
anyone who prefers to sign in ahead of time. It is optional; nothing requires it.

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
| `YT_UPLOAD_CHANNELS` | none — upload tools refuse to run without it | `name=channel_id` pairs, comma-separated, e.g. `main=UCDzx6hNPpuha4fCwYA5WAyg,second=UC…`; each name's profile is `~/.mcp-youtube-extract/profiles/<name>` |
| `YT_UPLOAD_DEFAULT_CHANNEL` | the first name listed | used when a call names no channel |
| `YT_UPLOAD_BROWSER` | `/Applications/Brave Browser.app/Contents/MacOS/Brave Browser` | must be the browser that created the profile |
| `YT_UPLOAD_HEADLESS` | `true` | `false` shows the window, for debugging |
| `YT_UPLOAD_LOGIN_TIMEOUT` | `600` (seconds) | how long a job waits for sign-in |
| `YT_UPLOAD_CALL_WAIT` | `600` (seconds) | how long `upload_yt_video` waits before handing back a job id |

## Concurrency and lifecycle

- One browser per profile at a time: uploads to the same channel are serialized by a
  per-channel lock; uploads to different channels may run concurrently. A call for a
  channel that is busy queues behind the running work — it must not fail obscurely.
- Every job (single or batch) runs in a background thread of the server process. Job
  state is written to `~/.mcp-youtube-extract/jobs/<job_id>.json` after every change, so
  status survives.
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
  shared/upload/channels.py       parse YT_UPLOAD_CHANNELS, resolve name/id, profile paths
  shared/upload/session.py        per-channel profile, session check, login flow, locks
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

Approved by the owner: defaults (`public`, `en`, made-for-kids `false`); read-back
verification after upload; everything under `~/.mcp-youtube-extract/`; configuration by
environment variable.

Not yet reviewed: the three-outcome result (done / needs attention / failed); every
upload running as a job; detecting sign-in from the cookie database's login-cookie
names; the 10-minute login and call-wait defaults; thumbnail file names `thumbnail.png`
/ `thumbnail.jpg`.

## Left to the builder

Studio selectors for the unproven steps; how busy calls behave during a batch; whether
`LOGIN_INFO` + `SAPISID` appearing is a reliable "sign-in done" signal (verify against a
real sign-in; fall back to a headless session check after closing the window if not);
exact result wording.
