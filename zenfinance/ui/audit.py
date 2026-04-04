"""
ZenFinance — Cross-Source Audit UI
═══════════════════════════════════════════════════════════════════════════════

Audit philosophy
────────────────
A bank transaction is marked **Audited** ONLY when:
  1. It is found in the AXIO export  (user's ground-truth manual ledger), OR
  2. It is found in a terminal/merchant app transaction
     (Swiggy, Zomato, Blinkit, Zepto, BigBasket, Amazon, …)

**PhonePe, Google Pay, Paytm, Amazon Pay** are treated as *payment intermediators*
— they route money but do not independently confirm which merchant received it.
Matching against an intermediator enriches the record (adds UTR, payment method)
but does NOT alone mark it Audited.

Audit status values
────────────────────
  Pending   — not yet processed
  Audited   — confirmed by AXIO or a terminal app
  Flagged   — no supporting record found; needs manual review
  Duplicate — detected as an exact duplicate of another transaction
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from zenfinance.data_store import load_all, save_all
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
CARD   = "#1A1D2E"

# All known terminal / merchant source names (display labels may differ from bank_name)
_TERMINAL_NAMES = set(TERMINAL_SOURCES) | {
    "Swiggy", "Zomato", "Blinkit", "Zepto",
    "BigBasket", "Amazon", "Swiggy Money",
    "Dunzo", "Instamart", "JioMart", "Ola", "Uber", "Rapido",
}

# All known intermediator source names
_INTERMEDIATOR_NAMES = set(INTERMEDIATOR_SOURCES) | {
    "PhonePe", "Google Pay", "GPay", "Paytm", "Amazon Pay", "BHIM",
}

# All audit ground-truth source names
_AUDIT_NAMES = set(AUDIT_SOURCES) | {"AXIO"}


def _classify_source(bank_name: str) -> str:
    """Return 'bank', 'intermediator', 'terminal', 'audit', or 'other'."""
    bn = str(bank_name).strip()
    if bn in _AUDIT_NAMES:
        return "audit"
    if bn in _TERMINAL_NAMES:
        return "terminal"
    if bn in _INTERMEDIATOR_NAMES:
        return "intermediator"
    if bn in set(BANK_SOURCES):
        return "bank"
    return "other"


def _run_audit(
    df: pd.DataFrame,
    date_tol: int = 1,
    amount_tol: float = 0.01,
) -> pd.DataFrame:
    """
    Full audit pass over the master transaction dataframe.

    Pass 1 — AXIO matching  (strongest: exact amount + date within tolerance)
    Pass 2 — Terminal app matching  (Swiggy, Zomato, Blinkit, Zepto …)
    Pass 3 — Intermediator enrichment  (PhonePe UTR lookup — enriches but
              does NOT set Audited)
    Pass 4 — Anything still Pending after all passes → Flagged
    """
    df = df.copy()
    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"]  = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)

    date_delta = pd.Timedelta(days=date_tol)

    # Segment dataframe by source classification
    bank_mask         = df["bank_name"].isin(BANK_SOURCES)
    audit_mask        = df["bank_name"].apply(lambda x: x in _AUDIT_NAMES)
    terminal_mask     = df["bank_name"].apply(lambda x: x in _TERMINAL_NAMES)
    intermediator_mask = df["bank_name"].apply(lambda x: x in _INTERMEDIATOR_NAMES)

    bank_df         = df[bank_mask].copy()
    audit_df        = df[audit_mask].copy()
    terminal_df     = df[terminal_mask].copy()
    intermediator_df = df[intermediator_mask].copy()

    # ── Pass 1: Match bank ↔ AXIO ─────────────────────────────────────────
    if not audit_df.empty:
        for b_idx, b_row in bank_df.iterrows():
            if df.loc[b_idx, "audit_status"] == "Audited":
                continue
            if pd.isna(b_row["date_dt"]):
                continue
            for _, a_row in audit_df.iterrows():
                if pd.isna(a_row["date_dt"]):
                    continue
                date_ok   = abs(b_row["date_dt"] - a_row["date_dt"]) <= date_delta
                amount_ok = abs(float(b_row["amount"]) - float(a_row["amount"])) <= amount_tol

                # Also try UTR match if available
                utr_ok = (
                    pd.notna(b_row.get("utr_number")) and
                    pd.notna(a_row.get("utr_number")) and
                    str(b_row["utr_number"]).split(".")[0].strip() ==
                    str(a_row["utr_number"]).split(".")[0].strip() and
                    str(b_row["utr_number"]).strip() != ""
                )

                if utr_ok or (date_ok and amount_ok):
                    df.loc[b_idx, "audit_status"]   = "Audited"
                    df.loc[b_idx, "system_comment"] = (
                        f"✅ Matched in AXIO — {a_row.get('bank_description','')[:60]}"
                    )
                    break

    # ── Pass 2: Match bank ↔ Terminal apps ────────────────────────────────
    if not terminal_df.empty:
        for b_idx, b_row in bank_df.iterrows():
            if df.loc[b_idx, "audit_status"] == "Audited":
                continue
            if pd.isna(b_row["date_dt"]):
                continue
            for _, t_row in terminal_df.iterrows():
                if pd.isna(t_row["date_dt"]):
                    continue
                date_ok   = abs(b_row["date_dt"] - t_row["date_dt"]) <= date_delta
                amount_ok = abs(float(b_row["amount"]) - float(t_row["amount"])) <= amount_tol

                if date_ok and amount_ok:
                    df.loc[b_idx, "audit_status"]   = "Audited"
                    df.loc[b_idx, "system_comment"] = (
                        f"✅ Matched in {t_row['bank_name']} — {t_row.get('bank_description','')[:50]}"
                    )
                    break

    # ── Pass 3: Intermediator enrichment (PhonePe / GPay / Paytm) ────────
    # PhonePe helps us find UTR numbers and payment methods, but does NOT
    # by itself confirm the merchant — so we ENRICH but don't mark Audited.
    if not intermediator_df.empty:
        for b_idx, b_row in bank_df.iterrows():
            if pd.isna(b_row["date_dt"]):
                continue
            for _, i_row in intermediator_df.iterrows():
                if pd.isna(i_row["date_dt"]):
                    continue

                utr_ok = (
                    pd.notna(b_row.get("utr_number")) and
                    pd.notna(i_row.get("utr_number")) and
                    str(b_row["utr_number"]).split(".")[0].strip() ==
                    str(i_row["utr_number"]).split(".")[0].strip() and
                    str(b_row["utr_number"]).strip() != ""
                )
                date_ok   = abs(b_row["date_dt"] - i_row["date_dt"]) <= date_delta
                amount_ok = abs(float(b_row["amount"]) - float(i_row["amount"])) <= amount_tol

                if utr_ok or (date_ok and amount_ok):
                    # Enrich: note the intermediator without changing audit_status
                    existing_comment = str(df.loc[b_idx, "system_comment"] or "")
                    intermediator    = i_row["bank_name"]
                    detail           = i_row.get("bank_description", "") or i_row.get("details", "")

                    if f"via {intermediator}" not in existing_comment:
                        enrichment = f"💳 Routed via {intermediator}"
                        if detail:
                            enrichment += f" — {str(detail)[:50]}"
                        df.loc[b_idx, "system_comment"] = (
                            (existing_comment + " | " + enrichment).strip(" | ")
                        )
                    break

    # ── Pass 4: Anything still Pending → Flagged ──────────────────────────
    still_pending = bank_mask & (df["audit_status"] == "Pending")
    df.loc[still_pending, "audit_status"]   = "Flagged"
    df.loc[still_pending, "system_comment"] = "⚠️ No matching AXIO or terminal-app record"

    df.drop(columns=["date_dt"], inplace=True, errors="ignore")
    return df


# ── Status badge HTML ──────────────────────────────────────────────────────

def _status_badge(status: str) -> str:
    colours = {
        "Audited":  (GREEN,  "✅"),
        "Flagged":  (RED,    "🚩"),
        "Pending":  (YELLOW, "⏳"),
        "Duplicate":(BLUE,   "🔄"),
    }
    col, icon = colours.get(status, ("#8888AA", "•"))
    return (
        f'<span style="background:{col}22;color:{col};border:1px solid {col}55;'
        f'border-radius:20px;padding:2px 10px;font-size:0.75rem;font-weight:600">'
        f'{icon} {status}</span>'
    )


def render():
    st.markdown("## 🔍 Cross-Source Audit")

    # ── Info banner ───────────────────────────────────────────────────────
    st.markdown(
        f"""
        <div style="background:#1A1D2E;border:1px solid #2A2D3E;border-radius:12px;
                    padding:14px 18px;margin-bottom:16px;font-size:0.88rem;line-height:1.8">
          <b style="color:#FAFAFA">How auditing works</b><br>
          A bank transaction is marked <b style="color:{GREEN}">Audited</b> only when it is found in:<br>
          &nbsp;&nbsp;• <b style="color:{GREEN}">AXIO</b> — your personal finance ledger (manual ground truth)<br>
          &nbsp;&nbsp;• A <b style="color:{BLUE}">terminal / merchant app</b>: Swiggy · Zomato · Blinkit · Zepto · BigBasket · Amazon …<br>
          <br>
          <b style="color:{YELLOW}">PhonePe · Google Pay · Paytm</b> are payment <i>intermediators</i> — they reveal the
          payment route but do not independently confirm the merchant, so they
          <i>enrich</i> transactions without marking them Audited.
        </div>
        """,
        unsafe_allow_html=True,
    )

    df = load_all()
    if df.empty:
        st.info("No transactions to audit yet — import data first.")
        return

    df["date"]   = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)

    # ── Source inventory ──────────────────────────────────────────────────
    st.markdown("### 📦 Data Sources Loaded")
    src_summary = df.groupby("bank_name").size().reset_index(name="txns")
    src_summary["Role"] = src_summary["bank_name"].apply(
        lambda x: {
            "audit": "🔍 Audit (AXIO)",
            "terminal": "🏪 Terminal App",
            "intermediator": "💳 Intermediator",
            "bank": "🏦 Bank",
        }.get(_classify_source(x), "📄 Other")
    )
    src_summary.columns = ["Source", "Transactions", "Role"]
    st.dataframe(src_summary, use_container_width=True, hide_index=True)

    # ── Audit settings ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### ⚙️ Audit Settings")
    s1, s2 = st.columns(2)
    date_tol   = s1.slider(
        "Date tolerance (days)", 0, 5, 1,
        help="Allow ±N days when matching transactions across sources",
    )
    amount_tol = s2.number_input(
        "Amount tolerance (₹)", 0.0, 100.0, 0.01, step=0.01,
        help="Allow small rounding differences in amounts",
    )

    # ── Current status overview ───────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📊 Current Audit Status")

    bank_df   = df[df["bank_name"].isin(BANK_SOURCES)]
    audit_src = df[df["bank_name"].apply(lambda x: x in _AUDIT_NAMES)]
    term_src  = df[df["bank_name"].apply(lambda x: x in _TERMINAL_NAMES)]
    inter_src = df[df["bank_name"].apply(lambda x: x in _INTERMEDIATOR_NAMES)]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Bank transactions",  len(bank_df))
    c2.metric("AXIO records",       len(audit_src))
    c3.metric("Terminal app txns",  len(term_src))
    c4.metric("Intermediator txns", len(inter_src))
    c5.metric(
        "Unresolved",
        int((df["audit_status"] == "Pending").sum()),
        delta_color="inverse",
    )

    # Status breakdown bar
    status_counts = df["audit_status"].value_counts()
    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("✅ Audited",   int(status_counts.get("Audited",   0)), delta_color="normal")
    sc2.metric("🚩 Flagged",   int(status_counts.get("Flagged",   0)), delta_color="inverse")
    sc3.metric("⏳ Pending",   int(status_counts.get("Pending",   0)), delta_color="off")
    sc4.metric("🔄 Duplicate", int(status_counts.get("Duplicate", 0)), delta_color="off")

    # ── Run audit button ──────────────────────────────────────────────────
    st.markdown("---")
    run_col, _ = st.columns([1, 3])
    if run_col.button("🚀 Run Audit Now", type="primary", use_container_width=True):
        if len(bank_df) == 0:
            st.warning(
                "No bank source transactions found. "
                "Import SBI / ICICI / HDFC data first."
            )
        elif len(audit_src) == 0 and len(term_src) == 0:
            st.warning(
                "No AXIO or terminal-app records found. "
                "Import AXIO, Swiggy, Zomato, Blinkit, or Zepto data to enable auditing."
            )
        else:
            with st.spinner("Running multi-source audit…"):
                updated_df = _run_audit(df, date_tol=date_tol, amount_tol=amount_tol)
                save_all(updated_df, reason="audit_run")

            audited  = int((updated_df["audit_status"] == "Audited").sum())
            flagged  = int((updated_df["audit_status"] == "Flagged").sum())
            pending  = int((updated_df["audit_status"] == "Pending").sum())
            st.success(
                f"✅ Audit complete — **{audited}** audited · "
                f"**{flagged}** flagged · **{pending}** pending"
            )
            # Reload page without st.rerun() to avoid sidebar collapse
            st.info("Scroll down to see updated results. Use the sidebar to navigate.")

    # ── Flagged transactions ──────────────────────────────────────────────
    st.markdown("---")
    flagged_df = df[df["audit_status"] == "Flagged"]
    if not flagged_df.empty:
        st.markdown(
            f'<h3>🚩 Flagged Transactions '
            f'<span style="color:{RED}">({len(flagged_df)})</span></h3>',
            unsafe_allow_html=True,
        )
        st.caption(
            "These bank transactions have no matching AXIO entry or terminal-app record. "
            "Review manually and resolve."
        )
        show_cols = ["date", "bank_name", "amount", "txn_type",
                     "bank_description", "payment_method", "system_comment"]
        view = flagged_df[[c for c in show_cols if c in flagged_df.columns]].copy()
        if "date" in view.columns:
            view["date"] = pd.to_datetime(view["date"]).dt.strftime("%d %b %Y")
        if "amount" in view.columns:
            view["amount"] = view["amount"].map(lambda x: f"₹{x:,.2f}")
        view.columns = [c.replace("_", " ").title() for c in view.columns]
        st.dataframe(view, use_container_width=True, hide_index=True,
                     height=min(400, 38 * len(view) + 50))

        if st.button("✅ Mark All Flagged as Manually Reviewed"):
            master = load_all()
            flagged_idx = master["audit_status"] == "Flagged"
            master.loc[flagged_idx, "audit_status"]   = "Audited"
            master.loc[flagged_idx, "system_comment"] = "✏️ Manually reviewed & approved"
            save_all(master, reason="resolve_flagged")
            st.success("All flagged transactions marked as reviewed.")
    else:
        st.success("🎉 No flagged transactions — everything is reconciled!")

    # ── Audited transactions ──────────────────────────────────────────────
    st.markdown("---")
    audited_df = df[df["audit_status"] == "Audited"]
    if not audited_df.empty:
        with st.expander(
            f"✅ Audited Transactions ({len(audited_df)})", expanded=False
        ):
            show_cols = ["date", "bank_name", "amount", "txn_type",
                         "bank_description", "payment_method", "system_comment"]
            view = audited_df[[c for c in show_cols if c in audited_df.columns]].copy()
            if "date" in view.columns:
                view["date"] = pd.to_datetime(view["date"]).dt.strftime("%d %b %Y")
            if "amount" in view.columns:
                view["amount"] = view["amount"].map(lambda x: f"₹{x:,.2f}")
            view.columns = [c.replace("_", " ").title() for c in view.columns]
            st.dataframe(view, use_container_width=True, hide_index=True,
                         height=min(400, 38 * len(view) + 50))

    # ── Intermediator-only records ────────────────────────────────────────
    inter_pending = df[
        df["bank_name"].apply(lambda x: x in _INTERMEDIATOR_NAMES)
        & (df["audit_status"] == "Pending")
    ]
    if not inter_pending.empty:
        st.markdown("---")
        with st.expander(
            f"💳 Unmatched Intermediator Transactions ({len(inter_pending)})"
        ):
            st.caption(
                "PhonePe / GPay / Paytm entries with no corresponding bank record "
                "(e.g. wallet-to-wallet transfers or cashback)."
            )
            show_cols = ["date", "bank_name", "amount", "txn_type",
                         "bank_description", "payment_method"]
            view = inter_pending[[c for c in show_cols if c in inter_pending.columns]].copy()
            if "date" in view.columns:
                view["date"] = pd.to_datetime(view["date"]).dt.strftime("%d %b %Y")
            if "amount" in view.columns:
                view["amount"] = view["amount"].map(lambda x: f"₹{x:,.2f}")
            view.columns = [c.replace("_", " ").title() for c in view.columns]
            st.dataframe(view, use_container_width=True, hide_index=True)

    # ── AXIO ↔ Terminal app coverage summary ──────────────────────────────
    if not audit_src.empty or not term_src.empty:
        st.markdown("---")
        with st.expander("📊 Audit Source Breakdown", expanded=False):
            col_a, col_b = st.columns(2)

            with col_a:
                st.markdown(f"**🔍 AXIO Records** ({len(audit_src)})")
                if not audit_src.empty:
                    axio_view = audit_src[["date", "amount", "bank_description"]].copy()
                    axio_view["date"] = pd.to_datetime(axio_view["date"]).dt.strftime("%d %b %Y")
                    axio_view["amount"] = axio_view["amount"].map(lambda x: f"₹{x:,.2f}")
                    axio_view.columns = ["Date", "Amount", "Description"]
                    st.dataframe(axio_view, use_container_width=True, hide_index=True, height=250)

            with col_b:
                st.markdown(f"**🏪 Terminal App Records** ({len(term_src)})")
                if not term_src.empty:
                    term_view = term_src[["date", "bank_name", "amount", "bank_description"]].copy()
                    term_view["date"] = pd.to_datetime(term_view["date"]).dt.strftime("%d %b %Y")
                    term_view["amount"] = term_view["amount"].map(lambda x: f"₹{x:,.2f}")
                    term_view.columns = ["Date", "App", "Amount", "Description"]
                    st.dataframe(term_view, use_container_width=True, hide_index=True, height=250)
