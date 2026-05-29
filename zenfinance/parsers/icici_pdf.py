"""
ZenFinance — ICICI Bank PDF Statement Parser

Real ICICI PDF layout (pdftotext -layout):
──────────────────────────────────────────
  DATE         MODE**          PARTICULARS            DEPOSITS    WITHDRAWALS      BALANCE
  01-01-2021                   B/F                                                 3,71,263.80
                               UPI/100524300969/…
  05-01-2021                   Ph/EURONET@ybl/…                        10.00       3,71,253.80

Strategy: balance is always the rightmost amount. We determine DEBIT/CREDIT
by comparing consecutive balances — this avoids column-position detection
issues entirely and works regardless of layout variations.
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
from zenfinance.parsers.icici import _parse_icici_description


_DATE_RE   = re.compile(r"^(\d{2}-\d{2}-\d{4})\s")
_AMOUNT_RE = re.compile(r"[\d,]+\.\d{2}")
_HEADER_RE = re.compile(r"^\s*DATE\s+MODE", re.IGNORECASE)
_PAGE_RE   = re.compile(r"Page\s+\d+\s+of\s+\d+", re.IGNORECASE)
_BF_RE     = re.compile(r"\bB/F\b")
_SKIP_RE   = re.compile(
    r"^(MR\.|Statement of|ACCOUNT|RELATIONSHIP|Savings|TOTAL|Visit|Dial|Did you|"
    r"PPF|NOMINATION|FIXED|Current|Recurring|Total|\s*$)",
    re.IGNORECASE,
)


def _parse_date(s: str) -> Optional[date]:
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _indian_amount(s: str) -> float:
    """Parse Indian lakh-style amounts: 3,71,263.80 → 371263.80"""
    return float(re.sub(r"[₹,\s]", "", s.strip()) or "0")


def _extract_text_layout(file_bytes: bytes) -> str:
    """Use pdftotext -layout (poppler) if available, else PyMuPDF."""
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", "-", "-"],
            input=file_bytes, capture_output=True, timeout=30,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        return "\n".join(page.get_text("text") for page in doc)
    except ImportError:
        raise ImportError("pdftotext (poppler) or PyMuPDF required for PDF parsing.")


def _parse_layout_text(text: str) -> List[dict]:
    """
    Parse layout-preserved text into transaction dicts.

    1. Group physical lines into transactions (new txn starts with DD-MM-YYYY)
    2. Extract description and rightmost amount (= balance) per group
    3. Derive amount & direction from consecutive balance differences
    """
    lines = text.splitlines()

    # ── Pass 1: group lines into transaction blocks ───────────────────────
    blocks = []   # [{"date": date, "desc_parts": [...], "all_amounts": [...]}]
    current = None

    for line in lines:
        stripped = line.strip()
        if not stripped or _HEADER_RE.match(stripped) or _PAGE_RE.search(stripped):
            continue
        if _SKIP_RE.match(stripped):
            continue

        date_m = _DATE_RE.match(line)
        if date_m:
            if current and current["date"]:
                blocks.append(current)
            txn_date = _parse_date(date_m.group(1))
            rest = line[date_m.end():]
            # Strip MODE keywords
            rest = re.sub(
                r"\b(MOBILE BANKING|NET BANKING|CMS TRANSACTION|DEBIT CARD|OTHER ATMS)\b",
                "", rest,
            )
            amounts = _AMOUNT_RE.findall(rest)
            desc = _AMOUNT_RE.sub("", rest).strip()
            current = {
                "date": txn_date,
                "desc_parts": [desc] if desc else [],
                "all_amounts": [_indian_amount(a) for a in amounts],
            }
        elif current is not None:
            amounts = _AMOUNT_RE.findall(line)
            desc = _AMOUNT_RE.sub("", line).strip()
            desc = re.sub(
                r"\b(MOBILE BANKING|NET BANKING|CMS TRANSACTION|DEBIT CARD|OTHER ATMS)\b",
                "", desc,
            ).strip()
            if desc:
                current["desc_parts"].append(desc)
            current["all_amounts"].extend(_indian_amount(a) for a in amounts)

    if current and current["date"]:
        blocks.append(current)

    # ── Pass 2: extract balance (rightmost amount) and derive txn amounts ─
    results = []
    prev_balance = 0.0

    for blk in blocks:
        desc = " ".join(blk["desc_parts"]).strip()

        # B/F (brought forward) — just captures opening balance
        if _BF_RE.search(desc):
            if blk["all_amounts"]:
                prev_balance = blk["all_amounts"][-1]
            continue

        if not blk["all_amounts"]:
            continue

        balance = blk["all_amounts"][-1]  # rightmost = balance column

        # Derive amount from balance difference
        if prev_balance > 0:
            diff = round(balance - prev_balance, 2)
            if diff < 0:
                txn_type = "DEBIT"
                amount   = abs(diff)
            elif diff > 0:
                txn_type = "CREDIT"
                amount   = diff
            else:
                prev_balance = balance
                continue
        else:
            # No previous balance — try to use intermediate amounts
            if len(blk["all_amounts"]) >= 2:
                amount = blk["all_amounts"][-2]
                txn_type = "DEBIT"  # default guess
            else:
                prev_balance = balance
                continue

        if amount > 0:
            results.append({
                "date": blk["date"],
                "description": desc,
                "txn_type": txn_type,
                "amount": amount,
            })

        prev_balance = balance

    return results


class ICICIPDFParser(BaseParser):
    bank_name = "ICICI"

    def parse(self, file_like, filename: str) -> List[TransactionDTO]:
        raw = file_like.read() if hasattr(file_like, "read") else file_like
        text = _extract_text_layout(raw)
        raw_rows = _parse_layout_text(text)

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
