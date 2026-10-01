"""Rule-based insights: turn price stats + fundamentals + valuation into plain-English bullets.

Every bullet carries the number it is based on. Tone: 'good' | 'bad' | 'info'.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .theme import num, pct

Insight = Tuple[str, str]  # (tone, text)


def _trend(series: List[Tuple[Any, Optional[float]]]) -> Optional[Tuple[float, float, int]]:
    vals = [(y, v) for y, v in series if isinstance(v, (int, float))]
    if len(vals) < 3:
        return None
    return vals[0][1], vals[-1][1], len(vals) - 1


def headline(verdict: Dict[str, Any], engine: Dict[str, Any], fin: Dict[str, Any], med_pe: Optional[float]) -> str:
    d = verdict["decision"]
    sc = verdict.get("score", {})
    if d == "Invest":
        return "Strong, financially safe business at a reasonable price."
    if d == "Avoid":
        return "Financial-stress flags outweigh the upside - avoid until they clear."
    pe, lo, hi, px = fin.get("pe"), engine.get("dcf_low"), engine.get("dcf_high"), fin.get("price")
    pricey = (isinstance(pe, (int, float)) and med_pe and pe > med_pe * 1.2) or \
             (isinstance(px, (int, float)) and isinstance(hi, (int, float)) and px > hi)
    if sc.get("pass", 0) > sc.get("fail", 0) and pricey:
        return "Good business, but the price already looks full - wait for a better entry."
    if sc.get("pass", 0) > sc.get("fail", 0):
        return "More strengths than weaknesses, but not every quality test is met - keep watching."
    return "Mixed picture - weaknesses match strengths; track the next results."


def build(fin: Dict[str, Any], engine: Dict[str, Any], stats: Dict[str, Any], hist: Dict[str, Any],
          med_pe: Optional[float]) -> List[Insight]:
    out: List[Insight] = []
    # ---- price action
    if stats:
        pos = stats.get("pos_52w")
        if pos is not None:
            if pos >= 90:
                out.append(("info", f"Trading at the top of its 52-week range ({pos:.0f}th percentile, {pct(stats['from_high_pct'], 1)} from the high) - momentum is strong but entry risk is higher."))
            elif pos <= 15:
                out.append(("info", f"Near its 52-week low ({pos:.0f}th percentile) - cheap versus its own year, but check why before buying."))
        if stats.get("above_200") is not None:
            if stats["above_200"] and stats.get("above_50"):
                out.append(("good", f"Uptrend: price is above both the 50-day (₹{stats['sma50']:,.0f}) and 200-day (₹{stats['sma200']:,.0f}) averages."))
            elif stats["above_200"] is False and stats.get("above_50") is False:
                out.append(("bad", f"Downtrend: price is below both the 50-day (₹{stats['sma50']:,.0f}) and 200-day (₹{stats['sma200']:,.0f}) averages."))
            else:
                out.append(("info", "Mixed trend: price sits between its 50- and 200-day averages."))
        rsi = stats.get("rsi14")
        if rsi is not None and rsi >= 70:
            out.append(("bad", f"RSI {rsi:.0f} - overbought; short-term pullbacks are common from here."))
        elif rsi is not None and rsi <= 30:
            out.append(("good", f"RSI {rsi:.0f} - oversold; selling may be stretched."))
        if stats.get("ret_1y") is not None:
            out.append(("good" if stats["ret_1y"] > 0 else "bad",
                        f"1-year return {pct(stats['ret_1y'], 1, sign=True)} (6M {pct(stats.get('ret_6m'), 1, sign=True)}, 1M {pct(stats.get('ret_1m'), 1, sign=True)}); "
                        f"worst fall in the last year {pct(stats.get('max_dd'), 1)}, annualised volatility {pct(stats.get('vol_ann'), 0)}."))
    # ---- fundamentals trend
    for key, label, good_up in (("roe", "Return on equity", True), ("npm", "Net margin", True),
                                ("debt_equity", "Debt/equity", False)):
        t = _trend(hist.get(key, []))
        if t:
            first, last, n = t
            delta = last - first
            if abs(delta) >= (0.25 if key == "debt_equity" else 2.0):
                good = (delta > 0) == good_up
                unit = "x" if key == "debt_equity" else "%"
                out.append(("good" if good else "bad",
                            f"{label} {'rose' if delta > 0 else 'fell'} from {num(first, 2 if unit == 'x' else 1)}{unit} to {num(last, 2 if unit == 'x' else 1)}{unit} over {n} years."))
    cagr = engine.get("revenue_cagr")
    if isinstance(cagr, (int, float)):
        out.append(("good" if cagr > 0.08 else ("info" if cagr >= 0 else "bad"),
                    f"Revenue has compounded at {cagr * 100:.1f}% a year over the last 3 years."))
    # ---- valuation
    pe = fin.get("pe")
    if isinstance(pe, (int, float)) and med_pe:
        rel = (pe / med_pe - 1) * 100
        out.append(("bad" if rel > 20 else ("good" if rel < -20 else "info"),
                    f"P/E {pe:.1f} is {abs(rel):.0f}% {'above' if rel > 0 else 'below'} the peer median ({med_pe:.1f})."))
    g = engine.get("implied_growth")
    if isinstance(g, (int, float)):
        out.append(("bad" if g > 0.15 else ("good" if g < 0.07 else "info"),
                    f"At today's price the market is assuming ~{g * 100:.0f}% yearly free-cash-flow growth for 10 years" +
                    (" - a very demanding expectation." if g > 0.15 else (" - a modest bar to clear." if g < 0.07 else "."))))
    lo, hi, px = engine.get("dcf_low"), engine.get("dcf_high"), fin.get("price")
    if all(isinstance(x, (int, float)) for x in (lo, hi, px)):
        if px < lo:
            out.append(("good", f"Price ₹{px:,.0f} is below the 3-year cash-flow value range (₹{lo:,.0f}-₹{hi:,.0f})."))
        elif px > hi:
            out.append(("bad", f"Price ₹{px:,.0f} is above the 3-year cash-flow value range (₹{lo:,.0f}-₹{hi:,.0f})."))
    return out
