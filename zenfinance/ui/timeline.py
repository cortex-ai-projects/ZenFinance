"""
ZenFinance — Timeline Visualization
Displays the available timeframes of dataset sources (Bank Accounts) to easily spot missing chunks.
"""

from __future__ import annotations

from datetime import timedelta
import pandas as pd
import streamlit as st
import plotly.express as px

def render(df: pd.DataFrame) -> None:
    st.markdown("## 📅 Data Set Coverage Timeline")
    st.markdown(
        "<p style='color:#8888AA; font-size:0.9rem;'>View available timespans for imported bank accounts. "
        "Gaps larger than 15 days are split to clearly show missing data periods.</p>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    if df.empty or df["date"].isna().all():
        st.info("No data available to build a timeline. Import data first.")
        return

    # Work on a copy with valid dates and bank_names
    df_clean = df.dropna(subset=["date", "bank_name"]).copy()
    if df_clean.empty:
        st.info("No valid dates or sources found to render the timeline.")
        return

    df_clean["date"] = pd.to_datetime(df_clean["date"])

    # Group by bank_name and analyze contiguous blocks (gap > 15 days = new block)
    threshold = timedelta(days=15)
    records = []

    for bank_name, group in df_clean.groupby("bank_name"):
        # Sort by date
        sorted_dates = group["date"].sort_values().drop_duplicates().tolist()
        
        if not sorted_dates:
            continue
            
        block_start = sorted_dates[0]
        last_date = sorted_dates[0]
        
        # Build contiguous blocks
        for d in sorted_dates[1:]:
            if d - last_date > threshold:
                records.append({
                    "Source (Bank)": bank_name,
                    "Start": block_start,
                    "Finish": last_date
                })
                block_start = d
            last_date = d
            
        # Add the final block
        records.append({
            "Source (Bank)": bank_name,
            "Start": block_start,
            "Finish": last_date
        })

    timeline_df = pd.DataFrame(records)

    if timeline_df.empty:
        st.info("Insufficient data properties for visualization.")
        return

    # For plotly timeline to render properly, start and finish must be datetime values
    timeline_df["Start"] = pd.to_datetime(timeline_df["Start"])
    # If a block has only 1 day, make it slightly larger so it's visible on the timeline
    timeline_df["Finish"] = [
        f + timedelta(hours=23, minutes=59) if s == f else pd.to_datetime(f)
        for s, f in zip(timeline_df["Start"], timeline_df["Finish"])
    ]

    # Create Plotly Gantt-style chart
    fig = px.timeline(
        timeline_df,
        x_start="Start",
        x_end="Finish",
        y="Source (Bank)",
        color="Source (Bank)",
        hover_data={"Start": "|%B %d, %Y", "Finish": "|%B %d, %Y"}
    )

    # Style matching ZenFinance Dark Mode
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#8E92B2", family="'Inter', sans-serif"),
        margin=dict(l=20, r=20, t=30, b=20),
        xaxis=dict(
            showgrid=True,
            gridcolor="rgba(255, 255, 255, 0.05)",
            title=None,
        ),
        yaxis=dict(
            showgrid=False,
            title="Available Data Sets",
        ),
        showlegend=False,  # Colors correlate directly to Y axis anyway
        height=max(300, len(timeline_df["Source (Bank)"].unique()) * 80 + 100),
    )
    
    # Improve bar design
    fig.update_traces(marker_line_color="#0E1117", marker_line_width=1.5, opacity=0.9)
    # Reorder Y-axis to flow neatly
    fig.update_yaxes(autorange="reversed")

    st.plotly_chart(fig, use_container_width=True)

    # Data Gap Summary list
    st.markdown("### Missing Data Highlights")
    with st.expander("Show detailed gap analysis", expanded=False):
        has_gaps = False
        for bank_name, group in timeline_df.groupby("Source (Bank)"):
            group = group.sort_values(by="Start")
            if len(group) > 1:
                has_gaps = True
                st.markdown(f"**{bank_name}**")
                prev_finish = None
                for _, row in group.iterrows():
                    if prev_finish is not None:
                        gap_days = (row["Start"] - prev_finish).days
                        st.markdown(
                            f"- ⚠️ Gap of **{gap_days} days** detected between: "
                            f"`{prev_finish.strftime('%Y-%m-%d')}` and `{row['Start'].strftime('%Y-%m-%d')}`"
                        )
                    prev_finish = row["Finish"]
        if not has_gaps:
            st.success("No significant gaps (>15 days) detected in any uploaded sources.")
