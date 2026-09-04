#!/usr/bin/env python3
"""Upsert the independent Codex investor universe and feed into Supabase."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = ROOT / "reference-data" / "investor-universe.json"
DECISIONS_PATH = ROOT / "reference-data" / "investor-decisions.json"
SOURCES_PATH = ROOT / "reference-data" / "investor-sources.json"
FEED_PATH = ROOT / "signals" / "feed-latest.json"
WORKSPACE_KEY = "mose-codex"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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
            query = urllib.parse.urlencode({"on_conflict": conflict})
            request = urllib.request.Request(
                f"{self.base}/{table}?{query}",
                data=json.dumps(batch).encode("utf-8"),
                headers=self.headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=90):
                    written += len(batch)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Supabase upsert failed for {table}: HTTP {exc.code}: {body}") from exc
        return written


def candidate_rows() -> list[dict[str, Any]]:
    universe = load_json(UNIVERSE_PATH, {})
    generated_at = universe.get("generated_at")
    source_quarter = universe.get("source", {}).get("latest_report_quarter")
    rows = []
    for item in universe.get("candidates", []):
        rows.append(
            {
                "workspace_key": WORKSPACE_KEY,
                "source_quarter": source_quarter or item.get("latest_quarter") or "unknown",
                "cik": str(item.get("cik") or ""),
                "manager_name": item.get("name") or str(item.get("cik") or "unknown"),
                "fund_name": item.get("fund"),
                "status": item.get("status") or "candidate",
                "score": item.get("score") or 0,
                "candidate_rank": item.get("candidate_rank"),
                "positions": item.get("positions"),
                "total_value_usd": item.get("total_value_usd"),
                "top10_weight": item.get("top10_weight"),
                "turnover_8q": item.get("turnover_8q"),
                "median_hold_q": item.get("median_hold_q"),
                "history_quarters": item.get("history_quarters"),
                "long_only_value_ratio": item.get("long_only_value_ratio"),
                "meets_quantitative_screen": bool(item.get("meets_quantitative_screen")),
                "screen_failures": item.get("screen_failures") or [],
                "score_components": item.get("score_components") or {},
                "source_payload": item,
                "generated_at": generated_at,
            }
        )
        for entity in overrides.get(cik, {}).get("sec_entities", []):
            entity_cik = str(entity.get("cik") or "").lstrip("0")
            if not entity_cik or entity_cik == cik:
                continue
            entity_url = f"https://data.sec.gov/submissions/CIK{entity_cik.zfill(10)}.json"
            rows.append(
                {
                    "workspace_key": WORKSPACE_KEY,
                    "source_key": f"sec-submissions:{cik}:{entity_cik}",
                    "cik": cik,
                    "investor_name": name,
                    "source_type": "sec_submissions_related_entity",
                    "source_url": entity_url,
                    "source_kind": "FILING",
                    "first_party": True,
                    "enabled": entity.get("enabled", True),
                    "verified_at": entity.get("verified_at"),
                    "source_payload": entity,
                }
            )
    return rows


def decision_rows() -> list[dict[str, Any]]:
    payload = load_json(DECISIONS_PATH, {"decisions": []})
    return [
        {
            "workspace_key": WORKSPACE_KEY,
            "cik": str(item.get("cik") or ""),
            "decision": item.get("decision"),
            "reason": item.get("reason"),
            "decided_at": item.get("decided_at"),
            "decided_by": item.get("decided_by") or "Joe Lynch",
            "source_payload": item,
        }
        for item in payload.get("decisions", [])
        if item.get("cik") and item.get("decision") in {"approve", "reject"} and item.get("decided_at") and item.get("reason")
    ]


def source_rows() -> list[dict[str, Any]]:
    sources = load_json(SOURCES_PATH, {})
    universe = load_json(UNIVERSE_PATH, {})
    approved = [row for row in universe.get("candidates", []) if row.get("status") == "approved"]
    overrides = sources.get("investors", {})
    rows: list[dict[str, Any]] = []
    for investor in approved:
        cik = str(investor.get("cik") or "").lstrip("0")
        name = investor.get("name") or cik
        sec_url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
        rows.append(
            {
                "workspace_key": WORKSPACE_KEY,
                "source_key": f"sec-submissions:{cik}",
                "cik": cik,
                "investor_name": name,
                "source_type": "sec_submissions",
                "source_url": sec_url,
                "source_kind": "FILING",
                "first_party": True,
                "enabled": overrides.get(cik, {}).get("sec_enabled", True),
                "verified_at": universe.get("generated_at"),
                "source_payload": sources.get("defaults", {}).get("sec_submissions", {}),
            }
        )
        for source in overrides.get(cik, {}).get("sources", []):
            url = source.get("url")
            if not url:
                continue
            rows.append(
                {
                    "workspace_key": WORKSPACE_KEY,
                    "source_key": f"source:{cik}:{source.get('id') or hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}",
                    "cik": cik,
                    "investor_name": name,
                    "source_type": source.get("type") or "rss",
                    "source_url": url,
                    "source_kind": source.get("kind") or "NEWS",
                    "first_party": source.get("first_party", True),
                    "enabled": source.get("enabled", True),
                    "verified_at": source.get("verified_at"),
                    "source_payload": source,
                }
            )
    return rows


def signal_rows() -> list[dict[str, Any]]:
    feed = load_json(FEED_PATH, {"items": []})
    return [
        {
            "workspace_key": WORKSPACE_KEY,
            "signal_id": item["id"],
            "observed_at": item.get("ts"),
            "kind": item.get("kind") or "NEWS",
            "form": item.get("form"),
            "investor_name": item.get("investor"),
            "investor_cik": item.get("investor_cik"),
            "ticker": item.get("ticker"),
            "cusip": item.get("cusip"),
            "company": item.get("company"),
            "direction": item.get("direction") or "neutral",
            "confidence": item.get("confidence"),
            "summary": item.get("quote"),
            "source_url": item.get("source_url"),
            "source_title": item.get("source_title"),
            "source_class": item.get("source_class") or "unknown",
            "affects_conviction": bool(item.get("affects_conviction")),
            "source_payload": item,
        }
        for item in feed.get("items", [])
        if item.get("id") and item.get("ts") and item.get("source_url")
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-only", action="store_true")
    parser.add_argument("--signals-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    client = SupabaseClient(url, key)
    counts: dict[str, int] = {}
    if not args.signals_only:
        counts["candidates"] = client.upsert(
            "mose_codex_investor_candidates",
            candidate_rows(),
            "workspace_key,source_quarter,cik",
        )
        counts["decisions"] = client.upsert(
            "mose_codex_investor_decisions",
            decision_rows(),
            "workspace_key,cik",
        )
        counts["sources"] = client.upsert(
            "mose_codex_investor_sources",
            source_rows(),
            "workspace_key,source_key",
        )
    if not args.universe_only:
        counts["signals"] = client.upsert(
            "mose_codex_investor_signals",
            signal_rows(),
            "workspace_key,signal_id",
        )
    print("Supabase investor intelligence sync: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
