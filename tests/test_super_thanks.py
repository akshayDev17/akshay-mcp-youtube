"""Unit tests for Super Thanks parsing, FX handling, and aggregation."""

import importlib.util
import sys
import types
import urllib.error
from pathlib import Path
from unittest.mock import patch

# Same stub-parent-package trick as test_comments_api.py: server.py's mcp
# import breaks against the installed mcp version for reasons unrelated to
# what we're testing here.
_SRC = Path(__file__).resolve().parents[1] / "src" / "mcp_youtube_extract"

if "mcp_youtube_extract" not in sys.modules:
    _pkg = types.ModuleType("mcp_youtube_extract")
    _pkg.__path__ = [str(_SRC)]
    sys.modules["mcp_youtube_extract"] = _pkg

_spec = importlib.util.spec_from_file_location(
    "mcp_youtube_extract.super_thanks", _SRC / "super_thanks.py"
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["mcp_youtube_extract.super_thanks"] = _mod
_spec.loader.exec_module(_mod)

parse_amount = _mod.parse_amount
summarize_super_thanks = _mod.summarize_super_thanks
format_super_thanks_summary = _mod.format_super_thanks_summary


class TestParseAmount:
    def test_inr_with_thousands_separator(self):
        assert parse_amount("₹10,000.00") == ("INR", 10000.0)

    def test_usd_simple(self):
        assert parse_amount("$25.00") == ("USD", 25.0)

    def test_gbp_simple(self):
        assert parse_amount("£5.00") == ("GBP", 5.0)

    def test_eur_simple(self):
        assert parse_amount("€12.50") == ("EUR", 12.5)

    def test_aud_wins_over_usd(self):
        # A$ must be tried before $ or "A" gets swallowed as a stray character.
        assert parse_amount("A$50.00") == ("AUD", 50.0)

    def test_ca_dollar(self):
        assert parse_amount("CA$100.00") == ("CAD", 100.0)

    def test_none_on_empty(self):
        assert parse_amount("") == (None, 0.0)

    def test_none_on_unrecognized_symbol(self):
        assert parse_amount("₸500.00") == (None, 0.0)  # tenge, not in our table

    def test_zero_value_still_returns_currency(self):
        assert parse_amount("$0.00") == ("USD", 0.0)

    def test_iso_code_fallback_space_separator(self):
        # YouTube renders currencies without well-known symbols as "ISO<nbsp>amount"
        assert parse_amount("SEK 129.00") == ("SEK", 129.0)
        assert parse_amount("SGD 50.00") == ("SGD", 50.0)
        assert parse_amount("AED 36.99") == ("AED", 36.99)

    def test_iso_code_fallback_nbsp_separator(self):
        assert parse_amount("SEK\xa0129.00") == ("SEK", 129.0)


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
        assert usd["total_inr"] == 2550.0    # 30 * 85
        assert inr["total_inr"] == 500.0
        assert result["grand_total_inr"] == 3050.0

    def test_sorts_currencies_by_inr_desc(self):
        comments = [
            {"id": "1", "paid_amount": "£1.00"},   # 130 INR
            {"id": "2", "paid_amount": "$100.00"}, # 8500 INR
            {"id": "3", "paid_amount": "€10.00"},  # 950 INR
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
        # Frankfurter doesn't cover, say, IDR — parses fine but total_inr is None
        # and the currency is listed as unsupported.
        comments = [
            {"id": "1", "paid_amount": "$10.00"},
            {"id": "2", "paid_amount": "Rp100000.00"},   # IDR
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
            {"id": "1", "paid_amount": "₸500.00"},  # tenge, not in table
            {"id": "2", "paid_amount": "$10.00"},
        ]
        with patch.object(_mod, "fetch_rates_to_inr", return_value={
            "rates": {"USD": 85.0, "INR": 1.0}, "unsupported": [],
            "fetched_at": 1_700_000_000, "stale": False, "source": "test",
        }):
            result = summarize_super_thanks(comments)
        assert result["unrecognized_currency"] == ["₸500.00"]
        assert result["paid_count"] == 2  # both are paid; one just can't be summed

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


class TestFxFallback:
    def test_returns_stale_cache_on_network_failure(self, tmp_path, monkeypatch):
        # Point cache at a temp dir with a pre-existing cache file.
        cache_path = tmp_path / "inr.json"
        cache_path.write_text(
            '{"rates": {"USD": 80.0}, "unsupported": [], "fetched_at": 100}'
        )
        monkeypatch.setattr(_mod, "_CACHE_DIR", tmp_path)
        monkeypatch.setattr(_mod, "_CACHE_PATH", cache_path)

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no network")):
            fx = _mod.fetch_rates_to_inr({"USD"})

        assert fx["rates"]["USD"] == 80.0
        assert fx["stale"] is True
        assert "stale" in fx["source"]

    def test_returns_empty_when_no_cache_and_no_network(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_CACHE_DIR", tmp_path)
        monkeypatch.setattr(_mod, "_CACHE_PATH", tmp_path / "inr.json")

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no network")):
            fx = _mod.fetch_rates_to_inr({"USD", "GBP"})

        assert fx["rates"] == {"INR": 1.0}
        assert set(fx["unsupported"]) == {"USD", "GBP"}
        assert fx["stale"] is True


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
        # Markdown table shape.
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
