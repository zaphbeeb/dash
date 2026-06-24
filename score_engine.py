import yfinance as yf
import pandas as pd
from datetime import datetime
import json
import os

class AIHIScorer:
    def __init__(self):
        # Define all tickers we need
        self.hyperscalers = ["AMZN", "MSFT", "GOOGL", "META"]
        self.semis = ["NVDA"]
        self.memory = ["MU"]          # Micron is the best US-traded HBM proxy
        self.energy = ["CEG", "VST"]
        self.dc_reits = ["DLR", "EQIX"]
        
        # Combine and deduplicate
        self.all_tickers = list(set(
            self.hyperscalers + self.semis + self.memory + self.energy + self.dc_reits
        ))
        
        # Cache for batch data (stored per instance run)
        self._price_cache = None

    def _fetch_all_prices(self, period="6mo"):
        """
        Fetch ALL required tickers in a single batch request.
        This prevents yfinance throttling (1 call vs 11+ calls).
        """
        if self._price_cache is not None:
            return self._price_cache

        try:
            # group_by='ticker' returns a dict: { 'NVDA': DataFrame, 'AMZN': DataFrame, ... }
            data = yf.download(
                tickers=self.all_tickers,
                period=period,
                group_by='ticker',
                auto_adjust=True,
                threads=True,          # Parallelize download internally
                progress=False         # Keep logs clean
            )
            self._price_cache = data
            return data
        except Exception as e:
            print(f"⚠️ Batch download failed: {e}")
            return {}

    # ---------- Helper metrics from batch data ----------
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

    def _get_monthly_change(self, ticker):
        """1-month price performance (approx 21 trading days)."""
        data = self._fetch_all_prices()
        if ticker not in data or data[ticker].empty or len(data[ticker]) < 21:
            return 0.0
        df = data[ticker]
        return (df['Close'].iloc[-1] / df['Close'].iloc[-21]) - 1

    # ---------- PILLAR SCORING (0 to 100) ----------
    def pillar_1_guidance(self):
        """
        [30% weight] Hyperscaler Capex Guidance.
        In production: parse SEC 10-Q/earnings calls.
        For demo, we use a simulated sentiment based on week of year.
        """
        week = datetime.now().isocalendar()[1]
        # Simulate cycle: Q1 growth, Q3 plateau, Q4 slowdown
        if week < 12:
            return 0
        elif week < 30:
            return 50
        else:
            return 80

    def pillar_2_backlog(self):
        """
        [25% weight] NVDA backlog / lead times.
        Using NVDA's price momentum vs 200MA as a proxy for order health.
        """
        nvda_mom = self._get_stock_momentum("NVDA")
        if nvda_mom > 0.15:      # Strongly above 200MA -> backlog expanding
            return 0
        elif nvda_mom > -0.10:   # Near 200MA -> plateau
            return 50
        else:                    # Below 200MA -> backlog compressing
            return 100

    def pillar_3_memory(self):
        """
        [15% weight] HBM/DRAM pricing.
        Using MU's 1-month change as proxy for spot/contract pricing.
        """
        mu_change = self._get_monthly_change("MU")
        if mu_change > 0.10:      # Prices up >10% -> bottleneck remains
            return 0
        elif mu_change > -0.05:   # Flat to slight down -> plateau
            return 50
        else:                     # Crash >5% -> oversupply / demand drop
            return 100

    def pillar_4_datacenter(self):
        """
        [15% weight] Data center vacancy & capex/revenue ratio.
        We compare Hyperscaler momentum vs REIT momentum.
        If hyperscalers outperform REITs, they are spending heavily (0).
        If REITs outperform, demand is weakening (100).
        """
        hyp_avg = sum([self._get_stock_momentum(t) for t in self.hyperscalers]) / len(self.hyperscalers)
        reit_avg = sum([self._get_stock_momentum(t) for t in self.dc_reits]) / len(self.dc_reits)
        spread = hyp_avg - reit_avg

        if spread > 0.20:
            return 0
        elif spread > -0.10:
            return 50
        else:
            return 100

    def pillar_5_energy(self):
        """
        [15% weight] Power/Energy – structurally last to break.
        If Energy outperforms Semis -> rotation to safety (Plateau = 50).
        If Energy crashes with Semis -> total collapse (100).
        """
        energy_avg = sum([self._get_stock_momentum(t) for t in self.energy]) / len(self.energy)
        semi_mom = self._get_stock_momentum("NVDA")
        spread = energy_avg - semi_mom

        if spread > 0.20:        # Energy is the safe haven -> plateau confirmed
            return 50
        elif spread > -0.15:     # Normal growth spread
            return 20
        else:                    # Energy crashing too -> structural collapse
            return 100

    def compute_weekly_score(self):
        """Calculate final 0-100 AI Health Index (AIHI)."""
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
            }
        }


# ----- Standalone runner for weekly CRON job -----
if __name__ == "__main__":
    scorer = AIHIScorer()
    result = scorer.compute_weekly_score()
    
    # Ensure data folder exists
    os.makedirs("data", exist_ok=True)
    
    filename = f"data/weekly_{datetime.now().strftime('%Y%m%d')}.json"
    with open(filename, "w") as f:
        json.dump(result, f, indent=4)
    
    print(f"✅ Weekly AIHI Score: {result['AIHI']} saved to {filename}")
