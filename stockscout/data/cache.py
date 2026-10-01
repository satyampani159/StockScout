"""24h file cache + live price/candle/quote paths (data layer only; no imports from engine or ui).

Fundamentals move quarterly - 10-min polling is price-only.
So: fundamentals cached 24h, price fetched live per view.
"""
from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

def _resolve_cache_dir() -> Path:
    """<project>/.cache if writable, else a temp dir (read-only hosts must degrade, not crash)."""
    primary = Path(__file__).resolve().parents[2] / ".cache"
    for cand in (primary, Path(tempfile.gettempdir()) / "stockscout_cache"):
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".write_test"
            probe.write_text("1", encoding="utf-8")
            probe.unlink()
            return cand
        except OSError:
            continue
    return primary


CACHE_DIR = _resolve_cache_dir()
SEED_QUOTES_FILE = Path(__file__).resolve().parent / "seed_quotes.json"  # committed last-good quotes
CACHE_TTL_HOURS = 24


def _safe_name(ticker: str) -> str:
    return ticker.strip().upper().replace(".", "_").replace("/", "_").replace(":", "_")


def get_cache_path(ticker: str) -> Path:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return CACHE_DIR / f"{_safe_name(ticker)}.json"


def is_fresh(path: Path, ttl_hours: float = CACHE_TTL_HOURS) -> bool:
    try:
        if not path.exists():
            return False
        age_s = time.time() - path.stat().st_mtime
        return age_s < ttl_hours * 3600
    except OSError:
        return False


def is_cache_fresh(ticker: str, ttl_hours: float = CACHE_TTL_HOURS) -> bool:
    return is_fresh(get_cache_path(ticker), ttl_hours)


def load_cache(ticker: str) -> dict | None:
    path = get_cache_path(ticker)
    try:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_cache(ticker: str, data: dict) -> Path:
    path = get_cache_path(ticker)
    payload = dict(data)
    payload.setdefault("fetched_at", datetime.now(timezone.utc).isoformat())
    payload.setdefault("ticker", ticker)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


PRICE_TTL_S = 30  # min seconds between live quote calls per ticker (429 guard)
_LAST_CALL: dict[str, float] = {}
_LAST_PRICE: dict[str, float] = {}


def _throttled(ticker: str, min_gap: float = 1.0) -> bool:
    """True if caller must wait (2 req/s Yahoo courtesy + 429 guard)."""
    now = time.time()
    last = _LAST_CALL.get(ticker.upper(), 0.0)
    if now - last < min_gap:
        return True
    _LAST_CALL[ticker.upper()] = now
    return False


def fetch_price(ticker: str, ttl_s: float = PRICE_TTL_S) -> tuple[float | None, str]:
    """Live price path. Never raises. Returns (price, status).

    status: 'live' | 'live-cached' (within TTL) | 'cache-fallback' | 'unavailable'.
    Respects per-ticker TTL so 10-15s UI polls don't hammer Yahoo (429 guard).
    """
    key = ticker.strip().upper()
    now = time.time()
    # 1) TTL memory cache (same process, e.g. Streamlit reruns)
    if key in _LAST_PRICE and (now - _LAST_CALL.get(key + ":ok", 1e18)) < ttl_s:
        return _LAST_PRICE[key], "live-cached"
    # 2) live attempt (fast, price-only), throttled to >=1s gaps
    if not _throttled(key, 1.0):
        try:
            import yfinance as yf  # local import so cache works without yfinance installed

            hist = yf.Ticker(ticker).history(period="1d", auto_adjust=False)
            if hist is not None and len(hist) > 0 and "Close" in hist.columns:
                price = float(hist["Close"].iloc[-1])
                if price and price > 0:
                    _LAST_PRICE[key] = price
                    _LAST_CALL[key + ":ok"] = now
                    return price, "live"
        except Exception:
            pass
    elif key in _LAST_PRICE:
        return _LAST_PRICE[key], "live-cached"
    # 3) fallback to 24h fundamentals cache price
    try:
        cached = load_cache(ticker)
        if isinstance(cached, dict) and cached.get("price"):
            return float(cached["price"]), "cache-fallback"
    except (TypeError, ValueError):
        pass
    if key in _LAST_PRICE:
        return _LAST_PRICE[key], "live-cached"
    return None, "unavailable"


def fetch_intraday(ticker: str, period: str = "1d", interval: str = "5m") -> list[dict]:
    """Intraday sparkline points [{t, price}]. Never raises; [] on failure/throttle."""
    if _throttled(ticker.strip().upper() + ":intra", 5.0):
        return []
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
        if hist is None or len(hist) == 0 or "Close" not in hist.columns:
            return []
        return [{"t": str(idx), "price": round(float(v), 2)}
                for idx, v in zip(hist.index, hist["Close"].tolist()) if v]
    except Exception:
        return []


def market_status(now_utc=None) -> dict:
    """NSE hours 9:15-15:30 IST (Mon-Fri). Returns {open: bool, label: str}."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    try:
        ist = (now_utc or datetime.now(timezone.utc)).astimezone(ZoneInfo("Asia/Kolkata"))
    except Exception:
        ist = datetime.now(timezone.utc)
    if ist.weekday() >= 5:
        return {"open": False, "label": "Market closed (weekend) · showing last close"}
    mins = ist.hour * 60 + ist.minute
    if 555 <= mins <= 930:
        return {"open": True, "label": f"Market open · IST {ist.strftime('%H:%M')}"}
    return {"open": False, "label": f"Market closed · IST {ist.strftime('%H:%M')} · showing last close"}


def get_cached_or_fetch(ticker: str, fetch_fn, ttl_hours: float = CACHE_TTL_HOURS,
                        force_refresh: bool = False) -> dict | None:
    """Generic helper: return fresh cache if available else call fetch_fn(ticker).

    fetch_fn must be a zero-raise callable returning a dict or None.
    Never raises - returns stale cache or None on total failure.
    """
    path = get_cache_path(ticker)
    if not force_refresh and is_fresh(path, ttl_hours):
        cached = load_cache(ticker)
        if isinstance(cached, dict):
            return cached
    try:
        fresh = fetch_fn(ticker)
    except Exception:
        fresh = None
    if isinstance(fresh, dict):
        try:
            save_cache(ticker, fresh)
        except OSError:
            pass
        return fresh
    return load_cache(ticker)


# ---------------------------------------------------------------- OHLC (candles)
_OHLC_CACHE: dict[tuple, tuple[float, list[dict]]] = {}
# period -> (default interval, cache TTL seconds)
OHLC_RANGES = {"1D": ("5m", 20), "5D": ("15m", 60), "1M": ("1h", 300),
               "6M": ("1d", 1800), "1Y": ("1d", 1800), "2Y": ("1d", 3600), "5Y": ("1wk", 3600), "7Y": ("1d", 3600),
               # longer same-interval history used only to warm up intraday moving averages
               "H1D": ("5m", 30), "H5D": ("15m", 90), "H1M": ("1h", 300)}
_PERIOD = {"1D": "1d", "5D": "5d", "1M": "1mo", "6M": "6mo", "1Y": "1y", "2Y": "2y", "5Y": "5y", "7Y": "7y", "H1D": "5d", "H5D": "1mo", "H1M": "3mo"}


def fetch_ohlc(ticker: str, range_key: str = "1Y") -> list[dict]:
    """Candles [{t, o, h, l, c, v}] for a UI range key (1D/5D/1M/6M/1Y/5Y). Never raises.

    Cached per (ticker, range) with a short TTL so live reruns don't hammer Yahoo (429 guard).
    Falls back to the last good copy if the live call fails or is throttled.
    """
    interval, ttl = OHLC_RANGES.get(range_key, ("1d", 1800))
    key = (ticker.strip().upper(), range_key)
    now = time.time()
    hit = _OHLC_CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period=_PERIOD.get(range_key, "1y"),
                                         interval=interval, auto_adjust=False)
        if hist is None or len(hist) == 0 or "Close" not in hist.columns:
            raise ValueError("empty history")
        rows = []
        for idx, r in hist.iterrows():
            o, h, l, c = (float(r.get(k)) for k in ("Open", "High", "Low", "Close"))
            if c != c or o != o:  # NaN bar
                continue
            ts = idx.tz_convert("Asia/Kolkata").tz_localize(None) if getattr(idx, "tzinfo", None) else idx
            rows.append({"t": ts.isoformat(), "o": round(o, 2), "h": round(h, 2),
                         "l": round(l, 2), "c": round(c, 2), "v": float(r.get("Volume") or 0)})
        if rows:
            _OHLC_CACHE[key] = (now, rows)
            return rows
    except Exception:
        pass
    return hit[1] if hit else []


# ---------------------------------------------------------------- batch quotes (landing cards)
_QUOTES_FILE = CACHE_DIR / "_quotes.json"
_QUOTES_MEM: dict = {"t": 0.0, "key": None, "data": None}


def fetch_quotes(tickers: list[str], ttl_s: float = 20.0) -> tuple[dict, float | None, bool]:
    """Batch last price / day change / 1-month sparkline for many tickers in ONE Yahoo call.

    Returns ({ticker: {price, prev, chg, chg_pct, spark}}, as_of_epoch, live). Never raises.
    On failure falls back to the last saved snapshot (live=False), then to per-ticker 24h caches.
    """
    key = tuple(tickers)
    now = time.time()
    if _QUOTES_MEM["key"] == key and now - _QUOTES_MEM["t"] < ttl_s and _QUOTES_MEM["data"]:
        return _QUOTES_MEM["data"], _QUOTES_MEM["t"], True
    out: dict = {}
    try:
        import yfinance as yf

        df = yf.download(" ".join(tickers), period="1mo", interval="1d", group_by="ticker",
                         progress=False, auto_adjust=False, threads=True)
        for tk in tickers:
            try:
                col = df[tk]["Close"] if len(tickers) > 1 else df["Close"]
                closes = [float(x) for x in col.dropna().tolist()]
            except Exception:
                continue
            if len(closes) >= 2:
                price, prev = closes[-1], closes[-2]
                out[tk] = {"price": round(price, 2), "prev": round(prev, 2), "chg": round(price - prev, 2),
                           "chg_pct": round((price / prev - 1) * 100, 2), "spark": [round(c, 2) for c in closes[-22:]]}
    except Exception:
        out = {}
    if out:
        _QUOTES_MEM.update(t=now, key=key, data=out)
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(_QUOTES_FILE, "w", encoding="utf-8") as f:
                json.dump({"t": now, "data": out}, f)
        except OSError:
            pass
        return out, now, True
    # fallback 1: last saved snapshot on disk, then the committed seed snapshot for anything still missing
    snap_t = None
    out = {}
    for path in (_QUOTES_FILE, SEED_QUOTES_FILE):
        try:
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
        except (OSError, ValueError):
            continue
        for k, v in snap.get("data", {}).items():
            if k in tickers and k not in out:
                out[k] = v
        if snap_t is None and snap.get("data"):
            snap_t = snap.get("t")
    # fallback 2: price from the per-company 24h cache (no day change available)
    for tk in tickers:
        if tk not in out:
            c = load_cache(tk)
            if isinstance(c, dict) and c.get("price"):
                out[tk] = {"price": float(c["price"]), "prev": None, "chg": None, "chg_pct": None, "spark": []}
                snap_t = snap_t or None
    return out, snap_t, False
