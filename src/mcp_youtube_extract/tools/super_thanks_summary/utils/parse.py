"""Currency-symbol and ISO-code parsing for YouTube Super Thanks amount strings."""

import re

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
    ("kr", "SEK"),
    ("zł", "PLN"),
    ("Kč", "CZK"),
    ("Ft", "HUF"),
    ("Rp", "IDR"),
    ("RM", "MYR"),
    ("$", "USD"),
    ("₹", "INR"),
    ("£", "GBP"),
    ("€", "EUR"),
    ("¥", "JPY"),
    ("₩", "KRW"),
    ("₪", "ILS"),
    ("₺", "TRY"),
    ("฿", "THB"),
    ("₱", "PHP"),
    ("₫", "VND"),
    ("R", "ZAR"),
]

# Fallback for currencies YouTube renders as "ISO<nbsp>amount", e.g. "SEK 129.00".
_ISO_PREFIX_RE = re.compile(r"^([A-Z]{3})[\s ]+")


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
    m = _ISO_PREFIX_RE.match(s)
    if m:
        digits = re.sub(r"[^\d.]", "", s[m.end():].replace(",", ""))
        try:
            return m.group(1), float(digits) if digits else 0.0
        except ValueError:
            return m.group(1), 0.0
    return None, 0.0
