# StockScout

**Pick an NSE stock, watch it live, and get a cited Invest / Watch / Avoid verdict.**

StockScout streams the price of any of 2,500+ NSE-listed companies, redraws the analysis on every tick, and explains
every number in plain language - 12 health ratios, bankruptcy risk (Altman Z), a fair-value range with a reverse DCF,
peer comparison, price technicals and a rule-based verdict where each reason cites the statement table it came from.
Free data only (Yahoo Finance + Screener.in): no API keys, no login, no uploads.

Built as a Term-4 Agentic AI individual assignment: a domain-expert advisor for a business process (investment
screening), engineered as a real product with honest limits.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py                 # http://localhost:8501
pip install -r requirements-dev.txt && pytest -q   # 22 offline tests
```

Shareable links: `?t=TITAN` opens a company, `?t=TITAN&p=val` also opens a section (`fin`, `health`, `val`, `peers`, `ask`).

Other commands (from the project root):

```bash
python -m stockscout.data.fetch_financials INFY.NS --refresh   # refetch one company, ignore the 24h cache
python scripts/calibrate.py                                    # refresh test fixtures + print verdicts for the 3 snapshots
python scripts/build_symbols.py                                # rebuild the NSE symbol list from EQUITY_L.csv
python tests/test_fetch.py && python tests/test_symbols.py     # data-layer schema + search checks
```

## Deploy it live (Streamlit Community Cloud, free)

1. Push this folder to GitHub (`https://github.com/satyampani159/StockScout`), branch `main`.
2. Go to https://share.streamlit.io, sign in with GitHub, **Create app**: repository `satyampani159/StockScout`, branch `main`, main file `app.py`.
3. Advanced settings: Python 3.12, no secrets needed. Pick a subdomain, then **Deploy** (first build takes ~3-5 minutes).
4. Update later with `git push` - the app redeploys automatically.

What to expect live: free apps sleep after ~12 h without visitors (first visit takes ~30 s to wake); Yahoo Finance quotes are ~15 min
delayed and may be rate-limited on shared cloud IPs - the app then falls back to its cache, the committed `seed_quotes.json`
(landing cards) and three offline company snapshots, and says so on screen. Refresh the seed with `python scripts/build_seed_quotes.py`.
Runtime dependencies are in `requirements.txt`; `requirements-dev.txt` adds pytest.

## What you see

| Area | Contents |
|---|---|
| Landing | Market strip (NIFTY 50, SENSEX, USD/INR) and 10 live stock cards with a green/red change pill and a 1-month sparkline; tap a card to analyse |
| Header | Company, live price, change vs previous close, quote time, market-open badge, data mode |
| Section buttons | Financials - Health - Valuation - Peers - Ask. A click slides the panel open above the chart and pushes it down; click again to close |
| Chart | Candlestick or line + volume; ranges 1D/5D/1M/6M/1Y/5Y; SMA 20/50/200; golden/death-cross markers and a volatility-based trend projection on daily ranges; no weekend/holiday/overnight gaps; the last candle ticks with the live price |
| Verdict card | Invest/Watch/Avoid, headline, strengths/risks count, market cap, P/E vs peers, ROE, Altman Z, 52-week range bar, 1-year return, RSI, D/E, interest cover, margins |
| Insights | Rule-based bullets from price action, fundamentals trend (ROE, margin, D/E direction, revenue CAGR) and valuation (P/E vs peers, what growth today's price implies) |
| Evidence + Citations | Top 3 reasons and risks with figures, and a citations card listing each figure and its source table |
| Valuation panel | Football field (52-week, cash-flow value, peer-P/E bands vs price), Altman gauge, what-if DCF sliders |

## Project structure

```
StockScout/
  app.py                       # Streamlit entry: search, live fragments, section buttons, panels
  requirements.txt             # runtime dependencies (requirements-dev.txt adds pytest)
  pytest.ini                   # pythonpath=., testpaths=tests
  .streamlit/config.toml       # light theme, minimal toolbar
  .cache/                      # 24h statement cache + last quotes snapshot (git-ignored, auto-created)
  stockscout/
    data/                      # DATA LAYER - fetch + cache, never scores
      fetch_financials.py      #   yfinance + Screener.in -> FinancialJSON (never raises, validated, fixture fallback)
      cache.py                 #   24h file cache, live price, OHLC candles, batch quotes, NSE market hours
      symbols.py, symbols.csv  #   2,567 NSE symbols, dual-field ranked search
      fixtures/                #   offline snapshots: INFY, TITAN, RELIANCE
    engine/                    # ENGINE - pure math, no network, no UI
      ratios.py                #   12 ratios, DuPont, Altman Z/Z'', DCF-lite, reverse DCF, ratio history
      verdict_inputs.py        #   threshold policy -> cited strengths/weaknesses
      verdict.py               #   Invest/Watch/Avoid policy, peer median, reprice() for live quotes
      technicals.py            #   SMA/EMA/RSI, 52-week stats, drawdown, volatility, trend projection, crosses
    ui/                        # UI - presentation only
      theme.py                 #   design tokens, None-safe formatters, shared CSS
      charts.py                #   candles+volume+SMA+projection, financial bars, football field, peer scatter
      tabs.py                  #   Financials / Health / Valuation / Peers / Ask panels
      landing.py               #   market strip + live stock cards
      insights.py, qa.py       #   rule-based insight bullets; offline Q&A (no LLM)
  scripts/                     # calibrate.py, build_symbols.py, build_seed_quotes.py, build_logo.py
  tests/                       # test_engine.py (pytest), test_fetch.py, test_symbols.py, fixtures/
  docs/                        # demo_script.md, report_outline.md, verdict_template.md
```

Layering rule: `data` only fetches, `engine` only computes (and never imports `data` or `ui`), `ui` only renders - it
calls `data` for numbers and `engine` for every score. The verdict policy lives in exactly one place, `engine/verdict.py`.

## How data flows

```
Search (2,567 NSE names + symbols, local, instant)  ->  select company
  -> data.get_financials(ticker)     yfinance: price, market cap, P/E, annual P&L / balance sheet / cash flow (+capex, dividends, sector)
                                     Screener.in: ROE/ROCE/D-E cross-check, peer table, annual-report link
                                     24h cache; validation warnings; fixture fallback; honest "unavailable" for unknown tickers
  -> engine.build_bundle(fin)        12 ratios -> DuPont -> Altman Z -> DCF + reverse DCF -> strengths/weaknesses -> verdict
  -> ui renders cards, chart, insights, panels
  -> live loop (st.fragment, 15/30/60 s while the market is open, 120 s otherwise):
       quote -> engine.reprice(fin, price) -> full re-analysis, so P/E, market cap, Altman Z,
       valuation headroom and the verdict all follow the live price and never contradict each other
```

Fundamentals are fetched once per company (they move quarterly); only the price streams. Yahoo quotes are ~15 minutes delayed and the UI says so.

## The 12 ratios, plainly

ROE (profit per Rs.100 of owner money), ROCE (profit per Rs.100 of all money used), D/E (loan burden), current ratio
(can it pay next year's bills), interest cover, net margin / operating margin, asset turnover, receivable and inventory days,
dividend payout (% of profit), FCF margin (operating cash minus capex, per Rs.100 sold). DuPont splits ROE into margin x
turnover x leverage. Altman Z blends five balance-sheet signals into a bankruptcy score (original Z for manufacturers
> 2.99 safe / < 1.81 distress; Z'' with book equity for IT/services > 2.6 safe / < 1.1 distress; not computed for banks).
The DCF is a 3-year cash-flow range using the company's own revenue CAGR (clipped to 6-20%); the reverse DCF solves for the
10-year growth rate the current price implies.

## How the verdict is decided

- **Invest** needs everything: Altman zone safe, ROE > 18%, positive free cash flow, D/E < 0.5, and P/E within 1.2x of the peer median.
- **Avoid** triggers on any danger flag: Altman zone distress, interest cover < 2x, or ROE < 8% together with D/E > 0.5.
- Everything else is **Watch** - often a good company at a full price.
- **Banks/NBFCs** are judged on ROE (> 15%) and valuation only, never get Avoid, and carry a low-confidence note (no NIM/NPA/CASA in free data).

Every reason and risk embeds its figure and the statement table it came from; the citations card lists them.

## Data contract (FinancialJSON)

`{ticker, name, currency, units, price, mcap, pe, sector, industry, statements:{pnl, bs, cf}, ratios_src:{roe,roce,de}, peers:[{ticker,pe,mcap,roce}], ar_url, fetched_at, source, notes, warnings}`.
Statements are INR crore. `pnl` rows carry revenue/ebitda/ebit/pat/interest; `bs` rows equity/debt/assets/current items/receivables/inventory/retained earnings; `cf` rows op/inv/fin/capex/fcf/dividend_paid. `source` is `live`, `live-yfinance-only`, `sample-documented` or `unavailable`.

## Honest limits (say these in the viva)

- Yahoo data is ~15 minutes delayed, rate-limited, and gives only 4-5 years of annual statements; Screener.in scraping can break on a layout change (yfinance-only mode still works).
- Yahoo can mis-map line items; `validate_financials` flags suspicious ones (e.g. retained earnings above equity) instead of hiding them.
- The DCF is a simplified equity range, not a price target; it tends to read high-growth companies as expensive. The trend projection extends the recent trend only - it cannot see earnings or news.
- SMA on 1D/5D/1M averages the last N bars (5-minute / 15-minute / hourly), not days.
- No LLM is used (`USE_LLM = False`): insights and Q&A are rule-based templates that quote the numbers they use.
- Estimates from public data - never financial advice.
