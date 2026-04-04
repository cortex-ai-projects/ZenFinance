"""
ZenFinance — SBI Bank Excel Parser
Expects the standard SBI statement XLSX (data starts at row 21).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, date
from typing import List, Optional

import pandas as pd

from zenfinance.models import TransactionDTO
from zenfinance.parsers.base import BaseParser


def _parse_sbi_description(description: str) -> dict:
    parsed = {"utr_number": None, "details": None, "payment_method": "Other"}
    if not isinstance(description, str):
        return parsed

    desc = description.strip()

    if "UPI/" in desc:
        desc_clean = desc.replace("TO TRANSFER-", "").replace("BY TRANSFER-", "").strip()
        m = re.search(r"UPI/(DR|CR)/(\d+)/.*?/.*?/(.*)", desc_clean)
        if m:
            parsed["utr_number"] = m.group(2)
            parsed["details"]    = m.group(3).strip()
        parsed["payment_method"] = "UPI"

    elif "CREDIT INTEREST" in desc:
        parsed["details"]        = "Credit Interest"
        parsed["payment_method"] = "Interest"

    elif "BULK POSTING" in desc:
        m = re.search(r"BULK POSTING-(.*)", desc)
        parsed["details"]        = m.group(1).strip() if m else desc
        parsed["payment_method"] = "NACH" if "ACH" in desc else "Bulk Transfer"

    elif "NEFT" in desc:
        parsed["payment_method"] = "NEFT"
        m = re.search(r"NEFT-([^-]+)-(.*)", desc)
        if m:
            parsed["utr_number"] = m.group(1)
            parsed["details"]    = m.group(2).strip()

    elif "IMPS" in desc:
        parsed["payment_method"] = "IMPS"
        m = re.search(r"IMPS/(\d+)/(\d+)/(.*?)/", desc)
        if m:
            parsed["utr_number"] = m.group(1)
            parsed["details"]    = f"IMPS A/C: {m.group(2)}, Details: {m.group(3).strip()}"

    elif "ATM WDL" in desc:
        parsed["payment_method"] = "ATM Withdrawal"
        parsed["details"]        = desc

    elif "POS" in desc:
        parsed["payment_method"] = "POS"
        parsed["details"]        = desc

    else:
        parsed["details"] = desc

    return parsed


class SBIParser(BaseParser):
    bank_name = "SBI"

    def parse(self, file_like, filename: str) -> List[TransactionDTO]:
        try:
            df = pd.read_excel(file_like, skiprows=20)
        except Exception:
            # Try different skiprows if default fails
            try:
                df = pd.read_excel(file_like, skiprows=0)
            except Exception as e:
                raise ValueError(f"Could not parse SBI file: {e}")

        dtos = []
        for _, row in df.iterrows():
            dto = self._convert_row(row, filename)
            if dto:
                dtos.append(dto)
        return dtos

    def _convert_row(self, row: pd.Series, filename: str) -> Optional[TransactionDTO]:
        txn_date      = row.get("Txn Date")
        description   = self._safe_str(row.get("Description", ""))
        ref_no        = row.get("Ref No./Cheque No.")
        debit_amount  = row.get("Debit")
        credit_amount = row.get("Credit")

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
        if isinstance(txn_date, (pd.Timestamp, datetime)):
            transaction_date = txn_date.date()
        elif isinstance(txn_date, date):
            transaction_date = txn_date

        if transaction_date is None:
            return None

        parsed = _parse_sbi_description(description)

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
