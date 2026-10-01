"""Symbol-universe tests - offline, no network. Run: python tests/test_symbols.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stockscout.data.symbols import load_universe, resolve_symbol, to_ticker

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print(f"FAIL: {msg}")


uni = load_universe()
check(len(uni) >= 2000, f"universe too small: {len(uni)} (want full NSE ~2500)")
syms = {s for s, _ in uni}
for must in ("INFY", "TITAN", "RELIANCE", "TCS", "M&M", "J&KBANK"):
    check(must in syms, f"{must} missing from universe")

r = resolve_symbol("titan")
check(r and r[0]["symbol"] == "TITAN" and r[0]["ticker"] == "TITAN.NS", f"titan -> {r[:1]}")
check(resolve_symbol("INFY.NS")[0]["symbol"] == "INFY", "INFY.NS suffix")
check(resolve_symbol("M&M")[0]["symbol"] == "M&M", "M&M quoting")
check(resolve_symbol("tcs")[0]["symbol"] == "TCS", "tcs name/symbol")
check(any(h["symbol"] == "TITAN" for h in resolve_symbol("titan company")), "name search")
check(resolve_symbol("") == [], "empty query")
check(all(set(h) >= {"symbol", "name", "ticker", "match", "label"} for h in r), "hit schema")
check(all(h["label"].endswith(f"({h['symbol']})") for h in r), "label Name (SYMBOL)")
check(to_ticker("tcs") == "TCS.NS", "to_ticker")

if fails:
    print(f"\n{len(fails)} failure(s)")
    raise SystemExit(1)
print(f"PASS: universe {len(uni)} symbols, dual-field search ok.")
