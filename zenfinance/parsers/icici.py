"""
ZenFinance — ICICI Bank Excel/XLS Parser
Expects the standard ICICI statement (data starts at row 13, columns B:I).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, date
from typing import List, Optional

import pandas as pd

from zenfinance.models import TransactionDTO
from zenfinance.parsers.base import BaseParser


def _parse_icici_description(description: str) -> dict:
    parsed = {"utr_number": None, "details": None, "payment_method": "Other"}
    if not isinstance(description, str):
        return parsed

    desc = description.strip()

    m_upi = re.search(r"UPI/(.*?)/(.*?)/(.*?)/(\d+)/(.*)", desc)
    if m_upi:
        parsed["utr_number"]     = m_upi.group(4)
        parsed["details"]        = m_upi.group(2).strip()
        parsed["payment_method"] = "UPI"

    elif "NEFT-" in desc:
        parsed["payment_method"] = "NEFT"
        m = re.search(r"NEFT-([^-]+)-(.*)", desc)
        if m:
            parsed["utr_number"] = m.group(1)
            parsed["details"]    = m.group(2).strip()

    elif "IMPS/" in desc:
        parsed["payment_method"] = "IMPS"
        m = re.search(r"IMPS/(\d+)/(\d+)/(.*?)/", desc)
        if m:
            parsed["utr_number"] = m.group(1)
            parsed["details"]    = f"IMPS A/C: {m.group(2)}, Details: {m.group(3).strip()}"

    elif "NACH" in desc or "ACH" in desc:
        parsed["payment_method"] = "NACH"
        parsed["details"]        = desc

    elif "ATM WDL" in desc:
        parsed["payment_method"] = "ATM Withdrawal"
        parsed["details"]        = desc

    elif "POS" in desc:
        parsed["payment_method"] = "POS"
        parsed["details"]        = desc

    else:
        parsed["details"] = desc

    return parsed


class ICICIParser(BaseParser):
    bank_name = "ICICI"

    def parse(self, file_like, filename: str) -> List[TransactionDTO]:
        # Try with standard ICICI skiprows
        for skiprows, usecols in [(12, "B:I"), (0, None)]:
            try:
                df = pd.read_excel(file_like, skiprows=skiprows, usecols=usecols)
                if len(df) > 0:
                    break
            except Exception:
                continue
        else:
            raise ValueError("Could not parse ICICI file.")

        dtos = []
        for _, row in df.iterrows():
            dto = self._convert_row(row, filename)
            if dto:
                dtos.append(dto)
        return dtos

    def _convert_row(self, row: pd.Series, filename: str) -> Optional[TransactionDTO]:
        txn_date      = row.get("Transaction Date")
        description   = self._safe_str(row.get("Transaction Remarks", ""))
        ref_no        = row.get("Cheque Number")
        debit_amount  = row.get("Withdrawal Amount (INR )")
        credit_amount = row.get("Deposit Amount (INR )")

        txn_type = None
        amount   = 0.0
        if pd.notna(debit_amount) and self._safe_float(debit_amount) > 0:
            txn_type = "DEBIT"
            amount   = self._safe_float(debit_amount)
        elif pd.notna(credit_amount) and self._safe_float(credit_amount) > 0:
            txn_type = "CREDIT"
            amount   = self._safe_float(credit_amount)

        if txn_type is None:
            return None

        transaction_date = None
        if isinstance(txn_date, str):
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
                try:
                    transaction_date = datetime.strptime(txn_date, fmt).date()
                    break
                except ValueError:
                    continue
        elif isinstance(txn_date, (pd.Timestamp, datetime)):
            transaction_date = txn_date.date()
        elif isinstance(txn_date, date):
            transaction_date = txn_date

        if transaction_date is None:
            return None

        parsed = _parse_icici_description(description)

        return TransactionDTO(
            id=uuid.uuid4(),
            date=transaction_date,
            amount=amount,
            bank_description=description,
            details=parsed["details"],
            txn_type=txn_type,
            bank_name=self.bank_name,
            payment_method=parsed["payment_method"],
            utr_number=parsed["utr_number"],
            reference_number=self._safe_str(ref_no) if pd.notna(ref_no) else None,
            audit_status="Pending",
            source_file=filename,
        )
