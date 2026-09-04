#!/usr/bin/env python3
"""Build Joe's review shortlist using an alternate 13F index transport.

The primary source remains each SEC filing. forms13f.com is used only as a
transport/index fallback when SEC bulk downloads are unavailable from the
runner. Every finalist retains original SEC filing URLs for human verification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from build_investor_universe import (
    CIK_MAP_PATH,
    DECISIONS_PATH,
    OUTPUT_PATH,
    POLICY_PATH,
    build_tracked_bootstrap,
    clean_cik,
    load_json,
    score_manager,
    write_json_atomic,
)
from investor_profile import (
    cover_pre_score,
    derive_archetype_baseline,
    discovery_failures,
    excluded_name,
    profile_fit,
)


ROOT = Path(__file__).resolve().parents[1]
API_BASE = "https://forms13f.com/api/v1"
SEC_DATASET_PAGE = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
DEFAULT_CACHE = ROOT / ".cache" / "forms13f"
FUND_NAME_PATTERNS = (
    " ETF",
    "ETF ",
    " INDEX FUND",
    " INDEX FD",
    "ISHARES ",
    "SPDR ",
    "VANGUARD ",
    "PROSHARES ",
    "DIREXION ",
    " SELECT SECTOR ",
)


def request_json(
    endpoint: str,
    params: dict[str, Any],
    cache_dir: Path,
    refresh: bool = False,
) -> Any:
    query = urllib.parse.urlencode(params)
    url = f"{API_BASE}/{endpoint}?{query}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cache_path = cache_dir / f"{cache_key}.json"
    if cache_path.exists() and not refresh:
        return load_json(cache_path, [])

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": os.environ.get(
                "SEC_USER_AGENT",
                "MOSE Codex Lab/1.0 roblobsterclaw@users.noreply.github.com",
            ),
        },
    )
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
            write_json_atomic(cache_path, payload)
            return payload
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in {429, 500, 502, 503, 504}:
                break
            time.sleep(2**attempt)
    raise RuntimeError(f"13F transport failed for {endpoint}: {last_error}") from last_error


def paginated_request(
    endpoint: str,
    params: dict[str, Any],
    cache_dir: Path,
    refresh: bool = False,
    max_pages: int = 200,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    limit = 100
    for page in range(max_pages):
        batch = request_json(
            endpoint,
            {**params, "offset": page * limit, "limit": limit},
            cache_dir,
            refresh,
        )
        if not isinstance(batch, list):
            raise RuntimeError(f"Unexpected {endpoint} response type: {type(batch).__name__}")
        rows.extend(batch)
        if len(batch) < limit:
            return rows
        time.sleep(0.03)
    raise RuntimeError(f"Pagination limit reached for {endpoint}")


def selected_filing_set(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    ordered = sorted(
        rows,
        key=lambda row: (str(row.get("filed_as_of_date") or ""), str(row.get("accession_number") or "")),
    )
    for row in ordered:
        form = str(row.get("submission_type") or row.get("form_type") or "").upper()
        if form == "13F-HR":
            selected = [row]
        elif form == "13F-HR/A":
            amendment_type = str(row.get("amendment_type") or "").upper()
            if "NEW HOLDINGS" in amendment_type and selected:
                selected.append(row)
            else:
                selected = [row]
    return selected


def group_filing_sets(
    rows: list[dict[str, Any]],
    period_end: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        period = str(row.get("period_of_report") or "")
        if period and (period_end is None or period == period_end):
            grouped[period].append(row)
    return {
        period: selected_filing_set(items)
        for period, items in grouped.items()
        if selected_filing_set(items)
    }


def filing_set_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest = rows[-1]
    return {
        "cik": clean_cik(str(latest.get("cik") or "")),
        "name": latest.get("company_name") or clean_cik(str(latest.get("cik") or "")),
        "total_value_usd": sum(float(row.get("table_value_total") or 0) for row in rows),
        "cover_entries": sum(int(row.get("table_entry_total") or 0) for row in rows),
        "filing_urls": [row.get("url") for row in rows if row.get("url")],
        "filings": rows,
    }


def form_holdings(
    filing: dict[str, Any],
    cache_dir: Path,
    refresh: bool,
) -> list[dict[str, Any]]:
    return paginated_request(
        "form",
        {
            "accession_number": filing.get("accession_number"),
            "cik": filing.get("cik"),
        },
        cache_dir,
        refresh,
        max_pages=20,
    )


def snapshot_from_filing_set(
    filing_set: list[dict[str, Any]],
    cache_dir: Path,
    refresh: bool,
) -> dict[str, Any]:
    holdings: dict[str, float] = defaultdict(float)
    long_value = 0.0
    option_value = 0.0
    fund_value = 0.0
    for filing in filing_set:
        for row in form_holdings(filing, cache_dir, refresh):
            value = float(row.get("value") or 0)
            if str(row.get("put_call") or "").strip():
                option_value += value
                continue
            cusip = str(row.get("cusip") or "").upper().replace(" ", "")
            if not cusip:
                continue
            holdings[cusip] += value
            long_value += value
            issuer = f" {str(row.get('name_of_issuer') or '').upper()} "
            title = f" {str(row.get('title_of_class') or '').upper()} "
            if any(pattern in issuer or pattern in title for pattern in FUND_NAME_PATTERNS):
                fund_value += value
    latest = filing_set[-1]
    return {
        "name": latest.get("company_name") or clean_cik(str(latest.get("cik") or "")),
        "holdings": dict(holdings),
        "positions": len(holdings),
        "total_value_usd": long_value,
        "option_value_usd": option_value,
        "long_only_value_ratio": long_value / (long_value + option_value) if long_value + option_value else 0.0,
        "fund_value_ratio": fund_value / long_value if long_value else 0.0,
        "filing_urls": [row.get("url") for row in filing_set if row.get("url")],
    }


def date_to_quarter(value: str) -> str:
    parsed = datetime.strptime(value, "%Y-%m-%d")
    return f"{parsed.year}-Q{((parsed.month - 1) // 3) + 1}"


def prior_quarter_end(reference: date | None = None) -> date:
    current = reference or date.today()
    quarter = (current.month - 1) // 3 + 1
    if quarter == 1:
        return date(current.year - 1, 12, 31)
    month = (quarter - 1) * 3 + 1
    return date(current.year, month, 1) - timedelta(days=1)


def build_api_universe(
    period_end: str,
    filing_from: str,
    filing_to: str,
    cache_dir: Path,
    refresh: bool = False,
    history_pool_limit: int = 180,
    holdings_pool_limit: int = 90,
    output_limit: int = 75,
    output_path: Path = OUTPUT_PATH,
) -> dict[str, Any]:
    policy = load_json(POLICY_PATH, {})
    bootstrap_path = output_path.with_suffix(".approved.tmp.json")
    existing = build_tracked_bootstrap(bootstrap_path)
    bootstrap_path.unlink(missing_ok=True)
    profile = derive_archetype_baseline(
        policy["joe_style_profile"],
        existing.get("candidates", []),
    )
    profile_gates = profile["discovery_gates"]
    approved_config = {
        clean_cik(str(row.get("cik") or "")): row
        for row in load_json(CIK_MAP_PATH, [])
        if row.get("cik") and row.get("active", True)
    }
    decisions = {
        clean_cik(str(row.get("cik") or "")): row
        for row in load_json(DECISIONS_PATH, {"decisions": []}).get("decisions", [])
        if row.get("cik")
    }

    print(f"Discovering 13F filers for report period {period_end}", flush=True)
    filings = paginated_request(
        "filings",
        {"from": filing_from, "to": filing_to},
        cache_dir,
        refresh,
        max_pages=160,
    )
    latest_rows = [
        row
        for row in filings
        if row.get("period_of_report") == period_end
        and str(row.get("submission_type") or "").upper() in {"13F-HR", "13F-HR/A"}
    ]
    by_cik: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in latest_rows:
        by_cik[clean_cik(str(row.get("cik") or ""))].append(row)

    exclusion_patterns = list(policy.get("excluded_manager_name_patterns", [])) + list(
        profile.get("excluded_manager_name_patterns", [])
    )
    required_markers = profile.get("required_manager_name_markers", [])
    cover_candidates: list[dict[str, Any]] = []
    for cik, rows in by_cik.items():
        selected = selected_filing_set(rows)
        if not selected or cik in approved_config or decisions.get(cik, {}).get("decision") == "reject":
            continue
        summary = filing_set_summary(selected)
        failures = excluded_name(str(summary["name"]), exclusion_patterns)
        manager_name = f" {str(summary['name']).upper()} "
        value = summary["total_value_usd"]
        entries = summary["cover_entries"]
        if failures or not any(marker in manager_name for marker in required_markers):
            continue
        if not (
            profile_gates["minimum_total_value_usd"] <= value <= profile_gates["maximum_total_value_usd"]
            and profile_gates["minimum_positions"] <= entries <= profile_gates["maximum_cover_entries"]
        ):
            continue
        summary["cover_pre_score"] = cover_pre_score(summary, profile)
        cover_candidates.append(summary)
    cover_candidates.sort(key=lambda row: (-row["cover_pre_score"], row["name"]))
    history_pool = cover_candidates[:history_pool_limit]
    print(
        f"Latest-quarter filers={len(by_cik)}, broad profile={len(cover_candidates)}, "
        f"history pool={len(history_pool)}",
        flush=True,
    )

    history_from = f"{int(period_end[:4]) - 3}-01-01"
    history_to = filing_to
    histories: list[dict[str, Any]] = []
    for index, candidate in enumerate(history_pool, start=1):
        cik = candidate["cik"]
        forms = paginated_request(
            "forms",
            {"cik": cik.zfill(10), "from": history_from, "to": history_to},
            cache_dir,
            refresh,
            max_pages=4,
        )
        quarter_sets = group_filing_sets(forms)
        quarter_sets = {
            period: selected
            for period, selected in quarter_sets.items()
            if period <= period_end
        }
        periods = sorted(quarter_sets, reverse=True)[: policy["history_quarters"]]
        if len(periods) < profile_gates["minimum_history_quarters"]:
            continue
        cover_counts = [sum(int(row.get("table_entry_total") or 0) for row in quarter_sets[p]) for p in periods]
        stability = 1.0 - min(1.0, statistics.pstdev(cover_counts) / max(1.0, statistics.mean(cover_counts)))
        candidate["quarter_sets"] = {period: quarter_sets[period] for period in periods}
        candidate["history_pre_score"] = candidate["cover_pre_score"] + 10 * (len(periods) / policy["history_quarters"]) + 10 * stability
        histories.append(candidate)
        if index % 25 == 0:
            print(f"  metadata {index}/{len(history_pool)}", flush=True)
    histories.sort(key=lambda row: (-row["history_pre_score"], row["name"]))
    holdings_pool = histories[:holdings_pool_limit]
    print(f"Holdings analysis pool={len(holdings_pool)}", flush=True)

    qualified: list[dict[str, Any]] = []
    for index, candidate in enumerate(holdings_pool, start=1):
        snapshots: list[tuple[str, dict[str, Any]]] = []
        latest_urls: list[str] = []
        for period, filing_set in sorted(candidate["quarter_sets"].items()):
            snapshot = snapshot_from_filing_set(filing_set, cache_dir, refresh)
            snapshots.append((date_to_quarter(period), snapshot))
            if period == period_end:
                latest_urls = snapshot["filing_urls"]
        row = score_manager(candidate["cik"], snapshots, policy, {}, {})
        row["structure_score"] = row["score"]
        fit_score, fit_components, lane = profile_fit(row, profile)
        failures = discovery_failures(row, profile)
        if fit_score < profile_gates["minimum_profile_fit_score"]:
            failures.append("profile fit score below minimum")
        row.update(
            {
                "name": candidate["name"],
                "fund": candidate["name"],
                "score": fit_score,
                "profile_fit_score": fit_score,
                "profile_fit_components": fit_components,
                "style_lane": lane,
                "status": "candidate" if not failures else "rejected",
                "meets_quantitative_screen": not failures,
                "screen_failures": failures,
                "cover_pre_score": candidate["cover_pre_score"],
                "philosophy_evidence_status": "required_before_approval",
                "filing_urls": latest_urls,
                "source": "SEC filings indexed through forms13f.com fallback transport",
            }
        )
        if row["status"] == "candidate":
            qualified.append(row)
        if index % 10 == 0:
            print(f"  holdings {index}/{len(holdings_pool)}; qualified={len(qualified)}", flush=True)

    qualified.sort(key=lambda row: (-row["profile_fit_score"], row["name"]))
    qualified = qualified[:output_limit]
    for rank, row in enumerate(qualified, start=1):
        row["candidate_rank"] = rank

    approved_rows = []
    for row in existing.get("candidates", []):
        if row.get("status") != "approved":
            continue
        row = {**row}
        row["structure_score"] = row.get("score")
        fit_score, fit_components, lane = profile_fit(row, profile)
        row["score"] = fit_score
        row["profile_fit_score"] = fit_score
        row["profile_fit_components"] = fit_components
        row["style_lane"] = lane if lane != "outside_profile" else "approved_outlier"
        row["philosophy_evidence_status"] = "grandfathered_refresh_due"
        approved_rows.append(row)
    approved_rows.sort(key=lambda row: (-row["profile_fit_score"], row["name"]))

    latest_quarter = date_to_quarter(period_end)
    payload = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "name": "SEC Form 13F filings with forms13f.com index transport",
            "url": SEC_DATASET_PAGE,
            "transport_url": API_BASE,
            "latest_report_quarter": latest_quarter,
            "period_end": period_end,
            "scope": "full_filer_discovery_fallback",
            "filers_discovered": len(by_cik),
            "original_filing_urls_retained": True,
            "disclaimer": "The transport is third-party. Every finalist requires review against the retained original SEC filing URLs before approval.",
        },
        "policy_version": policy["policy_version"],
        "style_profile": profile,
        "qualification_policy": {
            "hard_gates": profile_gates,
            "score_weights": profile["profile_score_weights"],
        },
        "target_approved_count": policy["target_approved_count"],
        "approved_count": len(approved_rows),
        "candidate_count": len(qualified),
        "core_candidate_count": sum(1 for row in qualified if row["style_lane"] == "core_patient_value"),
        "adventurous_candidate_count": sum(1 for row in qualified if row["style_lane"] == "adventurous_value"),
        "approved_needing_review_count": sum(1 for row in approved_rows if not row.get("meets_quantitative_screen")),
        "screened_manager_count": len(by_cik),
        "cover_prefilter_count": len(cover_candidates),
        "history_screened_count": len(history_pool),
        "holdings_screened_count": len(holdings_pool),
        "screened_out_count": max(0, len(cover_candidates) - len(qualified)),
        "rules": {
            "approval": "Joe must explicitly approve every new addition.",
            "style": "Candidates are split into core patient value and adventurous value lanes.",
            "evidence": "13F behavior nominates; primary-source philosophy review qualifies.",
            "source_verification": "Original SEC filing URLs must be checked before an approval is committed.",
        },
        "candidates": approved_rows + qualified,
    }
    return payload


def parse_args() -> argparse.Namespace:
    default_period_end = prior_quarter_end().isoformat()
    period_date = datetime.strptime(default_period_end, "%Y-%m-%d").date()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period-end", default=default_period_end)
    parser.add_argument("--filing-from", default=(period_date + timedelta(days=1)).isoformat())
    parser.add_argument("--filing-to", default=date.today().isoformat())
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--history-pool-limit", type=int, default=180)
    parser.add_argument("--holdings-pool-limit", type=int, default=90)
    parser.add_argument("--output-limit", type=int, default=75)
    parser.add_argument("--minimum-candidates", type=int, default=20)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_api_universe(
        period_end=args.period_end,
        filing_from=args.filing_from,
        filing_to=args.filing_to,
        cache_dir=args.cache_dir,
        refresh=args.refresh,
        history_pool_limit=args.history_pool_limit,
        holdings_pool_limit=args.holdings_pool_limit,
        output_limit=args.output_limit,
        output_path=args.output,
    )
    print(
        f"Shortlist: {payload['candidate_count']} candidates "
        f"({payload['core_candidate_count']} core, {payload['adventurous_candidate_count']} adventurous)",
        flush=True,
    )
    if payload["candidate_count"] < args.minimum_candidates:
        print(
            f"Refusing to publish: only {payload['candidate_count']} candidates passed; "
            f"minimum is {args.minimum_candidates}",
            file=sys.stderr,
        )
        return 3
    write_json_atomic(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
