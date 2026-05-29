"""
ZenFinance — SBI Bank Parser (Excel + CSV)

Supports all SBI statement export formats:
  • .xlsx / .xls  — standard SBI statement (data starts at row 21, skiprows=20)
  • .csv          — SBI CSV export (auto-detects header row)

Real column structure (same for both formats once header is located):
  Txn Date | Value Date | Description | Ref No./Cheque No. | Debit | Credit | Balance

CSV header detection: scans the first 30 rows for a line that contains
'Txn Date' or both 'Debit' + 'Credit' — handles any number of metadata
rows SBI may prepend to the file.
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


# ── SBI column header tokens used for auto-detection ──────────────────────
# Tokens for both XLSX headers ("Txn Date", "Description") and CSV headers ("Date", "Details")
_SBI_HEADER_TOKENS = {"txn date", "date", "debit", "credit", "description", "details", "balance"}


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


def _find_csv_header_row(raw_bytes: bytes) -> int:
    """
    Scan the first 30 lines of a CSV for the SBI column header row.
    Returns the 0-based line index of the best match.
    """
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            text = raw_bytes.decode(enc, errors="replace")
            break
        except Exception:
            continue
    else:
        return 0

    lines = text.splitlines()
    best_row, best_score = 0, 0

    for i, line in enumerate(lines[:30]):
        cells = {c.strip().strip('"').lower() for c in line.split(",")}
        score = sum(1 for t in _SBI_HEADER_TOKENS if t in cells)
        if score > best_score:
            best_score = score
            best_row   = i
        if best_score >= 3:
            break

    return best_row


def _read_sbi_csv(raw_bytes: bytes, filename: str) -> pd.DataFrame:
    """
    Read a SBI CSV, auto-detecting the header row.

    SBI CSVs have multi-line quoted description fields, so we cannot rely
    on physical-line counting (skiprows) since one CSV row can span several
    physical lines.  Instead we read everything as raw rows (header=None),
    locate the header row by column-name detection, then slice the DataFrame.
    """
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(
                io.BytesIO(raw_bytes),
                header=None,           # read ALL rows as data
                encoding=enc,
                dtype=str,
                on_bad_lines="skip",
            )
            break
        except Exception:
            continue
    else:
        raise ValueError(f"Could not parse SBI CSV file '{filename}'.")

    # Locate the header row: find the first row whose cells contain
    # enough SBI column-name tokens ("date", "debit", "credit" etc.)
    header_idx = None
    for idx, row in df.iterrows():
        cells_lower = {str(v).strip().lower() for v in row.values if pd.notna(v)}
        score = sum(1 for t in _SBI_HEADER_TOKENS if t in cells_lower)
        if score >= 3:
            header_idx = idx
            break

    if header_idx is None:
        raise ValueError(f"Could not find SBI column headers in '{filename}'.")

    # Use that row as column names, keep only data below it
    new_cols = [str(v).strip() for v in df.iloc[header_idx].values]
    df = df.iloc[header_idx + 1:].reset_index(drop=True)
    df.columns = new_cols

    return df


def _read_sbi_excel(file_like, filename: str) -> pd.DataFrame:
    """
    Read a SBI Excel file. Tries skiprows=20 first (standard SBI XLSX layout),
    then falls back to scanning rows 0–25.
    Uses native pandas types (no dtype=str) so Timestamps stay as Timestamps.
    """
    raw = file_like.read() if hasattr(file_like, "read") else file_like

    for skip in [20, 0, 5, 10, 15, 25]:
        try:
            df = pd.read_excel(io.BytesIO(raw), skiprows=skip)
            df.columns = [str(c).strip() for c in df.columns]
            cols_lower = [c.lower() for c in df.columns]
            if "txn date" in cols_lower or ("debit" in cols_lower and "credit" in cols_lower):
                return df
        except Exception:
            continue
    raise ValueError(f"Could not parse SBI Excel file '{filename}'.")


class SBIParser(BaseParser):
    bank_name = "SBI"

    def parse(self, file_like, filename: str) -> List[TransactionDTO]:
        fname = filename.lower().strip()
        raw   = file_like.read() if hasattr(file_like, "read") else file_like

        if fname.endswith(".csv"):
            df = _read_sbi_csv(raw, filename)
        else:
            df = _read_sbi_excel(io.BytesIO(raw), filename)

        dtos = []
        for _, row in df.iterrows():
            dto = self._convert_row(row, filename)
            if dto:
                dtos.append(dto)
        return dtos

    def _convert_row(self, row: pd.Series, filename: str) -> Optional[TransactionDTO]:
        # SBI XLSX uses "Txn Date / Description / Ref No./Cheque No."
        # SBI CSV  uses "Date / Details / Ref No/Cheque No" (no dots)
        # Handle both sets of column names transparently.
        txn_date      = row.get("Txn Date") or row.get("Date")
        description   = self._safe_str(
            row.get("Description") or row.get("Details") or ""
        )
        ref_no        = (
            row.get("Ref No./Cheque No.") or
            row.get("Ref No/Cheque No") or
            row.get("Ref No") or None
        )
        debit_amount  = row.get("Debit")
        credit_amount = row.get("Credit")

        txn_type = None
        amount   = 0.0
        if self._safe_float(debit_amount) > 0:
            txn_type = "DEBIT"
            amount   = self._safe_float(debit_amount)
        elif self._safe_float(credit_amount) > 0:
            txn_type = "CREDIT"
            amount   = self._safe_float(credit_amount)

        if txn_type is None:
            return None

        transaction_date = None
        if isinstance(txn_date, (pd.Timestamp, datetime)):
            transaction_date = txn_date.date()
        elif isinstance(txn_date, date):
            transaction_date = txn_date
        elif isinstance(txn_date, str):
            txn_date = txn_date.strip()
            for fmt in ("%d %b %Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d",
                        "%d/%m/%y", "%d %B %Y"):
                try:
                    transaction_date = datetime.strptime(txn_date, fmt).date()
                    break
                except ValueError:
                    continue

        if transaction_date is None:
            return None

        parsed = _parse_sbi_description(description)

        ref = self._safe_str(ref_no) if ref_no and str(ref_no).strip() not in ("", "nan") else None

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
            reference_number=ref,
            audit_status="Pending",
            source_file=filename,
        )
