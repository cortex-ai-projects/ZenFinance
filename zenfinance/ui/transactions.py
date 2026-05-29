"""
ZenFinance — Transactions Explorer UI
Filterable, colour-coded table with inline audit + category editing.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from zenfinance.categorization import get_all_categories
from zenfinance.data_store import delete_row, load_all, save_all, update_row

# ── colours ───────────────────────────────────────
GREEN  = "#43D9AD"
RED    = "#FF6584"
YELLOW = "#FFB347"
PURPLE = "#6C63FF"
BLUE   = "#56CCF2"
CARD   = "#1A1D2E"

STATUS_COLOURS = {
    "Pending":   YELLOW,
    "Audited":   GREEN,
    "Flagged":   RED,
    "Duplicate": PURPLE,
}


def _badge(text: str, colour: str) -> str:
    return (
        f'<span style="background:{colour}15;color:{colour};border:1px solid {colour}35;'
        f'border-radius:12px;padding:4px 12px;font-size:0.72rem;font-weight:600;display:inline-block;backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)">{text}</span>'
    )


def _apply_row_style(val, col: str):
    """Pandas Styler: colour cells by audit_status column."""
    if col == "audit_status":
        colour = STATUS_COLOURS.get(str(val), "#ffffff")
        return f"color:{colour};font-weight:600"
    if col == "txn_type":
        return f"color:{RED if val=='DEBIT' else GREEN};font-weight:600"
    if col == "amount":
        return "font-weight:600"
    return ""


def render(filter_source: str = "All", date_from=None, date_to=None):
    st.markdown("## 💳 Transactions Explorer")

    df = load_all()
    if df.empty:
        st.info("No transactions yet — head to **Import** to upload your first statement.")
        return

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)

    # ── Sidebar-driven filters ─────────────────────
    with st.expander("🔎 Filters", expanded=True):
        fcol1, fcol2, fcol3, fcol4 = st.columns(4)

        # Source
        sources = ["All"] + sorted(df["bank_name"].dropna().unique().tolist())
        if filter_source not in sources:
            filter_source = "All"
        sel_source = fcol1.selectbox("Source", sources,
                                     index=sources.index(filter_source))

        # Type
        sel_type = fcol2.selectbox("Type", ["All", "DEBIT", "CREDIT"])

        # Status
        statuses = ["All"] + sorted(df["audit_status"].dropna().unique().tolist())
        sel_status = fcol3.selectbox("Status", statuses)

        # Category
        cats = ["All"] + sorted(df["category"].dropna().unique().tolist())
        sel_cat = fcol4.selectbox("Category", cats)

        # Date range
        d1, d2 = st.columns(2)
        min_date = df["date"].min().date() if not df["date"].isna().all() else None
        max_date = df["date"].max().date() if not df["date"].isna().all() else None
        sel_from = d1.date_input("From", value=date_from or min_date, min_value=min_date, max_value=max_date)
        sel_to   = d2.date_input("To",   value=date_to   or max_date, min_value=min_date, max_value=max_date)

        # Search
        search = st.text_input("🔍 Search description / details", placeholder="e.g. Swiggy, Netflix, salary…")

    # ── Apply filters ──────────────────────────────
    fdf = df.copy()
    if sel_source != "All":
        fdf = fdf[fdf["bank_name"] == sel_source]
    if sel_type != "All":
        fdf = fdf[fdf["txn_type"] == sel_type]
    if sel_status != "All":
        fdf = fdf[fdf["audit_status"] == sel_status]
    if sel_cat != "All":
        fdf = fdf[fdf["category"] == sel_cat]
    if sel_from and sel_to:
        fdf = fdf[
            (fdf["date"].dt.date >= sel_from) &
            (fdf["date"].dt.date <= sel_to)
        ]
    if search:
        mask = (
            fdf["bank_description"].astype(str).str.contains(search, case=False, na=False) |
            fdf["details"].astype(str).str.contains(search, case=False, na=False)
        )
        fdf = fdf[mask]

    # ── Summary row ───────────────────────────────
    st.markdown("---")
    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("Showing",  f"{len(fdf)} rows")
    sm2.metric("Total Debits",  f"₹{fdf[fdf['txn_type']=='DEBIT']['amount'].sum():,.0f}")
    sm3.metric("Total Credits", f"₹{fdf[fdf['txn_type']=='CREDIT']['amount'].sum():,.0f}")
    sm4.metric("Pending",
               int((fdf["audit_status"] == "Pending").sum()),
               help="Transactions awaiting review")

    # ── Display columns ────────────────────────────
    display_cols = ["date", "bank_name", "txn_type", "amount", "category",
                    "bank_description", "payment_method", "audit_status"]
    view = fdf[display_cols].copy()
    view["date"]   = view["date"].dt.strftime("%d %b %Y")
    view["amount"] = view["amount"].map(lambda x: f"₹{x:,.2f}")
    view.columns   = ["Date", "Source", "Type", "Amount", "Category",
                       "Description", "Payment", "Status"]

    # Colour-coded display using st.dataframe column config
    st.dataframe(
        view,
        width="stretch",
        height=min(600, 38 * len(view) + 50),
        column_config={
            "Type": st.column_config.TextColumn("Type", width="small"),
            "Amount": st.column_config.TextColumn("Amount", width="small"),
            "Status": st.column_config.TextColumn("Status", width="medium"),
        },
        hide_index=True,
    )

    # ── Colour legend ──────────────────────────────
    legend_html = " &nbsp; ".join(
        _badge(k, v) for k, v in STATUS_COLOURS.items()
    )
    st.markdown(f"**Status colours:** {legend_html}", unsafe_allow_html=True)

    # ── Bulk status update ─────────────────────────
    st.markdown("---")
    st.markdown("### ✏️ Bulk Audit Update")
    st.caption("Select rows to mark as Audited, Flagged, or Duplicate.")

    if len(fdf) > 0:
        all_ids = fdf["id"].tolist()
        sel_ids = st.multiselect(
            "Select transaction IDs to update",
            options=all_ids,
            format_func=lambda i: (
                f"{fdf.loc[fdf['id']==i, 'date'].iloc[0].strftime('%d %b %y')} · "
                f"{fdf.loc[fdf['id']==i, 'bank_name'].iloc[0]} · "
                f"₹{fdf.loc[fdf['id']==i, 'amount'].iloc[0]:,.0f} · "
                f"{str(fdf.loc[fdf['id']==i, 'bank_description'].iloc[0])[:40]}"
            ),
        )

        ua_col1, ua_col2, ua_col3 = st.columns([2, 2, 2])
        new_status   = ua_col1.selectbox("Set Status to", ["Audited", "Pending", "Flagged", "Duplicate"])
        new_category = ua_col2.selectbox("Set Category (optional)", ["— keep existing —"] + get_all_categories())

        if ua_col3.button("Apply to Selected", type="primary", disabled=not sel_ids):
            master = load_all()
            updated = 0
            for row_id in sel_ids:
                upd: dict = {"audit_status": new_status}
                if new_category != "— keep existing —":
                    upd["category"] = new_category
                mask = master["id"] == row_id
                for col, val in upd.items():
                    master.loc[mask, col] = val
                updated += 1
            save_all(master, reason="bulk_audit")
            st.success(f"✅ Updated {updated} transaction(s) to **{new_status}**.")
            st.rerun()

    # ── Single row editor ─────────────────────────
    st.markdown("---")
    st.markdown("### 🔧 Edit Single Transaction")
    with st.expander("Open editor"):
        edit_id = st.text_input("Paste a Transaction ID to edit")
        if edit_id:
            row = df[df["id"] == edit_id]
            if row.empty:
                st.error("Transaction ID not found.")
            else:
                r = row.iloc[0]
                st.write(f"**{r['bank_name']}** · {r['bank_description'][:80]}")
                e1, e2, e3 = st.columns(3)
                new_cat    = e1.selectbox("Category",    get_all_categories(),
                                          index=get_all_categories().index(r["category"])
                                          if r["category"] in get_all_categories() else 0)
                new_status = e2.selectbox("Status",
                                          ["Pending", "Audited", "Flagged", "Duplicate"],
                                          index=["Pending","Audited","Flagged","Duplicate"].index(r["audit_status"])
                                          if r["audit_status"] in ["Pending","Audited","Flagged","Duplicate"] else 0)
                new_tags   = e3.text_input("Tags (comma-separated)", value=r.get("tags", "") or "")
                new_comment= st.text_input("Comment", value=r.get("system_comment", "") or "")
                if st.button("💾 Save Changes"):
                    update_row(edit_id, {
                        "category": new_cat,
                        "audit_status": new_status,
                        "tags": new_tags,
                        "system_comment": new_comment,
                    })
                    st.success("Saved!")
                    st.rerun()
                if st.button("🗑️ Delete Transaction", type="secondary"):
                    delete_row(edit_id)
                    st.warning("Transaction deleted.")
                    st.rerun()

    # ── Export ────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📤 Export")
    exp1, exp2 = st.columns(2)
    csv_data = fdf.to_csv(index=False).encode("utf-8")
    exp1.download_button(
        "⬇️ Download filtered CSV",
        data=csv_data,
        file_name="zenfinance_export.csv",
        mime="text/csv",
        width="stretch",
    )
