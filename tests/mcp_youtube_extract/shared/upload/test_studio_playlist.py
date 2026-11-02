"""Tests for the Studio playlist steps' sequencing and outcomes, with the page steps faked."""

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
        self.current = None
        self.order = list(spec.video_ids) if playlist_order is None else playlist_order
        facts = [VideoFacts(v, title=f"T{v[0]}", visibility="private") for v in spec.video_ids]
        fake = {
            "read_videos": lambda page, s: (facts, None if existing is None else list(existing)),
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
  <div id="list" style="height:120px; overflow-y:auto; position:relative">
    <div id="spacer" style="position:relative"></div>
  </div>
</div>
<script>
function start({playlists, loadMs, filterMs, ignoreSearch}) {
  const ROW = 30, list = document.getElementById('list'), spacer = document.getElementById('spacer');
  const checked = new Set();
  let shown = [], range = '';
  window.checkedNames = () => [...checked].map(i => playlists[i]);
  function render(force) {
    spacer.style.height = (shown.length * ROW) + 'px';
    const first = Math.floor(list.scrollTop / ROW), last = Math.ceil((list.scrollTop + list.clientHeight) / ROW);
    if (!force && range === `${first}-${last}`) return;
    range = `${first}-${last}`;
    spacer.innerHTML = '';
    shown.slice(first, last).forEach((index, i) => {
      const row = document.createElement('label');
      row.style.cssText = `position:absolute; top:${(first + i) * ROW}px; height:${ROW}px; display:block`;
      row.innerHTML = '<div role="checkbox"></div><span class="label-text"></span>';
      row.querySelector('.label-text').textContent = playlists[index];
      row.querySelector('[role=checkbox]').setAttribute('aria-checked', String(checked.has(index)));
      row.querySelector('.label-text').onclick = () => {
        checked.has(index) ? checked.delete(index) : checked.add(index);
        render(true);
      };
      spacer.appendChild(row);
    });
  }
  list.addEventListener('scroll', () => render(false));
  document.getElementById('search-input').addEventListener('input', (event) => {
    const query = event.target.value.toLowerCase();
    setTimeout(() => {
      if (!ignoreSearch) shown = playlists.map((_, i) => i).filter(i => playlists[i].toLowerCase().includes(query));
      list.scrollTop = 0;
      render(true);
    }, filterMs);
  });
  setTimeout(() => { shown = playlists.map((_, i) => i); render(true); }, loadMs);
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

    def opener(playlists, load_ms=200, filter_ms=200, ignore_search=False):
        page = browser.new_page()
        pages.append(page)
        page.set_content(PICKER_HTML)
        page.evaluate("(config) => start(config)", {
            "playlists": playlists, "loadMs": load_ms, "filterMs": filter_ms, "ignoreSearch": ignore_search,
        })
        return page, page.locator("#dialog")

    yield opener
    for page in pages:
        page.close()


def test_search_reads_every_match_beyond_the_rows_in_view(open_picker_page):
    page, picker = open_picker_page(PYTHONS)
    names = sp.search_picker(page, picker, "Python")
    assert sorted(names) == sorted(PYTHONS[:-1])


def test_tick_scrolls_to_the_exact_row_below_the_view_and_ticks_only_it(open_picker_page):
    page, picker = open_picker_page(PYTHONS)
    sp.tick(page, picker, "Python")
    assert page.evaluate("checkedNames()") == ["Python"]


def test_tick_refuses_two_playlists_with_the_same_name(open_picker_page):
    page, picker = open_picker_page(["Python", "Python", "Other"])
    with pytest.raises(sp.StepFailed, match="more than one playlist named 'Python'"):
        sp.tick(page, picker, "Python")
    assert page.evaluate("checkedNames()") == []


def test_search_on_a_channel_with_no_playlists_finds_none(open_picker_page):
    page, picker = open_picker_page([])
    assert sp.search_picker(page, picker, "Python") == []


def test_search_that_never_filters_fails_the_step(open_picker_page, monkeypatch):
    monkeypatch.setattr(sp, "_SCAN_POLLS", 6)
    page, picker = open_picker_page(PYTHONS, ignore_search=True)
    with pytest.raises(sp.StepFailed, match="could not read every playlist"):
        sp.search_picker(page, picker, "Python")


# -- when the picker cannot be read, nothing is created ------------------------------


def test_unreadable_picker_reads_as_unknown_names(monkeypatch, spec):
    monkeypatch.setattr(sp, "read_video_facts", lambda page, v: VideoFacts(v, title="T", visibility="public"))

    def unreadable(page, video_id, name):
        raise sp.StepFailed("could not read every playlist the Playlists picker lists for 'Course'")

    monkeypatch.setattr(sp, "read_matching_names", unreadable)
    facts, existing = sp.read_videos(object(), spec)
    assert [f.video_id for f in facts] == [C, A, B] and existing is None


def test_unreadable_picker_stops_create_with_needs_attention_and_creates_nothing(monkeypatch, spec, cfg):
    steps = Steps(monkeypatch, spec, existing=None)
    outcome = run(spec, cfg)
    assert outcome.status == "needs_attention" and outcome.created is False and steps.calls == []
    assert "nothing was created" in outcome.problems[0]
    assert format_outcome(spec, outcome).startswith("Playlist not created; needs attention")
