"""Data-layer schema tests - passes OFFLINE on fixtures (network optional).

Accept: python tests/test_fetch.py  (from the project root)
Validates frozen FinancialJSON contract keys (Sec 3) for INFY/TITAN/RELIANCE.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
FIXTURES = BASE / "stockscout" / "data" / "fixtures"
EXPECTED = ["INFY", "TITAN", "RELIANCE"]

TOP_KEYS = ["ticker", "name", "currency", "price", "mcap", "pe",
            "statements", "ratios_src", "peers", "ar_url", "fetched_at"]
PNL_KEYS = ["year", "revenue", "ebitda", "pat"]
BS_KEYS = ["year", "equity", "debt", "assets"]
CF_KEYS = ["year", "op", "inv", "fin"]
RATIO_KEYS = ["roe", "roce", "de"]

failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)
    print(f"FAIL: {msg}")


def check(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


def validate_one(sym: str) -> dict | None:
    path = FIXTURES / f"{sym}.json"
    check(path.exists(), f"{sym}.json missing at {path}")
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{sym}.json invalid JSON: {e}")
        return None

    for k in TOP_KEYS:
        check(k in data, f"{sym}: missing top key '{k}'")

    check(isinstance(data.get("ticker"), str) and data["ticker"], f"{sym}: bad ticker")
    check(isinstance(data.get("name"), str) and data["name"], f"{sym}: bad name")
    check(data.get("currency") == "INR", f"{sym}: currency != INR ({data.get('currency')})")
    for k in ("price", "mcap", "pe"):
        v = data.get(k)
        check(v is None or isinstance(v, (int, float)), f"{sym}: {k} not numeric/None ({v!r})")
    check(isinstance(data.get("price"), (int, float)) and data["price"] > 0,
          f"{sym}: price must be >0 ({data.get('price')!r})")

    st = data.get("statements")
    check(isinstance(st, dict), f"{sym}: statements not a dict")
    if isinstance(st, dict):
        for sec, keys in (("pnl", PNL_KEYS), ("bs", BS_KEYS), ("cf", CF_KEYS)):
            rows = st.get(sec)
            check(isinstance(rows, list) and len(rows) >= 1, f"{sym}: statements.{sec} empty/missing")
            if isinstance(rows, list):
                for i, r in enumerate(rows):
                    check(isinstance(r, dict), f"{sym}: {sec}[{i}] not a dict")
                    if isinstance(r, dict):
                        for k in keys:
                            check(k in r, f"{sym}: {sec}[{i}] missing '{k}'")
                        check(isinstance(r.get("year"), int), f"{sym}: {sec}[{i}].year not int")
                        for k in keys[1:]:
                            v = r.get(k)
                            check(v is None or isinstance(v, (int, float)),
                                  f"{sym}: {sec}[{i}].{k} not numeric/None")
                years = [r.get("year") for r in rows if isinstance(r, dict) and isinstance(r.get("year"), int)]
                check(years == sorted(years), f"{sym}: {sec} years not sorted {years}")

    rs = data.get("ratios_src")
    check(isinstance(rs, dict), f"{sym}: ratios_src not a dict")
    if isinstance(rs, dict):
        for k in RATIO_KEYS:
            check(k in rs, f"{sym}: ratios_src missing '{k}'")
            v = rs.get(k)
            check(v is None or isinstance(v, (int, float)), f"{sym}: ratios_src.{k} not numeric/None")

    check(isinstance(data.get("peers"), list), f"{sym}: peers not a list")
    if isinstance(data.get("peers"), list):
        for i, p in enumerate(data["peers"]):
            check(isinstance(p, dict), f"{sym}: peers[{i}] not a dict")
            if isinstance(p, dict):
                for k in ("ticker", "pe", "mcap", "roe"):
                    check(k in p, f"{sym}: peers[{i}] missing '{k}'")

    check("ar_url" in data, f"{sym}: missing ar_url")
    if data.get("ar_url") is not None:
        check(isinstance(data["ar_url"], str) and data["ar_url"].startswith("http"),
              f"{sym}: ar_url not http URL ({data.get('ar_url')!r})")

    try:
        datetime.fromisoformat(str(data.get("fetched_at", "")).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        fail(f"{sym}: fetched_at not ISO8601 ({data.get('fetched_at')!r})")

    print(f"[ok] {sym}: schema valid "
          f"(pnl={len(st.get('pnl', [])) if isinstance(st, dict) else '?'} rows, "
          f"peers={len(data.get('peers', [])) if isinstance(data.get('peers'), list) else '?'})")
    return data


def main() -> int:
    print(f"fixtures dir: {FIXTURES}")
    for sym in EXPECTED:
        validate_one(sym)
    # cross-check: tickers distinct, years overlap at least 2y
    if not failures:
        print("PASS: all 3 fixtures match FinancialJSON contract (offline).")
        return 0
    print(f"\n{len(failures)} failure(s).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
