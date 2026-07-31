from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from equity_analysis.historical_validation.governance_v1 import (
    AvailabilityEvidence,
    ClaimCeiling,
    EvaluationRole,
    ModelFreezeRecord,
    OutcomeDependence,
    PriceActionEvidence,
    UniverseEvidence,
    ValidationEvidenceEnvelope,
    ValidationTerminalStatus,
    claim_ceiling,
    freeze_hash,
    validate_complete_population,
    validate_formal_outcome_dependence,
    validate_terminal_status,
)

HASH_A = "A" * 64
HASH_B = "B" * 64


def _freeze(**overrides) -> ModelFreezeRecord:
    values = {
        "model_version": "TACTICAL-SIGNAL-v2.2.0",
        "validation_protocol_version": "MODEL-VALIDATION-GOVERNANCE-v1.0.0",
        "frozen_at": datetime(2026, 7, 29, 20, 0, tzinfo=UTC),
        "observed_evidence_cutoff": datetime(2026, 7, 29, 19, 0, tzinfo=UTC),
        "formulas_hash": HASH_A,
        "weights_hash": HASH_A,
        "input_schema_hash": HASH_A,
        "applicability_hash": HASH_A,
        "missing_data_policy_hash": HASH_A,
        "benchmark_contract_hash": HASH_A,
        "cost_model_hash": HASH_A,
        "universe_hash": HASH_A,
        "sampling_hash": HASH_A,
        "acceptance_threshold_hash": HASH_A,
        "source_artifact_hashes": (HASH_B,),
        "random_seed": 20260729,
        "maximum_horizon_sessions": 60,
        "purge_sessions": 60,
        "embargo_sessions": 60,
    }
    values.update(overrides)
    return ModelFreezeRecord(**values)


def test_freeze_hash_is_deterministic_and_binds_contract() -> None:
    first = freeze_hash(_freeze())
    assert first == freeze_hash(_freeze())
    assert first != freeze_hash(_freeze(random_seed=20260730))


def test_freeze_requires_purge_and_embargo_for_maximum_horizon() -> None:
    with pytest.raises(ValueError, match="Purge"):
        freeze_hash(_freeze(purge_sessions=59))
    with pytest.raises(ValueError, match="Embargo"):
        freeze_hash(_freeze(embargo_sessions=59))


def test_observed_history_is_diagnostic_only() -> None:
    evidence = ValidationEvidenceEnvelope(
        availability=AvailabilityEvidence.PIT_VERIFIED,
        universe=UniverseEvidence.HISTORICAL_MEMBERSHIP,
        outcome_dependence=OutcomeDependence.NON_OVERLAPPING,
        evaluation_role=EvaluationRole.DEVELOPMENT_OBSERVED,
        price_action=PriceActionEvidence.AS_OF_ACTION_LEDGER,
    )
    ceiling = claim_ceiling(evidence)
    assert ceiling == ClaimCeiling.DIAGNOSTIC_ONLY
    with pytest.raises(ValueError, match="exceeds"):
        validate_terminal_status(
            ValidationTerminalStatus.PROVISIONALLY_VALIDATED,
            ceiling,
        )


def test_retrospective_current_revision_cannot_validate() -> None:
    evidence = ValidationEvidenceEnvelope(
        availability=AvailabilityEvidence.CURRENT_REVISION_RETROSPECTIVE,
        universe=UniverseEvidence.CURRENT_UNIVERSE_RETROSPECTIVE,
        outcome_dependence=OutcomeDependence.PURGED_BLOCK,
        evaluation_role=EvaluationRole.WALK_FORWARD_OUTER_FOLD,
        price_action=PriceActionEvidence.AS_OF_ACTION_LEDGER,
    )
    ceiling = claim_ceiling(evidence)
    assert ceiling == ClaimCeiling.DIAGNOSTIC_ONLY
    with pytest.raises(ValueError, match="VALIDATED"):
        validate_terminal_status(ValidationTerminalStatus.VALIDATED, ceiling)


def test_strict_prospective_evidence_is_validation_eligible() -> None:
    evidence = ValidationEvidenceEnvelope(
        availability=AvailabilityEvidence.PROSPECTIVE_SEALED,
        universe=UniverseEvidence.PROSPECTIVE_FROZEN_UNIVERSE,
        outcome_dependence=OutcomeDependence.PURGED_BLOCK,
        evaluation_role=EvaluationRole.PROSPECTIVE_FORWARD,
        price_action=PriceActionEvidence.AS_OF_ACTION_LEDGER,
    )
    ceiling = claim_ceiling(evidence)
    assert ceiling == ClaimCeiling.VALIDATION_ELIGIBLE
    validate_terminal_status(ValidationTerminalStatus.VALIDATED, ceiling)


def test_unproven_dimension_blocks_positive_claim() -> None:
    evidence = ValidationEvidenceEnvelope(
        availability=AvailabilityEvidence.UNPROVEN,
        universe=UniverseEvidence.PROSPECTIVE_FROZEN_UNIVERSE,
        outcome_dependence=OutcomeDependence.NON_OVERLAPPING,
        evaluation_role=EvaluationRole.PROSPECTIVE_FORWARD,
        price_action=PriceActionEvidence.AS_OF_ACTION_LEDGER,
    )
    ceiling = claim_ceiling(evidence)
    assert ceiling == ClaimCeiling.BLOCKED
    validate_terminal_status(ValidationTerminalStatus.BLOCKED_BY_DATA, ceiling)
    with pytest.raises(ValueError, match="exceeds"):
        validate_terminal_status(
            ValidationTerminalStatus.PROVISIONALLY_VALIDATED,
            ceiling,
        )


def test_complete_population_requires_every_frozen_security_terminal_state() -> None:
    validate_complete_population(
        ("security-a", "security-b"),
        {"security-a": "ASSESSED", "security-b": "MISSING"},
    )
    with pytest.raises(ValueError, match="missing"):
        validate_complete_population(
            ("security-a", "security-b"),
            {"security-a": "ASSESSED"},
        )


def test_overlapping_outcomes_cannot_enter_formal_gate() -> None:
    with pytest.raises(ValueError, match="diagnostic only"):
        validate_formal_outcome_dependence(
            OutcomeDependence.OVERLAPPING_DIAGNOSTIC
        )
    validate_formal_outcome_dependence(OutcomeDependence.PURGED_BLOCK)


def test_git_safe_governance_artifact_hash_and_boundaries() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    artifact_path = (
        repository_root / "docs" / "generated" / "model-validation-governance-v1.json"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    expected = artifact.pop("artifactContentHash")
    canonical = json.dumps(
        artifact,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper() == expected
    assert artifact["observedHistoricalEvidence"]["untouchedHoldoutAvailable"] is False
    assert (
        artifact["freezeRequirements"][
            "ordinaryIidBootstrapOnOverlappingOutcomesFormal"
        ]
        is False
    )
    assert artifact["forwardBoundary"]["existingForwardV1RemainsImmutable"] is True
