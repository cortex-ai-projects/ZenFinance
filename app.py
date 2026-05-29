"""
ZenFinance — Main Streamlit App
Run: streamlit run app.py
"""
from __future__ import annotations

# ── SSL Monkey Patch for Python 3.14/OpenSSL unexpected EOF ────────────────
import ssl
try:
    orig_create_default_context = ssl.create_default_context
    def patched_create_default_context(*args, **kwargs):
        ctx = orig_create_default_context(*args, **kwargs)
        try:
            ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
        except AttributeError:
            pass
        return ctx
    ssl.create_default_context = patched_create_default_context
except Exception:
    pass

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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800&display=swap');

/* Hide default Streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }

/* Global App Styling with radial glows */
.stApp {
    background: 
        radial-gradient(circle at 8% 12%, rgba(108, 99, 255, 0.14) 0%, transparent 45%),
        radial-gradient(circle at 92% 85%, rgba(247, 37, 133, 0.12) 0%, transparent 45%),
        radial-gradient(circle at 50% 50%, rgba(67, 217, 173, 0.07) 0%, transparent 50%),
        #0b0c10 !important;
    background-attachment: fixed !important;
    color: #F3F4FD !important;
    font-family: 'Inter', -apple-system, sans-serif !important;
}

/* Container spacing */
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
    max-width: 1440px;
}

/* Headers */
h1, h2, h3, h4, h5, h6 {
    font-family: 'Outfit', sans-serif !important;
    font-weight: 700 !important;
    color: #FFFFFF !important;
    letter-spacing: -0.02em !important;
}

/* Glassmorphism sidebar positioned properly from top */
section[data-testid="stSidebar"] {
    background: rgba(11, 13, 22, 0.6) !important;
    backdrop-filter: blur(30px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(30px) saturate(180%) !important;
    border-right: 1px solid rgba(255, 255, 255, 0.05) !important;
}
section[data-testid="stSidebar"] > div {
    background-color: transparent !important;
    padding-top: 0 !important;
}
div[data-testid="stSidebarUserContent"], section[data-testid="stSidebar"] .block-container {
    background-color: transparent !important;
    padding-top: 0 !important; /* Proper placement from top */
}

/* Sidebar collapse button */
[data-testid="collapsedControl"] {
    background: rgba(11, 13, 22, 0.8) !important;
    border-right: 1px solid rgba(255, 255, 255, 0.05) !important;
    color: #6C63FF !important;
}

/* Radio nav pills - Styled like Finova's menu items */
section[data-testid="stSidebar"] div[data-testid="stRadio"] > div {
    gap: 6px;
    padding: 0 4px;
}
/* Hide the default radio circle/dot indicator */
section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label > div:first-child {
    display: none !important;
}
/* Style the actual radio option labels */
section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label {
    background: rgba(255, 255, 255, 0.02) !important;
    backdrop-filter: blur(8px);
    border: 1px solid rgba(255, 255, 255, 0.04) !important;
    border-radius: 12px !important;
    padding: 10px 16px !important;
    font-size: 0.94rem !important;
    font-family: 'Inter', sans-serif !important;
    color: #8E92B2 !important;
    cursor: pointer !important;
    transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
    display: flex !important;
    align-items: center !important;
    margin-bottom: 6px !important;
    width: 100% !important;
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label:hover {
    background: rgba(255, 255, 255, 0.06) !important;
    border-color: rgba(255, 255, 255, 0.1) !important;
    color: #FFFFFF !important;
    transform: translateX(4px) !important;
}
section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label:has(input[type="radio"]:checked) {
    background: linear-gradient(135deg, rgba(108, 99, 255, 0.22) 0%, rgba(247, 37, 133, 0.08) 100%) !important;
    color: #FFFFFF !important;
    font-weight: 600 !important;
    border: 1px solid rgba(108, 99, 255, 0.35) !important;
    border-left: 4px solid #6C63FF !important; /* Neon purple tab highlight */
    box-shadow: 
        0 4px 15px rgba(108, 99, 255, 0.15),
        inset 0 0 10px rgba(108, 99, 255, 0.1) !important;
}

/* Glass Card styling (applied globally to metric containers and Plotly charts) */
[data-testid="metric-container"], div.glass-card, [data-testid="stPlotlyChart"] {
    background: rgba(22, 25, 41, 0.45) !important;
    backdrop-filter: blur(16px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(16px) saturate(180%) !important;
    border: 1px solid rgba(255, 255, 255, 0.06) !important;
    border-top: 1px solid rgba(255, 255, 255, 0.12) !important;
    border-radius: 16px !important;
    padding: 20px 24px !important;
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2) !important;
    transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
}
[data-testid="metric-container"]:hover, div.glass-card:hover, [data-testid="stPlotlyChart"]:hover {
    transform: translateY(-4px);
    background: rgba(22, 25, 41, 0.55) !important;
    border-color: rgba(108, 99, 255, 0.25) !important;
    box-shadow: 0 12px 40px 0 rgba(108, 99, 255, 0.15) !important;
}

/* Glass Buttons */
.stButton button {
    background: rgba(255, 255, 255, 0.05) !important;
    color: #FFFFFF !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 12px !important;
    padding: 10px 24px !important;
    font-weight: 500 !important;
    transition: all 0.25s ease !important;
}
.stButton button:hover {
    background: rgba(255, 255, 255, 0.1) !important;
    border-color: rgba(255, 255, 255, 0.2) !important;
    transform: translateY(-1px);
}
.stButton button[kind="primary"] {
    background: linear-gradient(135deg, #6C63FF 0%, #8E2DE2 100%) !important;
    color: #FFFFFF !important;
    border: none !important;
    box-shadow: 0 4px 15px rgba(108, 99, 255, 0.3) !important;
}
.stButton button[kind="primary"]:hover {
    box-shadow: 0 6px 20px rgba(108, 99, 255, 0.45) !important;
    opacity: 0.95;
}

/* Tables and Dataframes */
.stDataFrame {
    background: rgba(22, 25, 41, 0.3) !important;
    backdrop-filter: blur(12px) !important;
    border: 1px solid rgba(255, 255, 255, 0.06) !important;
    border-radius: 14px !important;
    overflow: hidden;
}

/* Tabs */
[data-testid="stTabs"] {
    background: transparent !important;
    margin-bottom: 20px;
}
[data-testid="stTabs"] [role="tablist"] {
    gap: 8px;
    background: rgba(255, 255, 255, 0.03) !important;
    padding: 6px !important;
    border-radius: 14px !important;
    border: 1px solid rgba(255, 255, 255, 0.05) !important;
}
[data-testid="stTabs"] [role="tab"] {
    color: #8E92B2 !important;
    font-weight: 500 !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 8px 16px !important;
    background: transparent !important;
    transition: all 0.2s ease !important;
}
[data-testid="stTabs"] [role="tab"]:hover {
    color: #FFFFFF !important;
    background: rgba(255, 255, 255, 0.04) !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #FFFFFF !important;
    background: rgba(108, 99, 255, 0.2) !important;
    border: 1px solid rgba(108, 99, 255, 0.3) !important;
}

/* Expanders */
details {
    background: rgba(22, 25, 41, 0.25) !important;
    border: 1px solid rgba(255, 255, 255, 0.05) !important;
    border-radius: 14px !important;
    padding: 4px 8px !important;
    margin-bottom: 8px !important;
}
details summary {
    color: #FFFFFF !important;
    font-weight: 500 !important;
    cursor: pointer;
}
details summary:hover {
    color: #6C63FF !important;
}

/* Premium Scrollbars */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}
::-webkit-scrollbar-track {
    background: rgba(0, 0, 0, 0.1);
}
::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
    background: rgba(108, 99, 255, 0.4);
}

/* Form Inputs styling */
.stTextInput input, .stNumberInput input, .stDateInput input, div[data-baseweb="select"] {
    background: rgba(22, 25, 41, 0.4) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    color: #FFFFFF !important;
    border-radius: 12px !important;
    padding: 8px 12px !important;
    transition: all 0.25s ease !important;
}
.stTextInput input:focus, .stNumberInput input:focus, .stDateInput input:focus {
    border-color: rgba(108, 99, 255, 0.5) !important;
    box-shadow: 0 0 10px rgba(108, 99, 255, 0.2) !important;
}
div[data-baseweb="select"] > div {
    background: transparent !important;
    border: none !important;
    color: #FFFFFF !important;
}

/* Alert dialogs */
.stAlert {
    background: rgba(22, 25, 41, 0.45) !important;
    backdrop-filter: blur(12px) !important;
    border: 1px solid rgba(255, 255, 255, 0.06) !important;
    border-radius: 14px !important;
}

/* Dividers */
hr {
    border-color: rgba(255, 255, 255, 0.08) !important;
    margin: 1.5rem 0 !important;
}
</style>

""", unsafe_allow_html=True)

# ── Auto-refresh every 5 minutes (300 000 ms) ──────────────────────────────
st.iframe(
    src="data:text/html;charset=utf-8,%3Cscript%3EsetTimeout(function()%7B%20window.parent.location.reload()%3B%20%7D%2C%20300000)%3B%3C/script%3E",
    height=0,
)

# ── Lazy page imports ──────────────────────────────────────────────────────
from zenfinance.data_store import load_all
from zenfinance.ui import dashboard, upload, transactions, audit, settings, timeline

# ── Authentication ─────────────────────────────────────────────────────────
import extra_streamlit_components as stx

cookie_manager = stx.CookieManager(key="auth_manager")
st.session_state["cookie_manager"] = cookie_manager

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

# Check cookie if not authenticated in session
if not st.session_state["authenticated"]:
    try:
        cookie_val = cookie_manager.get(cookie="auth_pin")
        if cookie_val == "124816":
            st.session_state["authenticated"] = True
            st.rerun()
    except Exception:
        # Ignore initial loading exceptions of cookie manager
        pass

# If still not authenticated, show login page
if not st.session_state["authenticated"]:
    # Empty space to push login card down
    st.write("##")
    st.write("##")
    
    # Visual centering using columns
    c1, c2, c3 = st.columns([1, 1.8, 1])
    with c2:
        st.markdown("""
        <div class="glass-card" style="padding:40px; text-align:center; margin-bottom:20px; border:1px solid rgba(108, 99, 255, 0.2) !important;">
          <div style="font-size:3rem; margin-bottom:15px; filter: drop-shadow(0 0 15px rgba(108, 99, 255, 0.4));">🔑</div>
          <h2 style="margin-bottom:10px; font-family:'Outfit', sans-serif;">ZenFinance Security</h2>
          <p style="color:#8E92B2; font-size:0.92rem; margin-bottom:25px;">Enter the security PIN to access your personal dashboard</p>
        </div>
        """, unsafe_allow_html=True)
        
        # PIN Form input
        pin_input = st.text_input("Enter 6-digit PIN", type="password", key="pin_input", placeholder="••••••", label_visibility="collapsed")
        
        if pin_input:
            if pin_input == "124816":
                st.session_state["authenticated"] = True
                try:
                    cookie_manager.set(cookie="auth_pin", val="124816", max_age=86400) # 24 hours
                except Exception:
                    pass
                st.success("Access Granted! Loading...")
                time.sleep(0.6)
                st.rerun()
            else:
                st.error("Incorrect PIN. Please try again.")
                
    st.stop()

# ── Nav mapping ───────────────────────────────────────────────────────────
NAV_OPTIONS = [
    "📊  Dashboard",
    "📅  Data Timeline",
    "📥  Import Data",
    "💳  Transactions",
    "🔍  Audit",
    "⚙️  Settings",
]
NAV_KEYS = {
    "📊  Dashboard":    "dashboard",
    "📅  Data Timeline": "timeline",
    "📥  Import Data":  "import",
    "💳  Transactions": "transactions",
    "🔍  Audit":        "audit",
    "⚙️  Settings":     "settings",
}

# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    # Logo
    st.markdown("""
    <div style="display:flex;align-items:center;gap:12px;padding:24px 0 20px 12px">
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
        granularity = st.selectbox("Granularity", ["Daily", "Weekly", "Monthly"], index=1, key="sb_granularity")
    else:
        filter_source = "All"
        date_from = date.today() - timedelta(days=365)
        date_to   = date.today()
        granularity = "Weekly"
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

    # ── User Profile Card ──────────────────────────────────────────────────
    st.markdown("""
    <div style="display:flex;align-items:center;gap:12px;padding:12px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:14px;margin-top:20px">
      <div style="font-size:1.2rem;background:rgba(108,99,255,0.15);width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#6C63FF;font-weight:700">P</div>
      <div>
        <div style="font-size:0.82rem;font-weight:600;color:#FFFFFF;line-height:1.2">Pankaj Sharma</div>
        <div style="font-size:0.65rem;color:#8E92B2">Personal Account</div>
      </div>
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
    dashboard.render(_filtered_df(), granularity)

elif page == "timeline":
    timeline.render(_filtered_df())

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
