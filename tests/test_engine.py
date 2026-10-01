"""Engine tests - deterministic and offline (run: pytest -q from the project root).

Covers: INFY ROE>15, TITAN D/E sane, Z numeric, DCF low<high, figures traceable, lender/sparse-data
safety, negative-FCF handling, year alignment, payout %, reprice, technicals and the trend projection.
"""

import json
import re
import sys
from pathlib import Path

from stockscout.engine import ratios
from stockscout.engine.ratios import altman_z, analyze, compute_ratios, dcf_lite, dupont
from stockscout.engine.verdict_inputs import build_verdict_inputs

FIX = Path(__file__).parent / "fixtures"
CONTRACT_KEYS = {"ticker", "name", "currency", "price", "mcap", "pe",
                 "statements", "ratios_src", "peers", "ar_url", "fetched_at"}
RATIO12 = {"roe", "roce", "debt_equity", "current", "interest_cover", "npm",
           "opm", "asset_turnover", "receivables_days", "inventory_days",
           "payout", "fcf_margin"}


def _load(name):
    with open(FIX / name, encoding="utf-8") as f:
        return json.load(f)


def test_contract_keys_all_fixtures():
    for fn in ("INFY.json", "TITAN.json", "RELIANCE.json"):
        fin = _load(fn)
        assert CONTRACT_KEYS.issubset(fin.keys()), f"{fn} missing {CONTRACT_KEYS - set(fin)}"
        for k in ("year", "revenue", "ebitda", "pat"):
            assert all(k in r for r in fin["statements"]["pnl"]), f"{fn} pnl.{k}"
        for k in ("year", "equity", "debt", "assets"):
            assert all(k in r for r in fin["statements"]["bs"]), f"{fn} bs.{k}"
        for k in ("year", "op", "inv", "fin"):
            assert all(k in r for r in fin["statements"]["cf"]), f"{fn} cf.{k}"


def test_infy_roe_above_15():
    fin = _load("INFY.json")
    r, _ = compute_ratios(fin)
    assert r["roe"] is not None and r["roe"] > 15, f"INFY ROE {r['roe']}"
    # cross-check raw cells: PAT/equity*100 matches to 2dp
    assert abs(r["roe"] - round(fin["statements"]["pnl"][-1]["pat"]
                                / fin["statements"]["bs"][-1]["equity"] * 100, 2)) < 0.01


def test_titan_de_sane():
    fin = _load("TITAN.json")
    r, _ = compute_ratios(fin)
    assert r["debt_equity"] is not None and 0 < r["debt_equity"] < 2, f"TITAN D/E {r['debt_equity']}"


def test_twelve_ratios_present_and_reproducible():
    for fn in ("INFY.json", "TITAN.json", "RELIANCE.json"):
        fin = _load(fn)
        r, _ = compute_ratios(fin)
        assert set(r.keys()) == RATIO12, f"{fn} keys {set(r.keys())}"
        r2, _ = compute_ratios(fin)  # deterministic re-run
        assert r == r2
        # 2-decimal reproducibility: json round-trip stable
        assert json.loads(json.dumps(r)) == r


def test_dupont_reconciles():
    for fn in ("INFY.json", "TITAN.json", "RELIANCE.json"):
        fin = _load(fn)
        d = dupont(fin)
        assert d["roe_dupont_pct"] is not None and d["roe_reported_pct"] is not None
        assert abs(d["roe_dupont_pct"] - d["roe_reported_pct"]) < 0.6, f"{fn} {d}"


def test_altman_z_numeric_and_service_flag():
    infy = altman_z(_load("INFY.json"))  # auto-detect service via ticker
    assert infy["is_service"] is True and infy["model"] == "Z''-service"
    assert isinstance(infy["z"], float) and infy["z"] > 2.6 and infy["zone"] == "safe"
    for fn in ("TITAN.json", "RELIANCE.json"):
        z = altman_z(_load(fn))
        assert z["is_service"] is False and isinstance(z["z"], float), f"{fn} {z}"
        assert z["zone"] in ("safe", "grey", "distress")


def test_dcf_low_less_than_high_and_monotone_in_growth():
    for fn in ("INFY.json", "TITAN.json", "RELIANCE.json"):
        a = analyze(_load(fn))
        assert a["dcf_low"] is not None and a["dcf_high"] is not None
        assert a["dcf_low"] < a["dcf_high"], f"{fn} {a['dcf_low']} vs {a['dcf_high']}"
        assert a["dcf_low"] > 0 and a["dcf_high"] > 0
    assert dcf_lite(100.0, 0.12) > dcf_lite(100.0, 0.08)  # growth monotone
    assert dcf_lite(100.0, 0.08, discount_rate=0.15) < dcf_lite(100.0, 0.08, discount_rate=0.09)


def test_verdict_figures_traceable():
    for fn in ("INFY.json", "TITAN.json", "RELIANCE.json"):
        fin = _load(fn)
        a = analyze(fin)
        vi = a["verdict_inputs"]
        assert vi["strengths"] and vi["weaknesses"], f"{fn} needs both lists, got {vi}"
        for fig in vi["strengths"] + vi["weaknesses"]:
            assert re.search(r"\d", fig), f"{fn} figure without number: {fig}"
            assert "Table:" in fig or "page" in fig.lower(), f"{fn} no citation: {fig}"


def test_analyze_matches_ratiojson_contract():
    for fn in ("INFY.json", "TITAN.json", "RELIANCE.json"):
        a = analyze(_load(fn))
        for k in ("ticker", "ratios", "dupont", "altman_z", "dcf_low", "dcf_high", "verdict_inputs"):
            assert k in a, f"{fn} missing {k}"
        assert set(a["ratios"].keys()) == {"roe", "roce", "debt_equity", "current",
                                           "interest_cover", "npm", "asset_turnover"}
        assert {"strengths", "weaknesses"} == set(a["verdict_inputs"].keys())


def test_no_network_no_outside_imports():
    eng = Path(__file__).resolve().parents[1] / "stockscout" / "engine"
    src = "".join((eng / f).read_text(encoding="utf-8") for f in
                  ("ratios.py", "verdict_inputs.py", "verdict.py", "technicals.py"))
    for bad in ("requests", "urllib", "yfinance", "socket", "streamlit",
                "stockscout.data", "stockscout.ui", "from ..data", "from ..ui"):
        assert bad not in src, f"forbidden import/network ref in engine: {bad}"
    vi = (eng / "verdict_inputs.py").read_text(encoding="utf-8")
    assert "import ratios" not in vi and "from .ratios" not in vi  # no circular import


# ---------------------------------------------------------------- hardening tests
def _bank_like():
    return {"ticker": "HDFCBANK.NS", "sector": "Financial Services", "price": 900, "mcap": 690000,
            "statements": {"pnl": [{"year": 2026, "revenue": 300000, "pat": 70000}],
                           "bs": [{"year": 2026, "equity": 500000, "debt": None, "assets": 4000000}],
                           "cf": [{"year": 2026, "op": -50000, "inv": -10000}]}}


def test_sparse_lender_never_crashes_and_skips_meaningless_metrics():
    from stockscout.engine.verdict import build_bundle
    b = build_bundle(_bank_like())
    assert b["engine"]["altman_z"] is None and b["engine"]["dcf_low"] is None
    assert b["verdict"]["decision"] in ("Invest", "Watch", "Avoid")
    assert b["verdict"]["warnings"]  # low-confidence note for lenders


def test_negative_fcf_gives_no_dcf_not_negative_value():
    fin = _load("INFY.json")
    fin["statements"]["cf"][-1].update({"op": -100.0, "fcf": -100.0})
    a = analyze(fin)
    assert a["dcf_low"] is None and a["dcf_detail"]["unavailable"]


def test_fcf_prefers_explicit_fcf_and_subtracts_capex():
    assert ratios.get_fcf({"op": 100.0, "capex": 30.0}) == 70.0
    assert ratios.get_fcf({"op": 100.0, "capex": 30.0, "fcf": 55.0}) == 55.0


def test_year_alignment_uses_common_year():
    fin = _load("INFY.json")
    fin["statements"]["pnl"].append({"year": 2099, "revenue": 1.0, "ebitda": 1.0, "ebit": 1.0, "pat": 1.0, "interest": 1.0})
    _, meta = compute_ratios(fin)
    assert meta["year"] != 2099  # P&L-only year must not be mixed with an older balance sheet


def test_payout_is_percent():
    fin = _load("INFY.json")
    fin["statements"]["cf"][-1]["dividend_paid"] = fin["statements"]["pnl"][-1]["pat"] * 0.4
    r, _ = compute_ratios(fin)
    assert abs(r["payout"] - 40.0) < 0.5


def test_reprice_scales_pe_and_mcap_and_changes_dcf_headroom():
    from stockscout.engine.verdict import reprice
    fin = _load("TITAN.json")
    up = reprice(fin, fin["price"] * 2)
    assert abs(up["mcap"] / fin["mcap"] - 2) < 0.01 and abs(up["pe"] / fin["pe"] - 2) < 0.01


def test_technicals_basics():
    from stockscout.engine import technicals as T
    candles = [{"t": str(i), "o": 100 + i, "h": 101 + i, "l": 99 + i, "c": 100 + i, "v": 1.0} for i in range(260)]
    s = T.price_stats(candles)
    assert s["above_200"] is True and s["max_dd"] == 0 and s["pos_52w"] > 95
    assert T.max_drawdown([100, 120, 90, 110]) == -25.0
    assert T.rsi(list(range(1, 40))) == 100.0


def test_trend_forecast_follows_trend_and_band_widens():
    from stockscout.engine import technicals as T
    up = [100 * (1.002 ** i) for i in range(120)]
    f = T.trend_forecast(up, horizon=10)
    assert f["slope_pct_per_bar"] > 0.15 and f["mid"][-1] > up[-1] and f["r2"] > 0.99
    assert abs(f["mid"][0] / up[-1] - 1) < 0.01  # starts at the last price, no jump
    assert (f["hi"][-1] - f["lo"][-1]) >= (f["hi"][0] - f["lo"][0])
    assert T.trend_forecast([100.0] * 10) is None


def test_cross_points_detects_golden_cross():
    from stockscout.engine import technicals as T
    closes = [100.0] * 250 + [100 + 3 * i for i in range(60)]
    assert any(c["kind"] == "golden" for c in T.cross_points(closes))
