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

import uuid
def _link_money_trails(df: pd.DataFrame, days_tolerance: int = 2) -> pd.DataFrame:
    """Matches DEBITs from Bank A to CREDITs in Bank B within ±tolerance days forming a money_trail."""
    df = df.copy()
    if "money_trail_id" not in df.columns:
        df["money_trail_id"] = None
        
    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce")
    bank_only = df[df["bank_name"].isin(BANK_SOURCES)].copy()
    
    debits = bank_only[(bank_only["txn_type"] == "DEBIT") & (bank_only["money_trail_id"].isna())].copy()
    credits = bank_only[(bank_only["txn_type"] == "CREDIT") & (bank_only["money_trail_id"].isna())].copy()
    
    td = pd.Timedelta(days=days_tolerance)
    for d_idx, d_row in debits.iterrows():
        if pd.isna(d_row["date_dt"]): continue
        
        # find matching credit
        c_mask = (
            (credits["bank_name"] != d_row["bank_name"]) &
            (abs(credits["date_dt"] - d_row["date_dt"]) <= td) & 
            (abs(credits["amount"].astype(float) - float(d_row["amount"])) < 1.0) &
            (credits["money_trail_id"].isna())
        )
        matches = credits[c_mask]
        if not matches.empty:
            match_idx = matches.index[0]
            trail_id = str(uuid.uuid4())[:8]
            df.loc[d_idx, "money_trail_id"] = trail_id
            df.loc[d_idx, "system_comment"] = f"🔗 Trail {trail_id} → {df.loc[match_idx, 'bank_name']}"
            df.loc[match_idx, "money_trail_id"] = trail_id
            df.loc[match_idx, "system_comment"] = f"🔗 Trail {trail_id} ← {d_row['bank_name']}"
            df.loc[d_idx, "category"] = "Finance"
            df.loc[d_idx, "sub_category"] = "Savings/Transfer"
            df.loc[match_idx, "category"] = "Finance"
            df.loc[match_idx, "sub_category"] = "Savings/Transfer"
            
            credits.loc[match_idx, "money_trail_id"] = trail_id # mark used

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
        f'<span style="background:{col}15;color:{col};border:1px solid {col}35;'
        f'border-radius:12px;padding:4px 12px;font-size:0.75rem;font-weight:600;'
        f'backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)">'
        f'{icon} {status}</span>'
    )


def render():
    st.markdown("## 🔍 Cross-Source Audit")

    # ── Info banner ───────────────────────────────────────────────────────
    st.markdown(
        f"""
        <div class="glass-card" style="margin-bottom:16px;font-size:0.88rem;line-height:1.8">
          <b style="color:#FFFFFF; font-family:'Outfit',sans-serif; font-size:1.05rem;">How Auditing Works</b><br>
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
    st.dataframe(src_summary, width="stretch", hide_index=True)

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
    if run_col.button("🚀 Run Audit Now", type="primary", width="stretch"):
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
            with st.spinner("Running multi-source audit & tracing Money Trails…"):
                updated_df = _run_audit(df, date_tol=date_tol, amount_tol=amount_tol)
                updated_df = _link_money_trails(updated_df, days_tolerance=2)
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
            f'<h3>🚩 Conflicts & Flagged Transactions '
            f'<span style="color:{RED}">({len(flagged_df)})</span></h3>',
            unsafe_allow_html=True,
        )
        st.caption("Transactions lacking a matching origin. Resolve them by importing missing sources or overriding manually.")
        
        tab_term, tab_axio, tab_raw = st.tabs(["🛒 Missing Terminal Origins", "🧾 Missing AXIO Match", "⚠️ Raw Conflicts"])
        
        def _render_flag_tab(flg_df):
            if flg_df.empty:
                st.success("Clean! No conflicts here.")
                return
            show_cols = ["date", "bank_name", "amount", "txn_type", "bank_description", "payment_method", "system_comment"]
            view = flg_df[[c for c in show_cols if c in flg_df.columns]].copy()
            if "date" in view.columns: view["date"] = pd.to_datetime(view["date"]).dt.strftime("%d %b")
            if "amount" in view.columns: view["amount"] = view["amount"].map(lambda x: f"₹{x:,.0f}")
            view.columns = [c.replace("_", " ").title() for c in view.columns]
            st.dataframe(view, width="stretch", hide_index=True)
            
        with tab_term:
            # Suspect it's a missing terminal app because it was routed via UPI/Cards
            is_upi = flagged_df["bank_description"].str.contains("UPI|Zomato|Swiggy|Blinkit|Amazon", case=False, na=False)
            _render_flag_tab(flagged_df[is_upi])
            
        with tab_axio:
            # Standard debits missing AXIO entries
            _render_flag_tab(flagged_df[~is_upi & (flagged_df["txn_type"] == "DEBIT")])
            
        with tab_raw:
            # Everything else (Credits mostly)
            _render_flag_tab(flagged_df[~is_upi & (flagged_df["txn_type"] == "CREDIT")])

        if st.button("✅ Mark All Flagged as Manually Reviewed", type="secondary"):
            master = load_all()
            flagged_idx = master["audit_status"] == "Flagged"
            master.loc[flagged_idx, "audit_status"]   = "Audited"
            master.loc[flagged_idx, "system_comment"] = "✏️ Manually reviewed & approved"
            save_all(master, reason="resolve_flagged")
            st.success("All flagged transactions marked as reviewed.")
            st.rerun()
    else:
        st.success("🎉 No flagged transactions — everything is reconciled!")

    # ── Audited transactions ──────────────────────────────────────────────
    st.markdown("---")
    audited_df = df[df["audit_status"] == "Audited"]
    if not audited_df.empty:
        st.markdown(f"### ✅ Audited Transactions ({len(audited_df)})")
        
        tab_data, tab_flow = st.tabs(["📋 Data View", "🌊 Flow Graph"])
        
        with tab_data:
            show_cols = ["date", "bank_name", "amount", "txn_type",
                         "bank_description", "payment_method", "system_comment"]
            view = audited_df[[c for c in show_cols if c in audited_df.columns]].copy()
            if "date" in view.columns:
                view["date"] = pd.to_datetime(view["date"]).dt.strftime("%d %b %Y")
            if "amount" in view.columns:
                view["amount"] = view["amount"].map(lambda x: f"₹{x:,.2f}")
            view.columns = [c.replace("_", " ").title() for c in view.columns]
            st.dataframe(view, width="stretch", hide_index=True,
                         height=min(400, 38 * len(view) + 50))
                         
        with tab_flow:
            st.caption("Visualizing the cross-app match flow: Source Bank → Payment Method → Auditing Tool Origin")
            flows = []
            for _, r in audited_df.iterrows():
                bank = str(r.get("bank_name", "Unknown Bank"))
                pm = str(r.get("payment_method", ""))
                comment = str(r.get("system_comment", ""))
                
                # Extract payment method / intermediator
                if "Routed via " in comment:
                    route_part = comment.split("Routed via ")[1].split(" — ")[0]
                    pm_node = route_part.strip()
                elif pm.strip() not in ["", "nan", "None"]:
                    pm_node = pm.strip()
                else:
                    pm_node = "Direct / Card"
                    
                # Extract Match Origin
                if "Matched in " in comment:
                    origin_part = comment.split("Matched in ")[1].split(" — ")[0]
                    origin_node = origin_part.strip()
                else:
                    origin_node = "Manual Review"
                    
                # Append links
                flows.append({"source": f"Bank: {bank}", "target": f"Method: {pm_node}", "value": 1})
                flows.append({"source": f"Method: {pm_node}", "target": f"Match: {origin_node}", "value": 1})

            import plotly.graph_objects as go
            flow_df = pd.DataFrame(flows).groupby(["source", "target"]).sum().reset_index()
            
            if not flow_df.empty:
                all_nodes = list(set(flow_df["source"]).union(set(flow_df["target"])))
                node_indices = {n: i for i, n in enumerate(all_nodes)}
                
                source_indices = [node_indices[src] for src in flow_df["source"]]
                target_indices = [node_indices[tgt] for tgt in flow_df["target"]]
                
                fig_sankey = go.Figure(data=[go.Sankey(
                    node = dict(
                      pad = 25,
                      thickness = 25,
                      line = dict(color = "#1A1D2E", width = 1.5),
                      label = [n.split(": ", 1)[-1] for n in all_nodes],
                      color = ["#6C63FF" if n.startswith("Bank:") else "#4CC9F0" if n.startswith("Method:") else "#43D9AD" for n in all_nodes]
                    ),
                    link = dict(
                      source = source_indices,
                      target = target_indices,
                      value = flow_df["value"],
                      color = "rgba(108, 99, 255, 0.25)"
                    )
                )])
                fig_sankey.update_layout(
                    font_size=12, 
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#8E92B2", family="'Inter', sans-serif"),
                    margin=dict(t=20, b=20, l=10, r=10),
                    height=450
                )
                st.plotly_chart(fig_sankey, use_container_width=True)
            else:
                st.info("Not enough data elements resolved to generate flow visualization.")

    # ── Money Trails ──────────────────────────────────────────────────────
    if "money_trail_id" in df.columns:
        trails_df = df[df["money_trail_id"].notna()]
        if not trails_df.empty:
            st.markdown("---")
            with st.expander(f"🔗 Detected Money Trails ({trails_df['money_trail_id'].nunique()} paths)"):
                st.caption("Temporal matching engine detected the following logical fund transfers across your bank accounts.")
                trail_view = trails_df[["date", "money_trail_id", "bank_name", "txn_type", "amount", "system_comment"]].copy()
                trail_view.sort_values(by=["money_trail_id", "date"], inplace=True)
                if "date" in trail_view.columns:
                    trail_view["date"] = pd.to_datetime(trail_view["date"]).dt.strftime("%d %b %Y")
                
                # Apply custom styler to highlight the trail flows
                st.dataframe(trail_view, width="stretch", hide_index=True)

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
            st.dataframe(view, width="stretch", hide_index=True)

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
                    st.dataframe(axio_view, width="stretch", hide_index=True, height=250)

            with col_b:
                st.markdown(f"**🏪 Terminal App Records** ({len(term_src)})")
                if not term_src.empty:
                    term_view = term_src[["date", "bank_name", "amount", "bank_description"]].copy()
                    term_view["date"] = pd.to_datetime(term_view["date"]).dt.strftime("%d %b %Y")
                    term_view["amount"] = term_view["amount"].map(lambda x: f"₹{x:,.2f}")
                    term_view.columns = ["Date", "App", "Amount", "Description"]
                    st.dataframe(term_view, width="stretch", hide_index=True, height=250)
