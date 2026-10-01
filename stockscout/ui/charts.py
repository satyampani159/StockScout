"""Plotly charts: candlesticks + volume + SMA, financial bars, football field, peer scatter."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .theme import ACCENT, BORDER, DOWN, FAINT, INK, MUTED, UP, WARN, style

INTRADAY = ("1D", "5D", "1M")
SMA_COLORS = {20: "#f59e0b", 50: "#2563eb", 200: "#7c3aed"}


def _sma(vals: List[float], n: int) -> List[Optional[float]]:
    out, run = [], 0.0
    for i, v in enumerate(vals):
        run += v
        if i >= n:
            run -= vals[i - n]
        out.append(run / n if i >= n - 1 else None)
    return out


def with_live_bar(candles: List[Dict[str, Any]], live: Optional[float]) -> List[Dict[str, Any]]:
    """Copy of candles whose last bar is stretched to the live price (so the chart 'ticks')."""
    if not candles or not isinstance(live, (int, float)) or live <= 0:
        return candles
    out = [dict(c) for c in candles]
    last = out[-1]
    last["c"] = round(float(live), 2)
    last["h"] = max(last["h"], last["c"])
    last["l"] = min(last["l"], last["c"])
    return out


def candle_chart(candles: List[Dict[str, Any]], range_key: str, ticker: str, kind: str = "Candles",
                 smas: tuple = (50, 200), volume: bool = True, prev_close: Optional[float] = None,
                 history: Optional[List[Dict[str, Any]]] = None, forecast: Optional[Dict[str, Any]] = None,
                 crosses: Optional[List[Dict[str, Any]]] = None) -> go.Figure:
    """Candlestick (or line) + volume + SMAs. `history` = longer daily series so SMAs warm up fully.

    forecast: {mid, lo, hi} lists from technicals.trend_forecast (drawn dashed with a shaded band).
    crosses: [{i, kind}] 50/200 SMA cross indexes into `history` (golden = up, death = down).
    """
    src = history if history else candles
    df_all = pd.DataFrame(src)
    df_all["t"] = pd.to_datetime(df_all["t"])
    df = pd.DataFrame(candles)
    df["t"] = pd.to_datetime(df["t"])
    start = df["t"].iloc[0]

    rows = 2 if volume else 1
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        row_heights=[0.76, 0.24] if volume else [1.0])
    lo_y, hi_y = float(df["l"].min()), float(df["h"].max())
    if kind == "Line":
        floor = lo_y - (hi_y - lo_y) * 0.08
        # invisible floor trace + fill='tonexty' => area fills to the visible minimum, NOT down to zero
        fig.add_trace(go.Scatter(x=df["t"], y=[floor] * len(df), mode="lines", line=dict(width=0),
                                 hoverinfo="skip", showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["t"], y=df["c"], mode="lines", name="Close",
                                 line=dict(color=ACCENT, width=2.2), fill="tonexty",
                                 fillcolor="rgba(37,99,235,.10)"), row=1, col=1)
    else:
        fig.add_trace(go.Candlestick(
            x=df["t"], open=df["o"], high=df["h"], low=df["l"], close=df["c"], name="Price",
            increasing=dict(line=dict(color=UP, width=1), fillcolor=UP),
            decreasing=dict(line=dict(color=DOWN, width=1), fillcolor=DOWN)), row=1, col=1)

    closes_all = df_all["c"].tolist()
    for n in smas:
        if len(closes_all) < n:
            continue
        sr = pd.Series(_sma(closes_all, n), index=df_all["t"])
        sr = sr[sr.index >= start].dropna()
        if len(sr):
            fig.add_trace(go.Scatter(x=sr.index, y=sr.values, mode="lines", name=f"SMA {n}",
                                     line=dict(color=SMA_COLORS.get(n, MUTED), width=1.8)), row=1, col=1)
    if crosses and history:
        for kindc, sym, col, label in (("golden", "triangle-up", UP, "Golden cross (50 over 200)"),
                                       ("death", "triangle-down", DOWN, "Death cross (50 under 200)")):
            pts = [c["i"] for c in crosses if c["kind"] == kindc and df_all["t"].iloc[c["i"]] >= start]
            if pts:
                fig.add_trace(go.Scatter(
                    x=[df_all["t"].iloc[i] for i in pts], y=[df_all["c"].iloc[i] for i in pts], mode="markers",
                    name=label, marker=dict(symbol=sym, size=13, color=col, line=dict(color="#fff", width=1.5))),
                    row=1, col=1)
    if forecast:
        last_t = df["t"].iloc[-1]
        fut = pd.bdate_range(last_t + pd.Timedelta(days=1), periods=len(forecast["mid"]))
        xs = [last_t] + list(fut)
        base = float(df["c"].iloc[-1])
        fig.add_trace(go.Scatter(x=xs + xs[::-1], y=[base] + forecast["hi"] + ([base] + forecast["lo"])[::-1],
                                 fill="toself", fillcolor="rgba(124,58,237,.12)", line=dict(width=0),
                                 hoverinfo="skip", name="90% range", showlegend=True), row=1, col=1)
        fig.add_trace(go.Scatter(x=xs, y=[base] + forecast["mid"], mode="lines", name="Trend projection",
                                 line=dict(color="#7c3aed", width=2.2, dash="dash")), row=1, col=1)
        lo_y, hi_y = min(lo_y, min(forecast["lo"])), max(hi_y, max(forecast["hi"]))
    if prev_close and range_key == "1D":
        fig.add_hline(y=prev_close, line=dict(color=FAINT, dash="dot", width=1),
                      annotation_text="prev close", annotation_font_size=10, row=1, col=1)

    if volume and "v" in df:
        colors = [UP if c >= o else DOWN for o, c in zip(df["o"], df["c"])]
        fig.add_trace(go.Bar(x=df["t"], y=df["v"], marker_color=colors, opacity=.55, name="Volume",
                             showlegend=False), row=2, col=1)

    # hide non-trading time so there are no gaps
    breaks: List[Dict[str, Any]] = []
    breaks.append(dict(bounds=["sat", "mon"]))
    if range_key in INTRADAY:
        breaks.append(dict(bounds=[15.5, 9.25], pattern="hour"))
    else:
        days = pd.date_range(df["t"].min().normalize(), df["t"].max().normalize(), freq="B")
        have = set(df["t"].dt.normalize())
        missing = [d.strftime("%Y-%m-%d") for d in days if d not in have]
        if missing:
            breaks.append(dict(values=missing))
    fig.update_xaxes(rangebreaks=breaks, rangeslider_visible=False, showspikes=True,
                     spikecolor=FAINT, spikethickness=1, spikemode="across")
    fig.update_layout(xaxis_rangeslider_visible=False, hovermode="x unified",
                      uirevision=f"{ticker}-{range_key}-{kind}", dragmode="pan")
    style(fig, 470 if volume else 400)
    # zoom the price axis to the data actually shown (never from zero), with a little headroom
    pad = (hi_y - lo_y) * 0.06 or hi_y * 0.01
    fig.update_yaxes(side="right", showgrid=True, range=[lo_y - pad, hi_y + pad], row=1, col=1)
    return fig


def financial_bars(pnl: List[Dict[str, Any]], title_unit: str = "₹ cr") -> go.Figure:
    df = pd.DataFrame(pnl)
    df = df[df["revenue"].notna()].copy()
    df["year"] = df["year"].astype(str)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=df["year"], y=df["revenue"], name="Revenue", marker_color="#bfdbfe"), secondary_y=False)
    if "pat" in df:
        fig.add_trace(go.Bar(x=df["year"], y=df["pat"], name="Net profit", marker_color=ACCENT), secondary_y=False)
        margin = (df["pat"] / df["revenue"] * 100).where(df["revenue"] > 0)
        fig.add_trace(go.Scatter(x=df["year"], y=margin, name="Net margin %", mode="lines+markers",
                                 line=dict(color=WARN, width=2.5)), secondary_y=True)
    fig.update_layout(barmode="group")
    fig.update_yaxes(title_text=title_unit, secondary_y=False)
    fig.update_yaxes(title_text="margin %", showgrid=False, secondary_y=True)
    return style(fig, 340)


def football_field(price: float, bands: List[Dict[str, Any]]) -> go.Figure:
    """Horizontal ranges (52-week, DCF, peer-P/E implied) against the current price line."""
    fig = go.Figure()
    for b in bands:
        rng = f"₹{b['lo']:,.0f} – ₹{b['hi']:,.0f}"
        fig.add_trace(go.Bar(y=[b["label"]], x=[b["hi"] - b["lo"]], base=[b["lo"]], orientation="h",
                             marker_color=b.get("color", ACCENT), opacity=.9, showlegend=False,
                             text=[rng], textposition="outside", cliponaxis=False,
                             textfont=dict(size=12, color=INK), width=0.5,
                             hovertemplate=f"{b['label']}<br>{rng}<extra></extra>"))
    # current price: a line + a label box above the plot so it is never clipped
    fig.add_shape(type="line", x0=price, x1=price, y0=0, y1=1, xref="x", yref="paper",
                  line=dict(color=INK, width=2, dash="dash"))
    fig.add_annotation(x=price, y=1.0, xref="x", yref="paper", yanchor="bottom", showarrow=False,
                       text=f"<b>Price ₹{price:,.0f}</b>", bgcolor=INK, font=dict(color="#fff", size=12),
                       borderpad=4)
    # leave room on the right for the outside labels and make every band visible on one scale
    lo = min(b["lo"] for b in bands + [dict(lo=price)])
    hi = max(b["hi"] for b in bands + [dict(hi=price)])
    pad = (hi - lo) * 0.36
    fig.update_xaxes(title_text="₹ per share", range=[max(0, lo - pad * 0.15), hi + pad])
    fig.update_yaxes(autorange="reversed", automargin=True, tickfont=dict(size=12, color=INK))
    fig.update_layout(barmode="overlay", bargap=0.35)
    style(fig, 90 + 62 * len(bands), legend=False)
    fig.update_layout(margin=dict(l=8, r=8, t=44, b=8))
    return fig


def peer_scatter(rows: List[Dict[str, Any]]) -> go.Figure:
    """P/E vs ROCE, bubble = market cap; the selected company is highlighted."""
    df = pd.DataFrame(rows)
    df = df[df["pe"].notna() & df["roce"].notna()]
    fig = go.Figure()
    if len(df):
        sz = df["mcap"].fillna(df["mcap"].median() if df["mcap"].notna().any() else 1.0).clip(lower=1)
        sizes = 14 + 40 * (sz ** 0.5) / (sz.max() ** 0.5)
        fig.add_trace(go.Scatter(
            x=df["roce"], y=df["pe"], mode="markers+text", text=df["name"], textposition="top center",
            marker=dict(size=sizes, color=[ACCENT if s else "#cbd5e1" for s in df["self"]],
                        line=dict(color="#fff", width=1.5)),
            hovertemplate="%{text}<br>ROCE %{x:.1f}% · P/E %{y:.1f}<extra></extra>"))
    fig.update_xaxes(title_text="ROCE % (higher = better business)")
    fig.update_yaxes(title_text="P/E (higher = pricier)")
    return style(fig, 360, legend=False)


def range_bar_html(pos: Optional[float], lo: float, hi: float, fmt) -> str:
    """52-week range bar with a dot at the current position (0-100)."""
    p = 0 if pos is None else max(2, min(98, pos))
    return (f"<div class='range-bar'><div class='range-dot' style='left:calc({p:.0f}% - 8px)'></div></div>"
            f"<div style='display:flex;justify-content:space-between' class='muted'>"
            f"<span>{fmt(lo)}</span><span>{fmt(hi)}</span></div>")
