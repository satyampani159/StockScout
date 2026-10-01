"""Refresh engine test fixtures from the offline data snapshots and print the resulting verdicts.

Run from the project root: python scripts/calibrate.py
Copies stockscout/data/fixtures/*.json -> tests/fixtures/*.json and runs the real engine on each, so a
change to thresholds or ratios shows up immediately. The decision policy lives only in
stockscout/engine/verdict.py (shared with the live app).
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stockscout.engine.verdict import build_bundle  # noqa: E402

TICKERS = ["INFY", "TITAN", "RELIANCE"]


def main():
    for sym in TICKERS:
        src = ROOT / "stockscout" / "data" / "fixtures" / f"{sym}.json"
        shutil.copyfile(src, ROOT / "tests" / "fixtures" / f"{sym}.json")
        fin = json.loads(src.read_text(encoding="utf-8"))
        b = build_bundle(fin)
        e = b["engine"]
        print(f"[ok] {fin['ticker']}: FY{fin['statements']['pnl'][-1]['year']} ROE={e['ratios']['roe']} "
              f"Z={e['altman_z']} DCF={e['dcf_low']}-{e['dcf_high']} -> {b['verdict']['decision']}")


if __name__ == "__main__":
    main()
