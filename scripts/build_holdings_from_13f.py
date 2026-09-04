#!/usr/bin/env python3
"""Rebuild holdings-latest.json from the live SEC 13F pull.

The dashboard's Holdings Tracker, Convergence Heat Map and the Watchlist
"who owns this" overlap all read holdings-latest.json. Historically that file
was a stale export from convergence-master.json, so newly added investors never
showed up there. This script regenerates it from data/sec-13f-filings.json so
every tracked manager's CURRENT (latest-quarter) holdings flow into those views.

13F gives shares + market value per holding but not cost basis, so "entry" is
approximated from the first quarter each manager reported the position:
price ~= market_value / shares. current_price prefers the live quote when available.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEC_HISTORY = ROOT / "data" / "sec-13f-filings.json"
LIVE_QUOTES = ROOT / "live-quotes.json"
OUTPUT = ROOT / "holdings-latest.json"
CUSIP_MAP = ROOT / "reference-data" / "cusip-map.json"

TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]{0,6}$")  # resolved tickers only (skip raw CUSIPs)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def quarter_key(q: str):
    m = re.match(r"(\d{4}).*?Q?([1-4])", q or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def live_prices() -> dict[str, float]:
    prices = {}
    for q in load_json(LIVE_QUOTES, {}).get("quotes", []):
        t = str(q.get("ticker") or q.get("symbol") or "").upper()
        if t and isinstance(q.get("price"), (int, float)):
            prices[t] = float(q["price"])
    return prices


def load_cusip_tickers() -> dict[str, str]:
    payload = load_json(CUSIP_MAP, {})
    return {
        str(cusip).upper().replace(" ", ""): str(item.get("ticker") or "").upper()
        for cusip, item in (payload.get("map") or {}).items()
        if item.get("ticker")
    }


def aggregate(holdings: list[dict], cusip_tickers: dict[str, str]) -> dict[str, dict]:
    """Sum shares/value per resolved ticker within one filing."""
    agg: dict[str, dict] = {}
    for h in holdings:
        cusip = str(h.get("cusip") or "").upper().replace(" ", "")
        ticker = str(h.get("ticker") or cusip_tickers.get(cusip) or "").upper().strip()
        if not TICKER_RE.match(ticker):
            continue
        row = agg.setdefault(ticker, {
            "ticker": ticker, "company": h.get("company") or ticker,
            "shares": 0.0, "market_value": 0.0, "pct_portfolio": 0.0,
        })
        row["shares"] += float(h.get("shares") or 0)
        row["market_value"] += float(h.get("market_value") or 0)
        row["pct_portfolio"] += float(h.get("pct_portfolio") or 0)
    return agg


def price_of(row: dict) -> float | None:
    sh, mv = row.get("shares"), row.get("market_value")
    if sh and mv:
        return mv / sh
    return None


def main() -> int:
    history = load_json(SEC_HISTORY, {})
    investors = history.get("investors") or []
    if not investors:
        print("No SEC 13F history found; leaving holdings-latest.json untouched.")
        return 1

    quotes = live_prices()
    cusip_tickers = load_cusip_tickers()
    all_quarters = sorted(
        {f.get("quarter") for inv in investors for f in inv.get("filings", []) if f.get("quarter")},
        key=quarter_key,
    )
    if not all_quarters:
        return 1
    latest_q, prev_q = all_quarters[-1], (all_quarters[-2] if len(all_quarters) > 1 else None)

    holdings: list[dict] = []
    convergence: dict[str, set] = defaultdict(set)

    for inv in investors:
        name = inv.get("name")
        fund = inv.get("fund") or ""
        by_quarter = {
            f.get("quarter"): aggregate(f.get("holdings", []), cusip_tickers)
            for f in inv.get("filings", [])
        }
        current = by_quarter.get(latest_q)
        if not current:
            continue  # no latest-quarter filing (e.g. a manager who stopped filing)
        previous = by_quarter.get(prev_q, {}) if prev_q else {}
        # earliest quarter each ticker appears, for an entry approximation
        first_seen: dict[str, str] = {}
        for q in all_quarters:
            for t in by_quarter.get(q, {}):
                first_seen.setdefault(t, q)

        for ticker, row in current.items():
            convergence[ticker].add(name)
            cur_px = quotes.get(ticker) or price_of(row)
            entry_q = first_seen.get(ticker, latest_q)
            entry_px = price_of(by_quarter.get(entry_q, {}).get(ticker, {})) or cur_px
            unreal = ((cur_px - entry_px) / entry_px * 100) if (cur_px and entry_px) else None
            prev_row = previous.get(ticker)
            if not prev_row:
                trend = "NEW"
            else:
                ds = row["shares"] - prev_row["shares"]
                base = prev_row["shares"] or 1
                trend = "ADDING" if ds / base >= 0.01 else "TRIMMING" if ds / base <= -0.01 else "HOLDING"
            hold_q = sum(1 for q in all_quarters if quarter_key(entry_q) <= quarter_key(q) <= quarter_key(latest_q))
            holdings.append({
                "ticker": ticker,
                "company": row["company"],
                "investor": name,
                "fund": fund,
                "shares": round(row["shares"]) or None,
                "value_usd": round(row["market_value"]) or None,
                "pct_portfolio": round(row["pct_portfolio"], 2) or None,
                "current_price": round(cur_px, 2) if cur_px else None,
                "entry_quarter": entry_q,
                "entry_price": round(entry_px, 2) if entry_px else None,
                "entry_price_45d": round(entry_px, 2) if entry_px else None,
                "unrealized_pct": round(unreal, 2) if unreal is not None else None,
                "pct_change_since_entry": round(unreal, 2) if unreal is not None else None,
                "trend": trend,
                "hold_duration": hold_q,
            })

    for h in holdings:
        n = len(convergence.get(h["ticker"], ()))
        h["convergence"] = n
        h["convergence_score"] = n
        h["conviction"] = min(n, 10)

    holdings.sort(key=lambda h: (-(h["convergence"]), -(h.get("value_usd") or 0)))
    OUTPUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "data/sec-13f-filings.json (latest 13F per investor)",
        "total_holdings": len(holdings),
        "total_investors": len({h["investor"] for h in holdings}),
        "latest_quarter": latest_q,
        "holdings": holdings,
        "summary": {"unique_stocks": len(convergence), "holdings": len(holdings)},
    }, indent=2) + "\n")
    print(f"Wrote {OUTPUT.name}: {len(holdings)} holdings, "
          f"{len({h['investor'] for h in holdings})} investors, latest {latest_q}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
