from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from equity_analysis.historical_validation.governance_v1 import (
    AvailabilityEvidence,
    ClaimCeiling,
    EvaluationRole,
    OutcomeDependence,
    PriceActionEvidence,
    UniverseEvidence,
    ValidationEvidenceEnvelope,
)
from equity_analysis.historical_validation.governance_v11 import (
    EvidenceComponentState,
    EvidenceTarget,
    ModelEvidenceLabel,
    ModelTrack,
    OperationalRunStatus,
    PlannedRetrospective,
    PracticalValueThresholdPolicy,
    SuccessorAuthorization,
    SuccessorReason,
    TargetHorizonEvidenceRecord,
    ThresholdApplicability,
    register_planned_retrospective,
    validate_practical_value_threshold_policy,
    validate_successor_authorization,
    validate_target_horizon_evidence,
)


def _diagnostic_envelope() -> ValidationEvidenceEnvelope:
    return ValidationEvidenceEnvelope(
        availability=AvailabilityEvidence.CURRENT_REVISION_RETROSPECTIVE,
        universe=UniverseEvidence.CURRENT_UNIVERSE_RETROSPECTIVE,
        outcome_dependence=OutcomeDependence.OVERLAPPING_DIAGNOSTIC,
        evaluation_role=EvaluationRole.DEVELOPMENT_OBSERVED,
        price_action=PriceActionEvidence.EX_POST_TOTAL_RETURN_ADJUSTED,
    )


def _pit_envelope() -> ValidationEvidenceEnvelope:
    return ValidationEvidenceEnvelope(
        availability=AvailabilityEvidence.PIT_VERIFIED,
        universe=UniverseEvidence.HISTORICAL_MEMBERSHIP,
        outcome_dependence=OutcomeDependence.PURGED_BLOCK,
        evaluation_role=EvaluationRole.SEALED_VALIDATION,
        price_action=PriceActionEvidence.AS_OF_ACTION_LEDGER,
    )


def _forward_envelope() -> ValidationEvidenceEnvelope:
    return ValidationEvidenceEnvelope(
        availability=AvailabilityEvidence.PROSPECTIVE_SEALED,
        universe=UniverseEvidence.PROSPECTIVE_FROZEN_UNIVERSE,
        outcome_dependence=OutcomeDependence.NON_OVERLAPPING,
        evaluation_role=EvaluationRole.PROSPECTIVE_FORWARD,
        price_action=PriceActionEvidence.AS_OF_ACTION_LEDGER,
    )


def _ranking_record(**overrides) -> TargetHorizonEvidenceRecord:
    values = {
        "model_version": "TACTICAL-SIGNAL-v2.2.0",
        "model_track": ModelTrack.TACTICAL_V22,
        "target": EvidenceTarget.TACTICAL_RANKING,
        "horizon_completed_sessions": 20,
        "run_status": OperationalRunStatus.COMPLETED,
        "model_evidence_label": ModelEvidenceLabel.BACKTEST_SUPPORTED,
        "evidence_envelope": _diagnostic_envelope(),
        "target_evidence": EvidenceComponentState.PRESENT,
        "ranking_evidence": EvidenceComponentState.PRESENT,
        "entry_decision_evidence": EvidenceComponentState.MISSING,
        "limitations": ("CURRENT_UNIVERSE_SURVIVORSHIP_BIAS",),
    }
    values.update(overrides)
    return TargetHorizonEvidenceRecord(**values)


def test_run_status_and_model_label_are_independent() -> None:
    blocked = _ranking_record(
        run_status=OperationalRunStatus.BLOCKED_BY_DATA,
        model_evidence_label=ModelEvidenceLabel.NOT_VALIDATED,
        target_evidence=EvidenceComponentState.MISSING,
        ranking_evidence=EvidenceComponentState.MISSING,
    )
    assert validate_target_horizon_evidence(blocked) == ClaimCeiling.DIAGNOSTIC_ONLY
    with pytest.raises(ValueError, match="completed operational run"):
        validate_target_horizon_evidence(
            replace(
                blocked,
                model_evidence_label=ModelEvidenceLabel.PARTIALLY_SUPPORTED,
            )
        )


def test_current_universe_diagnostic_cannot_claim_pit_or_forward_support() -> None:
    validate_target_horizon_evidence(_ranking_record())
    with pytest.raises(ValueError, match="strict PIT"):
        validate_target_horizon_evidence(
            _ranking_record(model_evidence_label=ModelEvidenceLabel.PIT_SUPPORTED)
        )
    with pytest.raises(ValueError, match="prospective sealed"):
        validate_target_horizon_evidence(
            _ranking_record(model_evidence_label=ModelEvidenceLabel.FORWARD_SUPPORTED)
        )


def test_strict_pit_and_forward_labels_require_matching_evidence() -> None:
    pit = _ranking_record(
        model_evidence_label=ModelEvidenceLabel.PIT_SUPPORTED,
        evidence_envelope=_pit_envelope(),
    )
    assert validate_target_horizon_evidence(pit) == ClaimCeiling.VALIDATION_ELIGIBLE
    forward = replace(
        pit,
        model_evidence_label=ModelEvidenceLabel.FORWARD_SUPPORTED,
        evidence_envelope=_forward_envelope(),
    )
    assert validate_target_horizon_evidence(forward) == ClaimCeiling.VALIDATION_ELIGIBLE


def test_entry_decision_support_cannot_inherit_ranking_evidence() -> None:
    entry = _ranking_record(
        target=EvidenceTarget.TACTICAL_ENTRY_DECISION,
        model_evidence_label=ModelEvidenceLabel.PARTIALLY_SUPPORTED,
    )
    with pytest.raises(ValueError, match="separate entry evidence"):
        validate_target_horizon_evidence(entry)
    validate_target_horizon_evidence(
        replace(
            entry,
            entry_decision_evidence=EvidenceComponentState.PRESENT,
        )
    )


@pytest.mark.parametrize(
    "target",
    [
        EvidenceTarget.COMPANY_QUALITY,
        EvidenceTarget.SECURITY_ATTRACTIVENESS,
        EvidenceTarget.EXPECTED_RETURN,
        EvidenceTarget.DOWNSIDE_RISK,
    ],
)
def test_long_horizon_targets_are_separate_and_start_at_252(
    target: EvidenceTarget,
) -> None:
    record = TargetHorizonEvidenceRecord(
        model_version="LONG-HORIZON-RESEARCH-v1.1.0",
        model_track=ModelTrack.LONG_HORIZON_V11,
        target=target,
        horizon_completed_sessions=252,
        run_status=OperationalRunStatus.COMPLETED,
        model_evidence_label=ModelEvidenceLabel.PARTIALLY_SUPPORTED,
        evidence_envelope=_diagnostic_envelope(),
        target_evidence=EvidenceComponentState.PRESENT,
        ranking_evidence=EvidenceComponentState.NOT_APPLICABLE,
        entry_decision_evidence=EvidenceComponentState.NOT_APPLICABLE,
    )
    validate_target_horizon_evidence(record)
    with pytest.raises(ValueError, match="starts at 252"):
        validate_target_horizon_evidence(
            replace(record, horizon_completed_sessions=126)
        )


def test_invalidated_requires_predeclared_nondevelopment_adverse_evidence() -> None:
    with pytest.raises(ValueError, match="predeclared"):
        validate_target_horizon_evidence(
            _ranking_record(
                model_evidence_label=ModelEvidenceLabel.INVALIDATED,
                evidence_envelope=_pit_envelope(),
            )
        )
    validate_target_horizon_evidence(
        _ranking_record(
            model_evidence_label=ModelEvidenceLabel.INVALIDATED,
            evidence_envelope=_pit_envelope(),
            adverse_evidence_predeclared=True,
        )
    )


def test_one_frozen_version_has_one_planned_retrospective() -> None:
    plan = PlannedRetrospective(
        model_version="TACTICAL-SIGNAL-v2.2.0",
        freeze_hash="A" * 64,
        plan_hash="B" * 64,
        planned_run_id="tactical-v22-tier1",
    )
    ledger = register_planned_retrospective((), plan)
    assert register_planned_retrospective(ledger, plan) == ledger
    with pytest.raises(ValueError, match="one planned retrospective"):
        register_planned_retrospective(
            ledger,
            replace(plan, plan_hash="C" * 64, planned_run_id="rerun"),
        )
    with pytest.raises(ValueError, match="Observed outcomes"):
        register_planned_retrospective(
            (),
            replace(plan, observed_outcomes_used_to_choose_contract=True),
        )


def test_successor_requires_reason_new_version_freeze_and_later_evidence() -> None:
    authorization = SuccessorAuthorization(
        predecessor_model_version="TACTICAL-SIGNAL-v2.2.0",
        successor_model_version="TACTICAL-SIGNAL-v2.3.0",
        predecessor_freeze_hash="A" * 64,
        successor_freeze_hash="B" * 64,
        reason=SuccessorReason.METHODOLOGY_DEFECT,
        evidence_reference="artifact:methodology-defect",
    )
    validate_successor_authorization(authorization)
    with pytest.raises(ValueError, match="new model version"):
        validate_successor_authorization(
            replace(
                authorization,
                successor_model_version=authorization.predecessor_model_version,
            )
        )


def test_observed_tier1_cannot_receive_post_observation_numeric_thresholds() -> None:
    observed = PracticalValueThresholdPolicy(
        policy_version="PRACTICAL-VALUE-v1",
        applicability=ThresholdApplicability.OBSERVED_TIER1_NOT_APPLICABLE,
        frozen_before_outcomes=False,
    )
    validate_practical_value_threshold_policy(observed)
    with pytest.raises(ValueError, match="post-observation"):
        validate_practical_value_threshold_policy(
            replace(observed, numeric_thresholds=(("minimumSpread", "0.01"),))
        )
    forward = PracticalValueThresholdPolicy(
        policy_version="PRACTICAL-VALUE-FORWARD-v1",
        applicability=ThresholdApplicability.FORWARD_ONLY,
        frozen_before_outcomes=True,
        numeric_thresholds=(("minimumNetValue", "PREDECLARED"),),
    )
    validate_practical_value_threshold_policy(forward)


def test_git_safe_v11_policy_hash_and_exact_labels() -> None:
    root = Path(__file__).resolve().parents[2]
    path = root / "docs/generated/model-validation-governance-v1-1.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    expected = artifact.pop("artifactContentHash")
    canonical = json.dumps(
        artifact,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper() == expected
    assert artifact["statusAxes"]["modelEvidenceLabel"] == [
        "BACKTEST_SUPPORTED",
        "PIT_SUPPORTED",
        "FORWARD_SUPPORTED",
        "PARTIALLY_SUPPORTED",
        "NOT_VALIDATED",
        "INVALIDATED",
    ]
    assert artifact["modelBoundaries"]["tacticalV22OutputType"] == (
        "DETERMINISTIC_ORDINAL_SCORE"
    )
    assert artifact["finiteEvaluation"][
        "oneFrozenVersionOnePlannedRetrospective"
    ] is True
    assert artifact["executionBoundary"]["existingGovernanceV1Modified"] is False
