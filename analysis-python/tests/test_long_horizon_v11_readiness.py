from __future__ import annotations

import copy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from controlled_data import require_repository_paths

from equity_analysis.historical_validation.long_horizon_v11_readiness import (
    V11_HISTORICAL_FIELDS,
    DatabaseSecurityInventory,
    _load_json,
    _roles,
    build_readiness_artifact,
    verify_readiness_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DIAGNOSTIC_AT = datetime(2026, 7, 30, 1, 0, tzinfo=UTC)


def _inventory() -> dict[str, DatabaseSecurityInventory]:
    universe = _load_json(
        REPO_ROOT
        / "analysis-python/resources/universes/"
        "market-intelligence-closed-test-us-v1.json"
    )
    return {
        symbol: DatabaseSecurityInventory(
            public_security_id=f"00000000-0000-0000-0000-{index:012d}",
            fundamental_fact_count=100,
            distinct_metric_count=8,
            earliest_fundamental_period="2014-12-31",
            latest_fundamental_period="2025-12-31",
            membership_snapshot_count=1,
            earliest_membership_as_of="2026-07-28T00:00:00+00:00",
            latest_membership_as_of="2026-07-28T00:00:00+00:00",
            classification_observation_count=1,
        )
        for index, symbol in enumerate(sorted(_roles(universe)), start=1)
    }


@pytest.fixture(scope="module")
def artifact() -> dict:
    require_repository_paths(
        REPO_ROOT,
        (
            "storage/historical-validation/yahoo-daily-price-cache-v1",
            (
                "docs/generated/"
                "long-horizon-historical-stratified-validation-v1-4-"
                "2026-07-29.json"
            ),
        ),
        purpose="Long Horizon v1.1 readiness reconstruction",
    )
    return build_readiness_artifact(
        repo_root=REPO_ROOT,
        database_inventory=_inventory(),
        diagnostic_at=DIAGNOSTIC_AT,
    )


def test_universe_role_parser_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="Duplicate universe symbol"):
        _roles(
            {
                "roles": {
                    "PRIMARY": ["AAPL"],
                    "RESERVE": ["aapl"],
                }
            }
        )


def test_historical_field_contract_is_stable_and_explicit() -> None:
    assert len(V11_HISTORICAL_FIELDS) == 28
    assert V11_HISTORICAL_FIELDS[:3] == (
        "return_on_invested_capital",
        "operating_margin",
        "free_cash_flow_margin",
    )
    assert V11_HISTORICAL_FIELDS[-3:] == (
        "point_in_time_verified_ratio",
        "revision_lineage_ratio",
        "semantic_evidence_ratio",
    )


def test_readiness_covers_complete_frozen_population(artifact: dict) -> None:
    verify_readiness_artifact(artifact, REPO_ROOT)

    assert artifact["summary"]["frozenPopulationCount"] == 66
    assert artifact["summary"]["modelCandidateCount"] == 55
    assert artifact["summary"]["terminalCounts"] == {
        "MISSING": 55,
        "NOT_APPLICABLE": 2,
        "EXCLUDED": 9,
    }


def test_v11_inputs_are_explicitly_missing_without_proxy_scores(
    artifact: dict,
) -> None:
    candidates = [
        record
        for record in artifact["records"]
        if record["role"] in {"PRIMARY", "RESERVE"}
    ]

    assert len(candidates) == 55
    assert all(record["terminalState"] == "MISSING" for record in candidates)
    assert all(
        record["missingV11Fields"] == list(V11_HISTORICAL_FIELDS)
        for record in candidates
    )
    assert all(record["v11ScoreComputed"] is False for record in candidates)
    assert artifact["summary"]["v11ScoreCount"] == 0
    assert artifact["claimBoundary"]["proxyFormulaUsed"] is False
    assert artifact["claimBoundary"]["v10ScoreReused"] is False


def test_observed_v10_history_is_development_only(artifact: dict) -> None:
    evidence = artifact["observedHistoricalEvidence"]

    assert evidence["modelVersion"] == "LONG-HORIZON-RESEARCH-v1.0.0"
    assert evidence["evaluationRole"] == "DEVELOPMENT_OBSERVED"
    assert evidence["untouchedHoldout"] is False


def test_price_outcomes_do_not_repair_decision_time_inputs(artifact: dict) -> None:
    candidates = [
        record
        for record in artifact["records"]
        if record["role"] in {"PRIMARY", "RESERVE"}
    ]

    assert artifact["summary"]["hashVerified252SessionOutcomeSeriesCount"] == 55
    assert all(
        record["priceOutcomeEvidence"]["status"] == "AVAILABLE"
        for record in candidates
    )
    assert all(
        record["priceOutcomeEvidence"]["priceActionEvidence"]
        == "EX_POST_TOTAL_RETURN_ADJUSTED"
        for record in candidates
    )
    assert artifact["summary"]["v11HistoricalDecisionReadyCount"] == 0


def test_formal_benchmark_set_remains_incomplete(artifact: dict) -> None:
    readiness = artifact["benchmarkReadiness"]

    assert readiness["SPY"] == "AVAILABLE_DIAGNOSTIC_ONLY"
    assert readiness["SECTOR"] == "MISSING"
    assert readiness["PURE_VALUE"] == "BLOCKED_V11_PIT_INPUTS"
    assert readiness["formalSetReady"] is False
    assert artifact["terminalStatus"] == "BLOCKED_BY_DATA"


def test_artifact_hash_detects_changes(artifact: dict) -> None:
    changed = copy.deepcopy(artifact)
    changed["summary"]["v11HistoricalDecisionReadyCount"] = 1

    with pytest.raises(ValueError, match="content hash mismatch"):
        verify_readiness_artifact(changed)


def test_git_safe_artifact_has_no_financial_values_or_scores(artifact: dict) -> None:
    serialized = str(artifact).lower()

    assert "numeric_value" not in serialized
    assert "rawprovidervalues" not in serialized
    assert "'score':" not in serialized
    assert artifact["claimBoundary"]["networkRequestsExecuted"] is False
    assert artifact["claimBoundary"]["forwardValidationExecuted"] is False
