"""
ZenFinance — Google Drive Data Store.
Saves/Loads transactions to Google Drive folder using service account credentials.
Caches data in st.session_state to avoid excessive network requests.
"""
from __future__ import annotations

import io
from pathlib import Path
import streamlit as st
import pandas as pd
from datetime import datetime
from typing import List, Optional

from zenfinance.models import TRANSACTION_COLUMNS, TransactionDTO
from zenfinance import gdrive

# ──────────────────────────────────────────────
# Caching helpers
# ──────────────────────────────────────────────
def clear_cache() -> None:
    """Clear cached transactions DataFrame from Streamlit session state."""
    if "transactions_df" in st.session_state:
        del st.session_state["transactions_df"]


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
    """Load transactions. Checks session state cache first, falls back to Google Drive."""
    # 1. Return session cache if present
    if "transactions_df" in st.session_state:
        return st.session_state["transactions_df"]

    # 2. Fetch from Google Drive
    master_id = gdrive.find_file("transactions.csv")
    if not master_id:
        # One-time migration fallback: check local transactions.csv
        local_path = Path(__file__).resolve().parent.parent / "data" / "transactions.csv"
        if local_path.exists():
            try:
                df = pd.read_csv(local_path, dtype=str)
                df = _ensure_columns(df)
                df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
                df["date"]   = pd.to_datetime(df["date"], errors="coerce").dt.date
                
                # Upload to Google Drive so it's in the cloud
                save_all(df, reason="initial_migration")
                st.info("ℹ️ Successfully migrated local transactions.csv to Google Drive!")
            except Exception as e:
                st.error(f"Error during migration of local transactions.csv: {e}")
                df = _empty_df()
        else:
            df = _empty_df()
    else:
        try:
            content_bytes = gdrive.download_file_content(master_id)
            if content_bytes:
                # Use io.BytesIO to read into pandas
                df = pd.read_csv(io.BytesIO(content_bytes), dtype=str)
                df = _ensure_columns(df)
                df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
                df["date"]   = pd.to_datetime(df["date"], errors="coerce").dt.date
            else:
                df = _empty_df()
        except Exception as e:
            st.error(f"Error loading data from Google Drive: {e}")
            df = _empty_df()

    st.session_state["transactions_df"] = df
    return df



def save_all(df: pd.DataFrame, reason: str = "save") -> None:
    """Save transactions to Google Drive and update session state cache."""
    df = _ensure_columns(df)
    
    # 1. Update session state cache immediately
    st.session_state["transactions_df"] = df

    # Convert to CSV bytes
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_bytes = csv_buffer.getvalue().encode("utf-8")

    try:
        # 2. Save master file to Google Drive
        gdrive.upload_or_update_file("transactions.csv", csv_bytes)

        # 3. Create Google Drive backup
        backup_folder = gdrive.get_backups_folder_id()
        if backup_folder:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"transactions_{ts}_{reason}.csv"
            gdrive.upload_or_update_file(backup_filename, csv_bytes, backup_folder)
    except Exception as e:
        st.error(f"Failed to save data to Google Drive: {e}")


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
    """Return sorted list of backup filenames from Google Drive (newest first)."""
    service = gdrive.get_drive_service()
    backup_folder = gdrive.get_backups_folder_id()
    if not service or not backup_folder:
        return []

    try:
        query = f"'{backup_folder}' in parents and name contains 'transactions_' and trashed = false"
        results = service.files().list(q=query, spaces="drive", fields="files(name)").execute()
        files = results.get("files", [])
        return sorted([f["name"] for f in files], reverse=True)
    except Exception as e:
        st.error(f"Error fetching backups list: {e}")
        return []


def restore_backup(filename: str) -> bool:
    """Restore a named backup from Google Drive over the master CSV."""
    service = gdrive.get_drive_service()
    backup_folder = gdrive.get_backups_folder_id()
    if not service or not backup_folder:
        return False

    try:
        backup_id = gdrive.find_file(filename, backup_folder)
        if not backup_id:
            return False
            
        backup_bytes = gdrive.download_file_content(backup_id)
        if not backup_bytes:
            return False
            
        # Parse backup content
        df = pd.read_csv(io.BytesIO(backup_bytes), dtype=str)
        df = _ensure_columns(df)
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
        df["date"]   = pd.to_datetime(df["date"], errors="coerce").dt.date
        
        # Save as master and clear/update cache
        save_all(df, reason="restore")
        return True
    except Exception as e:
        st.error(f"Error restoring backup: {e}")
        return False

