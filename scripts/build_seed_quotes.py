"""Refresh stockscout/data/seed_quotes.json - the last-good quotes shown on the landing cards when Yahoo is unreachable.

Run from the project root while online: python scripts/build_seed_quotes.py
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stockscout.data import cache  # noqa: E402
from stockscout.ui.landing import TICKERS  # noqa: E402


def main():
    quotes, as_of, live = cache.fetch_quotes(TICKERS, ttl_s=0)
    if not live:
        raise SystemExit("Yahoo Finance is unreachable - seed not updated (existing file kept).")
    cache.SEED_QUOTES_FILE.write_text(json.dumps({"t": as_of or time.time(), "data": quotes}), encoding="utf-8")
    print(f"[ok] {len(quotes)}/{len(TICKERS)} quotes -> {cache.SEED_QUOTES_FILE}")


if __name__ == "__main__":
    main()
