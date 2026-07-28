import json
from pathlib import Path

import pytest

from equity_analysis.provider_validation.expansion_gate import canonical_hash
from equity_analysis.provider_validation.final_formula_aggregate import (
    _validate_scope,
    _verify_canonical_artifact,
    _verify_insufficient_result,
)


def test_final_aggregate_artifact_has_exact_scope_and_no_raw_values() -> None:
    root = Path(__file__).resolve().parents[2]
    path = root / "docs/generated/formula-ready-243-final-aggregate-v1.json"
    aggregate = json.loads(path.read_text(encoding="utf-8"))
    _verify_canonical_artifact(aggregate, "artifactContentHash")
    symbols = [item["symbol"] for item in aggregate["securities"]]
    assert len(symbols) == len(set(symbols)) == 243
    assert aggregate["statusCounts"] == {
        "FORMULA_READY": 223,
        "SECURITY_INSUFFICIENT_DATA": 20,
    }
    assert aggregate["systemExecutionFailures"] == 0
    assert aggregate["networkRetries"] == 0
    assert aggregate["objectiveRatingExecuted"] is False
    assert aggregate["rawProviderValuesIncluded"] is False
    assert not any("value" in item for item in aggregate["securities"])


def test_scope_rejects_duplicates_and_missing_symbols() -> None:
    symbols = [f"S{index:03d}" for index in range(243)]
    entries = [{"symbol": symbol} for symbol in symbols]
    assert _validate_scope(entries, symbols) == entries
    with pytest.raises(ValueError, match="FINAL_AGGREGATE_DUPLICATE_SYMBOL"):
        _validate_scope([*entries[:-1], entries[0]], symbols)
    with pytest.raises(ValueError, match="FINAL_AGGREGATE_SOURCE_SCOPE_MISMATCH"):
        _validate_scope(entries[:-1], symbols)


def test_insufficient_reason_mismatch_is_rejected() -> None:
    coverage = {
        "missingFormulaFields": [],
        "dilutedShareQuarterlyPeriods": 8,
        "interestExpenseQuarterlyPeriods": 0,
        "historicalMarketCapObservations": 12,
        "dailyPriceObservationDates": 1,
        "minimumDailyPriceObservationDates": 1,
        "historyRequirements": {
            "quarterlyFinancialPeriods": 8,
            "historicalValuationObservations": 12,
        },
        "complete": False,
    }
    result = {
        "symbol": "ABNB",
        "status": "SECURITY_INSUFFICIENT_DATA",
        "reasonCodes": ["INTEREST_EXPENSE_QUARTERS_0_OF_8"],
        "formulaCoverage": coverage,
    }
    assert _verify_insufficient_result(result)["contentHash"] == canonical_hash(result)
    with pytest.raises(ValueError, match="INSUFFICIENT_REASON_MISMATCH"):
        _verify_insufficient_result({**result, "reasonCodes": ["GENERIC_MISSING"]})


def test_component_report_and_checkpoint_hashes_are_complete() -> None:
    root = Path(__file__).resolve().parents[2]
    aggregate = json.loads(
        (
            root / "docs/generated/formula-ready-243-final-aggregate-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert len(aggregate["componentReports"]) == 12
    report_hashes = {
        item["sourceReportSha256"]
        for item in aggregate["securities"]
        if item["sourceSliceId"] is not None
    }
    assert report_hashes == {
        item["sha256"] for item in aggregate["componentReports"]
    }
    assert all(
        item["checkpointSha256"]
        for item in aggregate["securities"]
        if item["sourceSliceId"] is not None
    )
