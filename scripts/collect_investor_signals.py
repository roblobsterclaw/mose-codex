#!/usr/bin/env python3
"""Collect source-backed signals for Joe's approved super investors.

Structured SEC filings are collected directly. First-party RSS/Atom sources can
be added to investor-sources.json. This collector never guesses a ticker or an
investment direction; unresolved fields stay null/neutral for human review.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
CIK_MAP_PATH = ROOT / "reference-data" / "cik-map.json"
UNIVERSE_PATH = ROOT / "reference-data" / "investor-universe.json"
SOURCES_PATH = ROOT / "reference-data" / "investor-sources.json"
CUSIP_MAP_PATH = ROOT / "reference-data" / "cusip-map.json"
FEED_PATH = ROOT / "signals" / "feed-latest.json"
STATUS_PATH = ROOT / "signals" / "monitoring-status.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
SEC_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"


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


def request_bytes(url: str, accept: str = "application/json,text/xml,text/html,*/*") -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": sec_user_agent(), "Accept": accept},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def request_json(url: str) -> dict[str, Any]:
    return json.loads(request_bytes(url, "application/json").decode("utf-8"))


def clean_cik(value: Any) -> str:
    return str(value or "").strip().lstrip("0") or "0"


def approved_investors() -> list[dict[str, Any]]:
    universe = load_json(UNIVERSE_PATH, {})
    rows = [row for row in universe.get("candidates", []) if row.get("status") == "approved"]
    if rows:
        return rows
    return [row for row in load_json(CIK_MAP_PATH, []) if row.get("active", True)]


def load_cusip_map() -> dict[str, str]:
    payload = load_json(CUSIP_MAP_PATH, {})
    result: dict[str, str] = {}
    for cusip, row in payload.get("map", {}).items():
        ticker = row.get("ticker") if isinstance(row, dict) else row
        if ticker:
            result[str(cusip).upper()] = str(ticker).upper()
    return result


def stable_id(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def archive_urls(cik: str, accession: str, primary_document: str) -> tuple[str, str | None]:
    accession_clean = accession.replace("-", "")
    directory = f"{SEC_ARCHIVE_BASE}/{clean_cik(cik)}/{accession_clean}"
    index_url = f"{directory}/{accession}-index.html"
    document_url = f"{directory}/{primary_document}" if primary_document else None
    return index_url, document_url


def local_text(node: ElementTree.Element, name: str) -> str:
    for child in node.iter():
        if child.tag.split("}")[-1] == name and child.text:
            return child.text.strip()
    return ""


def parse_form4(document: bytes) -> dict[str, Any]:
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError:
        return {}
    ticker = local_text(root, "issuerTradingSymbol").upper() or None
    issuer = local_text(root, "issuerName") or None
    acquired = 0.0
    disposed = 0.0
    transaction_count = 0
    for transaction in root.iter():
        if transaction.tag.split("}")[-1] not in {"nonDerivativeTransaction", "derivativeTransaction"}:
            continue
        shares = 0.0
        code = ""
        for child in transaction.iter():
            local = child.tag.split("}")[-1]
            if local == "transactionShares":
                shares = number_from_nested_value(child)
            elif local == "transactionAcquiredDisposedCode":
                code = local_text(child, "value").upper()
        if shares <= 0 or code not in {"A", "D"}:
            continue
        transaction_count += 1
        if code == "A":
            acquired += shares
        else:
            disposed += shares
    net = acquired - disposed
    direction = "add" if net > 0 else "trim" if net < 0 else "neutral"
    summary = "Filed Form 4."
    if transaction_count:
        action = "net acquisition" if net > 0 else "net disposition" if net < 0 else "offsetting transactions"
        summary = f"Filed Form 4 reporting {action} of {abs(net):,.0f} shares."
    return {
        "ticker": ticker,
        "company": issuer,
        "direction": direction,
        "summary": summary,
        "transaction_count": transaction_count,
        "shares_acquired": acquired,
        "shares_disposed": disposed,
    }


def number_from_nested_value(node: ElementTree.Element) -> float:
    value = local_text(node, "value")
    try:
        return float(value.replace(",", ""))
    except (AttributeError, ValueError):
        return 0.0


def extract_filing_identity(document: bytes, cusip_map: dict[str, str]) -> dict[str, Any]:
    text = document.decode("utf-8", errors="replace")
    unescaped = html.unescape(text)
    ticker_match = re.search(r"<issuerTradingSymbol[^>]*>\s*([^<]+)", unescaped, flags=re.IGNORECASE)
    ticker = ticker_match.group(1).strip().upper() if ticker_match else None
    cusip_match = re.search(r"\bCUSIP(?:\s+(?:NO\.?|NUMBER))?\s*[:#]?\s*([0-9A-Z]{9})\b", unescaped, flags=re.IGNORECASE)
    cusip = cusip_match.group(1).upper() if cusip_match else None
    if not ticker and cusip:
        ticker = cusip_map.get(cusip)
    company_match = re.search(r"<(?:issuerName|nameOfIssuer)[^>]*>\s*([^<]+)", unescaped, flags=re.IGNORECASE)
    company = html.unescape(company_match.group(1).strip()) if company_match else None
    return {"ticker": ticker, "cusip": cusip, "company": company}


def filing_kind(form: str) -> str:
    normalized = form.upper()
    if normalized.startswith("SC 13D"):
        return "13D"
    if normalized.startswith("SC 13G"):
        return "13G"
    if normalized.startswith("4"):
        return "FORM4"
    if normalized.startswith("NPORT"):
        return "NPORT"
    if normalized == "13F-HR/A":
        return "13F_AMENDMENT"
    return "FILING"


def signals_from_submissions(
    investor: dict[str, Any],
    submissions: dict[str, Any],
    forms: set[str],
    cutoff: datetime,
    cusip_map: dict[str, str],
    existing_ids: set[str],
    fetch_documents: bool = True,
) -> tuple[list[dict[str, Any]], list[str]]:
    recent = submissions.get("filings", {}).get("recent", {})
    form_rows = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    documents = recent.get("primaryDocument", [])
    cik = clean_cik(investor.get("cik"))
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, raw_form in enumerate(form_rows):
        form = str(raw_form or "").upper()
        if form not in forms:
            continue
        filing_date = filing_dates[index] if index < len(filing_dates) else ""
        try:
            filed_at = datetime.fromisoformat(filing_date).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if filed_at < cutoff:
            continue
        accession = accessions[index] if index < len(accessions) else ""
        primary_document = documents[index] if index < len(documents) else ""
        item_id = stable_id("sec", cik, accession, form)
        if item_id in existing_ids:
            continue
        index_url, document_url = archive_urls(cik, accession, primary_document)
        identity: dict[str, Any] = {}
        details: dict[str, Any] = {}
        if fetch_documents and document_url:
            try:
                document = request_bytes(document_url)
                if form.startswith("4"):
                    details = parse_form4(document)
                    identity = details
                else:
                    identity = extract_filing_identity(document, cusip_map)
            except (OSError, urllib.error.URLError, ValueError) as exc:
                errors.append(f"{accession}: document unavailable: {exc}")

        direction = details.get("direction") or ("new" if form in {"SC 13D", "SC 13G"} else "neutral")
        summary = details.get("summary") or f"Filed {form}."
        report_date = report_dates[index] if index < len(report_dates) else None
        items.append(
            {
                "id": item_id,
                "ts": filed_at.isoformat(),
                "kind": filing_kind(form),
                "form": form,
                "investor": investor.get("name") or investor.get("fund") or cik,
                "investor_cik": cik,
                "ticker": identity.get("ticker"),
                "cusip": identity.get("cusip"),
                "company": identity.get("company"),
                "direction": direction,
                "confidence": 1.0 if identity.get("ticker") else 0.9,
                "quote": summary,
                "source_url": index_url,
                "source_title": f"SEC {form} filing {accession}",
                "accession": accession,
                "report_date": report_date,
                "source_class": "structured_filing",
                "affects_conviction": True,
                "extracted_by": "deterministic-sec-parser",
            }
        )
    return items, errors


def parse_feed_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def rss_signals(investor: dict[str, Any], source: dict[str, Any], cutoff: datetime) -> list[dict[str, Any]]:
    payload = request_bytes(source["url"], "application/rss+xml,application/atom+xml,text/xml,*/*")
    root = ElementTree.fromstring(payload)
    items: list[dict[str, Any]] = []
    for node in root.iter():
        if node.tag.split("}")[-1] not in {"item", "entry"}:
            continue
        title = local_text(node, "title")
        link = local_text(node, "link")
        if not link:
            for child in node:
                if child.tag.split("}")[-1] == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        published = local_text(node, "pubDate") or local_text(node, "published") or local_text(node, "updated")
        timestamp = parse_feed_date(published)
        if not title or not link or not timestamp or timestamp < cutoff:
            continue
        items.append(
            {
                "id": stable_id("source", source["url"], link),
                "ts": timestamp.isoformat(),
                "kind": source.get("kind") or "NEWS",
                "investor": investor.get("name"),
                "investor_cik": clean_cik(investor.get("cik")),
                "ticker": None,
                "direction": "neutral",
                "confidence": None,
                "quote": None,
                "source_url": link,
                "source_title": title,
                "source_class": "first_party_words" if source.get("first_party", True) else "news",
                "affects_conviction": False,
                "extracted_by": "source-registry-rss",
            }
        )
    return items


def collect(days: int, output_path: Path = FEED_PATH, status_path: Path = STATUS_PATH) -> tuple[dict[str, Any], int]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    investors = approved_investors()
    config = load_json(SOURCES_PATH, {})
    default_sec = config.get("defaults", {}).get("sec_submissions", {})
    forms = {str(form).upper() for form in default_sec.get("forms", [])}
    overrides = config.get("investors", {})
    cusip_map = load_cusip_map()
    existing = load_json(output_path, {"items": []})
    previous_status = load_json(status_path, {})
    existing_items = existing.get("items", [])
    existing_ids = {str(item.get("id")) for item in existing_items if item.get("id")}

    collected: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    sec_success = 0
    word_sources_configured = 0
    word_sources_succeeded = 0
    per_investor: list[dict[str, Any]] = []
    for investor in investors:
        cik = clean_cik(investor.get("cik"))
        override = overrides.get(cik, {})
        investor_errors: list[str] = []
        filing_count = 0
        investor_sec_success = 0
        if default_sec.get("enabled", True) and override.get("sec_enabled", True):
            sec_entities = [{"cik": cik, "name": investor.get("name"), "forms": sorted(forms)}]
            sec_entities.extend(override.get("sec_entities", []))
            seen_entities: set[str] = set()
            for entity in sec_entities:
                if not entity.get("enabled", True):
                    continue
                entity_cik = clean_cik(entity.get("cik"))
                if entity_cik in seen_entities:
                    continue
                seen_entities.add(entity_cik)
                entity_forms = {str(form).upper() for form in entity.get("forms", forms)}
                try:
                    submissions = request_json(SEC_SUBMISSIONS_URL.format(cik10=entity_cik.zfill(10)))
                    signal_investor = {**investor, "cik": entity_cik}
                    signals, filing_errors = signals_from_submissions(
                        signal_investor,
                        submissions,
                        entity_forms,
                        cutoff,
                        cusip_map,
                        existing_ids,
                    )
                    collected.extend(signals)
                    filing_count += len(signals)
                    investor_errors.extend(filing_errors)
                    investor_sec_success += 1
                except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
                    investor_errors.append(f"SEC CIK {entity_cik} unavailable: {exc}")
            if investor_sec_success:
                sec_success += 1

        for source in override.get("sources", []):
            if not source.get("enabled", True) or source.get("type") not in {"rss", "atom"}:
                continue
            word_sources_configured += 1
            try:
                source_items = rss_signals(investor, source, cutoff)
                collected.extend(item for item in source_items if item["id"] not in existing_ids)
                word_sources_succeeded += 1
            except (OSError, urllib.error.URLError, ElementTree.ParseError, KeyError) as exc:
                investor_errors.append(f"{source.get('url', 'source')}: {exc}")

        for message in investor_errors:
            errors.append({"cik": cik, "investor": str(investor.get("name") or cik), "error": message})
        per_investor.append(
            {
                "cik": cik,
                "investor": investor.get("name") or cik,
                "sec_ok": investor_sec_success > 0,
                "configured_sec_entities": 1 + len(override.get("sec_entities", [])),
                "new_filings": filing_count,
                "configured_word_sources": len(override.get("sources", [])),
            }
        )

    status = {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "approved_investors": len(investors),
        "sec_investors_succeeded": sec_success,
        "sec_investors_failed": max(0, len(investors) - sec_success),
        "word_sources_configured": word_sources_configured,
        "word_sources_succeeded": word_sources_succeeded,
        "new_items": len(collected),
        "errors": errors,
        "investors": per_investor,
        "accuracy_note": "Missing ticker or direction fields were left unresolved; no value was inferred from headlines.",
    }
    if investors and sec_success == 0:
        comparable_status = {key: value for key, value in status.items() if key != "generated_at"}
        comparable_previous = {key: value for key, value in previous_status.items() if key != "generated_at"}
        if comparable_status != comparable_previous:
            write_json_atomic(status_path, status)
        return existing, 2
    write_json_atomic(status_path, status)

    merged = {str(item.get("id")): item for item in existing_items if item.get("id")}
    for item in collected:
        merged[item["id"]] = item
    items = sorted(merged.values(), key=lambda item: str(item.get("ts") or ""), reverse=True)
    feed = {
        "schema_version": 2,
        "generated_at": now.isoformat() if collected or not existing.get("generated_at") else existing.get("generated_at"),
        "source": "Approved-investor SEC filings and verified source registry",
        "rules": {
            "filings_affect_conviction": True,
            "words_affect_conviction": False,
            "unresolved_values": "left null rather than inferred",
        },
        "items": items,
    }
    write_json_atomic(output_path, feed)
    return feed, 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--output", type=Path, default=FEED_PATH)
    parser.add_argument("--status", type=Path, default=STATUS_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    feed, result = collect(args.days, args.output, args.status)
    if result:
        print("Investor monitoring failed for every approved SEC CIK; existing feed preserved", file=sys.stderr)
        return result
    print(f"Investor feed contains {len(feed.get('items', []))} sourced items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
