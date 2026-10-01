"""Cache/quote fallbacks must degrade gracefully (the live host may block Yahoo or be read-only)."""
import json
import sys
import types

from stockscout.data import cache


def _block_yahoo(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network blocked")
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=boom))
    cache._QUOTES_MEM.update(t=0.0, key=None, data=None)


def test_quotes_fall_back_to_committed_seed(monkeypatch, tmp_path):
    _block_yahoo(monkeypatch)
    monkeypatch.setattr(cache, "_QUOTES_FILE", tmp_path / "missing.json")
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"t": 1700000000, "data": {"INFY.NS": {"price": 1000.0, "prev": 990.0, "chg": 10.0,
                                                                       "chg_pct": 1.01, "spark": [990.0, 1000.0]}}}))
    monkeypatch.setattr(cache, "SEED_QUOTES_FILE", seed)
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    out, as_of, live = cache.fetch_quotes(["INFY.NS"])
    assert live is False and as_of == 1700000000 and out["INFY.NS"]["price"] == 1000.0


def test_committed_seed_covers_landing_tickers():
    from stockscout.ui.landing import TICKERS
    seed = json.loads(cache.SEED_QUOTES_FILE.read_text(encoding="utf-8"))
    assert set(TICKERS) <= set(seed["data"]), "seed_quotes.json is missing landing tickers - run scripts/build_seed_quotes.py"


def test_cache_dir_is_writable_and_unwritable_dir_does_not_raise(monkeypatch, tmp_path):
    assert cache.CACHE_DIR.exists()
    blocker = tmp_path / "file_not_dir"
    blocker.write_text("x")
    monkeypatch.setattr(cache, "CACHE_DIR", blocker / "sub")  # mkdir under a file -> OSError
    assert cache.get_cache_path("INFY.NS").name == "INFY_NS.json"
    assert cache.load_cache("INFY.NS") is None
