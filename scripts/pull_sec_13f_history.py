#!/usr/bin/env python3
"""Pull tracked investors' 13F history directly from SEC EDGAR.

This writes a quarter-preserving raw-ish history file that the dashboard export
can turn into Q/Q new/add/trim/exit comparisons.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
CIK_MAP_PATH = ROOT / "reference-data" / "cik-map.json"
TICKER_MAP_PATH = ROOT / "reference-data" / "ticker-map.json"
HOLDINGS_PATH = ROOT / "holdings-latest.json"
OUTPUT_PATH = ROOT / "data" / "sec-13f-filings.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
SEC_FULL_INDEX_URL = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx"
USER_AGENT = "MOSE Dashboard joe@example.com"


@dataclass(frozen=True)
class InvestorConfig:
    name: str
    fund: str
    tier: int
    cik: str
    source_type: str = "13F"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    tmp.replace(path)


def request_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def request_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml,text/plain,*/*"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", errors="replace")


def load_cik_map() -> list[InvestorConfig]:
    configs = []
    for item in load_json(CIK_MAP_PATH, []):
        if item.get("active", True) is False:
            continue
        cik = str(item.get("cik") or "").strip().lstrip("0")
        if not cik:
            continue
        configs.append(
            InvestorConfig(
                name=str(item.get("name") or item.get("fund") or cik),
                fund=str(item.get("fund") or item.get("name") or ""),
                tier=int(item.get("tier") or 1),
                cik=cik,
                source_type=str(item.get("source_type") or "13F"),
            )
        )
    return configs


def load_ticker_map() -> dict[str, str]:
    raw = load_json(TICKER_MAP_PATH, {})
    ticker_map = {str(k).upper().strip(): str(v).upper().strip() for k, v in raw.items() if v}
    for holding in (load_json(HOLDINGS_PATH, {}).get("holdings") or []):
        company = str(holding.get("company") or "").upper().strip()
        ticker = str(holding.get("ticker") or "").upper().strip()
        if company and ticker:
            ticker_map.setdefault(company, ticker)
    return ticker_map


def quarter_for_date(date_text: str | None) -> str | None:
    if not date_text or len(date_text) < 7:
        return None
    try:
        year = int(date_text[:4])
        month = int(date_text[5:7])
    except ValueError:
        return None
    quarter = ((month - 1) // 3) + 1
    return f"{year}-Q{quarter}"


def filing_index_url(cik: str, accession: str) -> str:
    accession_clean = accession.replace("-", "")
    return f"{SEC_ARCHIVES_URL}/{cik}/{accession_clean}/index.json"


def filing_txt_url(file_name: str) -> str:
    return f"https://www.sec.gov/Archives/{file_name}"


def accession_from_file_name(file_name: str) -> str:
    return Path(file_name).name.replace(".txt", "")


def find_information_table_url(cik: str, accession: str) -> str | None:
    index = request_json(filing_index_url(cik, accession))
    items = index.get("directory", {}).get("item", [])
    accession_clean = accession.replace("-", "")
    candidates = []
    for item in items:
        name = str(item.get("name") or "")
        lower = name.lower()
        if not lower.endswith(".xml"):
            continue
        score = 0
        if "infotable" in lower:
            score += 5
        if "form13f" in lower:
            score += 4
        if "primary_doc" in lower:
            score -= 3
        candidates.append((score, name))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return f"{SEC_ARCHIVES_URL}/{cik}/{accession_clean}/{candidates[0][1]}"


def extract_period_from_submission(submission_text: str) -> str | None:
    match = re.search(r"CONFORMED PERIOD OF REPORT:\s*(\d{8})", submission_text)
    if match:
        raw = match.group(1)
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    match = re.search(r"<(?:reportCalendarOrQuarter|periodOfReport)>([^<]+)</", submission_text)
    if match:
        value = match.group(1).strip()
        if re.match(r"\d{2}-\d{2}-\d{4}", value):
            month, day, year = value.split("-")
            return f"{year}-{month}-{day}"
        return value
    return None


def extract_information_table_xml(submission_text: str) -> str | None:
    documents = re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", submission_text, flags=re.DOTALL | re.IGNORECASE)
    candidates = []
    for doc in documents:
        type_match = re.search(r"<TYPE>\s*([^\n\r<]+)", doc, flags=re.IGNORECASE)
        doc_type = type_match.group(1).strip().upper() if type_match else ""
        xml_blocks = re.findall(r"<XML>\s*(.*?)\s*</XML>", doc, flags=re.DOTALL | re.IGNORECASE)
        for xml in xml_blocks:
            if "infotable" in xml.lower():
                score = 10 if "INFORMATION TABLE" in doc_type else 1
                candidates.append((score, xml.strip()))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def index_calendar_quarters(count: int) -> list[tuple[int, int]]:
    now = datetime.now(timezone.utc)
    year = now.year
    quarter = ((now.month - 1) // 3) + 1
    result = []
    while len(result) < count:
        result.append((year, quarter))
        quarter -= 1
        if quarter == 0:
            quarter = 4
            year -= 1
    return result


def download_full_index(year: int, quarter: int) -> str:
    return request_text(SEC_FULL_INDEX_URL.format(year=year, quarter=quarter))


def parse_full_index(text: str, tracked_ciks: set[str]) -> list[dict[str, Any]]:
    rows = []
    for line in text.splitlines():
        if not line.startswith(("13F-HR", "13F-HR/A")):
            continue
        match = re.match(r"^(13F-HR(?:/A)?)\s+(.+?)\s+(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(edgar/data/.+?\.txt)\s*$", line)
        if not match:
            continue
        form, company, cik, filing_date, file_name = match.groups()
        cik_clean = cik.lstrip("0")
        if cik_clean not in tracked_ciks:
            continue
        rows.append(
            {
                "form": form,
                "company": company.strip(),
                "cik": cik_clean,
                "filing_date": filing_date,
                "file_name": file_name,
                "accession": accession_from_file_name(file_name),
            }
        )
    return rows


def text_of(node: ElementTree.Element, local_name: str) -> str:
    for child in node.iter():
        if child.tag.split("}")[-1] == local_name and child.text:
            return child.text.strip()
    return ""


def parse_information_table(xml_text: str, ticker_map: dict[str, str]) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    holdings = []
    for info in root.iter():
        if info.tag.split("}")[-1] != "infoTable":
            continue
        issuer = text_of(info, "nameOfIssuer")
        cusip = text_of(info, "cusip").upper()
        ticker = ticker_map.get(cusip) or ticker_map.get(issuer.upper())
        value_thousands = float(text_of(info, "value") or 0)
        shares = float(text_of(info, "sshPrnamt") or 0)
        put_call = text_of(info, "putCall")
        if put_call:
            continue
        holdings.append(
            {
                "ticker": ticker,
                "identifier": ticker or f"CUSIP:{cusip}",
                "cusip": cusip,
                "company": issuer,
                "market_value": value_thousands * 1000,
                "shares": shares,
            }
        )
    total_value = sum(h["market_value"] for h in holdings)
    holdings.sort(key=lambda h: h["market_value"], reverse=True)
    for rank, holding in enumerate(holdings, start=1):
        holding["rank"] = rank
        holding["pct_portfolio"] = round((holding["market_value"] / total_value * 100), 4) if total_value else 0
    return holdings


def recent_filings_from_submissions(config: InvestorConfig, quarters: int, ticker_map: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    submissions = request_json(SEC_SUBMISSIONS_URL.format(cik10=config.cik.zfill(10)))
    recent = submissions.get("filings", {}).get("recent", {})
    rows = []
    errors = []
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])

    by_quarter: dict[str, dict[str, Any]] = {}
    for idx, form in enumerate(forms):
        if form not in {"13F-HR", "13F-HR/A"}:
            continue
        report_date = report_dates[idx] if idx < len(report_dates) else None
        quarter = quarter_for_date(report_date)
        if not quarter:
            continue
        row = {
            "form": form,
            "accession": accessions[idx],
            "filing_date": filing_dates[idx] if idx < len(filing_dates) else None,
            "period_end": report_date,
            "quarter": quarter,
            "primary_document": primary_docs[idx] if idx < len(primary_docs) else None,
        }
        existing = by_quarter.get(quarter)
        if not existing or (row.get("filing_date") or "") > (existing.get("filing_date") or ""):
            by_quarter[quarter] = row

    selected = sorted(by_quarter.values(), key=lambda r: r["quarter"], reverse=True)[:quarters]
    for filing in selected:
        try:
            table_url = find_information_table_url(config.cik, filing["accession"])
            if not table_url:
                raise RuntimeError("information table XML not found")
            filing["information_table_url"] = table_url
            filing["holdings"] = parse_information_table(request_text(table_url), ticker_map)
            filing["total_value"] = sum(h["market_value"] for h in filing["holdings"])
            filing["num_holdings"] = len(filing["holdings"])
            time.sleep(0.15)
        except (RuntimeError, urllib.error.URLError, ElementTree.ParseError, ValueError) as exc:
            filing["holdings"] = []
            filing["error"] = str(exc)
            errors.append(f"{filing['quarter']}: {exc}")
    return selected, errors


def enrich_full_index_filing(filing: dict[str, Any], ticker_map: dict[str, str]) -> dict[str, Any]:
    submission_text = request_text(filing_txt_url(filing["file_name"]))
    period_end = extract_period_from_submission(submission_text)
    quarter = quarter_for_date(period_end)
    table_xml = extract_information_table_xml(submission_text)
    if not table_xml:
        raise RuntimeError("information table XML not found in submission text")
    holdings = parse_information_table(table_xml, ticker_map)
    filing = {**filing}
    filing["period_end"] = period_end
    filing["quarter"] = quarter
    filing["submission_url"] = filing_txt_url(filing["file_name"])
    filing["holdings"] = holdings
    filing["total_value"] = sum(h["market_value"] for h in holdings)
    filing["num_holdings"] = len(holdings)
    return filing


def build_filings_from_full_indexes(configs: list[InvestorConfig], quarters: int, ticker_map: dict[str, str]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    tracked_ciks = {config.cik for config in configs}
    rows = []
    errors: dict[str, list[str]] = defaultdict(list)
    for year, quarter in index_calendar_quarters(quarters + 3):
        try:
            print(f"Reading SEC full index {year} QTR{quarter}")
            rows.extend(parse_full_index(download_full_index(year, quarter), tracked_ciks))
            time.sleep(0.15)
        except (urllib.error.URLError, RuntimeError) as exc:
            errors["index"].append(f"{year} QTR{quarter}: {exc}")

    by_cik: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in sorted(rows, key=lambda item: item["filing_date"], reverse=True):
        cik = row["cik"]
        try:
            enriched = enrich_full_index_filing(row, ticker_map)
            q = enriched.get("quarter")
            if not q:
                raise RuntimeError("could not determine report quarter")
            existing = by_cik[cik].get(q)
            if not existing or enriched["filing_date"] > existing["filing_date"]:
                by_cik[cik][q] = enriched
            time.sleep(0.15)
        except (urllib.error.URLError, RuntimeError, ElementTree.ParseError, ValueError) as exc:
            errors[cik].append(f"{row.get('accession')}: {exc}")

    return {
        cik: sorted(filings.values(), key=lambda item: item["quarter"], reverse=True)[:quarters]
        for cik, filings in by_cik.items()
    }, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull SEC EDGAR 13F history for MOSE tracked investors.")
    parser.add_argument("--quarters", type=int, default=8)
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    parser.add_argument("--max-investors", type=int, default=0)
    args = parser.parse_args()

    configs = [c for c in load_cik_map() if c.source_type.upper() == "13F"]
    if args.max_investors:
        configs = configs[: args.max_investors]
    ticker_map = load_ticker_map()
    output_path = Path(args.output)

    filings_by_cik, full_index_errors = build_filings_from_full_indexes(configs, args.quarters, ticker_map)
    investors = []
    failed = []
    for config in configs:
        try:
            print(f"Pulling SEC 13F history: {config.name} ({config.cik})")
            filings = filings_by_cik.get(config.cik, [])
            errors = full_index_errors.get(config.cik, [])
            if not filings:
                filings, errors = recent_filings_from_submissions(config, args.quarters, ticker_map)
            good_filings = [f for f in filings if f.get("holdings")]
            if not good_filings:
                raise RuntimeError("; ".join(errors) or "no filings with holdings parsed")
            investors.append(
                {
                    "name": config.name,
                    "fund": config.fund,
                    "tier": config.tier,
                    "cik": config.cik,
                    "source_type": config.source_type,
                    "filings": good_filings,
                    "filing_errors": errors,
                }
            )
        except (RuntimeError, urllib.error.URLError, KeyError, ValueError) as exc:
            failed.append({"name": config.name, "cik": config.cik, "error": str(exc)})
        time.sleep(0.25)

    if not investors:
        raise SystemExit("No SEC 13F filings were pulled; leaving existing output untouched.")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "SEC EDGAR submissions and Archives information tables",
        "quarters_requested": args.quarters,
        "investor_count": len(investors),
        "filings_pulled": sum(len(i["filings"]) for i in investors),
        "failed_investors": failed,
        "investors": investors,
    }
    write_json(output_path, payload)
    print(f"Wrote {output_path} with {payload['investor_count']} investors and {payload['filings_pulled']} filings")
    if failed:
        print(f"Failed investors: {len(failed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
