"""
ZenFinance — PhonePe PDF Statement Parser
Uses PyMuPDF (fitz) to extract text from PhonePe PDF statements.
"""
from __future__ import annotations

import io
import re
import uuid
from datetime import datetime, date
from typing import List, Optional

import pandas as pd

from zenfinance.models import TransactionDTO
from zenfinance.parsers.base import BaseParser


def _extract_text(file_bytes: bytes) -> str:
    try:
        import fitz
        doc  = fitz.open(stream=file_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        return text
    except ImportError:
        raise ImportError("PyMuPDF (fitz) is required for PDF parsing. Install: pip install pymupdf")


def _parse_transactions_from_text(text: str) -> pd.DataFrame:
    transactions = []
    blocks = re.split(r"\n(?=\w{3}\s\d{2},\s\d{4}\n\d{2}:\d{2}\s[AP]M)", text)

    for block in blocks:
        if not block.strip() or "Transaction Statement for" in block:
            continue
        try:
            date_m  = re.search(r"(\w{3}\s\d{2},\s\d{4})", block)
            time_m  = re.search(r"(\d{2}:\d{2}\s[AP]M)", block)
            ta_m    = re.search(r"(DEBIT|CREDIT)\s₹([\d,]+\.?\d*)", block)
            txn_id  = re.search(r"Transaction ID\s(.+?)\n", block)
            utr_m   = re.search(r"UTR No\.\s(.+?)\n", block)
            paid_m  = re.search(r"Paid by\n(.+?)\n", block)
            cred_m  = re.search(r"Credited to\n(.+?)\n", block)
            det_m   = re.search(r"\d{2}:\d{2}\s[AP]M\n(.*?)\nTransaction ID", block, re.DOTALL)

            txn_type   = ta_m.group(1) if ta_m else None
            amount_str = ta_m.group(2) if ta_m else "0"
            amount     = float(amount_str.replace(",", ""))

            if date_m and txn_type:
                transactions.append({
                    "date":           date_m.group(1),
                    "bank_description": det_m.group(1).strip().replace("\n", " ") if det_m else "",
                    "txn_type":       txn_type,
                    "amount":         amount,
                    "transaction_id": txn_id.group(1).strip() if txn_id else None,
                    "utr_number":     utr_m.group(1).strip() if utr_m else None,
                    "details":        (paid_m or cred_m).group(1).strip() if (paid_m or cred_m) else None,
                    "payment_method": "UPI",
                })
        except Exception:
            continue

    return pd.DataFrame(transactions)


class PhonePeParser(BaseParser):
    bank_name = "PhonePe"

    def parse(self, file_like, filename: str) -> List[TransactionDTO]:
        raw = file_like.read() if hasattr(file_like, "read") else file_like
        text = _extract_text(raw)
        df   = _parse_transactions_from_text(text)

        if df.empty:
            return []

        dtos = []
        for _, row in df.iterrows():
            dto = self._convert_row(row, filename)
            if dto:
                dtos.append(dto)
        return dtos

    def _convert_row(self, row: pd.Series, filename: str) -> Optional[TransactionDTO]:
        txn_date = row.get("date")
        amount   = self._safe_float(row.get("amount", 0))
        txn_type = row.get("txn_type")

        if txn_type not in ("DEBIT", "CREDIT") or amount == 0:
            return None

        transaction_date = None
        if isinstance(txn_date, str):
            try:
                transaction_date = datetime.strptime(txn_date, "%b %d, %Y").date()
            except ValueError:
                pass
        elif isinstance(txn_date, (pd.Timestamp, datetime)):
            transaction_date = txn_date.date()
        elif isinstance(txn_date, date):
            transaction_date = txn_date

        if transaction_date is None:
            return None

        return TransactionDTO(
            id=uuid.uuid4(),
            date=transaction_date,
            amount=amount,
            bank_description=self._safe_str(row.get("bank_description", "")),
            details=self._safe_str(row.get("details", "")),
            txn_type=txn_type,
            bank_name=self.bank_name,
            payment_method=self._safe_str(row.get("payment_method", "UPI")),
            transaction_id=self._safe_str(row.get("transaction_id", "")),
            utr_number=self._safe_str(row.get("utr_number", "")),
            audit_status="Pending",
            source_file=filename,
        )
