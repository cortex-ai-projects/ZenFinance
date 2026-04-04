"""
ZenFinance — Cross-Source Audit UI
Matches bank transactions against PhonePe / GPay records using UTR + amount + date.
Shows unmatched, matched, and flagged transactions side-by-side.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from zenfinance.data_store import load_all, save_all

GREEN  = "#43D9AD"
RED    = "#FF6584"
YELLOW = "#FFB347"
PURPLE = "#6C63FF"
CARD   = "#1A1D2E"

BANK_SOURCES = ["SBI", "ICICI", "HDFC", "Axis", "Kotak"]
UPI_SOURCES  = ["PhonePe", "Google Pay", "Paytm", "Amazon Pay"]


def _run_audit(df: pd.DataFrame, date_tol: int = 1, amount_tol: float = 0.01) -> pd.DataFrame:
    """
    Cross-match bank rows against UPI rows.
    Marks bank rows MATCHED / UNMATCHED; marks UPI duplicates.
    Returns the updated dataframe.
    """
    df = df.copy()
    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce")

    bank_mask = df["bank_name"].isin(BANK_SOURCES)
    upi_mask  = df["bank_name"].isin(UPI_SOURCES)

    bank_df = df[bank_mask].copy()
    upi_df  = df[upi_mask].copy()

    date_delta = pd.Timedelta(days=date_tol)

    for b_idx, b_row in bank_df.iterrows():
        if pd.isna(b_row["date_dt"]):
            continue
        for u_idx, u_row in upi_df.iterrows():
            if pd.isna(u_row["date_dt"]):
                continue
            # UTR match (strongest signal)
            utr_match = (
                pd.notna(b_row.get("utr_number")) and
                pd.notna(u_row.get("utr_number")) and
                str(b_row["utr_number"]).split(".")[0] == str(u_row["utr_number"]).split(".")[0]
            )
            date_match   = abs(b_row["date_dt"] - u_row["date_dt"]) <= date_delta
            amount_match = abs(float(b_row["amount"]) - float(u_row["amount"])) <= amount_tol

            if utr_match or (date_match and amount_match):
                df.loc[b_idx, "audit_status"]    = "Audited"
                df.loc[b_idx, "system_comment"]  = f"Matched with {u_row['bank_name']} (UTR: {u_row.get('utr_number','')})"
                break
        else:
            if df.loc[b_idx, "audit_status"] == "Pending":
                df.loc[b_idx, "audit_status"]   = "Flagged"
                df.loc[b_idx, "system_comment"] = "No matching UPI record found"

    df.drop(columns=["date_dt"], inplace=True, errors="ignore")
    return df


def render():
    st.markdown("## 🔍 Cross-Source Audit")
    st.markdown(
        "Automatically match bank statement transactions with PhonePe / Google Pay records "
        "using UTR numbers, amounts, and dates. Flag anything that doesn't reconcile."
    )

    df = load_all()
    if df.empty:
        st.info("No transactions to audit yet — import data first.")
        return

    df["date"]   = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)

    # ── Audit settings ────────────────────────────
    st.markdown("### ⚙️ Audit Settings")
    s1, s2 = st.columns(2)
    date_tol   = s1.slider("Date tolerance (days)", 0, 5, 1,
                           help="Allow transactions within ±N days to be considered a match")
    amount_tol = s2.number_input("Amount tolerance (₹)", 0.0, 100.0, 0.01, step=0.01,
                                 help="Allow small rounding differences")

    # ── Current status overview ───────────────────
    st.markdown("---")
    st.markdown("### 📊 Current Audit Status")

    bank_rows = df[df["bank_name"].isin(BANK_SOURCES)]
    upi_rows  = df[df["bank_name"].isin(UPI_SOURCES)]

    ov1, ov2, ov3, ov4 = st.columns(4)
    ov1.metric("Bank transactions",  len(bank_rows))
    ov2.metric("UPI transactions",   len(upi_rows))
    ov3.metric("Audited",  int((df["audit_status"] == "Audited").sum()),  delta_color="normal")
    ov4.metric("Flagged",  int((df["audit_status"] == "Flagged").sum()),  delta_color="inverse")

    # ── Run audit ─────────────────────────────────
    st.markdown("---")
    run_col, _ = st.columns([1, 3])
    if run_col.button("🚀 Run Audit Now", type="primary", use_container_width=True):
        if len(bank_rows) == 0:
            st.warning("No bank source transactions found. Import SBI / ICICI / HDFC data first.")
        elif len(upi_rows) == 0:
            st.warning("No UPI source transactions found. Import PhonePe / GPay data first.")
        else:
            with st.spinner("Running cross-source audit…"):
                updated_df = _run_audit(df, date_tol=date_tol, amount_tol=amount_tol)
                save_all(updated_df, reason="audit_run")

            matched   = int((updated_df["audit_status"] == "Audited").sum())
            flagged   = int((updated_df["audit_status"] == "Flagged").sum())
            st.success(f"✅ Audit complete — **{matched}** matched · **{flagged}** flagged")
            st.rerun()

    # ── Flagged transactions ──────────────────────
    st.markdown("---")
    flagged_df = df[df["audit_status"] == "Flagged"]
    if not flagged_df.empty:
        st.markdown(f"### 🚩 Flagged Transactions ({len(flagged_df)})")
        st.caption("These bank transactions have no matching UPI record. Review and resolve.")

        show_cols = ["date", "bank_name", "amount", "txn_type", "bank_description",
                     "payment_method", "system_comment"]
        view = flagged_df[show_cols].copy()
        view["date"]   = view["date"].dt.strftime("%d %b %Y")
        view["amount"] = view["amount"].map(lambda x: f"₹{x:,.2f}")
        view.columns   = ["Date", "Source", "Amount", "Type", "Description", "Payment", "Comment"]
        st.dataframe(view, use_container_width=True, hide_index=True, height=min(400, 38*len(view)+50))

        if st.button("✅ Mark All Flagged as Reviewed"):
            master = load_all()
            master.loc[master["audit_status"] == "Flagged", "audit_status"] = "Audited"
            master.loc[master["audit_status"] == "Audited", "system_comment"] = "Manually reviewed"
            save_all(master, reason="resolve_flagged")
            st.success("All flagged transactions marked as reviewed.")
            st.rerun()
    else:
        st.success("🎉 No flagged transactions — everything is reconciled!")

    # ── Matched transactions ──────────────────────
    st.markdown("---")
    matched_df = df[df["audit_status"] == "Audited"]
    if not matched_df.empty:
        with st.expander(f"✅ Matched / Audited Transactions ({len(matched_df)})"):
            show_cols = ["date", "bank_name", "amount", "txn_type",
                         "bank_description", "payment_method", "system_comment"]
            view = matched_df[show_cols].copy()
            view["date"]   = view["date"].dt.strftime("%d %b %Y")
            view["amount"] = view["amount"].map(lambda x: f"₹{x:,.2f}")
            view.columns   = ["Date", "Source", "Amount", "Type", "Description", "Payment", "Comment"]
            st.dataframe(view, use_container_width=True, hide_index=True, height=min(400, 38*len(view)+50))

    # ── Unmatched UPI ─────────────────────────────
    unmatched_upi = df[df["bank_name"].isin(UPI_SOURCES) & (df["audit_status"] == "Pending")]
    if not unmatched_upi.empty:
        st.markdown("---")
        with st.expander(f"⚠️ Unmatched UPI Transactions ({len(unmatched_upi)})"):
            st.caption("These PhonePe / GPay entries have no corresponding bank record (e.g. wallet-only payments).")
            show_cols = ["date", "bank_name", "amount", "txn_type", "bank_description", "payment_method"]
            view = unmatched_upi[show_cols].copy()
            view["date"]   = view["date"].dt.strftime("%d %b %Y")
            view["amount"] = view["amount"].map(lambda x: f"₹{x:,.2f}")
            view.columns   = ["Date", "Source", "Amount", "Type", "Description", "Payment"]
            st.dataframe(view, use_container_width=True, hide_index=True)
