"""Unit tests for Super Thanks summary aggregation."""

from unittest.mock import patch

from mcp_youtube_extract.tools.super_thanks_summary.utils import summarize as _mod
from mcp_youtube_extract.tools.super_thanks_summary.utils.summarize import summarize_super_thanks


class TestSummarize:
    def test_bifurcates_paid_and_free(self):
        comments = [
            {"id": "1", "paid_amount": "$10.00"},
            {"id": "2", "paid_amount": None},
            {"id": "3", "paid_amount": None},
        ]
        with patch.object(_mod, "fetch_rates_to_inr", return_value={
            "rates": {"USD": 85.0, "INR": 1.0}, "unsupported": [],
            "fetched_at": 1_700_000_000, "stale": False, "source": "test",
        }):
            result = summarize_super_thanks(comments)
        assert result["paid_count"] == 1
        assert result["free_count"] == 2
        assert result["scanned"] == 3

    def test_per_currency_totals_and_inr_grand(self):
        comments = [
            {"id": "1", "paid_amount": "$10.00"},
            {"id": "2", "paid_amount": "$20.00"},
            {"id": "3", "paid_amount": "₹500.00"},
        ]
        with patch.object(_mod, "fetch_rates_to_inr", return_value={
            "rates": {"USD": 85.0, "INR": 1.0}, "unsupported": [],
            "fetched_at": 1_700_000_000, "stale": False, "source": "test",
        }):
            result = summarize_super_thanks(comments)
        usd = next(b for b in result["currencies"] if b["code"] == "USD")
        inr = next(b for b in result["currencies"] if b["code"] == "INR")
        assert usd["count"] == 2 and usd["total_native"] == 30.0
        assert usd["total_inr"] == 2550.0
        assert inr["total_inr"] == 500.0
        assert result["grand_total_inr"] == 3050.0

    def test_sorts_currencies_by_inr_desc(self):
        comments = [
            {"id": "1", "paid_amount": "£1.00"},
            {"id": "2", "paid_amount": "$100.00"},
            {"id": "3", "paid_amount": "€10.00"},
        ]
        with patch.object(_mod, "fetch_rates_to_inr", return_value={
            "rates": {"USD": 85.0, "GBP": 130.0, "EUR": 95.0, "INR": 1.0},
            "unsupported": [], "fetched_at": 1_700_000_000,
            "stale": False, "source": "test",
        }):
            result = summarize_super_thanks(comments)
        codes = [b["code"] for b in result["currencies"]]
        assert codes == ["USD", "EUR", "GBP"]

    def test_unsupported_currency_is_excluded_from_grand_total(self):
        comments = [
            {"id": "1", "paid_amount": "$10.00"},
            {"id": "2", "paid_amount": "Rp100000.00"},
        ]
        with patch.object(_mod, "fetch_rates_to_inr", return_value={
            "rates": {"USD": 85.0, "INR": 1.0}, "unsupported": ["IDR"],
            "fetched_at": 1_700_000_000, "stale": False, "source": "test",
        }):
            result = summarize_super_thanks(comments)
        idr = next(b for b in result["currencies"] if b["code"] == "IDR")
        assert idr["total_inr"] is None
        assert result["grand_total_inr"] == 850.0
        assert "IDR" in result["unsupported_currency"]

    def test_unrecognized_symbol_recorded(self):
        comments = [
            {"id": "1", "paid_amount": "₸500.00"},
            {"id": "2", "paid_amount": "$10.00"},
        ]
        with patch.object(_mod, "fetch_rates_to_inr", return_value={
            "rates": {"USD": 85.0, "INR": 1.0}, "unsupported": [],
            "fetched_at": 1_700_000_000, "stale": False, "source": "test",
        }):
            result = summarize_super_thanks(comments)
        assert result["unrecognized_currency"] == ["₸500.00"]
        assert result["paid_count"] == 2

    def test_no_paid_comments(self):
        comments = [{"id": "1", "paid_amount": None}, {"id": "2", "paid_amount": None}]
        with patch.object(_mod, "fetch_rates_to_inr", return_value={
            "rates": {"INR": 1.0}, "unsupported": [], "fetched_at": 0,
            "stale": False, "source": "test",
        }):
            result = summarize_super_thanks(comments)
        assert result["paid_count"] == 0
        assert result["free_count"] == 2
        assert result["currencies"] == []
        assert result["grand_total_inr"] == 0.0
