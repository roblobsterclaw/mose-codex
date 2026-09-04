#!/usr/bin/env python3
"""Validate the published 13F and Top 50 artifacts before deployment."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "data" / "sec-13f-filings.json"
TRACKER_PATH = ROOT / "filing-changes-latest.json"
HOLDINGS_PATH = ROOT / "holdings-latest.json"
UNIVERSE_PATH = ROOT / "reference-data" / "investor-universe.json"
CIK_MAP_PATH = ROOT / "reference-data" / "cik-map.json"
CUSIP_MAP_PATH = ROOT / "reference-data" / "cusip-map.json"
ELIGIBLE_PATH = ROOT / "eligible-universe.json"
DEFAULT_OUTPUT = ROOT / "reports" / "investor-data-audit.json"
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,10}$")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def clean_cik(value: Any) -> str:
    return str(value or "").strip().lstrip("0") or "0"


def clean_cusip(value: Any) -> str:
    return str(value or "").upper().replace(" ", "")


def expected_change_type(row: dict[str, Any]) -> str:
    current = row.get("shares")
    previous = row.get("previous_shares")
    if current is not None and previous is None:
        return "new"
    if previous is not None and current is None:
        return "exit"
    if current is None or previous in (None, 0):
        return "hold"
    delta_pct = (float(current) - float(previous)) / float(previous)
    if delta_pct >= 0.01:
        return "add"
    if delta_pct <= -0.01:
        return "trim"
    return "hold"


def build_audit() -> dict[str, Any]:
    raw = load_json(RAW_PATH)
    tracker = load_json(TRACKER_PATH)
    holdings = load_json(HOLDINGS_PATH)
    universe = load_json(UNIVERSE_PATH)
    cik_map = load_json(CIK_MAP_PATH)
    cusip_map = load_json(CUSIP_MAP_PATH)
    eligible = load_json(ELIGIBLE_PATH)
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    investors = raw.get("investors") or []
    filings = [filing for investor in investors for filing in investor.get("filings", [])]
    active_ciks = {
        clean_cik(row.get("cik"))
        for row in cik_map
        if row.get("cik") and row.get("active", True)
    }
    raw_ciks = {clean_cik(row.get("cik")) for row in investors if row.get("cik")}
    approved_ciks = {
        clean_cik(row.get("cik"))
        for row in universe.get("candidates", [])
        if row.get("status") == "approved"
    }
    universe_rows = universe.get("candidates") or []
    candidate_rows = [row for row in universe_rows if row.get("status") == "candidate"]
    candidate_ciks = [clean_cik(row.get("cik")) for row in candidate_rows]

    check(
        "canonical_market_value_unit",
        raw.get("market_value_unit") == "usd",
        f"market_value_unit={raw.get('market_value_unit')!r}",
    )

    filing_sum_errors = 0
    for filing in filings:
        expected_total = sum(float(row.get("market_value") or 0) for row in filing.get("holdings", []))
        actual_total = float(filing.get("total_value") or 0)
        if abs(expected_total - actual_total) > max(1.0, expected_total * 1e-10):
            filing_sum_errors += 1
    check(
        "filing_totals_match_holdings",
        filing_sum_errors == 0,
        f"{len(filings)} filings checked; {filing_sum_errors} mismatches",
    )

    check(
        "approved_roster_matches_history",
        active_ciks == raw_ciks == approved_ciks,
        f"active={len(active_ciks)}, history={len(raw_ciks)}, approved={len(approved_ciks)}",
    )

    check(
        "investor_universe_counts_match",
        universe.get("approved_count") == len(approved_ciks)
        and universe.get("candidate_count") == len(candidate_rows)
        and len(candidate_ciks) == len(set(candidate_ciks)),
        f"approved={len(approved_ciks)}; candidates={len(candidate_rows)}; unique_candidate_ciks={len(set(candidate_ciks))}",
    )

    valid_lanes = {"core_patient_value", "adventurous_value", "approved_outlier"}
    malformed_candidates = [
        row
        for row in candidate_rows
        if not row.get("meets_quantitative_screen")
        or row.get("screen_failures")
        or row.get("style_lane") not in valid_lanes
        or not row.get("filing_urls")
        or row.get("philosophy_evidence_status") != "required_before_approval"
    ]
    core_count = sum(1 for row in candidate_rows if row.get("style_lane") == "core_patient_value")
    adventurous_count = sum(1 for row in candidate_rows if row.get("style_lane") == "adventurous_value")
    check(
        "investor_candidates_are_auditable",
        not malformed_candidates
        and universe.get("core_candidate_count") == core_count
        and universe.get("adventurous_candidate_count") == adventurous_count,
        f"{len(candidate_rows)} candidates; {len(malformed_candidates)} malformed; core={core_count}; adventurous={adventurous_count}",
    )

    changes = tracker.get("changes") or []
    change_keys = [
        (
            str(row.get("investor") or ""),
            str(row.get("quarter") or ""),
            clean_cusip(row.get("cusip")),
        )
        for row in changes
    ]
    duplicate_change_keys = sum(1 for count in Counter(change_keys).values() if count > 1)
    check(
        "unique_change_rows",
        duplicate_change_keys == 0,
        f"{len(changes)} rows; {duplicate_change_keys} duplicate investor-quarter-CUSIP keys",
    )

    classification_errors = [
        row
        for row in changes
        if row.get("change_type") != expected_change_type(row)
    ]
    check(
        "share_change_classifications",
        not classification_errors,
        f"{len(changes)} rows checked; {len(classification_errors)} inconsistent labels",
    )

    pseudo_tickers = [
        row.get("ticker")
        for row in changes
        if str(row.get("ticker") or "").upper().startswith("CUSIP:")
    ]
    check(
        "no_pseudo_tickers_in_changes",
        not pseudo_tickers,
        f"{len(pseudo_tickers)} CUSIP placeholders found in ticker fields",
    )

    latest_quarter = tracker.get("latest_quarter")
    resolved_cusips = set((cusip_map.get("map") or {}).keys())
    latest_value = 0.0
    resolved_value = 0.0
    for investor in investors:
        for filing in investor.get("filings", []):
            if filing.get("quarter") != latest_quarter:
                continue
            for row in filing.get("holdings", []):
                value = float(row.get("market_value") or 0)
                latest_value += value
                cusip = clean_cusip(row.get("cusip"))
                ticker = str(row.get("ticker") or "").upper()
                if ticker or cusip in resolved_cusips:
                    resolved_value += value
    coverage = resolved_value / latest_value if latest_value else 0.0
    check(
        "cusip_value_coverage",
        coverage >= 0.95,
        f"{coverage:.2%} of {latest_quarter} reported value resolves to a ticker",
    )

    holding_rows = holdings.get("holdings") or []
    holding_keys = [
        (str(row.get("investor") or ""), str(row.get("ticker") or "").upper())
        for row in holding_rows
    ]
    duplicate_holding_keys = sum(1 for count in Counter(holding_keys).values() if count > 1)
    invalid_holding_tickers = [
        row.get("ticker")
        for row in holding_rows
        if not TICKER_RE.match(str(row.get("ticker") or "").upper())
    ]
    check(
        "published_holdings_are_unique_and_resolved",
        duplicate_holding_keys == 0 and not invalid_holding_tickers,
        f"{len(holding_rows)} rows; {duplicate_holding_keys} duplicate keys; {len(invalid_holding_tickers)} invalid tickers",
    )

    eligible_tickers = eligible.get("tickers") or []
    check(
        "eligible_universe_is_current",
        eligible.get("quarter") == latest_quarter and bool(eligible_tickers),
        f"quarter={eligible.get('quarter')}; tickers={len(eligible_tickers)}",
    )

    failures = [row for row in checks if not row["passed"]]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace_key": "mose-codex",
        "status": "passed" if not failures else "failed",
        "latest_quarter": latest_quarter,
        "metrics": {
            "approved_investors": len(approved_ciks),
            "investor_candidates": len(candidate_rows),
            "core_value_candidates": core_count,
            "adventurous_value_candidates": adventurous_count,
            "filings": len(filings),
            "change_rows": len(changes),
            "published_holdings": len(holding_rows),
            "cusip_value_coverage": round(coverage, 6),
            "eligible_tickers": len(eligible_tickers),
        },
        "checks": checks,
        "failure_count": len(failures),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    output = Path(args.output)
    audit = build_audit()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(
        f"Investor data audit {audit['status']}: "
        f"{len(audit['checks']) - audit['failure_count']}/{len(audit['checks'])} checks passed"
    )
    for row in audit["checks"]:
        print(f"  {'PASS' if row['passed'] else 'FAIL'} {row['name']}: {row['detail']}")
    return 0 if audit["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
