# StockScout - report outline

## 1. Problem and users
Retail investors face thousands of listed companies and annual reports they cannot read quickly. They need a fast, honest
answer to three questions: is the business healthy, is the price fair, and what could go wrong - with numbers they can check.

## 2. Solution
StockScout is a live advisor for NSE stocks: select a company, see the price stream, and read a cited Invest / Watch / Avoid
verdict with plain-language insights. Free public data only; no keys, login or uploads.

## 3. Architecture (three layers)
- **Data** (`stockscout/data`): yfinance + Screener.in -> one FinancialJSON; 24h cache; validation warnings; fixtures; batch quotes and OHLC candles; 2,567-symbol search.
- **Engine** (`stockscout/engine`): pure functions - 12 ratios, DuPont, Altman Z, DCF + reverse DCF, technicals, verdict policy, `reprice()` so the analysis follows the live price.
- **UI** (`stockscout/ui` + `app.py`): Streamlit + Plotly; live `st.fragment` loops; section panels; rule-based insights and Q&A.
- Why layered: the engine is testable offline (19 tests) and the verdict policy exists in exactly one place.

## 4. Methods
- Ratios and DuPont from the latest fiscal year shared by P&L and balance sheet; FCF = operating cash flow - capex.
- Altman Z (original for manufacturers, Z'' with book equity for services, not computed for lenders).
- DCF-lite from the company's own revenue CAGR; reverse DCF solves the growth the price implies.
- Technicals: SMA 20/50/200, golden/death cross, RSI, 52-week position, volatility, drawdown; trend projection = log-linear drift anchored at the last price with a sqrt-time volatility band.
- Verdict: transparent thresholds (see `verdict_template.md`); every reason cites its statement table.

## 5. Agentic behaviour
The app acts as a domain-expert agent: it perceives (live quote + filings), reasons with explicit rules (ratios -> verdict), and
explains with citations. It re-plans on every tick (reprice -> re-analyse). `USE_LLM = False`; an LLM could be added to the Ask panel
using engine functions as tools, quoting only tool outputs.

## 6. Evaluation
- 19 pytest tests: contract keys, ratio reproducibility, DuPont reconciliation, Altman zones, DCF monotonicity, traceable citations,
  lender/sparse-data safety, negative-FCF handling, year alignment, payout %, reprice, technicals, projection anchoring.
- Real-browser checks on Titan, Infosys, HDFC Bank and others across all chart ranges and panels.

## 7. Limits and ethics
Delayed and rate-limited Yahoo data, 4-5 years of statements, simplified DCF, banks need sector metrics, projection extends the trend only.
Not financial advice; every figure is traceable to a statement table so users can verify it.

## 8. Demo
See `demo_script.md` (2 minutes).
