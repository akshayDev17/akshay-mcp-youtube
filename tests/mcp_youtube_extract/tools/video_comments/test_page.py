"""Unit tests for video_comments tool's page rendering."""

from mcp_youtube_extract.tools.video_comments.utils.page import format_comment_thread


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
