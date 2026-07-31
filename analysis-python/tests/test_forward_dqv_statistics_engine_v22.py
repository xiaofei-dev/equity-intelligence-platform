from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid5

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import ModelTrack
from equity_analysis.forward_validation.dqv_statistics_contracts_v22 import (
    FORWARD_DQV_STATISTICS_INPUT_V22,
    AiProvenance,
    DownsideCaptureState,
    EvaluationState,
    HumanProvenance,
    SizeBand,
    seal_matured_observation,
)
from equity_analysis.forward_validation.dqv_statistics_engine_v22 import (
    evaluate_forward_dqv_v22,
)
from equity_analysis.forward_validation.dqv_statistics_preflight_v22 import (
    build_statistics_preflight_v22,
    verify_statistics_preflight_v22,
    write_or_verify_statistics_preflight_v22,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind
from equity_analysis.tactical.contracts_v22 import Actionability, SetupThesis

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT_PATH = (
    REPOSITORY_ROOT / "docs/generated/forward-dqv-v2-2-statistical-engine-preflight.json"
)
_NAMESPACE = UUID("4c7448d1-3e4e-4d7c-a78c-3c9179ac67c4")


def _hash(label: str) -> str:
    return canonical_hash({"fixture": label})


def _assessed_rows(
    *,
    completed_sessions: int,
    favorable: bool = True,
    all_participating: bool = False,
    include_all_abstain_date: bool = False,
    ai: AiProvenance = AiProvenance.NOT_EXECUTED,
    human: HumanProvenance = HumanProvenance.NOT_REVIEWED,
) -> tuple:
    rows = []
    track = ModelTrack.TACTICAL if completed_sessions in {5, 20, 60} else ModelTrack.LONG_HORIZON
    spacing = completed_sessions * 2
    decision_sessions = (0, spacing, spacing * 2) if include_all_abstain_date else (0, spacing)
    for decision_number, session_index in enumerate(decision_sessions):
        enrollment = uuid5(
            _NAMESPACE,
            f"enrollment:{completed_sessions}:{decision_number}",
        )
        decision_date = date(2026, 1, 2 + decision_number)
        for index in range(66):
            security_id = uuid5(_NAMESPACE, f"security:{index}")
            quality = Decimal(index)
            direction = Decimal(1) if favorable else Decimal(-1)
            net = Decimal("0.02") + direction * quality / Decimal("1000")
            gross = net + Decimal("0.001")
            benchmarks = {benchmark.value: Decimal("0.01") for benchmark in BenchmarkKind}
            benchmark_drawdowns = {benchmark.value: Decimal("-0.10") for benchmark in BenchmarkKind}
            body: dict[str, object] = {
                "schemaVersion": FORWARD_DQV_STATISTICS_INPUT_V22,
                "observationId": (f"{completed_sessions}:{decision_number}:{security_id}"),
                "enrollmentId": str(enrollment),
                "decisionManifestHash": _hash(f"decision:{completed_sessions}:{decision_number}"),
                "outcomeBatchHash": _hash(f"outcome:{completed_sessions}:{decision_number}"),
                "publicSecurityId": str(security_id),
                "decisionDate": decision_date,
                "decisionCompletedSessionIndex": session_index,
                "frozenPopulationCount": 66,
                "completedSessions": completed_sessions,
                "modelTrack": track.value,
                "modelVersion": (
                    "TACTICAL-SIGNAL-v2.2.0"
                    if track == ModelTrack.TACTICAL
                    else "LONG-HORIZON-RESEARCH-v1.1.0"
                ),
                "state": EvaluationState.ASSESSED.value,
                "reasonCodes": [],
                "sector": "Industrials" if index % 2 == 0 else "Technology",
                "sizeBand": (SizeBand.LARGE.value if index % 2 == 0 else SizeBand.MID.value),
                "abstained": False,
                "grossReturn": gross,
                "roundTripCostRate": Decimal("0.001"),
                "netReturn": net,
                "liquidityParticipationRate": (Decimal("0.01") + Decimal(index) / Decimal("10000")),
                "liquidityEvidenceHash": _hash(
                    f"liquidity:{completed_sessions}:{decision_number}:{index}"
                ),
                "benchmarkNetReturns": benchmarks,
                "benchmarkMaximumDrawdowns": benchmark_drawdowns,
                "maximumAdverseExcursion": Decimal("-0.03"),
                "maximumFavorableExcursion": Decimal("0.12"),
                "maximumDrawdown": Decimal("-0.05"),
                "downsideCaptureState": DownsideCaptureState.VALID.value,
                "downsideCapture": Decimal("0.70"),
                "realizedVolatility": Decimal("0.03"),
                "timeToFirstPositiveSession": 1,
                "timeToMaximumFavorableSession": max(1, completed_sessions // 2),
                "aiProvenance": ai.value,
                "humanProvenance": human.value,
                "aiAffectedDeterministicResult": False,
                "humanAffectedDeterministicResult": False,
                "provenanceHash": _hash(f"provenance:{ai}:{human}:{index}"),
                "sourceEvidenceHash": _hash(
                    f"source:{completed_sessions}:{decision_number}:{index}"
                ),
            }
            if track == ModelTrack.TACTICAL:
                actionability = (
                    Actionability.WATCH_ONLY
                    if include_all_abstain_date and decision_number == 0
                    else (
                        Actionability.ENTRY
                        if all_participating or index >= 33
                        else Actionability.WATCH_ONLY
                    )
                )
                body.update(
                    {
                        "deterministicScore": quality,
                        "selectedThesis": (
                            SetupThesis.CONTINUATION.value
                            if index % 2 == 0
                            else SetupThesis.MEAN_REVERSION.value
                        ),
                        "timingCategory": actionability.value,
                        "abstained": actionability == Actionability.WATCH_ONLY,
                    }
                )
            else:
                body.update(
                    {
                        "businessQualityScore": quality,
                        "securityAttractivenessScore": quality,
                        "downsideRiskScore": Decimal(65 - index),
                        "expectedReturnLow": net - Decimal("0.05"),
                        "expectedReturnBase": net,
                        "expectedReturnHigh": net + Decimal("0.05"),
                        "futureBusinessQualityOutcome": quality / Decimal("100"),
                    }
                )
            rows.append(seal_matured_observation(body))
    return tuple(rows)


def _missing_rows(completed_sessions: int) -> tuple:
    rows = []
    for index in range(66):
        enrollment = uuid5(_NAMESPACE, f"missing:{completed_sessions}")
        security_id = uuid5(_NAMESPACE, f"security:{index}")
        body = {
            "schemaVersion": FORWARD_DQV_STATISTICS_INPUT_V22,
            "observationId": f"missing:{completed_sessions}:{security_id}",
            "enrollmentId": str(enrollment),
            "decisionManifestHash": _hash("missing-decision"),
            "outcomeBatchHash": _hash("missing-outcome"),
            "publicSecurityId": str(security_id),
            "decisionDate": date(2026, 1, 2),
            "decisionCompletedSessionIndex": 0,
            "frozenPopulationCount": 66,
            "completedSessions": completed_sessions,
            "modelTrack": (
                ModelTrack.TACTICAL.value
                if completed_sessions in {5, 20, 60}
                else ModelTrack.LONG_HORIZON.value
            ),
            "modelVersion": (
                "TACTICAL-SIGNAL-v2.2.0"
                if completed_sessions in {5, 20, 60}
                else "LONG-HORIZON-RESEARCH-v1.1.0"
            ),
            "state": EvaluationState.MISSING.value,
            "reasonCodes": ["OUTCOME_NOT_AVAILABLE"],
            "sector": None,
            "sizeBand": SizeBand.MISSING.value,
            "abstained": False,
            "benchmarkNetReturns": {},
            "benchmarkMaximumDrawdowns": {},
            "downsideCaptureState": (DownsideCaptureState.MISSING_SPY_PATH_NOT_READY.value),
            "aiProvenance": AiProvenance.NOT_EXECUTED.value,
            "humanProvenance": HumanProvenance.NOT_REVIEWED.value,
            "aiAffectedDeterministicResult": False,
            "humanAffectedDeterministicResult": False,
            "provenanceHash": _hash(f"missing-provenance:{index}"),
            "sourceEvidenceHash": _hash(f"missing-source:{index}"),
        }
        rows.append(seal_matured_observation(body))
    return tuple(rows)


def test_repository_preflight_is_hash_valid_blocked_and_has_no_claims() -> None:
    artifact = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
    verify_statistics_preflight_v22(
        artifact,
        repository_root=REPOSITORY_ROOT,
    )
    assert artifact == build_statistics_preflight_v22(REPOSITORY_ROOT)
    assert artifact["status"] == "BLOCKED"
    assert artifact["realClaims"]["modelValidated"] is False
    assert artifact["bootstrap"]["iterations"] == 10_000
    assert len(artifact["requiredBenchmarks"]) == 6


def test_preflight_write_is_immutable(tmp_path: Path) -> None:
    path = tmp_path / "preflight.json"
    write_or_verify_statistics_preflight_v22(
        repository_root=REPOSITORY_ROOT,
        output_path=path,
    )
    write_or_verify_statistics_preflight_v22(
        repository_root=REPOSITORY_ROOT,
        output_path=path,
    )
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Immutable"):
        write_or_verify_statistics_preflight_v22(
            repository_root=REPOSITORY_ROOT,
            output_path=path,
        )


def test_tactical_formal_evaluation_uses_six_benchmarks_holm_and_timing() -> None:
    result = evaluate_forward_dqv_v22(
        _assessed_rows(completed_sessions=5),
        completed_sessions=5,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert result["terminalClassification"] == "VALIDATED"
    assert len(result["confirmatoryTests"]) == 8
    assert all(item["adjustedPValue"] is not None for item in result["confirmatoryTests"])
    assert all(item["bootstrapIterations"] == 10_000 for item in result["confirmatoryTests"])
    assert {item["holmFamilyId"] for item in result["confirmatoryTests"]} == {"TACTICAL_5_SESSION"}
    assert all(
        item["holmFamilySize"] == 8
        and item["pValueMethod"] == "NULL_CENTERED_CIRCULAR_BLOCK_BOOTSTRAP"
        for item in result["confirmatoryTests"]
    )
    assert {item["selectedThesis"] for item in result["tacticalEntryTiming"]} == {
        "CONTINUATION",
        "MEAN_REVERSION",
    }
    assert all(
        item["confirmatoryClaimAuthorized"] is False for item in result["tacticalEntryTiming"]
    )
    actionability = next(
        item
        for item in result["confirmatoryTests"]
        if item["testId"] == "TACTICAL_ACTIONABILITY_PARTICIPATION_MINUS_ABSTENTION"
    )
    assert actionability["identifiabilityStatus"] == "IDENTIFIABLE"
    assert actionability["frozenGroupingField"] == "timingCategory"
    assert actionability["outcomeDrivenRegroupingAuthorized"] is False
    assert result["descriptiveMetrics"]["selectionTurnover"]["averageOneWayTurnover"] is not None
    assert result["descriptiveMetrics"]["meanLiquidityParticipationRate"] is not None
    body = dict(result)
    claim = body.pop("reportContentHash")
    assert canonical_hash(body) == claim


def test_adverse_tactical_results_return_not_validated_not_a_favorable_claim() -> None:
    result = evaluate_forward_dqv_v22(
        _assessed_rows(completed_sessions=20, favorable=False),
        completed_sessions=20,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert result["terminalClassification"] == "NOT_VALIDATED"
    assert result["executionBoundary"]["favorableResultRequired"] is False
    assert any(not item["passed"] for item in result["confirmatoryTests"])
    assert all(
        Decimal(item["rawPValue"]) > Decimal("0.10") for item in result["confirmatoryTests"][:1]
    )


def test_actionability_test_is_insufficient_when_abstention_is_not_identifiable() -> None:
    result = evaluate_forward_dqv_v22(
        _assessed_rows(completed_sessions=5, all_participating=True),
        completed_sessions=5,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    actionability = next(
        item
        for item in result["confirmatoryTests"]
        if item["testId"] == "TACTICAL_ACTIONABILITY_PARTICIPATION_MINUS_ABSTENTION"
    )
    assert result["terminalClassification"] == "INSUFFICIENT_DATA"
    assert actionability["identifiabilityStatus"] == "NOT_IDENTIFIABLE"
    assert actionability["rawPValue"] is None
    assert actionability["adjustedPValue"] is None
    assert "ABSTENTION_GROUP_BELOW_20" in actionability["reasonCodes"]


def test_all_abstain_date_is_excluded_while_later_paired_dates_remain_valid() -> None:
    result = evaluate_forward_dqv_v22(
        _assessed_rows(
            completed_sessions=5,
            include_all_abstain_date=True,
        ),
        completed_sessions=5,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    actionability = next(
        item
        for item in result["confirmatoryTests"]
        if item["testId"] == "TACTICAL_ACTIONABILITY_PARTICIPATION_MINUS_ABSTENTION"
    )
    assert actionability["identifiabilityStatus"] == "IDENTIFIABLE"
    assert actionability["eligibleDecisionDateCount"] == 2
    assert actionability["excludedDecisionDateCount"] == 1
    assert actionability["comparisonUnit"] == "PAIRED_DECISION_DATE_SPREAD"


@pytest.mark.parametrize(
    ("replacement", "expected_state", "expected_reason"),
    [
        (
            None,
            "MISSING",
            "TURNOVER_SELECTION_SCORE_MISSING",
        ),
        (
            Decimal("50"),
            "NOT_IDENTIFIABLE",
            "TURNOVER_TOP_BAND_NOT_IDENTIFIABLE",
        ),
    ],
)
def test_long_turnover_missing_or_tied_score_is_explicit_without_crashing(
    replacement: Decimal | None,
    expected_state: str,
    expected_reason: str,
) -> None:
    rows = []
    for row in _assessed_rows(completed_sessions=126):
        body = row.model_dump(
            mode="json",
            by_alias=True,
            exclude={"observation_content_hash"},
        )
        body["securityAttractivenessScore"] = replacement
        rows.append(seal_matured_observation(body))
    result = evaluate_forward_dqv_v22(
        tuple(rows),
        completed_sessions=126,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    turnover = result["descriptiveMetrics"]["selectionTurnover"]
    assert result["terminalClassification"] == "DIAGNOSTIC_ONLY"
    assert turnover["state"] == expected_state
    assert any(reason.startswith(expected_reason) for reason in turnover["reasonCodes"])
    assert turnover["averageOneWayTurnover"] is None


def test_first_decision_has_no_turnover_transition_and_is_not_assessed() -> None:
    rows = _assessed_rows(completed_sessions=126)[:66]
    result = evaluate_forward_dqv_v22(
        rows,
        completed_sessions=126,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    turnover = result["descriptiveMetrics"]["selectionTurnover"]
    assert turnover["state"] == "INSUFFICIENT_DATA"
    assert turnover["reasonCodes"] == ["NO_TURNOVER_TRANSITION"]
    assert turnover["transitionCount"] == 0


def test_missing_liquidity_participation_evidence_blocks_evaluation() -> None:
    rows = list(_assessed_rows(completed_sessions=5))
    body = rows[0].model_dump(
        mode="json",
        by_alias=True,
        exclude={"observation_content_hash"},
    )
    body["liquidityParticipationRate"] = None
    body["liquidityEvidenceHash"] = None
    rows[0] = seal_matured_observation(body)
    result = evaluate_forward_dqv_v22(
        tuple(rows),
        completed_sessions=5,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert result["terminalClassification"] == "BLOCKED_BY_EVIDENCE"
    assert "REQUIRED_HASH_BOUND_LIQUIDITY_EVIDENCE_MISSING" in result["reasonCodes"]


def test_not_applicable_downside_capture_is_explicit_and_does_not_zero_fill() -> None:
    rows = []
    for row in _assessed_rows(completed_sessions=5):
        body = row.model_dump(
            mode="json",
            by_alias=True,
            exclude={"observation_content_hash"},
        )
        body["downsideCaptureState"] = (
            DownsideCaptureState.NOT_APPLICABLE_NO_SPY_NEGATIVE_SESSIONS.value
        )
        body["downsideCapture"] = None
        rows.append(seal_matured_observation(body))
    result = evaluate_forward_dqv_v22(
        tuple(rows),
        completed_sessions=5,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    risk = result["targetResults"][0]["riskGuardrails"]
    assert result["terminalClassification"] == "INSUFFICIENT_DATA"
    assert risk["identifiabilityStatus"] == "NOT_IDENTIFIABLE"
    assert risk["notApplicableCount"] > 0
    assert risk["meanDownsideCapture"] is None
    assert result["descriptiveMetrics"]["meanNetReturn"] is not None
    assert result["descriptiveMetrics"]["meanDownsideCapture"] is None


def test_long_formal_evaluation_separates_targets_and_calibrates_range() -> None:
    result = evaluate_forward_dqv_v22(
        _assessed_rows(completed_sessions=252),
        completed_sessions=252,
        assessed_at=datetime(2028, 1, 1, tzinfo=UTC),
    )
    targets = {item["target"]: item["status"] for item in result["targetResults"]}
    assert targets == {
        "BUSINESS_QUALITY": "VALIDATED",
        "SECURITY_ATTRACTIVENESS": "VALIDATED",
        "DOWNSIDE_RISK": "VALIDATED",
        "EXPECTED_RETURN_CALIBRATION": "VALIDATED",
    }
    calibration = result["longExpectedReturnCalibration"]
    assert calibration["nominalProbabilityClaimed"] is False
    assert calibration["metrics"]["empiricalRangeCoverage"] == "1.000000000000"
    families = {item["holmFamilyId"] for item in result["confirmatoryTests"]}
    assert families == {
        "LONG_252_BUSINESS_QUALITY",
        "LONG_252_SECURITY_ATTRACTIVENESS",
        "LONG_252_DOWNSIDE_RISK",
    }
    assert {
        item["holmFamilySize"]
        for item in result["confirmatoryTests"]
        if item["holmFamilyId"] == "LONG_252_SECURITY_ATTRACTIVENESS"
    } == {7}
    assert result["terminalClassification"] == "VALIDATED"


def test_126_session_results_are_diagnostic_only_even_with_complete_evidence() -> None:
    result = evaluate_forward_dqv_v22(
        _assessed_rows(completed_sessions=126),
        completed_sessions=126,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert result["terminalClassification"] == "DIAGNOSTIC_ONLY"
    assert result["evaluationRole"] == "LONG_HORIZON_INTERIM_DIAGNOSTIC"
    assert result["confirmatoryTests"] == []


def test_incomplete_sample_and_external_evidence_blocker_are_distinct() -> None:
    insufficient = evaluate_forward_dqv_v22(
        _missing_rows(60),
        completed_sessions=60,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert insufficient["terminalClassification"] == "INSUFFICIENT_DATA"
    assert "ELIGIBLE_SECURITY_DECISIONS_BELOW_100" in insufficient["reasonCodes"]

    blocked = evaluate_forward_dqv_v22(
        _assessed_rows(completed_sessions=60),
        completed_sessions=60,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
        evidence_blockers=("OUTCOME_HASH_CHAIN_MISMATCH",),
    )
    assert blocked["terminalClassification"] == "BLOCKED_BY_EVIDENCE"
    assert blocked["confirmatoryTests"] == []


def test_ai_and_human_provenance_are_descriptive_only() -> None:
    baseline = evaluate_forward_dqv_v22(
        _assessed_rows(completed_sessions=5),
        completed_sessions=5,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    reviewed = evaluate_forward_dqv_v22(
        _assessed_rows(
            completed_sessions=5,
            ai=AiProvenance.NARRATIVE_ONLY,
            human=HumanProvenance.REVIEWED_SEPARATE_ACTION,
        ),
        completed_sessions=5,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert reviewed["terminalClassification"] == baseline["terminalClassification"]
    assert reviewed["confirmatoryTests"] == baseline["confirmatoryTests"]
    assert reviewed["provenanceStrata"][0]["deterministicInfluenceAuthorized"] is False


def test_observation_contract_rejects_cost_mismatch_and_influence() -> None:
    row = _assessed_rows(completed_sessions=5)[0]
    payload = row.model_dump(mode="json", by_alias=True)
    payload["netReturn"] = "0"
    payload.pop("observationContentHash")
    with pytest.raises(ValueError, match="Net return"):
        seal_matured_observation(payload)

    payload = row.model_dump(mode="json", by_alias=True)
    payload["aiAffectedDeterministicResult"] = True
    payload.pop("observationContentHash")
    with pytest.raises(ValueError):
        seal_matured_observation(payload)
