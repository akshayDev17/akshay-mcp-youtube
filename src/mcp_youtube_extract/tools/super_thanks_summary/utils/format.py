"""Markdown-table rendering for the Super Thanks summary."""


def format_super_thanks_summary(result: dict, video_id: str, coverage: str) -> str:
    """Render a summary dict as a markdown response for the MCP tool.

    The per-currency breakdown ships as a markdown table so callers render it
    consistently instead of reinterpreting a padded plain-text layout.
    """
    lines = [
        f"## Super Thanks summary for `{video_id}`",
        "",
        coverage,
        "",
        f"- **Paid comments:** {result['paid_count']:,}",
        f"- **Free comments:** {result['free_count']:,} (of {result['scanned']:,} top-level scanned)",
        "",
    ]

    if not result["currencies"]:
        lines.append("_No Super Thanks found in this scan._")
        return "\n".join(lines)

    lines += [
        "### Per-currency breakdown (sorted by INR value)",
        "",
        "| Currency | Count | Native total | INR equivalent |",
        "|---|---:|---:|---:|",
    ]
    for bucket in result["currencies"]:
        code = bucket["code"]
        native = f"{code} {bucket['total_native']:,.2f}"
        if bucket["total_inr"] is None:
            inr = "n/a (no FX rate)"
        else:
            inr = f"₹{bucket['total_inr']:,.2f}"
        lines.append(f"| {code} | {bucket['count']:,} | {native} | {inr} |")
    lines.append(
        f"| **Total** | **{result['paid_count']:,}** | | **₹{result['grand_total_inr']:,.2f}** |"
    )
    lines.append("")

    if result["unsupported_currency"]:
        lines.append(
            f"> **Note:** excluded from INR total (no FX rate available): "
            f"{', '.join(result['unsupported_currency'])}"
        )
    if result["unrecognized_currency"]:
        lines.append(
            f"> **Note:** {len(result['unrecognized_currency'])} amount(s) had an "
            f"unrecognized currency symbol; add a mapping in `super_thanks.py`."
        )

    fx = result["fx"]
    stale_note = " (STALE — network failed, using cached rates)" if fx["stale"] else ""
    lines.append("")
    lines.append(f"_FX source: {fx['source']}{stale_note}_")

    return "\n".join(lines)
