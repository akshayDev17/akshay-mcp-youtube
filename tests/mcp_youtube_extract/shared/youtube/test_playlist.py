"""Unit tests for playlist gating classification, counts, and formatting.

Fixtures mirror real yt-dlp flat-extraction entries captured from
youtube.com/playlist?list=PLoCe3YxZTxRQRr1j_vi4bATfzt3XdbeXH
("Members Only Streams"), which contains all three entry states.
"""

from mcp_youtube_extract.shared.youtube.playlist import (
    classify_entry,
    count_by_status,
    format_playlist_info,
)


def _entry(video_id="abc123", title="A Title", availability=None, **kw):
    """A flat-extraction entry, shaped like yt-dlp's output."""
    return {"id": video_id, "title": title, "availability": availability, **kw}


class TestClassifyEntry:
    def test_subscriber_only_is_members_only(self):
        e = _entry(availability="subscriber_only")
        assert classify_entry(e) == "members_only"

    def test_titled_entry_without_availability_is_free(self):
        # Flat extraction cannot tell public from unlisted, so both read as free.
        assert classify_entry(_entry(availability=None)) == "free"

    def test_public_availability_is_free(self):
        assert classify_entry(_entry(availability="public")) == "free"

    def test_untitled_entry_is_unavailable(self):
        # A deleted / taken-down video comes back null except for id and url.
        e = _entry(title=None, availability=None)
        assert classify_entry(e) == "unavailable"

    def test_missing_title_key_is_unavailable(self):
        assert classify_entry({"id": "x"}) == "unavailable"

    def test_members_only_wins_over_missing_title(self):
        # Gating is the more important signal when both are present.
        e = _entry(title=None, availability="subscriber_only")
        assert classify_entry(e) == "members_only"

    def test_private_is_unavailable(self):
        assert classify_entry(_entry(availability="private")) == "unavailable"


class TestCountByStatus:
    def test_counts_each_status(self):
        entries = [
            _entry("a", availability="subscriber_only"),
            _entry("b", availability="subscriber_only"),
            _entry("c"),
            _entry("d", title=None),
        ]
        counts = count_by_status(entries)
        assert counts == {
            "total": 4,
            "free": 1,
            "members_only": 2,
            "unavailable": 1,
        }

    def test_empty_playlist_counts_zero(self):
        assert count_by_status([]) == {
            "total": 0,
            "free": 0,
            "members_only": 0,
            "unavailable": 0,
        }


class TestFormatPlaylistInfo:
    def _info(self, entries=None):
        return {
            "title": "Members Only Streams",
            "channel": "meghnerd",
            "availability": "public",
            "entries": entries
            if entries is not None
            else [
                _entry("F_C6SiqHjJI", "Scripting the NEXT unhinged video",
                       availability="subscriber_only"),
                _entry("pub123", "A free one"),
                _entry("KhCIfaUL3n8", None),
            ],
        }

    def test_header_reports_playlist_metadata(self):
        out = format_playlist_info(self._info())
        assert "Members Only Streams" in out
        assert "meghnerd" in out

    def test_header_reports_counts(self):
        out = format_playlist_info(self._info())
        assert "3 total" in out
        assert "1 free" in out
        assert "1 members-only" in out
        assert "1 unavailable" in out

    def test_playlist_visibility_is_distinct_from_video_gating(self):
        # The playlist is public while its videos are gated - the whole point.
        out = format_playlist_info(self._info())
        assert "public" in out

    def test_lists_each_video_with_status(self):
        out = format_playlist_info(self._info())
        assert "[members-only]" in out
        assert "[free]" in out
        assert "[unavailable]" in out
        assert "F_C6SiqHjJI" in out

    def test_include_videos_false_omits_listing(self):
        out = format_playlist_info(self._info(), include_videos=False)
        assert "3 total" in out
        assert "[members-only]" not in out
        assert "F_C6SiqHjJI" not in out

    def test_untitled_entry_renders_placeholder(self):
        out = format_playlist_info(self._info())
        assert "KhCIfaUL3n8" in out
        assert "(unavailable)" in out

    def test_none_info_is_reported(self):
        assert "not found" in format_playlist_info(None).lower()

    def test_empty_playlist_does_not_crash(self):
        out = format_playlist_info(self._info(entries=[]))
        assert "0 total" in out
