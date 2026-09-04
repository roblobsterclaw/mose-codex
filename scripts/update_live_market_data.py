#!/usr/bin/env python3
"""Refresh MOSE live quote snapshot for GitHub Pages.

The public app is static, so it cannot keep a server-side market feed open.
This script writes live-quotes.json for the browser to poll. Quotes come from
Yahoo Finance's public v8 chart endpoint (no API key required). Stooq was the
original source but its keyless CSV endpoint went dark in June 2026.

Failure policy: this script must never overwrite good data with bad data.
If the quote fetch fails or returns too few symbols, it writes
pipeline-status.json describing the failure and exits non-zero, leaving the
previous live-quotes.json / symbol-snapshots.json untouched.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "index.html"
OUTPUT = ROOT / "live-quotes.json"
SNAPSHOT_OUTPUT = ROOT / "symbol-snapshots.json"
HISTORY_OUTPUT = ROOT / "price-history.json"
STATUS_OUTPUT = ROOT / "pipeline-status.json"
EXIT_BASELINE_FILE = ROOT / "reference-data" / "exit-baseline.json"
DCF_FILE = ROOT / "dcf-latest.json"
RESEARCH_FILE = ROOT / "research-library.json"
JOE_HOLDINGS_FILE = ROOT / "joes-holdings.json"

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) MOSE-dashboard/1.0"
REQUEST_SPACING_SECONDS = 0.2
HISTORY_MAX_AGE_HOURS = 20
# Refuse to publish a snapshot if fewer than this many quotes came back —
# a near-empty result means the source is broken, not that the market moved.
MIN_QUOTES_TO_PUBLISH = 5

# Populated from the synced watchlist: maps a displayed ticker to the Yahoo
# symbol used to quote it when they differ (e.g. CSU -> CSU.TO).
QUOTE_OVERRIDES: dict[str, str] = {}

# Firebase Realtime DB holding the dashboard's synced state (custom watchlist
# tickers added from the UI live there, not in index.html).
MOSE_FB_URL = os.environ.get("MOSE_FB_URL", "https://jfl-ttd-default-rtdb.firebaseio.com/mose-codex")

INDICES = [
    {"name": "S&P 500", "symbol": "^GSPC"},
    {"name": "Dow Jones", "symbol": "^DJI"},
    {"name": "NASDAQ", "symbol": "^IXIC"},
    {"name": "Russell 2000", "symbol": "^RUT"},
    {"name": "VIX", "symbol": "^VIX"},
]

SKIP_TICKERS = {"ANTHR", "CASH", "MANAGED"}


def yahoo_symbol(ticker: str) -> str | None:
    ticker = ticker.strip().upper()
    if not ticker or ticker in SKIP_TICKERS:
        return None
    if ticker.startswith("^"):
        return ticker
    # Yahoo uses '-' for share classes (BRK-B), which matches MOSE tickers.
    return ticker


def http_get_json(url: str, timeout: int = 25) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_yahoo_quote(symbol: str) -> dict | None:
    """One symbol's latest price + previous close via the v8 chart endpoint."""
    params = urllib.parse.urlencode({"range": "1d", "interval": "1d"})
    url = YAHOO_CHART_URL.format(symbol=urllib.parse.quote(symbol)) + "?" + params
    payload = http_get_json(url)
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        return None
    meta = result[0].get("meta") or {}
    price = meta.get("regularMarketPrice")
    prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
    if price is None:
        return None
    change_pct = None
    if prev_close:
        change_pct = (price - prev_close) / prev_close * 100
    market_time = meta.get("regularMarketTime")
    stamp = (
        datetime.fromtimestamp(market_time, tz=timezone.utc).astimezone(ZoneInfo("America/New_York"))
        if market_time
        else None
    )
    return {
        "symbol": symbol,
        "price": price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "date": stamp.strftime("%Y-%m-%d") if stamp else None,
        "time": stamp.strftime("%H:%M:%S") if stamp else None,
        "volume": meta.get("regularMarketVolume"),
        "week52_high": meta.get("fiftyTwoWeekHigh"),
        "week52_low": meta.get("fiftyTwoWeekLow"),
    }


def fetch_yahoo_history(symbol: str, range_: str = "1y") -> list[dict]:
    """Daily OHLCV bars for charts and 52-week math."""
    params = urllib.parse.urlencode({"range": range_, "interval": "1d"})
    url = YAHOO_CHART_URL.format(symbol=urllib.parse.quote(symbol)) + "?" + params
    payload = http_get_json(url)
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        return []
    timestamps = result[0].get("timestamp") or []
    quote = ((result[0].get("indicators") or {}).get("quote") or [{}])[0]
    points = []
    for i, ts in enumerate(timestamps):
        close = (quote.get("close") or [None])[i] if i < len(quote.get("close") or []) else None
        if close is None:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        points.append({
            "date": day,
            "open": (quote.get("open") or [None] * (i + 1))[i],
            "high": (quote.get("high") or [None] * (i + 1))[i],
            "low": (quote.get("low") or [None] * (i + 1))[i],
            "close": close,
            "volume": (quote.get("volume") or [None] * (i + 1))[i],
        })
    return points


def fetch_quotes(symbols: list[str]) -> tuple[dict[str, dict], list[str]]:
    quotes: dict[str, dict] = {}

    def attempt(symbol: str) -> bool:
        try:
            q = fetch_yahoo_quote(symbol)
            if q:
                quotes[symbol] = q
                return True
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
            pass
        return False

    for symbol in symbols:
        attempt(symbol)
        time.sleep(REQUEST_SPACING_SECONDS)

    # Yahoo's per-symbol endpoint intermittently returns empty, leaving random
    # blanks. Retry anything that didn't come back once, a little slower.
    errors: list[str] = []
    for symbol in [s for s in symbols if s not in quotes]:
        time.sleep(0.4)
        if not attempt(symbol):
            errors.append(f"{symbol}: no data after retry")
    return quotes, errors


def _norm_ticker(t: str) -> str:
    """Normalize class shares to the Yahoo form: BRK.B -> BRK-B."""
    return re.sub(r"\.([A-Z])$", r"-\1", str(t or "").upper().strip())


def firebase_custom_tickers() -> list[str]:
    """Tickers Joe tracks via the dashboard (synced via Firebase): custom
    watchlist adds, watchlist bucket assignments, and every Buy Targets name."""
    try:
        state = http_get_json(MOSE_FB_URL + ".json", timeout=15)
    except Exception as exc:
        print(f"firebase state fetch skipped: {exc}")
        return []
    if not isinstance(state, dict):
        return []
    tickers = set()
    for item in state.get("customWatchlist") or []:
        # Private / pre-IPO entries have no public ticker — never try to quote them.
        if isinstance(item, dict) and item.get("ticker") and not item.get("private"):
            ticker = _norm_ticker(item["ticker"])
            tickers.add(ticker)
            # Foreign listings carry a Yahoo quote symbol (e.g. CSU -> CSU.TO).
            if item.get("quoteSymbol"):
                QUOTE_OVERRIDES[ticker] = str(item["quoteSymbol"]).upper()
    for ticker in (state.get("buckets") or {}):
        tickers.add(_norm_ticker(ticker))
    # Buy Targets names (IRA buckets + MOSE) so every planned buy gets a quote.
    targets = state.get("targets") or {}
    for b in ((targets.get("ira") or {}).get("buckets") or []):
        for t in (b.get("tickers") or []):
            tickers.add(_norm_ticker(t))
    for t in ((targets.get("mose") or {}).get("tickers") or []):
        tickers.add(_norm_ticker(t))
    return sorted(t for t in tickers if t)


def truist_baseline_tickers() -> list[str]:
    """Every ticker in the pre-exit Truist book. These are quoted daily so the
    opportunity-cost tracker can price the counterfactual — what the liquidated
    portfolio would be worth now — against live prices rather than a stale
    snapshot. Many are names Joe no longer holds, which is the whole point."""
    data = load_json(ROOT / "truist-baseline-feb2026.json", {})
    out = set()
    for acct in data.get("accounts", []):
        for h in acct.get("holdings", []):
            t = _norm_ticker(h.get("ticker") or "")
            if t and t not in SKIP_TICKERS:
                out.add(t)
    return sorted(out)


def watchlist_tickers() -> list[str]:
    html = INDEX_HTML.read_text()
    tickers = set(re.findall(r"ticker:\s*'([^']+)'", html))
    for report in load_json(RESEARCH_FILE, {}).get("reports", []):
        if report.get("ticker"):
            tickers.add(report["ticker"].upper())
    tickers.update(firebase_custom_tickers())
    tickers.update(truist_baseline_tickers())
    return sorted(t for t in (s.strip().upper() for s in tickers) if t and t not in SKIP_TICKERS)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def parse_static_watchlist() -> dict[str, dict]:
    html = INDEX_HTML.read_text()
    rows = {}
    pattern = re.compile(
        r"\{\s*ticker:\s*'([^']+)'\s*,\s*name:\s*'([^']*)'\s*,\s*bucket:\s*'([^']*)'\s*,\s*note:\s*'([^']*)'",
        re.S,
    )
    for ticker, name, bucket, note in pattern.findall(html):
        rows[ticker.upper()] = {"ticker": ticker.upper(), "name": name, "bucket": bucket, "note": note}
    return rows


def history_is_fresh() -> bool:
    data = load_json(HISTORY_OUTPUT, {})
    if not data.get("histories"):
        return False
    generated = data.get("generated_at")
    if not generated:
        return False
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(generated)
    except ValueError:
        return False
    return age.total_seconds() < HISTORY_MAX_AGE_HOURS * 3600


def build_symbol_snapshots(quotes: list[dict], indices: list[dict], histories: dict[str, list[dict]]) -> dict:
    watchlist = parse_static_watchlist()
    dcf = {item.get("ticker", "").upper(): item for item in load_json(DCF_FILE, {}).get("valuations", [])}
    reports = {item.get("ticker", "").upper(): item for item in load_json(RESEARCH_FILE, {}).get("reports", [])}
    owned = {}
    for acct in load_json(JOE_HOLDINGS_FILE, {}).get("accounts", []):
        for h in acct.get("holdings", []):
            ticker = (h.get("ticker") or "").upper()
            if not ticker or ticker in SKIP_TICKERS:
                continue
            owned.setdefault(ticker, {"shares": 0, "value": 0})
            owned[ticker]["shares"] += h.get("shares") or 0
            owned[ticker]["value"] += h.get("value") or 0

    symbols = {}
    for q in quotes:
        ticker = q["ticker"].upper()
        row = watchlist.get(ticker, {})
        val = dcf.get(ticker, {})
        report = reports.get(ticker, {})
        metrics = {
            "week52High": q.get("week52_high"),
            "week52Low": q.get("week52_low"),
        }
        if val.get("market_cap") is not None:
            metrics["marketCap"] = val.get("market_cap")
        if val.get("eps_ttm") and q.get("price"):
            metrics["peRatio"] = q["price"] / val["eps_ttm"]
        symbols[ticker] = {
            "ticker": ticker,
            "name": row.get("name") or val.get("company") or report.get("company") or ticker,
            "type": "ETF" if ticker in {"SGOV", "TFLO", "BIL", "VOO", "ROBO", "IRBO"} else "Equity",
            "bucket": row.get("bucket"),
            "note": row.get("note"),
            "quote": q,
            "metrics": metrics,
            "profile": {
                "company": val.get("company") or report.get("company"),
                "owned": owned.get(ticker),
                "hasResearch": bool(report.get("reportUrl")),
            },
            "source": "yahoo",
        }

    for idx in indices:
        ticker = idx["ticker"].upper()
        symbols[ticker] = {
            "ticker": ticker,
            "name": idx["name"],
            "type": "Index",
            "quote": {
                "ticker": ticker,
                "price": idx.get("price"),
                "change_pct": idx.get("change_pct"),
                "source": idx.get("source"),
            },
            "metrics": {},
            "profile": {"vsExit": idx.get("vs_exit")},
            "source": idx.get("source") or "yahoo",
        }
    return symbols


def market_status(now: datetime) -> str:
    weekday_open = now.weekday() < 5
    hour = now.hour + now.minute / 60
    return "open" if weekday_open and 9.5 <= hour < 16 else "closed"


def write_status(status: str, detail: str, quote_count: int, errors: list[str]) -> None:
    STATUS_OUTPUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "job": "update_live_market_data",
        "status": status,
        "detail": detail,
        "quote_count": quote_count,
        "errors": errors[:25],
    }, indent=2) + "\n")


def main() -> int:
    tickers = watchlist_tickers()  # also fills QUOTE_OVERRIDES
    symbol_map = {}
    for ticker in tickers:
        symbol = QUOTE_OVERRIDES.get(ticker) or yahoo_symbol(ticker)
        if symbol:
            symbol_map[symbol] = ticker

    index_symbols = [idx["symbol"] for idx in INDICES]
    all_symbols = sorted(set(symbol_map)) + index_symbols
    quotes_by_symbol, errors = fetch_quotes(all_symbols)

    quotes = []
    for symbol, ticker in sorted(symbol_map.items(), key=lambda item: item[1]):
        q = quotes_by_symbol.get(symbol)
        if q:
            quotes.append({"ticker": ticker, **q})

    if len(quotes) < MIN_QUOTES_TO_PUBLISH:
        detail = (
            f"Only {len(quotes)} of {len(symbol_map)} watchlist quotes returned; "
            "refusing to overwrite the previous snapshot."
        )
        print(f"ERROR: {detail}")
        for line in errors[:10]:
            print(f"  {line}")
        write_status("error", detail, len(quotes), errors)
        return 1

    exit_baseline = load_json(EXIT_BASELINE_FILE, {}).get("levels", {})
    indices = []
    for idx in INDICES:
        q = quotes_by_symbol.get(idx["symbol"])
        if not q:
            continue
        baseline = exit_baseline.get(idx["name"])
        vs_exit = ((q["price"] - baseline) / baseline * 100) if baseline else None
        indices.append({
            "name": idx["name"],
            "ticker": idx["symbol"],
            "price": q["price"],
            "change_pct": q["change_pct"] or 0,
            "vs_exit": vs_exit,
            "source": "yahoo",
        })

    histories: dict[str, list[dict]] = {}
    if not history_is_fresh():
        print("refreshing daily price history (1y) ...")
        for symbol, ticker in sorted(symbol_map.items(), key=lambda item: item[1]):
            try:
                points = fetch_yahoo_history(symbol)
                if points:
                    histories[ticker] = points
            except Exception as exc:
                errors.append(f"history {ticker}: {exc}")
            time.sleep(REQUEST_SPACING_SECONDS)
    else:
        histories = load_json(HISTORY_OUTPUT, {}).get("histories", {})

    now = datetime.now(timezone.utc)
    eastern_now = now.astimezone(ZoneInfo("America/New_York"))
    OUTPUT.write_text(json.dumps({
        "generated_at": now.isoformat(),
        "source": "yahoo",
        "market_status": market_status(eastern_now),
        "indices": indices,
        "quotes": quotes,
    }, indent=2) + "\n")
    HISTORY_OUTPUT.write_text(json.dumps({
        "generated_at": now.isoformat(),
        "source": "yahoo-history",
        "histories": histories,
    }, indent=2) + "\n")
    SNAPSHOT_OUTPUT.write_text(json.dumps({
        "generated_at": now.isoformat(),
        "source": "mose-live-quote-snapshot",
        "symbols": build_symbol_snapshots(quotes, indices, histories),
    }, indent=2) + "\n")

    status = "ok" if not errors else "partial"
    detail = f"{len(quotes)} quotes, {len(indices)} indices published."
    if errors:
        detail += f" {len(errors)} symbol(s) failed."
    write_status(status, detail, len(quotes), errors)
    print(detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
