from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
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
from collect_investor_signals import parse_form4, signals_from_submissions  # noqa: E402


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
                "FILING_DATE": "2026-05-15",
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
            cusip, value_thousands = holding
            info_rows.append(
                {
                    "ACCESSION_NUMBER": accession,
                    "INFOTABLE_SK": index,
                    "NAMEOFISSUER": f"ISSUER {cusip}",
                    "TITLEOFCLASS": "COM",
                    "CUSIP": cusip,
                    "VALUE": value_thousands,
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
            cusip, value_thousands = holding
            info_rows.append(
                {
                    "ACCESSION_NUMBER": accession,
                    "INFOTABLE_SK": index,
                    "NAMEOFISSUER": f"ISSUER {cusip}",
                    "TITLEOFCLASS": "COM",
                    "CUSIP": cusip,
                    "VALUE": value_thousands,
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
                [{"cik": "123", "name": "FOCUSED VALUE", "holdings": [("111111111", 600000)]}],
                [{"cik": "123", "name": "FOCUSED VALUE", "type": "ADD NEW HOLDINGS", "holdings": [("222222222", 400000)]}],
            )
            metadata, portfolios = scan_archive(path)
            self.assertEqual(metadata.quarter, "2026-Q1")
            self.assertEqual(portfolios["123"]["positions"], 2)
            self.assertEqual(portfolios["123"]["total_value_usd"], 1_000_000_000)

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
        holdings = [(f"{index:09d}", 100000) for index in range(1, 11)]
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


if __name__ == "__main__":
    unittest.main()
