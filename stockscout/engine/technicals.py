"""price analytics on OHLC candles (pure, zero network).

Input: candles [{t, o, h, l, c, v}] oldest -> newest (daily bars for most stats).
Everything returns None when there is not enough history - never raises.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def _closes(c: List[Dict[str, Any]]) -> List[float]:
    return [float(x["c"]) for x in c if isinstance(x.get("c"), (int, float))]


def sma(values: List[float], n: int) -> List[Optional[float]]:
    """Simple moving average aligned to `values` (None until n points exist)."""
    out: List[Optional[float]] = []
    run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= n:
            run -= values[i - n]
        out.append(run / n if i >= n - 1 else None)
    return out


def ema(values: List[float], n: int) -> List[Optional[float]]:
    k = 2.0 / (n + 1)
    out: List[Optional[float]] = []
    prev: Optional[float] = None
    for i, v in enumerate(values):
        if i < n - 1:
            out.append(None)
            continue
        prev = sum(values[:n]) / n if prev is None else v * k + prev * (1 - k)
        out.append(prev)
    return out


def rsi(values: List[float], n: int = 14) -> Optional[float]:
    """Wilder RSI of the latest bar."""
    if len(values) <= n:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(values)):
        d = values[i] - values[i - 1]
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
    return 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)


def max_drawdown(values: List[float]) -> Optional[float]:
    """Worst peak-to-trough fall as a negative percent."""
    if len(values) < 2:
        return None
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1.0)
    return worst * 100.0


def volatility(values: List[float]) -> Optional[float]:
    """Annualised volatility (%) from daily log returns."""
    if len(values) < 20:
        return None
    r = [math.log(b / a) for a, b in zip(values, values[1:]) if a > 0 and b > 0]
    if len(r) < 2:
        return None
    m = sum(r) / len(r)
    var = sum((x - m) ** 2 for x in r) / (len(r) - 1)
    return math.sqrt(var) * math.sqrt(252) * 100.0


def _ret(values: List[float], back: int) -> Optional[float]:
    if len(values) <= back or values[-1 - back] <= 0:
        return None
    return (values[-1] / values[-1 - back] - 1.0) * 100.0


def price_stats(daily: List[Dict[str, Any]], live_price: Optional[float] = None) -> Dict[str, Any]:
    """52-week range, returns, trend vs 50/200-DMA, RSI, volatility, drawdown from daily candles."""
    closes = _closes(daily)
    if len(closes) < 2:
        return {}
    if isinstance(live_price, (int, float)) and live_price > 0:
        closes = closes[:-1] + [float(live_price)]
    last = closes[-1]
    window = daily[-252:]
    hi = max(float(x["h"]) for x in window)
    lo = min(float(x["l"]) for x in window)
    hi, lo = max(hi, last), min(lo, last)
    s50 = sma(closes, 50)[-1]
    s200 = sma(closes, 200)[-1]
    return {
        "last": last,
        "high_52w": hi, "low_52w": lo,
        "pos_52w": (last - lo) / (hi - lo) * 100.0 if hi > lo else None,
        "from_high_pct": (last / hi - 1.0) * 100.0,
        "ret_1m": _ret(closes, 21), "ret_6m": _ret(closes, 126), "ret_1y": _ret(closes, 251),
        "sma50": s50, "sma200": s200,
        "above_50": None if s50 is None else last > s50,
        "above_200": None if s200 is None else last > s200,
        "golden_cross": None if s50 is None or s200 is None else s50 > s200,
        "rsi14": rsi(closes),
        "vol_ann": volatility(closes[-252:]),
        "max_dd": max_drawdown(closes[-252:]),
    }


def trend_forecast(closes: List[float], horizon: int = 21, lookback: int = 90) -> Optional[Dict[str, Any]]:
    """Trend projection anchored at the LAST close (no jump from the chart's current price).

    Drift = slope of an OLS fit on log-price over the last `lookback` bars. The ~90% band widens with
    sqrt(time) using the daily volatility seen in that window. It extends the recent trend only -
    it cannot see earnings, news or shocks. `r2` says how well a straight trend described the window.
    Returns {mid, lo, hi (lists of length horizon), slope_pct_per_bar, r2, vol_pct_per_bar, lookback} or None.
    """
    ys = [math.log(c) for c in closes[-lookback:] if isinstance(c, (int, float)) and c > 0]
    n = len(ys)
    if n < 30:
        return None
    xs = list(range(n))
    mx, my = (n - 1) / 2.0, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    icpt = my - slope * mx
    sse = sum((y - (icpt + slope * x)) ** 2 for x, y in zip(xs, ys))
    sst = sum((y - my) ** 2 for y in ys) or 1e-12
    rets = [b - a for a, b in zip(ys, ys[1:])]
    mr = sum(rets) / len(rets)
    sigma = math.sqrt(sum((r - mr) ** 2 for r in rets) / max(1, len(rets) - 1))
    last = closes[-1]
    mid, lo, hi = [], [], []
    for h in range(1, horizon + 1):
        center = math.log(last) + slope * h
        band = 1.645 * sigma * math.sqrt(h)
        mid.append(math.exp(center)); lo.append(math.exp(center - band)); hi.append(math.exp(center + band))
    return {"mid": mid, "lo": lo, "hi": hi, "slope_pct_per_bar": (math.exp(slope) - 1) * 100.0,
            "r2": 1 - sse / sst, "vol_pct_per_bar": sigma * 100.0, "lookback": n}


def cross_points(closes: List[float]) -> List[Dict[str, Any]]:
    """Indexes where the 50-bar SMA crosses the 200-bar SMA: 'golden' (up) or 'death' (down)."""
    a, b = sma(closes, 50), sma(closes, 200)
    out = []
    for i in range(1, len(closes)):
        if None in (a[i], b[i], a[i - 1], b[i - 1]):
            continue
        if a[i - 1] <= b[i - 1] and a[i] > b[i]:
            out.append({"i": i, "kind": "golden"})
        elif a[i - 1] >= b[i - 1] and a[i] < b[i]:
            out.append({"i": i, "kind": "death"})
    return out
