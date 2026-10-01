"""Verdict inputs (pure, zero network).

Threshold policy lives here (not in ratios.py) so the UI and docs can quote it.
Every string embeds its figure + statement source so the Critic rule holds:
"every figure cites a statement cell or AR page. No hallucinated numbers."
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

THRESHOLDS: Dict[str, Any] = {
    "roe_strength": 18.0, "roe_weak": 12.0,
    "roce_strength": 18.0, "roce_weak": 12.0,
    "de_strength": 0.5, "de_weak": 1.0,
    "current_strength": 1.5, "current_weak": 1.2,
    "ic_strength": 8.0, "ic_weak": 3.0,
    "npm_strength": 15.0, "npm_weak": 8.0,
    "opm_strength": 20.0, "opm_weak": 10.0,
    "turnover_strength": 1.0, "turnover_weak": 0.8,
    "recv_strength": 60.0, "recv_weak": 90.0,      # days
    "inv_strength": 60.0, "inv_weak": 90.0,        # days
    "payout_healthy_lo": 10.0, "payout_healthy_hi": 60.0,   # % of PAT
    "fcf_strength": 10.0, "fcf_weak": 5.0,         # % margin
    "z_strength": 2.6, "z_weak": 1.1,
}


def _fmt_cr(x: Any) -> str:
    try:
        return f"Rs.{float(x):,.0f}cr"
    except (TypeError, ValueError):
        return "n/a"


def _num(x: Any) -> bool:
    return isinstance(x, (int, float))


def build_verdict_inputs(
    analysis: Dict[str, Any],
    financial: Dict[str, Any] | None = None,
) -> Tuple[List[str], List[str]]:
    """Return (strengths, weaknesses) figure strings with table citations.

    analysis: output of ratios.analyze (uses ratios_full when present).
    financial: original FinancialJSON (for year + raw cells + price vs DCF).
    """
    financial = financial if isinstance(financial, dict) else {}
    ratios = analysis.get("ratios_full", analysis.get("ratios", {})) if isinstance(analysis, dict) else {}
    meta = analysis.get("ratio_meta", {}) if isinstance(analysis, dict) else {}
    year = meta.get("year", "?")
    cells = meta.get("inputs", {}) if isinstance(meta, dict) else {}
    z = analysis.get("altman_z")
    zone = (analysis.get("altman_detail") or {}).get("zone") if isinstance(analysis, dict) else None
    z_model = (analysis.get("altman_detail") or {}).get("model", "Altman Z") if isinstance(analysis, dict) else "Altman Z"
    dcf_low = analysis.get("dcf_low")
    dcf_high = analysis.get("dcf_high")
    dcf_unit = (analysis.get("dcf_detail") or {}).get("unit", "per_share") if isinstance(analysis, dict) else "per_share"
    price = financial.get("price")
    t = THRESHOLDS
    fin_co = isinstance(analysis, dict) and analysis.get("sector_kind") == "financial"
    if fin_co:  # lender: current ratio, D/E, interest cover, working capital and Z are not meaningful
        ratios = {k: v for k, v in ratios.items() if k in ("roe", "roce", "npm", "payout")}
        z = None
    s: List[str] = []
    w: List[str] = []

    def cite(table: str) -> str:
        return f"{year} | Table: {table}"

    # --- profitability ---
    roe = ratios.get("roe")
    if _num(roe):
        if roe > t["roe_strength"]:
            s.append(f"ROE {roe:.2f}% (PAT {_fmt_cr(cells.get('pat'))} / Equity {_fmt_cr(cells.get('equity'))}, {cite('P&L/BS')}) above 18% hurdle")
        elif roe < t["roe_weak"]:
            w.append(f"ROE {roe:.2f}% (PAT {_fmt_cr(cells.get('pat'))} / Equity {_fmt_cr(cells.get('equity'))}, {cite('P&L/BS')}) below 12% floor")
    roce = ratios.get("roce")
    if _num(roce):
        if roce > t["roce_strength"]:
            s.append(f"ROCE {roce:.2f}% (EBIT {_fmt_cr(cells.get('ebit'))} / Capital employed, {cite('P&L/BS')}) above 18% hurdle")
        elif roce < t["roce_weak"]:
            w.append(f"ROCE {roce:.2f}% (EBIT {_fmt_cr(cells.get('ebit'))} / Capital employed, {cite('P&L/BS')}) below 12% floor")

    # --- leverage / liquidity ---
    de = ratios.get("debt_equity")
    if _num(de):
        if de < t["de_strength"]:
            s.append(f"D/E {de:.2f}x (Debt {_fmt_cr(cells.get('debt'))} / Equity {_fmt_cr(cells.get('equity'))}, {cite('BS')}) under 0.50x")
        elif de > t["de_weak"]:
            w.append(f"D/E {de:.2f}x (Debt {_fmt_cr(cells.get('debt'))} / Equity {_fmt_cr(cells.get('equity'))}, {cite('BS')}) above 1.00x")
    cur = ratios.get("current")
    if _num(cur):
        if cur > t["current_strength"]:
            s.append(f"Current ratio {cur:.2f}x (CA {_fmt_cr(cells.get('current_assets'))} / CL {_fmt_cr(cells.get('current_liabilities'))}, {cite('BS')}) above 1.50x")
        elif cur < t["current_weak"]:
            w.append(f"Current ratio {cur:.2f}x (CA {_fmt_cr(cells.get('current_assets'))} / CL {_fmt_cr(cells.get('current_liabilities'))}, {cite('BS')}) below 1.20x")
    ic = ratios.get("interest_cover")
    if _num(ic):
        if ic > t["ic_strength"]:
            s.append(f"Interest cover {ic:.1f}x (EBIT {_fmt_cr(cells.get('ebit'))} / Interest {_fmt_cr(cells.get('interest'))}, {cite('P&L')}) above 8x")
        elif ic < t["ic_weak"]:
            w.append(f"Interest cover {ic:.1f}x (EBIT {_fmt_cr(cells.get('ebit'))} / Interest {_fmt_cr(cells.get('interest'))}, {cite('P&L')}) below 3x")

    # --- margins / efficiency ---
    npm = ratios.get("npm")
    if _num(npm):
        if npm > t["npm_strength"]:
            s.append(f"Net margin {npm:.2f}% (PAT {_fmt_cr(cells.get('pat'))} / Revenue {_fmt_cr(cells.get('revenue'))}, {cite('P&L')}) above 15%")
        elif npm < t["npm_weak"]:
            w.append(f"Net margin {npm:.2f}% (PAT {_fmt_cr(cells.get('pat'))} / Revenue {_fmt_cr(cells.get('revenue'))}, {cite('P&L')}) below 8%")
    opm = ratios.get("opm")
    if _num(opm):
        if opm > t["opm_strength"]:
            s.append(f"Operating margin {opm:.2f}% (EBITDA {_fmt_cr(cells.get('ebitda'))} / Revenue, {cite('P&L')}) above 20%")
        elif opm is not None and opm < t["opm_weak"]:
            w.append(f"Operating margin {opm:.2f}% (EBITDA {_fmt_cr(cells.get('ebitda'))} / Revenue, {cite('P&L')}) below 10%")
    ato = ratios.get("asset_turnover")
    if _num(ato):
        if ato > t["turnover_strength"]:
            s.append(f"Asset turnover {ato:.2f}x (Revenue {_fmt_cr(cells.get('revenue'))} / Assets {_fmt_cr(cells.get('assets'))}, {cite('P&L/BS')}) above 1.0x")
        elif ato < t["turnover_weak"]:
            w.append(f"Asset turnover {ato:.2f}x (Revenue {_fmt_cr(cells.get('revenue'))} / Assets {_fmt_cr(cells.get('assets'))}, {cite('P&L/BS')}) below 0.8x")

    # --- working capital ---
    recv = ratios.get("receivables_days")
    if _num(recv):
        if cells.get("receivables") == 0 or recv == 0:
            s.append(f"Nil receivables (services model, {cite('BS')}); collection risk structurally zero")
        elif recv < t["recv_strength"]:
            s.append(f"Receivables {recv:.1f} days (Receivables {_fmt_cr(cells.get('receivables'))} / Revenue, {cite('BS/P&L')}) under 60 days")
        elif recv > t["recv_weak"]:
            w.append(f"Receivables {recv:.1f} days (Receivables {_fmt_cr(cells.get('receivables'))} / Revenue, {cite('BS/P&L')}) over 90 days")
    invd = ratios.get("inventory_days")
    if _num(invd):
        if cells.get("inventory") == 0 or invd == 0:
            s.append(f"Nil inventory - services model ({cite('BS')}); no stock obsolescence risk")
        elif invd < t["inv_strength"]:
            s.append(f"Inventory {invd:.1f} days (Inventory {_fmt_cr(cells.get('inventory'))} / Revenue, {cite('BS/P&L')}) under 60 days")
        elif invd > t["inv_weak"]:
            w.append(f"Inventory {invd:.1f} days (Inventory {_fmt_cr(cells.get('inventory'))} / Revenue, {cite('BS/P&L')}) over 90 days - working-capital heavy")

    # --- distributions / cash ---
    payout = ratios.get("payout")
    if _num(payout):
        if t["payout_healthy_lo"] <= payout <= t["payout_healthy_hi"]:
            s.append(f"Payout {payout:.1f}% (Dividend {_fmt_cr(cells.get('dividend'))} / PAT, {cite('P&L/CF')}) in 10-60% healthy band")
        elif payout > 80.0:
            w.append(f"Payout {payout:.1f}% (Dividend {_fmt_cr(cells.get('dividend'))} / PAT, {cite('P&L/CF')}) above 80% - limits reinvestment buffer")
        elif payout < 5.0:
            w.append(f"Payout {payout:.1f}% - negligible distribution ({cite('P&L/CF')})")
    fcfm = ratios.get("fcf_margin")
    if _num(fcfm):
        if fcfm > t["fcf_strength"]:
            s.append(f"FCF margin {fcfm:.2f}% (FCF {_fmt_cr(cells.get('fcf'))} / Revenue, {cite('CF/P&L')}) above 10%")
        elif fcfm < t["fcf_weak"]:
            if (cells.get("fcf") or 0) < 0:
                w.append(f"Negative FCF {_fmt_cr(cells.get('fcf'))} (margin {fcfm:.2f}%, {cite('CF')}) - cash burn")
            else:
                w.append(f"Thin FCF margin {fcfm:.2f}% (FCF {_fmt_cr(cells.get('fcf'))} / Revenue, {cite('CF/P&L')}) below 5%")

    # --- solvency (Altman): zone-first (model-specific cutoffs), raw 2.6/1.1 fallback ---
    if _num(z):
        if zone == "safe":
            s.append(f"{z_model} {z:.2f} in safe zone ({cite('BS/P&L')}, MVE from market cap)")
        elif zone == "distress":
            w.append(f"{z_model} {z:.2f} in distress zone ({cite('BS/P&L')})")
        elif zone == "grey":
            w.append(f"{z_model} {z:.2f} in grey zone - borderline solvency buffer ({cite('BS/P&L')})")
        elif z > t["z_strength"]:
            s.append(f"{z_model} {z:.2f} above 2.6 ({cite('BS/P&L')}, MVE from market cap)")
        elif z < t["z_weak"]:
            w.append(f"{z_model} {z:.2f} below 1.1 ({cite('BS/P&L')})")
        else:
            w.append(f"{z_model} {z:.2f} in grey zone - borderline solvency buffer ({cite('BS/P&L')})")

    # --- valuation (price vs DCF) ---
    if _num(price) and _num(dcf_low) and _num(dcf_high):
        unit = "Rs./share" if dcf_unit == "per_share" else "Rs.cr total"
        if price < dcf_low:
            s.append(f"Price Rs.{price:,.2f} below DCF range Rs.{dcf_low:,.2f}-Rs.{dcf_high:,.2f} {unit} ({cite('CF')}, base FCF {_fmt_cr(cells.get('fcf'))}) - margin of safety on cash flows")
        elif price > dcf_high:
            w.append(f"Price Rs.{price:,.2f} above DCF range Rs.{dcf_low:,.2f}-Rs.{dcf_high:,.2f} {unit} ({cite('CF')}, base FCF {_fmt_cr(cells.get('fcf'))}) - rich vs 3-yr cash-flow value")
        else:
            s.append(f"Price Rs.{price:,.2f} inside DCF range Rs.{dcf_low:,.2f}-Rs.{dcf_high:,.2f} {unit} ({cite('CF')}) - fairly valued on cash flows")

    return s, w
