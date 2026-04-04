"""
ZenFinance — SBI Bank PDF Statement Parser
Extracts transactions from SBI Bank PDF account statements using PyMuPDF.

Typical SBI PDF table layout:
  Txn Date | Value Date | Description | Ref No./Cheque No. | Debit | Credit | Balance

The parser first tries PyMuPDF structured table extraction, then falls back
to regex-based text scanning for non-standard statement layouts.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, date
from typing import List, Optional

import pandas as pd

from zenfinance.models import TransactionDTO
from zenfinance.parsers.base import BaseParser
from zenfinance.parsers.sbi import _parse_sbi_description


# ── Date patterns seen in SBI PDFs ────────────────────────────────────────
_DATE_PATTERNS = [
    "%d %b %Y",     # 15 Jan 2025
    "%d/%m/%Y",     # 15/01/2025
    "%d-%m-%Y",     # 15-01-2025
    "%d/%m/%y",     # 15/01/25
    "%d %B %Y",     # 15 January 2025
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
    cleaned = re.sub(r"[₹,\s]", "", str(raw).strip())
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = []
        for page in doc:
            pages.append(page.get_text("text"))
        return "\n".join(pages)
    except ImportError:
        raise ImportError(
            "PyMuPDF is required for PDF parsing. Install: pip install pymupdf"
        )


def _extract_tables_from_pdf(file_bytes: bytes) -> List:
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        rows = []
        for page in doc:
            try:
                tabs = page.find_tables()
                for tab in tabs.tables:
                    for r in tab.extract():
                        if r and len(r) >= 5:
                            rows.append(r)
            except Exception:
                pass
        return rows
    except Exception:
        return []


# ── Regex to detect SBI-style date tokens ─────────────────────────────────
_DATE_RE = re.compile(
    r"\b(\d{2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}|\d{2}[/\-]\d{2}[/\-]\d{2,4})\b",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(r"[\d,]+\.\d{2}")


def _parse_via_text(text: str) -> List[dict]:
    """
    Line-by-line fallback parser for SBI PDF text.
    Looks for lines that begin with a recognisable SBI date format.
    """
    transactions = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    i = 0
    while i < len(lines):
        line = lines[i]
        date_m = _DATE_RE.search(line)
        if not date_m:
            i += 1
            continue

        txn_date = _parse_date(date_m.group(1))
        if txn_date is None:
            i += 1
            continue

        # Collect block (up to 5 more lines before hitting next date)
        block_lines = [line]
        j = i + 1
        while j < len(lines) and j < i + 6:
            if _DATE_RE.search(lines[j]):
                break
            block_lines.append(lines[j])
            j += 1

        block = " ".join(block_lines)
        amounts = _AMOUNT_RE.findall(block)
        if len(amounts) < 2:
            i = j
            continue

        float_amounts = [_safe_amount(a) for a in amounts]

        # Last amount is usually balance; second-last is credit; third-last is debit
        debit  = float_amounts[-3] if len(float_amounts) >= 3 else 0.0
        credit = float_amounts[-2] if len(float_amounts) >= 2 else 0.0

        txn_type: Optional[str] = None
        amount = 0.0
        if debit > 0 and credit == 0:
            txn_type, amount = "DEBIT", debit
        elif credit > 0 and debit == 0:
            txn_type, amount = "CREDIT", credit

        if txn_type and amount > 0:
            # Extract description: text between end of date and first amount
            first_amt_idx = block.find(amounts[0])
            date_end = block.find(date_m.group(1)) + len(date_m.group(1))
            description = block[date_end:first_amt_idx].strip()

            # Extract reference number from description (common SBI format)
            ref_m = re.search(r"\b(\d{16,22})\b", description)
            ref_no = ref_m.group(1) if ref_m else None

            transactions.append({
                "date": txn_date,
                "description": description,
                "ref_no": ref_no,
                "txn_type": txn_type,
                "amount": amount,
            })

        i = j

    return transactions


def _parse_via_table_rows(rows: List) -> List[dict]:
    """
    Parse structured table rows from PyMuPDF table extractor.
    Typical SBI columns:
      [Txn Date, Value Date, Description, Ref No./Cheque No., Debit, Credit, Balance]
    """
    transactions = []
    for row in rows:
        try:
            cells = [str(c).strip() if c else "" for c in row]
            if len(cells) < 5:
                continue

            # Try cell[0] then cell[1] for date
            txn_date = None
            for ci in [0, 1]:
                if ci < len(cells):
                    txn_date = _parse_date(cells[ci])
                    if txn_date:
                        break
            if txn_date is None:
                continue

            # Description in cell[2]
            description = cells[2] if len(cells) > 2 else ""
            ref_no      = cells[3] if len(cells) > 3 else ""
            debit       = _safe_amount(cells[4]) if len(cells) > 4 else 0.0
            credit      = _safe_amount(cells[5]) if len(cells) > 5 else 0.0

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
                    "ref_no": ref_no,
                    "txn_type": txn_type,
                    "amount": amount,
                })
        except Exception:
            continue
    return transactions


class SBIPDFParser(BaseParser):
    """Parses SBI Bank PDF account statements."""

    bank_name = "SBI"

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
        ref_no   = str(row.get("ref_no", "")).strip() or None

        if txn_type not in ("DEBIT", "CREDIT") or amount == 0:
            return None

        parsed = _parse_sbi_description(desc)

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
            reference_number=ref_no,
            audit_status="Pending",
            source_file=filename,
        )
