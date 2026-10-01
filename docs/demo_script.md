# StockScout - 2-minute demo script

Setup: `streamlit run app.py`, browser at http://localhost:8501, market hours if possible (otherwise say "last close").

## 0:00-0:20 Landing
- Landing page: "Know what you own." Point at the market strip (NIFTY, SENSEX, USD/INR) and the 10 live cards.
- Say: "Green and red pills show today's move; the sparkline is the last month. Prices refresh by themselves."
- Tap the **Titan** card.

## 0:20-0:50 Live chart
- Header: live price, change vs previous close, "quote at HH:MM IST", market-open badge.
- Chart: switch 1D -> 6M -> 5Y. Toggle Candles/Line. Turn on SMA 50 and 200: "price above both = uptrend".
- On 6M switch on **Trend projection**: "this extends the last 90 days, with a widening 90% range - it cannot see news."

## 0:50-1:20 Verdict and insights
- Verdict card: Watch, "good business, price looks full". Read the 52-week bar, P/E 71 vs peers 38.
- Insights: "market assumes ~28% yearly FCF growth for 10 years" - the reverse DCF.
- Evidence: read 2 reasons and 2 risks aloud; point to the **Citations** card: every figure names its statement table.

## 1:20-1:45 Sections
- Click **Valuation**: the panel slides open above the chart. Football field: price vs 52-week, cash-flow value, peer-P/E band.
  Move the what-if sliders. Click **Valuation** again to close.
- Click **Health**: 12 ratios with status and yearly trend lines; DuPont explains ROE.

## 1:45-2:00 Ask + limits
- Click **Ask**, tap "Is it overvalued?": a cited answer from the page numbers (no LLM).
- Close with the limits: delayed Yahoo data, simplified DCF, banks get a low-confidence note, not financial advice.

Backup if Yahoo is unreachable: companies already opened load from the 24h cache (`.cache/`); the landing cards show the last saved prices.
