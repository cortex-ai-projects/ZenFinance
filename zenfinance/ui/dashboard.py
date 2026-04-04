"""
ZenFinance — Dashboard UI
Plotly charts: KPI cards, spending timeline, category donut, monthly trends.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Colour palette ─────────────────────────────────
PALETTE   = ["#6C63FF", "#FF6584", "#43D9AD", "#FFB347", "#56CCF2", "#BB86FC",
             "#F72585", "#4CC9F0", "#4361EE", "#3A0CA3"]
CARD_BG   = "#1A1D2E"
TEXT_MAIN = "#FAFAFA"
RED       = "#FF6584"
GREEN     = "#43D9AD"
PURPLE    = "#6C63FF"


def _plotly_defaults(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor ="rgba(0,0,0,0)",
        font=dict(color=TEXT_MAIN, family="sans-serif"),
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor="#2A2D3E", showgrid=True)
    fig.update_yaxes(gridcolor="#2A2D3E", showgrid=True)
    return fig


# ── KPI Card ───────────────────────────────────────
def _kpi(col, label: str, value: str, delta: str = "", colour: str = PURPLE):
    col.markdown(
        f"""
        <div style="background:{CARD_BG};border-radius:12px;padding:18px 22px;
                    border-left:4px solid {colour};margin-bottom:6px">
          <div style="font-size:0.75rem;color:#aaa;letter-spacing:.08em;text-transform:uppercase">{label}</div>
          <div style="font-size:1.6rem;font-weight:700;color:{TEXT_MAIN};margin-top:4px">{value}</div>
          <div style="font-size:0.8rem;color:{colour};margin-top:2px">{delta}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _fmt_inr(val: float) -> str:
    if abs(val) >= 1e7:
        return f"₹{val/1e7:.2f} Cr"
    if abs(val) >= 1e5:
        return f"₹{val/1e5:.2f} L"
    return f"₹{val:,.0f}"


def render(df: pd.DataFrame):
    if df.empty:
        st.info("📂 No transactions yet. Head over to **Import** to upload your first statement.")
        return

    # ── ensure date is proper ──
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["month"] = df["date"].dt.to_period("M").astype(str)

    credit = df[df["txn_type"] == "CREDIT"]["amount"].sum()
    debit  = df[df["txn_type"] == "DEBIT"]["amount"].sum()
    net    = credit - debit
    count  = len(df)

    # ── KPI row ──
    st.markdown("### 📊 Overview")
    c1, c2, c3, c4 = st.columns(4)
    _kpi(c1, "Total Income",   _fmt_inr(credit), f"{len(df[df['txn_type']=='CREDIT'])} credits", GREEN)
    _kpi(c2, "Total Expenses", _fmt_inr(debit),  f"{len(df[df['txn_type']=='DEBIT'])} debits",   RED)
    _kpi(c3, "Net Balance",    _fmt_inr(net),    "income − expenses",                            GREEN if net >= 0 else RED)
    _kpi(c4, "Transactions",   str(count),        f"{df['bank_name'].nunique()} sources",         PURPLE)

    st.markdown("---")

    # ── Row 1: Spending over time + Category Donut ──
    col_l, col_r = st.columns([3, 2], gap="medium")

    with col_l:
        st.markdown("#### 📈 Daily Spending Over Time")
        daily = (
            df[df["txn_type"] == "DEBIT"]
            .groupby(df["date"].dt.date)["amount"]
            .sum()
            .reset_index()
            .rename(columns={"date": "Date", "amount": "Amount"})
        )
        if not daily.empty:
            fig_line = px.area(
                daily, x="Date", y="Amount",
                color_discrete_sequence=[PURPLE],
                labels={"Amount": "Spent (₹)"},
            )
            fig_line.update_traces(line_color=PURPLE, fillcolor="rgba(108,99,255,0.15)")
            _plotly_defaults(fig_line)
            st.plotly_chart(fig_line, use_container_width=True)
        else:
            st.caption("No debit data available.")

    with col_r:
        st.markdown("#### 🍩 Category Breakdown")
        cat_df = (
            df[df["txn_type"] == "DEBIT"]
            .groupby("category")["amount"]
            .sum()
            .reset_index()
            .rename(columns={"category": "Category", "amount": "Amount"})
            .sort_values("Amount", ascending=False)
        )
        if not cat_df.empty:
            fig_donut = px.pie(
                cat_df, values="Amount", names="Category",
                hole=0.55,
                color_discrete_sequence=PALETTE,
            )
            fig_donut.update_traces(
                textposition="outside",
                textfont_size=11,
                marker=dict(line=dict(color="#0E1117", width=2)),
            )
            _plotly_defaults(fig_donut)
            fig_donut.update_layout(showlegend=True, legend=dict(orientation="v", x=1.02))
            st.plotly_chart(fig_donut, use_container_width=True)
        else:
            st.caption("No debit data available.")

    # ── Row 2: Monthly Trends (grouped bar) ──
    st.markdown("#### 📅 Monthly Income vs Expenses")
    monthly = (
        df.groupby(["month", "txn_type"])["amount"]
        .sum()
        .reset_index()
        .pivot(index="month", columns="txn_type", values="amount")
        .fillna(0)
        .reset_index()
    )
    if not monthly.empty:
        fig_bar = go.Figure()
        if "CREDIT" in monthly.columns:
            fig_bar.add_trace(go.Bar(
                x=monthly["month"], y=monthly["CREDIT"],
                name="Income", marker_color=GREEN, opacity=0.85,
            ))
        if "DEBIT" in monthly.columns:
            fig_bar.add_trace(go.Bar(
                x=monthly["month"], y=monthly["DEBIT"],
                name="Expenses", marker_color=RED, opacity=0.85,
            ))
        fig_bar.update_layout(barmode="group", xaxis_tickangle=-30)
        _plotly_defaults(fig_bar)
        st.plotly_chart(fig_bar, use_container_width=True)

    # ── Row 3: Top Vendors + Payment Methods ──
    col_a, col_b = st.columns(2, gap="medium")

    with col_a:
        st.markdown("#### 🏪 Top Spending Vendors")
        top_v = (
            df[df["txn_type"] == "DEBIT"]
            .groupby("details")["amount"]
            .sum()
            .dropna()
            .nlargest(10)
            .reset_index()
            .rename(columns={"details": "Vendor", "amount": "Amount"})
        )
        top_v["Vendor"] = top_v["Vendor"].astype(str).str[:40]
        if not top_v.empty:
            fig_v = px.bar(
                top_v.sort_values("Amount"), x="Amount", y="Vendor",
                orientation="h", color="Amount",
                color_continuous_scale=[[0, "#3A0CA3"], [1, "#6C63FF"]],
            )
            fig_v.update_layout(coloraxis_showscale=False)
            _plotly_defaults(fig_v)
            st.plotly_chart(fig_v, use_container_width=True)
        else:
            st.caption("No vendor data.")

    with col_b:
        st.markdown("#### 💳 Payment Methods")
        pm_df = (
            df.groupby("payment_method")["amount"]
            .sum()
            .reset_index()
            .rename(columns={"payment_method": "Method", "amount": "Amount"})
            .dropna(subset=["Method"])
        )
        pm_df = pm_df[pm_df["Method"].astype(str).str.strip().str.len() > 0]
        if not pm_df.empty:
            fig_pm = px.pie(
                pm_df, values="Amount", names="Method",
                color_discrete_sequence=PALETTE,
            )
            _plotly_defaults(fig_pm)
            st.plotly_chart(fig_pm, use_container_width=True)
        else:
            st.caption("No payment method data.")

    # ── Row 4: Source breakdown ──
    st.markdown("#### 🏦 Transactions by Source")
    src_df = (
        df.groupby(["bank_name", "txn_type"])["amount"]
        .sum()
        .reset_index()
    )
    if not src_df.empty:
        fig_src = px.bar(
            src_df, x="bank_name", y="amount", color="txn_type",
            barmode="group",
            color_discrete_map={"CREDIT": GREEN, "DEBIT": RED},
            labels={"bank_name": "Source", "amount": "Amount (₹)", "txn_type": "Type"},
        )
        _plotly_defaults(fig_src)
        st.plotly_chart(fig_src, use_container_width=True)

    # ── Audit status summary ──
    st.markdown("#### ✅ Audit Status Summary")
    status_df = df["audit_status"].value_counts().reset_index()
    status_df.columns = ["Status", "Count"]
    colour_map = {"Pending": "#FFB347", "Audited": GREEN, "Flagged": RED, "Duplicate": "#BB86FC"}
    if not status_df.empty:
        fig_s = px.bar(
            status_df, x="Status", y="Count",
            color="Status",
            color_discrete_map=colour_map,
        )
        fig_s.update_layout(showlegend=False)
        _plotly_defaults(fig_s)
        st.plotly_chart(fig_s, use_container_width=True)
