from __future__ import annotations

from dataclasses import dataclass

from equity_analysis.dual_system_contract import DataState
from equity_analysis.evidence_foundation.contracts_v1 import (
    ConflictCriticality,
    ConflictStatus,
    EvidenceCandidate,
    EvidenceSelectionRequest,
)
from equity_analysis.evidence_foundation.domain_contracts_v1 import (
    canonical_data_matches_request,
)


@dataclass(frozen=True)
class EvidenceSelectionResult:
    state: DataState
    reason_code: str
    selector_version: str
    selected: EvidenceCandidate | None
    rejected_evidence_ids: tuple[str, ...]
    rejection_reasons: tuple[tuple[str, str], ...]


def select_evidence(request: EvidenceSelectionRequest) -> EvidenceSelectionResult:
    """Select canonical evidence without consulting scores or provider-native fields."""

    if not request.candidates:
        return EvidenceSelectionResult(
            state=DataState.MISSING,
            reason_code="NO_OBSERVATION_CANDIDATES",
            selector_version=request.policy.selector_version,
            selected=None,
            rejected_evidence_ids=(),
            rejection_reasons=(),
        )

    ambiguous = _ambiguous_provider_revision(request)
    if ambiguous:
        ambiguous_set = set(ambiguous)
        rejection_reasons = tuple(
            (
                candidate.evidence_id,
                (
                    "AMBIGUOUS_PROVIDER_REVISION"
                    if candidate.evidence_id in ambiguous_set
                    else "SELECTION_ABORTED_BY_AMBIGUOUS_PROVIDER_REVISION"
                ),
            )
            for candidate in sorted(
                request.candidates,
                key=lambda item: item.evidence_id,
            )
        )
        return EvidenceSelectionResult(
            state=DataState.INVALID,
            reason_code="AMBIGUOUS_PROVIDER_REVISION",
            selector_version=request.policy.selector_version,
            selected=None,
            rejected_evidence_ids=tuple(
                evidence_id for evidence_id, _ in rejection_reasons
            ),
            rejection_reasons=rejection_reasons,
        )

    eligible: list[EvidenceCandidate] = []
    rejected: list[str] = []
    rejection_reasons: dict[str, str] = {}
    critical_conflict = False
    fallback_failures: list[tuple[EvidenceCandidate, DataState, str]] = []

    for candidate in request.candidates:
        if not _matches_contract(candidate, request):
            rejected.append(candidate.evidence_id)
            rejection_reasons[candidate.evidence_id] = (
                "NO_CONTRACT_ELIGIBLE_EVIDENCE"
            )
            continue
        if (
            candidate.available_at > request.decision_cutoff
            or candidate.ingested_at > request.sealed_ingestion_cutoff
        ):
            fallback_failures.append(
                (
                    candidate,
                    DataState.EXCLUDED,
                    "EVIDENCE_AFTER_DECISION_OR_INGESTION_CUTOFF",
                )
            )
            rejected.append(candidate.evidence_id)
            rejection_reasons[candidate.evidence_id] = (
                "EVIDENCE_AFTER_DECISION_OR_INGESTION_CUTOFF"
            )
            continue
        if (
            candidate.conflict_criticality == ConflictCriticality.CRITICAL
        ):
            critical_conflict = True
            rejected.append(candidate.evidence_id)
            rejection_reasons[candidate.evidence_id] = (
                "CRITICAL_EVIDENCE_CONFLICT"
            )
            continue
        if (
            candidate.conflict_status == ConflictStatus.UNRESOLVED
            and candidate.conflict_criticality == ConflictCriticality.NONCRITICAL
            and request.policy.field_code in candidate.affected_factors
        ):
            fallback_failures.append(
                (candidate, DataState.MISSING, "DEPENDENT_FIELD_CONFLICT")
            )
            rejected.append(candidate.evidence_id)
            rejection_reasons[candidate.evidence_id] = (
                "DEPENDENT_FIELD_CONFLICT"
            )
            continue
        if (
            candidate.state == DataState.STALE
            or (
                candidate.stale_after is not None
                and candidate.stale_after <= request.decision_cutoff
            )
        ):
            fallback_failures.append(
                (candidate, DataState.STALE, "FRESHNESS_POLICY_EXPIRED")
            )
            rejected.append(candidate.evidence_id)
            rejection_reasons[candidate.evidence_id] = (
                "FRESHNESS_POLICY_EXPIRED"
            )
            continue
        if candidate.state != DataState.VALID:
            fallback_failures.append(
                (
                    candidate,
                    candidate.state,
                    candidate.reason_code or "NONVALID_EVIDENCE",
                )
            )
            rejected.append(candidate.evidence_id)
            rejection_reasons[candidate.evidence_id] = (
                candidate.reason_code or "NONVALID_EVIDENCE"
            )
            continue
        if (
            candidate.tolerance_field_code is not None
            and candidate.tolerance_field_code != request.policy.field_code
        ):
            fallback_failures.append(
                (candidate, DataState.MISSING, "TOLERANCE_FIELD_MISMATCH")
            )
            rejected.append(candidate.evidence_id)
            rejection_reasons[candidate.evidence_id] = (
                "TOLERANCE_FIELD_MISMATCH"
            )
            continue
        if candidate.canonical_data is None or not canonical_data_matches_request(
            request.policy.domain,
            request.policy.field_code,
            candidate.canonical_data,
            request.policy.domain_constraints,
        ):
            fallback_failures.append(
                (candidate, DataState.MISSING, "DOMAIN_CONSTRAINT_MISMATCH")
            )
            rejected.append(candidate.evidence_id)
            rejection_reasons[candidate.evidence_id] = (
                "DOMAIN_CONSTRAINT_MISMATCH"
            )
            continue
        eligible.append(candidate)

    if critical_conflict:
        for candidate in eligible:
            if candidate.evidence_id not in rejection_reasons:
                rejected.append(candidate.evidence_id)
                rejection_reasons[candidate.evidence_id] = (
                    "SELECTION_ABORTED_BY_CRITICAL_CONFLICT"
                )
        return EvidenceSelectionResult(
            state=DataState.INVALID,
            reason_code="CRITICAL_EVIDENCE_CONFLICT",
            selector_version=request.policy.selector_version,
            selected=None,
            rejected_evidence_ids=tuple(sorted(rejected)),
            rejection_reasons=tuple(sorted(rejection_reasons.items())),
        )
    if not eligible:
        if fallback_failures:
            fallback_failures.sort(
                key=lambda candidate: (
                    request.policy.provider_fallback_priority.index(
                        candidate[0].provider_code
                    ),
                    -candidate[0].source_revision,
                    candidate[0].normalized_record_hash,
                    candidate[0].evidence_id,
                )
            )
            _, state, reason_code = fallback_failures[0]
        else:
            state = DataState.MISSING
            reason_code = "NO_CONTRACT_ELIGIBLE_EVIDENCE"
        return EvidenceSelectionResult(
            state=state,
            reason_code=reason_code,
            selector_version=request.policy.selector_version,
            selected=None,
            rejected_evidence_ids=tuple(sorted(rejected)),
            rejection_reasons=tuple(sorted(rejection_reasons.items())),
        )

    priority = {
        provider: index
        for index, provider in enumerate(
            request.policy.provider_fallback_priority
        )
    }
    eligible.sort(
        key=lambda candidate: (
            priority[candidate.provider_code],
            -candidate.source_revision,
            candidate.normalized_record_hash,
            candidate.evidence_id,
        )
    )
    selected = eligible[0]
    rejected.extend(
        candidate.evidence_id
        for candidate in eligible
        if candidate.evidence_id != selected.evidence_id
    )
    for candidate in eligible:
        if candidate.evidence_id != selected.evidence_id:
            rejection_reasons[candidate.evidence_id] = (
                "LOWER_PROVIDER_PRIORITY_OR_REVISION"
            )
    return EvidenceSelectionResult(
        state=DataState.VALID,
        reason_code="SELECTED_BY_VERSIONED_PROVIDER_FALLBACK",
        selector_version=request.policy.selector_version,
        selected=selected,
        rejected_evidence_ids=tuple(sorted(rejected)),
        rejection_reasons=tuple(sorted(rejection_reasons.items())),
    )


def _matches_contract(
    candidate: EvidenceCandidate,
    request: EvidenceSelectionRequest,
) -> bool:
    policy = request.policy
    return (
        candidate.security == request.security
        and candidate.domain == policy.domain.value
        and candidate.layer == policy.required_layer
        and candidate.provider_code in policy.provider_fallback_priority
        and candidate.normalization_version
        == policy.required_normalization_version
        and candidate.strictness_class == policy.required_strictness_class
        and candidate.claim_class == policy.required_claim_class
    )


def _ambiguous_provider_revision(
    request: EvidenceSelectionRequest,
) -> tuple[str, ...]:
    groups: dict[tuple[str, int], list[EvidenceCandidate]] = {}
    for candidate in request.candidates:
        if _matches_contract(candidate, request):
            groups.setdefault(
                (candidate.provider_code, candidate.source_revision),
                [],
            ).append(candidate)
    ambiguous_ids = {
        candidate.evidence_id
        for candidates in groups.values()
        if len({candidate.normalized_record_hash for candidate in candidates}) > 1
        for candidate in candidates
    }
    return tuple(sorted(ambiguous_ids))
