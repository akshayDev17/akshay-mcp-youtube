"""Unit tests for the paid_comments tool's list helpers."""

from mcp_youtube_extract.tools.paid_comments.utils.list import _amount_sort_key


class TestAmountSortKey:
    def test_parses_currencies_and_separators(self):
        assert _amount_sort_key("₹10,000.00") == 10000.0
        assert _amount_sort_key("$25.00") == 25.0
        assert _amount_sort_key("£5.00") == 5.0

    def test_unpaid_sorts_last(self):
        assert _amount_sort_key(None) == 0.0
        assert _amount_sort_key("") == 0.0
