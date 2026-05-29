"""
ZenFinance — AXIO App Parser
AXIO is the user's personal finance / expense-tracking app where they
manually update transaction details and tags.  Importing an AXIO export
acts as the **ground truth** for audit reconciliation.

Real AXIO CSV / XLSX format (discovered from actual export):
─────────────────────────────────────────────────────────────
  Row 0  : metadata header ("axio", "EXPENSE", "REPORT", …)
  Row 1  : Name
  Row 2  : Phone Number
  Row 3  : Email
  Row 4  : FROM … TO date range
  Row 5  : blank
  Row 6  : actual column headers ← auto-detected
  Row 7+ : transaction data

Actual columns:
  DATE | TIME | PLACE | AMOUNT | DR/CR | ACCOUNT | EXPENSE | INCOME | CATEGORY | TAGS | NOTE

Key rule: every transaction imported from AXIO gets audit_status = "Audited"
because AXIO IS the audit source (user's manually curated ledger).
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


# ── Known AXIO header tokens (used to auto-locate the real header row) ──────
_AXIO_HEADER_TOKENS = {"date", "amount", "dr/cr", "place", "category", "account"}

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
]


def _find_header_row(raw_bytes: bytes, encoding: str = "utf-8") -> int:
    """
    Scan lines of a CSV looking for the real header row.
    Returns the 0-based row index whose cells contain the most AXIO header tokens.
    Stops searching after row 30 (metadata block is always short).
    """
    try:
        text = raw_bytes.decode(encoding, errors="replace")
    except Exception:
        return 0

    lines = text.splitlines()
    best_row, best_score = 0, 0

    for i, line in enumerate(lines[:30]):
        # Strip quotes, split on comma
        cells = [c.strip().strip('"').strip("'").lower() for c in line.split(",")]
        score = sum(1 for t in _AXIO_HEADER_TOKENS if any(t in c for c in cells))
        if score > best_score:
            best_score = score
            best_row   = i
        if best_score >= 3:   # confident enough
            break

    return best_row


def _parse_date(raw) -> Optional[date]:
    if isinstance(raw, (pd.Timestamp, datetime)):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if pd.isna(raw) if not isinstance(raw, str) else not raw.strip():
        return None
    s = str(raw).strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(s[:19], fmt).date()
        except ValueError:
            continue
    return None


def _safe_amount(val) -> float:
    """Strip commas, currency symbols, quotes; return float."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    s = re.sub(r"[₹,'\"\s]", "", str(val).strip())
    try:
        return abs(float(s))
    except ValueError:
        return 0.0


def _read_axio_df(file_like, filename: str) -> pd.DataFrame:
    """
    Read the AXIO file, auto-skipping metadata rows at the top.
    Tries CSV then XLSX, and within CSV tries multiple encodings.
    Returns a DataFrame with the real headers as column names.
    """
    fname = filename.lower()

    # ── Excel path ──────────────────────────────────────────────────────────
    if fname.endswith((".xlsx", ".xls")):
        # Try different skiprows (0–10) until we find the DATE column
        raw_bytes = file_like.read() if hasattr(file_like, "read") else file_like
        for skip in range(0, 15):
            try:
                df = pd.read_excel(io.BytesIO(raw_bytes), skiprows=skip, dtype=str)
                cols_lower = [str(c).lower().strip() for c in df.columns]
                if "date" in cols_lower and "amount" in cols_lower:
                    return df
            except Exception:
                continue
        # Last resort: no skip
        return pd.read_excel(io.BytesIO(raw_bytes), dtype=str)

    # ── CSV path ─────────────────────────────────────────────────────────────
    raw_bytes = file_like.read() if hasattr(file_like, "read") else file_like

    # Try each encoding
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            header_row = _find_header_row(raw_bytes, enc)
            df = pd.read_csv(
                io.BytesIO(raw_bytes),
                skiprows=header_row,
                dtype=str,
                encoding=enc,
            )
            cols_lower = [str(c).lower().strip() for c in df.columns]
            if "date" in cols_lower:
                return df
        except Exception:
            continue

    raise ValueError(
        f"Could not read AXIO file '{filename}' — no recognisable date column found."
    )


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace / quotes from column names, lowercase for matching."""
    df = df.copy()
    df.columns = [
        str(c).strip().strip('"').strip("'").upper()
        for c in df.columns
    ]
    return df


class AXIOParser(BaseParser):
    """
    Parses AXIO personal finance app exports (CSV / XLSX).

    All transactions from AXIO are marked audit_status="Audited" because
    AXIO is Pankaj's manually curated ground-truth ledger.
    """

    bank_name = "AXIO"

    def parse(self, file_like, filename: str) -> List[TransactionDTO]:
        df = _read_axio_df(file_like, filename)
        df = _normalise_columns(df)

        # Map AXIO column names to our canonical names
        # The actual AXIO columns are: DATE TIME PLACE AMOUNT DR/CR ACCOUNT
        #                               EXPENSE INCOME CATEGORY TAGS NOTE
        col_date     = self._find(df, ["DATE"])
        col_place    = self._find(df, ["PLACE", "DESCRIPTION", "MERCHANT", "NOTE", "NARRATION"])
        col_amount   = self._find(df, ["AMOUNT", "TRANSACTION AMOUNT", "AMOUNT (INR)"])
        col_drcr     = self._find(df, ["DR/CR", "TYPE", "TRANSACTION TYPE", "TXN TYPE", "DR_CR"])
        col_category = self._find(df, ["CATEGORY", "CAT", "EXPENSE CATEGORY"])
        col_tags     = self._find(df, ["TAGS", "TAG", "LABEL"])
        col_note     = self._find(df, ["NOTE", "NOTES", "REMARKS", "NARRATION"])
        col_account  = self._find(df, ["ACCOUNT", "BANK", "SOURCE", "WALLET"])

        if col_date is None:
            raise ValueError(
                f"Cannot find a DATE column in AXIO file '{filename}'. "
                f"Columns found: {list(df.columns)}"
            )

        dtos = []
        for _, row in df.iterrows():
            dto = self._convert_row(
                row, filename,
                col_date, col_place, col_amount, col_drcr,
                col_category, col_tags, col_note, col_account,
            )
            if dto:
                dtos.append(dto)
        return dtos

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _find(df: pd.DataFrame, candidates: list) -> Optional[str]:
        for cand in candidates:
            if cand in df.columns:
                return cand
        # Partial match fallback
        for cand in candidates:
            for col in df.columns:
                if cand in col:
                    return col
        return None

    def _convert_row(
        self, row: pd.Series, filename: str,
        col_date, col_place, col_amount, col_drcr,
        col_category, col_tags, col_note, col_account,
    ) -> Optional[TransactionDTO]:

        # ── Date ──────────────────────────────────────────────────────────
        txn_date = _parse_date(row.get(col_date) if col_date else None)
        if txn_date is None:
            return None

        # ── Amount ────────────────────────────────────────────────────────
        amount = _safe_amount(row.get(col_amount) if col_amount else None)
        if amount == 0:
            return None

        # ── Transaction type: DR → DEBIT, CR → CREDIT ─────────────────────
        drcr_raw = str(row.get(col_drcr, "")).strip().upper() if col_drcr else ""
        if "CR" in drcr_raw and "DR" not in drcr_raw:
            txn_type = "CREDIT"
        else:
            txn_type = "DEBIT"   # default; DR or anything else

        # ── Description / merchant ─────────────────────────────────────────
        place = self._safe_str(row.get(col_place, "") if col_place else "")
        note  = self._safe_str(row.get(col_note, "")  if col_note  else "")
        desc  = place or note or "(AXIO entry)"

        # ── Category & tags ────────────────────────────────────────────────
        category = self._safe_str(row.get(col_category, "") if col_category else "") or None
        tags     = self._safe_str(row.get(col_tags,    "") if col_tags    else "") or None
        account  = self._safe_str(row.get(col_account, "") if col_account else "") or None

        # Build a system_comment with the account so we can cross-reference later
        comment = f"AXIO account: {account}" if account else "Imported from AXIO"

        return TransactionDTO(
            id=uuid.uuid4(),
            date=txn_date,
            amount=amount,
            bank_description=desc,
            details=note or place,
            txn_type=txn_type,
            bank_name=self.bank_name,
            payment_method="AXIO",
            category=category,
            sub_category=None,
            tags=tags,
            # AXIO is the audit ground truth — always mark Audited
            audit_status="Audited",
            system_comment=comment,
            source_file=filename,
        )
