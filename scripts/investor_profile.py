#!/usr/bin/env python3
"""Shared Joe-style investor profile scoring for every 13F transport."""

from __future__ import annotations

import copy
import math
import statistics
from typing import Any


def clean_cik(value: Any) -> str:
    return str(value or "").strip().lstrip("0") or "0"


def excluded_name(name: str, patterns: list[str]) -> list[str]:
    upper_name = f" {str(name or '').upper()} "
    return [pattern for pattern in patterns if pattern in upper_name]


def closeness(value: float, target: float, log_width: float = 2.0) -> float:
    if value <= 0 or target <= 0:
        return 0.0
    return max(0.0, 1.0 - abs(math.log(value / target)) / log_width)


def cover_pre_score(row: dict[str, Any], profile: dict[str, Any]) -> float:
    baseline = profile["archetype_baseline"]
    gates = profile["discovery_gates"]
    entries = float(row.get("cover_entries") or 0)
    value = float(row.get("total_value_usd") or 0)
    focus = max(
        0.0,
        1.0
        - (entries - gates["minimum_positions"])
        / max(1, gates["maximum_cover_entries"] - gates["minimum_positions"]),
    )
    score = (
        0.50 * closeness(entries, baseline["positions"], 1.8)
        + 0.30 * closeness(value, baseline["total_value_usd"], 3.0)
        + 0.20 * focus
    )
    return round(score * 100, 2)


def discovery_failures(row: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    gates = profile["discovery_gates"]
    failures: list[str] = []
    value = float(row.get("total_value_usd") or 0)
    positions = int(row.get("positions") or 0)
    turnover = row.get("turnover_8q")
    median_hold = float(row.get("median_hold_q") or 0)
    top10 = float(row.get("top10_weight") or 0)
    history = int(row.get("history_quarters") or 0)
    long_ratio = row.get("long_only_value_ratio")
    fund_ratio = row.get("fund_value_ratio")
    if value < gates["minimum_total_value_usd"] or value > gates["maximum_total_value_usd"]:
        failures.append("reported value outside Joe profile")
    if positions < gates["minimum_positions"] or positions > gates["maximum_positions"]:
        failures.append("position count outside Joe profile")
    if history < gates["minimum_history_quarters"]:
        failures.append("fewer than six usable quarters")
    if turnover is None or float(turnover) > gates["maximum_average_turnover"]:
        failures.append("turnover above adventurous-value limit")
    if median_hold < gates["minimum_median_hold_quarters"]:
        failures.append("median holding age below four quarters")
    if top10 < gates["minimum_top10_weight"]:
        failures.append("reported book is not concentrated enough")
    if long_ratio is None or float(long_ratio) < gates["minimum_long_only_value_ratio"]:
        failures.append("long book is not representative enough")
    if fund_ratio is None or float(fund_ratio) > gates["maximum_fund_value_ratio"]:
        failures.append("fund or passive exposure is too large")
    return failures


def profile_fit(row: dict[str, Any], profile: dict[str, Any]) -> tuple[float, dict[str, float], str]:
    baseline = profile["archetype_baseline"]
    weights = profile["profile_score_weights"]
    top10 = float(row.get("top10_weight") or 0)
    median_hold = float(row.get("median_hold_q") or 0)
    turnover = float(row.get("turnover_8q") if row.get("turnover_8q") is not None else 1.0)
    positions = float(row.get("positions") or 0)
    value = float(row.get("total_value_usd") or 0)
    fund_ratio = float(row.get("fund_value_ratio") or 0)

    concentration = max(0.0, min(1.0, (top10 - 0.35) / 0.65))
    patience = max(0.0, min(1.0, (median_hold - 2) / 6))
    disciplined_turnover = max(0.0, min(1.0, (0.50 - turnover) / 0.45))
    similarities = [
        closeness(positions, baseline["positions"], 2.0),
        closeness(value, baseline["total_value_usd"], 3.0),
        max(0.0, 1.0 - abs(top10 - baseline["top10_weight"]) / 0.65),
        max(0.0, 1.0 - abs(turnover - baseline["average_turnover"]) / 0.45),
        max(0.0, 1.0 - abs(median_hold - baseline["median_hold_quarters"]) / 8.0),
    ]
    roster_similarity = statistics.mean(similarities)
    position_cloneability = 1.0 if positions <= 15 else 0.85 if positions <= 30 else 0.65 if positions <= 50 else 0.0
    cloneability = position_cloneability * max(0.0, 1.0 - fund_ratio)
    components = {
        "concentration": concentration * weights["concentration"],
        "patience": patience * weights["patience"],
        "disciplined_turnover": disciplined_turnover * weights["disciplined_turnover"],
        "current_roster_similarity": roster_similarity * weights["current_roster_similarity"],
        "cloneability": cloneability * weights["cloneability"],
    }
    score = round(sum(components.values()), 1)

    core = profile["core_patient_value"]
    adventurous = profile["adventurous_value"]
    if (
        turnover <= core["maximum_average_turnover"]
        and median_hold >= core["minimum_median_hold_quarters"]
        and top10 >= core["minimum_top10_weight"]
    ):
        lane = "core_patient_value"
    elif (
        turnover <= adventurous["maximum_average_turnover"]
        and median_hold >= adventurous["minimum_median_hold_quarters"]
        and top10 >= adventurous["minimum_top10_weight"]
    ):
        lane = "adventurous_value"
    else:
        lane = "outside_profile"
    return score, {key: round(value, 1) for key, value in components.items()}, lane


def derive_archetype_baseline(
    profile: dict[str, Any],
    approved_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    derived = copy.deepcopy(profile)
    archetype_ciks = {clean_cik(cik) for cik in profile.get("archetype_ciks", [])}
    archetypes = [
        row
        for row in approved_rows
        if clean_cik(row.get("cik")) in archetype_ciks
        and row.get("positions") is not None
        and row.get("total_value_usd") is not None
        and row.get("top10_weight") is not None
        and row.get("turnover_8q") is not None
        and row.get("median_hold_q") is not None
    ]
    if len(archetypes) < 3:
        derived["archetype_baseline_source"] = "policy_fallback"
        derived["archetype_manager_count"] = len(archetypes)
        return derived

    derived["archetype_baseline"] = {
        "positions": round(statistics.median(float(row["positions"]) for row in archetypes)),
        "total_value_usd": round(statistics.median(float(row["total_value_usd"]) for row in archetypes)),
        "top10_weight": round(statistics.median(float(row["top10_weight"]) for row in archetypes), 4),
        "average_turnover": round(statistics.median(float(row["turnover_8q"]) for row in archetypes), 4),
        "median_hold_quarters": round(statistics.median(float(row["median_hold_q"]) for row in archetypes), 1),
    }
    derived["archetype_baseline_source"] = "current_approved_history"
    derived["archetype_manager_count"] = len(archetypes)
    return derived
