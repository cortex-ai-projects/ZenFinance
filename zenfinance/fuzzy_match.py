"""
ZenFinance — Fuzzy vendor name normalisation.
Groups "STRP* NETFLIX" and "NETFLIX.COM" into the same vendor bucket.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

try:
    from thefuzz import process as fuzz_process, fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False

# Known vendor aliases → canonical name
VENDOR_ALIASES: dict[str, str] = {
    "STRP* NETFLIX": "Netflix",
    "NETFLIX.COM": "Netflix",
    "NETFLIX COM": "Netflix",
    "AMZN": "Amazon",
    "AMAZON.IN": "Amazon",
    "AMAZON PAY": "Amazon Pay",
    "SWIGGY ORDER": "Swiggy",
    "SWIGGY IT": "Swiggy",
    "ZOMATO ORDER": "Zomato",
    "PHONEPE": "PhonePe",
    "GPAY": "Google Pay",
    "GOOGLE PAY": "Google Pay",
    "PAYTM": "Paytm",
    "FLIPKART": "Flipkart",
    "IRCTC": "IRCTC",
    "UBER INDIA": "Uber",
    "OLA ELECTRIC": "Ola",
    "BOOKMYSHOW": "BookMyShow",
    "HOTSTAR": "Disney+ Hotstar",
    "SPOTIFY AB": "Spotify",
    "APPLE.COM/BILL": "Apple",
    "GOOGLE PLAY": "Google Play",
}

# Pre-compiled strip patterns
_STRIP_PREFIXES = re.compile(
    r"^(TO TRANSFER-|BY TRANSFER-|UPI/DR/\d+/|UPI/CR/\d+/|POS/|ATM WDL/|NEFT-|IMPS/\d+/)",
    re.IGNORECASE,
)
_STRIP_SUFFIXES = re.compile(r"\s+\d{10,}\s*$")   # trailing long numbers
_STRIP_SPECIAL  = re.compile(r"[/\\*]")


def clean_description(desc: str) -> str:
    """Strip transaction prefixes / suffixes to isolate vendor name."""
    d = str(desc).strip()
    d = _STRIP_PREFIXES.sub("", d)
    d = _STRIP_SUFFIXES.sub("", d)
    d = _STRIP_SPECIAL.sub(" ", d)
    return d.strip()


@lru_cache(maxsize=2048)
def normalize_vendor(description: str) -> str:
    """
    Return a canonical vendor name for a raw bank description.
    1. Exact alias lookup (case-insensitive).
    2. Fuzzy match against known aliases (threshold 85).
    3. Return cleaned description if no match.
    """
    cleaned = clean_description(description).upper()

    # 1. Exact alias lookup
    for alias, canonical in VENDOR_ALIASES.items():
        if alias.upper() in cleaned:
            return canonical

    # 2. Fuzzy match
    if FUZZY_AVAILABLE and VENDOR_ALIASES:
        best, score = fuzz_process.extractOne(
            cleaned,
            list(VENDOR_ALIASES.keys()),
            scorer=fuzz.token_set_ratio,
        )
        if score >= 85:
            return VENDOR_ALIASES[best]

    # 3. Return cleaned form (title-cased)
    return clean_description(description).title() or description


def fuzzy_deduplicate_vendors(descriptions: list[str], threshold: int = 85) -> dict[str, str]:
    """
    Given a list of vendor descriptions, return a mapping of
    raw_description → canonical_name for similar ones.
    """
    if not FUZZY_AVAILABLE:
        return {d: d for d in descriptions}

    canonical_map: dict[str, str] = {}
    seen: list[str] = []

    for desc in descriptions:
        cleaned = clean_description(desc).upper()
        if not seen:
            seen.append(cleaned)
            canonical_map[desc] = clean_description(desc).title()
            continue
        best, score = fuzz_process.extractOne(
            cleaned, seen, scorer=fuzz.token_set_ratio
        )
        if score >= threshold:
            # Map to the first canonical version we saw
            original = next(k for k, v in canonical_map.items() if clean_description(k).upper() == best)
            canonical_map[desc] = canonical_map[original]
        else:
            seen.append(cleaned)
            canonical_map[desc] = clean_description(desc).title()

    return canonical_map
