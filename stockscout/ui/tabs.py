"""Tab renderers: Financials, Health, Valuation, Peers, Ask."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import charts, qa
from .theme import (ACCENT, BORDER, DOWN, FAINT, MUTED, UP, WARN, cr, inr, kpi, num, pct, style)

HEALTH_ROWS = [
    # key, label, unit, direction, strong, weak, meaning
    ("roe", "Return on equity", "%", "high", 18, 12, "Profit per ₹100 of owners' money."),
    ("roce", "Return on capital", "%", "high", 18, 12, "Profit per ₹100 of all money used."),
    ("npm", "Net margin", "%", "high", 15, 8, "Paise kept from every ₹1 sold."),
    ("opm", "Operating margin", "%", "high", 20, 10, "Core operating profit before interest and tax."),
    ("debt_equity", "Debt / equity", "x", "low", 0.5, 1.0, "Loan burden per ₹1 of owners' money."),
    ("current", "Current ratio", "x", "high", 1.5, 1.2, "Can it pay next year's bills?"),
    ("interest_cover", "Interest cover", "x", "high", 8, 3, "How many times profit covers loan interest."),
    ("asset_turnover", "Asset turnover", "x", "high", 1.0, 0.8, "Sales generated per ₹1 of assets."),
    ("receivables_days", "Receivable days", "d", "low", 60, 90, "Days customers take to pay."),
    ("inventory_days", "Inventory days", "d", "low", 60, 90, "Days stock sits unsold."),
    ("payout", "Dividend payout", "%", "band", 10, 60, "Share of profit paid out (10-60% is balanced)."),
    ("fcf_margin", "FCF margin", "%", "high", 10, 5, "Real cash left per ₹1 sold."),
]
LENDER_KEYS = {"roe", "roce", "npm", "payout"}


def _spark(vals: Any) -> str:
    """Unicode sparkline for the no-pyarrow fallback."""
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    bars = "▁▂▃▄▅▆▇█"
    return "".join(bars[0 if hi == lo else int((v - lo) / (hi - lo) * 7)] for v in vals)


def safe_table(df: pd.DataFrame, **kw) -> None:
    """st.dataframe needs pyarrow (missing on some machines) - fall back to a plain HTML table."""
    try:
        st.dataframe(df, hide_index=True, width="stretch", **kw)
    except Exception:
        d = df.copy()
        for c in d.columns:
            d[c] = d[c].map(lambda v: "–" if v is None or (isinstance(v, float) and v != v)
                            else (f"{v:,.2f}" if isinstance(v, float) else v))
        st.markdown(d.to_html(index=False, border=0, classes="plain-table", escape=True), unsafe_allow_html=True)


def _status(direction: str, v: Any, strong: float, weak: float) -> str:
    if not isinstance(v, (int, float)):
        return "n/a"
    if direction == "band":
        return "Strong" if strong <= v <= weak else ("Weak" if v > 80 or v < 5 else "OK")
    if direction == "high":
        return "Strong" if v > strong else ("Weak" if v < weak else "OK")
    return "Strong" if v < strong else ("Weak" if v > weak else "OK")


# ---------------------------------------------------------------- Financials
def render_financials(fin: Dict[str, Any]) -> None:
    st_ = fin.get("statements", {})
    pnl, bs, cf = st_.get("pnl") or [], st_.get("bs") or [], st_.get("cf") or []
    with st.container(border=True):
        st.markdown("**Revenue, profit and margin**")
        if pnl:
            st.plotly_chart(charts.financial_bars(pnl), width="stretch")
            revs = [r["revenue"] for r in pnl if isinstance(r.get("revenue"), (int, float))]
            if len(revs) >= 2 and revs[0]:
                st.caption(f"Revenue went {num(revs[0], 0)} → {num(revs[-1], 0)} cr over {len(revs) - 1} years "
                           f"({pct((revs[-1] / revs[0] - 1) * 100, 1, sign=True)}). Annual statements, ₹ crore.")
        else:
            st.info("No P&L data available.")
    c1, c2, c3 = st.columns(3)
    for col, title, rows in ((c1, "Profit & loss", pnl), (c2, "Balance sheet", bs), (c3, "Cash flow", cf)):
        with col, st.expander(title, expanded=False):
            if rows:
                safe_table(pd.DataFrame(rows).set_index("year").T.reset_index().rename(columns={"index": "item"}))
    st.caption(f"Source: Yahoo Finance + Screener.in · fetched {str(fin.get('fetched_at', '?'))[:16]} · annual report: "
               f"{fin.get('ar_url') or 'n/a'}")


# ---------------------------------------------------------------- Health
def render_health(eng: Dict[str, Any], hist: Dict[str, List], lender: bool) -> None:
    rows = []
    for key, label, unit, direction, strong, weak, meaning in HEALTH_ROWS:
        if lender and key not in LENDER_KEYS:
            continue
        v = eng["ratios"].get(key)
        series = [x for _, x in hist.get(key, []) if isinstance(x, (int, float))]
        rows.append({"Ratio": label, "Value": "–" if not isinstance(v, (int, float)) else f"{v:,.2f}" + {"x": "x", "%": "%", "d": " d"}[unit],
                     "Status": _status(direction, v, strong, weak), "Trend": series or None,
                     "What it tells you": meaning})
    df = pd.DataFrame(rows)
    with st.container(border=True):
        n_strong = int((df["Status"] == "Strong").sum())
        n_weak = int((df["Status"] == "Weak").sum())
        st.markdown(f"**Health scorecard** · {n_strong} strong · {n_weak} weak · {len(df) - n_strong - n_weak} neutral")
        try:
            st.dataframe(df, hide_index=True, width="stretch", height=(len(df) + 1) * 35 + 3, column_config={
                "Trend": st.column_config.LineChartColumn("Trend (yearly)", width="small"),
                "Status": st.column_config.TextColumn(width="small")})
        except Exception:
            d2 = df.copy()
            d2["Trend"] = d2["Trend"].map(_spark)
            safe_table(d2)
        if lender:
            st.caption("Banks/NBFCs: current ratio, debt/equity, interest cover and Altman Z are not meaningful, so they are hidden.")
    dp = eng["dupont"]
    with st.container(border=True):
        st.markdown("**Why is ROE what it is? (DuPont)**")
        a, b, c, d = st.columns(4)
        a.markdown(kpi("Net margin", pct(dp.get("npm")), "profit / sales"), unsafe_allow_html=True)
        b.markdown(kpi("× Asset turnover", num(dp.get("asset_turnover")) + "x", "sales / assets"), unsafe_allow_html=True)
        c.markdown(kpi("× Leverage", num(dp.get("leverage_assets_over_equity")) + "x", "assets / equity"), unsafe_allow_html=True)
        d.markdown(kpi("= ROE", pct(dp.get("roe")), "high ROE from margin beats ROE from debt", ACCENT), unsafe_allow_html=True)


# ---------------------------------------------------------------- Valuation
def _z_gauge(eng: Dict[str, Any]) -> Optional[go.Figure]:
    z = eng.get("altman_z")
    if not isinstance(z, (int, float)):
        return None
    svc = "service" in str(eng.get("altman_model", "")).lower() or "''" in str(eng.get("altman_model", ""))
    lo, hi = (1.1, 2.6) if svc else (1.81, 2.99)
    top = max(hi * 2, z * 1.1)
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=z, number=dict(valueformat=".2f"),
        gauge=dict(axis=dict(range=[0, top]), bar=dict(color="#0f172a", thickness=.25),
                   steps=[dict(range=[0, lo], color="#fecaca"), dict(range=[lo, hi], color="#fde68a"),
                          dict(range=[hi, top], color="#bbf7d0")])))
    return style(fig, 210, legend=False)


def render_valuation(fin_fn: Callable[[], Dict[str, Any]], eng_fn: Callable[[], Dict[str, Any]],
                     med_pe: Optional[float], stats_fn: Callable[[], Dict[str, Any]]) -> None:
    fin, eng, stats = fin_fn(), eng_fn(), stats_fn()
    px = fin.get("price")
    left, right = st.columns([1.5, 1])
    with left, st.container(border=True):
        st.markdown("**Where does the price sit? (football field)**")
        bands = []
        if stats.get("low_52w") and stats.get("high_52w"):
            bands.append(dict(label="52-week range", lo=stats["low_52w"], hi=stats["high_52w"], color="#94a3b8"))
        if isinstance(eng.get("dcf_low"), (int, float)) and isinstance(eng.get("dcf_high"), (int, float)):
            bands.append(dict(label="3-yr cash-flow value", lo=eng["dcf_low"], hi=eng["dcf_high"], color=UP))
        pe = fin.get("pe")
        if isinstance(pe, (int, float)) and pe > 0 and med_pe and isinstance(px, (int, float)):
            bands.append(dict(label="At peer-median P/E (±20%)", lo=px * med_pe * 0.8 / pe, hi=px * med_pe * 1.2 / pe, color=ACCENT))
        if bands and isinstance(px, (int, float)):
            st.plotly_chart(charts.football_field(px, bands), width="stretch")
            st.caption("Dashed line = live price. Where bars sit left of the line, the price is above that yardstick.")
        else:
            st.info("Not enough data for a valuation view" + (f": {eng['dcf_unavailable']}." if eng.get("dcf_unavailable") else "."))
    with right, st.container(border=True):
        zone = eng.get("altman_zone")
        st.markdown(f"**Bankruptcy risk (Altman Z)** · {zone or 'n/a'}")
        g = _z_gauge(eng)
        if g is not None:
            st.plotly_chart(g, width="stretch")
            st.caption(f"{eng.get('altman_model')}. Red = distress, amber = grey, green = safe. Market cap feeds the score, so it moves with the price.")
        else:
            st.info(f"Not applicable: {eng.get('altman_model') or 'insufficient balance-sheet data'}.")

    with st.container(border=True):
        st.markdown("**What-if DCF - change the assumptions**")
        try:
            from ..engine.ratios import dcf_lite, get_fcf, _rows
        except Exception:
            st.info("Engine unavailable.")
            return
        base = get_fcf(_rows(fin.get("statements", {}))[2])
        mcap = fin.get("mcap")
        if base is None or base <= 0 or not mcap or not isinstance(px, (int, float)) or px <= 0:
            st.info(eng.get("dcf_unavailable") or "Free cash flow is not positive or data is missing - a cash-flow what-if is not meaningful.")
            return
        c1, c2, c3 = st.columns(3)
        g = c1.slider("FCF growth / yr", 0.0, 30.0, 10.0, 0.5, format="%.1f%%", key="w_g")
        r = c2.slider("Discount rate", 8.0, 16.0, 11.0, 0.5, format="%.1f%%", key="w_r")
        tg = c3.slider("Terminal growth", 2.0, 6.0, 4.0, 0.5, format="%.1f%%", key="w_t")
        yrs = st.select_slider("Forecast years", [3, 5, 7, 10], value=5, key="w_y")
        total = dcf_lite(base, g / 100, r / 100, tg / 100, yrs)
        if total is None:
            st.warning("Discount rate must exceed terminal growth.")
            return
        fair = total / (mcap / px)
        diff = (fair / px - 1) * 100
        a, b, c = st.columns(3)
        a.markdown(kpi("Fair value / share", inr(fair, 0), f"base FCF {cr(base)}"), unsafe_allow_html=True)
        b.markdown(kpi("Live price", inr(px, 0), ""), unsafe_allow_html=True)
        c.markdown(kpi("Upside / (downside)", pct(diff, 0, sign=True), "vs fair value", UP if diff > 0 else DOWN), unsafe_allow_html=True)
        ig = eng.get("implied_growth")
        if isinstance(ig, (int, float)):
            st.caption(f"Reverse DCF: today's price already assumes ~{ig * 100:.0f}% yearly FCF growth for 10 years. Simplified equity DCF - an estimate, not a price target.")


# ---------------------------------------------------------------- Peers
def render_peers(fin: Dict[str, Any], eng: Dict[str, Any], med_pe: Optional[float]) -> None:
    peers = fin.get("peers") or []
    if not peers:
        st.info("Peer data is unavailable (Screener.in did not return a peer table).")
        return
    rows = [{"name": fin["ticker"].replace(".NS", ""), "pe": fin.get("pe"), "mcap": fin.get("mcap"),
             "roce": eng["ratios"].get("roce"), "self": True}]
    rows += [{"name": p["ticker"].replace(".NS", ""), "pe": p.get("pe"), "mcap": p.get("mcap"),
              "roce": p.get("roce"), "self": False} for p in peers]
    c1, c2 = st.columns([1, 1.2])
    with c1, st.container(border=True):
        st.markdown(f"**Peer table** · median P/E {num(med_pe, 1)}")
        df = pd.DataFrame([{"Company": r["name"] + (" ◀" if r["self"] else ""), "P/E": r["pe"],
                            "Mkt cap (₹ cr)": r["mcap"], "ROCE %": r["roce"]} for r in rows])
        safe_table(df)
    with c2, st.container(border=True):
        st.markdown("**Price vs quality** - top-left = cheap & high quality")
        st.plotly_chart(charts.peer_scatter(rows), width="stretch")


# ---------------------------------------------------------------- Ask
def render_ask(data: Dict[str, Any], stats: Dict[str, Any], ticker: str) -> None:
    key = f"chat::{ticker}"
    hist = st.session_state.setdefault(key, [])
    with st.container(border=True):
        st.markdown("**Ask the numbers** - answers come only from the figures on this page")
        chips = ["What is the ROE?", "Is it overvalued?", "What are the risks?", "52-week range?", "Show the trend"]
        cols = st.columns(len(chips))
        picked = None
        for c, label in zip(cols, chips):
            if c.button(label, key=f"chip_{ticker}_{label}", width="stretch"):
                picked = label
        for role, text in hist:
            with st.chat_message(role):
                st.markdown(text)
        typed = st.chat_input("Ask about ROE, debt, DCF, peers, trend, risks...", key=f"ci_{ticker}")
        q = picked or typed
        if q:
            a = qa.answer(q, data, stats)
            hist.append(("user", q))
            hist.append(("assistant", a))
            with st.chat_message("user"):
                st.markdown(q)
            with st.chat_message("assistant"):
                st.markdown(a)
