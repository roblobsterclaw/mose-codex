#!/usr/bin/env python3
"""Record Joe's investor decision and safely update the tracked CIK roster."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = ROOT / "reference-data" / "investor-universe.json"
DECISIONS_PATH = ROOT / "reference-data" / "investor-decisions.json"
CIK_MAP_PATH = ROOT / "reference-data" / "cik-map.json"
POLICY_PATH = ROOT / "reference-data" / "investor-qualification-policy.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    temporary.replace(path)


def clean_cik(value: Any) -> str:
    return str(value or "").strip().lstrip("0") or "0"


def apply_decision(cik: str, decision: str, reason: str, tier: int = 2) -> dict[str, Any]:
    universe = load_json(UNIVERSE_PATH, {})
    rows = universe.get("candidates", [])
    candidate = next((row for row in rows if clean_cik(row.get("cik")) == cik), None)
    if not candidate:
        raise RuntimeError(f"CIK {cik} is not in the current investor universe")

    policy = load_json(POLICY_PATH, {})
    cik_rows = load_json(CIK_MAP_PATH, [])
    tracked = next((row for row in cik_rows if clean_cik(row.get("cik")) == cik), None)
    active_count = sum(1 for row in cik_rows if row.get("active", True))
    target = int(policy.get("target_approved_count") or 50)
    if decision == "approve" and not (tracked and tracked.get("active", True)) and active_count >= target:
        raise RuntimeError(f"The approved roster already has {active_count} active investors; target is {target}")

    decided_at = datetime.now(timezone.utc).isoformat()
    decisions = load_json(DECISIONS_PATH, {"schema_version": 1, "decisions": []})
    decisions["updated_at"] = decided_at
    decisions["decisions"] = [
        row for row in decisions.get("decisions", []) if clean_cik(row.get("cik")) != cik
    ]
    decision_row = {
        "cik": cik,
        "name": candidate.get("name"),
        "fund": candidate.get("fund"),
        "decision": decision,
        "reason": reason,
        "decided_at": decided_at,
        "decided_by": "Joe Lynch",
        "score_at_decision": candidate.get("score"),
        "source_quarter": candidate.get("latest_quarter"),
    }
    decisions["decisions"].append(decision_row)
    decisions["decisions"].sort(key=lambda row: (row.get("decision", ""), row.get("name", "")))

    if tracked:
        tracked["active"] = decision == "approve"
        tracked["approval_status"] = "approved" if decision == "approve" else "rejected"
        tracked["decision_reason"] = reason
        tracked["decision_at"] = decided_at
    elif decision == "approve":
        cik_rows.append(
            {
                "name": candidate.get("name") or candidate.get("fund") or cik,
                "fund": candidate.get("fund") or candidate.get("name") or cik,
                "tier": tier,
                "source_type": "13F",
                "cik": cik,
                "active": True,
                "approval_status": "approved",
                "decision_reason": reason,
                "decision_at": decided_at,
            }
        )

    candidate["status"] = "approved" if decision == "approve" else "rejected"
    candidate["approval_basis"] = decision
    candidate["approved_at"] = decided_at if decision == "approve" else None
    candidate["review_note"] = reason
    universe["approved_count"] = sum(1 for row in rows if row.get("status") == "approved")
    universe["candidate_count"] = sum(1 for row in rows if row.get("status") == "candidate")
    universe["last_decision_at"] = decided_at

    write_json_atomic(DECISIONS_PATH, decisions)
    write_json_atomic(CIK_MAP_PATH, cik_rows)
    write_json_atomic(UNIVERSE_PATH, universe)
    return decision_row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decision", choices=("approve", "reject"))
    parser.add_argument("--cik", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--tier", type=int, choices=(1, 2), default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cik = clean_cik(args.cik)
    row = apply_decision(cik, args.decision, args.reason.strip(), args.tier)
    print(f"Recorded {row['decision']} for {row['name']} (CIK {cik})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
