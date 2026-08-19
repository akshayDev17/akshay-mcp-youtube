"""Frankfurter.dev FX rate fetching with 24h disk cache and stale-cache fallback."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ....shared.logger import get_logger

logger = get_logger(__name__)

_CACHE_DIR = Path(__file__).resolve().parents[5] / ".cache" / "fx"
_CACHE_PATH = _CACHE_DIR / "inr.json"
_CACHE_TTL_SECONDS = 24 * 60 * 60
_FX_URL = "https://api.frankfurter.dev/v1/latest"


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

    Falls back to cached rates on network failure, marking them stale. If nothing
    is cached, returns empty rates and lists all requested currencies as unsupported.
    """
    needed = {c for c in currencies if c and c != "INR"}
    now = time.time()

    cached = _load_cached_rates()
    if cached and (now - cached.get("fetched_at", 0)) < _CACHE_TTL_SECONDS:
        cached_rates = cached.get("rates", {})
        if needed.issubset(cached_rates.keys()) or not needed:
            return {
                "rates": {**cached_rates, "INR": 1.0},
                "unsupported": cached.get("unsupported", []),
                "fetched_at": cached["fetched_at"],
                "stale": False,
                "source": "cache",
            }

    params = {"base": "INR"}
    if needed:
        params["symbols"] = ",".join(sorted(needed))
    url = f"{_FX_URL}?{urllib.parse.urlencode(params)}"

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
