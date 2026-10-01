"""NSE symbol universe + dual-field search (data layer, offline, no network).

Data: symbols.csv (symbol,name) built by build_symbols.py from NSE EQUITY_L.csv.
Search matches BOTH fields; display rows as "Company Name (SYMBOL)".

Ranking: exact symbol > symbol prefix > name prefix > name contains.
Full tickers (XXX.NS) pass through verbatim.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

BASE = Path(__file__).resolve().parent
SYMBOLS_CSV = BASE / "symbols.csv"


def _norm(text: str) -> str:
    return " ".join((text or "").strip().upper().replace(".", " ").split())


@lru_cache(maxsize=1)
def load_universe() -> list[tuple[str, str]]:
    """Return [(SYMBOL, Name)] from symbols.csv; [] if missing (never raises)."""
    try:
        rows: list[tuple[str, str]] = []
        with open(SYMBOLS_CSV, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader((ln for ln in f if not ln.startswith("#"))):
                sym = (row.get("symbol") or "").strip().upper()
                name = (row.get("name") or "").strip()
                if sym and name:
                    rows.append((sym, name))
        return rows
    except OSError:
        return []


def to_ticker(symbol: str) -> str:
    """SYMBOL -> SYMBOL.NS (NSE default suffix)."""
    return f"{symbol.strip().upper()}.NS"


def resolve_symbol(query: str, limit: int = 8) -> list[dict]:
    """Rank matches over symbol AND name. Never raises; [] on empty/no match.

    Returns [{symbol, name, ticker, match: 'symbol'|'name', label: 'Name (SYMBOL)'}].
    """
    q = _norm(query)
    if not q:
        return []
    raw = (query or "").strip().upper()
    short = q
    if raw.endswith(".NS") or raw.endswith(".BO"):
        short = _norm(raw[:-3])
    elif q.endswith(" NS") or q.endswith(" BO"):
        short = q[:-3].strip()
    uni = load_universe()
    exact, sym_pre, name_pre, contains = [], [], [], []
    for sym, name in uni:
        sym_n = _norm(sym).replace(" ", "")
        name_n = _norm(name)
        if not sym_n:
            continue
        if q == sym_n or short == sym_n or q == f"{sym_n} NS":
            exact.append((sym, name, "symbol"))
        elif sym_n.startswith(short):
            sym_pre.append((sym, name, "symbol"))
        elif name_n.startswith(q) or name_n.startswith(short):
            name_pre.append((sym, name, "name"))
        elif short in sym_n or q in name_n or short in name_n.replace(" ", ""):
            contains.append((sym, name, "name" if (q in name_n or short in name_n) else "symbol"))
    ranked = exact + sym_pre + name_pre + contains
    out = []
    for sym, name, match in ranked[: max(1, limit)]:
        out.append({"symbol": sym, "name": name, "ticker": to_ticker(sym),
                    "match": match, "label": f"{name} ({sym})"})
    return out


if __name__ == "__main__":
    for demo in ("titan", "TITAN", "tcs", "rel", "tata", "M&M", "INFY.NS", "j&k"):
        hits = resolve_symbol(demo)[:3]
        print(f"{demo!r:12} -> {[h['label'] for h in hits]}")
    print(f"universe: {len(load_universe())} symbols")
