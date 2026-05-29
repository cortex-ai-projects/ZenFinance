"""
ZenFinance — Settings & Management UI

Navigation note: this page uses st.tabs() for internal navigation.
No st.rerun() calls are used for nav — Streamlit button clicks already
trigger automatic reruns. Data-operation st.rerun() calls were removed
to prevent sidebar collapse.
"""
from __future__ import annotations

import io
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

from zenfinance import gdrive
from zenfinance.categorization import CATEGORY_RULES, get_all_categories
from zenfinance.data_store import (
    get_backup_list,
    load_all,
    restore_backup,
    save_all,
)
from zenfinance.parsers.registry import (
    BANK_SOURCES,
    INTERMEDIATOR_SOURCES,
    TERMINAL_SOURCES,
    AUDIT_SOURCES,
)

GREEN  = "#43D9AD"
RED    = "#FF6584"
YELLOW = "#FFB347"
PURPLE = "#6C63FF"
BLUE   = "#4CC9F0"


def render():
    st.markdown("## ⚙️ Settings & Management")

    # Quick-jump anchors rendered as an info bar
    st.markdown(
        '<div style="background:#1A1D2E;border:1px solid #2A2D3E;border-radius:10px;'
        'padding:10px 16px;font-size:0.82rem;color:#8888AA;margin-bottom:12px">'
        'Tabs: &nbsp;'
        '<b style="color:#6C63FF">💾 Backups</b> &nbsp;·&nbsp; '
        '<b style="color:#6C63FF">🏷️ Categories</b> &nbsp;·&nbsp; '
        '<b style="color:#6C63FF">🔍 Audit Sources</b> &nbsp;·&nbsp; '
        '<b style="color:#6C63FF">🗄️ Data</b> &nbsp;·&nbsp; '
        '<b style="color:#6C63FF">🔒 Security & Cloud</b> &nbsp;·&nbsp; '
        '<b style="color:#6C63FF">ℹ️ About</b>'
        '</div>',
        unsafe_allow_html=True,
    )

    tab_backup, tab_cats, tab_audit_cfg, tab_data, tab_security, tab_about = st.tabs(
        ["💾 Backups", "🏷️ Categories", "🔍 Audit Sources", "🗄️ Data Management", "🔒 Security & Cloud", "ℹ️ About"]
    )

    # ══════════════════════════════════════════════════════════════════
    # TAB 1 — Backups
    # ══════════════════════════════════════════════════════════════════
    with tab_backup:
        st.markdown("### Automatic Backup History")
        st.caption(
            "Every import and edit triggers an automatic timestamped backup. "
            "Backups are stored securely in your Google Drive `backups/` subfolder."
        )

        backups = get_backup_list()
        if not backups:
            st.info("No backups yet — they are created automatically on every import or edit.")
        else:
            st.markdown(f"**{len(backups)} backup(s) available** · newest first")
            selected_backup = st.selectbox("Select backup to restore", backups)
            b1, b2 = st.columns(2)

            # Restore — use a flag in session state so UI refreshes without
            # sidebar-collapsing st.rerun()
            if b1.button("🔄 Restore Selected Backup", type="primary", key="btn_restore"):
                if restore_backup(selected_backup):
                    st.success(f"✅ Restored from `{selected_backup}`. Refresh the page to see updated data.")
                else:
                    st.error("Restore failed — file not found in Google Drive.")

            # Download from Google Drive
            try:
                backup_folder = gdrive.get_backups_folder_id()
                backup_id = gdrive.find_file(selected_backup, backup_folder)
                if backup_id:
                    backup_bytes = gdrive.download_file_content(backup_id)
                    b2.download_button(
                        "⬇️ Download Backup",
                        data=backup_bytes,
                        file_name=selected_backup,
                        mime="text/csv",
                    )
                else:
                    b2.error("Backup file not found in Google Drive.")
            except Exception as e:
                b2.error(f"Error fetching backup: {e}")

            with st.expander("📋 All backup files"):
                for b in backups:
                    st.code(b, language=None)

    # ══════════════════════════════════════════════════════════════════
    # TAB 2 — Categories
    # ══════════════════════════════════════════════════════════════════
    with tab_cats:
        st.markdown("### Categorisation Rules")
        st.caption(
            "These regex patterns are applied to transaction descriptions to auto-assign categories. "
            "Rules are checked in order — first match wins."
        )

        rules_rows = []
        for cat, sub, patterns in CATEGORY_RULES:
            rules_rows.append({
                "Category":     cat,
                "Sub-Category": sub,
                "Patterns":     ", ".join(patterns[:4]) + ("…" if len(patterns) > 4 else ""),
            })
        rules_df = pd.DataFrame(rules_rows)
        st.dataframe(rules_df, width="stretch", hide_index=True, height=450)

        st.markdown("---")
        st.markdown("#### 🔁 Re-Categorisation Runner & Previewer")
        st.caption(
            "Detect proposed changes to categories based on current rules. "
            "You can review a preview of affected transactions before committing them to the database."
        )

        only_uncategorized = st.checkbox(
            "Only re-categorise Uncategorised transactions (keep manually edited/categorised rows)",
            value=False,
            key="only_uncategorized_chk"
        )

        if "cat_preview_df" not in st.session_state:
            st.session_state.cat_preview_df = None
        if "cat_preview_changes" not in st.session_state:
            st.session_state.cat_preview_changes = None

        col_run, col_clear = st.columns([2, 1])

        if col_run.button("🔍 Run Dry-Run Analysis & Preview", type="primary", key="btn_dry_run"):
            from zenfinance.categorization import categorize
            df = load_all()
            if df.empty:
                st.warning("No transactions in database.")
            else:
                changes = []
                for idx, row in df.iterrows():
                    curr_cat = str(row.get("category", "")).strip()
                    curr_sub = str(row.get("sub_category", "")).strip()
                    if curr_cat in ["nan", "None"]:
                        curr_cat = ""
                    if curr_sub in ["nan", "None"]:
                        curr_sub = ""

                    # If only_uncategorized is True, only process Uncategorized/empty rows
                    if only_uncategorized and curr_cat not in ["Uncategorized", "General", ""]:
                        continue

                    new_cat, new_sub = categorize(str(row.get("bank_description", "")), str(row.get("details", "")))
                    if curr_cat != new_cat or curr_sub != new_sub:
                        changes.append({
                            "id": row["id"],
                            "date": row["date"],
                            "bank_name": row["bank_name"],
                            "bank_description": row["bank_description"],
                            "amount": row["amount"],
                            "Current Category": curr_cat if curr_cat else "Uncategorized",
                            "Current Sub-Category": curr_sub if curr_sub else "General",
                            "Proposed Category": new_cat,
                            "Proposed Sub-Category": new_sub
                        })
                
                if changes:
                    st.session_state.cat_preview_changes = changes
                    # Format a preview dataframe for user display
                    preview_rows = []
                    for c in changes:
                        preview_rows.append({
                            "Date": pd.to_datetime(c["date"]).strftime("%d %b %Y") if pd.notna(c["date"]) else "—",
                            "Bank": c["bank_name"],
                            "Description": str(c["bank_description"])[:60],
                            "Amount": f"₹{c['amount']:,.2f}",
                            "Current": f"{c['Current Category']} ({c['Current Sub-Category']})",
                            "Proposed": f"{c['Proposed Category']} ({c['Proposed Sub-Category']})"
                        })
                    st.session_state.cat_preview_df = pd.DataFrame(preview_rows)
                else:
                    st.session_state.cat_preview_changes = []
                    st.session_state.cat_preview_df = pd.DataFrame()

        if col_clear.button("✕ Clear Preview", key="btn_clear_preview"):
            st.session_state.cat_preview_changes = None
            st.session_state.cat_preview_df = None

        # Display preview if available
        if st.session_state.cat_preview_df is not None:
            if st.session_state.cat_preview_df.empty:
                st.info("🎉 No categorization changes detected. All transactions are already up to date!")
            else:
                st.markdown(f"**Proposed Changes ({len(st.session_state.cat_preview_df)} transactions affected):**")
                st.dataframe(
                    st.session_state.cat_preview_df,
                    width="stretch",
                    height=min(400, 38 * len(st.session_state.cat_preview_df) + 38),
                    hide_index=True
                )
                
                if st.button("💾 Confirm & Apply Proposed Changes", type="primary", key="btn_apply_cat_changes"):
                    master = load_all()
                    updated = 0
                    for c in st.session_state.cat_preview_changes:
                        mask = master["id"] == c["id"]
                        if mask.any():
                            master.loc[mask, "category"] = c["Proposed Category"]
                            master.loc[mask, "sub_category"] = c["Proposed Sub-Category"]
                            updated += 1
                    
                    if updated > 0:
                        save_all(master, reason="runner_recategorize")
                        st.success(f"✅ Successfully updated {updated} transaction(s) in the database!")
                        # Clear preview
                        st.session_state.cat_preview_changes = None
                        st.session_state.cat_preview_df = None
                    else:
                        st.error("No matches found to update.")

    # ══════════════════════════════════════════════════════════════════
    # TAB 3 — Audit Sources
    # (new tab: shows the pipeline configuration at a glance)
    # ══════════════════════════════════════════════════════════════════
    with tab_audit_cfg:
        st.markdown("### Audit Pipeline Configuration")
        st.caption(
            "These lists control how the audit engine classifies each source "
            "and whether a match marks a bank transaction as **Audited**."
        )

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown(
                f'<div style="background:{GREEN}11;border:1px solid {GREEN}55;'
                f'border-radius:10px;padding:12px 16px;margin-bottom:12px">'
                f'<b style="color:{GREEN}">🔍 Audit Sources</b><br>'
                f'<span style="font-size:0.78rem;color:#aaa">Match → always marks Audited</span><br><br>'
                + "".join(f'<code style="color:{GREEN}">{s}</code><br>' for s in AUDIT_SOURCES)
                + '</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div style="background:{BLUE}11;border:1px solid {BLUE}55;'
                f'border-radius:10px;padding:12px 16px">'
                f'<b style="color:{BLUE}">🏪 Terminal / Merchant Apps</b><br>'
                f'<span style="font-size:0.78rem;color:#aaa">Match → marks Audited</span><br><br>'
                + "".join(f'<code style="color:{BLUE}">{s}</code><br>' for s in TERMINAL_SOURCES)
                + '</div>',
                unsafe_allow_html=True,
            )

        with col_b:
            st.markdown(
                f'<div style="background:{YELLOW}11;border:1px solid {YELLOW}55;'
                f'border-radius:10px;padding:12px 16px;margin-bottom:12px">'
                f'<b style="color:{YELLOW}">💳 Payment Intermediators</b><br>'
                f'<span style="font-size:0.78rem;color:#aaa">Match → enriches only (no Audited)</span><br><br>'
                + "".join(f'<code style="color:{YELLOW}">{s}</code><br>' for s in INTERMEDIATOR_SOURCES)
                + '</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div style="background:{PURPLE}11;border:1px solid {PURPLE}55;'
                f'border-radius:10px;padding:12px 16px">'
                f'<b style="color:{PURPLE}">🏦 Bank Sources</b><br>'
                f'<span style="font-size:0.78rem;color:#aaa">Primary audit targets</span><br><br>'
                + "".join(f'<code style="color:{PURPLE}">{s}</code><br>' for s in BANK_SOURCES)
                + '</div>',
                unsafe_allow_html=True,
            )

        st.markdown("---")
        st.info(
            "To add a new source or change its role, update "
            "`zenfinance/parsers/registry.py` — "
            "`BANK_SOURCES`, `INTERMEDIATOR_SOURCES`, `TERMINAL_SOURCES`, `AUDIT_SOURCES`."
        )

    # ══════════════════════════════════════════════════════════════════
    # TAB 4 — Data Management
    # ══════════════════════════════════════════════════════════════════
    with tab_data:
        st.markdown("### Database Overview")
        df = load_all()
        if df.empty:
            st.info("Database is empty.")
        else:
            d1, d2, d3 = st.columns(3)
            d1.metric("Total Transactions", len(df))
            d2.metric(
                "Date Range",
                f"{pd.to_datetime(df['date']).min().strftime('%d %b %y')} – "
                f"{pd.to_datetime(df['date']).max().strftime('%d %b %y')}",
            )
            d3.metric("Sources", df["bank_name"].nunique())

            st.markdown("**Breakdown by source:**")
            src = (
                df.groupby("bank_name")
                .agg(
                    Transactions=("id", "count"),
                    Debits=("amount", lambda x: x[df.loc[x.index, "txn_type"] == "DEBIT"].sum()),
                    Credits=("amount", lambda x: x[df.loc[x.index, "txn_type"] == "CREDIT"].sum()),
                )
                .reset_index()
                .rename(columns={"bank_name": "Source"})
            )
            st.dataframe(src, width="stretch", hide_index=True)

            # Audit status summary
            st.markdown("**Audit status breakdown:**")
            audit_summary = df["audit_status"].value_counts().reset_index()
            audit_summary.columns = ["Status", "Count"]
            st.dataframe(audit_summary, width="stretch", hide_index=True)

        st.markdown("---")
        st.markdown("#### 🗑️ Danger Zone")
        with st.expander("⚠️ Delete all transactions", expanded=False):
            st.warning(
                "This will permanently delete ALL transactions from the database. "
                "A backup will be created first."
            )
            confirm = st.text_input("Type **DELETE** to confirm", key="del_confirm")
            if st.button(
                "Delete All Data", type="secondary",
                disabled=(confirm != "DELETE"), key="btn_delete_all"
            ):
                from zenfinance.models import TRANSACTION_COLUMNS
                save_all(pd.DataFrame(columns=TRANSACTION_COLUMNS), reason="delete_all")
                st.success(
                    "✅ All transactions deleted. A backup was saved automatically. "
                    "Refresh the page to confirm."
                )

        st.markdown("---")
        st.markdown("#### 📥 Import from Raw CSV")
        st.caption("Already have a ZenFinance-format CSV? Upload it directly to merge into the database.")
        raw_csv = st.file_uploader("Upload ZenFinance CSV", type=["csv"], key="raw_csv_upload")
        if raw_csv:
            try:
                raw_df = pd.read_csv(raw_csv)
                st.write(f"Found **{len(raw_df)}** rows. Preview:")
                st.dataframe(raw_df.head(5), width="stretch")
                if st.button("Merge into Database", key="btn_merge_csv"):
                    existing = load_all()
                    merged = pd.concat([existing, raw_df], ignore_index=True)
                    merged = merged.drop_duplicates(subset=["hash"], keep="first")
                    save_all(merged, reason="raw_csv_import")
                    st.success(
                        f"✅ Merged! Database now has {len(merged)} rows. "
                        "Refresh the page to see updated data."
                    )
            except Exception as e:
                st.error(f"Error reading CSV: {e}")

    # ══════════════════════════════════════════════════════════════════
    # TAB 5 — Security & Cloud
    # ══════════════════════════════════════════════════════════════════
    with tab_security:
        st.markdown("### 🔒 Security & Cloud Settings")
        st.caption("Manage authentication settings and sync/export data with Google Drive.")
        
        # 1. Auth Section
        st.markdown("#### 🔑 Authentication")
        col_out, _ = st.columns([1.5, 3])
        if col_out.button("🚪 Log Out of ZenFinance", type="secondary", key="btn_logout"):
            try:
                if "cookie_manager" in st.session_state and st.session_state["cookie_manager"]:
                    st.session_state["cookie_manager"].delete("auth_pin")
                st.session_state["authenticated"] = False
                st.success("Logged out! Refreshing...")
                st.rerun()
            except Exception as e:
                st.error(f"Error logging out: {e}")
                
        st.markdown("---")
        
        # 2. Google Drive Section
        st.markdown("#### ☁️ Google Drive Connection")
        st.info(
            f"**Drive Folder ID:** `{gdrive.FOLDER_ID}`\n\n"
            f"**Service Account:** `gdrive@zenfinance369.iam.gserviceaccount.com` "
            f"(Ensure Editor access is granted to this email for the folder)."
        )
        
        if st.button("🔌 Test Google Drive Connection", key="btn_test_gdrive"):
            service = gdrive.get_drive_service()
            if service:
                try:
                    # Try listing files in the directory
                    query = f"'{gdrive.FOLDER_ID}' in parents and trashed = false"
                    results = service.files().list(q=query, pageSize=1, fields="files(id, name)").execute()
                    st.success("✅ Connected successfully to Google Drive folder!")
                except Exception as e:
                    st.error(f"❌ Connection failed: {e}")
            else:
                st.error("❌ Authentication failed. Please check credentials.")
                
        st.markdown("---")
        
        # 3. ZIP Import/Export Section
        st.markdown("#### 📦 ZIP Import / Export")
        st.caption(
            "Download a complete archive of your transactions and backups, "
            "or restore them in bulk by uploading a structured ZIP file."
        )
        
        z1, z2 = st.columns(2)
        
        with z1:
            st.markdown("**Export Data**")
            st.caption("Downloads transactions.csv and all backups from Google Drive as a single ZIP archive.")
            if st.button("📦 Prepare Export ZIP", key="btn_prep_zip"):
                with st.spinner("Generating ZIP from Google Drive..."):
                    try:
                        zip_bytes = gdrive.generate_data_zip()
                        st.download_button(
                            "⬇️ Download Data ZIP",
                            data=zip_bytes,
                            file_name=f"zenfinance_backup_{datetime.now().strftime('%Y%m%d')}.zip",
                            mime="application/zip",
                            key="btn_download_zip_act"
                        )
                        st.success("ZIP prepared successfully! Click above to download.")
                    except Exception as e:
                        st.error(f"Failed to generate ZIP: {e}")
                        
        with z2:
            st.markdown("**Import / Restore ZIP**")
            st.caption("Upload a structured ZIP (containing transactions.csv) to overwrite cloud data.")
            uploaded_zip = st.file_uploader("Upload ZIP Backup", type=["zip"], key="zip_backup_uploader")
            if uploaded_zip:
                if st.button("⚠️ Restore Entire Database from ZIP", type="secondary", key="btn_restore_zip"):
                    with st.spinner("Restoring data in Google Drive..."):
                        if gdrive.restore_data_from_zip(uploaded_zip.read()):
                            from zenfinance.data_store import clear_cache
                            clear_cache()
                            st.success("✅ Database restored successfully! Refresh the page to see changes.")
                        else:
                            st.error("Restore failed. Verify the ZIP file format.")

    # ══════════════════════════════════════════════════════════════════
    # TAB 6 — About
    # ══════════════════════════════════════════════════════════════════
    with tab_about:

        st.markdown("""
### ZenFinance — Personal Finance Auditing Tool

**Version**: 2.0.0

---

### Supported Sources

**🔍 Audit / Ground Truth**
- AXIO — your personal finance ledger (CSV / XLSX). Imports mark bank transactions as Audited.

**🏦 Banks**
- SBI Bank (XLSX · XLS · **PDF** ← new)
- ICICI Bank (XLS · XLSX · **PDF** ← new)
- HDFC Bank (CSV / Excel — generic parser)
- Axis Bank (CSV / Excel — generic parser)
- Kotak Bank (CSV / Excel — generic parser)

**💳 Payment Intermediators** *(enrich records, do NOT set Audited alone)*
- PhonePe (PDF)
- Google Pay (CSV)
- Paytm (CSV / Excel)
- Amazon Pay (CSV)

**🏪 Terminal / Merchant Apps** *(confirm spend → set Audited)*
- Swiggy · Zomato · Blinkit · Zepto
- BigBasket · Amazon · Swiggy Money

---

### Audit Philosophy

A bank transaction is marked **Audited** only when:
1. It is found in your **AXIO** export, OR
2. It is found in a **terminal/merchant app** record (Swiggy, Zomato, Blinkit, Zepto…)

**PhonePe / GPay** are payment *intermediators* — they show the payment route
but do not confirm which merchant received the money. They enrich the record
(add UTR, payment method info) without marking it Audited.

---

### Core Features
- MD5-based deduplication — re-uploading the same file is always safe
- Multi-format parsers — each source supports Excel AND PDF where available
- Regex + fuzzy matching auto-categorises transactions
- 4-pass cross-source audit (AXIO → Terminal Apps → Intermediator enrichment → Flag)
- Automatic timestamped backups on every change
- Plotly charts: spending timeline, category donut, monthly trends

### Tech Stack
Python · Pandas · Plotly · Streamlit · PyMuPDF · thefuzz

---
Built with ❤️ for personal finance clarity.
        """)
