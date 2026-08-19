"""Unit tests for currency/ISO amount parsing."""

from mcp_youtube_extract.tools.super_thanks_summary.utils.parse import parse_amount


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
        assert parse_amount("A$50.00") == ("AUD", 50.0)

    def test_ca_dollar(self):
        assert parse_amount("CA$100.00") == ("CAD", 100.0)

    def test_none_on_empty(self):
        assert parse_amount("") == (None, 0.0)

    def test_none_on_unrecognized_symbol(self):
        assert parse_amount("₸500.00") == (None, 0.0)

    def test_zero_value_still_returns_currency(self):
        assert parse_amount("$0.00") == ("USD", 0.0)

    def test_iso_code_fallback_space_separator(self):
        assert parse_amount("SEK 129.00") == ("SEK", 129.0)
        assert parse_amount("SGD 50.00") == ("SGD", 50.0)
        assert parse_amount("AED 36.99") == ("AED", 36.99)

    def test_iso_code_fallback_nbsp_separator(self):
        assert parse_amount("SEK\xa0129.00") == ("SEK", 129.0)
