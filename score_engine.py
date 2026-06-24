import yfinance as yf
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta

class AIHIScorer:
    def __init__(self):
        self.hyperscalers = ["AMZN", "MSFT", "GOOGL", "META"]
        self.semis = ["NVDA"]
        self.memory = ["MU", "SKHYF"]  # SK Hynix ADR
        self.energy = ["CEG", "VST"]
        self.dc_reits = ["DLR", "EQIX"]

    def get_stock_momentum(self, ticker):
        """Fetches 20-day and 200-day MA to gauge momentum."""
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if len(hist) < 200:
            return 0
        last_close = hist['Close'].iloc[-1]
        ma_20 = hist['Close'].rolling(20).mean().iloc[-1]
        ma_200 = hist['Close'].rolling(200).mean().iloc[-1]
        # If price > 200MA, bullish. If below, bearish.
        return (last_close / ma_200) - 1

    def pillar_1_guidance(self):
        """Scrape sentiment from latest 10-Q filings via SEC API."""
        # Simplified: Use a placeholder - In production, pull from SEC EDGAR.
        # We check for specific bearish phrases.
        bearish_phrases = ["digestion", "prioritization", "deceleration", "efficiency"]
        # Simulate a sentiment count from recent news/filings
        # Assume we parsed text and counted occurrences.
        # Score logic: 0 occurrences = 0; 1-2 = 25; 3-4 = 50; 5+ = 100
        # For demo, returning a dynamic value based on current date/week.
        week = datetime.now().isocalendar()[1]
        # Simulate cycle: Weeks 1-10 growth, 20-30 plateau, 40-52 collapse.
        if week < 10:
            return 0
        elif week < 30:
            return 50
        else:
            return 80

    def pillar_2_backlog(self):
        """NVDA backlog via 10-Q purchase obligations."""
        # Real implementation parses NVDA's 10-Q. Simulate with stock momentum.
        nvda_momentum = self.get_stock_momentum("NVDA")
        if nvda_momentum > 0.15:  # Strong growth
            return 0
        elif nvda_momentum > -0.10:
            return 50
        else:
            return 100

    def pillar_3_memory(self):
        """HBM pricing simulation."""
        # In reality, scrape DRAMeXchange. Simulate using MU stock performance.
        mu = yf.Ticker("MU")
        hist = mu.history(period="1mo")
        if len(hist) < 2:
            return 50
        pct_change = (hist['Close'].iloc[-1] / hist['Close'].iloc[0]) - 1
        if pct_change > 0.10:
            return 0
        elif pct_change > -0.05:
            return 50
        else:
            return 100

    def pillar_4_datacenter(self):
        """Vacancy and Capex/Revenue ratio."""
        # Simplified: Track hyperscaler price performance vs. REITs.
        dc_avg = sum([self.get_stock_momentum(t) for t in self.dc_reits]) / len(self.dc_reits)
        hyp_avg = sum([self.get_stock_momentum(t) for t in self.hyperscalers]) / len(self.hyperscalers)
        # If hyperscalers outperform REITs, they are spending heavily (0). If REITs outperform, demand is weak (100).
        ratio = hyp_avg - dc_avg
        if ratio > 0.20:
            return 0
        elif ratio > -0.10:
            return 50
        else:
            return 100

    def pillar_5_energy(self):
        """Energy is structurally late. If energy outperforms semis, it's a plateau (50). If it crashes hard, collapse (100)."""
        energy_avg = sum([self.get_stock_momentum(t) for t in self.energy]) / len(self.energy)
        semi_mom = self.get_stock_momentum("NVDA")
        spread = energy_avg - semi_mom
        if spread > 0.20:  # Energy is safe-haven -> plateau
            return 50
        elif spread > -0.15:
            return 20  # Still growing
        else:  # Energy crashing with semis -> collapse
            return 100

    def compute_weekly_score(self):
        """Run all pillars and compute the final 0-100 index."""
        p1 = self.pillar_1_guidance()
        p2 = self.pillar_2_backlog()
        p3 = self.pillar_3_memory()
        p4 = self.pillar_4_datacenter()
        p5 = self.pillar_5_energy()

        weights = [0.30, 0.25, 0.15, 0.15, 0.15]
        final_score = (p1*weights[0] + p2*weights[1] + p3*weights[2] + 
                       p4*weights[3] + p5*weights[4])
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "AIHI": round(final_score, 2),
            "pillars": {"Guidance": p1, "Backlog": p2, "Memory": p3, 
                        "DataCenter": p4, "Energy": p5}
        }

# For weekly cron job
if __name__ == "__main__":
    scorer = AIHIScorer()
    result = scorer.compute_weekly_score()
    with open(f"data/weekly_{datetime.now().strftime('%Y%m%d')}.json", "w") as f:
        json.dump(result, f)
    print(f"Weekly AIHI Score: {result['AIHI']}")
