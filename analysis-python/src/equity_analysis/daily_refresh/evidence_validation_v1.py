from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

CLASSIFICATION_EVIDENCE_CONTRACT_VERSION = (
    "CLASSIFICATION-SOURCE-EVIDENCE-v1.0.0"
)
CLASSIFICATION_VALIDATION_POLICY_VERSION = (
    "CLASSIFICATION-SOURCE-VALIDATION-v1.0.0"
)
PRICE_EVIDENCE_CONTRACT_VERSION = "COMPLETED-DAILY-PRICE-EVIDENCE-v1.0.0"
PRICE_VALIDATION_POLICY_VERSION = "COMPLETED-DAILY-PRICE-VALIDATION-v1.0.0"

_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_PLACEHOLDER_CLASSIFICATIONS = frozenset(
    {"VALIDATION", "PLACEHOLDER", "UNKNOWN", "UNCLASSIFIED", "N/A", "NA"}
)


class EvidenceValidationState(StrEnum):
    VALIDATED = "VALIDATED"
    MISSING = "MISSING"
    INVALID = "INVALID"


class EvidencePersistenceScope(StrEnum):
    NEW_REVISION_OR_SNAPSHOT_ONLY = "NEW_REVISION_OR_SNAPSHOT_ONLY"


class EvidenceReason(StrEnum):
    CLASSIFICATION_EVIDENCE_MISSING = "CLASSIFICATION_EVIDENCE_MISSING"
    CLASSIFICATION_REQUIRED_FIELD_MISSING = "CLASSIFICATION_REQUIRED_FIELD_MISSING"
    CLASSIFICATION_PLACEHOLDER_REJECTED = "CLASSIFICATION_PLACEHOLDER_REJECTED"
    CLASSIFICATION_SOURCE_LINEAGE_MISSING = "CLASSIFICATION_SOURCE_LINEAGE_MISSING"
    CLASSIFICATION_SOURCE_HASH_INVALID = "CLASSIFICATION_SOURCE_HASH_INVALID"
    CLASSIFICATION_SOURCE_QUALITY_NOT_VALIDATED = (
        "CLASSIFICATION_SOURCE_QUALITY_NOT_VALIDATED"
    )
    CLASSIFICATION_TIME_INVALID = "CLASSIFICATION_TIME_INVALID"
    CLASSIFICATION_NOT_EFFECTIVE_AT_CUTOFF = "CLASSIFICATION_NOT_EFFECTIVE_AT_CUTOFF"
    CLASSIFICATION_MANUAL_OVERRIDE_INCOMPLETE = (
        "CLASSIFICATION_MANUAL_OVERRIDE_INCOMPLETE"
    )
    PRICE_EVIDENCE_MISSING = "PRICE_EVIDENCE_MISSING"
    PRICE_SECURITY_ID_MISMATCH = "PRICE_SECURITY_ID_MISMATCH"
    PRICE_DATES_NOT_STRICTLY_ORDERED = "PRICE_DATES_NOT_STRICTLY_ORDERED"
    PRICE_DUPLICATE_SESSION_DATE = "PRICE_DUPLICATE_SESSION_DATE"
    PRICE_EXPECTED_SESSION_MISSING = "PRICE_EXPECTED_SESSION_MISSING"
    PRICE_SESSION_NOT_COMPLETE = "PRICE_SESSION_NOT_COMPLETE"
    PRICE_SESSION_AFTER_CUTOFF = "PRICE_SESSION_AFTER_CUTOFF"
    PRICE_OHLC_INVALID = "PRICE_OHLC_INVALID"
    PRICE_VOLUME_INVALID = "PRICE_VOLUME_INVALID"
    PRICE_PROVIDER_MISMATCH = "PRICE_PROVIDER_MISMATCH"
    PRICE_ADJUSTMENT_MODE_MISMATCH = "PRICE_ADJUSTMENT_MODE_MISMATCH"
    PRICE_VERSION_LINEAGE_MISSING = "PRICE_VERSION_LINEAGE_MISSING"
    PRICE_REVISION_INVALID = "PRICE_REVISION_INVALID"
    PRICE_REVISION_SELECTION_UNPROVEN = "PRICE_REVISION_SELECTION_UNPROVEN"
    PRICE_SOURCE_LINEAGE_MISSING = "PRICE_SOURCE_LINEAGE_MISSING"
    PRICE_SOURCE_HASH_INVALID = "PRICE_SOURCE_HASH_INVALID"
    PRICE_QUALITY_STATUS_NOT_VALIDATED = "PRICE_QUALITY_STATUS_NOT_VALIDATED"
    PRICE_TIME_INVALID = "PRICE_TIME_INVALID"


@dataclass(frozen=True)
class ClassificationSourceEvidence:
    security_id: str
    classification_version: str
    normalized_sector: str
    normalized_industry: str
    company_type: str
    effective_from: date
    effective_to: date | None
    source_record_id: str
    source_provider: str
    source_schema_version: str
    normalization_version: str
    source_content_hash: str
    source_quality_status: str
    available_at: datetime
    ingested_at: datetime
    is_manual_override: bool = False
    override_reason: str | None = None
    reviewed_by: str | None = None


@dataclass(frozen=True)
class ClassificationValidationDecision:
    evidence_contract_version: str
    validation_policy_version: str
    state: EvidenceValidationState
    reason_codes: tuple[EvidenceReason, ...]
    security_id: str | None
    classification_version: str | None
    evidence_content_hash: str | None
    persistence_scope: EvidencePersistenceScope
    may_mutate_existing_evidence: bool
    binding_authorized: bool
    promotion_authorized: bool
    decision_content_hash: str


@dataclass(frozen=True)
class DailyPriceEvidenceBar:
    security_id: str
    trading_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    adjusted_close: Decimal | None
    volume: int
    adjustment_mode: str
    provider: str
    provider_schema_version: str
    parser_version: str
    normalization_version: str
    revision_number: int
    source_revision_status: str
    selected_revision_is_latest_at_cutoff: bool
    source_record_id: str
    source_content_hash: str
    source_quality_status: str
    available_at: datetime
    ingested_at: datetime
    session_complete: bool


@dataclass(frozen=True)
class DailyPriceSeriesEvidence:
    security_id: str
    expected_provider: str
    expected_adjustment_mode: str
    expected_completed_session: date
    bars: tuple[DailyPriceEvidenceBar, ...]


@dataclass(frozen=True)
class PriceValidationDecision:
    evidence_contract_version: str
    validation_policy_version: str
    state: EvidenceValidationState
    reason_codes: tuple[EvidenceReason, ...]
    security_id: str
    provider: str
    adjustment_mode: str
    expected_completed_session: date
    first_session: date | None
    last_session: date | None
    session_count: int
    evidence_content_hash: str | None
    source_quality_statuses: tuple[str, ...]
    persistence_scope: EvidencePersistenceScope
    may_mutate_existing_evidence: bool
    binding_authorized: bool
    promotion_authorized: bool
    decision_content_hash: str


def _canonical_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _canonical_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.isoformat()
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, tuple | list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    raise TypeError(f"Unsupported canonical value: {type(value).__name__}")


def canonical_content_hash(value: Any) -> str:
    encoded = json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _ordered_reasons(reasons: set[EvidenceReason]) -> tuple[EvidenceReason, ...]:
    return tuple(sorted(reasons, key=lambda item: item.value))


def _classification_decision(
    *,
    evidence: ClassificationSourceEvidence | None,
    state: EvidenceValidationState,
    reasons: set[EvidenceReason],
) -> ClassificationValidationDecision:
    evidence_hash = canonical_content_hash(evidence) if evidence is not None else None
    payload = {
        "evidenceContractVersion": CLASSIFICATION_EVIDENCE_CONTRACT_VERSION,
        "validationPolicyVersion": CLASSIFICATION_VALIDATION_POLICY_VERSION,
        "state": state,
        "reasonCodes": _ordered_reasons(reasons),
        "securityId": evidence.security_id if evidence is not None else None,
        "classificationVersion": (
            evidence.classification_version if evidence is not None else None
        ),
        "evidenceContentHash": evidence_hash,
        "persistenceScope": EvidencePersistenceScope.NEW_REVISION_OR_SNAPSHOT_ONLY,
        "mayMutateExistingEvidence": False,
        "bindingAuthorized": state == EvidenceValidationState.VALIDATED,
        "promotionAuthorized": False,
    }
    return ClassificationValidationDecision(
        evidence_contract_version=CLASSIFICATION_EVIDENCE_CONTRACT_VERSION,
        validation_policy_version=CLASSIFICATION_VALIDATION_POLICY_VERSION,
        state=state,
        reason_codes=_ordered_reasons(reasons),
        security_id=evidence.security_id if evidence is not None else None,
        classification_version=(
            evidence.classification_version if evidence is not None else None
        ),
        evidence_content_hash=evidence_hash,
        persistence_scope=EvidencePersistenceScope.NEW_REVISION_OR_SNAPSHOT_ONLY,
        may_mutate_existing_evidence=False,
        binding_authorized=state == EvidenceValidationState.VALIDATED,
        promotion_authorized=False,
        decision_content_hash=canonical_content_hash(payload),
    )


def validate_classification_evidence(
    evidence: ClassificationSourceEvidence | None,
    *,
    as_of: datetime,
) -> ClassificationValidationDecision:
    """Validate classification lineage for a future revision or snapshot.

    This function is deliberately read-only. A validated result authorizes a caller
    to create a new revision; it never promotes or mutates prior evidence.
    """

    if not _aware(as_of):
        raise ValueError("Classification validation as_of must be timezone-aware")
    if evidence is None:
        return _classification_decision(
            evidence=None,
            state=EvidenceValidationState.MISSING,
            reasons={EvidenceReason.CLASSIFICATION_EVIDENCE_MISSING},
        )

    reasons: set[EvidenceReason] = set()
    required = (
        evidence.security_id,
        evidence.classification_version,
        evidence.normalized_sector,
        evidence.normalized_industry,
        evidence.company_type,
        evidence.source_record_id,
        evidence.source_provider,
        evidence.source_schema_version,
        evidence.normalization_version,
    )
    if any(not item.strip() for item in required):
        reasons.add(EvidenceReason.CLASSIFICATION_REQUIRED_FIELD_MISSING)
    if (
        evidence.normalized_sector.strip().upper() in _PLACEHOLDER_CLASSIFICATIONS
        or evidence.normalized_industry.strip().upper() in _PLACEHOLDER_CLASSIFICATIONS
    ):
        reasons.add(EvidenceReason.CLASSIFICATION_PLACEHOLDER_REJECTED)
    if not evidence.source_record_id.strip() or not evidence.source_provider.strip():
        reasons.add(EvidenceReason.CLASSIFICATION_SOURCE_LINEAGE_MISSING)
    if _SHA256_PATTERN.fullmatch(evidence.source_content_hash) is None:
        reasons.add(EvidenceReason.CLASSIFICATION_SOURCE_HASH_INVALID)
    if evidence.source_quality_status != EvidenceValidationState.VALIDATED.value:
        reasons.add(EvidenceReason.CLASSIFICATION_SOURCE_QUALITY_NOT_VALIDATED)
    if (
        not _aware(evidence.available_at)
        or not _aware(evidence.ingested_at)
        or evidence.ingested_at < evidence.available_at
        or evidence.available_at > as_of
        or evidence.ingested_at > as_of
    ):
        reasons.add(EvidenceReason.CLASSIFICATION_TIME_INVALID)
    if (
        evidence.effective_from > as_of.date()
        or (
            evidence.effective_to is not None
            and evidence.effective_to <= as_of.date()
        )
    ):
        reasons.add(EvidenceReason.CLASSIFICATION_NOT_EFFECTIVE_AT_CUTOFF)
    if evidence.is_manual_override and (
        evidence.override_reason is None
        or not evidence.override_reason.strip()
        or evidence.reviewed_by is None
        or not evidence.reviewed_by.strip()
    ):
        reasons.add(EvidenceReason.CLASSIFICATION_MANUAL_OVERRIDE_INCOMPLETE)

    return _classification_decision(
        evidence=evidence,
        state=(
            EvidenceValidationState.INVALID
            if reasons
            else EvidenceValidationState.VALIDATED
        ),
        reasons=reasons,
    )


def _price_decision(
    *,
    evidence: DailyPriceSeriesEvidence,
    state: EvidenceValidationState,
    reasons: set[EvidenceReason],
) -> PriceValidationDecision:
    bars = evidence.bars
    evidence_hash = canonical_content_hash(evidence) if bars else None
    source_quality_statuses = tuple(
        sorted({item.source_quality_status for item in bars})
    )
    payload = {
        "evidenceContractVersion": PRICE_EVIDENCE_CONTRACT_VERSION,
        "validationPolicyVersion": PRICE_VALIDATION_POLICY_VERSION,
        "state": state,
        "reasonCodes": _ordered_reasons(reasons),
        "securityId": evidence.security_id,
        "provider": evidence.expected_provider,
        "adjustmentMode": evidence.expected_adjustment_mode,
        "expectedCompletedSession": evidence.expected_completed_session,
        "firstSession": bars[0].trading_date if bars else None,
        "lastSession": bars[-1].trading_date if bars else None,
        "sessionCount": len(bars),
        "evidenceContentHash": evidence_hash,
        "sourceQualityStatuses": source_quality_statuses,
        "persistenceScope": EvidencePersistenceScope.NEW_REVISION_OR_SNAPSHOT_ONLY,
        "mayMutateExistingEvidence": False,
        "bindingAuthorized": state == EvidenceValidationState.VALIDATED,
        "promotionAuthorized": False,
    }
    return PriceValidationDecision(
        evidence_contract_version=PRICE_EVIDENCE_CONTRACT_VERSION,
        validation_policy_version=PRICE_VALIDATION_POLICY_VERSION,
        state=state,
        reason_codes=_ordered_reasons(reasons),
        security_id=evidence.security_id,
        provider=evidence.expected_provider,
        adjustment_mode=evidence.expected_adjustment_mode,
        expected_completed_session=evidence.expected_completed_session,
        first_session=bars[0].trading_date if bars else None,
        last_session=bars[-1].trading_date if bars else None,
        session_count=len(bars),
        evidence_content_hash=evidence_hash,
        source_quality_statuses=source_quality_statuses,
        persistence_scope=EvidencePersistenceScope.NEW_REVISION_OR_SNAPSHOT_ONLY,
        may_mutate_existing_evidence=False,
        binding_authorized=state == EvidenceValidationState.VALIDATED,
        promotion_authorized=False,
        decision_content_hash=canonical_content_hash(payload),
    )


def validate_daily_price_series(
    evidence: DailyPriceSeriesEvidence,
    *,
    cutoff: datetime,
) -> PriceValidationDecision:
    """Return a deterministic binding decision without mutating or promoting evidence.

    PROVISIONAL evidence is an explicit blocker. A future promotion workflow must
    have a separate versioned policy and promotion-evidence hash; this validator
    cannot authorize such a promotion.
    """

    if not _aware(cutoff):
        raise ValueError("Price validation cutoff must be timezone-aware")
    if not evidence.bars:
        return _price_decision(
            evidence=evidence,
            state=EvidenceValidationState.MISSING,
            reasons={EvidenceReason.PRICE_EVIDENCE_MISSING},
        )

    reasons: set[EvidenceReason] = set()
    dates = tuple(item.trading_date for item in evidence.bars)
    if len(set(dates)) != len(dates):
        reasons.add(EvidenceReason.PRICE_DUPLICATE_SESSION_DATE)
    if dates != tuple(sorted(dates)) or any(
        current <= prior
        for prior, current in zip(dates[:-1], dates[1:], strict=True)
    ):
        reasons.add(EvidenceReason.PRICE_DATES_NOT_STRICTLY_ORDERED)
    if dates[-1] != evidence.expected_completed_session:
        reasons.add(EvidenceReason.PRICE_EXPECTED_SESSION_MISSING)
    if evidence.expected_completed_session > cutoff.date() or any(
        item.trading_date > evidence.expected_completed_session
        or item.trading_date > cutoff.date()
        for item in evidence.bars
    ):
        reasons.add(EvidenceReason.PRICE_SESSION_AFTER_CUTOFF)

    for item in evidence.bars:
        if item.security_id != evidence.security_id:
            reasons.add(EvidenceReason.PRICE_SECURITY_ID_MISMATCH)
        if not item.session_complete:
            reasons.add(EvidenceReason.PRICE_SESSION_NOT_COMPLETE)
        if (
            item.open_price <= 0
            or item.high_price <= 0
            or item.low_price <= 0
            or item.close_price <= 0
            or (
                item.adjusted_close is not None
                and item.adjusted_close <= 0
            )
            or item.high_price
            < max(item.open_price, item.low_price, item.close_price)
            or item.low_price
            > min(item.open_price, item.high_price, item.close_price)
        ):
            reasons.add(EvidenceReason.PRICE_OHLC_INVALID)
        if item.volume <= 0:
            reasons.add(EvidenceReason.PRICE_VOLUME_INVALID)
        if item.provider != evidence.expected_provider:
            reasons.add(EvidenceReason.PRICE_PROVIDER_MISMATCH)
        if item.adjustment_mode != evidence.expected_adjustment_mode:
            reasons.add(EvidenceReason.PRICE_ADJUSTMENT_MODE_MISMATCH)
        if any(
            not value.strip()
            for value in (
                item.provider_schema_version,
                item.parser_version,
                item.normalization_version,
            )
        ):
            reasons.add(EvidenceReason.PRICE_VERSION_LINEAGE_MISSING)
        if item.revision_number < 1:
            reasons.add(EvidenceReason.PRICE_REVISION_INVALID)
        if (
            not item.source_revision_status.strip()
            or not item.selected_revision_is_latest_at_cutoff
        ):
            reasons.add(EvidenceReason.PRICE_REVISION_SELECTION_UNPROVEN)
        if not item.source_record_id.strip():
            reasons.add(EvidenceReason.PRICE_SOURCE_LINEAGE_MISSING)
        if _SHA256_PATTERN.fullmatch(item.source_content_hash) is None:
            reasons.add(EvidenceReason.PRICE_SOURCE_HASH_INVALID)
        if item.source_quality_status != EvidenceValidationState.VALIDATED.value:
            reasons.add(EvidenceReason.PRICE_QUALITY_STATUS_NOT_VALIDATED)
        if (
            not _aware(item.available_at)
            or not _aware(item.ingested_at)
            or item.ingested_at < item.available_at
            or item.available_at > cutoff
            or item.ingested_at > cutoff
            or item.available_at.date() < item.trading_date
        ):
            reasons.add(EvidenceReason.PRICE_TIME_INVALID)

    return _price_decision(
        evidence=evidence,
        state=(
            EvidenceValidationState.INVALID
            if reasons
            else EvidenceValidationState.VALIDATED
        ),
        reasons=reasons,
    )
