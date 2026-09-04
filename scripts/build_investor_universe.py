#!/usr/bin/env python3
"""Build Joe's reviewable super-investor universe from SEC bulk 13F data.

The scorer is intentionally conservative. It nominates managers from filing
structure and holding behavior, but only an explicit Joe decision can add a new
CIK to the approved tracker.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import statistics
import sys
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "reference-data" / "investor-qualification-policy.json"
DECISIONS_PATH = ROOT / "reference-data" / "investor-decisions.json"
CIK_MAP_PATH = ROOT / "reference-data" / "cik-map.json"
OUTPUT_PATH = ROOT / "reference-data" / "investor-universe.json"
TRACKED_HISTORY_PATH = ROOT / "data" / "sec-13f-filings.json"
DATASET_PAGE = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
DEFAULT_CACHE = ROOT / ".cache" / "sec-13f"


@dataclass(frozen=True)
class DatasetRef:
    url: str
    path: Path


@dataclass
class DatasetMetadata:
    quarter: str
    accession_to_cik: dict[str, str]
    manager_names: dict[str, str]


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")
    temporary.replace(path)


def sec_user_agent() -> str:
    return os.environ.get(
        "SEC_USER_AGENT",
        "MOSE Dashboard/1.0 roblobsterclaw@users.noreply.github.com",
    ).strip()


def request_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": sec_user_agent(),
            "Accept": "text/html,application/zip,application/octet-stream,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def discover_dataset_urls(page_url: str = DATASET_PAGE) -> list[str]:
    html = request_bytes(page_url).decode("utf-8", errors="replace")
    links = re.findall(r'href=["\']([^"\']+form13f\.zip)["\']', html, flags=re.IGNORECASE)
    result: list[str] = []
    for link in links:
        absolute = urllib.parse.urljoin(page_url, link)
        if absolute not in result:
            result.append(absolute)
    if not result:
        raise RuntimeError("SEC 13F page did not expose any bulk data-set links")
    return result


def download_dataset(url: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    name = Path(urllib.parse.urlparse(url).path).name
    destination = cache_dir / name
    if destination.exists() and zipfile.is_zipfile(destination):
        return destination
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    payload = request_bytes(url)
    temporary.write_bytes(payload)
    if not zipfile.is_zipfile(temporary):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"SEC download was not a valid ZIP: {url}")
    temporary.replace(destination)
    return destination


def table_member(archive: zipfile.ZipFile, table: str) -> str:
    wanted = table.upper()
    for name in archive.namelist():
        stem = Path(name).stem.upper()
        if stem == wanted or stem.endswith("_" + wanted):
            return name
    raise RuntimeError(f"{archive.filename} is missing the {table} table")


def table_rows(archive: zipfile.ZipFile, table: str) -> Iterable[dict[str, str]]:
    member = table_member(archive, table)
    with archive.open(member) as raw:
        with io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="") as text:
            reader = csv.DictReader(text, delimiter="\t")
            for row in reader:
                yield {str(key or "").upper(): str(value or "").strip() for key, value in row.items()}


def clean_cik(value: str) -> str:
    return str(value or "").strip().lstrip("0") or "0"


def parse_number(value: str) -> float:
    try:
        return float(str(value or "0").replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def quarter_from_date(value: str) -> str | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    formats = ("%d-%b-%Y", "%Y-%m-%d", "%Y%m%d", "%m-%d-%Y")
    for date_format in formats:
        try:
            date_value = datetime.strptime(text, date_format)
            return f"{date_value.year}-Q{((date_value.month - 1) // 3) + 1}"
        except ValueError:
            continue
    return None


def sortable_date(value: str) -> datetime:
    text = str(value or "").strip().upper()
    for date_format in ("%d-%b-%Y", "%Y-%m-%d", "%Y%m%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue
    return datetime.min


def choose_accessions(archive: zipfile.ZipFile) -> DatasetMetadata:
    covers: dict[str, dict[str, str]] = {}
    for row in table_rows(archive, "COVERPAGE"):
        accession = row.get("ACCESSION_NUMBER", "")
        if accession:
            covers[accession] = row

    submissions: list[dict[str, str]] = []
    quarter_counts: Counter[str] = Counter()
    for row in table_rows(archive, "SUBMISSION"):
        form = row.get("SUBMISSIONTYPE", "").upper()
        if form not in {"13F-HR", "13F-HR/A"}:
            continue
        quarter = quarter_from_date(row.get("PERIODOFREPORT", ""))
        if not quarter:
            continue
        row["_QUARTER"] = quarter
        submissions.append(row)
        if form == "13F-HR":
            quarter_counts[quarter] += 1
    if not quarter_counts:
        raise RuntimeError(f"{archive.filename} has no usable 13F-HR submissions")
    primary_quarter = quarter_counts.most_common(1)[0][0]

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    manager_names: dict[str, str] = {}
    for row in submissions:
        if row["_QUARTER"] != primary_quarter:
            continue
        cik = clean_cik(row.get("CIK", ""))
        grouped[cik].append(row)
        cover = covers.get(row.get("ACCESSION_NUMBER", ""), {})
        name = cover.get("FILINGMANAGER_NAME", "").strip()
        if name:
            manager_names[cik] = name

    accession_to_cik: dict[str, str] = {}
    for cik, rows in grouped.items():
        rows.sort(key=lambda row: (sortable_date(row.get("FILING_DATE", "")), row.get("ACCESSION_NUMBER", "")))
        selected: list[str] = []
        for row in rows:
            accession = row.get("ACCESSION_NUMBER", "")
            form = row.get("SUBMISSIONTYPE", "").upper()
            cover = covers.get(accession, {})
            amendment_type = cover.get("AMENDMENTTYPE", "").upper()
            if form == "13F-HR":
                selected = [accession]
            elif "ADD NEW" in amendment_type and selected:
                selected.append(accession)
            else:
                selected = [accession]
        for accession in selected:
            if accession:
                accession_to_cik[accession] = cik

    return DatasetMetadata(
        quarter=primary_quarter,
        accession_to_cik=accession_to_cik,
        manager_names=manager_names,
    )


def scan_archive(
    path: Path,
    target_ciks: set[str] | None = None,
    include_holdings: bool = True,
) -> tuple[DatasetMetadata, dict[str, dict[str, Any]]]:
    with zipfile.ZipFile(path) as archive:
        metadata = choose_accessions(archive)
        holdings: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        position_cusips: dict[str, set[str]] = defaultdict(set)
        option_value: dict[str, float] = defaultdict(float)
        long_value: dict[str, float] = defaultdict(float)
        for row in table_rows(archive, "INFOTABLE"):
            cik = metadata.accession_to_cik.get(row.get("ACCESSION_NUMBER", ""))
            if not cik or (target_ciks is not None and cik not in target_ciks):
                continue
            value_usd = parse_number(row.get("VALUE", "")) * 1000
            if row.get("PUTCALL", "").strip():
                option_value[cik] += value_usd
                continue
            cusip = row.get("CUSIP", "").upper().replace(" ", "")
            if not cusip:
                continue
            long_value[cik] += value_usd
            position_cusips[cik].add(cusip)
            if include_holdings:
                holdings[cik][cusip] += value_usd

        portfolios: dict[str, dict[str, Any]] = {}
        seen_ciks = set(long_value) | set(option_value) | set(holdings)
        for cik in seen_ciks:
            position_values = dict(holdings.get(cik, {}))
            total_long = long_value.get(cik, 0.0)
            total_options = option_value.get(cik, 0.0)
            portfolios[cik] = {
                "name": metadata.manager_names.get(cik, cik),
                "holdings": position_values,
                "positions": len(position_cusips.get(cik, set())),
                "total_value_usd": total_long,
                "option_value_usd": total_options,
                "long_only_value_ratio": total_long / (total_long + total_options) if total_long + total_options else 0.0,
            }
        return metadata, portfolios


def portfolio_weights(holdings: dict[str, float]) -> dict[str, float]:
    total = sum(holdings.values())
    if total <= 0:
        return {}
    return {cusip: value / total for cusip, value in holdings.items()}


def portfolio_turnover(current: dict[str, float], previous: dict[str, float]) -> float:
    current_weights = portfolio_weights(current)
    previous_weights = portfolio_weights(previous)
    identifiers = set(current_weights) | set(previous_weights)
    return 0.5 * sum(abs(current_weights.get(key, 0) - previous_weights.get(key, 0)) for key in identifiers)


def consecutive_holding_ages(history: list[dict[str, float]]) -> list[int]:
    if not history:
        return []
    ages: list[int] = []
    for cusip in history[-1]:
        age = 0
        for quarter in reversed(history):
            if cusip not in quarter:
                break
            age += 1
        ages.append(age)
    return ages


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def score_manager(
    cik: str,
    snapshots: list[tuple[str, dict[str, Any]]],
    policy: dict[str, Any],
    approved: dict[str, dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    snapshots.sort(key=lambda item: item[0])
    latest_quarter, latest = snapshots[-1]
    history = [snapshot[1].get("holdings", {}) for snapshot in snapshots]
    turnovers = [portfolio_turnover(history[index], history[index - 1]) for index in range(1, len(history))]
    average_turnover = statistics.mean(turnovers) if turnovers else None
    ages = consecutive_holding_ages(history)
    median_hold = statistics.median(ages) if ages else 0.0
    weights = sorted(portfolio_weights(latest.get("holdings", {})).values(), reverse=True)
    top10 = sum(weights[:10])
    positions = int(latest.get("positions") or len(latest.get("holdings", {})))
    total_value = float(latest.get("total_value_usd") or 0)
    long_ratio_raw = latest.get("long_only_value_ratio")
    long_ratio = float(long_ratio_raw) if long_ratio_raw is not None else None
    history_count = len(snapshots)

    score_weights = policy["score_weights"]
    components = {
        "concentration": score_weights["concentration"] * clamp((top10 - 0.35) / 0.65),
        "patience": score_weights["patience"] * clamp((median_hold - 2) / 8),
        "low_turnover": score_weights["low_turnover"] * clamp((0.50 - (average_turnover if average_turnover is not None else 0.50)) / 0.50),
        "reporting_consistency": score_weights["reporting_consistency"] * clamp(history_count / policy["history_quarters"]),
        "cloneability": score_weights["cloneability"] * (1.0 if positions <= 15 else 0.8 if positions <= 30 else 0.6 if positions <= 50 else 0.0),
    }
    score = round(sum(components.values()), 1)

    gates = policy["hard_gates"]
    failures: list[str] = []
    if total_value < gates["minimum_total_value_usd"]:
        failures.append("reported value below minimum")
    if total_value > gates["maximum_total_value_usd"]:
        failures.append("reported value above maximum")
    if positions > gates["maximum_positions"]:
        failures.append("too many reported positions")
    if average_turnover is None or average_turnover > gates["maximum_average_turnover"]:
        failures.append("turnover above limit or insufficient history")
    if median_hold < gates["minimum_median_hold_quarters"]:
        failures.append("median holding age below minimum")
    if history_count < gates["minimum_history_quarters"]:
        failures.append("insufficient quarter history")
    if long_ratio is None:
        failures.append("long-only representation not loaded")
    elif long_ratio < gates["minimum_long_only_value_ratio"]:
        failures.append("options are too material to the reported book")
    upper_name = str(latest.get("name") or "").upper()
    matched_patterns = [pattern for pattern in policy["excluded_manager_name_patterns"] if pattern in upper_name]
    if matched_patterns:
        failures.append("institutional or non-cloneable manager name pattern")

    decision = decisions.get(cik, {})
    is_grandfathered = cik in approved
    if decision.get("decision") == "reject":
        status = "rejected"
    elif decision.get("decision") == "approve" or is_grandfathered:
        status = "approved"
    elif failures:
        status = "rejected"
    else:
        status = "candidate"

    approved_row = approved.get(cik, {})
    display_name = approved_row.get("name") or latest.get("name") or cik
    fund = approved_row.get("fund") or latest.get("name") or display_name
    return {
        "cik": cik,
        "name": display_name,
        "fund": fund,
        "latest_quarter": latest_quarter,
        "positions": positions,
        "total_value_usd": round(total_value),
        "top10_weight": round(top10, 4),
        "turnover_8q": round(average_turnover, 4) if average_turnover is not None else None,
        "median_hold_q": round(float(median_hold), 1),
        "history_quarters": history_count,
        "long_only_value_ratio": round(long_ratio, 4) if long_ratio is not None else None,
        "score": score,
        "score_components": {key: round(value, 1) for key, value in components.items()},
        "status": status,
        "meets_quantitative_screen": not failures,
        "screen_failures": failures,
        "matched_exclusion_patterns": matched_patterns,
        "approval_basis": decision.get("decision") or ("existing_cik_map" if is_grandfathered else None),
        "approved_at": decision.get("decided_at"),
        "review_note": decision.get("reason") or approved_row.get("note"),
        "source": "SEC Form 13F bulk data sets",
    }


def build_universe(dataset_paths: list[Path], output_path: Path = OUTPUT_PATH) -> dict[str, Any]:
    policy = load_json(POLICY_PATH, {})
    if not policy:
        raise RuntimeError(f"Missing policy: {POLICY_PATH}")
    approved_rows = load_json(CIK_MAP_PATH, [])
    approved = {
        clean_cik(row.get("cik", "")): row
        for row in approved_rows
        if row.get("cik") and row.get("active", True)
    }
    decisions_payload = load_json(DECISIONS_PATH, {"decisions": []})
    decisions = {clean_cik(row.get("cik", "")): row for row in decisions_payload.get("decisions", []) if row.get("cik")}

    if not dataset_paths:
        raise RuntimeError("At least one SEC bulk ZIP is required")
    latest_path = dataset_paths[0]
    latest_metadata, latest_summary = scan_archive(latest_path, include_holdings=False)
    gates = policy["hard_gates"]
    target_ciks = set(approved) | set(decisions)
    for cik, portfolio in latest_summary.items():
        if (
            portfolio["positions"] <= gates["maximum_positions"]
            and gates["minimum_total_value_usd"] <= portfolio["total_value_usd"] <= gates["maximum_total_value_usd"]
        ):
            target_ciks.add(cik)

    latest_metadata, latest_portfolios = scan_archive(latest_path, target_ciks=target_ciks)
    snapshots_by_cik: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for index, path in enumerate(dataset_paths):
        metadata, portfolios = (
            (latest_metadata, {cik: row for cik, row in latest_portfolios.items() if cik in target_ciks})
            if index == 0
            else scan_archive(path, target_ciks=target_ciks)
        )
        for cik, portfolio in portfolios.items():
            snapshots_by_cik[cik].append((metadata.quarter, portfolio))

    rows = [
        score_manager(cik, snapshots, policy, approved, decisions)
        for cik, snapshots in snapshots_by_cik.items()
        if snapshots
    ]
    rows.sort(key=lambda row: (row["status"] != "approved", -row["score"], row["name"]))
    approved_rows_out = [row for row in rows if row["status"] == "approved"]
    candidate_rows = [row for row in rows if row["status"] == "candidate"][: int(policy["candidate_limit"])]
    rejected_approved = [row for row in approved_rows_out if not row["meets_quantitative_screen"]]
    output_rows = approved_rows_out + candidate_rows
    for rank, row in enumerate(sorted(candidate_rows, key=lambda item: -item["score"]), start=1):
        row["candidate_rank"] = rank

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "name": "SEC Form 13F Data Sets",
            "url": DATASET_PAGE,
            "latest_report_quarter": latest_metadata.quarter,
            "quarters_loaded": sorted({quarter for snapshots in snapshots_by_cik.values() for quarter, _ in snapshots}, reverse=True),
            "disclaimer": "SEC bulk data is as filed and is not a substitute for reviewing the original filing.",
        },
        "policy_version": policy["policy_version"],
        "qualification_policy": {
            "hard_gates": policy["hard_gates"],
            "score_weights": policy["score_weights"],
        },
        "target_approved_count": policy["target_approved_count"],
        "approved_count": len(approved_rows_out),
        "candidate_count": len(candidate_rows),
        "approved_needing_review_count": len(rejected_approved),
        "screened_manager_count": len(snapshots_by_cik),
        "screened_out_count": max(0, len(rows) - len(output_rows)),
        "rules": {
            "approval": "Joe must explicitly approve every new addition.",
            "continuity": "Existing CIK map entries remain approved but failed gates are disclosed.",
            "score_scope": "13F portfolio structure only; no performance or drawdown claims.",
        },
        "candidates": output_rows,
    }
    write_json_atomic(output_path, payload)
    return payload


def build_tracked_bootstrap(output_path: Path = OUTPUT_PATH) -> dict[str, Any]:
    """Score only the already tracked CIKs from the committed SEC history.

    This is a labeled fallback for environments where SEC blocks bulk downloads.
    It never emits a new candidate and therefore cannot be mistaken for the full
    universe screen.
    """
    policy = load_json(POLICY_PATH, {})
    raw = load_json(TRACKED_HISTORY_PATH, {})
    cik_rows = load_json(CIK_MAP_PATH, [])
    approved = {
        clean_cik(row.get("cik", "")): row
        for row in cik_rows
        if row.get("cik") and row.get("active", True)
    }
    decisions_payload = load_json(DECISIONS_PATH, {"decisions": []})
    decisions = {clean_cik(row.get("cik", "")): row for row in decisions_payload.get("decisions", []) if row.get("cik")}
    snapshots_by_cik: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for investor in raw.get("investors", []):
        cik = clean_cik(investor.get("cik", ""))
        if cik not in approved and cik not in decisions:
            continue
        for filing in investor.get("filings", []):
            quarter = filing.get("quarter")
            if not quarter:
                continue
            holdings: dict[str, float] = defaultdict(float)
            for holding in filing.get("holdings", []):
                cusip = str(holding.get("cusip") or "").upper().replace(" ", "")
                if cusip:
                    holdings[cusip] += float(holding.get("market_value") or 0)
            snapshots_by_cik[cik].append(
                (
                    quarter,
                    {
                        "name": investor.get("name") or investor.get("fund") or cik,
                        "holdings": dict(holdings),
                        "positions": len(holdings),
                        "total_value_usd": sum(holdings.values()),
                        "long_only_value_ratio": None,
                    },
                )
            )
    rows = [
        score_manager(cik, snapshots, policy, approved, decisions)
        for cik, snapshots in snapshots_by_cik.items()
        if snapshots
    ]
    rows.sort(key=lambda row: (-row["score"], row["name"]))
    quarters = sorted({quarter for snapshots in snapshots_by_cik.values() for quarter, _ in snapshots}, reverse=True)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "name": "Committed SEC EDGAR history for already tracked filers",
            "url": "data/sec-13f-filings.json",
            "latest_report_quarter": quarters[0] if quarters else None,
            "quarters_loaded": quarters,
            "scope": "tracked_only",
            "disclaimer": "This bootstrap does not represent the full SEC filer universe and nominates no new candidates. Market values use the canonical U.S.-dollar unit stored in the tracked filing history.",
        },
        "policy_version": policy["policy_version"],
        "qualification_policy": {
            "hard_gates": policy["hard_gates"],
            "score_weights": policy["score_weights"],
        },
        "target_approved_count": policy["target_approved_count"],
        "approved_count": sum(1 for row in rows if row["status"] == "approved"),
        "candidate_count": 0,
        "approved_needing_review_count": sum(1 for row in rows if row["status"] == "approved" and not row["meets_quantitative_screen"]),
        "screened_manager_count": len(rows),
        "screened_out_count": 0,
        "rules": {
            "approval": "Joe must explicitly approve every new addition.",
            "continuity": "Existing active CIK map entries remain approved but failed gates are disclosed.",
            "score_scope": "Tracked 13F portfolio structure only; no performance or drawdown claims.",
            "bootstrap_limit": "No manager outside the existing tracked list was evaluated.",
        },
        "candidates": rows,
    }
    write_json_atomic(output_path, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quarters", type=int, default=8, help="Number of latest SEC bulk data sets to load")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--input", type=Path, action="append", help="Use local ZIPs in newest-to-oldest order")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--minimum-candidates", type=int, default=0, help="Fail without publishing if fewer candidates pass")
    parser.add_argument("--tracked-bootstrap", action="store_true", help="Score only committed tracked-filer history")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.tracked_bootstrap:
        payload = build_tracked_bootstrap(args.output)
        print(
            f"Tracked bootstrap: {payload['approved_count']} approved, "
            f"0 new candidates, latest {payload['source']['latest_report_quarter']}"
        )
        return 0
    if args.input:
        paths = args.input
    else:
        urls = discover_dataset_urls()[: args.quarters]
        paths = [download_dataset(url, args.cache_dir) for url in urls]
    temporary_output = args.output.with_suffix(args.output.suffix + ".candidate")
    payload = build_universe(paths[: args.quarters], temporary_output)
    print(
        f"Investor universe: {payload['approved_count']} approved, "
        f"{payload['candidate_count']} candidates, "
        f"latest {payload['source']['latest_report_quarter']}"
    )
    if payload["candidate_count"] < args.minimum_candidates:
        temporary_output.unlink(missing_ok=True)
        print(
            f"Refusing to publish: only {payload['candidate_count']} candidates passed; "
            f"minimum is {args.minimum_candidates}",
            file=sys.stderr,
        )
        return 3
    temporary_output.replace(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
