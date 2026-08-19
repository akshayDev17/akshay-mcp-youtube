"""Unit tests for scan-coverage note formatting."""

from mcp_youtube_extract.shared.comments.coverage import _truncation_note


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
