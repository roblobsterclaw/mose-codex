#!/usr/bin/env python3
"""Build a compact one-year price-return snapshot for Top 50 holdings.

This is deliberately separate from fund performance. It calculates the price
return of each resolvable security currently present in a manager's latest top
ten 13F holdings. The browser combines those returns using reported weights.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

from update_live_market_data import fetch_yahoo_history, yahoo_symbol


ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = ROOT / "reference-data" / "investor-universe.json"
OUTPUT_PATH = ROOT / "reference-data" / "investor-performance.json"
MAX_AGE_HOURS = 20
REQUEST_SPACING_SECONDS = 0.12


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def normalized_ticker(value: str) -> str | None:
    ticker = re.sub(r"\.([A-Z])$", r"-\1", str(value or "").upper().strip())
    if not ticker or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker):
        return None
    if len(ticker) == 9 and any(char.isdigit() for char in ticker):
        return None
    return ticker


def source_tickers() -> list[str]:
    universe = load_json(UNIVERSE_PATH, {})
    tickers = {
        ticker
        for row in universe.get("candidates", [])
        for holding in row.get("top_holdings", [])
        if (ticker := normalized_ticker(holding.get("ticker") or ""))
    }
    return sorted(tickers)


def is_fresh() -> bool:
    payload = load_json(OUTPUT_PATH, {})
    generated_at = payload.get("generated_at")
    if not generated_at or not payload.get("returns"):
        return False
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(generated_at)
    except ValueError:
        return False
    return age.total_seconds() < MAX_AGE_HOURS * 3600


def one_year_return(points: list[dict]) -> dict | None:
    rows = sorted(
        [row for row in points if row.get("date") and row.get("close") is not None],
        key=lambda row: row["date"],
    )
    if len(rows) < 2:
        return None
    latest = rows[-1]
    cutoff = (datetime.fromisoformat(latest["date"]).date() - timedelta(days=365)).isoformat()
    start = next((row for row in rows if row["date"] >= cutoff), rows[0])
    start_close = float(start["close"])
    end_close = float(latest["close"])
    if start["date"] == latest["date"] or start_close <= 0:
        return None
    return {
        "one_year_price_return_pct": round((end_close / start_close - 1) * 100, 4),
        "from": start["date"],
        "to": latest["date"],
        "observations": len(rows),
    }


def main() -> int:
    if is_fresh():
        print("Investor performance snapshot is still fresh")
        return 0
    returns = {}
    errors = []
    tickers = source_tickers()
    for ticker in tickers:
        symbol = yahoo_symbol(ticker)
        if not symbol:
            continue
        try:
            result = one_year_return(fetch_yahoo_history(symbol))
            if result:
                returns[ticker] = result
            else:
                errors.append(f"{ticker}: insufficient history")
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError) as exc:
            errors.append(f"{ticker}: {exc}")
        time.sleep(REQUEST_SPACING_SECONDS)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Yahoo Finance public chart endpoint",
        "methodology": "One-year price return for currently reported top-10 13F securities; excludes dividends.",
        "ticker_count": len(returns),
        "requested_ticker_count": len(tickers),
        "errors": errors[:50],
        "returns": returns,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Investor performance: {len(returns)}/{len(tickers)} tickers")
    return 0 if returns else 1


if __name__ == "__main__":
    raise SystemExit(main())
