"""
ZenFinance — Settings & Backup Management UI
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from zenfinance.categorization import CATEGORY_RULES, get_all_categories
from zenfinance.data_store import (
    get_backup_list,
    load_all,
    restore_backup,
    save_all,
    DB_PATH,
    BACKUP_DIR,
)

GREEN  = "#43D9AD"
RED    = "#FF6584"
YELLOW = "#FFB347"
PURPLE = "#6C63FF"


def render():
    st.markdown("## ⚙️ Settings & Management")

    tab_backup, tab_cats, tab_data, tab_about = st.tabs(
        ["💾 Backups", "🏷️ Categories", "🗄️ Data Management", "ℹ️ About"]
    )

    # ── Backups ──────────────────────────────────────────
    with tab_backup:
        st.markdown("### Automatic Backup History")
        st.caption(
            f"Every import and edit triggers an automatic timestamped backup. "
            f"Backups are stored in `{BACKUP_DIR}`."
        )

        backups = get_backup_list()
        if not backups:
            st.info("No backups yet — they are created automatically on every import or edit.")
        else:
            st.markdown(f"**{len(backups)} backup(s) available** · newest first")
            selected_backup = st.selectbox("Select backup to restore", backups)
            b1, b2 = st.columns(2)
            if b1.button("🔄 Restore Selected Backup", type="primary"):
                if restore_backup(selected_backup):
                    st.success(f"✅ Restored from `{selected_backup}`. Current data replaced.")
                    st.rerun()
                else:
                    st.error("Restore failed — file not found.")

            # Show backup as downloadable CSV
            import io
            from pathlib import Path
            backup_path = BACKUP_DIR / selected_backup
            if backup_path.exists():
                bdf = pd.read_csv(backup_path)
                b2.download_button(
                    "⬇️ Download Backup",
                    data=bdf.to_csv(index=False).encode(),
                    file_name=selected_backup,
                    mime="text/csv",
                    use_container_width=True,
                )

            with st.expander("📋 All backup files"):
                for b in backups:
                    st.code(b, language=None)

    # ── Category rules ────────────────────────────────────
    with tab_cats:
        st.markdown("### Categorisation Rules")
        st.caption(
            "These regex patterns are applied to transaction descriptions to auto-assign categories. "
            "Rules are checked in order — first match wins."
        )

        # Display rules as a table
        rules_rows = []
        for cat, sub, patterns in CATEGORY_RULES:
            rules_rows.append({
                "Category":    cat,
                "Sub-Category": sub,
                "Patterns":    ", ".join(patterns[:4]) + ("…" if len(patterns) > 4 else ""),
            })
        rules_df = pd.DataFrame(rules_rows)
        st.dataframe(rules_df, use_container_width=True, hide_index=True, height=450)

        # Re-apply categorisation button
        st.markdown("---")
        st.markdown("#### Re-apply Auto-Categorisation")
        st.caption("This will re-run category detection on all **Uncategorized** transactions.")
        if st.button("🔁 Re-categorise Uncategorised Transactions"):
            from zenfinance.categorization import apply_categories
            df = load_all()
            if df.empty:
                st.warning("No transactions in database.")
            else:
                before = int((df["category"].isna() | (df["category"] == "Uncategorized")).sum())
                df = apply_categories(df)
                save_all(df, reason="recategorize")
                after = int((df["category"].isna() | (df["category"] == "Uncategorized")).sum())
                st.success(f"✅ Done! Fixed {before - after} previously uncategorised transaction(s).")

    # ── Data management ───────────────────────────────────
    with tab_data:
        st.markdown("### Database Overview")
        df = load_all()
        if df.empty:
            st.info("Database is empty.")
        else:
            d1, d2, d3 = st.columns(3)
            d1.metric("Total Transactions", len(df))
            d2.metric("Date Range",
                       f"{pd.to_datetime(df['date']).min().strftime('%d %b %y')} – "
                       f"{pd.to_datetime(df['date']).max().strftime('%d %b %y')}")
            d3.metric("Sources", df["bank_name"].nunique())

            st.markdown("**Breakdown by source:**")
            src = df.groupby("bank_name").agg(
                Transactions=("id", "count"),
                Debits=("amount", lambda x: x[df.loc[x.index, "txn_type"] == "DEBIT"].sum()),
                Credits=("amount", lambda x: x[df.loc[x.index, "txn_type"] == "CREDIT"].sum()),
            ).reset_index().rename(columns={"bank_name": "Source"})
            st.dataframe(src, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("#### 🗑️ Danger Zone")
        with st.expander("⚠️ Delete all transactions", expanded=False):
            st.warning("This will permanently delete ALL transactions from the database. A backup will be created first.")
            confirm = st.text_input("Type **DELETE** to confirm", key="del_confirm")
            if st.button("Delete All Data", type="secondary", disabled=(confirm != "DELETE")):
                import pandas as pd
                from zenfinance.data_store import save_all
                from zenfinance.models import TRANSACTION_COLUMNS
                save_all(pd.DataFrame(columns=TRANSACTION_COLUMNS), reason="delete_all")
                st.success("✅ All transactions deleted. A backup was saved automatically.")
                st.rerun()

        st.markdown("---")
        st.markdown("#### 📥 Import from Raw CSV")
        st.caption("Already have a ZenFinance-format CSV? Upload it directly to merge into the database.")
        raw_csv = st.file_uploader("Upload ZenFinance CSV", type=["csv"], key="raw_csv_upload")
        if raw_csv:
            try:
                raw_df = pd.read_csv(raw_csv)
                st.write(f"Found **{len(raw_df)}** rows. Preview:")
                st.dataframe(raw_df.head(5), use_container_width=True)
                if st.button("Merge into Database"):
                    existing = load_all()
                    merged = pd.concat([existing, raw_df], ignore_index=True)
                    merged = merged.drop_duplicates(subset=["hash"], keep="first")
                    save_all(merged, reason="raw_csv_import")
                    st.success(f"✅ Merged! Database now has {len(merged)} rows.")
                    st.rerun()
            except Exception as e:
                st.error(f"Error reading CSV: {e}")

    # ── About ─────────────────────────────────────────────
    with tab_about:
        st.markdown("""
### ZenFinance — Personal Finance Auditing Tool

**Version**: 1.0.0

**Supported Sources**
- 🏦 SBI Bank (XLSX)
- 🏦 ICICI Bank (XLS / XLSX)
- 📱 PhonePe (PDF)
- 📱 Google Pay (CSV)
- 🏦 HDFC, Axis, Kotak (CSV / Excel — generic parser)
- 🛒 Swiggy Money, Amazon Pay, Paytm (CSV)

**Core Features**
- MD5-based deduplication prevents double-importing
- Regex + fuzzy matching auto-categorises transactions
- Cross-source UTR audit (bank vs PhonePe/GPay)
- Automatic timestamped backups on every change
- Plotly charts: spending timeline, category donut, monthly trends

**Tech Stack**
Python · Pandas · Plotly · Streamlit · PyMuPDF · thefuzz

---
Built with ❤️ for personal finance clarity.
        """)
