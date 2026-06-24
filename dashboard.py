import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from score_engine import AIHIScorer
import json
import glob
import os

st.set_page_config(page_title="AI Investment Health Index", layout="wide")

# ---- Load Historical Data ----
def load_historical_scores():
    files = glob.glob("data/weekly_*.json")
    records = []
    for f in files:
        with open(f, "r") as file:
            data = json.load(file)
            records.append(data)
    return pd.DataFrame(records)

# ---- Run Current Score ----
scorer = AIHIScorer()
current = scorer.compute_weekly_score()

# ---- DASHBOARD LAYOUT ----
st.title("🚀 AIHI Dashboard")
st.caption("Composite 0-100 Index tracking Hyperscaler Capex, Semis, Memory, DC Reits, and Power.")

col1, col2, col3 = st.columns([2, 1, 1])

# Big Gauge
with col1:
    fig = go.Figure(go.Indicator(
        mode = "gauge+number+delta",
        value = current['AIHI'],
        domain = {'x': [0, 1], 'y': [0, 1]},
        title = {'text': "AI Health Index (0=Growth, 50=Plateau, 100=Collapse)"},
        delta = {'reference': 50},
        gauge = {
            'axis': {'range': [0, 100]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [0, 20], 'color': "lightgreen"},
                {'range': [21, 49], 'color': "yellowgreen"},
                {'range': [50, 50], 'color': "gold"},
                {'range': [51, 79], 'color': "orange"},
                {'range': [80, 100], 'color': "red"}
            ],
            'threshold': {
                'line': {'color': "black", 'width': 4},
                'thickness': 0.75,
                'value': current['AIHI']
            }
        }
    ))
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)

# Pillar Breakdown
with col2:
    st.subheader("Pillar Scores")
    for k, v in current['pillars'].items():
        color = "green" if v < 30 else ("orange" if v < 70 else "red")
        st.metric(label=k, value=f"{v}/100", delta_color=color)

# Daily Market Movers
with col3:
    st.subheader("Daily Sentiment (Accelerant)")
    tickers = ["NVDA", "AMZN", "MSFT", "CEG", "MU"]
    # Use yfinance to get daily change (simplified here)
    import yfinance as yf
    for t in tickers:
        tk = yf.Ticker(t)
        hist = tk.history(period="2d")
        if len(hist) >= 2:
            change = ((hist['Close'].iloc[-1] / hist['Close'].iloc[-2]) - 1) * 100
            st.write(f"**{t}**: {change:.2f}%")

# ---- Weekly Trend Chart ----
st.subheader("52-Week AIHI Trend")
hist_df = load_historical_scores()
if not hist_df.empty:
    hist_df['date'] = pd.to_datetime(hist_df['date'])
    hist_df = hist_df.sort_values('date')
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=hist_df['date'], y=hist_df['AIHI'], 
                              mode='lines+markers', name='AIHI'))
    fig2.add_hline(y=50, line_dash="dash", line_color="gold", annotation_text="Plateau Threshold")
    fig2.add_hline(y=20, line_dash="dot", line_color="green")
    fig2.add_hline(y=80, line_dash="dot", line_color="red")
    fig2.update_layout(height=300, margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig2, use_container_width=True)

# ---- Raw News Feed (The Canary) ----
st.subheader("📰 Early Warning Feed (Last 24hrs)")
# Simulate news scraping - in prod, hit NewsAPI with keywords.
st.warning("⚠️ [Bloomberg] MSFT signals 'efficiency prioritization' in next fiscal year.")
st.info("📉 [TrendForce] HBM contract prices flat MoM for first time in 8 months.")
st.success("⚡ [CEG] Signs new 15-yr PPA with AWS; unaffected by chip cycle.")
