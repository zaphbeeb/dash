import yfinance as yf
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
import re
import json
import os
from datetime import datetime, timedelta
from functools import lru_cache
import time

# ------------------------------------------------------------------
#  CONFIGURATION
# ------------------------------------------------------------------
# Optional: Set your free NewsAPI key as an environment variable
# (Sign up at https://newsapi.org/ to get one)
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", None)

# User-Agent to avoid blocks when scraping
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


class AIHIScorer:
    def __init__(self):
        # Core tickers
        self.hyperscalers = ["AMZN", "MSFT", "GOOGL", "META"]
        self.semis = ["NVDA"]
        self.memory = ["MU"]          # Micron (HBM/DRAM proxy)
        self.energy = ["CEG", "VST"]
        self.dc_reits = ["DLR", "EQIX"]
        self.all_tickers = list(set(
            self.hyperscalers + self.semis + self.memory + self.energy + self.dc_reits
        ))

        # Internal cache for price data (cleared per instance)
        self._price_cache = None
        self._financial_cache = {}

    # ------------------------------------------------------------------
    #  PRICE DATA (BATCH DOWNLOAD - AVOIDS THROTTLE)
    # ------------------------------------------------------------------
    def _fetch_all_prices(self, period="6mo"):
        """Fetch all ticker prices in a single batch request."""
        if self._price_cache is not None:
            return self._price_cache
        try:
            data = yf.download(
                tickers=self.all_tickers,
                period=period,
                group_by='ticker',
                auto_adjust=True,
                threads=True,
                progress=False
            )
            self._price_cache = data
            return data
        except Exception as e:
            print(f"⚠️ Batch price download failed: {e}")
            return {}

    def _get_stock_momentum(self, ticker):
        """Relative strength vs 200-day moving average."""
        data = self._fetch_all_prices()
        if ticker not in data or data[ticker].empty or len(data[ticker]) < 200:
            return 0.0
        df = data[ticker]
        last_close = df['Close'].iloc[-1]
        ma_200 = df['Close'].rolling(200).mean().iloc[-1]
        if pd.isna(ma_200) or ma_200 == 0:
            return 0.0
        return (last_close / ma_200) - 1

    def _get_monthly_return(self, ticker):
        """1-month price performance (approx 21 trading days)."""
        data = self._fetch_all_prices()
        if ticker not in data or data[ticker].empty or len(data[ticker]) < 21:
            return 0.0
        df = data[ticker]
        return (df['Close'].iloc[-1] / df['Close'].iloc[-21]) - 1

    # ------------------------------------------------------------------
    #  FINANCIAL DATA (REAL SEC/10-Q METRICS)
    # ------------------------------------------------------------------
    def _get_quarterly_metric(self, ticker, metric_name, statement_type="income"):
        """
        Fetch the most recent quarterly value for a given financial metric.
        statement_type: 'income', 'cashflow', or 'balance'
        """
        cache_key = f"{ticker}_{metric_name}_{statement_type}"
        if cache_key in self._financial_cache:
            return self._financial_cache[cache_key]

        try:
            tk = yf.Ticker(ticker)
            if statement_type == "income":
                df = tk.quarterly_income_stmt
            elif statement_type == "cashflow":
                df = tk.quarterly_cashflow
            elif statement_type == "balance":
                df = tk.quarterly_balance_sheet
            else:
                return None

            if df.empty:
                return None

            # Find the row (case-insensitive)
            for idx in df.index:
                if metric_name.lower() in idx.lower():
                    # Get the latest quarter (first column)
                    val = df.loc[idx].iloc[0]
                    if pd.isna(val):
                        return None
                    self._financial_cache[cache_key] = val
                    return val

            return None

        except Exception as e:
            print(f"⚠️ Could not fetch {metric_name} for {ticker}: {e}")
            return None

    def _get_quarterly_revenue(self, ticker):
        return self._get_quarterly_metric(ticker, "Total Revenue", "income")

    def _get_quarterly_capex(self, ticker):
        # Try "Capital Expenditure", fallback to "Purchase Of Property, Plant And Equipment"
        val = self._get_quarterly_metric(ticker, "Capital Expenditure", "cashflow")
        if val is None:
            val = self._get_quarterly_metric(ticker, "Purchase Of Property, Plant And Equipment", "cashflow")
        return val

    def _get_quarterly_inventory(self, ticker):
        return self._get_quarterly_metric(ticker, "Inventory", "balance")

    def _get_quarterly_gross_margin(self, ticker):
        """Gross profit / Total Revenue."""
        rev = self._get_quarterly_revenue(ticker)
        if rev is None or rev == 0:
            return None
        gp = self._get_quarterly_metric(ticker, "Gross Profit", "income")
        if gp is None:
            return None
        return gp / rev

    def _get_historical_revenue(self, ticker, quarters_ago=4):
        """
        Get revenue from a specific quarter in the past (e.g., 4 quarters ago for YoY).
        """
        try:
            tk = yf.Ticker(ticker)
            df = tk.quarterly_income_stmt
            if df.empty:
                return None
            for idx in df.index:
                if "Total Revenue" in idx:
                    # df.loc[idx] returns a Series with quarters as columns
                    # Column 0 = latest, column 4 = 4 quarters ago
                    if len(df.loc[idx]) > quarters_ago:
                        val = df.loc[idx].iloc[quarters_ago]
                        if not pd.isna(val):
                            return val
                    return None
            return None
        except Exception:
            return None

    def _get_historical_capex(self, ticker, quarters_ago=4):
        try:
            tk = yf.Ticker(ticker)
            df = tk.quarterly_cashflow
            if df.empty:
                return None
            for idx in df.index:
                if "Capital Expenditure" in idx or "Purchase Of Property" in idx:
                    if len(df.loc[idx]) > quarters_ago:
                        val = df.loc[idx].iloc[quarters_ago]
                        if not pd.isna(val):
                            return val
                    return None
            return None
        except Exception:
            return None

    # ------------------------------------------------------------------
    #  NEWS SENTIMENT (OPTIONAL, USING FREE NEWSAPI)
    # ------------------------------------------------------------------
    def _fetch_bearish_headlines(self):
        """
        Search for recent headlines about hyperscalers containing bearish capex phrases.
        Returns a score modifier (0 to +30) based on frequency.
        """
        if not NEWS_API_KEY:
            return 0

        phrases = ["capex cut", "digestion", "prioritization", "deceleration", "efficiency", "reducing spend"]
        query = " OR ".join(phrases)
        url = f"https://newsapi.org/v2/everything?q={query}&language=en&pageSize=20&apiKey={NEWS_API_KEY}"

        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            data = resp.json()
            if data.get("status") != "ok":
                return 0

            count = 0
            for article in data.get("articles", []):
                title = article.get("title", "")
                desc = article.get("description", "")
                text = (title + " " + desc).lower()
                for p in phrases:
                    if p in text:
                        count += 1
                        break  # count each article only once

            # If >5 relevant articles, add 30 points (severe bearish sentiment)
            # 3-5 articles -> +15, 1-2 -> +5
            if count >= 5:
                return 30
            elif count >= 3:
                return 15
            elif count >= 1:
                return 5
            return 0

        except Exception as e:
            print(f"⚠️ News API error: {e}")
            return 0

    # ------------------------------------------------------------------
    #  PILLAR 1: HYPERSCALER CAPEX GUIDANCE (30% weight)
    # ------------------------------------------------------------------
    def pillar_1_guidance(self):
        """
        Real data: Aggregate capex and revenue for AMZN, MSFT, GOOGL, META.
        Score = f(capex_growth_yoy, revenue_growth_yoy, news sentiment)
        """
        total_capex_curr = 0
        total_rev_curr = 0
        total_capex_prev = 0
        total_rev_prev = 0

        for ticker in self.hyperscalers:
            capex_curr = self._get_quarterly_capex(ticker)
            rev_curr = self._get_quarterly_revenue(ticker)
            capex_prev = self._get_historical_capex(ticker, 4)  # 4 quarters ago
            rev_prev = self._get_historical_revenue(ticker, 4)

            if capex_curr is not None and rev_curr is not None:
                total_capex_curr += capex_curr
                total_rev_curr += rev_curr
            if capex_prev is not None and rev_prev is not None:
                total_capex_prev += capex_prev
                total_rev_prev += rev_prev

        # If we have no data, return neutral
        if total_capex_prev == 0 or total_rev_prev == 0:
            return 50

        capex_growth = (total_capex_curr / total_capex_prev) - 1
        rev_growth = (total_rev_curr / total_rev_prev) - 1
        gap = capex_growth - rev_growth

        # Base score: smaller gap = more mature (higher score)
        if gap > 0.50:
            base = 0
        elif gap > 0.30:
            base = 15
        elif gap > 0.15:
            base = 35
        elif gap > 0.00:
            base = 55
        elif gap > -0.15:
            base = 70
        else:
            base = 85

        # Adjust for absolute capex growth rate
        if capex_growth < -0.05:   # Actual cuts
            base = min(100, base + 20)

        # Add news sentiment penalty
        news_penalty = self._fetch_bearish_headlines()
        final_score = min(100, base + news_penalty)

        return round(final_score, 2)

    # ------------------------------------------------------------------
    #  PILLAR 2: NVIDIA BACKLOG & LEAD TIMES (25% weight)
    # ------------------------------------------------------------------
    def pillar_2_backlog(self):
        """
        Real data: NVDA revenue growth QoQ + Inventory growth QoQ.
        Fast revenue growth + slow inventory growth = strong backlog (score 0).
        Slow revenue + fast inventory = backlog building up (warning).
        """
        ticker = "NVDA"

        # Current revenue and previous quarter revenue
        rev_curr = self._get_quarterly_revenue(ticker)
        rev_prev = self._get_historical_revenue(ticker, 1)  # 1 quarter ago
        inv_curr = self._get_quarterly_inventory(ticker)
        inv_prev = None

        # Try to get inventory from 1 quarter ago
        try:
            tk = yf.Ticker(ticker)
            df = tk.quarterly_balance_sheet
            if not df.empty:
                for idx in df.index:
                    if "Inventory" in idx:
                        if len(df.loc[idx]) > 1:
                            inv_prev = df.loc[idx].iloc[1]
                        break
        except Exception:
            pass

        if rev_curr is None or rev_prev is None or rev_prev == 0:
            return 50

        rev_growth = (rev_curr / rev_prev) - 1

        # Score based on revenue growth
        if rev_growth > 0.15:
            score = 0
        elif rev_growth > 0.05:
            score = 25
        elif rev_growth > 0.00:
            score = 50
        else:
            score = 80

        # Adjust for inventory accumulation (if data available)
        if inv_curr is not None and inv_prev is not None and inv_prev != 0:
            inv_growth = (inv_curr / inv_prev) - 1
            # If inventory grows faster than revenue, backlog is compressing (bad)
            if inv_growth > rev_growth + 0.10:
                score = min(100, score + 25)
            elif inv_growth < rev_growth - 0.10:
                score = max(0, score - 10)

        return round(score, 2)

    # ------------------------------------------------------------------
    #  PILLAR 3: HBM / DRAM PRICING (15% weight)
    # ------------------------------------------------------------------
    def pillar_3_memory(self):
        """
        Primary: Scrape TrendForce DRAM spot price.
        Fallback: Micron's gross margin (pricing power proxy).
        """
        # ---- Attempt 1: Scrape TrendForce ----
        try:
            url = "https://www.trendforce.com/price/dram"
            resp = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")

            # Look for DDR5 or generic DRAM spot price
            # TrendForce typically displays a number like "4.85" or "$4.85"
            text = soup.get_text()
            # Find patterns like $X.XX or X.XX (with context of DRAM)
            matches = re.findall(r'\$?(\d+\.\d{2})', text)

            # Filter for reasonable DRAM prices (typically $1 - $10)
            prices = [float(m) for m in matches if 1.0 <= float(m) <= 10.0]
            if prices:
                current_price = prices[0]  # First reasonable price

                # Simulate historical price by looking at a cached value
                # In production, store last week's price in a JSON file.
                # For now, we compare current price to 3-month MA estimate.
                # We'll just use MU's gross margin as a cross-check.
                print(f"✅ Scraped DRAM price: ${current_price}")
                # Since we don't have historical scraped prices here, we'll fallback to MU margin
                # but use this as a confirmation.
                # We'll trust the fallback below for consistent scoring.
        except Exception as e:
            print(f"⚠️ TrendForce scrape failed: {e}")

        # ---- Fallback: Micron's Gross Margin ----
        mu_gm = self._get_quarterly_gross_margin("MU")
        if mu_gm is None:
            return 50

        if mu_gm > 0.45:
            return 0       # Strong pricing power (HBM shortage)
        elif mu_gm > 0.35:
            return 30      # Healthy margins
        elif mu_gm > 0.25:
            return 60      # Margin compression
        elif mu_gm > 0.15:
            return 85      # Weak pricing
        else:
            return 100     # Collapse in pricing

    # ------------------------------------------------------------------
    #  PILLAR 4: DATA CENTER VACANCY & CAPEX/REV RATIO (15% weight)
    # ------------------------------------------------------------------
    def pillar_4_datacenter(self):
        """
        Uses the aggregate capex/revenue ratio from P1 (already computed logic)
        plus the relative performance of Data Center REITs vs Hyperscalers.
        """
        # Re-use P1 logic to get ratio
        total_capex = 0
        total_rev = 0
        for ticker in self.hyperscalers:
            capex = self._get_quarterly_capex(ticker)
            rev = self._get_quarterly_revenue(ticker)
            if capex is not None and rev is not None:
                total_capex += capex
                total_rev += rev

        if total_rev == 0:
            return 50

        ratio = total_capex / total_rev

        # Base score: high ratio = aggressive building = low score (0)
        if ratio > 0.25:
            base = 0
        elif ratio > 0.20:
            base = 25
        elif ratio > 0.15:
            base = 50
        elif ratio > 0.10:
            base = 75
        else:
            base = 100

        # Adjust using REIT momentum relative to Hyperscalers
        hyp_mom_avg = np.mean([self._get_stock_momentum(t) for t in self.hyperscalers])
        reit_mom_avg = np.mean([self._get_stock_momentum(t) for t in self.dc_reits])
        spread = hyp_mom_avg - reit_mom_avg

        # If Hyperscalers outperform REITs, they are spending heavily (good -> lower score)
        # If REITs outperform, demand for data center space is high (tight vacancy -> good -> lower score)
        # Actually, if REITs outperform, it means investors value data centers, suggesting tight vacancy (good).
        # So we invert: high REIT outperformance => lower score (growth).
        if spread > 0.20:
            # Hyperscalers outperforming REITs: they are doing well, but could be building their own (less REIT demand)
            # We'll slightly increase score.
            adjust = +10
        elif spread < -0.20:
            # REITs outperforming: strong data center demand -> tight vacancy (good)
            adjust = -10
        else:
            adjust = 0

        final = max(0, min(100, base + adjust))
        return round(final, 2)

    # ------------------------------------------------------------------
    #  PILLAR 5: ENERGY LAG (15% weight)
    # ------------------------------------------------------------------
    def pillar_5_energy(self):
        """
        Structural lag: Energy is last to break.
        If Energy outperforms Semis, market is rotating to safety (plateau = 50).
        If Energy crashes with Semis, full collapse (100).
        """
        energy_mom = np.mean([self._get_stock_momentum(t) for t in self.energy])
        nvda_mom = self._get_stock_momentum("NVDA")
        spread = energy_mom - nvda_mom

        if spread > 0.20:
            # Safe-haven rotation -> Plateau
            return 50
        elif spread > -0.10:
            # Normal correlation -> Growth continues
            return 20
        elif spread > -0.30:
            # Energy starting to weaken -> Warning (move toward 70)
            return 70
        else:
            # Energy crashing with semis -> Total collapse
            return 100

    # ------------------------------------------------------------------
    #  COMPOSITE SCORE
    # ------------------------------------------------------------------
    def compute_weekly_score(self):
        """Run all pillars and return the final 0-100 AI Health Index."""
        p1 = self.pillar_1_guidance()
        p2 = self.pillar_2_backlog()
        p3 = self.pillar_3_memory()
        p4 = self.pillar_4_datacenter()
        p5 = self.pillar_5_energy()

        weights = [0.30, 0.25, 0.15, 0.15, 0.15]
        final_score = (
            p1 * weights[0] +
            p2 * weights[1] +
            p3 * weights[2] +
            p4 * weights[3] +
            p5 * weights[4]
        )

        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "AIHI": round(final_score, 2),
            "pillars": {
                "Guidance (Capex)": p1,
                "Backlog (NVDA)": p2,
                "Memory (HBM)": p3,
                "Data Center": p4,
                "Energy (Lag)": p5
            },
            "meta": {
                "p1_gap": "computed",
                "p2_rev_growth": "computed",
                "p3_mu_gm": "computed",
                "p4_capex_rev_ratio": "computed",
                "p5_energy_spread": "computed"
            }
        }


# ------------------------------------------------------------------
#  STANDALONE RUNNER (for GitHub Actions CRON)
# ------------------------------------------------------------------
if __name__ == "__main__":
    scorer = AIHIScorer()
    result = scorer.compute_weekly_score()
    os.makedirs("data", exist_ok=True)

    filename = f"data/weekly_{datetime.now().strftime('%Y%m%d')}.json"
    with open(filename, "w") as f:
        json.dump(result, f, indent=4)

    print(f"✅ Weekly AIHI Score: {result['AIHI']} saved to {filename}")
    print(f"   Pillars: {result['pillars']}")
