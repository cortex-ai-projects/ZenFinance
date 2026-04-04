"""
ZenFinance — ICICI Bank PDF Statement Parser
Extracts transactions from ICICI Bank PDF account statements using PyMuPDF.

Typical ICICI PDF table layout (columns, left-to-right):
  S.No. | Transaction Date | Value Date | Description | Cheque No. | Debit (INR) | Credit (INR) | Balance (INR)

The parser handles multi-line description cells and trims header/footer noise.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, date
from typing import List, Optional

import pandas as pd

from zenfinance.models import TransactionDTO
from zenfinance.parsers.base import BaseParser
from zenfinance.parsers.icici import _parse_icici_description


# ── Date patterns seen in ICICI PDFs ──────────────────────────────────────
_DATE_PATTERNS = [
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d %b %Y",
    "%d/%m/%y",
]


def _parse_date(raw: str) -> Optional[date]:
    raw = raw.strip()
    for fmt in _DATE_PATTERNS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _safe_amount(raw: str) -> float:
    """Strip currency symbols and commas, return float."""
    cleaned = re.sub(r"[₹,\s]", "", str(raw).strip())
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = []
        for page in doc:
            pages.append(page.get_text("text"))
        return "\n".join(pages)
    except ImportError:
        raise ImportError(
            "PyMuPDF is required for PDF parsing. Install: pip install pymupdf"
        )


def _extract_tables_from_pdf(file_bytes: bytes) -> List[dict]:
    """
    Use PyMuPDF's table-extraction API (available in fitz >= 1.23) if possible,
    otherwise fall back to regex-based text parsing.
    """
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        rows = []
        for page in doc:
            try:
                tabs = page.find_tables()
                for tab in tabs.tables:
                    for r in tab.extract():
                        if r and len(r) >= 7:
                            rows.append(r)
            except Exception:
                pass
        return rows
    except Exception:
        return []


# ── Regex-based fallback parser ────────────────────────────────────────────
_DATE_RE = re.compile(r"\b(\d{2}[/\-]\d{2}[/\-]\d{2,4})\b")
_AMOUNT_RE = re.compile(r"[\d,]+\.\d{2}")


def _parse_via_text(text: str) -> List[dict]:
    """
    Fallback: scan PDF text line-by-line looking for transaction rows.
    A transaction row typically starts with a date (DD/MM/YYYY).
    """
    transactions = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    i = 0
    while i < len(lines):
        line = lines[i]
        # Check if this line starts with a date
        date_m = _DATE_RE.match(line)
        if not date_m:
            i += 1
            continue

        txn_date_str = date_m.group(1)
        txn_date = _parse_date(txn_date_str)
        if txn_date is None:
            i += 1
            continue

        # Gather the rest of this transaction block (up to 4 more lines)
        block_lines = [line]
        j = i + 1
        while j < len(lines) and j < i + 5:
            if _DATE_RE.match(lines[j]):
                break
            block_lines.append(lines[j])
            j += 1

        block = " ".join(block_lines)
        amounts = _AMOUNT_RE.findall(block)
        if len(amounts) < 2:
            i = j
            continue

        # Description is everything between the date match and the first amount
        desc_start = date_m.end()
        first_amt_pos = block.find(amounts[0])
        description = block[desc_start:first_amt_pos].strip()

        # Heuristic: last two amounts are debit, credit (or vice-versa)
        # The balance is the last amount; debit/credit are the two before it
        float_amounts = [_safe_amount(a) for a in amounts]

        debit = credit = 0.0
        if len(float_amounts) >= 3:
            # Pattern: ... debit credit balance
            # Non-zero middle values indicate the transaction direction
            # Try to pick debit and credit from second-to-last and third-to-last
            debit  = float_amounts[-3] if len(float_amounts) >= 3 else 0.0
            credit = float_amounts[-2]
        elif len(float_amounts) == 2:
            debit  = float_amounts[0]
            credit = float_amounts[1]

        # Determine direction
        txn_type: Optional[str] = None
        amount = 0.0
        if debit > 0 and credit == 0:
            txn_type, amount = "DEBIT", debit
        elif credit > 0 and debit == 0:
            txn_type, amount = "CREDIT", credit
        elif debit > 0 and credit > 0:
            # Both non-zero — ambiguous; skip
            i = j
            continue

        if txn_type and amount > 0:
            transactions.append({
                "date": txn_date,
                "description": description,
                "debit": debit,
                "credit": credit,
                "txn_type": txn_type,
                "amount": amount,
            })

        i = j

    return transactions


def _parse_via_table_rows(rows: List) -> List[dict]:
    """
    Parse structured table rows returned by fitz table extractor.
    Expected columns: [S.No., Txn Date, Value Date, Description, Cheque No., Debit, Credit, Balance]
    """
    transactions = []
    for row in rows:
        try:
            # Normalize cells
            cells = [str(c).strip() if c else "" for c in row]
            if len(cells) < 6:
                continue

            # Try to find a date in cells[1] or cells[0]
            txn_date = None
            for ci in [1, 0, 2]:
                if ci < len(cells):
                    txn_date = _parse_date(cells[ci])
                    if txn_date:
                        break
            if txn_date is None:
                continue

            # Description is usually cells[3]
            description = cells[3] if len(cells) > 3 else ""

            debit  = _safe_amount(cells[-3]) if len(cells) >= 3 else 0.0
            credit = _safe_amount(cells[-2]) if len(cells) >= 2 else 0.0

            txn_type: Optional[str] = None
            amount = 0.0
            if debit > 0 and credit == 0:
                txn_type, amount = "DEBIT", debit
            elif credit > 0 and debit == 0:
                txn_type, amount = "CREDIT", credit

            if txn_type and amount > 0:
                transactions.append({
                    "date": txn_date,
                    "description": description,
                    "debit": debit,
                    "credit": credit,
                    "txn_type": txn_type,
                    "amount": amount,
                })
        except Exception:
            continue
    return transactions


class ICICIPDFParser(BaseParser):
    """Parses ICICI Bank PDF account statements."""

    bank_name = "ICICI"

    def parse(self, file_like, filename: str) -> List[TransactionDTO]:
        raw = file_like.read() if hasattr(file_like, "read") else file_like

        # Try structured table extraction first
        table_rows = _extract_tables_from_pdf(raw)
        if table_rows:
            raw_rows = _parse_via_table_rows(table_rows)
        else:
            text = _extract_text_from_pdf(raw)
            raw_rows = _parse_via_text(text)

        dtos = []
        for row in raw_rows:
            dto = self._convert_row(row, filename)
            if dto:
                dtos.append(dto)
        return dtos

    def _convert_row(self, row: dict, filename: str) -> Optional[TransactionDTO]:
        txn_date = row.get("date")
        if not isinstance(txn_date, date):
            return None

        amount   = float(row.get("amount", 0))
        txn_type = row.get("txn_type")
        desc     = str(row.get("description", "")).strip()

        if txn_type not in ("DEBIT", "CREDIT") or amount == 0:
            return None

        parsed = _parse_icici_description(desc)

        return TransactionDTO(
            id=uuid.uuid4(),
            date=txn_date,
            amount=amount,
            bank_description=desc,
            details=parsed["details"],
            txn_type=txn_type,
            bank_name=self.bank_name,
            payment_method=parsed["payment_method"],
            utr_number=parsed["utr_number"],
            audit_status="Pending",
            source_file=filename,
        )
