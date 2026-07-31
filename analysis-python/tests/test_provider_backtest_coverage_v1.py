from __future__ import annotations

from pathlib import Path

import pytest
from controlled_data import require_artifact_controlled_references

from equity_analysis.historical_validation.provider_backtest_coverage_v1 import (
    MINIMUM_ADJUSTED_CLOSE_SESSIONS,
    MINIMUM_ANNUAL_OBSERVATIONS,
    MINIMUM_MARKET_CAP_OBSERVATIONS,
    MINIMUM_QUARTERLY_OBSERVATIONS,
    PREFLIGHT_PATH,
    ProviderBacktestCoverageError,
    build_provider_backtest_coverage,
    write_coverage,
)
from equity_analysis.historical_validation.provider_backtest_preflight_v1 import (
    REPOSITORY_ROOT,
    canonical_hash,
)


def _require_controlled_data() -> None:
    require_artifact_controlled_references(
        REPOSITORY_ROOT,
        [PREFLIGHT_PATH],
        purpose="provider backtest coverage audit",
    )


@pytest.fixture(scope="module")
def coverage_artifact() -> dict:
    _require_controlled_data()
    return build_provider_backtest_coverage()


def test_coverage_thresholds_are_practical_and_frozen() -> None:
    assert MINIMUM_ADJUSTED_CLOSE_SESSIONS == 1261
    assert MINIMUM_MARKET_CAP_OBSERVATIONS == 12
    assert MINIMUM_QUARTERLY_OBSERVATIONS == 20
    assert MINIMUM_ANNUAL_OBSERVATIONS == 7


def test_canary_passes_before_exact_one_hundred_security_expansion(
    coverage_artifact: dict,
) -> None:
    artifact = coverage_artifact

    assert artifact["status"] == "PASS_WITH_EXECUTION_LIMITATIONS"
    assert artifact["passScope"] == "PER_SECURITY_RAW_COVERAGE_AND_HASH_AUDIT"
    assert artifact["executionOrder"] == [
        "EIGHT_SECTOR_CANARY",
        "FULL_100_SECURITY_AUDIT",
    ]
    assert artifact["canary"]["status"] == "PASS"
    assert artifact["canary"]["securityCount"] == 8
    assert artifact["fullAudit"]["status"] == "PASS_PER_SECURITY_COVERAGE"
    assert artifact["fullAudit"]["securityCount"] == 100
    assert artifact["fullAudit"]["stableSecurityIdCount"] == 100
    assert artifact["networkRequestsExecuted"] is False
    assert artifact["providerValuesIncluded"] is False
    ranges = artifact["fullAudit"]["aggregateUsableRanges"]
    assert ranges["commonRangeStatus"] == "NO_COMMON_ALL_FIELD_ANCHOR"
    assert ranges["exact100CommonInputWindowAvailable"] is False
    assert (
        ranges["crossSectionByCompletedSessions"]["252"][
            "maximumConcurrentSecurityCount"
        ]
        >= 50
    )
    assert (
        ranges["crossSectionByCompletedSessions"]["1260"][
            "maximumConcurrentSecurityCount"
        ]
        == 0
    )


def test_all_results_have_hashes_ranges_and_no_duplicate_periods(
    coverage_artifact: dict,
) -> None:
    for item in coverage_artifact["results"]:
        assert item["securityId"] == f"US:{item['symbol']}"
        assert len(item["controlledPayload"]["contentHash"]) == 64
        assert len(item["controlledPayload"]["fileSha256"]) == 64
        assert item["adjustedClose"]["recordCount"] >= 1261
        assert item["adjustedClose"]["duplicatePeriodCount"] == 0
        assert item["historicalMarketCap"]["recordCount"] >= 12
        assert item["historicalMarketCap"]["duplicatePeriodCount"] == 0
        assert item["usableRange"]["earliestPracticalAnchor"]
        assert item["usableRange"]["latestInputAnchor"]
        for coverage in item["financialFieldCoverage"].values():
            assert coverage["annual"]["duplicatePeriodCount"] == 0
            assert coverage["quarterly"]["duplicatePeriodCount"] == 0


def test_coverage_hash_is_canonical_and_deterministic(
    coverage_artifact: dict,
) -> None:
    first = coverage_artifact
    second = build_provider_backtest_coverage()
    body = dict(first)
    claimed = body.pop("artifactContentHash")

    assert first == second
    assert claimed == canonical_hash(body)


def test_write_coverage_is_immutable(
    tmp_path: Path,
    coverage_artifact: dict,
) -> None:
    payload = coverage_artifact
    path = tmp_path / "coverage.json"
    write_coverage(path, payload)
    write_coverage(path, payload)

    changed = dict(payload)
    changed["status"] = "CHANGED"
    with pytest.raises(
        ProviderBacktestCoverageError,
        match="IMMUTABLE_COVERAGE_CONFLICT",
    ):
        write_coverage(path, changed)
