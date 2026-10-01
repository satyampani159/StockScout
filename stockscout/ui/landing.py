"""Landing page: hero, market strip and live stock cards with growth/fall indicators."""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Callable, Dict, List, Optional

import streamlit as st

from .theme import DOWN, DOWN_BG, FAINT, INK, MUTED, UP, UP_BG, inr, num, pct

# (symbol, short name, tag)
STOCKS = [
    ("RELIANCE", "Reliance Industries", "Energy & Retail"), ("TCS", "Tata Consultancy", "IT Services"),
    ("HDFCBANK", "HDFC Bank", "Banking"), ("INFY", "Infosys", "IT Services"),
    ("ICICIBANK", "ICICI Bank", "Banking"), ("BHARTIARTL", "Bharti Airtel", "Telecom"),
    ("SBIN", "State Bank of India", "Banking"), ("ITC", "ITC", "FMCG"),
    ("TITAN", "Titan Company", "Consumer"), ("LT", "Larsen & Toubro", "Engineering"),
]
INDICES = [("^NSEI", "NIFTY 50"), ("^BSESN", "SENSEX"), ("USDINR=X", "USD / INR")]
TICKERS = [f"{s}.NS" for s, _, _ in STOCKS] + [t for t, _ in INDICES]


def spark_svg(vals: List[float], color: str, w: int = 160, h: int = 44) -> str:
    """Inline SVG sparkline with a soft area fill (empty string when there is no history)."""
    if not vals or len(vals) < 2:
        return f"<div style='height:{h}px'></div>"
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    pts = [(i / (len(vals) - 1) * w, h - 4 - (v - lo) / rng * (h - 8)) for i, v in enumerate(vals)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"0,{h} {line} {w},{h}"
    return (f"<svg viewBox='0 0 {w} {h}' width='100%' height='{h}' preserveAspectRatio='none'>"
            f"<polygon points='{area}' fill='{color}' opacity='.12'/>"
            f"<polyline points='{line}' fill='none' stroke='{color}' stroke-width='2' "
            f"stroke-linejoin='round' stroke-linecap='round'/></svg>")


def _change_pill(chg: Optional[float], pct_: Optional[float]) -> str:
    if pct_ is None:
        return f"<span style='color:{MUTED};font-size:.8rem'>day change n/a</span>"
    up = pct_ >= 0
    fg, bg = (UP, UP_BG) if up else (DOWN, DOWN_BG)
    return (f"<span style='display:inline-block;padding:2px 9px;border-radius:999px;font-weight:700;"
            f"font-size:.8rem;color:{fg};background:{bg}'>{'▲' if up else '▼'} {abs(pct_):.2f}%</span>"
            f"<span style='color:{fg};font-size:.8rem;margin-left:6px'>{'+' if up else '-'}{abs(chg or 0):,.2f}</span>")


def _card_html(name: str, sym: str, tag: str, q: Optional[Dict[str, Any]]) -> str:
    price = q.get("price") if q else None
    pct_ = q.get("chg_pct") if q else None
    color = UP if (pct_ or 0) >= 0 else DOWN
    edge = color if pct_ is not None else "#cbd5e1"
    return (f"<div style='border-top:3px solid {edge};margin:-4px -4px 0;padding:10px 4px 0'>"
            f"<div style='display:flex;justify-content:space-between;align-items:baseline'>"
            f"<span style='font-weight:700'>{name}</span><span class='muted'>{sym}</span></div>"
            f"<div class='muted' style='margin-bottom:6px'>{tag}</div>"
            f"<div style='font-size:1.45rem;font-weight:800;letter-spacing:-.02em'>{inr(price)}</div>"
            f"<div style='margin:2px 0 4px'>{_change_pill(q.get('chg') if q else None, pct_)}</div>"
            f"{spark_svg(q.get('spark') if q else [], color)}</div>")


def _index_html(label: str, q: Optional[Dict[str, Any]]) -> str:
    price = q.get("price") if q else None
    pct_ = q.get("chg_pct") if q else None
    color = UP if (pct_ or 0) >= 0 else DOWN
    d = 2 if label == "USD / INR" else 2
    return (f"<div style='display:flex;justify-content:space-between;align-items:center;gap:10px'>"
            f"<div><div class='kpi-l'>{label}</div>"
            f"<div style='font-size:1.25rem;font-weight:800'>{num(price, d)}</div>"
            f"<div>{_change_pill(q.get('chg') if q else None, pct_)}</div></div>"
            f"<div style='width:45%'>{spark_svg(q.get('spark') if q else [], color, 120, 40)}</div></div>")


def render(fetch_quotes: Callable, on_pick: Callable[[str], None]) -> None:
    """Draw market strip + stock cards. Meant to run inside a fragment so prices refresh live."""
    quotes, as_of, live = fetch_quotes(TICKERS)
    stamp = (datetime.fromtimestamp(as_of, ZoneInfo("Asia/Kolkata")).strftime("%d %b %H:%M") if as_of else "–")
    badge = (f"<span style='color:{UP}'>●</span> Live · updated {stamp} IST · ~15-min delayed" if live else
             f"<span style='color:{FAINT}'>●</span> Offline snapshot · {('saved ' + stamp + ' IST') if as_of else 'cached prices only'}")
    st.markdown(f"<div class='muted' style='text-align:center;margin:-4px 0 14px'>{badge}</div>", unsafe_allow_html=True)

    cols = st.columns(len(INDICES))
    for c, (tk, label) in zip(cols, INDICES):
        with c, st.container(border=True):
            st.markdown(_index_html(label, quotes.get(tk)), unsafe_allow_html=True)

    st.markdown("<div style='font-weight:700;margin:14px 0 6px'>Popular stocks <span class='muted'>· tap a card to analyse</span></div>",
                unsafe_allow_html=True)
    for row in (STOCKS[:5], STOCKS[5:]):
        cols = st.columns(5)
        for c, (sym, name, tag) in zip(cols, row):
            with c, st.container(border=True):
                st.markdown(_card_html(name, sym, tag, quotes.get(f"{sym}.NS")), unsafe_allow_html=True)
                if st.button("Analyse →", key=f"card_{sym}", width="stretch"):
                    on_pick(sym)


def features() -> None:
    items = [("Live candlesticks", "1D to 5Y candles with volume and SMA 20/50/200 that tick with the market."),
             ("12 health ratios", "ROE, ROCE, debt, margins, cash flow and Altman Z, each explained in plain words."),
             ("Cited verdict", "Invest / Watch / Avoid with the exact figures and statement tables behind it."),
             ("Reverse DCF", "See what growth today's price already assumes - and test your own what-ifs.")]
    cols = st.columns(len(items))
    for c, (title, text) in zip(cols, items):
        with c, st.container(border=True):
            st.markdown(f"<div style='height:3px;width:28px;border-radius:2px;background:#2563eb;margin-bottom:8px'></div>"
                        f"<div style='font-weight:700;margin:2px 0'>{title}</div>"
                        f"<div class='muted'>{text}</div>", unsafe_allow_html=True)
