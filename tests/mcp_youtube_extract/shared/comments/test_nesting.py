"""Unit tests for comment reply nesting."""

from mcp_youtube_extract.shared.comments.nesting import nest_comments


class TestNesting:
    def test_groups_replies_under_parent(self):
        comments = [
            {"id": "r1", "parent": "root"},
            {"id": "c1", "parent": "r1"},
            {"id": "c2", "parent": "r1"},
            {"id": "r2", "parent": "root"},
        ]
        roots = nest_comments(comments)
        assert [r["id"] for r in roots] == ["r1", "r2"]
        assert [c["id"] for c in roots[0]["replies"]] == ["c1", "c2"]
        assert roots[1]["replies"] == []

    def test_treats_missing_parent_as_root(self):
        assert len(nest_comments([{"id": "x"}])) == 1
