"""Offline Q&A over the already-computed numbers (no LLM). Word-boundary matching, None-safe."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .theme import cr, inr, num, pct


def _has(q: str, *words: str) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", q) for w in words)


def answer(question: str, data: Dict[str, Any], stats: Optional[Dict[str, Any]] = None) -> str:
    fin, eng, ver = data["financial"], data["engine"], data["verdict"]
    r = eng["ratios"]
    st = fin.get("statements", {})
    pnl = (st.get("pnl") or [{}])[-1]
    bs = (st.get("bs") or [{}])[-1]
    cf = (st.get("cf") or [{}])[-1]
    yr = pnl.get("year", "?")
    q = question.lower().strip()
    src = lambda s: f" _(source: {s})_"

    if _has(q, "roe", "return on equity"):
        return f"ROE is **{pct(r['roe'])}** (PAT {cr(pnl.get('pat'))} / equity {cr(bs.get('equity'))}, FY{yr})." + src("P&L + balance sheet")
    if _has(q, "roce", "capital employed"):
        return f"ROCE is **{pct(r['roce'])}**." + src("engine")
    if _has(q, "debt", "d/e", "leverage", "borrowing"):
        return f"D/E is **{num(r['debt_equity'])}x** (debt {cr(bs.get('debt'))} / equity {cr(bs.get('equity'))}, FY{yr})." + src("balance sheet")
    if _has(q, "interest", "cover"):
        return f"Interest cover is **{num(r['interest_cover'], 1)}x**." + src("engine")
    if _has(q, "current", "liquidity"):
        return f"Current ratio is **{num(r['current'])}x**." + src("engine")
    if _has(q, "npm", "net margin", "profit margin"):
        return f"Net margin is **{pct(r['npm'])}** (PAT {cr(pnl.get('pat'))} on revenue {cr(pnl.get('revenue'))}, FY{yr})." + src("P&L")
    if _has(q, "opm", "operating margin", "ebitda"):
        return f"Operating margin is **{pct(r['opm'])}** (EBITDA {cr(pnl.get('ebitda'))} on revenue {cr(pnl.get('revenue'))})." + src("P&L")
    if _has(q, "dividend", "payout"):
        return f"Dividend payout is **{pct(r['payout'])}** of profit." + src("cash-flow + P&L")
    if _has(q, "fcf", "free cash flow", "cash flow"):
        return f"FCF margin is **{pct(r['fcf_margin'])}** (operating cash {cr(cf.get('op'))}, capex {cr(cf.get('capex'))}, FCF {cr(cf.get('fcf'))})." + src("cash-flow")
    if _has(q, "altman", "z", "z-score", "bankruptcy", "distress"):
        return f"Altman Z is **{num(eng.get('altman_z'))}** - {eng.get('altman_note', '')}" + src("balance sheet + market cap")
    if _has(q, "dcf", "fair value", "valuation", "undervalued", "overvalued", "target"):
        if eng.get("dcf_low") is None:
            return f"No cash-flow valuation: {eng.get('dcf_unavailable') or 'insufficient data'}." + src("engine")
        return (f"3-year DCF range **{inr(eng['dcf_low'], 0)}-{inr(eng['dcf_high'], 0)}** vs price **{inr(fin.get('price'))}**. "
                f"The price implies ~{num((eng.get('implied_growth') or 0) * 100, 0)}% yearly FCF growth for 10 years.") + src("valuation")
    if _has(q, "p/e", "pe", "price to earnings"):
        return f"P/E is **{num(fin.get('pe'), 1)}**; peers: " + ", ".join(f"{p['ticker']} {num(p.get('pe'), 1)}" for p in fin.get("peers", [])[:5]) + "." + src("peers")
    if _has(q, "52", "52-week", "high", "low", "range"):
        if stats:
            return f"52-week range {inr(stats['low_52w'])} - {inr(stats['high_52w'])}; now {inr(stats['last'])} ({pct(stats['from_high_pct'], 1)} from the high)." + src("price history")
    if _has(q, "trend", "rsi", "momentum", "moving average", "dma", "return", "volatility"):
        if stats:
            return (f"1Y return {pct(stats.get('ret_1y'), 1, sign=True)}, RSI {num(stats.get('rsi14'), 0)}, "
                    f"50-DMA {inr(stats.get('sma50'), 0)}, 200-DMA {inr(stats.get('sma200'), 0)}, volatility {pct(stats.get('vol_ann'), 0)}.") + src("price history")
    if _has(q, "price", "quote"):
        return f"Price is **{inr(fin.get('price'))}**, market cap {cr(fin.get('mcap'))}." + src("live quote")
    if _has(q, "revenue", "sales", "growth"):
        return "Revenue (cr): " + "; ".join(f"FY{x['year']} {num(x.get('revenue'), 0)}" for x in st.get("pnl", [])) + "." + src("P&L")
    if _has(q, "profit", "pat", "earnings"):
        return "Net profit (cr): " + "; ".join(f"FY{x['year']} {num(x.get('pat'), 0)}" for x in st.get("pnl", [])) + "." + src("P&L")
    if _has(q, "peer", "peers", "compare", "rivals"):
        return "Peers: " + "; ".join(f"{p['ticker']} P/E {num(p.get('pe'), 1)}" for p in fin.get("peers", [])) + "." + src("peers")
    if _has(q, "invest", "buy", "verdict", "recommend", "should"):
        top = ver["reasons"][0] if ver.get("reasons") else "no standout signal"
        return f"Verdict: **{ver['decision']}** ({ver['horizon']}). Lead evidence: {top}" + src("verdict")
    if _has(q, "risk", "risks", "weak", "weakness", "downside"):
        return "Top risks: " + "; ".join(f"({i + 1}) {x}" for i, x in enumerate(ver.get("risks", []))) + src("verdict")
    if _has(q, "strength", "strengths", "strong"):
        return "Strengths: " + "; ".join(f"({i + 1}) {x}" for i, x in enumerate(eng["verdict_inputs"].get("strengths", [])[:4])) + src("engine")
    if _has(q, "annual report", "report", "pdf"):
        return f"Annual report: {fin.get('ar_url') or 'not available'}." + src("screener")
    return ("I answer from the numbers on this page (no LLM). Try: ROE, debt, Altman Z, DCF, P/E, peers, revenue, "
            "dividend, free cash flow, 52-week range, trend, risks, verdict.")
