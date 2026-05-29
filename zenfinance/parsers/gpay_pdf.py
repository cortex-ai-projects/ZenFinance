"""
ZenFinance — Google Pay PDF Statement Parser

Real GPay PDF layout (pdftotext -layout):
─────────────────────────────────────────
Date & time                     Transaction details                                                                                Amount

01 Oct, 2025                    Paid to VJ82 MY HOME MANGALA                                                                       ₹104.40
08:18 AM                        UPI Transaction ID: 564015404173
                                    Paid by IDFC Bank XX41 | RuPay credit card

Each transaction block has:
  Line 1: date + "Paid to MERCHANT" or "Received from MERCHANT" + ₹Amount
  Line 2: time + UPI Transaction ID: NNNNN
  Line 3: Paid by / Received in BANK INFO
  Blank line separator

Amounts use ₹ symbol (not "INR") and may have commas: ₹3,900 or ₹104.40
"""
from __future__ import annotations

import io
import re
import subprocess
import uuid
from datetime import datetime, date
from typing import List, Optional

import pandas as pd

from zenfinance.models import TransactionDTO
from zenfinance.parsers.base import BaseParser


# ── Regexes ─────────────────────────────────────────────────────────────
_DATE_RE = re.compile(
    r"^(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec),\s+\d{4})",
    re.IGNORECASE,
)
_AMOUNT_RE    = re.compile(r"₹([\d,]+\.?\d*)")
_TXN_ID_RE    = re.compile(r"UPI Transaction ID:\s*(\d+)")
_PAID_RE      = re.compile(r"Paid to\s+(.+?)(?:\s{3,}|₹|$)")
_RECEIVED_RE  = re.compile(r"Received from\s+(.+?)(?:\s{3,}|₹|$)")
_PAID_BY_RE   = re.compile(r"Paid by\s+(.+)")
_RECV_IN_RE   = re.compile(r"Received in\s+(.+)")
_PAGE_RE      = re.compile(r"Page\s+\d+\s+of\s+\d+", re.IGNORECASE)

_DATE_FMTS = [
    "%d %b, %Y",   # 01 Oct, 2025
    "%d %B, %Y",   # 01 October, 2025
    "%d %b %Y",    # 01 Oct 2025
]


def _parse_date(s: str) -> Optional[date]:
    s = s.strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(s: str) -> float:
    cleaned = re.sub(r"[₹,\s]", "", s.strip())
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _extract_text_layout(file_bytes: bytes) -> str:
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", "-", "-"],
            input=file_bytes, capture_output=True, timeout=60,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except ImportError:
        raise ImportError("pdftotext (poppler) or PyMuPDF required for PDF parsing.")


def _parse_layout(text: str) -> List[dict]:
    """
    Parse GPay -layout text into transaction dicts.
    Each transaction is a block starting with a date line.
    """
    lines = text.splitlines()
    transactions = []
    current = None

    for line in lines:
        stripped = line.strip()

        # Skip empties, headers, page numbers, notes
        if not stripped:
            if current and current.get("date") and current.get("amount", 0) > 0:
                transactions.append(current)
                current = None
            continue

        if (
            "Transaction statement" in stripped
            or "Date & time" in stripped
            or "Transaction details" in stripped
            or _PAGE_RE.search(stripped)
            or stripped.startswith("Note:")
            or "pankaj" in stripped.lower()
            or "7248587306" in stripped
            or "Transaction statement period" in stripped
            or "This statement reflects" in stripped
            or "deleted from your Google" in stripped
        ):
            continue

        # Summary line like "Sent ₹35,988.75 Received ₹0"
        if re.match(r"^\s*(Sent|Received)\b", stripped):
            continue

        # Check if this line starts a new transaction
        date_m = _DATE_RE.match(stripped)
        if date_m:
            # Flush previous
            if current and current.get("date") and current.get("amount", 0) > 0:
                transactions.append(current)

            txn_date = _parse_date(date_m.group(1))
            rest = line[line.index(date_m.group(1)) + len(date_m.group(1)):]

            # Extract merchant
            merchant = ""
            paid_m = _PAID_RE.search(rest)
            recv_m = _RECEIVED_RE.search(rest)
            if paid_m:
                merchant = paid_m.group(1).strip()
            elif recv_m:
                merchant = recv_m.group(1).strip()

            # Determine type
            txn_type = "DEBIT"
            if recv_m:
                txn_type = "CREDIT"

            # Extract amount (₹ symbol)
            amount = 0.0
            amt_m = _AMOUNT_RE.search(rest)
            if amt_m:
                amount = _parse_amount(amt_m.group(1))

            current = {
                "date": txn_date,
                "merchant": merchant,
                "type": txn_type,
                "amount": amount,
                "txn_id": None,
                "payment_info": None,
            }
            continue

        # Continuation lines
        if current is not None:
            txn_m = _TXN_ID_RE.search(stripped)
            if txn_m:
                current["txn_id"] = txn_m.group(1).strip()

            paid_by_m = _PAID_BY_RE.search(stripped)
            recv_in_m = _RECV_IN_RE.search(stripped)
            if paid_by_m:
                current["payment_info"] = paid_by_m.group(1).strip()
            elif recv_in_m:
                current["payment_info"] = recv_in_m.group(1).strip()

            # Pick up amount if missing (wrapped to next line)
            if current["amount"] == 0:
                amt_m = _AMOUNT_RE.search(stripped)
                if amt_m:
                    current["amount"] = _parse_amount(amt_m.group(1))

            # Pick up merchant if missing
            if not current["merchant"]:
                paid_m = _PAID_RE.search(stripped)
                recv_m = _RECEIVED_RE.search(stripped)
                if paid_m:
                    current["merchant"] = paid_m.group(1).strip()
                elif recv_m:
                    current["merchant"] = recv_m.group(1).strip()

    # Flush last block
    if current and current.get("date") and current.get("amount", 0) > 0:
        transactions.append(current)

    return transactions


class GPayPDFParser(BaseParser):
    bank_name = "Google Pay"

    def parse(self, file_like, filename: str) -> List[TransactionDTO]:
        raw = file_like.read() if hasattr(file_like, "read") else file_like
        text = _extract_text_layout(raw)
        raw_rows = _parse_layout(text)

        if not raw_rows:
            return []

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

        amount = float(row.get("amount", 0))
        txn_type = row.get("type", "DEBIT")
        if txn_type not in ("DEBIT", "CREDIT") or amount == 0:
            return None

        merchant = row.get("merchant", "") or ""
        txn_id = row.get("txn_id")
        payment_info = row.get("payment_info", "")

        return TransactionDTO(
            id=uuid.uuid4(),
            date=txn_date,
            amount=amount,
            bank_description=merchant,
            details=merchant,
            txn_type=txn_type,
            bank_name=self.bank_name,
            payment_method="UPI",
            transaction_id=txn_id,
            system_comment=payment_info if payment_info else None,
            audit_status="Pending",
            source_file=filename,
        )
