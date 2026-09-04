#!/usr/bin/env python3
"""Sync CUSIP-keyed 13F history into isolated MOSE Codex Supabase tables."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TRACKER_PATH = ROOT / "filing-changes-latest.json"
HISTORY_PATH = ROOT / "data" / "sec-13f-filings.json"
CIK_MAP_PATH = ROOT / "reference-data" / "cik-map.json"
CUSIP_MAP_PATH = ROOT / "reference-data" / "cusip-map.json"
WORKSPACE_KEY = "mose-codex"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def clean_cik(value: Any) -> str:
    return str(value or "").strip().lstrip("0") or "0"


def clean_ticker(value: Any) -> str | None:
    ticker = str(value or "").upper().strip()
    if not ticker or ticker.startswith("CUSIP:"):
        return None
    return ticker


def merge_security(
    security_map: dict[str, dict[str, Any]],
    cusip: str,
    ticker: Any,
    company_name: Any,
    source_payload: dict[str, Any],
) -> None:
    resolved_ticker = clean_ticker(ticker)
    existing = security_map.get(cusip)
    if existing is None:
        security_map[cusip] = {
            "workspace_key": WORKSPACE_KEY,
            "cusip": cusip,
            "ticker": resolved_ticker,
            "company_name": company_name,
            "resolution_status": "resolved" if resolved_ticker else "unresolved",
            "source_payload": source_payload,
        }
        return
    if not existing.get("ticker") and resolved_ticker:
        existing["ticker"] = resolved_ticker
        existing["resolution_status"] = "resolved"
        existing["source_payload"] = source_payload
    if not existing.get("company_name") and company_name:
        existing["company_name"] = company_name


class SupabaseClient:
    def __init__(self, url: str, key: str) -> None:
        self.base = url.rstrip("/") + "/rest/v1"
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal,resolution=merge-duplicates",
        }

    def upsert(self, table: str, rows: list[dict[str, Any]], conflict: str, batch_size: int = 500) -> int:
        written = 0
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            if not batch:
                continue
            query = urllib.parse.urlencode({"on_conflict": conflict})
            request = urllib.request.Request(
                f"{self.base}/{table}?{query}",
                data=json.dumps(batch).encode("utf-8"),
                headers=self.headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=120):
                    written += len(batch)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Supabase upsert failed for {table}: HTTP {exc.code}: {body}") from exc
        return written

    def delete(self, table: str, filters: dict[str, str]) -> None:
        query = urllib.parse.urlencode(filters)
        request = urllib.request.Request(
            f"{self.base}/{table}?{query}",
            headers=self.headers,
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(request, timeout=120):
                return
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase delete failed for {table}: HTTP {exc.code}: {body}") from exc

    def delete_in(
        self,
        table: str,
        column: str,
        values: list[str],
        batch_size: int = 100,
    ) -> None:
        for start in range(0, len(values), batch_size):
            batch = values[start : start + batch_size]
            if batch:
                self.delete(
                    table,
                    {
                        "workspace_key": f"eq.{WORKSPACE_KEY}",
                        column: f"in.({','.join(batch)})",
                    },
                )


def aggregate_filing_holdings(filing: dict[str, Any]) -> list[dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}
    for holding in filing.get("holdings", []):
        cusip = str(holding.get("cusip") or "").upper().replace(" ", "")
        if not cusip:
            continue
        row = aggregated.setdefault(
            cusip,
            {
                "cusip": cusip,
                "ticker": holding.get("ticker"),
                "company": holding.get("company"),
                "shares": 0.0,
                "market_value": 0.0,
                "pct_portfolio": 0.0,
                "rank": holding.get("rank"),
                "raw_rows": [],
            },
        )
        row["shares"] += float(holding.get("shares") or 0)
        row["market_value"] += float(holding.get("market_value") or 0)
        row["pct_portfolio"] += float(holding.get("pct_portfolio") or 0)
        row["raw_rows"].append(holding)
        if not row.get("ticker") and holding.get("ticker"):
            row["ticker"] = holding["ticker"]
    return list(aggregated.values())


def build_payloads() -> dict[str, list[dict[str, Any]]]:
    history = load_json(HISTORY_PATH, {})
    tracker = load_json(TRACKER_PATH, {})
    cik_config = {
        clean_cik(row.get("cik")): row
        for row in load_json(CIK_MAP_PATH, [])
        if row.get("cik")
    }
    cusip_tickers = {
        str(cusip).upper().replace(" ", ""): str(item.get("ticker") or "").upper()
        for cusip, item in (load_json(CUSIP_MAP_PATH, {}).get("map") or {}).items()
        if item.get("ticker")
    }
    investors: list[dict[str, Any]] = []
    filings: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    security_map: dict[str, dict[str, Any]] = {}
    investor_name_to_cik: dict[str, str] = {}

    for investor in history.get("investors", []):
        cik = clean_cik(investor.get("cik"))
        config = cik_config.get(cik, {})
        name = investor.get("name") or config.get("name") or cik
        investor_name_to_cik[name] = cik
        investors.append(
            {
                "workspace_key": WORKSPACE_KEY,
                "cik": cik,
                "investor_name": name,
                "fund_name": investor.get("fund") or config.get("fund"),
                "tier": investor.get("tier") or config.get("tier"),
                "active": config.get("active", True),
                "approval_status": config.get("approval_status") or ("approved" if config.get("active", True) else "rejected"),
                "source_payload": {"source_type": investor.get("source_type"), "filing_errors": investor.get("filing_errors", [])},
            }
        )
        for filing in investor.get("filings", []):
            accession = filing.get("accession")
            quarter = filing.get("quarter")
            if not accession or not quarter:
                continue
            filing_holdings = aggregate_filing_holdings(filing)
            filings.append(
                {
                    "workspace_key": WORKSPACE_KEY,
                    "accession": accession,
                    "investor_cik": cik,
                    "form": filing.get("form") or "13F-HR",
                    "report_quarter": quarter,
                    "period_end": filing.get("period_end"),
                    "filing_date": filing.get("filing_date"),
                    "total_value_usd": round(sum(row["market_value"] for row in filing_holdings), 2),
                    "holding_count": len(filing_holdings),
                    "source_url": filing.get("submission_url"),
                    "source_payload": {key: filing.get(key) for key in ("file_name", "company", "num_holdings")},
                }
            )
            for row in filing_holdings:
                cusip = row["cusip"]
                ticker = clean_ticker(row.get("ticker") or cusip_tickers.get(cusip))
                merge_security(
                    security_map,
                    cusip,
                    ticker,
                    row.get("company"),
                    {"identifier": (row.get("raw_rows") or [{}])[0].get("identifier")},
                )
                holdings.append(
                    {
                        "workspace_key": WORKSPACE_KEY,
                        "accession": accession,
                        "investor_cik": cik,
                        "report_quarter": quarter,
                        "cusip": cusip,
                        "ticker": ticker,
                        "company_name": row.get("company"),
                        "shares": row.get("shares"),
                        "market_value_usd": round(row.get("market_value") or 0, 2),
                        "pct_portfolio": row.get("pct_portfolio"),
                        "rank_in_portfolio": row.get("rank"),
                        "source_payload": {"raw_row_count": len(row.get("raw_rows") or [])},
                    }
                )

    changes: list[dict[str, Any]] = []
    for change in tracker.get("changes", []):
        cusip = str(change.get("cusip") or "").upper().replace(" ", "")
        cik = investor_name_to_cik.get(str(change.get("investor") or ""))
        quarter = change.get("quarter") or tracker.get("latest_quarter")
        if not cik or not cusip or not quarter:
            continue
        ticker = clean_ticker(change.get("ticker"))
        merge_security(
            security_map,
            cusip,
            ticker,
            change.get("company"),
            {"identifier": change.get("identifier")},
        )
        changes.append(
            {
                "workspace_key": WORKSPACE_KEY,
                "investor_cik": cik,
                "report_quarter": quarter,
                "previous_quarter": change.get("previous_quarter") or tracker.get("previous_quarter"),
                "cusip": cusip,
                "ticker": ticker,
                "change_type": change.get("change_type") or "hold",
                "shares_current": change.get("shares"),
                "shares_previous": change.get("previous_shares"),
                "market_value_current_usd": float(change.get("market_value") or 0),
                "market_value_previous_usd": float(change.get("previous_market_value") or 0),
                "pct_portfolio_current": change.get("pct_portfolio"),
                "pct_portfolio_previous": change.get("previous_pct_portfolio"),
                "source_payload": {"source": change.get("source"), "identifier": change.get("identifier")},
            }
        )

    return {
        "investors": investors,
        "securities": list(security_map.values()),
        "filings": filings,
        "holdings": holdings,
        "changes": changes,
    }


def main() -> int:
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    payloads = build_payloads()
    client = SupabaseClient(url, key)
    counts = {}
    counts["investors"] = client.upsert("mose_codex_investors", payloads["investors"], "workspace_key,cik")
    counts["securities"] = client.upsert("mose_codex_securities", payloads["securities"], "workspace_key,cusip")
    counts["filings"] = client.upsert("mose_codex_filings", payloads["filings"], "workspace_key,accession")

    accessions = sorted({str(row["accession"]) for row in payloads["filings"]})
    client.delete_in("mose_codex_holdings", "accession", accessions)
    counts["holdings"] = client.upsert(
        "mose_codex_holdings",
        payloads["holdings"],
        "workspace_key,accession,cusip",
    )

    latest_quarter = str(load_json(TRACKER_PATH, {}).get("latest_quarter") or "")
    if latest_quarter:
        client.delete(
            "mose_codex_holding_changes",
            {
                "workspace_key": f"eq.{WORKSPACE_KEY}",
                "report_quarter": f"eq.{latest_quarter}",
            },
        )
    counts["changes"] = client.upsert(
        "mose_codex_holding_changes",
        payloads["changes"],
        "workspace_key,investor_cik,report_quarter,cusip",
    )
    print("Supabase 13F sync: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
