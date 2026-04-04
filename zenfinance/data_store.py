"""
ZenFinance — CSV Data Store with automatic timestamped backups.
Every write triggers a backup copy to /backups/.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

from zenfinance.models import TRANSACTION_COLUMNS, TransactionDTO

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
_BASE_DIR  = Path(__file__).resolve().parent.parent   # ZenFinance/
DATA_DIR   = _BASE_DIR / "data"
BACKUP_DIR = _BASE_DIR / "backups"
DB_PATH    = DATA_DIR / "transactions.csv"

DATA_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)


# ──────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────
def _backup(reason: str = "change") -> None:
    """Copy the master CSV to backups/ with a timestamp."""
    if not DB_PATH.exists():
        return
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"transactions_{ts}_{reason}.csv"
    shutil.copy2(DB_PATH, dest)


def _empty_df() -> pd.DataFrame:
    df = pd.DataFrame(columns=TRANSACTION_COLUMNS)
    return df


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in TRANSACTION_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[TRANSACTION_COLUMNS]


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────
def load_all() -> pd.DataFrame:
    """Load the master transactions CSV. Returns empty DataFrame if absent."""
    if not DB_PATH.exists():
        return _empty_df()
    df = pd.read_csv(DB_PATH, dtype=str)
    df = _ensure_columns(df)
    # Restore numeric types
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["date"]   = pd.to_datetime(df["date"], errors="coerce").dt.date
    return df


def save_all(df: pd.DataFrame, reason: str = "save") -> None:
    """Overwrite the master CSV and create a backup."""
    _backup(reason)
    df = _ensure_columns(df)
    df.to_csv(DB_PATH, index=False)


def append_transactions(
    new_dtos: List[TransactionDTO],
    source_file: Optional[str] = None,
) -> dict:
    """
    Merge new transactions into the master store using hash-based deduplication.
    Returns a summary dict: {added, skipped_duplicates, total}.
    """
    existing = load_all()
    existing_hashes = set(existing["hash"].dropna().tolist())

    added_rows  = []
    duplicates  = 0

    for dto in new_dtos:
        if dto.hash in existing_hashes:
            duplicates += 1
        else:
            row = dto.to_dict()
            if source_file and not row.get("source_file"):
                row["source_file"] = source_file
            added_rows.append(row)
            existing_hashes.add(dto.hash)

    if added_rows:
        new_df  = pd.DataFrame(added_rows)
        new_df  = _ensure_columns(new_df)
        merged  = pd.concat([existing, new_df], ignore_index=True)
        save_all(merged, reason="import")

    return {
        "added":              len(added_rows),
        "skipped_duplicates": duplicates,
        "total":              len(existing) + len(added_rows),
    }


def update_row(row_id: str, updates: dict) -> bool:
    """Update a single transaction row by its UUID string and save."""
    df = load_all()
    mask = df["id"] == row_id
    if not mask.any():
        return False
    for col, val in updates.items():
        if col in df.columns:
            df.loc[mask, col] = val
    save_all(df, reason="edit")
    return True


def delete_row(row_id: str) -> bool:
    """Remove a transaction by UUID."""
    df = load_all()
    before = len(df)
    df = df[df["id"] != row_id]
    if len(df) < before:
        save_all(df, reason="delete")
        return True
    return False


def get_backup_list() -> list[str]:
    """Return sorted list of backup filenames (newest first)."""
    files = sorted(BACKUP_DIR.glob("*.csv"), reverse=True)
    return [f.name for f in files]


def restore_backup(filename: str) -> bool:
    """Restore a named backup over the master CSV."""
    src = BACKUP_DIR / filename
    if not src.exists():
        return False
    _backup("pre_restore")
    shutil.copy2(src, DB_PATH)
    return True
