"""StockScout - live NSE stock dashboard (Streamlit). Run: streamlit run app.py

Pick an NSE company -> fundamentals are fetched once (24h cache) and the price streams.
Every tick the whole analysis (P/E, market cap, Altman Z, valuation, verdict) is recomputed from the
live price by the pure analytics engine, so the screen never contradicts itself.

Layout: search -> live header + candlestick chart + verdict card -> insights -> tabs.
No LLM (USE_LLM = False): insights and Q&A are rule-based and quote the numbers they use.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stockscout.data.cache import fetch_ohlc, fetch_price, fetch_quotes, market_status  # noqa: E402
from stockscout.data.fetch_financials import get_financials  # noqa: E402
from stockscout.data.symbols import load_universe  # noqa: E402
from stockscout.engine.ratios import ratio_history  # noqa: E402
from stockscout.engine.technicals import cross_points, price_stats, trend_forecast  # noqa: E402
from stockscout.engine.verdict import build_bundle, peer_median_pe, reprice  # noqa: E402
from stockscout.ui import charts, insights, landing, tabs  # noqa: E402
from stockscout.ui.theme import (ACCENT, DOWN, MUTED, UP, VERDICT, cr, inject_css, inr, kpi, num, pct, pill)  # noqa: E402

USE_LLM = False

st.set_page_config(page_title="StockScout", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
inject_css()


# ------------------------------------------------------------------ data
@st.cache_data(show_spinner=False)
def _universe() -> list[tuple[str, str]]:
    return load_universe()


@st.cache_data(ttl=3600, show_spinner="Fetching statements, peers and ratios… (about 10 s)")
def _load_fin(ticker: str, nonce: int) -> dict:
    return get_financials(ticker, force_refresh=nonce > 0)


def _label_for(symbol: str) -> str | None:
    for s, n in _universe():
        if s == symbol:
            return f"{n} ({s})"
    return None


def _pick(symbol: str) -> None:
    """Queue a company switch; applied before the search box is created (widget keys are locked after)."""
    st.session_state["_pending"] = symbol


# ------------------------------------------------------------------ header / search
if "_deeplinked" not in st.session_state:  # shareable links: ?t=TITAN&p=val
    st.session_state["_deeplinked"] = True
    _t = st.query_params.get("t")
    if _t:
        st.session_state["_pending"] = _t.upper().replace(".NS", "")
if "_pending" in st.session_state:
    _lab = _label_for(st.session_state.pop("_pending"))
    if _lab:
        st.session_state["company"] = _lab
st.session_state.setdefault("cadence", 30)
st.session_state.setdefault("nonce", {})
top = st.columns([1.1, 3.4, 0.7])
top[0].markdown("<div style='font-weight:800;font-size:1.15rem;padding-top:6px'>📈 Stock<span style='color:#2563eb'>Scout</span></div>",
                unsafe_allow_html=True)
labels = [f"{n} ({s})" for s, n in _universe()]
choice = top[1].selectbox("Company", labels, index=None, key="company", label_visibility="collapsed",
                          placeholder=f"Search {len(labels):,} NSE companies by name or symbol…")
with top[2].popover("⚙ Live", width="stretch"):
    st.session_state["cadence"] = st.selectbox("Refresh every (s)", [15, 30, 60], index=[15, 30, 60].index(
        st.session_state["cadence"]), help="Price/analysis re-poll cadence while the market is open.")
    st.caption("Quotes from Yahoo Finance are ~15 min delayed. Fundamentals are fetched once per company and cached 24h.")

if not choice:
    st.markdown(
        "<div style='text-align:center;padding:2.2rem 0 .6rem'>"
        "<div style='display:inline-block;padding:3px 12px;border-radius:999px;background:#dbeafe;color:#1d4ed8;"
        "font-weight:600;font-size:.78rem;margin-bottom:10px'>NSE · live prices · cited analysis</div>"
        "<div style='font-size:clamp(2rem,5vw,3.1rem);font-weight:800;letter-spacing:-.03em;line-height:1.08'>"
        "Know what you own.<br><span style='background:linear-gradient(90deg,#2563eb,#16a34a);-webkit-background-clip:text;"
        "-webkit-text-fill-color:transparent'>Before the market moves.</span></div>"
        "<div class='muted' style='font-size:1.02rem;margin:10px auto 0;max-width:640px'>Live candlesticks, 12 health ratios, "
        "bankruptcy risk and a fair-value range for any of 2,500+ NSE companies - ending in a cited "
        "Invest / Watch / Avoid verdict.</div></div>", unsafe_allow_html=True)

    def _landing() -> None:
        def _go(sym: str) -> None:
            _pick(sym)
            st.rerun()
        landing.render(fetch_quotes, _go)

    st.fragment(run_every="60s" if market_status()["open"] else "300s")(_landing)()
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    landing.features()
    st.markdown("<div class='disclaimer'>Public data, simplified models, estimates - not financial advice.</div>", unsafe_allow_html=True)
    st.stop()

SYMBOL = choice.rsplit("(", 1)[-1].rstrip(")")
TICKER = f"{SYMBOL}.NS"
nonce = st.session_state["nonce"].get(TICKER, 0)
fin0 = _load_fin(TICKER, nonce)
def _network_blocked() -> bool:
    """True when Yahoo Finance is unreachable from this network (firewall/proxy/offline)."""
    try:
        import requests
        requests.get("https://query2.finance.yahoo.com/v8/finance/chart/TITAN.NS", timeout=6,
                     headers={"User-Agent": "Mozilla/5.0"})
        return False
    except Exception:
        return True


if not fin0.get("statements", {}).get("pnl"):
    if _network_blocked():
        st.error(f"Cannot reach Yahoo Finance from this network, so {choice} could not be loaded. "
                 "A firewall, proxy or captive portal is probably blocking it (try another network or hotspot). "
                 "Companies fetched earlier still open from the 24h cache.")
    else:
        st.error(f"Could not load financial statements for {choice}. Yahoo Finance may be rate-limiting, "
                 "or the company has no filings in its database.")
    if st.button("↻ Retry live fetch"):
        st.session_state["nonce"][TICKER] = nonce + 1
        _load_fin.clear()
        st.rerun()
    st.stop()

MODE = {"live": "Live statements", "live-yfinance-only": "Live statements (no peer data)"}.get(
    str(fin0.get("source")), "Saved snapshot")


# ------------------------------------------------------------------ live state (shared, cheap: TTL-cached fetches)
def _live() -> dict:
    cadence = st.session_state["cadence"]
    mkt = market_status()
    px, pstat = fetch_price(TICKER, ttl_s=cadence)
    live = px if isinstance(px, (int, float)) and px > 0 else fin0.get("price")
    fin = reprice(fin0, live)
    bundle = build_bundle(fin)
    daily = fetch_ohlc(TICKER, "1Y")
    stats = price_stats(daily, live) if daily else {}
    st.session_state["bundle"], st.session_state["stats"] = bundle, stats
    intraday = fetch_ohlc(TICKER, "1D")
    prev = daily[-2]["c"] if len(daily) >= 2 else None
    chg = (live - prev) if isinstance(live, (int, float)) and prev else None
    chg_pct = (chg / prev * 100) if chg is not None and prev else None
    tick = intraday[-1]["t"][11:16] if intraday else None
    return dict(
        mkt=mkt, live=live, fin=fin, bundle=bundle, eng=bundle["engine"], ver=bundle["verdict"], daily=daily,
        stats=stats, prev=prev, chg=chg, chg_pct=chg_pct, col=UP if (chg or 0) >= 0 else DOWN,
        when=f"quote at {tick} IST" if tick else "last close",
        status={"live": "live", "live-cached": "live", "cache-fallback": "from cache (feed throttled)",
                "unavailable": "price feed unavailable"}.get(pstat, pstat),
        med=peer_median_pe(fin))


def run_every(default: int):
    return f"{default}s" if market_status()["open"] else "120s"


# ------------------------------------------------------------------ 1) live header
def header() -> None:
    d = _live()
    mkt, live, fin, bundle, eng, ver, daily, stats, prev, chg, chg_pct, col, when, status, med = (d[k] for k in ('mkt', 'live', 'fin', 'bundle', 'eng', 'ver', 'daily', 'stats', 'prev', 'chg', 'chg_pct', 'col', 'when', 'status', 'med',))

    # ---- header
    h1, h2 = st.columns([2.2, 1])
    with h1:
        sector = fin0.get("sector") or ""
        st.markdown(f"<div class='hero-name'>{fin['name']} <span class='muted'>· {SYMBOL} · {sector}</span></div>"
                    f"<div class='hero-price'>{inr(live)} <span style='font-size:1.1rem;color:{col};font-weight:700'>"
                    f"{'▲' if (chg or 0) >= 0 else '▼'} {num(abs(chg) if chg is not None else None)} ({pct(chg_pct, 2, sign=True)})</span></div>"
                    f"<div class='muted'>{when} · {status} · ~15-min delayed</div>", unsafe_allow_html=True)
    with h2:
        dot = UP if mkt["open"] else MUTED
        st.markdown(f"<div style='text-align:right'><span style='color:{dot}'>●</span> "
                    f"<span class='muted'>{mkt['label']}</span><br><span class='muted'>{MODE}"
                    f" · FY{(fin['statements']['pnl'][-1] or {}).get('year', '?')} · {datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%H:%M:%S')} IST</span></div>",
                    unsafe_allow_html=True)
        if st.button("↻ Refetch fundamentals", key="refetch", help="Ignores the 24h cache and re-fetches statements."):
            st.session_state["nonce"][TICKER] = nonce + 1
            _load_fin.clear()
            st.rerun()


_every = run_every(st.session_state["cadence"])
st.fragment(run_every=_every)(header)()

# ------------------------------------------------------------------ 2) section buttons + slide-down panel
NAV = {"📊 Financials": "fin", "🩺 Health": "health", "⚖️ Valuation": "val", "👥 Peers": "peers", "💬 Ask": "ask"}
_p = {"fin": "📊 Financials", "health": "🩺 Health", "val": "⚖️ Valuation", "peers": "👥 Peers", "ask": "💬 Ask"}.get(
    st.query_params.get("p", ""))
if _p and "nav" not in st.session_state:
    st.session_state["nav"] = _p
sel = st.segmented_control("Explore", list(NAV), selection_mode="single", default=None, key="nav",
                           width="stretch", label_visibility="collapsed",
                           help="Open a section - it slides down and pushes the chart below. Click it again to close.")
if sel:
    with st.container(border=True, key="panel"):
        pid = NAV[sel]
        bundle0 = build_bundle(fin0)
        eng0 = bundle0["engine"]
        st.markdown(f"<div style='display:flex;justify-content:space-between;align-items:baseline'>"
                    f"<span style='font-weight:700;font-size:1.05rem'>{sel}</span>"
                    f"<span class='muted'>click the highlighted button again to close</span></div>", unsafe_allow_html=True)
        if pid == "fin":
            tabs.render_financials(fin0)
        elif pid == "health":
            tabs.render_health(eng0, ratio_history(fin0), eng0.get("sector_kind") == "financial")
        elif pid == "val":
            def _val() -> None:
                px_, _ = fetch_price(TICKER, ttl_s=st.session_state["cadence"])
                f = reprice(fin0, px_ if isinstance(px_, (int, float)) and px_ > 0 else fin0.get("price"))
                e = build_bundle(f)["engine"]
                tabs.render_valuation(lambda: f, lambda: e, peer_median_pe(f), lambda: st.session_state.get("stats", {}))
            st.fragment(run_every=run_every(st.session_state["cadence"]))(_val)()
        elif pid == "peers":
            tabs.render_peers(fin0, eng0, peer_median_pe(fin0))
        elif pid == "ask":
            _l = _live()
            tabs.render_ask(_l["bundle"], _l["stats"], TICKER)


# ------------------------------------------------------------------ 3) live chart, verdict, insights, citations
def board() -> None:
    d = _live()
    mkt, live, fin, bundle, eng, ver, daily, stats, prev, chg, chg_pct, col, when, status, med = (d[k] for k in ('mkt', 'live', 'fin', 'bundle', 'eng', 'ver', 'daily', 'stats', 'prev', 'chg', 'chg_pct', 'col', 'when', 'status', 'med',))

    # ---- chart + verdict card
    cc, vc = st.columns([2.1, 1])
    with cc, st.container(border=True):
        k1, k2 = st.columns([2.4, 1.2])
        rk = k1.segmented_control("Range", ["1D", "5D", "1M", "6M", "1Y", "5Y"], default="6M", key="rk",
                                  label_visibility="collapsed") or "6M"
        kind = k2.segmented_control("Type", ["Candles", "Line"], default="Candles", key="ck",
                                    label_visibility="collapsed") or "Candles"
        k3 = st.container()
        is_daily = rk in ("6M", "1Y", "5Y")
        if is_daily:
            opts = ["SMA 20", "SMA 50", "SMA 200", "Trend projection", "Volume"]
        else:  # projection only makes sense on daily bars; averages work on every range
            opts = ["SMA 20", "SMA 50", "SMA 200", "Volume"]
        dflt = ["SMA 50", "SMA 200", "Volume"]
        ov = k3.pills("Overlays", opts, selection_mode="multi", default=dflt, key="ov_d" if is_daily else "ov_i",
                      label_visibility="collapsed") or []
        if rk in ("6M", "1Y"):
            long = fetch_ohlc(TICKER, "2Y") or daily  # 2 years so the 200-day average spans the whole view
            series, history = (long[-126:] if rk == "6M" else long[-252:]), long
        elif rk == "5Y":
            long = fetch_ohlc(TICKER, "7Y") or fetch_ohlc(TICKER, "5Y")  # daily bars; extra 2y warms up the SMAs
            series, history = long[-1260:], long
        else:  # intraday: same-interval but longer history so SMA 50/200 are warmed up
            series, history = fetch_ohlc(TICKER, rk), (fetch_ohlc(TICKER, "H" + rk) or None)
        if not series:
            st.info("Price history is unavailable right now (Yahoo Finance did not respond).")
        else:
            series = charts.with_live_bar(series, live)
            if history:
                history = charts.with_live_bar(history, live)
            closes = [c["c"] for c in (history or series)]
            fc = trend_forecast(closes) if ("Trend projection" in ov and is_daily) else None
            smas = tuple(int(o.split()[1]) for o in ov if o.startswith("SMA"))
            crosses = cross_points(closes) if (history and is_daily and {50, 200} <= set(smas)) else None
            short = [n for n in smas if n > len(closes)]
            fig = charts.candle_chart(series, rk, TICKER, kind=kind, smas=smas, volume="Volume" in ov,
                                      prev_close=prev, history=history, forecast=fc, crosses=crosses)
            st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "scrollZoom": True})
            if is_daily:
                parts = []
                if stats.get("above_50") is not None and stats.get("above_200") is not None:
                    if stats["above_50"] and stats["above_200"]:
                        msg = "Price is **above** both the 50- and 200-day averages - an uptrend."
                    elif not stats["above_50"] and not stats["above_200"]:
                        msg = "Price is **below** both the 50- and 200-day averages - a downtrend."
                    else:
                        msg = "Price is between the 50- and 200-day averages - the trend is unclear."
                    parts.append(f"{msg} (SMA 50 {inr(stats['sma50'], 0)}, SMA 200 {inr(stats['sma200'], 0)})")
                if fc:
                    parts.append(f"**Trend projection:** if the recent {fc['lookback']}-day trend continues, about "
                                 f"**{inr(fc['mid'][-1], 0)}** in {len(fc['mid'])} trading days "
                                 f"(90% range {inr(fc['lo'][-1], 0)}-{inr(fc['hi'][-1], 0)}; fit R² {fc['r2']:.2f}). "
                                 "This extends the past trend - it cannot see earnings or news.")
                st.caption("  \n".join(parts) if parts else "Not enough history for moving averages.")
                st.caption("SMA = average closing price over the last N days. Short averages (20) react fast; long ones (200) show "
                           "the big trend. Price above them is bullish, below is bearish. ▲ golden / ▼ death cross = the 50 crossing the 200.")
            else:
                bar = {"1D": "5-minute", "5D": "15-minute", "1M": "hourly"}.get(rk, "")
                st.caption(f"Intraday view: each SMA averages the last N {bar} bars (SMA 50 = last 50 bars). "
                           "Switch to 6M / 1Y / 5Y for the day-based trend averages and the projection.")
            if short:
                st.caption("⚠ " + ", ".join(f"SMA {n}" for n in short) + f" needs more history than is available ({len(closes)} bars).")

    lender_ = eng.get("sector_kind") == "financial"
    with vc, st.container(border=True):
        fg, bg = VERDICT.get(ver["decision"], (MUTED, "#f1f5f9"))
        st.markdown(f"<div class='muted'>3-year verdict</div><div class='verdict-word' style='color:{fg}'>{ver['decision']}</div>"
                    f"<div style='margin:6px 0 8px;font-size:.92rem'>{insights.headline(ver, eng, fin, med)}</div>"
                    f"{pill(str(ver['score']['pass']) + ' strengths', '#166534', '#dcfce7')} "
                    f"{pill(str(ver['score']['fail']) + ' risks', '#991b1b', '#fee2e2')}", unsafe_allow_html=True)
        st.divider()
        a, b = st.columns(2)
        a.markdown(kpi("Market cap", cr(fin.get("mcap"))), unsafe_allow_html=True)
        b.markdown(kpi("P/E", num(fin.get("pe"), 1), f"peers {num(med, 1)}"), unsafe_allow_html=True)
        a.markdown(kpi("ROE", pct(eng["ratios"]["roe"])), unsafe_allow_html=True)
        z = eng.get("altman_z")
        b.markdown(kpi("Altman Z", num(z), (eng.get("altman_zone") or "n/a").title() if z is not None else "n/a for lenders"),
                   unsafe_allow_html=True)
        if stats.get("pos_52w") is not None:
            st.markdown(f"<div class='kpi-l'>52-week range</div>"
                        + charts.range_bar_html(stats["pos_52w"], stats["low_52w"], stats["high_52w"], lambda v: inr(v, 0)),
                        unsafe_allow_html=True)
        st.divider()
        rr = eng["ratios"]
        c1_, c2_ = st.columns(2)
        r1 = stats.get("ret_1y")
        c1_.markdown(kpi("1-year return", pct(r1, 1, sign=True), "price change", UP if (r1 or 0) >= 0 else DOWN), unsafe_allow_html=True)
        rsi_v = stats.get("rsi14")
        c2_.markdown(kpi("RSI (14)", num(rsi_v, 0), "overbought" if (rsi_v or 0) >= 70 else ("oversold" if (rsi_v or 50) <= 30 else "neutral")),
                     unsafe_allow_html=True)
        if not lender_:
            c1_.markdown(kpi("Debt / equity", num(rr.get("debt_equity")) + "x", "lower is safer"), unsafe_allow_html=True)
            c2_.markdown(kpi("Interest cover", num(rr.get("interest_cover"), 1) + "x", "profit vs interest"), unsafe_allow_html=True)
        c1_.markdown(kpi("Net margin", pct(rr.get("npm")), "kept per ₹100 sold"), unsafe_allow_html=True)
        c2_.markdown(kpi("FCF margin", pct(rr.get("fcf_margin")), "real cash per ₹100 sold"), unsafe_allow_html=True)
        for w in ver.get("warnings", [])[:2]:
            st.caption(f"⚠ {w}")

    # ---- insights + evidence
    hist = ratio_history(fin)
    ins = insights.build(fin, eng, stats, hist, med)
    i1, i2 = st.columns([1.15, 1])
    with i1, st.container(border=True):
        st.markdown("**Insights from the numbers**")
        colr = {"good": UP, "bad": DOWN, "info": "#94a3b8"}
        if ins:
            st.markdown("".join(f"<div class='insight'><span class='dot' style='background:{colr[t]}'></span><span>{x}</span></div>"
                                for t, x in ins), unsafe_allow_html=True)
        else:
            st.caption("Not enough data to generate insights.")
    with i1, st.container(border=True):
        st.markdown("**Citations** <span class='muted'>· every figure traces to a statement table</span>", unsafe_allow_html=True)
        st.markdown("".join(
            f"<div class='insight'><span class='dot' style='background:#2563eb'></span>"
            f"<span>{c['figure']} <span class='muted'>({c['source']})</span></span></div>" for c in ver["citations"]),
            unsafe_allow_html=True)
    with i2, st.container(border=True):
        st.markdown("**Evidence behind the call**")
        for x in ver["reasons"]:
            st.success(x, icon="✅")
        for x in ver["risks"]:
            st.warning(x, icon="⚠️")
        if not ver["reasons"] and not ver["risks"]:
            st.caption("No signal met a threshold either way.")


st.fragment(run_every=_every)(board)()

st.markdown("<div class='disclaimer'>StockScout · public data (Yahoo Finance, Screener.in), simplified models and rule-based text. "
            "Estimates for learning - not financial advice.</div>", unsafe_allow_html=True)
