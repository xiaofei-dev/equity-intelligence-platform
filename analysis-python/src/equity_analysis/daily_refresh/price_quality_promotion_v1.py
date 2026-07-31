from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from equity_analysis.daily_refresh.evidence_validation_v1 import (
    DailyPriceSeriesEvidence,
    EvidenceReason,
    EvidenceValidationState,
    canonical_content_hash,
    validate_daily_price_series,
)

PRICE_QUALITY_PROMOTION_POLICY_VERSION = "PRICE-QUALITY-PROMOTION-v1.0.0"
NEW_VALIDATED_PRICE_REVISION_BINDING_VERSION = (
    "NEW-VALIDATED-PRICE-REVISION-BINDING-v1.0.0"
)
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


class PromotionState(StrEnum):
    AUTHORIZED_NEW_REVISION = "AUTHORIZED_NEW_REVISION"
    BLOCKED = "BLOCKED"


class PromotionScopeMode(StrEnum):
    COMPLETE_POPULATION_COMMON_CUTOFF = "COMPLETE_POPULATION_COMMON_CUTOFF"
    PER_SECURITY = "PER_SECURITY"


class ReconciliationState(StrEnum):
    RECONCILED = "RECONCILED"
    MISSING = "MISSING"
    CONFLICT = "CONFLICT"


class PromotionReason(StrEnum):
    OHLCV_VALIDATION_BLOCKED = "OHLCV_VALIDATION_BLOCKED"
    SOURCE_STATUS_NOT_PROVISIONAL = "SOURCE_STATUS_NOT_PROVISIONAL"
    COMPLETED_SESSION_CALENDAR_INVALID = "COMPLETED_SESSION_CALENDAR_INVALID"
    COMPLETED_SESSION_CALENDAR_MISMATCH = "COMPLETED_SESSION_CALENDAR_MISMATCH"
    PROMOTION_SCOPE_INVALID = "PROMOTION_SCOPE_INVALID"
    POPULATION_COVERAGE_HASH_INVALID = "POPULATION_COVERAGE_HASH_INVALID"
    TRANSPORT_SOURCE_LINEAGE_INVALID = "TRANSPORT_SOURCE_LINEAGE_INVALID"
    SOURCE_MANIFEST_MISMATCH = "SOURCE_MANIFEST_MISMATCH"
    CORPORATE_ACTION_RECONCILIATION_MISSING = (
        "CORPORATE_ACTION_RECONCILIATION_MISSING"
    )
    ADJUSTMENT_RECONCILIATION_MISSING = "ADJUSTMENT_RECONCILIATION_MISSING"
    REVISION_SELECTION_PROOF_INVALID = "REVISION_SELECTION_PROOF_INVALID"
    PROMOTION_POLICY_BINDING_INVALID = "PROMOTION_POLICY_BINDING_INVALID"
    REVIEW_CUTOFF_INVALID = "REVIEW_CUTOFF_INVALID"
    REVIEWER_MISSING = "REVIEWER_MISSING"


_PROMOTION_POLICY_PAYLOAD = {
    "policyVersion": PRICE_QUALITY_PROMOTION_POLICY_VERSION,
    "sourceStatus": "PROVISIONAL_ONLY",
    "mutationAllowed": False,
    "output": "NEW_VALIDATED_REVISION_ONLY",
    "requiredEvidence": (
        "COMPLETED_SESSION_CALENDAR",
        "POPULATION_OR_PER_SECURITY_COVERAGE",
        "TRANSPORT_AND_SOURCE_HASHES",
        "CORPORATE_ACTION_RECONCILIATION",
        "ADJUSTMENT_RECONCILIATION",
        "LATEST_REVISION_AT_CUTOFF",
        "OHLCV_STRUCTURAL_VALIDATION",
        "REVIEWED_CUTOFF",
    ),
}
PRICE_QUALITY_PROMOTION_POLICY_HASH = canonical_content_hash(
    _PROMOTION_POLICY_PAYLOAD
)


@dataclass(frozen=True)
class CompletedSessionCalendarEvidence:
    authority: str
    calendar_version: str
    completed_session: date
    source_content_hash: str
    reviewed_at: datetime
    evidence_hash: str


@dataclass(frozen=True)
class PromotionCoverageEvidence:
    scope_mode: PromotionScopeMode
    frozen_population_hash: str
    population_size: int
    covered_security_ids: tuple[str, ...]
    common_cutoff: datetime | None
    coverage_hash: str


@dataclass(frozen=True)
class PriceQualityPromotionEvidence:
    series: DailyPriceSeriesEvidence
    reviewed_cutoff: datetime
    reviewer: str
    calendar: CompletedSessionCalendarEvidence
    coverage: PromotionCoverageEvidence
    transport_manifest_hash: str
    transport_content_hashes: tuple[str, ...]
    source_manifest_hash: str
    source_content_hashes: tuple[str, ...]
    corporate_action_state: ReconciliationState
    corporate_action_reconciliation_hash: str | None
    adjustment_state: ReconciliationState
    adjustment_reconciliation_hash: str | None
    revision_selection_manifest_hash: str
    promotion_policy_version: str
    promotion_policy_hash: str


@dataclass(frozen=True)
class SessionRevisionBinding:
    trading_date: date
    prior_revision_number: int
    minimum_new_revision_number: int
    prior_source_record_id: str
    prior_source_content_hash: str


@dataclass(frozen=True)
class NewValidatedPriceRevisionBinding:
    binding_version: str
    security_id: str
    expected_completed_session: date
    prior_quality_status: str
    new_quality_status: str
    minimum_new_revision_number: int
    session_revision_bindings: tuple[SessionRevisionBinding, ...]
    prior_evidence_content_hash: str
    promotion_evidence_hash: str
    promotion_policy_version: str
    promotion_policy_hash: str
    reviewed_cutoff: datetime
    may_mutate_existing_evidence: bool
    binding_content_hash: str


@dataclass(frozen=True)
class PriceQualityPromotionDecision:
    policy_version: str
    policy_hash: str
    state: PromotionState
    reason_codes: tuple[PromotionReason, ...]
    security_id: str
    prior_quality_statuses: tuple[str, ...]
    reviewed_cutoff: datetime
    structural_validation_decision_hash: str
    structural_validation_passed: bool
    promotion_evidence_hash: str
    new_revision_binding: NewValidatedPriceRevisionBinding | None
    may_mutate_existing_evidence: bool
    decision_content_hash: str


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _valid_hash(value: str | None) -> bool:
    return value is not None and _SHA256_PATTERN.fullmatch(value) is not None


def _ordered_reasons(reasons: set[PromotionReason]) -> tuple[PromotionReason, ...]:
    return tuple(sorted(reasons, key=lambda item: item.value))


def build_completed_session_calendar_evidence_hash(
    *,
    authority: str,
    calendar_version: str,
    completed_session: date,
    source_content_hash: str,
    reviewed_at: datetime,
) -> str:
    return canonical_content_hash(
        {
            "authority": authority,
            "calendarVersion": calendar_version,
            "completedSession": completed_session,
            "sourceContentHash": source_content_hash,
            "reviewedAt": reviewed_at,
        }
    )


def build_population_coverage_hash(
    *,
    scope_mode: PromotionScopeMode,
    frozen_population_hash: str,
    population_size: int,
    covered_security_ids: tuple[str, ...],
    common_cutoff: datetime | None,
) -> str:
    return canonical_content_hash(
        {
            "scopeMode": scope_mode,
            "frozenPopulationHash": frozen_population_hash,
            "populationSize": population_size,
            "coveredSecurityIds": tuple(sorted(covered_security_ids)),
            "commonCutoff": common_cutoff,
        }
    )


def build_transport_manifest_hash(
    *,
    security_id: str,
    reviewed_cutoff: datetime,
    transport_content_hashes: tuple[str, ...],
) -> str:
    return canonical_content_hash(
        {
            "securityId": security_id,
            "reviewedCutoff": reviewed_cutoff,
            "transportContentHashes": tuple(sorted(transport_content_hashes)),
        }
    )


def build_source_manifest_hash(
    *,
    security_id: str,
    expected_completed_session: date,
    source_content_hashes: tuple[str, ...],
) -> str:
    return canonical_content_hash(
        {
            "securityId": security_id,
            "expectedCompletedSession": expected_completed_session,
            "sourceContentHashes": tuple(sorted(source_content_hashes)),
        }
    )


def build_revision_selection_manifest_hash(
    *,
    series: DailyPriceSeriesEvidence,
    reviewed_cutoff: datetime,
) -> str:
    return canonical_content_hash(
        {
            "securityId": series.security_id,
            "reviewedCutoff": reviewed_cutoff,
            "revisions": tuple(
                {
                    "tradingDate": item.trading_date,
                    "revisionNumber": item.revision_number,
                    "sourceRecordId": item.source_record_id,
                    "sourceContentHash": item.source_content_hash,
                    "selectedLatestAtCutoff": (
                        item.selected_revision_is_latest_at_cutoff
                    ),
                }
                for item in series.bars
            ),
        }
    )


def _promotion_evidence_hash(
    evidence: PriceQualityPromotionEvidence,
    *,
    prior_evidence_hash: str | None,
    structural_decision_hash: str,
) -> str:
    return canonical_content_hash(
        {
            "policyVersion": evidence.promotion_policy_version,
            "policyHash": evidence.promotion_policy_hash,
            "securityId": evidence.series.security_id,
            "reviewedCutoff": evidence.reviewed_cutoff,
            "reviewer": evidence.reviewer,
            "priorEvidenceHash": prior_evidence_hash,
            "structuralValidationDecisionHash": structural_decision_hash,
            "calendar": evidence.calendar,
            "coverage": evidence.coverage,
            "transportManifestHash": evidence.transport_manifest_hash,
            "transportContentHashes": tuple(
                sorted(evidence.transport_content_hashes)
            ),
            "sourceManifestHash": evidence.source_manifest_hash,
            "sourceContentHashes": tuple(sorted(evidence.source_content_hashes)),
            "corporateActionState": evidence.corporate_action_state,
            "corporateActionReconciliationHash": (
                evidence.corporate_action_reconciliation_hash
            ),
            "adjustmentState": evidence.adjustment_state,
            "adjustmentReconciliationHash": evidence.adjustment_reconciliation_hash,
            "revisionSelectionManifestHash": (
                evidence.revision_selection_manifest_hash
            ),
        }
    )


def _new_revision_binding(
    evidence: PriceQualityPromotionEvidence,
    *,
    prior_evidence_hash: str,
    promotion_evidence_hash: str,
) -> NewValidatedPriceRevisionBinding:
    session_bindings = tuple(
        SessionRevisionBinding(
            trading_date=item.trading_date,
            prior_revision_number=item.revision_number,
            minimum_new_revision_number=item.revision_number + 1,
            prior_source_record_id=item.source_record_id,
            prior_source_content_hash=item.source_content_hash,
        )
        for item in evidence.series.bars
    )
    payload = {
        "bindingVersion": NEW_VALIDATED_PRICE_REVISION_BINDING_VERSION,
        "securityId": evidence.series.security_id,
        "expectedCompletedSession": evidence.series.expected_completed_session,
        "priorQualityStatus": "PROVISIONAL",
        "newQualityStatus": EvidenceValidationState.VALIDATED.value,
        "minimumNewRevisionNumber": (
            max(item.revision_number for item in evidence.series.bars) + 1
        ),
        "sessionRevisionBindings": session_bindings,
        "priorEvidenceContentHash": prior_evidence_hash,
        "promotionEvidenceHash": promotion_evidence_hash,
        "promotionPolicyVersion": evidence.promotion_policy_version,
        "promotionPolicyHash": evidence.promotion_policy_hash,
        "reviewedCutoff": evidence.reviewed_cutoff,
        "mayMutateExistingEvidence": False,
    }
    return NewValidatedPriceRevisionBinding(
        binding_version=NEW_VALIDATED_PRICE_REVISION_BINDING_VERSION,
        security_id=evidence.series.security_id,
        expected_completed_session=evidence.series.expected_completed_session,
        prior_quality_status="PROVISIONAL",
        new_quality_status=EvidenceValidationState.VALIDATED.value,
        minimum_new_revision_number=payload["minimumNewRevisionNumber"],
        session_revision_bindings=session_bindings,
        prior_evidence_content_hash=prior_evidence_hash,
        promotion_evidence_hash=promotion_evidence_hash,
        promotion_policy_version=evidence.promotion_policy_version,
        promotion_policy_hash=evidence.promotion_policy_hash,
        reviewed_cutoff=evidence.reviewed_cutoff,
        may_mutate_existing_evidence=False,
        binding_content_hash=canonical_content_hash(payload),
    )


def evaluate_price_quality_promotion(
    evidence: PriceQualityPromotionEvidence,
) -> PriceQualityPromotionDecision:
    """Authorize only a new VALIDATED revision; never relabel the prior rows."""

    if not _aware(evidence.reviewed_cutoff):
        raise ValueError("Promotion reviewed_cutoff must be timezone-aware")

    base = validate_daily_price_series(
        evidence.series,
        cutoff=evidence.reviewed_cutoff,
    )
    quality_only_blocker = base.reason_codes == (
        EvidenceReason.PRICE_QUALITY_STATUS_NOT_VALIDATED,
    )
    reasons: set[PromotionReason] = set()
    prior_statuses = base.source_quality_statuses
    if not quality_only_blocker:
        reasons.add(PromotionReason.OHLCV_VALIDATION_BLOCKED)
    if prior_statuses != ("PROVISIONAL",):
        reasons.add(PromotionReason.SOURCE_STATUS_NOT_PROVISIONAL)

    calendar = evidence.calendar
    expected_calendar_hash = build_completed_session_calendar_evidence_hash(
        authority=calendar.authority,
        calendar_version=calendar.calendar_version,
        completed_session=calendar.completed_session,
        source_content_hash=calendar.source_content_hash,
        reviewed_at=calendar.reviewed_at,
    )
    if (
        not calendar.authority.strip()
        or not calendar.calendar_version.strip()
        or not _valid_hash(calendar.source_content_hash)
        or not _aware(calendar.reviewed_at)
        or calendar.reviewed_at > evidence.reviewed_cutoff
        or calendar.evidence_hash != expected_calendar_hash
    ):
        reasons.add(PromotionReason.COMPLETED_SESSION_CALENDAR_INVALID)
    if calendar.completed_session != evidence.series.expected_completed_session:
        reasons.add(PromotionReason.COMPLETED_SESSION_CALENDAR_MISMATCH)

    coverage = evidence.coverage
    expected_coverage_hash = build_population_coverage_hash(
        scope_mode=coverage.scope_mode,
        frozen_population_hash=coverage.frozen_population_hash,
        population_size=coverage.population_size,
        covered_security_ids=coverage.covered_security_ids,
        common_cutoff=coverage.common_cutoff,
    )
    unique_ids = set(coverage.covered_security_ids)
    scope_valid = (
        coverage.population_size > 0
        and len(unique_ids) == len(coverage.covered_security_ids)
        and evidence.series.security_id in unique_ids
    )
    if coverage.scope_mode == PromotionScopeMode.COMPLETE_POPULATION_COMMON_CUTOFF:
        scope_valid = (
            scope_valid
            and len(unique_ids) == coverage.population_size
            and coverage.common_cutoff == evidence.reviewed_cutoff
        )
    elif coverage.scope_mode == PromotionScopeMode.PER_SECURITY:
        scope_valid = (
            scope_valid
            and unique_ids == {evidence.series.security_id}
            and coverage.common_cutoff is None
        )
    if not scope_valid or not _valid_hash(coverage.frozen_population_hash):
        reasons.add(PromotionReason.PROMOTION_SCOPE_INVALID)
    if coverage.coverage_hash != expected_coverage_hash:
        reasons.add(PromotionReason.POPULATION_COVERAGE_HASH_INVALID)

    source_hashes = tuple(
        sorted({item.source_content_hash for item in evidence.series.bars})
    )
    expected_transport_manifest_hash = build_transport_manifest_hash(
        security_id=evidence.series.security_id,
        reviewed_cutoff=evidence.reviewed_cutoff,
        transport_content_hashes=evidence.transport_content_hashes,
    )
    expected_source_manifest_hash = build_source_manifest_hash(
        security_id=evidence.series.security_id,
        expected_completed_session=evidence.series.expected_completed_session,
        source_content_hashes=evidence.source_content_hashes,
    )
    if (
        not evidence.transport_content_hashes
        or any(
            not _valid_hash(item) for item in evidence.transport_content_hashes
        )
        or evidence.transport_manifest_hash != expected_transport_manifest_hash
        or not _valid_hash(evidence.transport_manifest_hash)
        or not _valid_hash(evidence.source_manifest_hash)
        or not evidence.source_content_hashes
        or any(not _valid_hash(item) for item in evidence.source_content_hashes)
    ):
        reasons.add(PromotionReason.TRANSPORT_SOURCE_LINEAGE_INVALID)
    if (
        tuple(sorted(set(evidence.source_content_hashes))) != source_hashes
        or evidence.source_manifest_hash != expected_source_manifest_hash
    ):
        reasons.add(PromotionReason.SOURCE_MANIFEST_MISMATCH)

    if (
        evidence.corporate_action_state != ReconciliationState.RECONCILED
        or not _valid_hash(evidence.corporate_action_reconciliation_hash)
    ):
        reasons.add(PromotionReason.CORPORATE_ACTION_RECONCILIATION_MISSING)
    if (
        evidence.adjustment_state != ReconciliationState.RECONCILED
        or not _valid_hash(evidence.adjustment_reconciliation_hash)
    ):
        reasons.add(PromotionReason.ADJUSTMENT_RECONCILIATION_MISSING)
    expected_revision_selection_hash = build_revision_selection_manifest_hash(
        series=evidence.series,
        reviewed_cutoff=evidence.reviewed_cutoff,
    )
    if (
        evidence.revision_selection_manifest_hash
        != expected_revision_selection_hash
        or not _valid_hash(evidence.revision_selection_manifest_hash)
        or any(
            not item.selected_revision_is_latest_at_cutoff
            for item in evidence.series.bars
        )
    ):
        reasons.add(PromotionReason.REVISION_SELECTION_PROOF_INVALID)
    if (
        evidence.promotion_policy_version
        != PRICE_QUALITY_PROMOTION_POLICY_VERSION
        or evidence.promotion_policy_hash != PRICE_QUALITY_PROMOTION_POLICY_HASH
    ):
        reasons.add(PromotionReason.PROMOTION_POLICY_BINDING_INVALID)
    if (
        any(item.available_at > evidence.reviewed_cutoff for item in evidence.series.bars)
        or any(item.ingested_at > evidence.reviewed_cutoff for item in evidence.series.bars)
    ):
        reasons.add(PromotionReason.REVIEW_CUTOFF_INVALID)
    if not evidence.reviewer.strip():
        reasons.add(PromotionReason.REVIEWER_MISSING)

    promotion_evidence_hash = _promotion_evidence_hash(
        evidence,
        prior_evidence_hash=base.evidence_content_hash,
        structural_decision_hash=base.decision_content_hash,
    )
    state = (
        PromotionState.BLOCKED
        if reasons
        else PromotionState.AUTHORIZED_NEW_REVISION
    )
    binding = (
        _new_revision_binding(
            evidence,
            prior_evidence_hash=base.evidence_content_hash,
            promotion_evidence_hash=promotion_evidence_hash,
        )
        if state == PromotionState.AUTHORIZED_NEW_REVISION
        and base.evidence_content_hash is not None
        else None
    )
    payload = {
        "policyVersion": PRICE_QUALITY_PROMOTION_POLICY_VERSION,
        "policyHash": PRICE_QUALITY_PROMOTION_POLICY_HASH,
        "state": state,
        "reasonCodes": _ordered_reasons(reasons),
        "securityId": evidence.series.security_id,
        "priorQualityStatuses": prior_statuses,
        "reviewedCutoff": evidence.reviewed_cutoff,
        "structuralValidationDecisionHash": base.decision_content_hash,
        "structuralValidationPassed": quality_only_blocker,
        "promotionEvidenceHash": promotion_evidence_hash,
        "newRevisionBinding": binding,
        "mayMutateExistingEvidence": False,
    }
    return PriceQualityPromotionDecision(
        policy_version=PRICE_QUALITY_PROMOTION_POLICY_VERSION,
        policy_hash=PRICE_QUALITY_PROMOTION_POLICY_HASH,
        state=state,
        reason_codes=_ordered_reasons(reasons),
        security_id=evidence.series.security_id,
        prior_quality_statuses=prior_statuses,
        reviewed_cutoff=evidence.reviewed_cutoff.astimezone(UTC),
        structural_validation_decision_hash=base.decision_content_hash,
        structural_validation_passed=quality_only_blocker,
        promotion_evidence_hash=promotion_evidence_hash,
        new_revision_binding=binding,
        may_mutate_existing_evidence=False,
        decision_content_hash=canonical_content_hash(payload),
    )
