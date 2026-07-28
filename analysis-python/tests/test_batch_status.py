import json
from pathlib import Path

import pytest

from equity_analysis.provider_validation.batch_status import (
    build_batch_aggregate,
    build_remaining_manifest,
    file_sha256,
    read_combined_report,
)
from equity_analysis.provider_validation.combined_backfill_cli import execute_combined
from equity_analysis.provider_validation.execution_safety import SymbolExecutionJournal


class _NeverCalled:
    def __getattr__(self, name):
        raise AssertionError(f"Network-facing method called during resume: {name}")


class _StoreNeverCalled:
    def persist(self, *_args):
        raise AssertionError("Insufficient terminal result must not be persisted")


def test_v1_1_and_legacy_report_reader_separates_telemetry(tmp_path) -> None:
    modern = tmp_path / "modern.json"
    modern.write_text(
        json.dumps(
            {
                "reportVersion": "formula-ready-combined-backfill-v1.1.0",
                "logicalEndpointEvaluations": {"fundamentals": 1},
                "replayedCompletedEndpoints": {"eod": 1},
                "newPhysicalAttempts": {"fundamentals": 1},
            }
        ),
        encoding="utf-8",
    )
    loaded = read_combined_report(modern, expected_sha256=file_sha256(modern))
    assert loaded["telemetryCompatibility"] == "V1_1_SEPARATED"
    assert loaded["newPhysicalAttempts"] == {"fundamentals": 1}

    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps({"endpointPhysicalAttempts": {"fundamentals": 1}}),
        encoding="utf-8",
    )
    loaded = read_combined_report(legacy)
    assert loaded["logicalEndpointEvaluations"] == {"fundamentals": 1}
    assert loaded["newPhysicalAttempts"] is None
    assert "NOT_VERIFIED_PHYSICAL" in loaded["telemetryCompatibility"]
    with pytest.raises(ValueError, match="SOURCE_REPORT_SHA256_MISMATCH"):
        read_combined_report(legacy, expected_sha256="00")


def test_remaining_manifest_preserves_order_and_builds_239_symbols() -> None:
    root = Path(__file__).resolve().parents[2]
    source = json.loads(
        (root / "docs/generated/formula-ready-243-backfill-manifest-v1.json").read_text(
            encoding="utf-8"
        )
    )
    terminal = {
        symbol: {
            "status": status,
            "sourceRunId": "evidence-run",
            "sourceReportSha256": f"HASH-{symbol}",
        }
        for symbol, status in (
            ("AAPL", "FORMULA_READY"),
            ("CAT", "FORMULA_READY"),
            ("JNJ", "FORMULA_READY"),
            ("ABNB", "SECURITY_INSUFFICIENT_DATA"),
        )
    }
    manifest = build_remaining_manifest(source, terminal)
    flattened = [symbol for item in manifest["slices"] for symbol in item["symbols"]]
    expected = [
        item["symbol"]
        for item in source["records"]
        if item["symbol"] not in terminal
    ]
    assert flattened == expected
    assert len(flattened) == len(set(flattened)) == 239
    assert manifest["sliceCount"] == 12
    assert max(len(item["symbols"]) for item in manifest["slices"]) == 20
    assert all(symbol not in flattened for symbol in terminal)
    assert manifest == build_remaining_manifest(source, terminal)
    assert manifest["selectionApplied"] is False
    assert manifest["replacementApplied"] is False


def test_aggregate_preserves_exact_reasons_and_strict_majority_signal() -> None:
    results = [
        {
            "symbol": symbol,
            "status": "SECURITY_INSUFFICIENT_DATA",
            "reasonCodes": ["INTEREST_EXPENSE_QUARTERS_0_OF_8"],
        }
        for symbol in ("A", "B", "C")
    ] + [{"symbol": "D", "status": "FORMULA_READY"}]
    aggregate = build_batch_aggregate(results)
    assert aggregate["statusCounts"] == {
        "FORMULA_READY": 1,
        "SECURITY_INSUFFICIENT_DATA": 3,
    }
    assert aggregate["reasonCounts"] == {"INTEREST_EXPENSE_QUARTERS_0_OF_8": 3}
    assert aggregate["stopSignal"] == "STOP_FOR_SYSTEMATIC_DATA_GAP"
    assert aggregate["missingValuesCoerced"] is False

    tied = build_batch_aggregate(
        results[:2]
        + [
            {"symbol": "X", "status": "FORMULA_READY"},
            {"symbol": "Y", "status": "FORMULA_READY"},
        ]
    )
    assert tied["stopSignal"] == "CONTINUE"


def test_system_failure_stops_and_duplicate_results_are_rejected() -> None:
    aggregate = build_batch_aggregate(
        [{"symbol": "A", "status": "SYSTEM_EXECUTION_FAIL", "reasonCodes": ["IO_ERROR"]}]
    )
    assert aggregate["stopSignal"] == "STOP_FOR_SYSTEM_EXECUTION_FAILURE"
    with pytest.raises(ValueError, match="DUPLICATE_BATCH_RESULT_SYMBOL"):
        build_batch_aggregate(
            [
                {"symbol": "A", "status": "FORMULA_READY"},
                {"symbol": "A", "status": "FORMULA_READY"},
            ]
        )


def test_resume_skips_completed_insufficient_security_without_requests(tmp_path) -> None:
    journal = SymbolExecutionJournal(tmp_path / "journal", "run")
    result = {
        "symbol": "ABNB",
        "status": "SECURITY_INSUFFICIENT_DATA",
        "reasonCodes": ["INTEREST_EXPENSE_QUARTERS_0_OF_8"],
    }
    checkpoint, content_hash = journal.checkpoint("ABNB", result)
    journal.append(
        "ABNB",
        "COMPLETED",
        {
            "checkpointPath": str(checkpoint),
            "checkpointHash": content_hash,
            "terminalStatus": "SECURITY_INSUFFICIENT_DATA",
        },
    )
    report = execute_combined(
        {
            "runId": "run",
            "sliceId": "slice",
            "classifications": (
                {"symbol": "ABNB", "actions": ("NEEDS_EODHD", "NEEDS_SEC")},
            ),
        },
        eodhd=_NeverCalled(),
        sec=_NeverCalled(),
        existing_pit={},
        existing_records={},
        existing_receipts={},
        start_date=__import__("datetime").date(2020, 1, 1),
        end_date=__import__("datetime").date(2026, 7, 27),
        store=_StoreNeverCalled(),
        journal=journal,
    )
    assert report["status"] == "COMPLETE_WITH_INSUFFICIENT_DATA"
    assert report["results"] == [result]
    assert report["logicalEndpointEvaluations"] == {}
