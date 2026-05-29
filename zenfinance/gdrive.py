"""
ZenFinance — Google Drive Integration Module
Handles downloading/uploading CSVs and backups from/to Google Drive using a Service Account.
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# Config
try:
    FOLDER_ID = st.secrets.get("gdrive_folder_id", "17DC3eOMWSWshibk5SbXq33tsnSY7c9HL")
except Exception:
    FOLDER_ID = "17DC3eOMWSWshibk5SbXq33tsnSY7c9HL"

@st.cache_resource
def get_drive_service():
    """Authenticate and return Google Drive API service client."""
    # 1. Try streamlit secrets (for cloud deployment)
    try:
        if "gcp_service_account" in st.secrets:
            creds_info = dict(st.secrets["gcp_service_account"])
            # Format private key properly since secrets might convert newlines
            if "private_key" in creds_info:
                creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
            creds = service_account.Credentials.from_service_account_info(
                creds_info,
                scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
    except Exception as e:
        # Ignore secrets-not-found errors; report formatting errors if gcp_service_account was present
        if "gcp_service_account" in globals() or "gcp_service_account" in locals():
            st.error(f"Error loading service account from secrets: {e}")

    # 2. Try local credentials file (for development)
    local_creds_path = Path(__file__).resolve().parent.parent / "gcp_credentials.json"
    if local_creds_path.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(local_creds_path),
                scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            st.error(f"Error loading local credentials file: {e}")

    st.error("Google Cloud credentials not found! Please check st.secrets or local gcp_credentials.json.")
    return None


def get_or_create_subfolder(folder_name: str, parent_id: str = FOLDER_ID) -> str:
    """Find a subfolder inside a parent folder, or create it if not exists."""
    service = get_drive_service()
    if not service:
        return ""

    query = f"name = '{folder_name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]

    # Create it
    file_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id]
    }
    folder = service.files().create(body=file_metadata, fields="id").execute()
    return folder.get("id")


def find_file(filename: str, parent_id: str = FOLDER_ID) -> Optional[str]:
    """Find a file inside a parent folder, return its file ID or None."""
    service = get_drive_service()
    if not service:
        return None

    query = f"name = '{filename}' and '{parent_id}' in parents and trashed = false"
    results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    return None


def download_file_content(file_id: str) -> bytes:
    """Download a file's binary content by file ID."""
    service = get_drive_service()
    if not service:
        return b""

    request = service.files().get_media(fileId=file_id)
    file_io = io.BytesIO()
    downloader = MediaIoBaseDownload(file_io, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return file_io.getvalue()


def upload_or_update_file(
    filename: str,
    content_bytes: bytes,
    parent_id: str = FOLDER_ID,
    mime_type: str = "text/csv"
) -> str:
    """Upload new file to Google Drive or update existing file content if it already exists."""
    service = get_drive_service()
    if not service:
        return ""

    existing_id = find_file(filename, parent_id)
    media = MediaIoBaseUpload(io.BytesIO(content_bytes), mimetype=mime_type, resumable=True)

    if existing_id:
        # Update existing
        file = service.files().update(
            fileId=existing_id,
            media_body=media
        ).execute()
        return file.get("id")
    else:
        # Upload new
        file_metadata = {
            "name": filename,
            "parents": [parent_id]
        }
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id"
        ).execute()
        return file.get("id")


def get_backups_folder_id() -> str:
    """Get or create the backups/ folder inside the main folder."""
    return get_or_create_subfolder("backups", FOLDER_ID)


# ──────────────────────────────────────────────
# Zip Operations
# ──────────────────────────────────────────────

def generate_data_zip() -> bytes:
    """
    Fetch the master transactions.csv and all backups from Google Drive,
    and compress them into a structured ZIP file in-memory.
    Returns ZIP bytes.
    """
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        # 1. Download master transactions.csv
        master_id = find_file("transactions.csv", FOLDER_ID)
        if master_id:
            master_data = download_file_content(master_id)
            zip_file.writestr("transactions.csv", master_data)
        
        # 2. Download backups
        backup_folder = get_backups_folder_id()
        service = get_drive_service()
        if service and backup_folder:
            query = f"'{backup_folder}' in parents and trashed = false"
            results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
            files = results.get("files", [])
            for file in files:
                file_data = download_file_content(file["id"])
                zip_file.writestr(f"backups/{file['name']}", file_data)
                
    return zip_buffer.getvalue()


def restore_data_from_zip(zip_bytes: bytes) -> bool:
    """
    Extract a structured ZIP in-memory and write the CSV files back to Google Drive,
    completely updating transactions.csv and the backups/ folder.
    """
    zip_buffer = io.BytesIO(zip_bytes)
    
    try:
        with zipfile.ZipFile(zip_buffer, "r") as zip_file:
            # Verify basic structure
            file_list = zip_file.namelist()
            if "transactions.csv" not in file_list:
                st.error("Invalid ZIP: transactions.csv not found in the root.")
                return False
            
            # 1. Extract and upload master transactions.csv
            master_data = zip_file.read("transactions.csv")
            upload_or_update_file("transactions.csv", master_data, FOLDER_ID, "text/csv")
            
            # 2. Extract and upload backups
            backup_folder = get_backups_folder_id()
            for filename in file_list:
                if filename.startswith("backups/") and filename.endswith(".csv"):
                    base_name = os.path.basename(filename)
                    if base_name:
                        file_data = zip_file.read(filename)
                        upload_or_update_file(base_name, file_data, backup_folder, "text/csv")
            return True
    except Exception as e:
        st.error(f"Failed to restore from ZIP: {e}")
        return False
