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
        '<b style="color:#6C63FF">ℹ️ About</b>'
        '</div>',
        unsafe_allow_html=True,
    )

    tab_backup, tab_cats, tab_audit_cfg, tab_data, tab_about = st.tabs(
        ["💾 Backups", "🏷️ Categories", "🔍 Audit Sources", "🗄️ Data Management", "ℹ️ About"]
    )

    # ══════════════════════════════════════════════════════════════════
    # TAB 1 — Backups
    # ══════════════════════════════════════════════════════════════════
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

            # Restore — use a flag in session state so UI refreshes without
            # sidebar-collapsing st.rerun()
            if b1.button("🔄 Restore Selected Backup", type="primary", key="btn_restore"):
                if restore_backup(selected_backup):
                    st.success(f"✅ Restored from `{selected_backup}`. Refresh the page to see updated data.")
                else:
                    st.error("Restore failed — file not found.")

            # Download
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
        st.dataframe(rules_df, use_container_width=True, hide_index=True, height=450)

        st.markdown("---")
        st.markdown("#### Re-apply Auto-Categorisation")
        st.caption("Re-runs category detection on all **Uncategorized** transactions.")
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
            st.dataframe(src, use_container_width=True, hide_index=True)

            # Audit status summary
            st.markdown("**Audit status breakdown:**")
            audit_summary = df["audit_status"].value_counts().reset_index()
            audit_summary.columns = ["Status", "Count"]
            st.dataframe(audit_summary, use_container_width=True, hide_index=True)

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
                st.dataframe(raw_df.head(5), use_container_width=True)
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
    # TAB 5 — About
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
