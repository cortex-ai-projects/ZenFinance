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

from zenfinance.categorization import get_all_categories
from zenfinance.data_store import load_all, save_all

# ── Colour palette ─────────────────────────────────
PALETTE   = ["#6C63FF", "#FF6584", "#43D9AD", "#FFB347", "#56CCF2", "#BB86FC",
             "#F72585", "#4CC9F0", "#4361EE", "#3A0CA3"]
CARD_BG   = "#1A1D2E"
TEXT_MAIN = "#FAFAFA"
RED       = "#FF6584"
GREEN     = "#43D9AD"
PURPLE    = "#6C63FF"
BLUE      = "#56CCF2"


def _plotly_defaults(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor ="rgba(0,0,0,0)",
        font=dict(color="#8E92B2", family="'Inter', sans-serif", size=11),
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#F3F4FD")),
    )
    fig.update_xaxes(gridcolor="rgba(255, 255, 255, 0.05)", showgrid=True, zeroline=False)
    fig.update_yaxes(gridcolor="rgba(255, 255, 255, 0.05)", showgrid=True, zeroline=False)
    return fig


# ── KPI Card ───────────────────────────────────────
def _kpi(col, label: str, value: str, delta: str = "", colour: str = PURPLE, icon: str = "📈"):
    badge_bg = f"{colour}15"
    col.markdown(
        f"""
        <div class="glass-card" style="border-left: 4px solid {colour}; margin-bottom: 12px; display: flex; flex-direction: column; justify-content: space-between; height: 100%;">
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span style="font-size: 0.72rem; color: #8E92B2; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase;">{label}</span>
              <span style="font-size: 1.25rem; background: {colour}15; padding: 6px; border-radius: 8px; line-height: 1; display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px;">{icon}</span>
            </div>
            <div style="font-size: 1.8rem; font-weight: 700; color: #FFFFFF; margin-top: 10px; font-family: 'Outfit', sans-serif; letter-spacing: -0.01em;">{value}</div>
          </div>
          {f'<div style="display: inline-flex; align-items: center; margin-top: 8px; font-size: 0.76rem; font-weight: 600; color: {colour}; background: {badge_bg}; padding: 2px 10px; border-radius: 12px; align-self: flex-start;">{delta}</div>' if delta else ''}
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


def render(df: pd.DataFrame, granularity: str = "Weekly"):
    if df.empty:
        st.info("📂 No transactions yet. Head over to **Import** to upload your first statement.")
        return

    # ── ensure date is proper ──
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["month"] = df["date"].dt.to_period("M").astype(str)

    is_investment = (df["category"] == "Finance") & (df["sub_category"].isin(["Mutual Funds", "Stocks", "FD", "PPF", "Savings/Transfer"]))
    
    credit = df[df["txn_type"] == "CREDIT"]["amount"].sum()
    debit  = df[(df["txn_type"] == "DEBIT") & (~is_investment)]["amount"].sum()
    invested = df[(df["txn_type"] == "DEBIT") & is_investment]["amount"].sum()
    net    = credit - debit - invested
    count  = len(df)

    # ── KPI row ──
    st.markdown("### 📊 Overview")
    c1, c2, c3, c4, c5 = st.columns(5)
    _kpi(c1, "Total Income",   _fmt_inr(credit), f"🟢 {len(df[df['txn_type']=='CREDIT'])} credits", GREEN, "💰")
    _kpi(c2, "Total Expenses", _fmt_inr(debit),  f"🔴 {len(df[(df['txn_type']=='DEBIT') & (~is_investment)])} debits", RED, "💸")
    _kpi(c3, "Investments",    _fmt_inr(invested), f"🛡️ {len(df[(df['txn_type']=='DEBIT') & is_investment])} transfers", BLUE, "💎")
    _kpi(c4, "Net Balance",    _fmt_inr(net),    "Income − Spend", GREEN if net >= 0 else RED, "⚖️")
    _kpi(c5, "Transactions",   str(count),        f"🏦 {df['bank_name'].nunique()} sources", PURPLE, "🧾")

    st.markdown("---")

    # ── Row 1: Dynamic Analytics Console (Combined Charts) ──
    st.markdown("### 📈 Dynamic Analytics Console")
    
    # Inline dropdown controls
    cc1, cc2, cc3 = st.columns(3)
    
    view_type = cc1.selectbox(
        "Analysis View",
        ["Spending Trend (Area)", "Income vs Expenses (Bar)", "Year-Over-Year (FY)"],
        index=0,
        key="analytics_view"
    )
    
    agg_type = cc2.selectbox(
        "Aggregation Metric",
        ["Total Sum (₹)", "Transaction Count", "Average Amount (₹)"],
        index=0,
        key="analytics_agg"
    )
    
    if view_type == "Year-Over-Year (FY)":
        cc3.selectbox("Granularity", ["N/A (Fiscal Year)"], disabled=True, key="analytics_gran")
        selected_gran = "Yearly"
    else:
        gran_options = ["Daily", "Weekly", "Monthly"]
        default_idx = gran_options.index(granularity) if granularity in gran_options else 1
        selected_gran = cc3.selectbox("Granularity", gran_options, index=default_idx, key="analytics_gran")

    # Map aggregation function and labeling
    agg_func = "sum"
    y_label = "Amount (₹)"
    if agg_type == "Transaction Count":
        agg_func = "count"
        y_label = "Count"
    elif agg_type == "Average Amount (₹)":
        agg_func = "mean"
        y_label = "Average (₹)"

    if view_type == "Spending Trend (Area)":
        # Filter DEBITs (excluding investments)
        df_spends = df[(df["txn_type"] == "DEBIT") & (~is_investment)].copy()
        
        if selected_gran == "Daily":
            df_spends["group_date"] = df_spends["date"].dt.date
            title_text = f"Daily Spending Trend ({agg_type})"
        elif selected_gran == "Weekly":
            df_spends["group_date"] = df_spends["date"].dt.to_period("W").dt.start_time
            title_text = f"Weekly Spending Trend ({agg_type})"
        else: # Monthly
            df_spends["group_date"] = df_spends["date"].dt.to_period("M").dt.start_time
            title_text = f"Monthly Spending Trend ({agg_type})"

        chart_data = (
            df_spends.groupby("group_date")["amount"]
            .agg(agg_func)
            .reset_index()
            .rename(columns={"group_date": "Date", "amount": "Value"})
        )

        st.markdown(f"#### {title_text}")
        if not chart_data.empty:
            fig_line = px.area(
                chart_data, x="Date", y="Value",
                color_discrete_sequence=[PURPLE],
                labels={"Value": y_label},
            )
            fig_line.update_traces(line_color=PURPLE, fillcolor="rgba(108,99,255,0.15)", line_width=2.5)
            _plotly_defaults(fig_line)
            st.plotly_chart(fig_line, use_container_width=True)
        else:
            st.caption("No spend data available for the selected filters.")

    elif view_type == "Income vs Expenses (Bar)":
        # Group both Income and Expenses (excluding investment debits)
        df_trends = df.copy()
        df_trends = df_trends[~((df_trends["txn_type"] == "DEBIT") & is_investment)]
        df_trends["Type"] = df_trends["txn_type"].map({"CREDIT": "Income", "DEBIT": "Expenses"})

        if selected_gran == "Daily":
            df_trends["group_date"] = df_trends["date"].dt.date
            title_text = f"Daily Income vs Expenses ({agg_type})"
        elif selected_gran == "Weekly":
            df_trends["group_date"] = df_trends["date"].dt.to_period("W").dt.start_time
            title_text = f"Weekly Income vs Expenses ({agg_type})"
        else: # Monthly
            df_trends["group_date"] = df_trends["date"].dt.to_period("M").dt.start_time
            title_text = f"Monthly Income vs Expenses ({agg_type})"

        chart_data = (
            df_trends.groupby(["group_date", "Type"])["amount"]
            .agg(agg_func)
            .reset_index()
            .rename(columns={"group_date": "Date", "amount": "Value"})
        )

        st.markdown(f"#### {title_text}")
        if not chart_data.empty:
            fig_bar = px.bar(
                chart_data, x="Date", y="Value", color="Type",
                barmode="group",
                color_discrete_map={"Income": GREEN, "Expenses": RED},
                labels={"Value": y_label},
            )
            _plotly_defaults(fig_bar)
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.caption("No trend data available for the selected filters.")

    else: # Year-Over-Year (FY)
        df["fy"] = df["date"].apply(
            lambda d: f"FY{str(d.year + 1)[-2:]}" if pd.notna(d) and d.month >= 4 else f"FY{str(d.year)[-2:]}" if pd.notna(d) else "Unknown"
        )
        df_fy = df[df["fy"] != "Unknown"].copy()
        df_fy = df_fy[~((df_fy["txn_type"] == "DEBIT") & is_investment)]
        df_fy["Type"] = df_fy["txn_type"].map({"CREDIT": "Income", "DEBIT": "Expenses"})

        chart_data = (
            df_fy.groupby(["fy", "Type"])["amount"]
            .agg(agg_func)
            .reset_index()
            .rename(columns={"fy": "Fiscal Year", "amount": "Value"})
            .sort_values(by="Fiscal Year")
        )

        st.markdown(f"#### ⚖️ Year-Over-Year (FY) Comparison ({agg_type})")
        if not chart_data.empty:
            fig_fy = px.bar(
                chart_data, x="Fiscal Year", y="Value", color="Type",
                barmode="group",
                color_discrete_map={"Income": GREEN, "Expenses": RED},
                labels={"Value": y_label},
            )
            _plotly_defaults(fig_fy)
            st.plotly_chart(fig_fy, use_container_width=True)
        else:
            st.caption("No fiscal year data available.")

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
            st.plotly_chart(fig_v, width="stretch")
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
            st.plotly_chart(fig_pm, width="stretch")
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
        st.plotly_chart(fig_src, width="stretch")

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
        st.plotly_chart(fig_s, width="stretch")

    # ── Interactive Review Data Editor ──
    st.markdown("---")
    st.markdown("### 📝 Needs Review")
    st.caption("These are your largest uncategorized or flagged transactions. Resolve them right here!")
    
    review_mask = (df["category"].isna()) | (df["category"] == "Uncategorized") | (df["category"] == "") | (df["audit_status"] == "Flagged")
    review_df = df[review_mask & (df["txn_type"] == "DEBIT")].sort_values("amount", ascending=False).head(15).copy()
    
    if not review_df.empty:
        # We need a clean view for editing
        view = review_df[["id", "date", "bank_name", "amount", "bank_description", "category", "tags"]].copy()
        if "date" in view.columns:
            view["date"] = pd.to_datetime(view["date"]).dt.strftime("%d %b %Y")
            
        edited_df = st.data_editor(
            view,
            disabled=["id", "date", "bank_name", "amount", "bank_description"],
            column_config={
                "id": None, # Hide column entirely
                "date": st.column_config.TextColumn("Date"),
                "bank_name": st.column_config.TextColumn("Bank"),
                "amount": st.column_config.NumberColumn("Amount (₹)", format="₹%d"),
                "bank_description": st.column_config.TextColumn("Description"),
                "category": st.column_config.SelectboxColumn("Category", options=get_all_categories()),
                "tags": st.column_config.TextColumn("Tags (CSV)"),
            },
            hide_index=True,
            use_container_width=True,
            key="dashboard_editor"
        )
        if st.button("💾 Save Review Updates", type="primary"):
            master = load_all()
            changes = 0
            for idx, row in edited_df.iterrows():
                mask = master["id"] == row["id"]
                if not mask.any(): continue
                curr_cat = str(master.loc[mask, "category"].iloc[0])
                curr_tag = str(master.loc[mask, "tags"].iloc[0])
                new_cat = str(row["category"])
                new_tag = str(row["tags"])
                
                # Coerce strict types avoiding nan strings
                new_cat = new_cat if new_cat not in ["nan", "None", ""] else "Uncategorized"
                new_tag = new_tag if new_tag not in ["nan", "None"] else ""
                
                if (curr_cat != new_cat) or (curr_tag != new_tag):
                    master.loc[mask, "category"] = new_cat
                    master.loc[mask, "tags"] = new_tag
                    changes += 1
            if changes > 0:
                save_all(master, reason="dashboard_quick_edit")
                st.success(f"✅ Saved {changes} transaction changes.")
                # We do not use rerun since user can hit another button or refresh dashboard directly.
    else:
        st.success("🎉 All good! No major transactions pending review.")
