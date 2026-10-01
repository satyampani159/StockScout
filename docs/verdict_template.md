# Verdict policy and wording

The policy lives in code (`stockscout/engine/verdict.py` and `verdict_inputs.py`); this page documents it for the report.

## Decision (3-year horizon)
| Call | Rule |
|---|---|
| **Invest** | Altman zone safe AND ROE > 18% AND FCF margin > 0 AND D/E < 0.5 AND P/E <= 1.2 x peer median |
| **Avoid** | Altman zone distress OR interest cover < 2x OR (ROE < 8% AND D/E > 0.5) |
| **Watch** | Everything else - often a good company at a full price |
| Banks / NBFCs | Invest if ROE > 15% and P/E within 1.2 x peers, otherwise Watch; never Avoid; low-confidence note shown |

Peer median = true median P/E of peers within 0.2x-5x of the company's market cap (all peers if fewer than two qualify).

## Signal thresholds (strength / weakness)
ROE 18% / 12% - ROCE 18% / 12% - D/E < 0.5 / > 1.0 - current ratio 1.5 / 1.2 - interest cover 8x / 3x - net margin 15% / 8% -
operating margin 20% / 10% - asset turnover 1.0 / 0.8 - receivable days 60 / 90 - inventory days 60 / 90 -
payout healthy 10-60% (weak > 80% or < 5%) - FCF margin 10% / 5% - Altman by model zone - price vs DCF range.
Banks skip current ratio, D/E, interest cover, working-capital days, asset turnover and Altman Z.

## Wording rules (the critic rule)
1. Every reason and risk embeds its figure and the statement table and fiscal year it came from, e.g.
   "ROE 32.31% (PAT Rs.5,073cr / Equity Rs.15,703cr, 2026 | Table: P&L/BS) above 18% hurdle".
2. No filler: if fewer than three strengths or risks pass a threshold, fewer are shown. **Avoid** leads with its red flags.
3. The citations card lists the figures behind the call and their source tables.
4. Text is rule-based (no LLM); estimates from public data, not financial advice.
