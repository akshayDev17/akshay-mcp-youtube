"""Paid-amount extraction from YouTube's commentSurfaceEntityPayload.

yt-dlp exposes comments but drops paid amounts. The amount lives in a sibling
entity, `commentSurfaceEntityPayload`, which yt-dlp never reads. The two
entities share no key, but base64-decoding the surface key reveals the comment
id inside it, which joins to commentEntityPayload.properties.commentId.
"""

import base64
import re
import urllib.parse

# Comment ids are the longest "Ug..." token in the decoded surface key.
_UG_TOKEN = re.compile(r"Ug[A-Za-z0-9_-]+")


def _comment_id_from_surface_key(key: str) -> str | None:
    """Decode a commentSurfaceEntityPayload key and pull out the comment id."""
    try:
        padded = urllib.parse.unquote(key) + "=="
        decoded = base64.b64decode(padded).decode("utf8", "replace")
    except Exception:
        return None

    tokens = _UG_TOKEN.findall(decoded)
    return max(tokens, key=len) if tokens else None


def _collect_paid_amounts(responses: list) -> dict[str, str]:
    """Walk captured innertube responses and map comment_id -> paid amount."""
    amounts: dict[str, str] = {}

    def walk(node):
        if isinstance(node, dict):
            payload = node.get("commentSurfaceEntityPayload")
            if isinstance(payload, dict):
                chip = payload.get("pdgCommentChip")
                key = payload.get("key")
                if isinstance(chip, dict) and key:
                    text = (
                        chip.get("pdgCommentChipRenderer", {})
                        .get("chipText", {})
                        .get("simpleText")
                    )
                    comment_id = _comment_id_from_surface_key(key)
                    if text and comment_id:
                        amounts[comment_id] = text
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(responses)
    return amounts


def _merge_paid(comments: list[dict], amounts: dict[str, str]) -> list[dict]:
    """Attach paid_amount to each comment (None when not a Super Thanks)."""
    merged = []
    for comment in comments:
        item = dict(comment)
        item["paid_amount"] = amounts.get(comment.get("id"))
        merged.append(item)
    return merged
