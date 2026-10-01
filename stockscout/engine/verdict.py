"""Single source of truth for the Invest / Watch / Avoid call (pure, zero network).

Used by the live app and scripts/calibrate.py so the policy cannot drift between them.
`build_bundle(fin)` -> {financial, engine, verdict}; `reprice(fin, price)` re-scales the
price-sensitive fields so the whole analysis can follow a streaming quote.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .ratios import analyze


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and x == x


def peer_median_pe(fin: Dict[str, Any]) -> Optional[float]:
    """True median P/E of comparable peers (0.2x-5x market cap when size is known)."""
    mcap = fin.get("mcap")
    peers = [p for p in (fin.get("peers") or []) if _num(p.get("pe")) and p["pe"] > 0]
    if _num(mcap) and mcap > 0:
        near = [p for p in peers if _num(p.get("mcap")) and 0.2 * mcap <= p["mcap"] <= 5 * mcap]
        if len(near) >= 2:
            peers = near
    pes = sorted(p["pe"] for p in peers)
    if not pes:
        return None
    mid = len(pes) // 2
    return pes[mid] if len(pes) % 2 else (pes[mid - 1] + pes[mid]) / 2


def decide(analysis: Dict[str, Any], fin: Dict[str, Any]) -> str:
    r = analysis.get("ratios_full", analysis.get("ratios", {}))
    z, roe, de = analysis.get("altman_z"), r.get("roe"), r.get("debt_equity")
    fcfm, ic = r.get("fcf_margin"), r.get("interest_cover")
    zone = (analysis.get("altman_detail") or {}).get("zone")
    pe, med = fin.get("pe"), peer_median_pe(fin)
    pe_ok = not (_num(pe) and med) or pe <= med * 1.2

    if analysis.get("sector_kind") == "financial":  # lender: judge on returns + valuation only
        return "Invest" if _num(roe) and roe > 15 and pe_ok else "Watch"

    if zone == "distress" or (_num(roe) and roe < 8 and _num(de) and de > 0.5) or (_num(ic) and ic < 2):
        return "Avoid"
    if zone == "safe" and _num(roe) and roe > 18 and _num(fcfm) and fcfm > 0 and _num(de) and de < 0.5 and pe_ok:
        return "Invest"
    return "Watch"


def adapt_engine(analysis: Dict[str, Any]) -> Dict[str, Any]:
    r, dp = analysis.get("ratios_full", {}), analysis.get("dupont", {})
    zd, dd = analysis.get("altman_detail", {}), analysis.get("dcf_detail", {})
    det = dd.get("details", {})
    year = analysis.get("ratio_meta", {}).get("year", "?")
    keys = ("roe", "roce", "debt_equity", "current", "interest_cover", "npm", "opm", "asset_turnover",
            "receivables_days", "inventory_days", "payout", "fcf_margin")
    return {
        "ticker": analysis.get("ticker"),
        "sector_kind": analysis.get("sector_kind", "general"),
        "ratios": {k: r.get(k) for k in keys},
        "dupont": {"npm": dp.get("npm_pct"), "asset_turnover": dp.get("asset_turnover"),
                   "leverage_assets_over_equity": dp.get("equity_multiplier"), "roe": dp.get("roe_dupont_pct")},
        "altman_z": analysis.get("altman_z"),
        "altman_zone": zd.get("zone"),
        "altman_model": zd.get("model"),
        "altman_note": f"{zd.get('model', 'Altman Z')} zone={zd.get('zone')} (FY{year}).",
        "dcf_low": analysis.get("dcf_low"), "dcf_high": analysis.get("dcf_high"),
        "dcf_unavailable": dd.get("unavailable"),
        "dcf_note": (f"3-yr FCF growth {det.get('growth_low')}-{det.get('growth_high')}, discount {det.get('discount_rate')}, "
                     f"base FCF {det.get('base_fcf')} cr (FY{year})."),
        "implied_growth": analysis.get("implied_growth"),
        "revenue_cagr": analysis.get("revenue_cagr"),
        "verdict_inputs": analysis.get("verdict_inputs", {}),
    }


def build_verdict(fin: Dict[str, Any], engine: Dict[str, Any], decision: str) -> Dict[str, Any]:
    """Reasons/risks are only real, cited signals - no filler. Avoid leads with its red flags."""
    s = list(engine["verdict_inputs"].get("strengths", []))
    w = list(engine["verdict_inputs"].get("weaknesses", []))
    if decision == "Avoid":
        reasons, risks = w[:3], (w[3:6] or s[:3])
    else:
        reasons, risks = s[:3], w[:3]
    pnl = (fin.get("statements", {}).get("pnl") or [{}])[-1]
    bs = (fin.get("statements", {}).get("bs") or [{}])[-1]
    r = engine["ratios"]
    year = pnl.get("year", "?")
    def n0(x):
        return f"{x:,.0f}" if _num(x) else "n/a"

    def n2(x):
        return f"{x:,.2f}" if _num(x) else "n/a"

    cites = [
        {"figure": f"FY{year} PAT Rs.{n0(pnl.get('pat'))} cr on revenue Rs.{n0(pnl.get('revenue'))} cr (NPM {n2(r.get('npm'))}%)",
         "source": f"table:pnl FY{year}"},
        {"figure": f"FY{bs.get('year', year)} equity Rs.{n0(bs.get('equity'))} cr, debt Rs.{n0(bs.get('debt'))} cr (D/E {n2(r.get('debt_equity'))})",
         "source": f"table:bs FY{bs.get('year', year)}"},
        {"figure": f"Altman Z {n2(engine.get('altman_z'))}, DCF Rs.{n0(engine.get('dcf_low'))}-{n0(engine.get('dcf_high'))} vs price Rs.{n2(fin.get('price'))}",
         "source": "table:valuation"},
        {"figure": f"P/E {n2(fin.get('pe'))} vs peer median {n2(peer_median_pe(fin))}", "source": "table:peers"},
    ]
    return {"ticker": fin.get("ticker"), "decision": decision, "horizon": "3y",
            "reasons": reasons, "risks": risks, "citations": cites,
            "score": {"pass": len(s), "fail": len(w)},
            "warnings": list(fin.get("warnings") or []) + (
                ["Lender: bank-specific metrics (NIM, NPA, CASA, capital adequacy) are not in the free data - treat this call as low-confidence."]
                if engine.get("sector_kind") == "financial" else [])}


def build_bundle(fin: Dict[str, Any]) -> Dict[str, Any]:
    analysis = analyze(fin)
    engine = adapt_engine(analysis)
    return {"financial": fin, "engine": engine, "verdict": build_verdict(fin, engine, decide(analysis, fin))}


def reprice(fin: Dict[str, Any], price: float) -> Dict[str, Any]:
    """Copy of `fin` re-based to a new price: market cap and P/E scale with price (shares/EPS fixed)."""
    out = dict(fin)
    p0 = fin.get("price")
    if _num(price) and price > 0 and _num(p0) and p0 > 0:
        k = price / p0
        out["price"] = round(float(price), 2)
        if _num(fin.get("mcap")):
            out["mcap"] = round(fin["mcap"] * k, 2)
        if _num(fin.get("pe")):
            out["pe"] = round(fin["pe"] * k, 2)
    elif _num(price) and price > 0:
        out["price"] = round(float(price), 2)
    return out
