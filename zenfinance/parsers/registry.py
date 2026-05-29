"""
ZenFinance — Parser Registry
Maps source names to their parser class(es), supporting multiple formats
per source (e.g. ICICI Bank can be XLS or PDF).

Structure
─────────
PARSER_REGISTRY[source][".ext"] = ParserClass

get_parser(source, filename) resolves the correct class based on the
file extension.  Falls back to the first registered parser if the
extension isn't explicitly listed.
"""
from __future__ import annotations

from zenfinance.parsers.sbi      import SBIParser
from zenfinance.parsers.sbi_pdf  import SBIPDFParser
from zenfinance.parsers.icici    import ICICIParser
from zenfinance.parsers.icici_pdf import ICICIPDFParser
from zenfinance.parsers.phonepe  import PhonePeParser
from zenfinance.parsers.gpay     import GPayParser
from zenfinance.parsers.gpay_pdf import GPayPDFParser
from zenfinance.parsers.axio     import AXIOParser
from zenfinance.parsers.generic  import GenericParser


# ── Multi-format registry ──────────────────────────────────────────────────
# Each source maps an extension → parser class.
# The special key "__default__" is used when no extension match is found.
PARSER_REGISTRY: dict[str, dict[str, type]] = {

    # ── Banks ──────────────────────────────────────────────────────────────
    "SBI Bank": {
        ".xlsx":       SBIParser,
        ".xls":        SBIParser,
        ".csv":        SBIParser,   # SBI CSV export — auto-detects header row
        ".pdf":        SBIPDFParser,
        "__default__": SBIParser,
    },
    "ICICI Bank": {
        ".xlsx":     ICICIParser,
        ".xls":      ICICIParser,
        ".pdf":      ICICIPDFParser,
        "__default__": ICICIParser,
    },
    "HDFC Bank": {
        ".xlsx":     GenericParser,
        ".xls":      GenericParser,
        ".csv":      GenericParser,
        ".pdf":      GenericParser,
        "__default__": GenericParser,
    },
    "Axis Bank": {
        ".xlsx":     GenericParser,
        ".xls":      GenericParser,
        ".csv":      GenericParser,
        ".pdf":      GenericParser,
        "__default__": GenericParser,
    },
    "Kotak Bank": {
        ".xlsx":     GenericParser,
        ".xls":      GenericParser,
        ".csv":      GenericParser,
        "__default__": GenericParser,
    },

    # ── UPI / Payment intermediators ───────────────────────────────────────
    "PhonePe": {
        ".pdf":      PhonePeParser,
        "__default__": PhonePeParser,
    },
    "Google Pay": {
        ".csv":        GPayParser,
        ".pdf":        GPayPDFParser,
        "__default__": GPayPDFParser,
    },
    "Paytm": {
        ".csv":      GenericParser,
        ".xlsx":     GenericParser,
        "__default__": GenericParser,
    },
    "Amazon Pay": {
        ".csv":      GenericParser,
        "__default__": GenericParser,
    },

    # ── Audit source (user's ground-truth ledger) ──────────────────────────
    "AXIO": {
        ".csv":      AXIOParser,
        ".xlsx":     AXIOParser,
        ".xls":      AXIOParser,
        "__default__": AXIOParser,
    },

    # ── Delivery / terminal apps ───────────────────────────────────────────
    "Swiggy": {
        ".csv":      GenericParser,
        ".xlsx":     GenericParser,
        "__default__": GenericParser,
    },
    "Zomato": {
        ".csv":      GenericParser,
        ".xlsx":     GenericParser,
        "__default__": GenericParser,
    },
    "Blinkit": {
        ".csv":      GenericParser,
        ".xlsx":     GenericParser,
        "__default__": GenericParser,
    },
    "Zepto": {
        ".csv":      GenericParser,
        ".xlsx":     GenericParser,
        "__default__": GenericParser,
    },
    "BigBasket": {
        ".csv":      GenericParser,
        ".xlsx":     GenericParser,
        "__default__": GenericParser,
    },
    "Amazon": {
        ".csv":      GenericParser,
        ".xlsx":     GenericParser,
        "__default__": GenericParser,
    },
    "Swiggy Money": {
        ".csv":      GenericParser,
        "__default__": GenericParser,
    },

    # ── Catch-all ─────────────────────────────────────────────────────────
    "Other / Generic": {
        ".csv":      GenericParser,
        ".xlsx":     GenericParser,
        ".xls":      GenericParser,
        "__default__": GenericParser,
    },
}

# Flat list of all supported sources (for UI dropdowns)
SUPPORTED_SOURCES = list(PARSER_REGISTRY.keys())

# Accepted file extensions per source (drives the file_uploader type filter)
ACCEPTED_EXTENSIONS: dict[str, list[str]] = {
    src: [ext for ext in exts if ext != "__default__"]
    for src, exts in PARSER_REGISTRY.items()
}

# ── Source-classification helpers (used by the audit engine) ──────────────

# Banks: raw ledger — primary audit targets
BANK_SOURCES = ["SBI", "ICICI", "HDFC", "Axis", "Kotak"]

# Intermediator payment rails — route money but don't confirm the merchant
INTERMEDIATOR_SOURCES = ["PhonePe", "Google Pay", "Paytm", "Amazon Pay", "BHIM"]

# Terminal / merchant apps — confirm the actual spending event
TERMINAL_SOURCES = [
    "Swiggy", "Zomato", "Blinkit", "Zepto",
    "BigBasket", "Amazon", "Swiggy Money",
    "Dunzo", "Instamart", "JioMart",
    "Ola", "Uber", "Rapido",
]

# Audit ground-truth source (user's manually curated ledger)
AUDIT_SOURCES = ["AXIO"]


def get_parser(source: str, filename: str = "", bank_name: str = "Other"):
    """
    Return the correct parser instance for (source, file extension).

    Args:
        source:    Registry key (e.g. "ICICI Bank", "PhonePe")
        filename:  Original filename — extension used for format routing
        bank_name: Fallback bank label for GenericParser instances
    """
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""

    source_map = PARSER_REGISTRY.get(source)

    if source_map is None:
        # Unknown source — fall back to GenericParser
        return GenericParser(bank_name=source)

    cls = source_map.get(ext) or source_map.get("__default__", GenericParser)

    # GenericParser needs a bank_name; all others are singletons
    if cls is GenericParser:
        return cls(bank_name=source)
    return cls()
