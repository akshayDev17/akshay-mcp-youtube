"""Group replies under their parent top-level threads using yt-dlp's `parent` field."""


def nest_comments(comments: list[dict]) -> list[dict]:
    """Group replies under their parents using yt-dlp's `parent` field."""
    by_parent: dict[str, list[dict]] = {}
    roots: list[dict] = []

    for comment in comments:
        parent = comment.get("parent", "root")
        if parent == "root":
            roots.append(comment)
        else:
            by_parent.setdefault(parent, []).append(comment)

    for root in roots:
        root["replies"] = by_parent.get(root.get("id"), [])

    return roots
