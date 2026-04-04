"""
ZenFinance — Import / Upload UI
Visual card-based source selector + file uploader with live preview.
"""
from __future__ import annotations

import io
from typing import List

import pandas as pd
import streamlit as st

from zenfinance.categorization import apply_categories
from zenfinance.data_store import append_transactions
from zenfinance.models import TransactionDTO
from zenfinance.parsers.registry import ACCEPTED_EXTENSIONS, get_parser

# ── Source catalogue with display metadata ─────────────────────────────
# (key, display_name, emoji, colour, formats, description, group)
# group: "bank" | "audit" | "intermediator" | "terminal" | "other"
SOURCE_CARDS = [
    # ── Audit ground-truth ─────────────────────────────────────────────
    ("AXIO",            "AXIO",             "🔍",  "#43D9AD", [".csv", ".xlsx"],           "Your personal ledger — marks transactions Audited",       "audit"),

    # ── Banks ──────────────────────────────────────────────────────────
    ("SBI Bank",        "SBI Bank",         "🏦",  "#4CC9F0", [".xlsx", ".xls", ".pdf"],   "State Bank of India — Excel or PDF statement",            "bank"),
    ("ICICI Bank",      "ICICI Bank",       "🏦",  "#56CCF2", [".xlsx", ".xls", ".pdf"],   "ICICI Bank — Excel (XLS/XLSX) or PDF statement",          "bank"),
    ("HDFC Bank",       "HDFC Bank",        "🏦",  "#6C63FF", [".xlsx", ".csv"],            "HDFC Bank Excel / CSV export",                            "bank"),
    ("Axis Bank",       "Axis Bank",        "🏦",  "#BB86FC", [".xlsx", ".csv"],            "Axis Bank Excel / CSV export",                            "bank"),
    ("Kotak Bank",      "Kotak Bank",       "🏦",  "#9B59B6", [".xlsx", ".csv"],            "Kotak Bank Excel / CSV export",                           "bank"),

    # ── Payment intermediators ──────────────────────────────────────────
    ("PhonePe",         "PhonePe",          "📱",  "#7C3AED", [".pdf"],                     "PhonePe PDF — enriches bank records (intermediator)",     "intermediator"),
    ("Google Pay",      "Google Pay",       "📱",  "#43D9AD", [".csv"],                     "Google Pay CSV — enriches bank records (intermediator)",  "intermediator"),
    ("Paytm",           "Paytm",            "📱",  "#4361EE", [".csv", ".xlsx"],            "Paytm — payment intermediator",                           "intermediator"),
    ("Amazon Pay",      "Amazon Pay",       "🛒",  "#FFB347", [".csv"],                     "Amazon Pay — payment intermediator",                      "intermediator"),

    # ── Terminal / merchant apps ────────────────────────────────────────
    ("Swiggy",          "Swiggy",           "🍔",  "#FC8019", [".csv", ".xlsx"],            "Swiggy orders — confirms food delivery spend",            "terminal"),
    ("Zomato",          "Zomato",           "🍕",  "#E23744", [".csv", ".xlsx"],            "Zomato orders — confirms food delivery spend",            "terminal"),
    ("Blinkit",         "Blinkit",          "⚡",  "#F8CB2E", [".csv", ".xlsx"],            "Blinkit (quick commerce) orders",                         "terminal"),
    ("Zepto",           "Zepto",            "🛵",  "#8B5CF6", [".csv", ".xlsx"],            "Zepto quick-delivery orders",                             "terminal"),
    ("BigBasket",       "BigBasket",        "🛒",  "#84CC16", [".csv", ".xlsx"],            "BigBasket grocery orders",                                "terminal"),
    ("Amazon",          "Amazon",           "📦",  "#FF9900", [".csv", ".xlsx"],            "Amazon order history",                                    "terminal"),
    ("Swiggy Money",    "Swiggy Money",     "💰",  "#FF6584", [".csv"],                     "Swiggy Money wallet transactions",                        "terminal"),

    # ── Catch-all ──────────────────────────────────────────────────────
    ("Other / Generic", "Other / Generic",  "📄",  "#8888AA", [".csv", ".xlsx", ".xls"],   "Any bank / app CSV or Excel (auto-detect columns)",       "other"),
]

SOURCE_MAP = {s[0]: s for s in SOURCE_CARDS}

# Group labels for the upload UI
_GROUP_LABELS = {
    "audit":        ("🔍 Audit / Ground Truth", "#43D9AD"),
    "bank":         ("🏦 Banks",                "#4CC9F0"),
    "intermediator":("💳 Payment Intermediators (route money, enrich records)", "#7C3AED"),
    "terminal":     ("🏪 Terminal / Merchant Apps (confirm spend)", "#FC8019"),
    "other":        ("📄 Other / Generic",       "#8888AA"),
}

GREEN  = "#43D9AD"
RED    = "#FF6584"
YELLOW = "#FFB347"
PURPLE = "#6C63FF"
CARD   = "#1A1D2E"


def _source_grid() -> str | None:
    """
    Render a grouped card-grid of source options; return the selected source key.

    Groups:  Audit → Banks → Intermediators → Terminal Apps → Other
    Each group shows a header so users know the role of each source.
    """
    if "selected_source" not in st.session_state:
        st.session_state.selected_source = None

    st.markdown("### 1 · Select Your Source")
    st.caption(
        "Click the bank or app your statement comes from. "
        "Sources are grouped by their role in the audit pipeline."
    )

    # Organise cards by group
    from collections import OrderedDict
    groups: dict[str, list] = OrderedDict()
    for card in SOURCE_CARDS:
        g = card[6] if len(card) > 6 else "other"
        groups.setdefault(g, []).append(card)

    row_size = 4
    for group_key, cards in groups.items():
        label, colour = _GROUP_LABELS.get(group_key, (group_key.title(), "#8888AA"))
        st.markdown(
            f'<div style="font-size:0.8rem;font-weight:700;color:{colour};'
            f'letter-spacing:.06em;margin:14px 0 6px 2px;text-transform:uppercase">'
            f'{label}</div>',
            unsafe_allow_html=True,
        )

        for row_start in range(0, len(cards), row_size):
            row_items = cards[row_start : row_start + row_size]
            # Pad to row_size so columns are always equal width
            cols = st.columns(row_size)
            for col_idx, col in enumerate(cols):
                if col_idx >= len(row_items):
                    break
                card = row_items[col_idx]
                key, name, emoji, card_colour, fmts = card[0], card[1], card[2], card[3], card[4]
                desc = card[5] if len(card) > 5 else name

                is_selected = st.session_state.selected_source == key
                border = f"2px solid {card_colour}" if is_selected else "1px solid #2A2D3E"
                bg     = f"{card_colour}22"          if is_selected else "#1A1D2E"
                shadow = f"0 0 12px {card_colour}55" if is_selected else "none"

                col.markdown(
                    f"""
                    <div style="
                        background:{bg};
                        border:{border};
                        border-radius:14px;
                        padding:14px 10px 12px;
                        text-align:center;
                        box-shadow:{shadow};
                        margin-bottom:6px;
                        cursor:pointer;
                        transition:all .2s;
                    ">
                      <div style="font-size:1.7rem">{emoji}</div>
                      <div style="font-weight:700;font-size:0.82rem;color:#FAFAFA;margin-top:4px">{name}</div>
                      <div style="font-size:0.62rem;color:#8888AA;margin-top:2px">{', '.join(fmts)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                # NOTE: do NOT call st.rerun() here — the button press already
                # triggers a Streamlit rerun automatically. A second explicit rerun
                # collapses the sidebar permanently. Session-state update is enough.
                if col.button(
                    f"Select {name}",
                    key=f"src_btn_{key}",
                    help=desc,
                    use_container_width=True,
                ):
                    st.session_state.selected_source = key
                    # No st.rerun() — Streamlit reruns automatically on button click

    return st.session_state.selected_source


def _preview_table(dtos: List[TransactionDTO]) -> pd.DataFrame:
    rows = []
    for d in dtos:
        rows.append({
            "Date":        str(d.date),
            "Type":        d.txn_type,
            "Amount (₹)":  f"{d.amount:,.2f}",
            "Description": (d.bank_description or "")[:60],
            "Category":    d.category or "—",
            "Payment":     d.payment_method or "—",
        })
    return pd.DataFrame(rows)


def render():
    st.markdown("## 📥 Import Transactions")
    st.markdown(
        "Upload bank statements, UPI app exports, or delivery-app CSVs. "
        "ZenFinance automatically **deduplicates** and **categorises** every row."
    )

    # ── Step 1: Visual source card selector ──────────────────────────────
    source = _source_grid()

    if not source:
        st.info("👆 Click a source card above to get started.")
        return

    # Show selected source pill
    _, name, emoji, colour, fmts, desc, _group = SOURCE_MAP[source]
    st.markdown(
        f'<div style="display:inline-flex;align-items:center;gap:8px;'
        f'background:{colour}18;border:1px solid {colour}55;border-radius:30px;'
        f'padding:6px 16px;margin-bottom:10px">'
        f'<span style="font-size:1.1rem">{emoji}</span>'
        f'<span style="font-weight:600;color:{colour}">{name} selected</span>'
        f'<span style="font-size:0.72rem;color:#8888AA">({", ".join(fmts)})</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Reset button — no st.rerun() needed; button click triggers automatic rerun
    if st.button("✕ Change source", key="reset_source"):
        st.session_state.selected_source = None

    # ── Step 2: File uploader ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 2 · Upload Statement File(s)")
    accepted_types = [e.lstrip(".") for e in fmts]

    uploaded_files = st.file_uploader(
        f"Drop your **{name}** file(s) here",
        type=accepted_types,
        accept_multiple_files=True,
        help=f"Accepted: {', '.join(fmts)}. You can upload multiple files at once.",
    )

    if not uploaded_files:
        # Show format hint card
        st.markdown(
            f"""
            <div style="background:#1A1D2E;border:1px dashed #2A2D3E;border-radius:12px;
                        padding:20px;text-align:center;color:#8888AA">
              <div style="font-size:1.8rem">{emoji}</div>
              <div style="margin-top:8px;font-size:0.9rem">
                Drag & drop your <b style="color:{colour}">{name}</b> statement here
              </div>
              <div style="font-size:0.75rem;margin-top:4px">
                Accepted formats: <b>{', '.join(fmts)}</b>
              </div>
              <div style="font-size:0.72rem;margin-top:8px;color:#555">{desc}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    # ── Step 3: Parse each file ───────────────────────────────────────────
    all_dtos: List[TransactionDTO] = []

    for uf in uploaded_files:
        st.markdown(f"---\n#### 📄 `{uf.name}`")
        file_bytes = uf.read()

        with st.spinner(f"Parsing `{uf.name}`…"):
            try:
                # Pass filename so registry can dispatch to the correct format parser
                # (e.g. ICICI .pdf → ICICIPDFParser, ICICI .xlsx → ICICIParser)
                parser   = get_parser(source, filename=uf.name)
                raw_dtos = parser.parse(io.BytesIO(file_bytes), uf.name)

                if raw_dtos:
                    tmp_df = pd.DataFrame([d.to_dict() for d in raw_dtos])
                    tmp_df = apply_categories(tmp_df)
                    for dto, (_, row) in zip(raw_dtos, tmp_df.iterrows()):
                        dto.category     = row.get("category")
                        dto.sub_category = row.get("sub_category")
                else:
                    tmp_df = pd.DataFrame()
            except Exception as e:
                st.error(f"❌ Could not parse `{uf.name}`: {e}")
                st.caption("Try switching to **Other / Generic** if your format isn't listed.")
                continue

        if not raw_dtos:
            st.warning(f"⚠️ No valid transactions found in `{uf.name}`.")
            continue

        # Metrics
        credits = sum(1 for d in raw_dtos if d.txn_type == "CREDIT")
        debits  = sum(1 for d in raw_dtos if d.txn_type == "DEBIT")
        total_c = sum(d.amount for d in raw_dtos if d.txn_type == "CREDIT")
        total_d = sum(d.amount for d in raw_dtos if d.txn_type == "DEBIT")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Rows parsed",   len(raw_dtos))
        m2.metric("Total Credits", f"₹{total_c:,.0f}", f"{credits} txns")
        m3.metric("Total Debits",  f"₹{total_d:,.0f}", f"{debits} txns")
        m4.metric("Categories",    tmp_df["category"].nunique() if not tmp_df.empty else "—")

        # Category breakdown mini-chart
        if not tmp_df.empty and "category" in tmp_df.columns:
            top_cats = (
                tmp_df[tmp_df["txn_type"] == "DEBIT"]
                .groupby("category")["amount"]
                .sum()
                .nlargest(5)
            )
            if not top_cats.empty:
                with st.expander("📊 Category preview", expanded=False):
                    import plotly.express as px
                    fig = px.bar(
                        top_cats.reset_index(),
                        x="amount", y="category", orientation="h",
                        color="amount",
                        color_continuous_scale=[[0,"#3A0CA3"],[1,colour]],
                        labels={"amount": "₹", "category": ""},
                    )
                    fig.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#FAFAFA"),
                        margin=dict(l=10, r=10, t=10, b=10),
                        coloraxis_showscale=False,
                        height=220,
                    )
                    st.plotly_chart(fig, use_container_width=True)

        # Preview table
        with st.expander("🔍 Preview all rows", expanded=True):
            preview_df = _preview_table(raw_dtos)
            st.dataframe(preview_df, use_container_width=True,
                         height=min(420, 38 * len(preview_df) + 38),
                         hide_index=True)

        all_dtos.extend(raw_dtos)

    if not all_dtos:
        return

    # ── Step 4: Confirm & import ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 3 · Confirm & Import")

    st.markdown(
        f"<div style='background:#1A1D2E;border:1px solid #2A2D3E;border-radius:12px;"
        f"padding:14px 18px;margin-bottom:14px'>"
        f"Ready to import <b style='color:{colour}'>{len(all_dtos)} transactions</b> "
        f"from <b>{len(uploaded_files)}</b> file(s) into ZenFinance.<br>"
        f"<span style='font-size:0.8rem;color:#8888AA'>Duplicates will be skipped automatically.</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    col_btn, _ = st.columns([1, 3])
    with col_btn:
        if st.button("⚡ Import Now", type="primary", use_container_width=True):
            with st.spinner("Merging and deduplicating…"):
                result = append_transactions(all_dtos)

            added = result["added"]
            dupes = result["skipped_duplicates"]
            total = result["total"]

            if added > 0:
                st.success(
                    f"✅ **{added}** new transactions added! "
                    f"({dupes} duplicates skipped · {total} total in database)"
                )
                st.balloons()
                # Reset for next import — no st.rerun(), sidebar stays stable
                st.session_state.selected_source = None
            else:
                st.warning(
                    f"⚠️ All {dupes} transaction(s) already exist — nothing new imported."
                )

    # ── Format tips ───────────────────────────────────────────────────────
    with st.expander("ℹ️ Format guide & tips"):
        st.markdown("""
### Audit pipeline roles

| Role | Sources | Effect on audit status |
|------|---------|------------------------|
| **🔍 Audit / Ground Truth** | AXIO | Always marks matched bank txns as **Audited** |
| **🏦 Bank** | SBI, ICICI, HDFC, Axis, Kotak | Primary audit targets |
| **🏪 Terminal apps** | Swiggy, Zomato, Blinkit, Zepto, BigBasket, Amazon | Marks matched bank txns as **Audited** |
| **💳 Intermediators** | PhonePe, GPay, Paytm | Enriches records (adds UTR/route) but does **NOT** mark Audited alone |

---

### File formats supported

| Source | Formats | Notes |
|--------|---------|-------|
| **SBI Bank** | `.xlsx` · `.xls` · `.pdf` | Excel: data from row 21. PDF: table-extracted automatically |
| **ICICI Bank** | `.xlsx` · `.xls` · `.pdf` | Excel: rows from row 13, cols B–I. PDF: auto-extracted |
| **PhonePe** | `.pdf` | "Download Statement" PDF from the PhonePe app |
| **AXIO** | `.csv` · `.xlsx` | Export from the AXIO finance app — columns auto-detected |
| **Swiggy / Zomato / Blinkit / Zepto** | `.csv` · `.xlsx` | Order history export — columns auto-detected |
| **HDFC / Axis / Kotak** | `.csv` · `.xlsx` | Auto-detects date, debit, credit columns |
| **Other** | `.csv` · `.xlsx` | Any statement with Date + Amount columns |

---
🔒 **Deduplication**: MD5 fingerprint of `date + amount + description` — re-uploading the same file is always safe.

🔗 **Multi-format**: Each source supports multiple file formats. ZenFinance picks the right parser automatically based on the file extension.
        """)
