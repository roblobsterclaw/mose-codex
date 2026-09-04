from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_investor_universe import (  # noqa: E402
    build_universe,
    load_json,
    portfolio_turnover,
    scan_archive,
    score_manager,
)
from build_investor_universe_from_api import (  # noqa: E402
    derive_archetype_baseline,
    discovery_failures,
    excluded_name,
    prior_quarter_end,
    profile_fit,
    selected_filing_set,
)
from build_13f_tracker import aggregate_holdings, classify_change  # noqa: E402
from collect_investor_signals import parse_form4, signals_from_submissions  # noqa: E402
from sync_13f_tracker_to_supabase import (  # noqa: E402
    aggregate_filing_holdings,
    clean_ticker,
    merge_security,
)
from sync_investor_intelligence_to_supabase import candidate_rows, source_rows  # noqa: E402
from validate_investor_data import build_audit  # noqa: E402


def tsv_bytes(fieldnames: list[str], rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def make_bulk_zip(
    path: Path,
    period_end: str,
    managers: list[dict[str, object]],
    amendments: list[dict[str, object]] | None = None,
    filing_date: str = "2026-05-15",
) -> None:
    submission_rows: list[dict[str, object]] = []
    cover_rows: list[dict[str, object]] = []
    info_rows: list[dict[str, object]] = []
    sequence = 1
    for manager in managers:
        cik = str(manager["cik"])
        accession = f"{cik.zfill(10)}-26-{sequence:06d}"
        sequence += 1
        submission_rows.append(
            {
                "ACCESSION_NUMBER": accession,
                "FILING_DATE": filing_date,
                "SUBMISSIONTYPE": "13F-HR",
                "CIK": cik,
                "PERIODOFREPORT": period_end,
            }
        )
        cover_rows.append(
            {
                "ACCESSION_NUMBER": accession,
                "FILINGMANAGER_NAME": manager["name"],
                "ISAMENDMENT": "N",
                "AMENDMENTTYPE": "",
            }
        )
        for index, holding in enumerate(manager["holdings"], start=1):
            cusip, value_reported = holding
            info_rows.append(
                {
                    "ACCESSION_NUMBER": accession,
                    "INFOTABLE_SK": index,
                    "NAMEOFISSUER": f"ISSUER {cusip}",
                    "TITLEOFCLASS": "COM",
                    "CUSIP": cusip,
                    "VALUE": value_reported,
                    "PUTCALL": "",
                }
            )

    for amendment in amendments or []:
        cik = str(amendment["cik"])
        accession = f"{cik.zfill(10)}-26-{sequence:06d}"
        sequence += 1
        submission_rows.append(
            {
                "ACCESSION_NUMBER": accession,
                "FILING_DATE": "2026-05-20",
                "SUBMISSIONTYPE": "13F-HR/A",
                "CIK": cik,
                "PERIODOFREPORT": period_end,
            }
        )
        cover_rows.append(
            {
                "ACCESSION_NUMBER": accession,
                "FILINGMANAGER_NAME": amendment["name"],
                "ISAMENDMENT": "Y",
                "AMENDMENTTYPE": amendment["type"],
            }
        )
        for index, holding in enumerate(amendment["holdings"], start=1):
            cusip, value_reported = holding
            info_rows.append(
                {
                    "ACCESSION_NUMBER": accession,
                    "INFOTABLE_SK": index,
                    "NAMEOFISSUER": f"ISSUER {cusip}",
                    "TITLEOFCLASS": "COM",
                    "CUSIP": cusip,
                    "VALUE": value_reported,
                    "PUTCALL": "",
                }
            )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "SUBMISSION.tsv",
            tsv_bytes(
                ["ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"],
                submission_rows,
            ),
        )
        archive.writestr(
            "COVERPAGE.tsv",
            tsv_bytes(
                ["ACCESSION_NUMBER", "FILINGMANAGER_NAME", "ISAMENDMENT", "AMENDMENTTYPE"],
                cover_rows,
            ),
        )
        archive.writestr(
            "INFOTABLE.tsv",
            tsv_bytes(
                ["ACCESSION_NUMBER", "INFOTABLE_SK", "NAMEOFISSUER", "TITLEOFCLASS", "CUSIP", "VALUE", "PUTCALL"],
                info_rows,
            ),
        )


class UniverseTests(unittest.TestCase):
    def test_api_additive_amendment_keeps_original_filing(self) -> None:
        rows = [
            {
                "submission_type": "13F-HR",
                "filed_as_of_date": "2026-05-10",
                "accession_number": "base",
            },
            {
                "submission_type": "13F-HR/A",
                "amendment_type": "NEW HOLDINGS",
                "filed_as_of_date": "2026-05-20",
                "accession_number": "additive",
            },
        ]
        self.assertEqual(
            [row["accession_number"] for row in selected_filing_set(rows)],
            ["base", "additive"],
        )

    def test_api_restatement_replaces_original_filing(self) -> None:
        rows = [
            {
                "submission_type": "13F-HR",
                "filed_as_of_date": "2026-05-10",
                "accession_number": "base",
            },
            {
                "submission_type": "13F-HR/A",
                "amendment_type": "RESTATEMENT",
                "filed_as_of_date": "2026-05-20",
                "accession_number": "restated",
            },
        ]
        self.assertEqual(
            [row["accession_number"] for row in selected_filing_set(rows)],
            ["restated"],
        )

    def test_adventurous_value_lane_allows_measured_extra_risk(self) -> None:
        policy = load_json(ROOT / "reference-data" / "investor-qualification-policy.json", {})
        row = {
            "positions": 20,
            "total_value_usd": 2_000_000_000,
            "top10_weight": 0.70,
            "turnover_8q": 0.32,
            "median_hold_q": 4,
        }
        score, components, lane = profile_fit(row, policy["joe_style_profile"])
        self.assertEqual(lane, "adventurous_value")
        self.assertGreater(score, 50)
        self.assertEqual(round(sum(components.values()), 1), score)

    def test_previous_quarter_end_uses_calendar_quarter(self) -> None:
        self.assertEqual(prior_quarter_end(date(2026, 9, 4)).isoformat(), "2026-06-30")

    def test_archetype_baseline_is_derived_from_current_approved_history(self) -> None:
        profile = {
            "archetype_ciks": ["1", "2", "3"],
            "archetype_baseline": {"positions": 99},
        }
        rows = [
            {"cik": str(index), "positions": positions, "total_value_usd": value, "top10_weight": top10,
             "turnover_8q": turnover, "median_hold_q": hold}
            for index, positions, value, top10, turnover, hold in [
                (1, 8, 1_000_000_000, 0.80, 0.08, 8),
                (2, 10, 2_000_000_000, 0.90, 0.10, 7),
                (3, 12, 3_000_000_000, 1.00, 0.12, 6),
            ]
        ]
        derived = derive_archetype_baseline(profile, rows)
        self.assertEqual(derived["archetype_baseline_source"], "current_approved_history")
        self.assertEqual(derived["archetype_manager_count"], 3)
        self.assertEqual(derived["archetype_baseline"]["positions"], 10)
        self.assertEqual(derived["archetype_baseline"]["average_turnover"], 0.10)

    def test_fund_allocator_does_not_qualify_as_stock_picker(self) -> None:
        policy = load_json(ROOT / "reference-data" / "investor-qualification-policy.json", {})
        row = {
            "positions": 9,
            "total_value_usd": 3_000_000_000,
            "top10_weight": 1.0,
            "turnover_8q": 0.02,
            "median_hold_q": 8,
            "history_quarters": 8,
            "long_only_value_ratio": 1.0,
            "fund_value_ratio": 0.95,
        }
        failures = discovery_failures(row, policy["joe_style_profile"])
        self.assertIn("fund or passive exposure is too large", failures)

    def test_private_growth_adviser_is_not_nominated_as_value_manager(self) -> None:
        policy = load_json(ROOT / "reference-data" / "investor-qualification-policy.json", {})
        patterns = policy["joe_style_profile"]["excluded_manager_name_patterns"]
        matches = excluded_name("SB INVESTMENT ADVISERS (UK) LTD", patterns)
        self.assertIn(" SB INVESTMENT ADVISERS ", matches)

    def test_weight_turnover_is_zero_for_unchanged_book(self) -> None:
        current = {"111111111": 600, "222222222": 400}
        previous = {"111111111": 300, "222222222": 200}
        self.assertAlmostEqual(portfolio_turnover(current, previous), 0.0)

    def test_additive_amendment_combines_with_original_filing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quarter.zip"
            make_bulk_zip(
                path,
                "2026-03-31",
                [{"cik": "123", "name": "FOCUSED VALUE", "holdings": [("111111111", 600_000_000)]}],
                [{"cik": "123", "name": "FOCUSED VALUE", "type": "ADD NEW HOLDINGS", "holdings": [("222222222", 400_000_000)]}],
            )
            metadata, portfolios = scan_archive(path)
            self.assertEqual(metadata.quarter, "2026-Q1")
            self.assertEqual(portfolios["123"]["positions"], 2)
            self.assertEqual(portfolios["123"]["total_value_usd"], 1_000_000_000)

    def test_pre_2023_bulk_values_are_converted_from_thousands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-quarter.zip"
            make_bulk_zip(
                path,
                "2022-09-30",
                [{"cik": "123", "name": "FOCUSED VALUE", "holdings": [("111111111", 600_000)]}],
                filing_date="2022-11-14",
            )
            _, portfolios = scan_archive(path)
            self.assertEqual(portfolios["123"]["total_value_usd"], 600_000_000)

    def test_eight_quarter_patient_manager_becomes_candidate(self) -> None:
        dates = [
            "2026-03-31",
            "2025-12-31",
            "2025-09-30",
            "2025-06-30",
            "2025-03-31",
            "2024-12-31",
            "2024-09-30",
            "2024-06-30",
        ]
        holdings = [(f"{index:09d}", 100_000_000) for index in range(1, 11)]
        with tempfile.TemporaryDirectory() as directory:
            paths: list[Path] = []
            for index, period in enumerate(dates):
                path = Path(directory) / f"q{index}.zip"
                make_bulk_zip(path, period, [{"cik": "987654", "name": "FOCUSED VALUE PARTNERS", "holdings": holdings}])
                paths.append(path)
            output = Path(directory) / "universe.json"
            payload = build_universe(paths, output)
            row = next(item for item in payload["candidates"] if item["cik"] == "987654")
            self.assertEqual(row["status"], "candidate")
            self.assertTrue(row["meets_quantitative_screen"])
            self.assertEqual(row["median_hold_q"], 8.0)
            self.assertEqual(row["turnover_8q"], 0.0)
            self.assertEqual(row["total_value_usd"], 1_000_000_000)
            self.assertEqual(row["style_lane"], "core_patient_value")
            self.assertTrue(row["filing_urls"][0].startswith("https://www.sec.gov/Archives/edgar/data/"))
            self.assertEqual(json.loads(output.read_text())["source"]["latest_report_quarter"], "2026-Q1")

    def test_name_exclusion_is_disclosed(self) -> None:
        policy = load_json(ROOT / "reference-data" / "investor-qualification-policy.json", {})
        snapshots = []
        for index in range(8):
            snapshots.append(
                (
                    f"202{4 + (index + 2) // 4}-Q{(index % 4) + 1}",
                    {
                        "name": "BANK OF TEST TRUST DEPARTMENT",
                        "holdings": {"111111111": 1_000_000_000},
                        "positions": 1,
                        "total_value_usd": 1_000_000_000,
                        "long_only_value_ratio": 1.0,
                    },
                )
            )
        row = score_manager("333", snapshots, policy, {}, {})
        self.assertEqual(row["status"], "rejected")
        self.assertIn("institutional or non-cloneable manager name pattern", row["screen_failures"])


class SignalTests(unittest.TestCase):
    def test_form4_net_acquisition_is_parsed_without_guessing(self) -> None:
        xml = b"""<ownershipDocument>
          <issuer><issuerName>Example Corp</issuerName><issuerTradingSymbol>EXM</issuerTradingSymbol></issuer>
          <nonDerivativeTable>
            <nonDerivativeTransaction><transactionAmounts><transactionShares><value>100</value></transactionShares>
              <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts></nonDerivativeTransaction>
            <nonDerivativeTransaction><transactionAmounts><transactionShares><value>20</value></transactionShares>
              <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts></nonDerivativeTransaction>
          </nonDerivativeTable>
        </ownershipDocument>"""
        parsed = parse_form4(xml)
        self.assertEqual(parsed["ticker"], "EXM")
        self.assertEqual(parsed["direction"], "add")
        self.assertEqual(parsed["shares_acquired"], 100)
        self.assertEqual(parsed["shares_disposed"], 20)

    def test_derivative_only_form4_stays_neutral(self) -> None:
        xml = b"""<ownershipDocument>
          <issuer><issuerName>Example Corp</issuerName><issuerTradingSymbol>EXM</issuerTradingSymbol></issuer>
          <derivativeTable><derivativeTransaction><transactionAmounts>
            <transactionShares><value>100</value></transactionShares>
            <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
          </transactionAmounts></derivativeTransaction></derivativeTable>
        </ownershipDocument>"""
        parsed = parse_form4(xml)
        self.assertEqual(parsed["direction"], "neutral")
        self.assertEqual(parsed["derivative_transaction_count"], 1)
        self.assertIn("not classified", parsed["summary"])

    def test_13d_without_document_keeps_ticker_unresolved(self) -> None:
        submissions = {
            "filings": {
                "recent": {
                    "form": ["SC 13D"],
                    "accessionNumber": ["0000000123-26-000001"],
                    "filingDate": ["2026-09-03"],
                    "reportDate": ["2026-09-02"],
                    "primaryDocument": ["schedule13d.htm"],
                }
            }
        }
        items, errors = signals_from_submissions(
            {"cik": "123", "name": "Focused Investor"},
            submissions,
            {"SC 13D"},
            datetime(2026, 9, 1, tzinfo=timezone.utc),
            {},
            set(),
            fetch_documents=False,
        )
        self.assertFalse(errors)
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["ticker"])
        self.assertEqual(items[0]["direction"], "new")
        self.assertTrue(items[0]["affects_conviction"])


class SupabaseSyncTests(unittest.TestCase):
    def test_investor_intelligence_exports_use_isolated_workspace(self) -> None:
        candidates = candidate_rows()
        sources = source_rows()
        self.assertGreaterEqual(len(candidates), 29)
        self.assertGreaterEqual(len(sources), 29)
        self.assertTrue(all(row["workspace_key"] == "mose-codex" for row in candidates + sources))
        pending = [row for row in candidates if row["status"] == "candidate"]
        self.assertTrue(pending)
        self.assertTrue(all(row["style_lane"] in {"core_patient_value", "adventurous_value"} for row in pending))
        self.assertTrue(all(row["filing_urls"] for row in pending))

    def test_committed_investor_data_passes_audit(self) -> None:
        audit = build_audit()
        self.assertEqual(audit["status"], "passed", audit["checks"])

    def test_duplicate_cusip_rows_are_aggregated(self) -> None:
        rows = aggregate_filing_holdings(
            {
                "holdings": [
                    {"cusip": "111 111 111", "ticker": None, "shares": 10, "market_value": 1_000_000},
                    {"cusip": "111111111", "ticker": "EXM", "shares": 5, "market_value": 500_000},
                ]
            }
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["shares"], 15)
        self.assertEqual(rows[0]["market_value"], 1_500_000)
        self.assertEqual(rows[0]["ticker"], "EXM")

    def test_resolved_ticker_is_not_replaced_by_unresolved_history(self) -> None:
        securities: dict[str, dict[str, object]] = {}
        merge_security(securities, "111111111", "EXM", "Example Corp", {"source": "new"})
        merge_security(securities, "111111111", "CUSIP:111111111", "Example Corp", {"source": "old"})
        self.assertEqual(securities["111111111"]["ticker"], "EXM")
        self.assertEqual(securities["111111111"]["resolution_status"], "resolved")
        self.assertEqual(clean_ticker("CUSIP:111111111"), None)

    def test_quarters_match_by_cusip_when_only_one_has_a_ticker(self) -> None:
        current = aggregate_holdings(
            [{"cusip": "037833100", "ticker": "AAPL", "shares": 110, "market_value": 22_000}]
        )
        previous = aggregate_holdings(
            [{"cusip": "037833100", "ticker": None, "shares": 100, "market_value": 20_000}]
        )
        self.assertEqual(set(current), set(previous))
        key = next(iter(current))
        self.assertEqual(classify_change(current[key], previous[key]), "add")

    def test_cusip_map_resolves_unmapped_tracker_row(self) -> None:
        rows = aggregate_holdings(
            [{"cusip": "037833100", "ticker": None, "shares": 100, "market_value": 20_000}],
            {"037833100": "AAPL"},
        )
        self.assertEqual(next(iter(rows.values()))["ticker"], "AAPL")


if __name__ == "__main__":
    unittest.main()
