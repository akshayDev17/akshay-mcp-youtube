"""Unit tests for paid-amount extraction from YouTube's commentSurfaceEntityPayload."""

import base64
import urllib.parse

from mcp_youtube_extract.shared.comments.paid_join import (
    _collect_paid_amounts,
    _comment_id_from_surface_key,
    _merge_paid,
)


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
