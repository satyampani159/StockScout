"""Ratio & valuation engine (pure, zero network).

Owns: 12 ratios + DuPont decomposition + Altman Z + DCF-lite.
Input: FinancialJSON dict (see README.md, 'Data contract').
Output: RatioJSON-compatible dict.

Rules:
- Pure functions only. No network, no file IO, no imports outside stockscout.engine.
- Only stdlib + pandas (optional) allowed. pandas is optional at runtime so
  tests pass even on a bare interpreter; it is used only for trend helpers.
- All figures traceable: every ratio records its numerator/denominator/year.
- Round display values to 2 decimals; keep full precision internally.

Altman Z:
- Manufacturing (original 1968): Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5
  X1=WC/TA, X2=RE/TA, X3=EBIT/TA, X4=MVE/TL, X5=Sales/TA.
  Zones: >2.99 safe, 1.81-2.99 grey, <1.81 distress.
- Service / non-manufacturing (Altman Z'' for emerging/service, used for INFY):
  Z'' = 6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4 (no sales turnover factor).
  Zones: >2.6 safe, 1.1-2.6 grey, <1.1 distress.
  Pass is_service=True for IT/services tickers (e.g. INFY.NS).

DCF-lite:
- 3-year FCF projection, 2 scenarios (low/high growth), single-stage Gordon
  terminal: TV = FCF3 * (1+g_term) / (r - g_term); PV discounted at r (WACC).
- Assumes input FCF is free cash flow to equity -> PV is equity value directly.
  Net-debt adjustment is documented as a limitation (see docstring of dcf_range).
- Returns per-share fair values (equity_value / implied_shares) where
  implied_shares = mcap / price. If price/mcap missing, returns totals only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .verdict_inputs import build_verdict_inputs

try:  # pandas is in requirements.txt; the engine also works without it.
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore

SERVICE_TICKERS = {"INFY.NS", "TCS.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS", "LTIM.NS"}
SERVICE_SECTORS = {"technology", "communication services"}
FINANCIAL_SECTORS = {"financial services"}


def sector_kind(fin: Any) -> str:
    """'financial' | 'service' | 'general' from FinancialJSON sector (ticker fallback for services)."""
    if not isinstance(fin, dict):
        return "general"
    sec = str(fin.get("sector") or "").strip().lower()
    if sec in FINANCIAL_SECTORS:
        return "financial"
    if sec in SERVICE_SECTORS or fin.get("ticker") in SERVICE_TICKERS:
        return "service"
    return "general"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _safe_div(num: Any, den: Any) -> Optional[float]:
    """Return num/den or None when inputs are missing/zero."""
    try:
        if num is None or den is None:
            return None
        num_f = float(num)
        den_f = float(den)
        if den_f == 0:
            return None
        return num_f / den_f
    except (TypeError, ValueError):
        return None


def _r2(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(float(x), 2)


def _latest(rows: Any) -> Dict[str, Any]:
    """Return the last row of a statement list (latest year)."""
    if isinstance(rows, list) and rows:
        last = rows[-1]
        if isinstance(last, dict):
            return last
    return {}


def _rows(st: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Latest (pnl, bs, cf) rows aligned to ONE fiscal year (max year present in P&L and BS).

    Mixing a FY2026 P&L with a FY2025 balance sheet silently skews every ratio, so we pick
    the newest year both statements share; cf uses the same year when present.
    """
    def by_year(rows: Any) -> Dict[Any, Dict[str, Any]]:
        return {r.get("year"): r for r in rows if isinstance(r, dict)} if isinstance(rows, list) else {}

    p, b, c = by_year(st.get("pnl")), by_year(st.get("bs")), by_year(st.get("cf"))
    common = [y for y in p if y in b and y is not None]
    if common:
        y = max(common)
        return p[y], b[y], c.get(y) or _latest(st.get("cf"))
    return _latest(st.get("pnl")), _latest(st.get("bs")), _latest(st.get("cf"))


def get_fcf(cf_row: Dict[str, Any]) -> Optional[float]:
    """Resolve FCF for one cashflow row.

    Preference: explicit ``fcf`` field; else ``op - capex``; else ``op + inv``
    (inv is stored negative for outflow, matching FinancialJSON convention).
    """
    if not isinstance(cf_row, dict):
        return None
    if cf_row.get("fcf") is not None:
        try:
            return float(cf_row["fcf"])
        except (TypeError, ValueError):
            pass
    op = cf_row.get("op")
    capex = cf_row.get("capex")
    if op is not None and capex is not None:
        try:
            return float(op) - float(capex)
        except (TypeError, ValueError):
            pass
    if op is not None and cf_row.get("inv") is not None:
        try:
            return float(op) + float(cf_row["inv"])
        except (TypeError, ValueError):
            return None
    return None


def trend(values: List[Any]) -> List[float]:
    """Return sanitised float trend using pandas when available (optional)."""
    clean = [float(v) for v in values if isinstance(v, (int, float))]
    if pd is not None and clean:
        try:
            return list(pd.Series(clean, dtype="float64").tolist())
        except Exception:
            pass
    return clean

# ---------------------------------------------------------------------------
# 12 ratios (latest year)
# ---------------------------------------------------------------------------

def compute_ratios(fin: Dict[str, Any]) -> Tuple[Dict[str, Optional[float]], Dict[str, Any]]:
    """Compute the 12 ratios from the latest statement year.

    Returns (ratios, meta) where meta records {year, numerator, denominator}
    per ratio for citation/traceability.
    """
    st = fin.get("statements", {}) if isinstance(fin, dict) else {}
    pnl, bs, cf = _rows(st)
    year = pnl.get("year") or bs.get("year") or cf.get("year") or "?"

    revenue = pnl.get("revenue")
    ebitda = pnl.get("ebitda")
    ebit = pnl.get("ebit")
    pat = pnl.get("pat")
    interest = pnl.get("interest")
    dividend = pnl.get("dividend", pnl.get("dividend_paid", cf.get("dividend_paid")))
    equity = bs.get("equity")
    debt = bs.get("debt")
    assets = bs.get("assets")
    ca = bs.get("current_assets")
    cl = bs.get("current_liabilities")
    recv = bs.get("receivables")
    invt = bs.get("inventory")
    fcf = get_fcf(cf)

    roe = _safe_div(pat, equity)
    roce = _safe_div(ebit, (float(equity) + float(debt)) if equity is not None and debt is not None else None)
    # ebit may be missing while ebitda exists: fall back to ebitda for ROCE? No -
    # keep None (traceable) rather than mixing operating definitions.
    de = _safe_div(debt, equity)
    current = _safe_div(ca, cl)
    interest_cover = _safe_div(ebit, interest)
    npm = _safe_div(pat, revenue)
    opm = _safe_div(ebitda, revenue)
    asset_turnover = _safe_div(revenue, assets)
    recv_days = None if _safe_div(recv, revenue) is None else _safe_div(recv, revenue) * 365.0
    inv_days = None if _safe_div(invt, revenue) is None else _safe_div(invt, revenue) * 365.0
    div_abs = None if dividend is None else abs(float(dividend))
    payout_f = _safe_div(div_abs, pat)
    payout = None if payout_f is None else payout_f * 100.0  # percent, like roe/npm
    fcf_margin = _safe_div(fcf, revenue)

    ratios = {
        "roe": _r2(None if roe is None else roe * 100.0),
        "roce": _r2(None if roce is None else roce * 100.0),
        "debt_equity": _r2(de),
        "current": _r2(current),
        "interest_cover": _r2(interest_cover),
        "npm": _r2(None if npm is None else npm * 100.0),
        "opm": _r2(None if opm is None else opm * 100.0),
        "asset_turnover": _r2(asset_turnover),
        "receivables_days": _r2(recv_days),
        "inventory_days": _r2(inv_days),
        "payout": _r2(payout),
        "fcf_margin": _r2(None if fcf_margin is None else fcf_margin * 100.0),
    }
    meta = {
        "year": year,
        "inputs": {
            "revenue": revenue, "ebitda": ebitda, "ebit": ebit, "pat": pat,
            "interest": interest, "dividend": dividend, "equity": equity,
            "debt": debt, "assets": assets, "current_assets": ca,
            "current_liabilities": cl, "receivables": recv,
            "inventory": invt, "fcf": fcf,
        },
    }
    return ratios, meta

def ratio_history(fin: Dict[str, Any]) -> Dict[str, List[Tuple[Any, Optional[float]]]]:
    """Each of the 12 ratios for every fiscal year both P&L and balance sheet cover.

    Returns {ratio: [(year, value), ...]} oldest -> newest, for trend/sparkline use.
    """
    st = fin.get("statements", {}) if isinstance(fin, dict) else {}
    pys = {r.get("year") for r in st.get("pnl") or [] if isinstance(r, dict)}
    bys = {r.get("year") for r in st.get("bs") or [] if isinstance(r, dict)}
    out: Dict[str, List[Tuple[Any, Optional[float]]]] = {}
    for y in sorted(y for y in pys & bys if y is not None):
        sub = {"statements": {k: [r for r in (st.get(k) or []) if isinstance(r, dict) and (r.get("year") or 0) <= y]
                              for k in ("pnl", "bs", "cf")}}
        ratios, _ = compute_ratios(sub)
        for k, v in ratios.items():
            out.setdefault(k, []).append((y, v))
    return out


# ---------------------------------------------------------------------------
# DuPont (3-step)
# ---------------------------------------------------------------------------

def revenue_cagr(fin: Any, years: int = 3) -> Optional[float]:
    """Compound annual revenue growth over up to `years` periods (None if not computable)."""
    rows = [r for r in (fin.get("statements", {}).get("pnl") or []) if isinstance(r.get("revenue"), (int, float))]         if isinstance(fin, dict) else []
    if len(rows) < 2:
        return None
    last = rows[-1]
    first = rows[max(0, len(rows) - 1 - years)]
    n = (last.get("year") or 0) - (first.get("year") or 0)
    if n <= 0 or first["revenue"] <= 0 or last["revenue"] <= 0:
        return None
    return (last["revenue"] / first["revenue"]) ** (1.0 / n) - 1.0


def reverse_dcf(fin: Dict[str, Any], years: int = 10, discount_rate: float = 0.11,
                terminal_growth: float = 0.04) -> Optional[float]:
    """Annual FCF growth the CURRENT price implies over `years` (bisection). None if unsolvable.

    Reads better than a point 'fair value': 'the price assumes X% growth for a decade'.
    """
    if sector_kind(fin) == "financial":
        return None
    base = get_fcf(_rows(fin.get("statements", {}) if isinstance(fin, dict) else {})[2])
    price, mcap = (fin.get("price"), fin.get("mcap")) if isinstance(fin, dict) else (None, None)
    if base is None or base <= 0 or not mcap or mcap <= 0 or not price:
        return None
    lo, hi = -0.20, 0.60
    f = lambda g: dcf_lite(base, g, discount_rate, terminal_growth, years)
    if f(hi) is None or f(hi) < mcap:
        return hi  # even 60% growth does not justify the price
    if f(lo) > mcap:
        return lo
    for _ in range(60):
        mid = (lo + hi) / 2
        if f(mid) < mcap:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def dupont(fin: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """3-step DuPont: ROE = NPM x AssetTurnover x EquityMultiplier."""
    st = fin.get("statements", {}) if isinstance(fin, dict) else {}
    pnl, bs, _cf = _rows(st)
    revenue, pat = pnl.get("revenue"), pnl.get("pat")
    assets, equity = bs.get("assets"), bs.get("equity")

    npm = _safe_div(pat, revenue)
    turnover = _safe_div(revenue, assets)
    mult = _safe_div(assets, equity)
    roe_dup = None if None in (npm, turnover, mult) else npm * turnover * mult * 100.0
    roe_rep = None if _safe_div(pat, equity) is None else _safe_div(pat, equity) * 100.0
    return {
        "npm_pct": _r2(None if npm is None else npm * 100.0),
        "asset_turnover": _r2(turnover),
        "equity_multiplier": _r2(mult),
        "roe_dupont_pct": _r2(roe_dup),
        "roe_reported_pct": _r2(roe_rep),
    }

# ---------------------------------------------------------------------------
# Altman Z
# ---------------------------------------------------------------------------

def altman_z(
    fin: Dict[str, Any],
    is_service: Optional[bool] = None,
) -> Dict[str, Any]:
    """Altman Z-score for the latest balance sheet.

    is_service: None -> auto-detect via SERVICE_TICKERS; True uses Z'' weights.
    Returns {z, model, zone, components{x1..x5}, inputs}.
    Missing fields -> z None (never raises).
    """
    ticker = fin.get("ticker") if isinstance(fin, dict) else None
    kind = sector_kind(fin)
    if is_service is None:
        is_service = kind == "service"
    st = fin.get("statements", {}) if isinstance(fin, dict) else {}
    pnl, bs, _cf = _rows(st)

    ta = bs.get("assets")
    ca, cl = bs.get("current_assets"), bs.get("current_liabilities")
    wc = None if ca is None or cl is None else float(ca) - float(cl)
    re = bs.get("retained_earnings")
    ebit = pnl.get("ebit")
    sales = pnl.get("revenue")
    tl = bs.get("total_liabilities")
    if tl is None and ta is not None and bs.get("equity") is not None:
        try:
            tl = float(ta) - float(bs.get("equity"))
        except (TypeError, ValueError):
            tl = None
    mve = fin.get("mcap") if isinstance(fin, dict) else None  # market value of equity

    x1 = _safe_div(wc, ta)
    x2 = _safe_div(re, ta)
    x3 = _safe_div(ebit, ta)
    # Altman's Z'' (non-manufacturing) specifies BOOK equity in X4; original Z uses market value.
    x4 = _safe_div(bs.get("equity") if is_service else mve, tl)
    x5 = _safe_div(sales, ta)

    if kind == "financial":
        # Z-scores are not meaningful for lenders (deposits are liabilities, no working capital).
        return {"z": None, "model": "n/a (financial company)", "zone": None, "is_service": False,
                "components": {}, "inputs": {}}
    if is_service:
        model = "Z''-service"
        z = None if None in (x1, x2, x3, x4) else 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
        zone = None if z is None else ("safe" if z > 2.6 else ("grey" if z >= 1.1 else "distress"))
    else:
        model = "Z-manufacturing"
        z = None if None in (x1, x2, x3, x4, x5) else 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
        zone = None if z is None else ("safe" if z > 2.99 else ("grey" if z >= 1.81 else "distress"))

    return {
        "z": _r2(z),
        "model": model,
        "zone": zone,
        "is_service": bool(is_service),
        "components": {"x1": _r2(x1), "x2": _r2(x2), "x3": _r2(x3), "x4": _r2(x4), "x5": _r2(x5)},
        "inputs": {"wc": wc, "ta": ta, "re": re, "ebit": ebit, "tl": tl, "mve": mve, "sales": sales},
    }

# ---------------------------------------------------------------------------
# DCF-lite
# ---------------------------------------------------------------------------

def dcf_lite(
    base_fcf: float,
    growth: float,
    discount_rate: float = 0.11,
    terminal_growth: float = 0.04,
    years: int = 3,
) -> Optional[float]:
    """PV of `years` FCF projections + Gordon terminal. Returns equity value."""
    try:
        base = float(base_fcf)
        g = float(growth)
        r = float(discount_rate)
        gt = float(terminal_growth)
        n = int(years)
    except (TypeError, ValueError):
        return None
    if r <= gt or n < 1:
        return None
    pv = 0.0
    fcf_t = base
    for t in range(1, n + 1):
        fcf_t = fcf_t * (1.0 + g)
        pv += fcf_t / ((1.0 + r) ** t)
    terminal = fcf_t * (1.0 + gt) / (r - gt)
    pv += terminal / ((1.0 + r) ** n)
    return pv


def dcf_range(
    fin: Dict[str, Any],
    growth_low: float = 0.08,
    growth_high: float = 0.12,
    discount_rate: float = 0.11,
    terminal_growth: float = 0.04,
    years: int = 3,
) -> Dict[str, Any]:
    """2-scenario DCF range. Returns totals + per-share fair values.

    Limitation (stated for viva/report): FCF-to-equity simplification - PV is
    treated as equity value directly (no net-debt/cash adjustment); implied
    shares = mcap / price. Conservative on purpose: flags rich multiples.
    """
    st = fin.get("statements", {}) if isinstance(fin, dict) else {}
    base = get_fcf(_rows(st)[2])
    price = fin.get("price") if isinstance(fin, dict) else None
    mcap = fin.get("mcap") if isinstance(fin, dict) else None
    shares: Optional[float] = None
    try:
        if price is not None and mcap is not None and float(price) > 0:
            shares = float(mcap) / float(price)
    except (TypeError, ValueError):
        shares = None

    unavailable = None
    if sector_kind(fin) == "financial":
        unavailable = "cash-flow valuation is not meaningful for banks/lenders (deposits flow through operating cash)"
        base = None
    elif base is None:
        unavailable = "no free-cash-flow data"
    elif base <= 0:
        unavailable = "free cash flow is not positive - a cash-flow valuation is not meaningful"
        base = None
    low_total = None if base is None else dcf_lite(base, growth_low, discount_rate, terminal_growth, years)
    high_total = None if base is None else dcf_lite(base, growth_high, discount_rate, terminal_growth, years)
    # Guard against inverted scenarios (caller passes low > high).
    if low_total is not None and high_total is not None and low_total > high_total:
        low_total, high_total = high_total, low_total
    low_ps = None if low_total is None or not shares else low_total / shares
    high_ps = None if high_total is None or not shares else high_total / shares
    return {
        "dcf_low": _r2(low_ps if low_ps is not None else low_total),
        "dcf_high": _r2(high_ps if high_ps is not None else high_total),
        "unit": "per_share" if low_ps is not None else "total_cr",
        "unavailable": unavailable,
        "details": {
            "base_fcf": base if base is not None else get_fcf(_rows(st)[2]),
            "growth_low": growth_low,
            "growth_high": growth_high,
            "discount_rate": discount_rate,
            "terminal_growth": terminal_growth,
            "years": years,
            "implied_shares_cr": _r2(shares),
            "low_total_cr": _r2(low_total),
            "high_total_cr": _r2(high_total),
            "price": price,
        },
    }

# ---------------------------------------------------------------------------
# top-level
# ---------------------------------------------------------------------------

def analyze(
    fin: Dict[str, Any],
    is_service: Optional[bool] = None,
    dcf_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """FinancialJSON -> RatioJSON (without verdict_inputs; see verdict_inputs.py).

    verdict_inputs (strengths/weaknesses) come from verdict_inputs.py, where the
    threshold policy lives, so this module stays free of policy.
    """
    ratios, meta = compute_ratios(fin)
    dp = dupont(fin)
    z = altman_z(fin, is_service=is_service)
    dcf_params = dcf_params or {}
    if "growth_low" not in dcf_params and "growth_high" not in dcf_params:
        g_hi = revenue_cagr(fin)
        if g_hi is not None:  # data-driven: high case = company's own revenue CAGR (clipped)
            g_hi = min(0.20, max(0.06, g_hi))
            dcf_params = {"growth_low": round(g_hi * 0.6, 4), "growth_high": round(g_hi, 4)}
    dcf = dcf_range(
        fin,
        growth_low=dcf_params.get("growth_low", 0.08),
        growth_high=dcf_params.get("growth_high", 0.12),
        discount_rate=dcf_params.get("discount_rate", 0.11),
        terminal_growth=dcf_params.get("terminal_growth", 0.04),
        years=dcf_params.get("years", 3),
    )
    ticker = fin.get("ticker") if isinstance(fin, dict) else None
    analysis: Dict[str, Any] = {
        "ticker": ticker,
        "ratios": {
            "roe": ratios["roe"],
            "roce": ratios["roce"],
            "debt_equity": ratios["debt_equity"],
            "current": ratios["current"],
            "interest_cover": ratios["interest_cover"],
            "npm": ratios["npm"],
            "asset_turnover": ratios["asset_turnover"],
        },
        "ratios_full": ratios,  # all 12; 'ratios' keeps the 7-key contract subset
        "ratio_meta": meta,
        "dupont": dp,
        "altman_z": z["z"],
        "altman_detail": z,
        "dcf_low": dcf["dcf_low"],
        "dcf_high": dcf["dcf_high"],
        "dcf_detail": dcf,
        "sector_kind": sector_kind(fin),
        "revenue_cagr": revenue_cagr(fin),
        "implied_growth": reverse_dcf(fin),
    }
    strengths, weaknesses = build_verdict_inputs(analysis, fin)
    analysis["verdict_inputs"] = {"strengths": strengths, "weaknesses": weaknesses}
    return analysis


def build_full_analysis(fin: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Alias for analyze(), kept for backward compatibility."""
    return analyze(fin, **kwargs)
