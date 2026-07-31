from __future__ import annotations

import json
from pathlib import Path

import pytest

from equity_analysis.forward_validation.dqv_evaluation_protocol_v22 import (
    ALL_HORIZONS,
    FORMAL_HORIZONS,
    REQUIRED_BENCHMARKS,
    DqvEvaluationProtocolV22Error,
    build_protocol_fixture,
    verify_protocol_fixture,
    write_or_verify_protocol_fixture,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = (
    REPOSITORY_ROOT
    / "docs/generated/forward-decision-quality-validation-v2-2-protocol-fixture.json"
)


def test_repository_fixture_is_hash_valid_and_reproducible() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    verify_protocol_fixture(payload, repository_root=REPOSITORY_ROOT)
    assert payload == build_protocol_fixture(REPOSITORY_ROOT)


def test_historical_slices_are_explicitly_observed_diagnostics() -> None:
    payload = build_protocol_fixture(REPOSITORY_ROOT)
    historical = payload["historicalDiagnostics"]

    assert historical["evaluationRole"] == "DEVELOPMENT_OBSERVED"
    assert historical["formalGateEligible"] is False
    assert historical["claimCeiling"] == "DIAGNOSTIC_ONLY"
    assert historical["untouchedHoldout"] is False
    assert historical["selectionAfterOutcomesExistDoesNotCreateAHoldout"] is True
    assert historical["randomSelection"]["seed"] == 20260729
    assert historical["calendarAnchors"]["monthOffsetsBeforeFreeze"] == [
        3,
        6,
        9,
        12,
        18,
        24,
        48,
        72,
        120,
    ]


def test_prospective_roles_and_natural_maturity_are_not_weakened() -> None:
    payload = build_protocol_fixture(REPOSITORY_ROOT)
    rows = payload["prospectiveHorizons"]

    assert tuple(item["completedSessions"] for item in rows) == ALL_HORIZONS
    assert (
        tuple(item["completedSessions"] for item in rows if item["formalGateEligible"])
        == FORMAL_HORIZONS
    )
    assert (
        next(item for item in rows if item["completedSessions"] == 126)["evaluationRole"]
        == "LONG_HORIZON_INTERIM_DIAGNOSTIC"
    )
    assert all(item["naturalMaturityRequired"] for item in rows)
    assert all(item["minimumBootstrapBlockSessions"] >= item["completedSessions"] for item in rows)
    assert all(
        item["minimumMaturedCalendarSpanSessions"] >= item["completedSessions"] * 2 for item in rows
    )


def test_metrics_require_six_benchmarks_costs_path_risk_and_abstention() -> None:
    payload = build_protocol_fixture(REPOSITORY_ROOT)
    metrics = payload["metrics"]

    assert tuple(metrics["benchmarks"]) == REQUIRED_BENCHMARKS
    assert metrics["returnAccounting"]["requiredRepresentations"] == [
        "GROSS",
        "COST",
        "NET",
    ]
    assert {
        "MAXIMUM_ADVERSE_EXCURSION",
        "MAXIMUM_FAVORABLE_EXCURSION",
        "MAXIMUM_DRAWDOWN",
        "DOWNSIDE_CAPTURE",
        "TURNOVER",
        "LIQUIDITY_PARTICIPATION_RATE",
        "COVERAGE",
        "ABSTENTION_COUNT",
    }.issubset(metrics["requiredMetrics"])
    assert metrics["defaultLongHorizonAggregateRankAuthorized"] is False
    assert metrics["aiMayAffectDeterministicFields"] is False


def test_statistical_contract_controls_dependence_and_multiplicity() -> None:
    payload = build_protocol_fixture(REPOSITORY_ROOT)
    statistics = payload["statistics"]

    assert statistics["confidenceLevel"] == "0.90"
    assert statistics["familyWiseAlpha"] == "0.10"
    assert statistics["multipleComparisonMethod"] == "HOLM_BONFERRONI"
    assert statistics["bootstrapIterations"] == 10_000
    assert statistics["ordinaryIidBootstrapAllowed"] is False
    assert len(statistics["confirmatoryFamilies"]) == 6
    tactical = statistics["confirmatoryFamilies"][:3]
    assert all(
        "ACTIONABILITY_PARTICIPATION_MINUS_ABSTENTION" in family["tests"] for family in tactical
    )
    assert all(len(family["tests"]) == 8 for family in tactical)
    assert statistics["tacticalActionabilityPairing"] == {
        "groupingFrozenBeforeOutcome": True,
        "participationCategories": ["ENTRY", "LIMITED_ENTRY"],
        "comparison": "PAIRED_WITHIN_DECISION_DATE_NET_RETURN_SPREAD",
        "minimumPairedDecisionDates": 2,
        "minimumObservationsPerGroup": 20,
        "singleGroupDatePolicy": ("REPORT_NOT_COMPARABLE_AND_EXCLUDE_FROM_THIS_TEST"),
        "outcomeDrivenRegroupingAuthorized": False,
        "exactMarketBottomPredictionClaimed": False,
    }


def test_sector_and_size_strata_are_complete_and_underpowered_is_explicit() -> None:
    payload = build_protocol_fixture(REPOSITORY_ROOT)
    stratification = payload["stratification"]

    assert stratification["dimensions"] == ["SECTOR", "MARKET_CAP_SIZE_BAND"]
    assert stratification["minimumEligibleDecisionsForInferentialStratum"] == 20
    assert stratification["allStrataReportedEvenWhenUnderpowered"] is True
    assert stratification["underpoweredStratumStatus"] == "INSUFFICIENT_EVIDENCE"
    assert stratification["missingClassificationPolicy"] == ("EXPLICIT_MISSING_NOT_IMPUTED")


def test_current_fixture_is_blocked_without_execution_or_favorable_claim() -> None:
    payload = build_protocol_fixture(REPOSITORY_ROOT)

    assert payload["status"] == "BLOCKED_AWAITING_PROSPECTIVE_DATA"
    assert payload["currentBlockers"] == [
        "PROSPECTIVE_ENROLLMENT_NOT_EXECUTED",
        "NATURALLY_MATURED_OUTCOMES_NOT_AVAILABLE",
    ]
    assert payload["terminalRules"]["favorableConclusionRequired"] is False
    assert payload["executionBoundary"] == {
        "historicalScoringExecuted": False,
        "prospectiveEnrollmentExecuted": False,
        "outcomeObservationExecuted": False,
        "providerNetworkRequests": 0,
        "databaseWrites": 0,
        "commitCreated": False,
        "pushExecuted": False,
        "deploymentExecuted": False,
        "automaticTradingAuthorized": False,
        "rawProviderValuesIncluded": False,
    }


def test_tampering_is_rejected_and_fixture_write_is_immutable(tmp_path: Path) -> None:
    payload = build_protocol_fixture(REPOSITORY_ROOT)
    payload["status"] = "VALIDATED"

    with pytest.raises(
        DqvEvaluationProtocolV22Error,
        match="differs from the frozen contract",
    ):
        verify_protocol_fixture(payload, repository_root=REPOSITORY_ROOT)

    path = tmp_path / "fixture.json"
    assert (
        write_or_verify_protocol_fixture(
            REPOSITORY_ROOT,
            output_path=path,
        )
        == path
    )
    write_or_verify_protocol_fixture(REPOSITORY_ROOT, output_path=path)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(DqvEvaluationProtocolV22Error, match="Immutable"):
        write_or_verify_protocol_fixture(REPOSITORY_ROOT, output_path=path)
