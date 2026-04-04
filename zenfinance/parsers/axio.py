"""
ZenFinance — AXIO App Parser
AXIO is the user's personal finance / expense-tracking app where they
manually update transaction details and tags.  Importing an AXIO export
acts as the **ground truth** for audit reconciliation.

Supported export formats:
  • CSV  — most common AXIO export
  • XLSX — some versions export Excel

Typical AXIO CSV columns (ZenFinance will auto-detect variations):
  Date | Account | Category | Sub-category | Description/Merchant | Amount | Type | Tags | Notes | Currency

Key rule: any transaction imported from AXIO automatically gets
  audit_status = "Audited"  (it IS the audit source).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, date
from typing import List, Optional

import pandas as pd

from zenfinance.models import TransactionDTO
from zenfinance.parsers.base import BaseParser


# ── Column name candidates (case-insensitive) ──────────────────────────────
_DATE_COLS   = ["date", "transaction date", "txn date", "posting date", "value date",
                "created at", "created", "time"]
_DESC_COLS   = ["description", "merchant", "merchant name", "narration", "note",
                "notes", "particulars", "details", "name", "payee", "title"]
_AMOUNT_COLS = ["amount", "transaction amount", "amount (inr)", "inr", "value",
                "net amount", "total"]
_TYPE_COLS   = ["type", "transaction type", "txn type", "dr/cr", "debit/credit",
                "direction"]
_DEBIT_COLS  = ["debit", "expense", "dr", "withdrawal", "paid"]
_CREDIT_COLS = ["credit", "income", "cr", "deposit", "received"]
_CAT_COLS    = ["category", "cat", "expense category", "category name"]
_SUBCAT_COLS = ["sub-category", "subcategory", "sub category", "sub cat"]
_TAG_COLS    = ["tags", "tag", "label", "labels"]
_ACCT_COLS   = ["account", "bank", "source", "wallet", "payment method"]

_DATE_FMTS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%m/%d/%Y",
    "%d/%m/%y",
    "%Y/%m/%d",
    "%b %d, %Y",
    "%d-%b-%Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
]


def _find_col(df: pd.DataFrame, candidates: list) -> Optional[str]:
    norm = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in norm:
            return norm[cand.lower()]
    return None


def _parse_date(raw) -> Optional[date]:
    if isinstance(raw, (pd.Timestamp, datetime)):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if pd.isna(raw):
        return None
    s = str(raw).strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(s[:19], fmt).date()
        except ValueError:
            continue
    return None


class AXIOParser(BaseParser):
    """
    Parses AXIO personal finance app exports (CSV / XLSX).

    All transactions from AXIO are marked audit_status="Audited" because
    AXIO is Pankaj's manual ground-truth ledger.
    """

    bank_name = "AXIO"

    def parse(self, file_like, filename: str) -> List[TransactionDTO]:
        fname = filename.lower()
        try:
            if fname.endswith(".csv"):
                df = pd.read_csv(file_like, dtype=str)
            else:
                df = pd.read_excel(file_like, dtype=str)
        except Exception as e:
            raise ValueError(f"Could not read AXIO file '{filename}': {e}")

        if df.empty:
            return []

        # Detect columns
        date_col   = _find_col(df, _DATE_COLS)
        desc_col   = _find_col(df, _DESC_COLS)
        amount_col = _find_col(df, _AMOUNT_COLS)
        type_col   = _find_col(df, _TYPE_COLS)
        debit_col  = _find_col(df, _DEBIT_COLS)
        credit_col = _find_col(df, _CREDIT_COLS)
        cat_col    = _find_col(df, _CAT_COLS)
        subcat_col = _find_col(df, _SUBCAT_COLS)
        tag_col    = _find_col(df, _TAG_COLS)

        if date_col is None:
            raise ValueError(
                "Cannot find a date column in AXIO file. "
                f"Columns present: {list(df.columns)}"
            )

        dtos = []
        for _, row in df.iterrows():
            dto = self._convert_row(
                row, filename,
                date_col, desc_col, amount_col, type_col,
                debit_col, credit_col, cat_col, subcat_col, tag_col,
            )
            if dto:
                dtos.append(dto)
        return dtos

    def _convert_row(
        self, row: pd.Series, filename: str,
        date_col, desc_col, amount_col, type_col,
        debit_col, credit_col, cat_col, subcat_col, tag_col,
    ) -> Optional[TransactionDTO]:

        # ── Date ──────────────────────────────────────────────────────────
        txn_date = _parse_date(row.get(date_col) if date_col else None)
        if txn_date is None:
            return None

        # ── Description ───────────────────────────────────────────────────
        desc = self._safe_str(row.get(desc_col, "") if desc_col else "")

        # ── Amount & type ─────────────────────────────────────────────────
        txn_type: Optional[str] = None
        amount   = 0.0

        if debit_col and credit_col:
            d = self._safe_float(row.get(debit_col, 0))
            c = self._safe_float(row.get(credit_col, 0))
            if d > 0:
                txn_type, amount = "DEBIT", d
            elif c > 0:
                txn_type, amount = "CREDIT", c

        if txn_type is None and amount_col:
            raw_amt = self._safe_float(row.get(amount_col, 0))
            amount  = abs(raw_amt)

            if type_col:
                t = str(row.get(type_col, "")).upper().strip()
                if any(x in t for x in ["DR", "DEBIT", "EXPENSE", "PAID", "W"]):
                    txn_type = "DEBIT"
                elif any(x in t for x in ["CR", "CREDIT", "INCOME", "RECEIVED", "D"]):
                    txn_type = "CREDIT"

            if txn_type is None:
                # Infer from sign of raw amount
                txn_type = "CREDIT" if raw_amt > 0 else "DEBIT"

        if amount == 0 or txn_type is None:
            return None

        # ── Category / tags ───────────────────────────────────────────────
        category    = self._safe_str(row.get(cat_col,    "") if cat_col    else "") or None
        sub_category = self._safe_str(row.get(subcat_col, "") if subcat_col else "") or None
        tags        = self._safe_str(row.get(tag_col,    "") if tag_col    else "") or None

        return TransactionDTO(
            id=uuid.uuid4(),
            date=txn_date,
            amount=amount,
            bank_description=desc,
            details=desc,
            txn_type=txn_type,
            bank_name=self.bank_name,
            payment_method="AXIO",
            category=category,
            sub_category=sub_category,
            tags=tags,
            # AXIO imports are the user's own audit records — always Audited
            audit_status="Audited",
            system_comment="Imported from AXIO (user's audit ledger)",
            source_file=filename,
        )
