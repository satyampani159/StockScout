"""Data layer - yfinance + Screener.in -> FinancialJSON.

Contract (frozen, Sec 3):
{ticker, name, currency, price, mcap, pe, statements:{pnl, bs, cf},
 ratios_src:{roe,roce,de}, peers:[{ticker,pe,mcap,roe}], ar_url, fetched_at}

Rules:
- retry 3x, never raises (returns fixture/sample on failure)
- yfinance-only mode still passes if Screener HTML changes
- 2 req/s throttle on Screener, browser headers, 1x daily (24h cache)
- units: INR Crore for statement cells (documented here + in JSON "units")
- CLI: python -m stockscout.data.fetch_financials INFY.NS [--refresh]
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
FIXTURES = BASE / "fixtures"

from .cache import (  # noqa: E402
    get_cached_or_fetch,
    is_cache_fresh,
    load_cache,
    save_cache,
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------- helpers

def to_symbol(ticker: str) -> str:
    """INFY.NS -> INFY (Screener uses NSE symbol without suffix)."""
    t = (ticker or "").strip().upper()
    for suffix in (".NS", ".BO", ":NS", ":NSE"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
    return t


def _num(x) -> float | None:
    try:
        if x is None:
            return None
        f = float(x)
        if f != f or f in (float("inf"), float("-inf")):  # NaN/inf guard
            return None
        return f
    except (TypeError, ValueError):
        return None


def _to_cr(x) -> float | None:
    """yfinance absolute INR -> INR Crore, rounded 2dp."""
    v = _num(x)
    if v is None:
        return None
    return round(v / 1e7, 2)


def _pick_row(df, candidates: list[str]):
    """Return first matching row (case-insensitive) from a yfinance DataFrame."""
    if df is None or getattr(df, "empty", True):
        return None
    try:
        idx = {str(i).strip().lower(): i for i in df.index}
    except Exception:
        return None
    for c in candidates:
        key = c.strip().lower()
        if key in idx:
            try:
                return df.loc[idx[key]]
            except Exception:
                continue
    return None


def _cols_years(df):
    """Map yfinance statement columns -> calendar year int, sorted ascending."""
    years = []
    if df is None or getattr(df, "empty", True):
        return years
    for col in df.columns:
        try:
            import pandas as pd  # local import, only needed for Timestamp parsing

            if isinstance(col, (pd.Timestamp,)):
                years.append((col.year, col))
            else:
                # strings like '2024-03-31' or datetime
                ts = pd.to_datetime(col, errors="coerce")
                if ts is not None and str(ts) != "NaT":
                    years.append((int(ts.year), col))
        except Exception:
            continue
    years.sort(key=lambda t: t[0])
    return years


# ------------------------------------------------------- yfinance layer

YF_REV = ["Total Revenue", "TotalRevenue", "Revenue", "Sales", "Operating Revenue"]
YF_EBITDA = ["EBITDA", "Ebitda", "Normalized EBITDA"]
YF_EBIT = ["EBIT", "Ebit"]
YF_PAT = ["Net Income", "NetIncome", "Net Income Common Stockholders",
          "Net Income Applicable To Common Shares"]
YF_EQUITY = ["Total Stockholder Equity", "TotalStockholderEquity",
             "Stockholders' Equity", "Total Equity", "Total Equity Gross Minority Interest"]
YF_ASSETS = ["Total Assets", "TotalAssets"]
YF_TDEBT = ["Total Debt", "TotalDebt", "Short Long Term Debt Total"]
YF_STDEBT = ["Short Term Debt", "ShortTermDebt", "Current Debt"]
YF_LTDEBT = ["Long Term Debt", "LongTermDebt"]
YF_CF_OP = ["Total Cash From Operating Activities", "TotalCashFromOperatingActivities",
            "Operating Cash Flow"]
YF_CF_INV = ["Total Cashflows From Investing Activities", "TotalCashflowsFromInvestingActivities",
             "Investing Cash Flow"]
YF_CF_CAPEX = ["Capital Expenditure", "CapitalExpenditure", "Purchase Of PPE"]
YF_CF_FCF = ["Free Cash Flow", "FreeCashFlow"]
YF_CF_DIV = ["Cash Dividends Paid", "Common Stock Dividend Paid", "Dividends Paid"]
YF_CF_FIN = ["Total Cash From Financing Activities", "TotalCashFromFinancingActivities",
             "Financing Cash Flow"]
YF_CA = ["Total Current Assets", "TotalCurrentAssets", "Current Assets"]
YF_CL = ["Total Current Liabilities", "TotalCurrentLiabilities", "Current Liabilities"]
YF_RE = ["Retained Earnings", "RetainedEarnings"]
YF_RECV = ["Accounts Receivable", "AccountsReceivable", "Receivable", "Net Receivables"]
YF_INVT = ["Inventory", "Inventories"]
YF_INT = ["Interest Expense", "InterestExpense", "Interest Expense Non Operating"]


def _fx_rate(from_ccy: str, to_ccy: str) -> tuple[float, str]:
    """FX multiplier FROM->TO. Live via yfinance pair (e.g. USDINR=X), else static fallback.

    Returns (rate, note). Never raises.
    """
    from_ccy, to_ccy = (from_ccy or "").upper(), (to_ccy or "").upper()
    if from_ccy == to_ccy or not from_ccy or not to_ccy:
        return 1.0, "no-fx"
    pair = f"{from_ccy}{to_ccy}=X"
    try:
        import yfinance as yf

        hist = yf.Ticker(pair).history(period="1d", auto_adjust=False)
        if hist is not None and len(hist) > 0 and "Close" in hist.columns:
            rate = float(hist["Close"].iloc[-1])
            if rate and rate > 0:
                return rate, f"live-{pair}"
    except Exception:
        pass
    static = {("USD", "INR"): 88.0, ("EUR", "INR"): 95.0, ("USD", "EUR"): 0.92}
    if (from_ccy, to_ccy) in static:
        return static[(from_ccy, to_ccy)], "static-fallback"
    return 1.0, "fx-unknown-1:1"


def fetch_yfinance(ticker: str, retries: int = 3) -> dict:
    """Fetch statements + price via yfinance. Raises on failure (caller retries)."""
    import yfinance as yf  # imported here so tests run offline without yfinance

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            t = yf.Ticker(ticker)
            info = {}
            try:
                info = t.info or {}
            except Exception:
                info = {}
            income = t.income_stmt
            bs = t.balance_sheet
            cf = t.cashflow
            hist = None
            try:
                hist = t.history(period="1d", auto_adjust=False)
            except Exception:
                hist = None

            price = _num(info.get("currentPrice") or info.get("regularMarketPrice")
                         or info.get("previousClose"))
            if price is None and hist is not None and len(hist) > 0 and "Close" in hist.columns:
                price = _num(hist["Close"].iloc[-1])

            # yfinance may report statements in a different currency than price
            # (e.g. INFY.NS price in INR but statements in USD via ADR mirror).
            # Convert to display currency so fixtures match annual reports.
            disp_ccy = info.get("currency") or "INR"
            fin_ccy = info.get("financialCurrency") or disp_ccy
            fx, fx_note = _fx_rate(fin_ccy, disp_ccy)

            def _cr(x) -> float | None:
                v = _num(x)
                if v is None:
                    return None
                return round(v * fx / 1e7, 2)

            pnl, bs_list, cf_list = [], [], []
            for df, kind in ((income, "pnl"), (bs, "bs"), (cf, "cf")):
                pass  # parsed below per-kind

            # P&L (extra keys ebit/interest are additive - old fixtures still validate)
            rev_r = _pick_row(income, YF_REV)
            ebitda_r = _pick_row(income, YF_EBITDA)
            ebit_r = _pick_row(income, YF_EBIT)
            pat_r = _pick_row(income, YF_PAT)
            int_r = _pick_row(income, YF_INT)
            for year, col in _cols_years(income):
                rev = _cr(rev_r[col]) if rev_r is not None else None
                ebitda = _cr(ebitda_r[col]) if ebitda_r is not None else None
                ebit = _cr(ebit_r[col]) if ebit_r is not None else None
                if ebitda is None and ebit is not None:
                    ebitda = ebit  # EBIT fallback if EBITDA missing
                pat = _cr(pat_r[col]) if pat_r is not None else None
                interest = _cr(int_r[col]) if int_r is not None else None
                if interest is not None and interest < 0:
                    interest = round(-interest, 2)  # yfinance signs expense negative
                pnl.append({"year": year, "revenue": rev, "ebitda": ebitda,
                            "ebit": ebit, "pat": pat, "interest": interest})
            # BS (extra keys additive for Altman/working-capital)
            eq_r = _pick_row(bs, YF_EQUITY)
            as_r = _pick_row(bs, YF_ASSETS)
            td_r = _pick_row(bs, YF_TDEBT)
            st_r = _pick_row(bs, YF_STDEBT)
            lt_r = _pick_row(bs, YF_LTDEBT)
            ca_r = _pick_row(bs, YF_CA)
            cl_r = _pick_row(bs, YF_CL)
            re_r = _pick_row(bs, YF_RE)
            recv_r = _pick_row(bs, YF_RECV)
            invt_r = _pick_row(bs, YF_INVT)
            for year, col in _cols_years(bs):
                eq = _cr(eq_r[col]) if eq_r is not None else None
                assets = _cr(as_r[col]) if as_r is not None else None
                debt = _cr(td_r[col]) if td_r is not None else None
                if debt is None and (st_r is not None or lt_r is not None):
                    s = _cr(st_r[col]) if st_r is not None else 0.0
                    l = _cr(lt_r[col]) if lt_r is not None else 0.0
                    if s is not None and l is not None:
                        debt = round(s + l, 2)
                bs_list.append({"year": year, "equity": eq, "debt": debt, "assets": assets,
                                "current_assets": _cr(ca_r[col]) if ca_r is not None else None,
                                "current_liabilities": _cr(cl_r[col]) if cl_r is not None else None,
                                "retained_earnings": _cr(re_r[col]) if re_r is not None else None,
                                "receivables": _cr(recv_r[col]) if recv_r is not None else None,
                                "inventory": _cr(invt_r[col]) if invt_r is not None else None})
            # CF
            op_r = _pick_row(cf, YF_CF_OP)
            inv_r = _pick_row(cf, YF_CF_INV)
            fin_r = _pick_row(cf, YF_CF_FIN)
            capex_r = _pick_row(cf, YF_CF_CAPEX)
            fcf_r = _pick_row(cf, YF_CF_FCF)
            div_r = _pick_row(cf, YF_CF_DIV)
            for year, col in _cols_years(cf):
                op = _cr(op_r[col]) if op_r is not None else None
                inv = _cr(inv_r[col]) if inv_r is not None else None
                fin = _cr(fin_r[col]) if fin_r is not None else None
                capex = _cr(capex_r[col]) if capex_r is not None else None
                if capex is not None:
                    capex = abs(capex)  # yfinance signs outflow negative; engine wants a positive spend
                fcf = _cr(fcf_r[col]) if fcf_r is not None else None
                if fcf is None and op is not None and capex is not None:
                    fcf = round(op - capex, 2)
                div = _cr(div_r[col]) if div_r is not None else None
                if div is not None:
                    div = abs(div)
                cf_list.append({"year": year, "op": op, "inv": inv, "fin": fin,
                                "capex": capex, "fcf": fcf, "dividend_paid": div})

            if not pnl and not bs_list and not cf_list and not info:
                raise ValueError("yfinance returned empty statements+info")

            return {
                "name": info.get("longName") or info.get("shortName") or to_symbol(ticker),
                "currency": disp_ccy,
                "price": price,
                "mcap_cr": round(_num(info.get("marketCap")) / 1e7, 2)
                if _num(info.get("marketCap")) else None,
                "pe": _num(info.get("trailingPE")) or _num(info.get("forwardPE")),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "pnl": pnl,
                "bs": bs_list,
                "cf": cf_list,
                "fx_note": f"{fin_ccy}->{disp_ccy} x{round(fx, 4)} ({fx_note})"
                if fx != 1.0 else "no-fx",
            }
        except Exception as e:  # retry
            last_err = e
            time.sleep(1.0 * attempt)
    raise RuntimeError(f"yfinance fetch failed for {ticker}: {last_err}")


# ------------------------------------------------------- screener layer

def _named_number(html: str, label: str) -> float | None:
    """Parse Screener top-ratios card: <span class="name"> ROE </span>...<span class="number">31.9"""
    m = re.search(
        r'<span class="name">\s*' + re.escape(label) + r'\s*</span>'
        r'.*?<span class="number">\s*([\d,\.]+)',
        html, re.I | re.S)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


_INDEX_LIKE = ("NIFTY", "NFTY", "NFT", "CNX", "CNXIT", "LIX", "NV", "NI15",
               "LMIDCAP", "NQUALITY", "NFINDDIGIT", "ENHANCE", "NTYTOP", "NY500")


def _is_peer_symbol(sym: str, self_sym: str) -> bool:
    s = (sym or "").upper()
    if not s or s == self_sym.upper() or len(s) < 2 or len(s) > 15:
        return False
    if not s[0].isalpha() or not re.fullmatch(r"[A-Z0-9\-&]+", s):
        return False
    if s.isdigit() or s.startswith(_INDEX_LIKE):
        return False
    return True


def _parse_peers_api(html: str, self_sym: str) -> list[dict]:
    """Parse Screener peers API fragment: rows with /company/SYM/ + cells
    [.., CMP, P/E, MarCap(Rs.Cr), DivYld, NP Qtr, Qtr Profit Var, Sales Qtr, Qtr Sales Var, ROCE]."""
    peers: list[dict] = []
    for row in re.finditer(r"<tr[^>]*data-row-company-id[^>]*>(.*?)</tr>", html, re.S | re.I):
        body = row.group(1)
        link = re.search(r"/company/([A-Za-z0-9\-&]+)/", body)
        if not link or not _is_peer_symbol(link.group(1), self_sym):
            continue
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip().strip(",")
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", body, re.S)]
        # cells[0]=S.No, [1]=Company, [2]=CMP, [3]=P/E, [4]=MarCap, ..., [10]=ROCE
        def _f(i: int) -> float | None:
            try:
                return float(cells[i].replace(",", "")) if i < len(cells) and cells[i] not in ("", "-") else None
            except (ValueError, IndexError):
                return None
        peers.append({"ticker": f"{link.group(1).upper()}.NS", "pe": _f(3),
                      "mcap": _f(4), "roe": None, "roce": _f(10)})
        if len(peers) >= 8:
            break
    return peers


def fetch_screener(symbol: str, retries: int = 3) -> dict:
    """Scrape Screener.in consolidated page + peers API. Never raises.

    Returns {roe, roce, de, peers, ar_url, unavailable?}.
    Verified live Oct-2026: top-ratios card spans, data-warehouse-id -> peers API,
    BSE annual-report PDF links. yfinance-only mode still passes if this is empty.
    """
    import requests

    symbol = (symbol or "").strip().upper()
    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            time.sleep(0.5)  # 2 req/s throttle
            sess = requests.Session()
            sess.headers.update(BROWSER_HEADERS)
            r = sess.get(url, timeout=15)
            if r.status_code == 404:
                return {"roe": None, "roce": None, "de": None, "peers": [],
                        "ar_url": None, "unavailable": "screener-404"}
            r.raise_for_status()
            html = r.text

            roe = _named_number(html, "ROE")
            roce = _named_number(html, "ROCE")
            de = (_named_number(html, "Debt to equity")
                  or _named_number(html, "Debt/Equity")
                  or _named_number(html, "D/E"))

            # peers via warehouse-id API (company-id returns wrong group)
            peers: list[dict] = []
            peers_note = ""
            wid = re.search(r'data-warehouse-id="(\d+)"', html)
            if wid:
                try:
                    time.sleep(0.5)
                    pr = sess.get(f"https://www.screener.in/api/company/{wid.group(1)}/peers/",
                                  headers={"Referer": url}, timeout=15)
                    if pr.status_code == 200 and len(pr.text) > 1000:
                        peers = _parse_peers_api(pr.text, symbol)
                    if not peers:
                        peers_note = "; peers-empty"
                except Exception as e:
                    peers_note = f"; peers-failed:{str(e)[:100]}"
            else:
                peers_note = "; peers-no-warehouse-id"

            # annual-report PDF link (prefer explicit annual-report URLs)
            ar_url = None
            pdfs = re.findall(r'href="([^"]*?\.pdf[^"]*)"', html, re.I)
            for link in pdfs:
                if "annualreport" in link.lower().replace("-", "") or "-ar-" in link.lower():
                    ar_url = link
                    break
            if ar_url is None and pdfs:
                ar_url = pdfs[0]
            if ar_url and ar_url.startswith("/"):
                ar_url = f"https://www.screener.in{ar_url}"

            out: dict = {"roe": roe, "roce": roce, "de": de, "peers": peers, "ar_url": ar_url}
            if roe is None and roce is None and not peers and ar_url is None:
                out["unavailable"] = "screener-unparsed (layout change?)"
            elif peers_note:
                out["unavailable"] = f"screener-partial{peers_note}"
            return out
        except Exception as e:
            last_err = str(e)[:200]
            time.sleep(1.0 * attempt)
    return {"roe": None, "roce": None, "de": None, "peers": [],
            "ar_url": None, "unavailable": f"screener-failed: {last_err}"}


# ------------------------------------------------------- merge + entry

def _sample_financial_json(ticker: str) -> dict:
    """Documented sample fallback (offline). Realistic FY22-FY25, INR Crore.

    Used only when live fetch fails AND no fixture exists. Marked source=sample.
    """
    sym = to_symbol(ticker)
    now = datetime.now(timezone.utc).isoformat()
    base_peers = {
        "INFY": [{"ticker": "TCS.NS", "pe": 30.1, "mcap": 1500000.0, "roe": 46.0},
                 {"ticker": "HCLTECH.NS", "pe": 28.4, "mcap": 450000.0, "roe": 23.0},
                 {"ticker": "WIPRO.NS", "pe": 24.8, "mcap": 320000.0, "roe": 15.0}],
        "TITAN": [{"ticker": "KALYANKJIL.NS", "pe": 62.5, "mcap": 85000.0, "roe": 19.0},
                  {"ticker": "RAJESHEXPO.NS", "pe": 18.2, "mcap": 9000.0, "roe": 12.0}],
        "RELIANCE": [{"ticker": "ONGC.NS", "pe": 8.4, "mcap": 350000.0, "roe": 14.0},
                     {"ticker": "BPCL.NS", "pe": 9.1, "mcap": 140000.0, "roe": 22.0}],
    }
    samples = {
        "INFY": dict(
            name="Infosys Ltd", price=1500.0, mcap=622000.0, pe=23.5,
            pnl=[{"year": 2022, "revenue": 121641.0, "ebitda": 33546.0, "pat": 22110.0},
                 {"year": 2023, "revenue": 146767.0, "ebitda": 37945.0, "pat": 24108.0},
                 {"year": 2024, "revenue": 153958.0, "ebitda": 38533.0, "pat": 26248.0},
                 {"year": 2025, "revenue": 162990.0, "ebitda": 39610.0, "pat": 26713.0}],
            bs=[{"year": 2022, "equity": 69672.0, "debt": 5347.0, "assets": 121964.0},
                {"year": 2023, "equity": 76048.0, "debt": 6697.0, "assets": 128195.0},
                {"year": 2024, "equity": 86038.0, "debt": 8503.0, "assets": 138411.0},
                {"year": 2025, "equity": 91430.0, "debt": 9052.0, "assets": 142202.0}],
            cf=[{"year": 2022, "op": 22565.0, "inv": -4208.0, "fin": -27298.0},
                {"year": 2023, "op": 24034.0, "inv": -3805.0, "fin": -24178.0},
                {"year": 2024, "op": 28624.0, "inv": -5210.0, "fin": -25402.0},
                {"year": 2025, "op": 29885.0, "inv": -4980.0, "fin": -26915.0}],
            ratios_src={"roe": 29.5, "roce": 40.2, "de": 0.10},
            ar_url="https://www.infosys.com/investors/reports-filings/documents/annual-report-2025.pdf",
        ),
        "TITAN": dict(
            name="Titan Company Ltd", price=3400.0, mcap=301800.0, pe=85.3,
            pnl=[{"year": 2022, "revenue": 32799.0, "ebitda": 4344.0, "pat": 2229.0},
                 {"year": 2023, "revenue": 44876.0, "ebitda": 5461.0, "pat": 3274.0},
                 {"year": 2024, "revenue": 55480.0, "ebitda": 5770.0, "pat": 3496.0},
                 {"year": 2025, "revenue": 67740.0, "ebitda": 6415.0, "pat": 3800.0}],
            bs=[{"year": 2022, "equity": 9461.0, "debt": 5965.0, "assets": 22189.0},
                {"year": 2023, "equity": 11583.0, "debt": 6830.0, "assets": 27458.0},
                {"year": 2024, "equity": 13540.0, "debt": 8145.0, "assets": 32610.0},
                {"year": 2025, "equity": 15210.0, "debt": 9300.0, "assets": 36980.0}],
            cf=[{"year": 2022, "op": 1890.0, "inv": -1120.0, "fin": -640.0},
                {"year": 2023, "op": 1245.0, "inv": -1480.0, "fin": 310.0},
                {"year": 2024, "op": 2310.0, "inv": -1755.0, "fin": -890.0},
                {"year": 2025, "op": 2650.0, "inv": -1900.0, "fin": -1050.0}],
            ratios_src={"roe": 28.4, "roce": 21.5, "de": 0.61},
            ar_url="https://www.titancompany.in/sites/default/files/annual-report-2024-25.pdf",
        ),
        "RELIANCE": dict(
            name="Reliance Industries Ltd", price=2900.0, mcap=1962000.0, pe=27.2,
            pnl=[{"year": 2022, "revenue": 699962.0, "ebitda": 125206.0, "pat": 67845.0},
                 {"year": 2023, "revenue": 920727.0, "ebitda": 147191.0, "pat": 74378.0},
                 {"year": 2024, "revenue": 1000122.0, "ebitda": 161875.0, "pat": 79020.0},
                 {"year": 2025, "revenue": 1058060.0, "ebitda": 172345.0, "pat": 81309.0}],
            bs=[{"year": 2022, "equity": 728715.0, "debt": 266305.0, "assets": 1416713.0},
                {"year": 2023, "equity": 779521.0, "debt": 303724.0, "assets": 1535213.0},
                {"year": 2024, "equity": 832972.0, "debt": 324622.0, "assets": 1635772.0},
                {"year": 2025, "equity": 895000.0, "debt": 345000.0, "assets": 1750000.0}],
            cf=[{"year": 2022, "op": 110959.0, "inv": -113174.0, "fin": 15940.0},
                {"year": 2023, "op": 132294.0, "inv": -144624.0, "fin": 18450.0},
                {"year": 2024, "op": 148220.0, "inv": -139145.0, "fin": -12300.0},
                {"year": 2025, "op": 156000.0, "inv": -145000.0, "fin": -15000.0}],
            ratios_src={"roe": 8.8, "roce": 9.6, "de": 0.39},
            ar_url="https://www.ril.com/ar2024-25/pdf/reliance-annual-report-2025.pdf",
        ),
    }
    s = samples.get(sym)
    if s is None:  # never show another company's numbers under this ticker
        return {"ticker": ticker.strip().upper(), "name": sym, "currency": "INR", "units": "INR Cr",
                "price": None, "mcap": None, "pe": None,
                "statements": {"pnl": [], "bs": [], "cf": []}, "ratios_src": {}, "peers": [],
                "ar_url": None, "fetched_at": now, "source": "unavailable",
                "notes": "No live data and no offline copy for this company."}
    return {
        "ticker": ticker.strip().upper(),
        "name": s["name"],
        "currency": "INR",
        "units": "INR Cr",
        "price": s["price"],
        "mcap": s["mcap"],
        "pe": s["pe"],
        "statements": {"pnl": s["pnl"], "bs": s["bs"], "cf": s["cf"]},
        "ratios_src": s["ratios_src"],
        "peers": base_peers.get(sym, []),
        "ar_url": s["ar_url"],
        "fetched_at": now,
        "source": "sample-documented",
        "notes": "Offline fallback sample (FY22-FY25 approx, public annual reports). Replace via live fetch.",
    }


def validate_financials(fin: dict) -> list[str]:
    """Sanity checks on fetched statements. Returns human-readable warnings (never raises)."""
    w: list[str] = []
    try:
        st = fin.get("statements") or {}
        pnl, bs, cf = (st.get("pnl") or [None])[-1], (st.get("bs") or [None])[-1], (st.get("cf") or [None])[-1]
        if pnl and bs and pnl.get("year") != bs.get("year"):
            w.append(f"P&L is FY{pnl.get('year')} but balance sheet is FY{bs.get('year')} - ratios mix years.")
        if cf and pnl and cf.get("year") != pnl.get("year"):
            w.append(f"Cash-flow is FY{cf.get('year')} but P&L is FY{pnl.get('year')}.")
        if bs and bs.get("retained_earnings") and bs.get("equity") and bs["retained_earnings"] > bs["equity"] * 1.05:
            w.append("Retained earnings exceed total equity - check data quality.")
        if cf and cf.get("fcf") is not None and cf.get("op") is not None and cf["fcf"] > cf["op"] * 1.01:
            w.append("Free cash flow exceeds operating cash flow - capex data missing or wrong.")
        if pnl and bs and pnl.get("revenue") and bs.get("inventory") and bs["inventory"] > 0.5 * pnl["revenue"]:
            w.append("Inventory is over 50% of revenue - likely a mis-mapped line item.")
    except Exception:
        pass
    return w


def merge_financial_json(ticker: str, yf_data: dict | None, scr_data: dict | None) -> dict:
    """Merge yfinance + screener dicts into frozen FinancialJSON. Never raises."""
    ticker = ticker.strip().upper()
    yf_data = yf_data or {}
    scr_data = scr_data or {}
    scr_unavail = scr_data.get("unavailable")

    ratios_src = {
        "roe": scr_data.get("roe"),
        "roce": scr_data.get("roce"),
        "de": scr_data.get("de"),
    }
    # backfill D/E from balance sheet if screener unavailable
    if ratios_src["de"] is None:
        try:
            bs = yf_data.get("bs") or []
            if bs:
                last = bs[-1]
                if last.get("equity") and last.get("debt"):
                    ratios_src["de"] = round(float(last["debt"]) / float(last["equity"]), 2)
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    notes = "yfinance+screener live"
    if scr_unavail:
        notes = f"yfinance-only mode ({scr_unavail}); peers/AR marked unavailable"
    if yf_data.get("fx_note") and yf_data["fx_note"] != "no-fx":
        notes += f" [{yf_data['fx_note']}]"
    out = {
        "ticker": ticker,
        "name": yf_data.get("name") or to_symbol(ticker),
        "currency": yf_data.get("currency") or "INR",
        "units": "INR Cr",
        "price": yf_data.get("price"),
        "mcap": yf_data.get("mcap_cr"),
        "pe": yf_data.get("pe"),
        "sector": yf_data.get("sector"),
        "industry": yf_data.get("industry"),
        "statements": {
            "pnl": yf_data.get("pnl") or [],
            "bs": yf_data.get("bs") or [],
            "cf": yf_data.get("cf") or [],
        },
        "ratios_src": ratios_src,
        "peers": scr_data.get("peers") or [],
        "ar_url": scr_data.get("ar_url"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "live" if not scr_unavail else "live-yfinance-only",
        "notes": notes,
    }
    out["warnings"] = validate_financials(out)
    return out


def load_fixture(ticker: str) -> dict | None:
    sym = to_symbol(ticker)
    for cand in (FIXTURES / f"{sym}.json", FIXTURES / f"{ticker.strip().upper()}.json"):
        try:
            if cand.exists():
                with open(cand, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (OSError, ValueError):
            continue
    return None


def get_financials(ticker: str, force_refresh: bool = False) -> dict:
    """Top-level entry. NEVER raises - fixture/sample fallback guaranteed."""
    ticker = (ticker or "INFY.NS").strip().upper() or "INFY.NS"
    try:
        if not force_refresh and is_cache_fresh(ticker):
            cached = load_cache(ticker)
            if isinstance(cached, dict) and cached.get("statements"):
                return cached
    except Exception:
        pass
    try:
        yf_data: dict | None = None
        try:
            yf_data = fetch_yfinance(ticker, retries=3)
        except Exception:
            yf_data = None
        scr_data: dict = fetch_screener(to_symbol(ticker), retries=3)
        if yf_data is None and not (scr_data.get("peers") or scr_data.get("ar_url")
                                    or scr_data.get("roe") is not None):
            raise RuntimeError("both sources failed")
        if yf_data is None:
            yf_data = {}
        merged = merge_financial_json(ticker, yf_data, scr_data)
        # only cache if we have real statements
        if merged.get("statements", {}).get("pnl"):
            try:
                save_cache(ticker, merged)
            except OSError:
                pass
            return merged
        raise RuntimeError("empty statements")
    except Exception:
        for fallback in (load_cache(ticker), load_fixture(ticker)):
            try:
                if isinstance(fallback, dict) and fallback.get("statements"):
                    return fallback
            except Exception:
                continue
        return _sample_financial_json(ticker)


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    force = False
    if "--refresh" in args:
        force = True
        args.remove("--refresh")
    out_path = None
    if "--out" in args:
        i = args.index("--out")
        if i + 1 < len(args):
            out_path = Path(args[i + 1])
            del args[i:i + 2]
    tickers = args or ["INFY.NS"]
    FIXTURES.mkdir(parents=True, exist_ok=True)
    rc = 0
    for tk in tickers:
        try:
            data = get_financials(tk, force_refresh=force)
        except Exception as e:  # should never happen, belt-and-braces
            print(f"[error] {tk}: {e}", file=sys.stderr)
            rc = 1
            continue
        default_out = FIXTURES / f"{to_symbol(tk)}.json"
        dest = out_path if out_path and len(tickers) == 1 else default_out
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"[ok] {data.get('ticker')} -> {dest} (source={data.get('source')})")
        except OSError as e:
            print(f"[error] write {dest}: {e}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
