#!/usr/bin/env python3
"""Build the MOSE 13F tracker export used by the static dashboard."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HOLDINGS_PATH = ROOT / "holdings-latest.json"
SEC_HISTORY_PATH = ROOT / "data" / "sec-13f-filings.json"
OUTPUT_PATH = ROOT / "filing-changes-latest.json"
CIK_MAP_PATH = ROOT / "reference-data" / "cik-map.json"
CUSIP_MAP_PATH = ROOT / "reference-data" / "cusip-map.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    tmp.replace(path)


def quarter_sort_key(value: str | None) -> tuple[int, int]:
    if not value or "-Q" not in value:
        return (0, 0)
    year, quarter = value.split("-Q", 1)
    try:
        return (int(year), int(quarter))
    except ValueError:
        return (0, 0)


def prior_quarter(value: str | None) -> str | None:
    year, quarter = quarter_sort_key(value)
    if not year or not quarter:
        return None
    if quarter == 1:
        return f"{year - 1}-Q4"
    return f"{year}-Q{quarter - 1}"


def change_type(holding: dict[str, Any], latest_quarter: str | None) -> str:
    trend = str(holding.get("trend") or "").upper()
    entry_quarter = holding.get("entry_quarter")
    if entry_quarter == latest_quarter or trend == "NEW":
        return "new"
    if trend == "ADDING":
        return "add"
    if trend == "TRIMMING":
        return "trim"
    if trend == "EXITED":
        return "exit"
    return "hold"


def pct_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def row_key(row: dict[str, Any]) -> str:
    cusip = str(row.get("cusip") or "").upper().replace(" ", "")
    if cusip:
        return f"CUSIP:{cusip}"
    return str(row.get("ticker") or row.get("identifier") or "").upper()




def load_cusip_tickers() -> dict[str, str]:
    payload = load_json(CUSIP_MAP_PATH, {})
    return {
        str(cusip).upper().replace(" ", ""): str(item.get("ticker") or "").upper()
        for cusip, item in (payload.get("map") or {}).items()
        if item.get("ticker")
    }


def aggregate_holdings(
    rows: list[dict[str, Any]],
    cusip_tickers: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        row = {**row}
        cusip = str(row.get("cusip") or "").upper().replace(" ", "")
        if not row.get("ticker") and cusip and cusip_tickers:
            row["ticker"] = cusip_tickers.get(cusip)
            if row.get("ticker"):
                row["identifier"] = row["ticker"]
        key = row_key(row)
        if not key:
            continue
        current = aggregated.get(key)
        if not current:
            current = {**row}
            current["market_value"] = 0.0
            current["shares"] = 0.0
            current["pct_portfolio"] = 0.0
            aggregated[key] = current
        current["market_value"] = pct_float(current.get("market_value")) + pct_float(row.get("market_value"))
        current["shares"] = pct_float(current.get("shares")) + pct_float(row.get("shares"))
        current["pct_portfolio"] = pct_float(current.get("pct_portfolio")) + pct_float(row.get("pct_portfolio"))
        if not current.get("ticker") and row.get("ticker"):
            current["ticker"] = row["ticker"]
            current["identifier"] = row.get("identifier") or row["ticker"]
        current["rank"] = min(
            [rank for rank in [current.get("rank"), row.get("rank")] if isinstance(rank, int)],
            default=current.get("rank"),
        )
    return aggregated

def classify_change(current: dict[str, Any] | None, previous: dict[str, Any] | None) -> str:
    if current and not previous:
        return "new"
    if previous and not current:
        return "exit"
    if not current or not previous:
        return "hold"
    current_shares = pct_float(current.get("shares"))
    previous_shares = pct_float(previous.get("shares"))
    if previous_shares <= 0:
        return "hold"
    delta_pct = (current_shares - previous_shares) / previous_shares
    if delta_pct >= 0.01:
        return "add"
    if delta_pct <= -0.01:
        return "trim"
    return "hold"


def build_from_sec_history(history: dict[str, Any]) -> dict[str, Any] | None:
    investors_raw = history.get("investors") or []
    all_quarters = sorted(
        {filing.get("quarter") for inv in investors_raw for filing in inv.get("filings", []) if filing.get("quarter")},
        key=quarter_sort_key,
    )
    if len(all_quarters) < 2:
        return None
    latest_quarter = all_quarters[-1]
    previous_quarter = all_quarters[-2]

    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    changes: list[dict[str, Any]] = []
    investor_summaries = []
    cusip_tickers = load_cusip_tickers()

    for investor in investors_raw:
        filings = {f.get("quarter"): f for f in investor.get("filings", [])}
        current_filing = filings.get(latest_quarter)
        previous_filing = filings.get(previous_quarter)
        if not current_filing and not previous_filing:
            continue
        current_map = aggregate_holdings((current_filing or {}).get("holdings", []), cusip_tickers)
        previous_map = aggregate_holdings((previous_filing or {}).get("holdings", []), cusip_tickers)
        keys = sorted(set(current_map) | set(previous_map))
        rows = []
        for key in keys:
            current = current_map.get(key)
            previous = previous_map.get(key)
            source = current or previous or {}
            ctype = classify_change(current, previous)
            current_value = pct_float((current or {}).get("market_value"))
            previous_value = pct_float((previous or {}).get("market_value"))
            current_shares = pct_float((current or {}).get("shares"))
            previous_shares = pct_float((previous or {}).get("shares"))
            row = {
                "ticker": source.get("ticker"),
                "identifier": source.get("identifier") or key,
                "cusip": source.get("cusip"),
                "company": source.get("company") or key,
                "investor": investor.get("name"),
                "fund": investor.get("fund") or "",
                "quarter": latest_quarter,
                "previous_quarter": previous_quarter,
                "change_type": ctype,
                "trend": {"new": "NEW", "add": "ADDING", "trim": "TRIMMING", "exit": "EXITED"}.get(ctype, "HOLDING"),
                "shares": current_shares if current is not None else None,
                "previous_shares": previous_shares if previous is not None else None,
                "shares_delta": (current_shares - previous_shares) if current or previous else None,
                "market_value": current_value if current is not None else None,
                "previous_market_value": previous_value if previous is not None else None,
                "market_value_delta": current_value - previous_value,
                "pct_portfolio": (current or {}).get("pct_portfolio"),
                "previous_pct_portfolio": (previous or {}).get("pct_portfolio"),
                "rank": (current or previous or {}).get("rank"),
                "filing_date": (current_filing or previous_filing or {}).get("filing_date"),
                "source": "SEC EDGAR 13F-HR",
                "convergence": 1,
            }
            rows.append(row)
            by_ticker[row.get("ticker") or row["identifier"]].append(row)
            if ctype != "hold":
                changes.append(row)

        rows.sort(key=lambda r: (r["change_type"] == "exit", pct_float(r.get("market_value") or r.get("previous_market_value"))), reverse=True)
        counts = defaultdict(int)
        for row in rows:
            counts[row["change_type"]] += 1
        investor_summaries.append(
            {
                "name": investor.get("name"),
                "fund": investor.get("fund") or "",
                "cik": investor.get("cik"),
                "tier": investor.get("tier", 1),
                "source_type": investor.get("source_type", "13F"),
                "latest_quarter": latest_quarter,
                "previous_quarter": previous_quarter,
                "filing_date": (current_filing or {}).get("filing_date"),
                "previous_filing_date": (previous_filing or {}).get("filing_date"),
                "total_positions": len(current_map),
                "total_value": (current_filing or {}).get("total_value"),
                "new_positions": counts["new"],
                "adds": counts["add"],
                "trims": counts["trim"],
                "exits": counts["exit"],
                "positions": rows,
                "top_positions": rows[:10],
            }
        )

    ticker_summaries = []
    for ticker, rows in by_ticker.items():
        add_like = [r for r in rows if r["change_type"] in {"new", "add"}]
        trim_like = [r for r in rows if r["change_type"] in {"trim", "exit"}]
        ticker_summaries.append(
            {
                "ticker": rows[0].get("ticker"),
                "identifier": rows[0].get("identifier") or ticker,
                "company": rows[0].get("company") or ticker,
                "investor_count": len({r["investor"] for r in rows if r["change_type"] != "exit"}),
                "buyers": len({r["investor"] for r in add_like}),
                "sellers": len({r["investor"] for r in trim_like}),
                "total_value": sum(pct_float(r.get("market_value")) for r in rows),
                "changes": rows,
            }
        )

    changes.sort(
        key=lambda r: (
            {"new": 4, "add": 3, "trim": 2, "exit": 1}.get(r["change_type"], 0),
            abs(pct_float(r.get("market_value_delta"))),
        ),
        reverse=True,
    )
    investor_summaries.sort(key=lambda r: (r["new_positions"] + r["adds"] + r["trims"] + r["exits"], r["total_positions"]), reverse=True)
    ticker_summaries.sort(key=lambda r: (r["buyers"], r["investor_count"], r["total_value"]), reverse=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "data/sec-13f-filings.json",
        "latest_quarter": latest_quarter,
        "previous_quarter": previous_quarter,
        "available_quarters": all_quarters,
        "note": "Built from SEC EDGAR 13F information-table history. Tickers depend on available CUSIP/ticker mapping; unmapped securities display by CUSIP.",
        "investor_count": len(investor_summaries),
        "holding_count": sum(i.get("total_positions") or 0 for i in investor_summaries),
        "change_count": len(changes),
        "investors": investor_summaries,
        "changes": changes,
        "tickers": ticker_summaries,
    }


def build_from_legacy_holdings() -> dict[str, Any]:
    source = load_json(HOLDINGS_PATH, {})
    holdings = source.get("holdings") or []
    latest_quarter = source.get("latest_quarter") or "Unknown"
    previous_quarter = prior_quarter(latest_quarter) or "Prior quarter"
    cik_registry = {item.get("name"): item for item in load_json(CIK_MAP_PATH, []) if item.get("name")}

    by_investor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    changes: list[dict[str, Any]] = []

    for holding in holdings:
        investor = holding.get("investor") or "Unknown"
        ticker = holding.get("ticker") or "UNKNOWN"
        ctype = change_type(holding, latest_quarter)
        row = {
            "ticker": ticker,
            "company": holding.get("company") or ticker,
            "investor": investor,
            "fund": holding.get("fund") or "",
            "quarter": latest_quarter,
            "previous_quarter": previous_quarter,
            "change_type": ctype,
            "trend": holding.get("trend") or "HOLDING",
            "shares": holding.get("shares"),
            "market_value": holding.get("value_usd") or holding.get("reported_value"),
            "pct_portfolio": holding.get("pct_portfolio"),
            "rank": None,
            "filing_date": holding.get("filing_date"),
            "source": holding.get("data_source") or "13F-HR (SEC EDGAR)",
            "convergence": holding.get("convergence") or 1,
        }
        by_investor[investor].append(row)
        by_ticker[ticker].append(row)
        if ctype != "hold":
            changes.append(row)

    investor_summaries = []
    for investor, rows in by_investor.items():
        rows.sort(key=lambda r: pct_float(r.get("pct_portfolio")), reverse=True)
        total_value = sum(pct_float(r.get("market_value")) for r in rows)
        registry = cik_registry.get(investor, {})
        counts = defaultdict(int)
        for row in rows:
            counts[row["change_type"]] += 1
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        investor_summaries.append(
            {
                "name": investor,
                "fund": rows[0].get("fund") or registry.get("fund") or "",
                "cik": registry.get("cik"),
                "tier": registry.get("tier", 1),
                "source_type": registry.get("source_type", "13F"),
                "latest_quarter": latest_quarter,
                "previous_quarter": previous_quarter,
                "filing_date": rows[0].get("filing_date"),
                "total_positions": len(rows),
                "total_value": total_value,
                "new_positions": counts["new"],
                "adds": counts["add"],
                "trims": counts["trim"],
                "exits": counts["exit"],
                "positions": rows,
                "top_positions": rows[:10],
            }
        )

    ticker_summaries = []
    for ticker, rows in by_ticker.items():
        rows.sort(key=lambda r: (r["change_type"] != "hold", pct_float(r.get("pct_portfolio"))), reverse=True)
        add_like = [r for r in rows if r["change_type"] in {"new", "add"}]
        trim_like = [r for r in rows if r["change_type"] in {"trim", "exit"}]
        ticker_summaries.append(
            {
                "ticker": ticker,
                "company": rows[0].get("company") or ticker,
                "investor_count": len({r["investor"] for r in rows}),
                "buyers": len({r["investor"] for r in add_like}),
                "sellers": len({r["investor"] for r in trim_like}),
                "total_value": sum(pct_float(r.get("market_value")) for r in rows),
                "changes": rows,
            }
        )

    changes.sort(
        key=lambda r: (
            {"new": 4, "add": 3, "trim": 2, "exit": 1}.get(r["change_type"], 0),
            pct_float(r.get("pct_portfolio")),
        ),
        reverse=True,
    )
    investor_summaries.sort(key=lambda r: (r["new_positions"] + r["adds"] + r["trims"] + r["exits"], r["total_positions"]), reverse=True)
    ticker_summaries.sort(key=lambda r: (r["buyers"], r["investor_count"], r["total_value"]), reverse=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(HOLDINGS_PATH.name),
        "latest_quarter": latest_quarter,
        "previous_quarter": previous_quarter,
        "available_quarters": [previous_quarter, latest_quarter],
        "note": "Fallback built from holdings-latest.json. Run scripts/pull_sec_13f_history.py to populate real SEC quarter history.",
        "investor_count": len(investor_summaries),
        "holding_count": len(holdings),
        "change_count": len(changes),
        "investors": investor_summaries,
        "changes": changes,
        "tickers": ticker_summaries,
    }


def build() -> dict[str, Any]:
    history = load_json(SEC_HISTORY_PATH, {})
    if history:
        from_history = build_from_sec_history(history)
        if from_history:
            return from_history
    return build_from_legacy_holdings()


def main() -> int:
    if not HOLDINGS_PATH.exists():
        raise SystemExit(f"Missing {HOLDINGS_PATH}")
    output = build()
    write_json(OUTPUT_PATH, output)
    print(f"Wrote {OUTPUT_PATH} with {output['investor_count']} investors and {output['change_count']} changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
