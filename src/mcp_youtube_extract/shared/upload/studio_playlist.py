"""Create a playlist through YouTube Studio, in the channel's browser profile.

Studio creates a playlist from a video's own edit page: its "Playlists" picker has a
"New playlist" button. So the first video's edit page creates the playlist and ticks
it, and each later video's edit page ticks it in turn. Studio sorts a new playlist by
"Date published (newest)" unless told otherwise, so the form sets "Manually sorted";
then every tick appends the video to the end, and adding them one by one in the asked
order gives that order. The picker selects playlists by name, which is why a name the
channel already uses is refused before anything is created.

As in studio.py, each step has a name, and a failure leaves a screenshot and the page's
visible text behind.
"""

import re
from contextlib import contextmanager
from datetime import datetime
from typing import Callable

from ..logger import get_logger
from . import session
from .config import UploadConfig
from .playlist import (
    PlaylistOutcome,
    PlaylistSpec,
    VideoFacts,
    compare_playlist_readback,
    preview_problems,
    unread_names_problem,
)
from .studio import StepFailed, read_edit_page, save_evidence, visibility_word

logger = get_logger(__name__)

_STEP_TIMEOUT_MS = 30_000
_PICKER_TRIGGER = "ytcp-video-metadata-playlists ytcp-text-dropdown-trigger"
# The custom-element hosts report no size; their inner paper dialogs are what shows.
_PICKER = "ytcp-playlist-dialog tp-yt-paper-dialog"
_FORM = "ytcp-playlist-creation-dialog tp-yt-paper-dialog"
_MANUAL_ORDER = "Manually sorted"
_PLAYLIST_LINK = re.compile(r"(?:[?&]list=|/playlist/)([A-Za-z0-9_-]{10,})")


@contextmanager
def studio_page(spec: PlaylistSpec, config: UploadConfig):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            **session.persistent_context_args(spec.channel, config, headless=config.headless)
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(_STEP_TIMEOUT_MS)
            yield page
        finally:
            context.close()


# -- reading --------------------------------------------------------------------


def open_edit_page(page, video_id: str) -> None:
    page.goto(f"https://studio.youtube.com/video/{video_id}/edit")
    session.skip_unsupported_notice(page)


def first_line(error: Exception) -> str:
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__


def read_video_facts(page, video_id: str) -> VideoFacts:
    """Title and visibility of one of the channel's videos, from its Studio edit page."""
    open_edit_page(page, video_id)
    try:
        title, visibility, _ = read_edit_page(page)
    except Exception as error:
        return VideoFacts(video_id, problem=(
            f"could not be read from Studio; check it is one of this channel's videos, or try again ({first_line(error)})"
        ))
    return VideoFacts(video_id, title=title, visibility=visibility)


def open_picker(page):
    trigger = page.locator(_PICKER_TRIGGER).first
    trigger.scroll_into_view_if_needed()
    trigger.click()
    picker = page.locator(_PICKER).first
    picker.wait_for(state="visible")
    return picker


_POLL_MS = 500
_SCAN_POLLS = 120
_PASSES = 30

_LIST_JS = r"""(picker, [query, move]) => {
    const norm = (text) => text.replace(/\s+/g, ' ').trim().toLowerCase();
    const visible = (el) => el.getBoundingClientRect().height > 0
        && getComputedStyle(el.closest('ytcp-ve') || el).display !== 'none';
    const scrolls = (el) => el.scrollHeight > el.clientHeight + 1
        && /(auto|scroll)/.test(getComputedStyle(el).overflowY);
    const labels = [...picker.querySelectorAll('.label-text')].filter(visible);
    const names = labels.map(el => el.innerText.trim()).filter(Boolean);
    let box = labels.length ? labels[0].parentElement : null;
    while (box && !scrolls(box)) box = box === picker ? null : box.parentElement;
    const rows = labels.map(el => (el.closest('label, li') || el).getBoundingClientRect()).filter(r => r.height > 0);
    const row = rows.length ? Math.min(...rows.map(r => r.height)) : 1;
    const atEnd = !box || box.scrollTop + box.clientHeight >= box.scrollHeight - row;
    let covered = true;
    if (box && rows.length) {
        const area = box.getBoundingClientRect();
        covered = Math.min(...rows.map(r => r.top)) - area.top < row
            && (atEnd || area.bottom - Math.max(...rows.map(r => r.bottom)) < row);
    }
    const emptyShown = !names.length
        && picker.innerText.split('\n').some(line => line.trim() === 'No playlists available');
    if (box && move === 'top') box.scrollTop = 0;
    if (box && move === 'down') box.scrollTop += Math.max(1, Math.floor(box.clientHeight / 2));
    return {
        names,
        matches: names.every(n => norm(n).includes(norm(query))),
        exact: names.filter(n => n === query).length,
        atEnd,
        covered,
        emptyShown,
    };
}"""


def settled_view(page, picker, name: str) -> dict:
    """The picker's visible rows once they fill the list's visible area and two reads
    agree: the list renders its rows a moment after it scrolls or filters, and keeps
    rows it no longer shows in the page, hidden."""
    previous = None
    for _ in range(_SCAN_POLLS):
        page.wait_for_timeout(_POLL_MS)
        view = picker.evaluate(_LIST_JS, [name, None])
        if view["covered"] and view == previous:
            return view
        previous = view
    raise StepFailed("the Playlists picker's list did not settle")


def scan_from_top(page, picker, name: str) -> list[str] | None:
    """One pass over the searched list from the top to its end, collecting the names at
    each position. None when the pass cannot count: a row that does not match the name
    (the search has not filtered the list yet), or no rows without Studio showing "No
    playlists available"."""
    picker.evaluate(_LIST_JS, [name, "top"])
    found: list[str] = []
    for _ in range(_SCAN_POLLS):
        view = settled_view(page, picker, name)
        if not view["names"]:
            return [] if view["emptyShown"] and not found else None
        if not view["matches"]:
            return None
        found += [n for n in dict.fromkeys(view["names"]) if n not in found]
        if view["atEnd"]:
            return found
        picker.evaluate(_LIST_JS, [name, "down"])
    raise StepFailed(f"the Playlists picker's list for '{name}' did not reach its end")


def search_picker(page, picker, name: str) -> list[str]:
    """Search the picker for the name; return every playlist name it then lists.

    Its list renders only the rows in view, so each pass scrolls the filtered list from
    the top to its end. The result counts only once two passes in a row agree, and an
    empty result only when Studio shows "No playlists available". Otherwise it raises
    StepFailed."""
    picker.locator("input#search-input").fill(name)
    previous = None
    for _ in range(_PASSES):
        found = scan_from_top(page, picker, name)
        if found is not None and found == previous:
            return found
        previous = found
    raise StepFailed(f"could not read every playlist the Playlists picker lists for '{name}'")


def show_row(page, picker, name: str) -> None:
    """Scroll the searched picker from the top until the playlist named exactly `name`
    is in view; refuse if more than one row in view has that name."""
    picker.evaluate(_LIST_JS, [name, "top"])
    for _ in range(_SCAN_POLLS):
        view = settled_view(page, picker, name)
        if view["exact"] > 1:
            raise StepFailed(f"the Playlists picker lists more than one playlist named '{name}'")
        if view["exact"] == 1:
            return
        if view["atEnd"]:
            break
        picker.evaluate(_LIST_JS, [name, "down"])
    raise StepFailed(f"the Playlists picker does not list '{name}'")


_TICKED_JS = """(picker, name) => {
    const label = [...picker.querySelectorAll('.label-text')]
        .find(el => el.getBoundingClientRect().height > 0 && el.innerText.trim() === name);
    const row = label && label.closest('label, li');
    const box = row && row.querySelector('[role="checkbox"]');
    return box ? box.getAttribute('aria-checked') === 'true' : null;
}"""


def is_ticked(picker, name: str) -> bool | None:
    """True/False for the playlist's checkbox in the picker; None if it is not listed."""
    return picker.evaluate(_TICKED_JS, name)


def read_matching_names(page, video_id: str, name: str) -> list[str]:
    """The channel's playlist names that Studio's picker finds when searching for `name`."""
    open_edit_page(page, video_id)
    read_edit_page(page)
    picker = open_picker(page)
    names = search_picker(page, picker, name)
    page.keyboard.press("Escape")
    return names


def read_videos(page, spec: PlaylistSpec) -> list[VideoFacts]:
    return [read_video_facts(page, video_id) for video_id in spec.video_ids]


def read_existing_names(page, spec: PlaylistSpec, facts: list[VideoFacts]) -> list[str]:
    """The channel's playlist names matching the name, from the first readable video's
    picker. Raises when they cannot all be read."""
    readable = next((f.video_id for f in facts if not f.problem), None)
    return read_matching_names(page, readable, spec.name) if readable else []


# -- creating -------------------------------------------------------------------


def click_new_playlist(page, picker) -> None:
    """The button opens a menu (New playlist / New podcast / New course)."""
    picker.locator("ytcp-button.new-playlist-button").click()
    page.locator("tp-yt-paper-item[test-id='new_playlist']").click()


def creation_form(page):
    form = page.locator(_FORM).first
    form.wait_for(state="visible")
    return form


def choose(page, form, host: str, item) -> str:
    """Open one of the form's dropdowns, pick the item, and return what the dropdown shows."""
    trigger = form.locator(f"{host} #menu-button")
    trigger.click()
    item.click()
    page.wait_for_timeout(300)
    return trigger.inner_text()


def fill_creation_form(page, form, spec: PlaylistSpec) -> None:
    title = form.locator("#title-textarea #textbox").first
    title.click()
    page.keyboard.press("Meta+A")
    page.keyboard.type(spec.name)

    test_id = spec.visibility.upper()
    shown = choose(page, form, "ytcp-playlist-metadata-visibility",
                   page.locator(f"#visibility-menu tp-yt-paper-item[test-id='{test_id}']"))
    if visibility_word(shown.replace("Visibility", "")) != spec.visibility:
        raise StepFailed(f"the form shows '{shown.strip()}', expected {spec.visibility}")

    shown = choose(page, form, "ytcp-playlist-metadata-sorting",
                   page.locator("#sorting-menu tp-yt-paper-item").filter(has_text=_MANUAL_ORDER))
    if _MANUAL_ORDER not in shown:
        raise StepFailed(f"the form shows '{shown.strip()}', expected {_MANUAL_ORDER}")


def click_create(page, form) -> None:
    form.locator("#create-button").click()
    form.wait_for(state="hidden")


def tick(page, picker, name: str) -> None:
    """Tick the named playlist in the picker; a playlist just created may already be ticked."""
    if name not in search_picker(page, picker, name):
        raise StepFailed(f"the Playlists picker does not list '{name}'")
    show_row(page, picker, name)
    state = is_ticked(picker, name)
    if state is None:
        raise StepFailed(f"the Playlists picker shows no checkbox for '{name}'")
    if not state:
        picker.locator(".label-text:visible").filter(has_text=re.compile(rf"^\s*{re.escape(name)}\s*$")).first.click()
        page.wait_for_timeout(300)
    if is_ticked(picker, name) is not True:
        raise StepFailed(f"could not tick '{name}' in the Playlists picker")


def close_picker(picker) -> None:
    picker.locator("ytcp-button.done-button").click()
    picker.wait_for(state="hidden")


def save_edit_page(page) -> None:
    page.locator("#save").first.click()
    page.wait_for_function(
        """() => {
            const save = document.querySelector('#save');
            return !save || save.hasAttribute('disabled') || save.getAttribute('aria-disabled') === 'true';
        }""",
        timeout=_STEP_TIMEOUT_MS,
    )


# -- reading the created playlist back --------------------------------------------


_FIND_ROW_JS = """(name) => {
    const link = [...document.querySelectorAll('a[href*="list="], a[href*="/playlist/"]')]
        .find(a => a.innerText.trim() === name);
    if (!link) return null;
    const row = link.closest('ytcp-playlist-row');
    const cell = row && row.querySelector('.visibility-cell');
    return {href: link.href, visibility: cell ? cell.innerText : ''};
}"""


def find_playlist(page, spec: PlaylistSpec) -> tuple[str, str | None]:
    """(playlist id, visibility) from the channel's Playlists list in Studio."""
    url = f"https://studio.youtube.com/channel/{spec.channel.channel_id}/content/playlists"
    for _ in range(3):
        page.goto(url)
        session.skip_unsupported_notice(page)
        try:
            page.wait_for_function(_FIND_ROW_JS, arg=spec.name, timeout=15_000)
        except Exception:
            continue
        found = page.evaluate(_FIND_ROW_JS, spec.name)
        match = _PLAYLIST_LINK.search(found["href"])
        if match:
            return match.group(1), visibility_word(found["visibility"])
    raise StepFailed(f"Studio's playlist list does not show '{spec.name}'")


_PLAYLIST_VIDEOS_JS = """() => [...document.querySelectorAll('ytd-playlist-video-renderer a#video-title')]
    .map(a => a.href)"""
_WATCH_ID = re.compile(r"[?&]v=([A-Za-z0-9_-]{11})")


def read_playlist_videos(page, playlist_id: str, expected: int) -> list[str]:
    """Video ids in playlist order, from the playlist page as the signed-in owner sees it."""
    page.goto(f"https://www.youtube.com/playlist?list={playlist_id}")
    page.locator("ytd-playlist-video-renderer").first.wait_for(state="visible")
    hrefs: list[str] = []
    for _ in range(30):  # the page loads 100 videos at a time as it scrolls
        hrefs = page.evaluate(_PLAYLIST_VIDEOS_JS)
        if len(hrefs) >= expected:
            break
        page.mouse.wheel(0, 20_000)
        page.wait_for_timeout(1000)
        if len(page.evaluate(_PLAYLIST_VIDEOS_JS)) == len(hrefs):
            break
    return [m.group(1) for m in (_WATCH_ID.search(h) for h in hrefs) if m]


# -- the two jobs -------------------------------------------------------------------


def preview(
    spec: PlaylistSpec, config: UploadConfig, now: Callable[[], datetime] = datetime.now
) -> tuple[list[VideoFacts], list[str]]:
    """(facts per video in order, problems). Creates nothing."""
    with studio_page(spec, config) as page:
        facts = read_videos(page, spec)
        try:
            existing = read_existing_names(page, spec, facts)
        except Exception as error:
            evidence = save_evidence(page, config.failures_dir, "playlist read playlist names", now())
            return facts, preview_problems(spec, facts, []) + [unread_names_problem(spec.name, first_line(error), evidence)]
    return facts, preview_problems(spec, facts, existing)


def create(spec: PlaylistSpec, config: UploadConfig, now: Callable[[], datetime] = datetime.now) -> PlaylistOutcome:
    """Re-check the videos and the name, create the playlist from the first video, add the
    rest in order, then read the playlist back."""
    with studio_page(spec, config) as page:
        return _create_steps(page, spec, config, now)


def _create_steps(page, spec: PlaylistSpec, config: UploadConfig, now) -> PlaylistOutcome:
    created = False
    added: list[str] = []
    playlist_id: str | None = None
    titles: dict[str, str | None] = {}
    step = "read videos"
    try:
        facts = read_videos(page, spec)
        step = "read playlist names"
        try:
            existing = read_existing_names(page, spec, facts)
        except Exception as error:
            evidence = save_evidence(page, config.failures_dir, f"playlist {step}", now())
            return PlaylistOutcome(status="needs_attention", evidence=evidence,
                                   problems=preview_problems(spec, facts, [])
                                   + [unread_names_problem(spec.name, first_line(error))])
        problems = preview_problems(spec, facts, existing)
        if problems:
            return PlaylistOutcome(status="failed", problems=problems)
        titles = {f.video_id: f.title for f in facts}

        for position, video_id in enumerate(spec.video_ids, start=1):
            step = f"open video {position} ({video_id})"
            open_edit_page(page, video_id)
            read_edit_page(page)
            step = f"open Playlists picker for video {position}"
            picker = open_picker(page)
            if position == 1:
                step = "open new playlist form"
                click_new_playlist(page, picker)
                form = creation_form(page)
                step = "fill new playlist form"
                fill_creation_form(page, form, spec)
                step = "create playlist"
                created = True  # from the click on, the playlist may exist
                click_create(page, form)
            step = f"tick playlist for video {position}"
            tick(page, picker, spec.name)
            close_picker(picker)
            step = f"save video {position}"
            save_edit_page(page)
            added.append(video_id)
            logger.info(f"playlist '{spec.name}': added {video_id} at position {position}")

        step = "find playlist"
        playlist_id, visibility = find_playlist(page, spec)
        step = "read playlist videos"
        video_ids = read_playlist_videos(page, playlist_id, len(spec.video_ids))
        mismatches = compare_playlist_readback(
            spec, {"name": spec.name, "visibility": visibility, "video_ids": video_ids}
        )
    except Exception as error:
        evidence = save_evidence(page, config.failures_dir, f"playlist {step}", now())
        reason = f"{step}: {first_line(error)}"
        outcome = PlaylistOutcome(status="needs_attention" if created else "failed", created=created,
                                  playlist_id=playlist_id, problems=[reason], evidence=evidence)
        if created:
            not_added = [v for v in spec.video_ids if v not in added]
            outcome.applied = _applied(spec, added, titles)
            if not_added:
                outcome.problems.append(f"not added: {', '.join(not_added)}")
            if not added:
                outcome.problems.append(
                    f"the playlist '{spec.name}' may exist on the channel; check Studio before creating it again"
                )
        return outcome
    outcome = PlaylistOutcome(status="needs_attention" if mismatches else "done", created=True,
                              playlist_id=playlist_id, problems=mismatches)
    outcome.applied = _applied(spec, added, titles)
    return outcome


def _applied(spec: PlaylistSpec, added: list[str], titles: dict[str, str | None]) -> dict[str, str]:
    applied = {
        "channel": f"{spec.channel.name} ({spec.channel.channel_id})",
        "name": spec.name,
        "visibility": spec.visibility,
    }
    applied["videos added, in order"] = (
        "; ".join(f"{i}. {v}" + (f" {titles[v]}" if titles.get(v) else "") for i, v in enumerate(added, start=1))
        or "none"
    )
    return applied
