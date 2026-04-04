"""
ZenFinance — Parser Registry
Maps source names to their parser classes.
"""
from __future__ import annotations

from zenfinance.parsers.sbi     import SBIParser
from zenfinance.parsers.icici   import ICICIParser
from zenfinance.parsers.phonepe import PhonePeParser
from zenfinance.parsers.gpay    import GPayParser
from zenfinance.parsers.generic import GenericParser

PARSER_REGISTRY: dict[str, type] = {
    "SBI Bank":         SBIParser,
    "ICICI Bank":       ICICIParser,
    "PhonePe":          PhonePeParser,
    "Google Pay":       GPayParser,
    "HDFC Bank":        GenericParser,
    "Axis Bank":        GenericParser,
    "Kotak Bank":       GenericParser,
    "Paytm":            GenericParser,
    "Amazon Pay":       GenericParser,
    "Swiggy Money":     GenericParser,
    "Other / Generic":  GenericParser,
}

SUPPORTED_SOURCES = list(PARSER_REGISTRY.keys())

ACCEPTED_EXTENSIONS = {
    "SBI Bank":         [".xlsx", ".xls"],
    "ICICI Bank":       [".xlsx", ".xls"],
    "PhonePe":          [".pdf"],
    "Google Pay":       [".csv"],
    "HDFC Bank":        [".xlsx", ".xls", ".csv"],
    "Axis Bank":        [".xlsx", ".xls", ".csv"],
    "Kotak Bank":       [".xlsx", ".xls", ".csv"],
    "Paytm":            [".csv", ".xlsx"],
    "Amazon Pay":       [".csv"],
    "Swiggy Money":     [".csv"],
    "Other / Generic":  [".csv", ".xlsx", ".xls"],
}


def get_parser(source: str, bank_name: str = "Other"):
    cls = PARSER_REGISTRY.get(source, GenericParser)
    if cls is GenericParser:
        return cls(bank_name=source)
    return cls()
