"""One-shot builder for stockscout/data/symbols.csv (full NSE EQ/BE list).

Run:  python build_symbols.py            # uses live NSE download, weekly refresh
       python build_symbols.py --seed    # offline fallback seed (top names) if NSE blocked

Output: stockscout/data/symbols.csv  (symbol,name + header with source + date)
"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "stockscout" / "data" / "symbols.csv"

URLS = [
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://www.nseindia.com/content/equities/EQUITY_L.csv",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def download():
    import requests

    last = ""
    for u in URLS:
        try:
            r = requests.get(u, headers=HEADERS, timeout=25)
            if r.status_code == 200 and "SYMBOL" in r.text[:500].upper():
                return r.text, u
            last = f"{u} -> HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = f"{u} -> {str(e)[:120]}"
    raise RuntimeError(f"NSE download failed: {last}")


def parse(text):
    rows = []
    reader = csv.DictReader(text.splitlines())
    for row in reader:
        sym = (row.get("SYMBOL") or "").strip().upper()
        name = (row.get("NAME OF COMPANY") or "").strip()
        series = (row.get(" SERIES") or row.get("SERIES") or "").strip().upper()
        if sym and name and series in ("EQ", "BE"):
            rows.append((sym, name))
    # dedup, sort
    seen = {}
    for sym, name in rows:
        seen.setdefault(sym, name)
    return sorted(seen.items())


SEED = [
    ("RELIANCE", "Reliance Industries Limited"),
    ("TCS", "Tata Consultancy Services Limited"),
    ("HDFCBANK", "HDFC Bank Limited"),
    ("INFY", "Infosys Limited"),
    ("ICICIBANK", "ICICI Bank Limited"),
    ("SBIN", "State Bank of India"),
    ("TITAN", "Titan Company Limited"),
    ("TATAMOTORS", "Tata Motors Limited"),
    ("TATASTEEL", "Tata Steel Limited"),
    ("LT", "Larsen & Toubro Limited"),
    ("HCLTECH", "HCL Technologies Limited"),
    ("WIPRO", "Wipro Limited"),
    ("ONGC", "Oil & Natural Gas Corporation Limited"),
    ("BPCL", "Bharat Petroleum Corporation Limited"),
    ("KALYANKJIL", "Kalyan Jewellers India Limited"),
    ("M&M", "Mahindra & Mahindra Limited"),
    ("J&KBANK", "Jammu & Kashmir Bank Limited"),
]


def main():
    use_seed = "--seed" in sys.argv
    if use_seed:
        rows, src = sorted(SEED), "seed-fallback"
    else:
        try:
            text, url = download()
            rows, src = parse(text), url
        except Exception as e:  # noqa: BLE001
            print(f"live download failed ({e}); use --seed for offline fallback")
            return 1
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write(f"# NSE equities (EQ/BE) | source: {src} | built: {stamp} | refresh: weekly\n")
        w = csv.writer(f)
        w.writerow(["symbol", "name"])
        w.writerows(rows)
    print(f"wrote {len(rows)} symbols -> {OUT} (source={src})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
