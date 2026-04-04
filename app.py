"""
ZenFinance — Main Streamlit App
Run: streamlit run app.py
"""
from __future__ import annotations

from datetime import date, timedelta
import time

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ZenFinance",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Hide default chrome */
#MainMenu, footer, header { visibility: hidden; }

/* App background */
.stApp { background-color: #0E1117; }
.block-container { padding-top: 1.2rem; max-width: 1400px; }

/* Sidebar always dark */
[data-testid="stSidebar"] {
    background: #13151f !important;
    border-right: 1px solid #2A2D3E;
}
[data-testid="stSidebar"] > div:first-child { padding-top: 1rem; }

/* Sidebar collapse button — always keep it accessible */
[data-testid="collapsedControl"] {
    background: #13151f !important;
    border-right: 1px solid #2A2D3E !important;
    color: #6C63FF !important;
}

/* Radio nav pills */
div[data-testid="stSidebar"] .stRadio > div {
    gap: 4px;
}
div[data-testid="stSidebar"] .stRadio label {
    background: transparent;
    border-radius: 8px;
    padding: 8px 14px !important;
    font-size: 0.92rem !important;
    color: #CCCCDD !important;
    cursor: pointer;
    transition: background .15s;
    width: 100%;
    display: block;
}
div[data-testid="stSidebar"] .stRadio label:hover {
    background: rgba(108,99,255,0.15) !important;
    color: #6C63FF !important;
}
div[data-testid="stSidebar"] .stRadio label[data-baseweb="radio"]:has(input:checked) {
    background: rgba(108,99,255,0.22) !important;
    color: #6C63FF !important;
    font-weight: 600 !important;
}
/* Hide radio circle dots */
div[data-testid="stSidebar"] .stRadio [data-baseweb="radio"] div:first-child {
    display: none;
}

/* Metric cards */
[data-testid="metric-container"] {
    background: #1A1D2E;
    border: 1px solid #2A2D3E;
    border-radius: 12px;
    padding: 14px 18px;
}

/* Buttons */
.stButton button[kind="primary"] {
    background: linear-gradient(135deg,#6C63FF,#9B59B6);
    border: none; border-radius: 8px; font-weight: 600;
}
.stButton button[kind="primary"]:hover { opacity: .88; }

/* Tables */
.stDataFrame { border: 1px solid #2A2D3E; border-radius: 10px; overflow: hidden; }

/* Tabs */
[data-testid="stTabs"] [role="tab"] { color: #8888AA; }
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #6C63FF; border-bottom: 2px solid #6C63FF;
}

/* Expander */
details summary { color: #6C63FF; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #0E1117; }
::-webkit-scrollbar-thumb { background: #2A2D3E; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #6C63FF; }

/* Inputs */
.stTextInput input, .stNumberInput input, .stDateInput input {
    background: #1A1D2E; border: 1px solid #2A2D3E;
    color: #FAFAFA; border-radius: 8px;
}
div[data-baseweb="select"] { background: #1A1D2E !important; }

/* Info / success / warning boxes */
.stAlert { border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

# ── Auto-refresh every 5 minutes (300 000 ms) ──────────────────────────────
components.html(
    '<script>'
    'setTimeout(function(){ window.location.reload(); }, 300000);'
    '</script>',
    height=0,
)

# ── Lazy page imports ──────────────────────────────────────────────────────
from zenfinance.data_store import load_all
from zenfinance.ui import dashboard, upload, transactions, audit, settings

# ── Nav mapping ───────────────────────────────────────────────────────────
NAV_OPTIONS = [
    "📊  Dashboard",
    "📥  Import Data",
    "💳  Transactions",
    "🔍  Audit",
    "⚙️  Settings",
]
NAV_KEYS = {
    "📊  Dashboard":    "dashboard",
    "📥  Import Data":  "import",
    "💳  Transactions": "transactions",
    "🔍  Audit":        "audit",
    "⚙️  Settings":     "settings",
}

# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    # Logo
    st.markdown("""
    <div style="display:flex;align-items:center;gap:10px;padding:4px 0 20px 4px">
      <div style="font-size:2rem;line-height:1">💰</div>
      <div>
        <div style="font-size:1.2rem;font-weight:700;color:#FAFAFA;line-height:1.2">ZenFinance</div>
        <div style="font-size:0.65rem;color:#6C63FF;letter-spacing:.1em;text-transform:uppercase">
          Personal Finance Audit
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div style="font-size:.7rem;color:#555;letter-spacing:.1em;text-transform:uppercase;padding:0 4px 6px">NAVIGATION</div>', unsafe_allow_html=True)

    # ── st.radio nav — NO st.rerun() needed, sidebar stays stable ──────────
    selected_nav = st.radio(
        "nav",
        NAV_OPTIONS,
        index=0,
        key="nav_radio",
        label_visibility="collapsed",
    )
    page = NAV_KEYS[selected_nav]

    st.markdown("---")

    # ── Global filters ─────────────────────────────────────────────────────
    df_all = load_all()

    st.markdown('<div style="font-size:.7rem;color:#555;letter-spacing:.1em;text-transform:uppercase;padding:0 4px 6px">FILTERS</div>', unsafe_allow_html=True)

    if not df_all.empty:
        df_all["date"] = pd.to_datetime(df_all["date"], errors="coerce")
        sources = ["All"] + sorted(df_all["bank_name"].dropna().unique().tolist())
        filter_source = st.selectbox("Source", sources, key="sb_source")

        min_d = df_all["date"].min().date() if not df_all["date"].isna().all() else date(2020, 1, 1)
        max_d = df_all["date"].max().date() if not df_all["date"].isna().all() else date.today()
        date_from = st.date_input("From", value=min_d, min_value=min_d, max_value=max_d, key="sb_from")
        date_to   = st.date_input("To",   value=max_d, min_value=min_d, max_value=max_d, key="sb_to")
    else:
        filter_source = "All"
        date_from = date.today() - timedelta(days=365)
        date_to   = date.today()
        st.caption("Import data to enable filters.")

    st.markdown("---")

    # ── Mini stats ─────────────────────────────────────────────────────────
    if not df_all.empty:
        total   = len(df_all)
        pending = int((df_all["audit_status"] == "Pending").sum())
        audited = int((df_all["audit_status"] == "Audited").sum())
        st.markdown(f"""
        <div style="font-size:.8rem;color:#aaa;line-height:2">
          🗄️ &nbsp;<b style="color:#FAFAFA">{total}</b> transactions<br>
          ✅ &nbsp;<b style="color:#43D9AD">{audited}</b> audited<br>
          ⏳ &nbsp;<b style="color:#FFB347">{pending}</b> pending review
        </div>
        """, unsafe_allow_html=True)

    # ── Auto-refresh indicator ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("""
    <div style="font-size:.68rem;color:#444;text-align:center">
      🔄 Auto-refreshes every 5 min
    </div>
    """, unsafe_allow_html=True)

# ── Apply sidebar filters to dataframe ────────────────────────────────────
def _filtered_df() -> pd.DataFrame:
    df = load_all()
    if df.empty:
        return df
    df["date"]   = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    if filter_source and filter_source != "All":
        df = df[df["bank_name"] == filter_source]
    if date_from:
        df = df[df["date"].dt.date >= date_from]
    if date_to:
        df = df[df["date"].dt.date <= date_to]
    return df

# ── Page router ────────────────────────────────────────────────────────────
if page == "dashboard":
    dashboard.render(_filtered_df())

elif page == "import":
    upload.render()

elif page == "transactions":
    transactions.render(
        filter_source=filter_source,
        date_from=date_from,
        date_to=date_to,
    )

elif page == "audit":
    audit.render()

elif page == "settings":
    settings.render()
