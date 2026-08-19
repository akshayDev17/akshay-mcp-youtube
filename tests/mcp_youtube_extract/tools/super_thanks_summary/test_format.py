"""Unit tests for Super Thanks markdown formatting."""

from mcp_youtube_extract.tools.super_thanks_summary.utils.format import format_super_thanks_summary


class TestFormat:
    def test_shows_paid_free_and_grand_total(self):
        result = {
            "paid_count": 3, "free_count": 7, "scanned": 10,
            "currencies": [
                {"code": "USD", "count": 2, "total_native": 30.0, "total_inr": 2550.0},
                {"code": "INR", "count": 1, "total_native": 500.0, "total_inr": 500.0},
            ],
            "grand_total_inr": 3050.0,
            "unrecognized_currency": [],
            "unsupported_currency": [],
            "fx": {"source": "frankfurter.dev", "stale": False},
        }
        out = format_super_thanks_summary(result, "abc123", "Scanned 10 (~10 reported; full coverage).")
        assert "| Currency | Count | Native total | INR equivalent |" in out
        assert "| USD | 2 |" in out
        assert "| INR | 1 |" in out
        assert "**Paid comments:** 3" in out
        assert "**Free comments:** 7" in out
        assert "**₹3,050.00**" in out
        assert "frankfurter.dev" in out

    def test_notes_stale_fx(self):
        result = {
            "paid_count": 1, "free_count": 0, "scanned": 1,
            "currencies": [
                {"code": "USD", "count": 1, "total_native": 10.0, "total_inr": 800.0},
            ],
            "grand_total_inr": 800.0,
            "unrecognized_currency": [],
            "unsupported_currency": [],
            "fx": {"source": "cache (stale)", "stale": True},
        }
        out = format_super_thanks_summary(result, "abc", "coverage")
        assert "STALE" in out
