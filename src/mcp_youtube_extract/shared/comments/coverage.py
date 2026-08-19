"""Coverage-note formatting for a comment walk: distinguish partial from full scans."""


def _truncation_note(scanned: int, reported: int | None) -> str:
    """
    One line describing scan coverage, so a count is never mistaken for total.

    `reported` is approximate, so only a clear shortfall is called truncation.
    """
    if reported is None:
        return f"Scanned {scanned:,} comments (video total unknown)."
    if scanned < reported:
        return (
            f"Scanned {scanned:,} of ~{reported:,} comments — TRUNCATED. "
            f"Raise max_comments to cover the rest."
        )
    return f"Scanned {scanned:,} comments (~{reported:,} reported; full coverage)."
