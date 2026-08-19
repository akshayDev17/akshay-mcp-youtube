"""Aggregate Super Thanks: paid/free bifurcation, per-currency totals, INR grand total."""

from .parse import parse_amount
from .fx import fetch_rates_to_inr


def summarize_super_thanks(comments: list[dict]) -> dict:
    """
    Aggregate a list of top-level comments (each with paid_amount or None) into
    the Super Thanks summary structure.

    Returns:
      {
        "paid_count": int,
        "free_count": int,
        "scanned": int,
        "currencies": [
          {"code": "INR", "count": 140, "total_native": 245600.0, "total_inr": 245600.0},
          ...
        ],
        "grand_total_inr": float,
        "unrecognized_currency": [...],
        "unsupported_currency": [...],
        "fx": {...},
      }
    """
    paid = [c for c in comments if c.get("paid_amount")]
    scanned = len(comments)

    per_currency: dict[str, dict] = {}
    unrecognized: list[str] = []

    for comment in paid:
        rendered = comment["paid_amount"]
        code, value = parse_amount(rendered)
        if code is None:
            unrecognized.append(rendered)
            continue
        bucket = per_currency.setdefault(
            code, {"code": code, "count": 0, "total_native": 0.0}
        )
        bucket["count"] += 1
        bucket["total_native"] += value

    fx = fetch_rates_to_inr(set(per_currency.keys()))
    rates = fx["rates"]

    unsupported: list[str] = []
    grand_total_inr = 0.0
    for code, bucket in per_currency.items():
        rate = rates.get(code)
        if rate is None:
            bucket["total_inr"] = None
            unsupported.append(code)
        else:
            bucket["total_inr"] = round(bucket["total_native"] * rate, 2)
            grand_total_inr += bucket["total_inr"]

    currencies = sorted(
        per_currency.values(),
        key=lambda b: (b["total_inr"] is None, -(b["total_inr"] or 0)),
    )

    return {
        "paid_count": len(paid),
        "free_count": scanned - len(paid),
        "scanned": scanned,
        "currencies": currencies,
        "grand_total_inr": round(grand_total_inr, 2),
        "unrecognized_currency": unrecognized,
        "unsupported_currency": sorted(set(unsupported)),
        "fx": fx,
    }
