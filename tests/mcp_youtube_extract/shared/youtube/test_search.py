"""Unit tests for search filter construction and result classification.

Fixtures mirror real yt-dlp flat search entries. Search results mix three
kinds: videos (ie_key Youtube), playlists and channels (both YoutubeTab),
and Shorts, which are videos whose url uses the /shorts/ path.
"""

import pytest

from mcp_youtube_extract.shared.youtube.search import (
    build_search_url,
    is_short,
    keep_videos,
    keep_playlists,
    format_search_results,
)


def _video(video_id="abc123", title="A Video", short=False, **kw):
    path = "shorts/" if short else "watch?v="
    return {
        "id": video_id,
        "title": title,
        "ie_key": "Youtube",
        "url": f"https://www.youtube.com/{path}{video_id}",
        **kw,
    }


def _playlist(pid="PLabc", title="A Playlist", **kw):
    return {
        "id": pid,
        "title": title,
        "ie_key": "YoutubeTab",
        "url": f"https://www.youtube.com/playlist?list={pid}",
        **kw,
    }


def _channel(cid="UCabc", title="A Channel"):
    return {
        "id": cid,
        "title": title,
        "ie_key": "YoutubeTab",
        "url": f"https://www.youtube.com/channel/{cid}",
    }


class TestBuildSearchUrl:
    def test_encodes_query(self):
        url = build_search_url("electoral bonds", "video", "relevance")
        assert "search_query=electoral+bonds" in url

    def test_video_and_playlist_modes_differ(self):
        v = build_search_url("q", "video", "relevance")
        p = build_search_url("q", "playlist", "relevance")
        assert v != p

    @pytest.mark.parametrize("sort", ["relevance", "date", "views"])
    def test_each_sort_is_accepted(self, sort):
        assert "sp=" in build_search_url("q", "video", sort)

    def test_sorts_produce_distinct_filters(self):
        urls = {build_search_url("q", "video", s) for s in ("relevance", "date", "views")}
        assert len(urls) == 3

    def test_rejects_unknown_sort(self):
        with pytest.raises(ValueError, match="sort"):
            build_search_url("q", "video", "popularity")

    def test_rejects_unknown_mode(self):
        with pytest.raises(ValueError, match="mode"):
            build_search_url("q", "channel", "relevance")


class TestIsShort:
    def test_shorts_url_path_is_a_short(self):
        assert is_short(_video(short=True)) is True

    def test_watch_url_is_not_a_short(self):
        assert is_short(_video(short=False)) is False

    def test_missing_url_is_not_a_short(self):
        assert is_short({"id": "x"}) is False

    def test_brief_watch_video_is_not_a_short(self):
        # Duration alone must not condemn a video; only the url path decides.
        assert is_short(_video(duration=20)) is False


class TestKeepVideos:
    def test_drops_shorts_playlists_and_channels(self):
        entries = [
            _video("keep1"),
            _video("drop1", short=True),
            _playlist(),
            _channel(),
            _video("keep2"),
        ]
        kept = keep_videos(entries)
        assert [e["id"] for e in kept] == ["keep1", "keep2"]

    def test_empty_stays_empty(self):
        assert keep_videos([]) == []


class TestKeepPlaylists:
    def test_keeps_only_playlists(self):
        # Channels share ie_key YoutubeTab, so the url must disambiguate.
        entries = [_playlist("PLkeep"), _channel(), _video()]
        kept = keep_playlists(entries)
        assert [e["id"] for e in kept] == ["PLkeep"]

    def test_drops_channels(self):
        assert keep_playlists([_channel()]) == []


class TestFormatSearchResults:
    def _results(self):
        return {
            "query": "electoral bonds",
            "sort": "views",
            "videos": [
                _video("vid1", "A Video", view_count=1234567, duration=1017,
                       channel="Think School"),
            ],
            "playlists": [
                _playlist("PL7ZJ", "Electoral Bonds - Deshbhakt", channel="Deshbhakt"),
            ],
        }

    def test_reports_query_and_sort(self):
        out = format_search_results(self._results())
        assert "electoral bonds" in out
        assert "views" in out

    def test_lists_videos_and_playlists_separately(self):
        out = format_search_results(self._results())
        assert "VIDEOS" in out
        assert "PLAYLISTS" in out
        assert "vid1" in out
        assert "PL7ZJ" in out

    def test_formats_view_counts_readably(self):
        out = format_search_results(self._results())
        assert "1,234,567" in out

    def test_shows_duration_for_videos(self):
        out = format_search_results(self._results())
        assert "16:57" in out  # 1017s

    def test_empty_sections_are_reported(self):
        out = format_search_results({"query": "q", "sort": "relevance",
                                     "videos": [], "playlists": []})
        assert "no videos" in out.lower()
        assert "no playlists" in out.lower()
