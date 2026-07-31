from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from equity_analysis.historical_validation.governance_v1 import (
    AvailabilityEvidence,
    ClaimCeiling,
    EvaluationRole,
    OutcomeDependence,
    PriceActionEvidence,
    UniverseEvidence,
    ValidationEvidenceEnvelope,
    claim_ceiling,
)

MODEL_VALIDATION_GOVERNANCE_V11 = "MODEL-VALIDATION-GOVERNANCE-v1.1.0"


class OperationalRunStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    BLOCKED_BY_DATA = "BLOCKED_BY_DATA"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    FAILED = "FAILED"


class ModelEvidenceLabel(StrEnum):
    BACKTEST_SUPPORTED = "BACKTEST_SUPPORTED"
    PIT_SUPPORTED = "PIT_SUPPORTED"
    FORWARD_SUPPORTED = "FORWARD_SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    NOT_VALIDATED = "NOT_VALIDATED"
    INVALIDATED = "INVALIDATED"


class ModelTrack(StrEnum):
    TACTICAL_V22 = "TACTICAL_V22"
    LONG_HORIZON_V11 = "LONG_HORIZON_V11"


class EvidenceTarget(StrEnum):
    TACTICAL_RANKING = "TACTICAL_RANKING"
    TACTICAL_ENTRY_DECISION = "TACTICAL_ENTRY_DECISION"
    COMPANY_QUALITY = "COMPANY_QUALITY"
    SECURITY_ATTRACTIVENESS = "SECURITY_ATTRACTIVENESS"
    EXPECTED_RETURN = "EXPECTED_RETURN"
    DOWNSIDE_RISK = "DOWNSIDE_RISK"


class EvidenceComponentState(StrEnum):
    PRESENT = "PRESENT"
    MISSING = "MISSING"
    NOT_EVALUATED = "NOT_EVALUATED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SuccessorReason(StrEnum):
    IMPLEMENTATION_DEFECT = "IMPLEMENTATION_DEFECT"
    METHODOLOGY_DEFECT = "METHODOLOGY_DEFECT"
    JUSTIFIED_MISSING_FACTOR = "JUSTIFIED_MISSING_FACTOR"
    SYSTEMATICALLY_HARMFUL_ASSUMPTION = "SYSTEMATICALLY_HARMFUL_ASSUMPTION"


class ThresholdApplicability(StrEnum):
    FORWARD_ONLY = "FORWARD_ONLY"
    OBSERVED_TIER1_NOT_APPLICABLE = "OBSERVED_TIER1_NOT_APPLICABLE"


TACTICAL_HORIZONS = frozenset({5, 20, 60})
LONG_HORIZON_MINIMUM_SESSIONS = 252
TACTICAL_TARGETS = frozenset(
    {
        EvidenceTarget.TACTICAL_RANKING,
        EvidenceTarget.TACTICAL_ENTRY_DECISION,
    }
)
LONG_HORIZON_TARGETS = frozenset(
    {
        EvidenceTarget.COMPANY_QUALITY,
        EvidenceTarget.SECURITY_ATTRACTIVENESS,
        EvidenceTarget.EXPECTED_RETURN,
        EvidenceTarget.DOWNSIDE_RISK,
    }
)
SUPPORT_LABELS = frozenset(
    {
        ModelEvidenceLabel.BACKTEST_SUPPORTED,
        ModelEvidenceLabel.PIT_SUPPORTED,
        ModelEvidenceLabel.FORWARD_SUPPORTED,
        ModelEvidenceLabel.PARTIALLY_SUPPORTED,
    }
)


@dataclass(frozen=True)
class TargetHorizonEvidenceRecord:
    model_version: str
    model_track: ModelTrack
    target: EvidenceTarget
    horizon_completed_sessions: int
    run_status: OperationalRunStatus
    model_evidence_label: ModelEvidenceLabel
    evidence_envelope: ValidationEvidenceEnvelope
    target_evidence: EvidenceComponentState
    ranking_evidence: EvidenceComponentState
    entry_decision_evidence: EvidenceComponentState
    limitations: tuple[str, ...] = ()
    adverse_evidence_predeclared: bool = False
    ai_may_affect_deterministic_fields: bool = False
    human_judgment_may_mutate_model_snapshot: bool = False


@dataclass(frozen=True)
class PlannedRetrospective:
    model_version: str
    freeze_hash: str
    plan_hash: str
    planned_run_id: str
    observed_outcomes_used_to_choose_contract: bool = False


@dataclass(frozen=True)
class SuccessorAuthorization:
    predecessor_model_version: str
    successor_model_version: str
    predecessor_freeze_hash: str
    successor_freeze_hash: str
    reason: SuccessorReason
    evidence_reference: str
    later_window_or_prospective_evaluation_required: bool = True


@dataclass(frozen=True)
class PracticalValueThresholdPolicy:
    policy_version: str
    applicability: ThresholdApplicability
    frozen_before_outcomes: bool
    numeric_thresholds: tuple[tuple[str, str], ...] = ()


def _strict_pit(envelope: ValidationEvidenceEnvelope) -> bool:
    return (
        envelope.availability == AvailabilityEvidence.PIT_VERIFIED
        and envelope.universe == UniverseEvidence.HISTORICAL_MEMBERSHIP
        and envelope.outcome_dependence
        in {OutcomeDependence.NON_OVERLAPPING, OutcomeDependence.PURGED_BLOCK}
        and envelope.evaluation_role
        in {EvaluationRole.SEALED_VALIDATION, EvaluationRole.UNTOUCHED_HOLDOUT}
        and envelope.price_action == PriceActionEvidence.AS_OF_ACTION_LEDGER
    )


def _strict_forward(envelope: ValidationEvidenceEnvelope) -> bool:
    return (
        envelope.availability == AvailabilityEvidence.PROSPECTIVE_SEALED
        and envelope.universe == UniverseEvidence.PROSPECTIVE_FROZEN_UNIVERSE
        and envelope.outcome_dependence
        in {OutcomeDependence.NON_OVERLAPPING, OutcomeDependence.PURGED_BLOCK}
        and envelope.evaluation_role == EvaluationRole.PROSPECTIVE_FORWARD
        and envelope.price_action == PriceActionEvidence.AS_OF_ACTION_LEDGER
    )


def _validate_target_and_horizon(record: TargetHorizonEvidenceRecord) -> None:
    if not record.model_version:
        raise ValueError("model_version is required")
    if record.model_track == ModelTrack.TACTICAL_V22:
        if record.target not in TACTICAL_TARGETS:
            raise ValueError("Tactical record uses a Long Horizon target")
        if record.horizon_completed_sessions not in TACTICAL_HORIZONS:
            raise ValueError("Tactical horizon must be 5, 20, or 60 sessions")
    else:
        if record.target not in LONG_HORIZON_TARGETS:
            raise ValueError("Long Horizon record uses a Tactical target")
        if record.horizon_completed_sessions < LONG_HORIZON_MINIMUM_SESSIONS:
            raise ValueError("Long Horizon evidence starts at 252 sessions")


def validate_target_horizon_evidence(
    record: TargetHorizonEvidenceRecord,
) -> ClaimCeiling:
    _validate_target_and_horizon(record)
    if record.ai_may_affect_deterministic_fields:
        raise ValueError("AI cannot affect deterministic model evidence")
    if record.human_judgment_may_mutate_model_snapshot:
        raise ValueError("Human judgment must be stored separately from the model snapshot")

    ceiling = claim_ceiling(record.evidence_envelope)
    label = record.model_evidence_label
    if label in SUPPORT_LABELS:
        if record.run_status != OperationalRunStatus.COMPLETED:
            raise ValueError("A support label requires a completed operational run")
        if record.target_evidence != EvidenceComponentState.PRESENT:
            raise ValueError("A support label requires target evidence")
        if ceiling == ClaimCeiling.BLOCKED:
            raise ValueError("Blocked evidence cannot receive a support label")

    if record.target == EvidenceTarget.TACTICAL_RANKING and label in SUPPORT_LABELS:
        if record.ranking_evidence != EvidenceComponentState.PRESENT:
            raise ValueError("Tactical ranking support requires ranking evidence")
    if (
        record.target == EvidenceTarget.TACTICAL_ENTRY_DECISION
        and label in SUPPORT_LABELS
        and record.entry_decision_evidence != EvidenceComponentState.PRESENT
    ):
        raise ValueError("Entry-decision support requires separate entry evidence")

    if label == ModelEvidenceLabel.BACKTEST_SUPPORTED:
        if record.evidence_envelope.evaluation_role == EvaluationRole.PROSPECTIVE_FORWARD:
            raise ValueError("Prospective evidence cannot be labeled BACKTEST_SUPPORTED")
    elif label == ModelEvidenceLabel.PIT_SUPPORTED:
        if not _strict_pit(record.evidence_envelope):
            raise ValueError("PIT_SUPPORTED requires strict PIT historical evidence")
    elif label == ModelEvidenceLabel.FORWARD_SUPPORTED:
        if not _strict_forward(record.evidence_envelope):
            raise ValueError("FORWARD_SUPPORTED requires prospective sealed evidence")
    elif label == ModelEvidenceLabel.INVALIDATED:
        if record.run_status != OperationalRunStatus.COMPLETED:
            raise ValueError("INVALIDATED requires a completed run")
        if ceiling == ClaimCeiling.BLOCKED:
            raise ValueError("Blocked evidence cannot invalidate a model")
        if not record.adverse_evidence_predeclared:
            raise ValueError("INVALIDATED requires predeclared adverse evidence")
        if record.evidence_envelope.evaluation_role == EvaluationRole.DEVELOPMENT_OBSERVED:
            raise ValueError("Observed development evidence cannot invalidate a model")

    if (
        record.run_status
        in {
            OperationalRunStatus.BLOCKED_BY_DATA,
            OperationalRunStatus.INSUFFICIENT_EVIDENCE,
            OperationalRunStatus.FAILED,
        }
        and label != ModelEvidenceLabel.NOT_VALIDATED
    ):
        raise ValueError("An incomplete operational run must remain NOT_VALIDATED")
    return ceiling


def register_planned_retrospective(
    existing: tuple[PlannedRetrospective, ...],
    candidate: PlannedRetrospective,
) -> tuple[PlannedRetrospective, ...]:
    if (
        not candidate.model_version
        or not candidate.freeze_hash
        or not candidate.plan_hash
        or not candidate.planned_run_id
    ):
        raise ValueError("A retrospective plan requires version, hashes, and run ID")
    if candidate.observed_outcomes_used_to_choose_contract:
        raise ValueError("Observed outcomes cannot choose the frozen retrospective contract")
    same_freeze = [
        record
        for record in existing
        if (
            record.model_version,
            record.freeze_hash,
        )
        == (
            candidate.model_version,
            candidate.freeze_hash,
        )
    ]
    if not same_freeze:
        return (*existing, candidate)
    if len(same_freeze) == 1 and same_freeze[0] == candidate:
        return existing
    raise ValueError(
        "One frozen model version permits one planned retrospective; "
        "a conflicting replay requires a successor version"
    )


def validate_successor_authorization(
    authorization: SuccessorAuthorization,
) -> None:
    if authorization.predecessor_model_version == authorization.successor_model_version:
        raise ValueError("A successor requires a new model version")
    if authorization.predecessor_freeze_hash == authorization.successor_freeze_hash:
        raise ValueError("A successor requires a new freeze")
    if not authorization.evidence_reference:
        raise ValueError("A successor requires a documented evidence reference")
    if not authorization.later_window_or_prospective_evaluation_required:
        raise ValueError("A successor must use a later window or prospective evidence")


def validate_practical_value_threshold_policy(
    policy: PracticalValueThresholdPolicy,
) -> None:
    if not policy.policy_version:
        raise ValueError("Threshold policy version is required")
    if policy.applicability == ThresholdApplicability.OBSERVED_TIER1_NOT_APPLICABLE:
        if policy.numeric_thresholds:
            raise ValueError("Observed Tier-1 cannot receive post-observation thresholds")
        return
    if not policy.frozen_before_outcomes:
        raise ValueError("Forward-only practical-value thresholds must be preregistered")


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def build_policy_artifact() -> dict[str, object]:
    artifact: dict[str, object] = {
        "artifactType": "MODEL_VALIDATION_GOVERNANCE_POLICY",
        "schemaVersion": MODEL_VALIDATION_GOVERNANCE_V11,
        "effectiveDate": "2026-07-30",
        "statusAxes": {
            "operationalRunStatus": [item.value for item in OperationalRunStatus],
            "modelEvidenceLabel": [item.value for item in ModelEvidenceLabel],
            "axesMayBeConflated": False,
        },
        "claimBoundary": {
            "inheritsEvidenceEnvelopeAndClaimCeilingFrom": (
                "MODEL-VALIDATION-GOVERNANCE-v1.0.0"
            ),
            "currentUniverseDiagnosticMayBecomePitSupported": False,
            "currentUniverseDiagnosticMayBecomeForwardSupported": False,
            "strictPitEvidenceRequiredForPitSupported": True,
            "prospectiveSealedEvidenceRequiredForForwardSupported": True,
        },
        "labelGranularity": {
            "perModel": True,
            "perTarget": True,
            "perHorizon": True,
            "tacticalTargets": [item.value for item in sorted(TACTICAL_TARGETS)],
            "tacticalHorizonsCompletedSessions": sorted(TACTICAL_HORIZONS),
            "longHorizonTargets": [
                item.value for item in sorted(LONG_HORIZON_TARGETS)
            ],
            "longHorizonMinimumCompletedSessions": LONG_HORIZON_MINIMUM_SESSIONS,
        },
        "finiteEvaluation": {
            "oneFrozenVersionOnePlannedRetrospective": True,
            "exactIdempotentReplayAllowed": True,
            "conflictingReplayAllowed": False,
            "observedOutcomeTuningAllowed": False,
            "allowedSuccessorReasons": [item.value for item in SuccessorReason],
            "successorRequiresNewVersionAndFreeze": True,
            "successorRequiresLaterWindowOrProspectiveEvidence": True,
        },
        "modelBoundaries": {
            "tacticalV22OutputType": "DETERMINISTIC_ORDINAL_SCORE",
            "tacticalV22CalibratedProbabilityClaimAllowed": False,
            "futureCalibratedProbabilityRequiresSuccessorVersion": True,
            "rankingEvidenceSeparateFromEntryDecisionEvidence": True,
            "longHorizonTargetsRemainSeparate": [
                EvidenceTarget.COMPANY_QUALITY.value,
                EvidenceTarget.SECURITY_ATTRACTIVENESS.value,
                EvidenceTarget.EXPECTED_RETURN.value,
                EvidenceTarget.DOWNSIDE_RISK.value,
            ],
            "longHorizonDefaultAggregateRankAuthorized": False,
        },
        "practicalValueThresholds": {
            "observedTier1Applicability": (
                ThresholdApplicability.OBSERVED_TIER1_NOT_APPLICABLE.value
            ),
            "postObservationNumericThresholdsAllowed": False,
            "futureNumericThresholdApplicability": (
                ThresholdApplicability.FORWARD_ONLY.value
            ),
            "futureThresholdsMustBeFrozenBeforeOutcomes": True,
        },
        "evidenceBoundaries": {
            "missingStatesRemainExplicit": [
                "MISSING",
                "STALE",
                "INVALID",
                "NOT_APPLICABLE",
                "EXCLUDED",
                "ABSTAIN",
                "WATCH_ONLY",
            ],
            "missingMayBecomeZeroOrNeutral": False,
            "aiMayAffectDeterministicFields": False,
            "humanJudgmentStoredSeparately": True,
            "humanJudgmentMayMutateModelSnapshot": False,
        },
        "executionBoundary": {
            "networkRequestsExecuted": False,
            "scoringExecuted": False,
            "databaseWritten": False,
            "existingGovernanceV1Modified": False,
        },
    }
    artifact["artifactContentHash"] = _canonical_hash(artifact)
    return artifact


def _write_immutable(path: Path, payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise FileExistsError(f"Refusing to overwrite immutable artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    _write_immutable(args.output, build_policy_artifact())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
