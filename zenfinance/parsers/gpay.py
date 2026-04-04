"""
ZenFinance — Google Pay CSV Statement Parser
Handles the standard Google Pay transaction history export (CSV).
"""
from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import List, Optional

import pandas as pd

from zenfinance.models import TransactionDTO
from zenfinance.parsers.base import BaseParser


class GPayParser(BaseParser):
    bank_name = "Google Pay"

    # Possible column name variations
    _DATE_COLS   = ["Date", "Transaction Date", "date", "Timestamp"]
    _DESC_COLS   = ["Description", "Transaction Description", "Merchant", "description"]
    _AMOUNT_COLS = ["Amount (INR)", "Amount", "amount", "Transaction Amount"]
    _TYPE_COLS   = ["Transaction Type", "Type", "type"]
    _UTR_COLS    = ["UTR", "UTR No.", "utr_number", "UPI Ref No"]

    def parse(self, file_like, filename: str) -> List[TransactionDTO]:
        try:
            df = pd.read_csv(file_like)
        except Exception as e:
            raise ValueError(f"Could not parse Google Pay CSV: {e}")

        dtos = []
        for _, row in df.iterrows():
            dto = self._convert_row(row, filename)
            if dto:
                dtos.append(dto)
        return dtos

    def _get(self, row: pd.Series, candidates: list) -> Optional[str]:
        for col in candidates:
            if col in row.index and pd.notna(row[col]):
                return str(row[col]).strip()
        return None

    def _convert_row(self, row: pd.Series, filename: str) -> Optional[TransactionDTO]:
        date_str = self._get(row, self._DATE_COLS)
        desc     = self._get(row, self._DESC_COLS) or ""
        amt_str  = self._get(row, self._AMOUNT_COLS)
        type_str = self._get(row, self._TYPE_COLS)
        utr      = self._get(row, self._UTR_COLS)

        if not amt_str:
            return None
        amount = self._safe_float(amt_str.replace("INR", "").replace("₹", "").strip())
        if amount == 0:
            return None

        # Infer txn_type from the type column or description heuristics
        txn_type: Optional[str] = None
        if type_str:
            t = type_str.upper()
            if any(x in t for x in ["DEBIT", "PAID", "SENT", "OUT"]):
                txn_type = "DEBIT"
            elif any(x in t for x in ["CREDIT", "RECEIVED", "IN"]):
                txn_type = "CREDIT"
        if txn_type is None:
            txn_type = "DEBIT"  # default

        transaction_date = None
        if date_str:
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%b %d, %Y", "%d %b %Y", "%m/%d/%Y"):
                try:
                    transaction_date = datetime.strptime(date_str[:20], fmt).date()
                    break
                except ValueError:
                    continue
        if transaction_date is None:
            return None

        return TransactionDTO(
            id=uuid.uuid4(),
            date=transaction_date,
            amount=amount,
            bank_description=desc,
            details=desc,
            txn_type=txn_type,
            bank_name=self.bank_name,
            payment_method="UPI",
            utr_number=utr,
            audit_status="Pending",
            source_file=filename,
        )
