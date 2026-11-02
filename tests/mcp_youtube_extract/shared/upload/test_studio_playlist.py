"""Tests for the Studio playlist steps' sequencing and outcomes, with the page steps faked."""

from contextlib import contextmanager
from datetime import datetime

import pytest

from mcp_youtube_extract.shared.upload import studio_playlist as sp
from mcp_youtube_extract.shared.upload.playlist import VideoFacts, build_playlist_spec, format_outcome

A, B, C = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"


@pytest.fixture
def spec(cfg):
    spec, _ = build_playlist_spec({"name": "Course", "visibility": "unlisted", "video_ids": [C, A, B]}, cfg)
    return spec


class Steps:
    """Records what the create flow does, standing in for the browser."""

    def __init__(self, monkeypatch, spec, existing=(), fail_at=None, playlist_order=None):
        self.calls = []
        self.fail_at = fail_at
        self.existing = existing
        self.current = None
        self.order = list(spec.video_ids) if playlist_order is None else playlist_order
        facts = [VideoFacts(v, title=f"T{v[0]}", visibility="private") for v in spec.video_ids]
        fake = {
            "read_videos": lambda page, s: facts,
            "read_existing_names": self.existing_names,
            "open_edit_page": self.opener,
            "read_edit_page": lambda page: ("t", "private", "Private"),
            "open_picker": lambda page: self.step("picker") or "picker",
            "click_new_playlist": lambda page, picker: self.step("new"),
            "creation_form": lambda page: "form",
            "fill_creation_form": lambda page, form, s: self.step("fill"),
            "click_create": lambda page, form: self.step("create"),
            "tick": lambda page, picker, name: self.step(f"tick {name}"),
            "close_picker": lambda picker: self.step("done"),
            "save_edit_page": lambda page: self.step("save"),
            "find_playlist": lambda page, s: (self.step("find") or ("PLcreated123", s.visibility)),
            "read_playlist_videos": lambda page, pid, n: self.order,
            "save_evidence": lambda page, d, step, now: [f"/evidence/{step}"],
        }
        for name, fn in fake.items():
            monkeypatch.setattr(sp, name, fn)

    def existing_names(self, page, s, facts):
        if self.existing is None:
            raise sp.StepFailed("could not read every playlist the Playlists picker lists for 'Course'\nmore")
        return list(self.existing)

    def opener(self, page, video_id):
        self.current = video_id
        self.step(f"open {video_id}")

    def step(self, label):
        self.calls.append(label)
        if self.fail_at and label == self.fail_at:
            raise RuntimeError(f"boom at {label}\nsecond line")


def run(spec, cfg):
    return sp._create_steps(object(), spec, cfg, lambda: datetime(2026, 11, 2))


def test_creates_from_first_video_and_adds_the_rest_in_order(monkeypatch, spec, cfg):
    steps = Steps(monkeypatch, spec)
    outcome = run(spec, cfg)
    assert outcome.status == "done" and outcome.playlist_id == "PLcreated123" and outcome.problems == []
    opened = [c.split()[1] for c in steps.calls if c.startswith("open ")]
    assert opened == [C, A, B]
    assert steps.calls.count("create") == 1
    assert steps.calls.index("create") < steps.calls.index(f"open {A}")
    assert steps.calls.count("tick Course") == 3 and steps.calls.count("save") == 3
    assert outcome.applied["visibility"] == "unlisted"
    assert outcome.applied["videos added, in order"] == f"1. {C} Tc; 2. {A} Ta; 3. {B} Tb"


def test_preview_problems_stop_before_anything_is_created(monkeypatch, spec, cfg):
    steps = Steps(monkeypatch, spec, existing=["Course"])
    outcome = run(spec, cfg)
    assert outcome.status == "failed" and "already has a playlist named 'Course'" in outcome.problems[0]
    assert steps.calls == []


def test_failure_before_create_is_failed(monkeypatch, spec, cfg):
    Steps(monkeypatch, spec, fail_at="fill")
    outcome = run(spec, cfg)
    assert outcome.status == "failed" and outcome.problems == ["fill new playlist form: boom at fill"]
    assert outcome.evidence == ["/evidence/playlist fill new playlist form"]


def test_failure_on_create_click_may_have_created(monkeypatch, spec, cfg):
    Steps(monkeypatch, spec, fail_at="create")
    outcome = run(spec, cfg)
    assert outcome.status == "needs_attention"
    assert any("may exist on the channel" in p for p in outcome.problems)


def test_failure_mid_way_stops_and_lists_what_was_not_added(monkeypatch, spec, cfg):
    steps = Steps(monkeypatch, spec, fail_at=f"open {B}")
    outcome = run(spec, cfg)
    assert outcome.status == "needs_attention"
    assert outcome.problems == [f"open video 3 ({B}): boom at open {B}", f"not added: {B}"]
    assert outcome.applied["videos added, in order"] == f"1. {C} Tc; 2. {A} Ta"
    assert "find" not in steps.calls


def test_readback_mismatch_is_needs_attention(monkeypatch, spec, cfg):
    Steps(monkeypatch, spec, playlist_order=[A, C, B])
    outcome = run(spec, cfg)
    assert outcome.status == "needs_attention" and outcome.playlist_id == "PLcreated123"
    assert outcome.problems == [f"video order is {A}, {C}, {B}, expected {C}, {A}, {B}"]


def test_unreadable_video_says_why_without_claiming_it_is_not_the_channels(monkeypatch):
    def slow(page):
        raise TimeoutError("Timeout 30000ms exceeded.\nCall log: ...")

    monkeypatch.setattr(sp, "open_edit_page", lambda page, video_id: None)
    monkeypatch.setattr(sp, "read_edit_page", slow)
    facts = sp.read_video_facts(object(), A)
    assert facts.title is None and "could not be read from Studio" in facts.problem
    assert facts.problem.endswith("(Timeout 30000ms exceeded.)")


# -- the Playlists picker, in a real browser -------------------------------------------

PICKER_HTML = """
<div id="dialog">
  <input id="search-input">
  <div id="empty" style="display:none"></div>
  <div id="list" style="height:120px; overflow-y:auto; position:relative">
    <div id="spacer" style="position:relative"></div>
  </div>
  <button>New playlist</button><button>Done</button>
</div>
<script>
function start({playlists, loadMs, filterMs, ignoreSearch, keepScroll, blankMs, emptyText}) {
  const ROW = 30, list = document.getElementById('list'), spacer = document.getElementById('spacer');
  const empty = document.getElementById('empty'), input = document.getElementById('search-input');
  const checked = new Set();
  let shown = [], stale = [], range = '';
  window.checkedNames = () => [...checked].map(i => playlists[i]);
  function row(index, top) {
    const ve = document.createElement('ytcp-ve');
    ve.innerHTML = '<label><div role="checkbox"></div><span class="label-text"></span></label>';
    const label = ve.querySelector('label');
    if (top === null) {
      ve.style.display = 'none';
    } else {
      label.style.cssText = `position:absolute; top:${top}px; height:${ROW}px; display:block`;
    }
    ve.querySelector('.label-text').textContent = playlists[index];
    ve.querySelector('[role=checkbox]').setAttribute('aria-checked', String(checked.has(index)));
    ve.querySelector('.label-text').onclick = () => {
      checked.has(index) ? checked.delete(index) : checked.add(index);
      render(true);
    };
    return ve;
  }
  function show(indices, blank) {
    shown = indices;
    empty.textContent = emptyText;
    empty.style.display = !blank && !indices.length && emptyText ? 'block' : 'none';
    render(true);
  }
  function render(force) {
    spacer.style.height = (shown.length * ROW) + 'px';
    const first = Math.floor(list.scrollTop / ROW), last = Math.ceil((list.scrollTop + list.clientHeight) / ROW);
    if (!force && range === `${first}-${last}`) return;
    range = `${first}-${last}`;
    spacer.innerHTML = '';
    stale.forEach(index => spacer.appendChild(row(index, null)));
    shown.slice(first, last).forEach((index, i) => spacer.appendChild(row(index, (first + i) * ROW)));
  }
  function filtered() {
    const query = input.value.toLowerCase();
    if (ignoreSearch) return shown;
    return playlists.map((_, i) => i).filter(i => playlists[i].toLowerCase().includes(query));
  }
  function apply() {
    stale = shown.slice(0, 15);
    const rows = filtered();
    if (!keepScroll) list.scrollTop = 0;
    show(rows, false);
  }
  window.addPlaylist = (name) => { playlists.push(name); show(filtered(), false); };
  list.addEventListener('scroll', () => render(false));
  input.addEventListener('input', () => {
    setTimeout(() => {
      if (!blankMs) return apply();
      show([], true);
      setTimeout(apply, blankMs);
    }, filterMs);
  });
  show([], true);
  setTimeout(() => show(playlists.map((_, i) => i), false), loadMs);
}
</script>
"""

PYTHONS = [f"Python {n}" for n in range(1, 31)] + ["Python", "Other"]


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        with sync_api.sync_playwright() as p:
            launched = p.chromium.launch(headless=True)
            yield launched
            launched.close()
    except Exception as error:
        pytest.skip(f"no headless Chromium: {error}")


@pytest.fixture
def open_picker_page(browser, monkeypatch):
    monkeypatch.setattr(sp, "_POLL_MS", 50)
    pages = []

    def opener(playlists, load_ms=200, filter_ms=200, ignore_search=False, keep_scroll=False,
               blank_ms=0, empty_text="No playlists available"):
        page = browser.new_page()
        pages.append(page)
        page.set_content(PICKER_HTML)
        page.evaluate("(config) => start(config)", {
            "playlists": playlists, "loadMs": load_ms, "filterMs": filter_ms, "ignoreSearch": ignore_search,
            "keepScroll": keep_scroll, "blankMs": blank_ms, "emptyText": empty_text,
        })
        return page, page.locator("#dialog")

    yield opener
    for page in pages:
        page.close()


def test_search_reads_every_match_beyond_the_rows_in_view(open_picker_page):
    page, picker = open_picker_page(PYTHONS)
    names = sp.search_picker(page, picker, "Python")
    assert sorted(names) == sorted(PYTHONS[:-1])


def test_a_new_name_reads_as_empty_and_its_new_playlist_is_ticked(open_picker_page):
    page, picker = open_picker_page(PYTHONS)
    assert sp.search_picker(page, picker, "Linear Algebra 2026") == []
    page.evaluate("addPlaylist('Linear Algebra 2026')")
    sp.tick(page, picker, "Linear Algebra 2026")
    assert page.evaluate("checkedNames()") == ["Linear Algebra 2026"]


def test_a_single_existing_match_is_read_once_and_ticked(open_picker_page):
    page, picker = open_picker_page(["k8s"] + [f"Course {n}" for n in range(14)])
    assert sp.search_picker(page, picker, "k8s") == ["k8s"]
    sp.tick(page, picker, "k8s")
    assert page.evaluate("checkedNames()") == ["k8s"]


def test_slow_filter_that_keeps_the_scroll_offset_still_reads_from_the_top(open_picker_page):
    newest_first = [f"Python {n}" for n in range(6, 0, -1)] + [f"Other {n}" for n in range(12)] + ["Python"]
    page, picker = open_picker_page(newest_first, filter_ms=1500, keep_scroll=True)
    names = sp.search_picker(page, picker, "Python")
    assert sorted(names) == sorted([f"Python {n}" for n in range(1, 7)] + ["Python"])


def test_a_list_that_blanks_while_it_filters_is_not_read_as_empty(open_picker_page):
    page, picker = open_picker_page(PYTHONS, blank_ms=1200)
    names = sp.search_picker(page, picker, "Python")
    assert "Python" in names and len(names) == 31


def test_tick_scrolls_to_the_exact_row_below_the_view_and_ticks_only_it(open_picker_page):
    page, picker = open_picker_page(PYTHONS)
    sp.tick(page, picker, "Python")
    assert page.evaluate("checkedNames()") == ["Python"]


def test_tick_refuses_two_playlists_with_the_same_name(open_picker_page):
    page, picker = open_picker_page(["Python", "Python", "Other"])
    with pytest.raises(sp.StepFailed, match="more than one playlist named 'Python'"):
        sp.tick(page, picker, "Python")
    assert page.evaluate("checkedNames()") == []


def test_an_empty_list_counts_only_when_studio_says_no_playlists_available(open_picker_page):
    page, picker = open_picker_page(["Other"])
    assert sp.search_picker(page, picker, "Python") == []
    page, picker = open_picker_page([])
    assert sp.search_picker(page, picker, "Python") == []


def test_an_empty_list_without_studio_saying_so_fails_the_step(open_picker_page, monkeypatch):
    monkeypatch.setattr(sp, "_PASSES", 3)
    page, picker = open_picker_page(["Other"], empty_text="")
    with pytest.raises(sp.StepFailed, match="could not read every playlist"):
        sp.search_picker(page, picker, "Python")


def test_search_that_never_filters_fails_the_step(open_picker_page, monkeypatch):
    monkeypatch.setattr(sp, "_PASSES", 3)
    page, picker = open_picker_page(PYTHONS, ignore_search=True)
    with pytest.raises(sp.StepFailed, match="could not read every playlist"):
        sp.search_picker(page, picker, "Python")


# -- when the picker cannot be read, nothing is created ------------------------------


def test_unreadable_picker_in_preview_reports_the_cause_and_evidence(monkeypatch, spec, cfg):
    @contextmanager
    def no_browser(s, config):
        yield object()

    def unreadable(page, video_id, name):
        raise sp.StepFailed("the Playlists picker's list did not settle\ncall log")

    monkeypatch.setattr(sp, "studio_page", no_browser)
    monkeypatch.setattr(sp, "read_video_facts", lambda page, v: VideoFacts(v, title="T", visibility="public"))
    monkeypatch.setattr(sp, "read_matching_names", unreadable)
    monkeypatch.setattr(sp, "save_evidence", lambda page, d, step, now: [f"/evidence/{step}.png"])
    facts, problems = sp.preview(spec, cfg)
    assert [f.video_id for f in facts] == [C, A, B] and len(problems) == 1
    assert "(the Playlists picker's list did not settle)" in problems[0] and "call log" not in problems[0]
    assert "nothing was created" in problems[0] and "/evidence/playlist read playlist names.png" in problems[0]


def test_unreadable_picker_stops_create_with_needs_attention_and_creates_nothing(monkeypatch, spec, cfg):
    steps = Steps(monkeypatch, spec, existing=None)
    outcome = run(spec, cfg)
    assert outcome.status == "needs_attention" and outcome.created is False and steps.calls == []
    assert "(could not read every playlist the Playlists picker lists for 'Course')" in outcome.problems[0]
    assert "nothing was created" in outcome.problems[0]
    assert outcome.evidence == ["/evidence/playlist read playlist names"]
    assert format_outcome(spec, outcome).startswith("Playlist not created; needs attention")
