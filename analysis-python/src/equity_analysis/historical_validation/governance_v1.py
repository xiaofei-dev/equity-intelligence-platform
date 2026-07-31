from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum

MODEL_VALIDATION_GOVERNANCE_VERSION = "MODEL-VALIDATION-GOVERNANCE-v1.0.0"

_SHA256_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")


class AvailabilityEvidence(StrEnum):
    PROSPECTIVE_SEALED = "PROSPECTIVE_SEALED"
    PIT_VERIFIED = "PIT_VERIFIED"
    CONSERVATIVE_LAG_CURRENT_REVISION = "CONSERVATIVE_LAG_CURRENT_REVISION"
    CURRENT_REVISION_RETROSPECTIVE = "CURRENT_REVISION_RETROSPECTIVE"
    UNPROVEN = "UNPROVEN"


class UniverseEvidence(StrEnum):
    HISTORICAL_MEMBERSHIP = "HISTORICAL_MEMBERSHIP"
    PROSPECTIVE_FROZEN_UNIVERSE = "PROSPECTIVE_FROZEN_UNIVERSE"
    CURRENT_UNIVERSE_RETROSPECTIVE = "CURRENT_UNIVERSE_RETROSPECTIVE"
    UNPROVEN = "UNPROVEN"


class OutcomeDependence(StrEnum):
    NON_OVERLAPPING = "NON_OVERLAPPING"
    PURGED_BLOCK = "PURGED_BLOCK"
    OVERLAPPING_DIAGNOSTIC = "OVERLAPPING_DIAGNOSTIC"


class EvaluationRole(StrEnum):
    DEVELOPMENT_OBSERVED = "DEVELOPMENT_OBSERVED"
    WALK_FORWARD_OUTER_FOLD = "WALK_FORWARD_OUTER_FOLD"
    SEALED_VALIDATION = "SEALED_VALIDATION"
    UNTOUCHED_HOLDOUT = "UNTOUCHED_HOLDOUT"
    PROSPECTIVE_FORWARD = "PROSPECTIVE_FORWARD"


class PriceActionEvidence(StrEnum):
    AS_OF_ACTION_LEDGER = "AS_OF_ACTION_LEDGER"
    EX_POST_TOTAL_RETURN_ADJUSTED = "EX_POST_TOTAL_RETURN_ADJUSTED"
    UNPROVEN = "UNPROVEN"


class ClaimCeiling(StrEnum):
    BLOCKED = "BLOCKED"
    DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
    PROVISIONAL_ONLY = "PROVISIONAL_ONLY"
    VALIDATION_ELIGIBLE = "VALIDATION_ELIGIBLE"


class ValidationTerminalStatus(StrEnum):
    VALIDATED = "VALIDATED"
    PROVISIONALLY_VALIDATED = "PROVISIONALLY_VALIDATED"
    MIXED = "MIXED"
    NOT_VALIDATED = "NOT_VALIDATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    BLOCKED_BY_DATA = "BLOCKED_BY_DATA"


@dataclass(frozen=True)
class ValidationEvidenceEnvelope:
    availability: AvailabilityEvidence
    universe: UniverseEvidence
    outcome_dependence: OutcomeDependence
    evaluation_role: EvaluationRole
    price_action: PriceActionEvidence


@dataclass(frozen=True)
class ModelFreezeRecord:
    model_version: str
    validation_protocol_version: str
    frozen_at: datetime
    observed_evidence_cutoff: datetime
    formulas_hash: str
    weights_hash: str
    input_schema_hash: str
    applicability_hash: str
    missing_data_policy_hash: str
    benchmark_contract_hash: str
    cost_model_hash: str
    universe_hash: str
    sampling_hash: str
    acceptance_threshold_hash: str
    source_artifact_hashes: tuple[str, ...]
    random_seed: int
    maximum_horizon_sessions: int
    purge_sessions: int
    embargo_sessions: int
    version: str = MODEL_VALIDATION_GOVERNANCE_VERSION


def _require_sha256(value: str, field_name: str) -> None:
    if not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be a SHA-256 value")


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def freeze_payload(record: ModelFreezeRecord) -> dict[str, object]:
    if not record.model_version or not record.validation_protocol_version:
        raise ValueError("Model and validation protocol versions are required")
    if record.frozen_at.tzinfo is None or record.observed_evidence_cutoff.tzinfo is None:
        raise ValueError("Freeze timestamps must be timezone-aware")
    if record.observed_evidence_cutoff > record.frozen_at:
        raise ValueError("Observed evidence cutoff cannot follow the freeze time")
    if record.random_seed < 0:
        raise ValueError("Random seed cannot be negative")
    if record.maximum_horizon_sessions < 1:
        raise ValueError("Maximum horizon must be positive")
    if record.purge_sessions < record.maximum_horizon_sessions:
        raise ValueError("Purge must cover the maximum evaluated horizon")
    if record.embargo_sessions < record.maximum_horizon_sessions:
        raise ValueError("Embargo must cover the maximum evaluated horizon")

    hash_fields = {
        "formulas_hash": record.formulas_hash,
        "weights_hash": record.weights_hash,
        "input_schema_hash": record.input_schema_hash,
        "applicability_hash": record.applicability_hash,
        "missing_data_policy_hash": record.missing_data_policy_hash,
        "benchmark_contract_hash": record.benchmark_contract_hash,
        "cost_model_hash": record.cost_model_hash,
        "universe_hash": record.universe_hash,
        "sampling_hash": record.sampling_hash,
        "acceptance_threshold_hash": record.acceptance_threshold_hash,
    }
    for field_name, value in hash_fields.items():
        _require_sha256(value, field_name)
    if not record.source_artifact_hashes:
        raise ValueError("At least one source artifact hash is required")
    for value in record.source_artifact_hashes:
        _require_sha256(value, "source_artifact_hash")

    payload = asdict(record)
    payload["frozen_at"] = record.frozen_at.isoformat()
    payload["observed_evidence_cutoff"] = (
        record.observed_evidence_cutoff.isoformat()
    )
    payload["source_artifact_hashes"] = list(record.source_artifact_hashes)
    return payload


def freeze_hash(record: ModelFreezeRecord) -> str:
    return hashlib.sha256(
        _canonical_json(freeze_payload(record)).encode("utf-8")
    ).hexdigest().upper()


def claim_ceiling(evidence: ValidationEvidenceEnvelope) -> ClaimCeiling:
    if (
        evidence.availability == AvailabilityEvidence.UNPROVEN
        or evidence.universe == UniverseEvidence.UNPROVEN
        or evidence.price_action == PriceActionEvidence.UNPROVEN
    ):
        return ClaimCeiling.BLOCKED

    if (
        evidence.evaluation_role == EvaluationRole.DEVELOPMENT_OBSERVED
        or evidence.outcome_dependence == OutcomeDependence.OVERLAPPING_DIAGNOSTIC
        or evidence.price_action
        == PriceActionEvidence.EX_POST_TOTAL_RETURN_ADJUSTED
        or evidence.availability
        == AvailabilityEvidence.CURRENT_REVISION_RETROSPECTIVE
    ):
        return ClaimCeiling.DIAGNOSTIC_ONLY

    strict_historical = (
        evidence.availability == AvailabilityEvidence.PIT_VERIFIED
        and evidence.universe == UniverseEvidence.HISTORICAL_MEMBERSHIP
        and evidence.price_action == PriceActionEvidence.AS_OF_ACTION_LEDGER
        and evidence.evaluation_role
        in {EvaluationRole.SEALED_VALIDATION, EvaluationRole.UNTOUCHED_HOLDOUT}
        and evidence.outcome_dependence
        in {OutcomeDependence.NON_OVERLAPPING, OutcomeDependence.PURGED_BLOCK}
    )
    strict_prospective = (
        evidence.availability == AvailabilityEvidence.PROSPECTIVE_SEALED
        and evidence.universe == UniverseEvidence.PROSPECTIVE_FROZEN_UNIVERSE
        and evidence.price_action == PriceActionEvidence.AS_OF_ACTION_LEDGER
        and evidence.evaluation_role == EvaluationRole.PROSPECTIVE_FORWARD
        and evidence.outcome_dependence
        in {OutcomeDependence.NON_OVERLAPPING, OutcomeDependence.PURGED_BLOCK}
    )
    if strict_historical or strict_prospective:
        return ClaimCeiling.VALIDATION_ELIGIBLE
    return ClaimCeiling.PROVISIONAL_ONLY


def validate_terminal_status(
    status: ValidationTerminalStatus,
    ceiling: ClaimCeiling,
) -> None:
    if status == ValidationTerminalStatus.VALIDATED:
        if ceiling != ClaimCeiling.VALIDATION_ELIGIBLE:
            raise ValueError("VALIDATED exceeds the evidence claim ceiling")
        return
    if status == ValidationTerminalStatus.PROVISIONALLY_VALIDATED:
        if ceiling not in {
            ClaimCeiling.PROVISIONAL_ONLY,
            ClaimCeiling.VALIDATION_ELIGIBLE,
        }:
            raise ValueError(
                "PROVISIONALLY_VALIDATED exceeds the evidence claim ceiling"
            )
        return
    if ceiling == ClaimCeiling.BLOCKED and status not in {
        ValidationTerminalStatus.BLOCKED_BY_DATA,
        ValidationTerminalStatus.INSUFFICIENT_EVIDENCE,
        ValidationTerminalStatus.NOT_VALIDATED,
    }:
        raise ValueError("Unproven evidence requires a blocked or adverse status")


def validate_complete_population(
    universe_security_ids: tuple[str, ...],
    terminal_states: Mapping[str, str],
) -> None:
    if not universe_security_ids:
        raise ValueError("Validation universe cannot be empty")
    if len(set(universe_security_ids)) != len(universe_security_ids):
        raise ValueError("Validation universe contains duplicate security IDs")
    if any(not value for value in universe_security_ids):
        raise ValueError("Validation universe contains an empty security ID")
    expected = set(universe_security_ids)
    actual = set(terminal_states)
    if expected != actual:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(
            "Terminal population does not match the frozen universe: "
            f"missing={missing}, unexpected={unexpected}"
        )
    if any(not state for state in terminal_states.values()):
        raise ValueError("Every frozen security requires an explicit terminal state")


def validate_formal_outcome_dependence(
    outcome_dependence: OutcomeDependence,
) -> None:
    if outcome_dependence == OutcomeDependence.OVERLAPPING_DIAGNOSTIC:
        raise ValueError(
            "Overlapping outcomes and ordinary IID bootstrap intervals are "
            "diagnostic only and cannot enter a formal acceptance gate"
        )
