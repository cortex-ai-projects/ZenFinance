"""
ZenFinance — Generic CSV / Excel Parser
Auto-detects column mappings for unknown statement formats.
"""
from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import List, Optional

import pandas as pd

from zenfinance.models import TransactionDTO
from zenfinance.parsers.base import BaseParser


_DATE_CANDIDATES   = ["date", "txn date", "transaction date", "value date", "posted date", "posting date"]
_DESC_CANDIDATES   = ["description", "narration", "particulars", "remarks", "details", "transaction remarks",
                      "merchant name", "beneficiary name"]
_DEBIT_CANDIDATES  = ["debit", "withdrawal", "debit amount", "withdrawal amount (inr )", "dr", "dr amount", "paid"]
_CREDIT_CANDIDATES = ["credit", "deposit", "credit amount", "deposit amount (inr )", "cr", "cr amount", "received"]
_AMOUNT_CANDIDATES = ["amount", "transaction amount", "amount (inr)"]
_TYPE_CANDIDATES   = ["type", "transaction type", "txn type", "dr/cr"]
_REF_CANDIDATES    = ["ref no./cheque no.", "ref no", "cheque number", "reference number", "utr", "utr no."]


def _find_col(df: pd.DataFrame, candidates: list) -> Optional[str]:
    normalized = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in normalized:
            return normalized[cand.lower()]
    return None


class GenericParser(BaseParser):
    bank_name = "Other"

    def __init__(self, bank_name: str = "Other"):
        self.bank_name = bank_name

    def parse(self, file_like, filename: str) -> List[TransactionDTO]:
        fname = filename.lower()
        try:
            if fname.endswith(".csv"):
                df = pd.read_csv(file_like)
            else:
                df = pd.read_excel(file_like)
        except Exception as e:
            raise ValueError(f"Could not parse file '{filename}': {e}")

        # Try to find columns
        date_col   = _find_col(df, _DATE_CANDIDATES)
        desc_col   = _find_col(df, _DESC_CANDIDATES)
        debit_col  = _find_col(df, _DEBIT_CANDIDATES)
        credit_col = _find_col(df, _CREDIT_CANDIDATES)
        amount_col = _find_col(df, _AMOUNT_CANDIDATES)
        type_col   = _find_col(df, _TYPE_CANDIDATES)
        ref_col    = _find_col(df, _REF_CANDIDATES)

        if not date_col:
            raise ValueError("Cannot find a date column in the uploaded file.")

        dtos = []
        for _, row in df.iterrows():
            dto = self._convert_row(
                row, filename, date_col, desc_col,
                debit_col, credit_col, amount_col, type_col, ref_col,
            )
            if dto:
                dtos.append(dto)
        return dtos

    def _convert_row(
        self, row, filename, date_col, desc_col,
        debit_col, credit_col, amount_col, type_col, ref_col,
    ) -> Optional[TransactionDTO]:
        # --- Date ---
        raw_date = row.get(date_col) if date_col else None
        txn_date = None
        if isinstance(raw_date, (pd.Timestamp, datetime)):
            txn_date = raw_date.date()
        elif isinstance(raw_date, date):
            txn_date = raw_date
        elif isinstance(raw_date, str):
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%b %d, %Y", "%d %b %Y", "%m/%d/%Y"):
                try:
                    txn_date = datetime.strptime(raw_date[:20], fmt).date()
                    break
                except ValueError:
                    continue
        if txn_date is None:
            return None

        # --- Description ---
        desc = self._safe_str(row.get(desc_col, "") if desc_col else "")

        # --- Amount & Type ---
        txn_type: Optional[str] = None
        amount   = 0.0

        if debit_col and credit_col:
            d = self._safe_float(row.get(debit_col, 0))
            c = self._safe_float(row.get(credit_col, 0))
            if d > 0:
                txn_type, amount = "DEBIT",  d
            elif c > 0:
                txn_type, amount = "CREDIT", c
        elif amount_col:
            amount = abs(self._safe_float(row.get(amount_col, 0)))
            if type_col:
                t = str(row.get(type_col, "")).upper()
                if any(x in t for x in ["DR", "DEBIT", "W"]):
                    txn_type = "DEBIT"
                elif any(x in t for x in ["CR", "CREDIT", "D"]):
                    txn_type = "CREDIT"
            txn_type = txn_type or ("DEBIT" if amount > 0 else None)

        if txn_type is None or amount == 0:
            return None

        ref = self._safe_str(row.get(ref_col, "") if ref_col else "")

        return TransactionDTO(
            id=uuid.uuid4(),
            date=txn_date,
            amount=amount,
            bank_description=desc,
            details=desc,
            txn_type=txn_type,
            bank_name=self.bank_name,
            payment_method=None,
            reference_number=ref or None,
            audit_status="Pending",
            source_file=filename,
        )
