"""Unit tests for comment nesting, paid-amount joining, and paging."""

import base64
import importlib.util
import sys
import types
import urllib.parse
from pathlib import Path

# Import comments_api without executing the package __init__, which imports
# server.py and fails against the installed `mcp` version for reasons unrelated
# to comments. We register a stub parent package so relative imports resolve.
_SRC = Path(__file__).resolve().parents[1] / "src" / "mcp_youtube_extract"

if "mcp_youtube_extract" not in sys.modules:
    _pkg = types.ModuleType("mcp_youtube_extract")
    _pkg.__path__ = [str(_SRC)]
    sys.modules["mcp_youtube_extract"] = _pkg

_spec = importlib.util.spec_from_file_location(
    "mcp_youtube_extract.comments_api", _SRC / "comments_api.py"
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["mcp_youtube_extract.comments_api"] = _mod
_spec.loader.exec_module(_mod)

_truncation_note = _mod._truncation_note
_amount_sort_key = _mod._amount_sort_key
_collect_paid_amounts = _mod._collect_paid_amounts
_comment_id_from_surface_key = _mod._comment_id_from_surface_key
_merge_paid = _mod._merge_paid
format_comment_thread = _mod.format_comment_thread
nest_comments = _mod.nest_comments


def _make_surface_key(comment_id: str) -> str:
    """Build a surface key shaped like YouTube's (id embedded in base64)."""
    raw = b"\x12\x1d" + comment_id.encode() + b"/12 O(\x01"
    return urllib.parse.quote(base64.b64encode(raw).decode())


class TestSurfaceKeyDecoding:
    def test_extracts_comment_id(self):
        key = _make_surface_key("UgwkmmO8yr4VDhtRfPp4AaABAg")
        assert _comment_id_from_surface_key(key) == "UgwkmmO8yr4VDhtRfPp4AaABAg"

    def test_returns_none_on_garbage(self):
        assert _comment_id_from_surface_key("not-base64-at-all!!") is None

    def test_returns_none_when_no_ug_token(self):
        key = urllib.parse.quote(base64.b64encode(b"no identifier here").decode())
        assert _comment_id_from_surface_key(key) is None


class TestCollectPaidAmounts:
    def test_maps_comment_id_to_amount(self):
        cid = "UgwkmmO8yr4VDhtRfPp4AaABAg"
        responses = [{
            "frameworkUpdates": {"mutations": [{"payload": {
                "commentSurfaceEntityPayload": {
                    "key": _make_surface_key(cid),
                    "pdgCommentChip": {"pdgCommentChipRenderer": {
                        "chipText": {"simpleText": "₹10,000.00"}
                    }},
                }
            }}]}
        }]
        assert _collect_paid_amounts(responses) == {cid: "₹10,000.00"}

    def test_ignores_surface_payload_without_chip(self):
        responses = [{"commentSurfaceEntityPayload": {
            "key": _make_surface_key("UgzzxX1ukVvMyxTsd7h4AaABAg"),
        }}]
        assert _collect_paid_amounts(responses) == {}

    def test_handles_empty_input(self):
        assert _collect_paid_amounts([]) == {}


class TestMergePaid:
    def test_attaches_amount_and_none(self):
        comments = [{"id": "a"}, {"id": "b"}]
        merged = _merge_paid(comments, {"a": "$25.00"})
        assert merged[0]["paid_amount"] == "$25.00"
        assert merged[1]["paid_amount"] is None

    def test_does_not_mutate_input(self):
        comments = [{"id": "a"}]
        _merge_paid(comments, {"a": "$5.00"})
        assert "paid_amount" not in comments[0]


class TestNesting:
    def test_groups_replies_under_parent(self):
        comments = [
            {"id": "r1", "parent": "root"},
            {"id": "c1", "parent": "r1"},
            {"id": "c2", "parent": "r1"},
            {"id": "r2", "parent": "root"},
        ]
        roots = nest_comments(comments)
        assert [r["id"] for r in roots] == ["r1", "r2"]
        assert [c["id"] for c in roots[0]["replies"]] == ["c1", "c2"]
        assert roots[1]["replies"] == []

    def test_treats_missing_parent_as_root(self):
        assert len(nest_comments([{"id": "x"}])) == 1


class TestAmountSortKey:
    def test_parses_currencies_and_separators(self):
        assert _amount_sort_key("₹10,000.00") == 10000.0
        assert _amount_sort_key("$25.00") == 25.0
        assert _amount_sort_key("£5.00") == 5.0

    def test_unpaid_sorts_last(self):
        assert _amount_sort_key(None) == 0.0
        assert _amount_sort_key("") == 0.0


class TestTruncationNote:
    def test_warns_when_scan_fell_short(self):
        note = _truncation_note(1087, 1200)
        assert "TRUNCATED" in note
        assert "1,087" in note and "1,200" in note
        assert "max_comments" in note

    def test_no_warning_at_full_coverage(self):
        note = _truncation_note(2435, 2400)
        assert "TRUNCATED" not in note
        assert "full coverage" in note

    def test_handles_unknown_total(self):
        note = _truncation_note(500, None)
        assert "TRUNCATED" not in note
        assert "unknown" in note

    def test_equal_counts_are_not_truncated(self):
        assert "TRUNCATED" not in _truncation_note(300, 300)


class TestFormatting:
    def test_marks_super_thanks_and_indents_replies(self):
        thread = {
            "author": "@fan", "text": "great video", "paid_amount": "$25.00",
            "like_count": 1200,
            "replies": [{"author": "@creator", "text": "thanks!", "replies": []}],
        }
        out = format_comment_thread(thread)
        assert "[SUPER THANKS $25.00]" in out
        assert "(1,200 likes)" in out
        assert "\n  @creator: thanks!" in out

    def test_unpaid_has_no_badge(self):
        out = format_comment_thread({"author": "@a", "text": "hi", "replies": []})
        assert "SUPER THANKS" not in out
