"""
Super Thanks aggregation: bifurcate paid vs free, per-currency totals, INR grand total.

YouTube's Super Thanks UI is video-level (button under the player), and per
support.google.com/youtube/answer/9632365, the resulting comment posts as a
top-level comment. Replies cannot be Super Thanks, so the underlying scan
skips replies entirely.

FX is fetched from frankfurter.dev (ECB rates, no key). Frankfurter covers ~30
currencies; anything outside that set is kept in its native currency in the
per-currency breakdown but excluded from the INR grand total, with the caller
told which currencies were skipped.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .logger import get_logger

logger = get_logger(__name__)

_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "fx"
_CACHE_PATH = _CACHE_DIR / "inr.json"
_CACHE_TTL_SECONDS = 24 * 60 * 60  # rates don't move enough intraday to matter
_FX_URL = "https://api.frankfurter.dev/v1/latest"

# Order matters: multi-char prefixes must be tried before single-char ones so
# "A$25.00" resolves to AUD, not USD with an "A" prefix.
_CURRENCY_PREFIXES: list[tuple[str, str]] = [
    ("CA$", "CAD"),
    ("HK$", "HKD"),
    ("NZ$", "NZD"),
    ("A$", "AUD"),
    ("R$", "BRL"),
    ("MX$", "MXN"),
    ("NT$", "TWD"),
    ("US$", "USD"),
    ("S$", "SGD"),
    ("CHF", "CHF"),
    ("kr", "SEK"),      # ambiguous across SEK/NOK/DKK; YouTube seems to render SEK
    ("zł", "PLN"),
    ("Kč", "CZK"),
    ("Ft", "HUF"),
    ("Rp", "IDR"),
    ("RM", "MYR"),
    ("$", "USD"),
    ("₹", "INR"),
    ("£", "GBP"),
    ("€", "EUR"),
    ("¥", "JPY"),       # YouTube uses ¥ for JPY; CNY uses ¥ or 元 depending on locale
    ("₩", "KRW"),
    ("₪", "ILS"),
    ("₺", "TRY"),
    ("฿", "THB"),
    ("₱", "PHP"),
    ("₫", "VND"),
    ("R", "ZAR"),       # last resort; keep after other prefixes
]


# Fallback for currencies YouTube renders as "ISO<nbsp>amount", e.g. "SEK 129.00".
# Matches at the start; whitespace (incl. non-breaking) between code and number.
_ISO_PREFIX_RE = re.compile(r"^([A-Z]{3})[\s ]+")


def parse_amount(rendered: str) -> tuple[str | None, float]:
    """
    Split a YouTube-rendered Super Thanks amount into (currency_code, value).

    Returns (None, 0.0) if the currency can't be identified. Comma is the
    thousands separator in every locale YouTube renders, so it is stripped
    unconditionally.
    """
    if not rendered:
        return None, 0.0
    s = rendered.strip()
    for prefix, code in _CURRENCY_PREFIXES:
        if s.startswith(prefix):
            digits = re.sub(r"[^\d.]", "", s[len(prefix):].replace(",", ""))
            try:
                return code, float(digits) if digits else 0.0
            except ValueError:
                return code, 0.0
    # Fallback: "SEK 129.00", "SGD 50.00", "AED 36.99", etc.
    m = _ISO_PREFIX_RE.match(s)
    if m:
        digits = re.sub(r"[^\d.]", "", s[m.end():].replace(",", ""))
        try:
            return m.group(1), float(digits) if digits else 0.0
        except ValueError:
            return m.group(1), 0.0
    return None, 0.0


def _load_cached_rates() -> dict | None:
    if not _CACHE_PATH.exists():
        return None
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception as e:
        logger.warning(f"Ignoring unreadable FX cache: {e}")
        return None


def _save_rates(payload: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(payload))
    except Exception as e:
        logger.warning(f"Could not write FX cache: {e}")


def fetch_rates_to_inr(currencies: set[str]) -> dict:
    """
    Return per-currency rates expressed as "1 unit of X = N INR".

    Result shape:
      {
        "rates": {"USD": 95.7, "GBP": 129.3, ...},   # INR per 1 unit
        "unsupported": ["BRL", ...],                  # frankfurter doesn't cover
        "fetched_at": 1723987200.0,
        "stale": False,                                # True if served from expired cache
        "source": "frankfurter.dev" or "cache",
      }

    Falls back to cached rates on network failure, marking them stale. If nothing
    is cached, returns empty rates and lists all requested currencies as unsupported.
    """
    # INR itself is always 1:1.
    needed = {c for c in currencies if c and c != "INR"}
    now = time.time()

    cached = _load_cached_rates()
    if cached and (now - cached.get("fetched_at", 0)) < _CACHE_TTL_SECONDS:
        # Cache is fresh enough; use it if it covers what we need.
        cached_rates = cached.get("rates", {})
        if needed.issubset(cached_rates.keys()) or not needed:
            return {
                "rates": {**cached_rates, "INR": 1.0},
                "unsupported": cached.get("unsupported", []),
                "fetched_at": cached["fetched_at"],
                "stale": False,
                "source": "cache",
            }

    # Fetch fresh. Ask for exactly the currencies we need; frankfurter returns
    # only the ones it covers, so anything missing goes to "unsupported".
    params = {"base": "INR"}
    if needed:
        params["symbols"] = ",".join(sorted(needed))
    url = f"{_FX_URL}?{urllib.parse.urlencode(params)}"

    # Frankfurter rejects the default Python-urllib UA with 403; any real UA works.
    request = urllib.request.Request(
        url, headers={"User-Agent": "akshay-mcp-youtube/0.1 (+github.com/akshayDev17)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        logger.warning(f"FX fetch failed ({e}); falling back to cache")
        if cached:
            return {
                "rates": {**cached.get("rates", {}), "INR": 1.0},
                "unsupported": cached.get("unsupported", []),
                "fetched_at": cached.get("fetched_at", 0),
                "stale": True,
                "source": "cache (stale)",
            }
        return {
            "rates": {"INR": 1.0},
            "unsupported": sorted(needed),
            "fetched_at": 0,
            "stale": True,
            "source": "unavailable",
        }

    # Invert: frankfurter returns "1 INR = X foreign"; we want "1 foreign = N INR".
    inr_per_unit = {code: 1.0 / rate for code, rate in data.get("rates", {}).items() if rate}
    unsupported = sorted(needed - set(inr_per_unit.keys()))

    payload = {
        "rates": inr_per_unit,
        "unsupported": unsupported,
        "fetched_at": now,
    }
    _save_rates(payload)

    return {
        "rates": {**inr_per_unit, "INR": 1.0},
        "unsupported": unsupported,
        "fetched_at": now,
        "stale": False,
        "source": "frankfurter.dev",
    }


def summarize_super_thanks(comments: list[dict]) -> dict:
    """
    Aggregate a list of top-level comments (each with paid_amount or None) into
    the Super Thanks summary structure.

    Returns:
      {
        "paid_count": int,
        "free_count": int,             # of scanned; not the video's total
        "scanned": int,
        "currencies": [
          {"code": "INR", "count": 140, "total_native": 245600.0, "total_inr": 245600.0},
          ...
        ],                             # sorted by total_inr desc
        "grand_total_inr": float,
        "unrecognized_currency": [...],   # rendered strings we couldn't parse
        "unsupported_currency": [...],    # parsed but no FX rate available
        "fx": {...},                      # from fetch_rates_to_inr
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
