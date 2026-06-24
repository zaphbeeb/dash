import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from score_engine import AIHIScorer
import json
import glob
import os
import yfinance as yf

# ------- PAGE CONFIG -------
st.set_page_config(page_title="AI Investment Health Index", layout="wide")

# ------- CACHED DATA FETCHERS (to avoid throttle) -------

@st.cache_data(ttl=300)   # Refresh every 5 minutes for daily movers
def get_daily_movers(tickers):
    """Fetch only the last 5 days of data for ALL tickers in one batch."""
    try:
        data = yf.download(
            tickers=tickers,
            period="5d",
            group_by='ticker',
            auto_adjust=True,
            threads=True,
            progress=False
        )
        moves = {}
        for t in tickers:
            if t in data and len(data[t]) >= 2:
                df = data[t]
                change = ((df['Close'].iloc[-1] / df['Close'].iloc[-2]) - 1) * 100
                moves[t] = round(change, 2)
            else:
                moves[t] = 0.0
        return moves
    except Exception as e:
        st.warning(f"Could not fetch daily prices: {e}")
        return {t: 0.0 for t in tickers}

@st.cache_data(ttl=3600)  # Refresh hourly for historical scores
def load_historical_scores():
    files = glob.glob("data/weekly_*.json")
    records = []
    for f in files:
        try:
            with open(f, "r") as file:
                data = json.load(file)
                records.append(data)
        except:
            continue
    if records:
        df = pd.DataFrame(records)
        df['date'] = pd.to_datetime(df['date'])
        return df.sort_values('date')
    return pd.DataFrame()

# ------- ENSURE DATA DIRECTORY EXISTS -------
os.makedirs("data", exist_ok=True)

# ------- COMPUTE CURRENT SCORE -------
scorer = AIHIScorer()
current = scorer.compute_weekly_score()

# ------- DASHBOARD LAYOUT -------
st.title("🚀 AIHI Dashboard")
st.caption("Composite 0-100 Index tracking Hyperscaler Capex, Semis, Memory, DC Reits, and Power.")

col1, col2, col3 = st.columns([2, 1, 1])

# ---------- COL 1: Big Gauge ----------
with col1:
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=current['AIHI'],
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': "AI Health Index (0=Growth, 50=Plateau, 100=Collapse)"},
        delta={'reference': 50},
        gauge={
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

# ---------- COL 2: Pillar Breakdown ----------
with col2:
    st.subheader("Pillar Scores")
    for k, v in current['pillars'].items():
        # Color coding
        if v < 30:
            color = "normal"
            delta = "🟢 Growth"
        elif v < 70:
            color = "off"
            delta = "🟡 Plateau/Transition"
        else:
            color = "inverse"
            delta = "🔴 Contraction"
        st.metric(label=k, value=f"{v}/100", delta=delta, delta_color=color)

# ---------- COL 3: Daily Movers (Batch fetched) ----------
with col3:
    st.subheader("📊 Daily Movers")
    tickers_watch = ["NVDA", "AMZN", "MSFT", "CEG", "MU"]
    daily_changes = get_daily_movers(tickers_watch)
    
    for t in tickers_watch:
        change = daily_changes.get(t, 0.0)
        arrow = "▲" if change > 0 else "▼" if change < 0 else "•"
        color = "green" if change > 0 else "red" if change < 0 else "gray"
        st.markdown(f"**{t}** : <span style='color:{color}'>{arrow} {change}%</span>", unsafe_allow_html=True)

# ---------- TREND CHART ----------
st.subheader("📈 52-Week AIHI Trend")
hist_df = load_historical_scores()

if not hist_df.empty:
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=hist_df['date'], 
        y=hist_df['AIHI'], 
        mode='lines+markers', 
        name='AIHI',
        line=dict(color='darkblue', width=3)
    ))
    fig2.add_hline(y=50, line_dash="dash", line_color="gold", annotation_text="Plateau Threshold")
    fig2.add_hline(y=20, line_dash="dot", line_color="green", annotation_text="Growth Zone")
    fig2.add_hline(y=80, line_dash="dot", line_color="red", annotation_text="Collapse Zone")
    fig2.update_layout(height=350, margin=dict(l=0, r=0, t=30, b=0))
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("⏳ No historical weekly data found. Run the scorer once to generate `data/weekly_*.json`.")

# ---------- EARLY WARNING NEWS FEED (Placeholder) ----------
st.subheader("📰 Early Warning Feed (Simulated)")
st.warning("⚠️ [Bloomberg] MSFT signals 'efficiency prioritization' in next fiscal year.")
st.info("📉 [TrendForce] HBM contract prices flat MoM for first time in 8 months.")
st.success("⚡ [CEG] Signs new 15-yr PPA with AWS; unaffected by chip cycle.")
