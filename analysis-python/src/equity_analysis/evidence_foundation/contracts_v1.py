from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from equity_analysis.dual_system_contract import (
    DataState,
    EvidenceClaimClass,
    EvidenceStrictness,
    ModelApplicability,
    optional_timestamp,
    required_bool,
    required_date,
    required_object,
    required_string,
    required_timestamp,
)
from equity_analysis.evidence_foundation.domain_contracts_v1 import (
    EvidenceDomain,
    validate_canonical_data,
    validate_domain_constraints,
    validate_selector_field,
)

CONTRACT_VERSION = "unified-market-data-evidence-foundation-v1.0.0"
SELECTOR_VERSION = "deterministic-evidence-selector-v1.0.0"
PRIVATE_RAW_STORAGE_CLASS = "PRIVATE_GIT_IGNORED"
SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


class UnifiedEvidenceContractViolation(ValueError):
    """Raised when a Task 1 evidence contract fails closed."""


class EvidenceLayer(StrEnum):
    RAW_MANIFEST = "RAW_MANIFEST"
    NORMALIZED_OBSERVATION = "NORMALIZED_OBSERVATION"
    ENGINE_DERIVED = "ENGINE_DERIVED"


class ConflictStatus(StrEnum):
    NONE = "NONE"
    RESOLVED_WITHIN_TOLERANCE = "RESOLVED_WITHIN_TOLERANCE"
    UNRESOLVED = "UNRESOLVED"


class ConflictCriticality(StrEnum):
    NONE = "NONE"
    NONCRITICAL = "NONCRITICAL"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class EvidenceParentReference:
    evidence_id: str
    normalized_record_hash: str

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> EvidenceParentReference:
        _require_exact_keys(
            payload,
            {"evidenceId", "normalizedRecordHash"},
            "inputEvidenceReference",
        )
        return cls(
            evidence_id=_required_uuid_string(payload, "evidenceId"),
            normalized_record_hash=_required_sha256(
                payload, "normalizedRecordHash"
            ),
        )


@dataclass(frozen=True)
class SecurityIdentity:
    security_id: str
    company_id: str
    instrument_id: str
    share_class_id: str
    listing_id: str
    ticker_assignment_id: str
    ticker: str
    mic: str
    currency: str

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> SecurityIdentity:
        _require_exact_keys(
            payload,
            {
                "securityId",
                "companyId",
                "instrumentId",
                "shareClassId",
                "listingId",
                "tickerAssignmentId",
                "ticker",
                "mic",
                "currency",
            },
            "security",
        )
        values = {
            name: _required_uuid_string(payload, name)
            for name in (
                "securityId",
                "companyId",
                "instrumentId",
                "shareClassId",
                "listingId",
                "tickerAssignmentId",
            )
        }
        for name in ("ticker", "mic", "currency"):
            values[name] = required_string(payload, name)
        if re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,31}", values["ticker"]) is None:
            raise UnifiedEvidenceContractViolation(
                "ticker must use the canonical US listing format"
            )
        if re.fullmatch(r"[A-Z0-9]{4}", values["mic"]) is None:
            raise UnifiedEvidenceContractViolation("mic must be a four-character MIC")
        if re.fullmatch(r"[A-Z]{3}", values["currency"]) is None:
            raise UnifiedEvidenceContractViolation(
                "currency must be an uppercase ISO currency code"
            )
        return cls(
            security_id=values["securityId"],
            company_id=values["companyId"],
            instrument_id=values["instrumentId"],
            share_class_id=values["shareClassId"],
            listing_id=values["listingId"],
            ticker_assignment_id=values["tickerAssignmentId"],
            ticker=values["ticker"],
            mic=values["mic"],
            currency=values["currency"],
        )

    @property
    def durable_tuple(self) -> tuple[str, ...]:
        return (
            self.security_id,
            self.company_id,
            self.instrument_id,
            self.share_class_id,
            self.listing_id,
            self.ticker_assignment_id,
        )


@dataclass(frozen=True)
class CompletedSession:
    calendar_id: str
    calendar_version: str
    mic: str
    session_date: date
    timezone: str
    scheduled_open: datetime
    scheduled_close: datetime
    early_close: bool
    completed_at: datetime

    @classmethod
    def parse(
        cls,
        payload: dict[str, Any],
        *,
        decision_cutoff: datetime,
        sealed_ingestion_cutoff: datetime,
    ) -> CompletedSession:
        _require_exact_keys(
            payload,
            {
                "calendarId",
                "calendarVersion",
                "mic",
                "sessionDate",
                "timezone",
                "scheduledOpen",
                "scheduledClose",
                "earlyClose",
                "status",
                "completedAt",
            },
            "completedSession",
        )
        if payload.get("status") != "COMPLETED":
            raise UnifiedEvidenceContractViolation(
                "Selector inputs require a COMPLETED session"
            )
        scheduled_open = required_timestamp(payload, "scheduledOpen")
        scheduled_close = required_timestamp(payload, "scheduledClose")
        completed_at = required_timestamp(payload, "completedAt")
        if not (
            scheduled_open
            < scheduled_close
            <= completed_at
            <= decision_cutoff
            <= sealed_ingestion_cutoff
        ):
            raise UnifiedEvidenceContractViolation(
                "Completed-session and decision chronology is invalid"
            )
        session_date = required_date(payload, "sessionDate")
        timezone_name = required_string(payload, "timezone")
        try:
            local_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise UnifiedEvidenceContractViolation(
                "Completed-session timezone must be an IANA timezone"
            ) from error
        if (
            scheduled_open.astimezone(local_timezone).date() != session_date
            or scheduled_close.astimezone(local_timezone).date() != session_date
        ):
            raise UnifiedEvidenceContractViolation(
                "Completed-session date must match local scheduled trading times"
            )
        return cls(
            calendar_id=required_string(payload, "calendarId"),
            calendar_version=required_string(payload, "calendarVersion"),
            mic=required_string(payload, "mic"),
            session_date=session_date,
            timezone=timezone_name,
            scheduled_open=scheduled_open,
            scheduled_close=scheduled_close,
            early_close=required_bool(payload, "earlyClose"),
            completed_at=completed_at,
        )


@dataclass(frozen=True)
class EvidenceCandidate:
    evidence_id: str
    domain: str
    layer: EvidenceLayer
    state: DataState
    reason_code: str | None
    security: SecurityIdentity
    provider_code: str
    provider_schema_version: str
    adapter_version: str
    normalization_version: str
    source_record_id: str
    source_revision: int
    source_content_hash: str
    normalized_record_hash: str
    effective_at: datetime
    available_at: datetime
    retrieved_at: datetime | None
    ingested_at: datetime
    freshness_policy_version: str
    stale_after: datetime | None
    strictness_class: EvidenceStrictness
    claim_class: EvidenceClaimClass
    conflict_status: ConflictStatus
    conflict_criticality: ConflictCriticality
    affected_factors: tuple[str, ...]
    observation_reference: str
    derivation_version: str | None
    input_evidence_references: tuple[EvidenceParentReference, ...]
    canonical_data: dict[str, Any] | None
    tolerance_policy_version: str | None
    tolerance_field_code: str | None
    supersedes_evidence_id: str | None

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> EvidenceCandidate:
        allowed_fields = {
            "evidenceId",
            "domain",
            "layer",
            "state",
            "reasonCode",
            "security",
            "strictnessClass",
            "claimClass",
            "observationReference",
            "canonicalData",
            "rawManifest",
            "derivation",
            "lineage",
            "fieldTolerancePolicy",
            "supersedesEvidenceId",
        }
        unknown_fields = set(payload) - allowed_fields
        if unknown_fields:
            raise UnifiedEvidenceContractViolation(
                "Evidence candidate contains unknown fields: "
                + ", ".join(sorted(unknown_fields))
            )
        evidence_id = _required_uuid_string(payload, "evidenceId")
        layer = EvidenceLayer(required_string(payload, "layer"))
        if layer == EvidenceLayer.RAW_MANIFEST:
            raise UnifiedEvidenceContractViolation(
                "Raw manifests are lineage references, not selectable evidence"
            )
        domain = EvidenceDomain(required_string(payload, "domain"))
        state = DataState(required_string(payload, "state"))
        reason_code = payload.get("reasonCode")
        if state != DataState.VALID:
            reason_code = required_string(payload, "reasonCode")
        elif reason_code is not None:
            raise UnifiedEvidenceContractViolation(
                "VALID evidence reasonCode must be null or absent"
            )

        lineage = required_object(payload, "lineage")
        _require_allowed_keys(
            lineage,
            {
                "providerCode",
                "providerSchemaVersion",
                "adapterVersion",
                "normalizationVersion",
                "sourceRecordId",
                "sourceRevision",
                "sourceContentHash",
                "normalizedRecordHash",
                "effectiveAt",
                "availableAt",
                "retrievedAt",
                "ingestedAt",
                "freshnessPolicyVersion",
                "staleAfter",
                "conflict",
            },
            {
                "providerCode",
                "providerSchemaVersion",
                "adapterVersion",
                "normalizationVersion",
                "sourceRecordId",
                "sourceRevision",
                "sourceContentHash",
                "normalizedRecordHash",
                "effectiveAt",
                "availableAt",
                "ingestedAt",
                "freshnessPolicyVersion",
                "conflict",
            },
            "lineage",
        )
        source_revision = lineage.get("sourceRevision")
        if (
            not isinstance(source_revision, int)
            or isinstance(source_revision, bool)
            or source_revision < 1
        ):
            raise UnifiedEvidenceContractViolation(
                "sourceRevision must be a positive integer"
            )
        effective_at = required_timestamp(lineage, "effectiveAt")
        available_at = required_timestamp(lineage, "availableAt")
        retrieved_at = optional_timestamp(lineage, "retrievedAt")
        ingested_at = required_timestamp(lineage, "ingestedAt")
        if not effective_at <= available_at <= ingested_at:
            raise UnifiedEvidenceContractViolation(
                "Evidence chronology must be effective <= available <= ingested"
            )
        if retrieved_at is not None and not available_at <= retrieved_at <= ingested_at:
            raise UnifiedEvidenceContractViolation(
                "Retrieved evidence chronology is invalid"
            )

        strictness = EvidenceStrictness(required_string(payload, "strictnessClass"))
        claim = EvidenceClaimClass(required_string(payload, "claimClass"))
        if strictness == EvidenceStrictness.APPROXIMATE_HISTORICAL_RESEARCH and claim in {
            EvidenceClaimClass.STRICT_PIT,
            EvidenceClaimClass.SEALED_PROSPECTIVE,
        }:
            raise UnifiedEvidenceContractViolation(
                "Approximate historical evidence cannot claim strict PIT or prospective use"
            )
        tolerance_field_code = None
        tolerance_policy_version = None
        if strictness == EvidenceStrictness.DOMAIN_TOLERANT_NUMERIC:
            tolerance = required_object(payload, "fieldTolerancePolicy")
            _require_exact_keys(
                tolerance,
                {
                    "policyVersion",
                    "fieldCode",
                    "alignmentSatisfied",
                    "alignmentDimensions",
                },
                "fieldTolerancePolicy",
            )
            tolerance_policy_version = required_string(
                tolerance, "policyVersion"
            )
            tolerance_field_code = required_string(tolerance, "fieldCode")
            if tolerance.get("alignmentSatisfied") is not True:
                raise UnifiedEvidenceContractViolation(
                    "Numeric tolerance requires prior semantic and chronology alignment"
                )
            alignment = required_object(tolerance, "alignmentDimensions")
            if alignment != {
                "semantic": True,
                "identity": True,
                "period": True,
                "unit": True,
                "currency": True,
                "adjustment": True,
                "chronology": True,
            }:
                raise UnifiedEvidenceContractViolation(
                    "Every tolerance alignment dimension must be explicitly satisfied"
                )
        elif payload.get("fieldTolerancePolicy") is not None:
            raise UnifiedEvidenceContractViolation(
                "Only DOMAIN_TOLERANT_NUMERIC may declare a tolerance policy"
            )

        conflict = required_object(lineage, "conflict")
        _require_exact_keys(
            conflict,
            {"status", "criticality", "affectedFactors"},
            "conflict",
        )
        conflict_status = ConflictStatus(required_string(conflict, "status"))
        conflict_criticality = ConflictCriticality(
            required_string(conflict, "criticality")
        )
        affected = conflict.get("affectedFactors")
        if (
            not isinstance(affected, list)
            or not all(isinstance(item, str) and item.strip() for item in affected)
        ):
            raise UnifiedEvidenceContractViolation(
                "affectedFactors must be a string list"
            )
        if conflict_status == ConflictStatus.NONE:
            if conflict_criticality != ConflictCriticality.NONE or affected:
                raise UnifiedEvidenceContractViolation(
                    "No-conflict lineage cannot declare criticality or affected factors"
                )
        elif conflict_criticality == ConflictCriticality.NONE:
            raise UnifiedEvidenceContractViolation(
                "A declared conflict requires explicit criticality"
            )
        if conflict_status == ConflictStatus.RESOLVED_WITHIN_TOLERANCE:
            if (
                conflict_criticality != ConflictCriticality.NONCRITICAL
                or strictness != EvidenceStrictness.DOMAIN_TOLERANT_NUMERIC
            ):
                raise UnifiedEvidenceContractViolation(
                    "Resolved-within-tolerance conflicts must be noncritical "
                    "domain-tolerant numeric evidence"
                )

        lineage_hash = _required_sha256(lineage, "sourceContentHash")
        derivation_version, input_evidence_references = _validate_layer_boundary(
            payload,
            layer=layer,
            state=state,
            lineage_hash=lineage_hash,
        )
        if any(
            reference.evidence_id == evidence_id
            for reference in input_evidence_references
        ):
            raise UnifiedEvidenceContractViolation(
                "Engine-derived evidence cannot reference itself"
            )
        supersedes_evidence_id = _optional_uuid_string(
            payload, "supersedesEvidenceId"
        )
        if supersedes_evidence_id == evidence_id:
            raise UnifiedEvidenceContractViolation(
                "Evidence cannot supersede itself"
            )
        canonical_data = None
        if state == DataState.VALID:
            canonical_data = validate_canonical_data(
                domain,
                payload.get("canonicalData"),
                layer=layer.value,
            )
            if domain == EvidenceDomain.FUNDAMENTAL:
                filed_at = required_timestamp(canonical_data, "filedAt")
                if filed_at > available_at or filed_at > ingested_at:
                    raise UnifiedEvidenceContractViolation(
                        "Fundamental filedAt cannot exceed evidence availability "
                        "or ingestion chronology"
                    )
            if (
                domain == EvidenceDomain.LIQUIDITY
                and len(input_evidence_references)
                != canonical_data["validObservationCount"]
            ):
                raise UnifiedEvidenceContractViolation(
                    "Liquidity parent count must equal validObservationCount"
                )
        elif payload.get("canonicalData") is not None:
            raise UnifiedEvidenceContractViolation(
                "Non-VALID evidence cannot carry canonical observation values"
            )

        return cls(
            evidence_id=evidence_id,
            domain=domain.value,
            layer=layer,
            state=state,
            reason_code=reason_code,
            security=SecurityIdentity.parse(required_object(payload, "security")),
            provider_code=required_string(lineage, "providerCode"),
            provider_schema_version=required_string(
                lineage, "providerSchemaVersion"
            ),
            adapter_version=required_string(lineage, "adapterVersion"),
            normalization_version=required_string(
                lineage, "normalizationVersion"
            ),
            source_record_id=required_string(lineage, "sourceRecordId"),
            source_revision=source_revision,
            source_content_hash=lineage_hash,
            normalized_record_hash=_required_sha256(
                lineage, "normalizedRecordHash"
            ),
            effective_at=effective_at,
            available_at=available_at,
            retrieved_at=retrieved_at,
            ingested_at=ingested_at,
            freshness_policy_version=required_string(
                lineage, "freshnessPolicyVersion"
            ),
            stale_after=optional_timestamp(lineage, "staleAfter"),
            strictness_class=strictness,
            claim_class=claim,
            conflict_status=conflict_status,
            conflict_criticality=conflict_criticality,
            affected_factors=tuple(affected),
            observation_reference=required_string(
                payload, "observationReference"
            ),
            derivation_version=derivation_version,
            input_evidence_references=input_evidence_references,
            canonical_data=canonical_data,
            tolerance_policy_version=tolerance_policy_version,
            tolerance_field_code=tolerance_field_code,
            supersedes_evidence_id=supersedes_evidence_id,
        )


@dataclass(frozen=True)
class SelectorPolicy:
    selector_version: str
    policy_version: str
    domain: EvidenceDomain
    field_code: str
    required_layer: EvidenceLayer
    domain_constraints: dict[str, Any]
    provider_fallback_priority: tuple[str, ...]
    required_strictness_class: EvidenceStrictness
    required_claim_class: EvidenceClaimClass
    required_normalization_version: str

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> SelectorPolicy:
        _require_exact_keys(
            payload,
            {
                "selectorVersion",
                "policyVersion",
                "domain",
                "fieldCode",
                "requiredLayer",
                "domainConstraints",
                "providerFallbackPriority",
                "requiredStrictnessClass",
                "requiredClaimClass",
                "requiredNormalizationVersion",
            },
            "selectorPolicy",
        )
        selector_version = required_string(payload, "selectorVersion")
        if selector_version != SELECTOR_VERSION:
            raise UnifiedEvidenceContractViolation("Unsupported selector version")
        priority = payload.get("providerFallbackPriority")
        if (
            not isinstance(priority, list)
            or not priority
            or not all(isinstance(item, str) and item.strip() for item in priority)
            or len(set(priority)) != len(priority)
        ):
            raise UnifiedEvidenceContractViolation(
                "Provider fallback priority must be a nonempty unique string list"
            )
        domain = EvidenceDomain(required_string(payload, "domain"))
        field_code = required_string(payload, "fieldCode")
        validate_selector_field(domain, field_code)
        return cls(
            selector_version=selector_version,
            policy_version=required_string(payload, "policyVersion"),
            domain=domain,
            field_code=field_code,
            required_layer=EvidenceLayer(required_string(payload, "requiredLayer")),
            domain_constraints=validate_domain_constraints(
                domain,
                payload.get("domainConstraints"),
            ),
            provider_fallback_priority=tuple(priority),
            required_strictness_class=EvidenceStrictness(
                required_string(payload, "requiredStrictnessClass")
            ),
            required_claim_class=EvidenceClaimClass(
                required_string(payload, "requiredClaimClass")
            ),
            required_normalization_version=required_string(
                payload, "requiredNormalizationVersion"
            ),
        )


@dataclass(frozen=True)
class EvidenceSelectionRequest:
    contract_version: str
    decision_cutoff: datetime
    sealed_ingestion_cutoff: datetime
    security: SecurityIdentity
    completed_session: CompletedSession
    policy: SelectorPolicy
    candidates: tuple[EvidenceCandidate, ...]

    def __post_init__(self) -> None:
        candidate_ids = tuple(
            str(UUID(candidate.evidence_id)) for candidate in self.candidates
        )
        if len(set(candidate_ids)) != len(candidate_ids):
            raise UnifiedEvidenceContractViolation(
                "Selector candidate evidence identifiers must be unique"
            )

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> EvidenceSelectionRequest:
        _require_exact_keys(
            payload,
            {
                "contractVersion",
                "decisionTiming",
                "security",
                "completedSession",
                "selectorPolicy",
                "candidates",
            },
            "evidenceSelectionRequest",
        )
        if payload.get("contractVersion") != CONTRACT_VERSION:
            raise UnifiedEvidenceContractViolation(
                "Unsupported unified evidence contract version"
            )
        timing = required_object(payload, "decisionTiming")
        _require_exact_keys(
            timing,
            {"decisionCutoff", "sealedIngestionCutoff"},
            "decisionTiming",
        )
        decision_cutoff = required_timestamp(timing, "decisionCutoff")
        sealed_ingestion_cutoff = required_timestamp(
            timing, "sealedIngestionCutoff"
        )
        if decision_cutoff > sealed_ingestion_cutoff:
            raise UnifiedEvidenceContractViolation(
                "Decision cutoff cannot exceed sealed ingestion cutoff"
            )
        security = SecurityIdentity.parse(required_object(payload, "security"))
        session = CompletedSession.parse(
            required_object(payload, "completedSession"),
            decision_cutoff=decision_cutoff,
            sealed_ingestion_cutoff=sealed_ingestion_cutoff,
        )
        if session.mic != security.mic:
            raise UnifiedEvidenceContractViolation(
                "Completed-session MIC must match the selected listing"
            )
        policy = SelectorPolicy.parse(required_object(payload, "selectorPolicy"))
        _validate_request_domain_bindings(policy, security, session)
        raw_candidates = payload.get("candidates")
        if not isinstance(raw_candidates, list):
            raise UnifiedEvidenceContractViolation(
                "Selector candidates must be a list"
            )
        candidates = tuple(
            EvidenceCandidate.parse(_required_dict(candidate, "candidate"))
            for candidate in raw_candidates
        )
        return cls(
            contract_version=CONTRACT_VERSION,
            decision_cutoff=decision_cutoff,
            sealed_ingestion_cutoff=sealed_ingestion_cutoff,
            security=security,
            completed_session=session,
            policy=policy,
            candidates=candidates,
        )


def applicability_for_company_type(company_type: str) -> ModelApplicability:
    """Return generic Fundamental Value applicability without running a model."""

    if company_type == "MATURE_OPERATING_COMPANY":
        return ModelApplicability.APPLICABLE
    if company_type in {
        "FINANCIAL",
        "BANK",
        "INSURER",
        "REIT",
        "RESOURCE",
        "BIOTECHNOLOGY",
        "EMERGING_GROWTH",
        "SPECIAL_SITUATION",
    }:
        return ModelApplicability.SPECIALIZED_MODEL_REQUIRED
    if company_type == "BENCHMARK":
        return ModelApplicability.NOT_APPLICABLE
    return ModelApplicability.INSUFFICIENT_EVIDENCE


def _validate_request_domain_bindings(
    policy: SelectorPolicy,
    security: SecurityIdentity,
    session: CompletedSession,
) -> None:
    constraints = policy.domain_constraints
    if policy.domain == EvidenceDomain.DAILY_PRICE:
        if (
            constraints["sessionDate"] != session.session_date.isoformat()
            or constraints["currency"] != security.currency
            or constraints["mic"] != security.mic
            or constraints["listingId"] != security.listing_id
        ):
            raise UnifiedEvidenceContractViolation(
                "Daily-price request constraints must bind to the selected "
                "listing and completed session"
            )
    elif policy.domain == EvidenceDomain.FUNDAMENTAL:
        if constraints["metricCode"] != policy.field_code:
            raise UnifiedEvidenceContractViolation(
                "Fundamental selector field must equal the requested metric"
            )
    elif policy.domain == EvidenceDomain.LIQUIDITY:
        if (
            constraints["windowEndSessionDate"]
            != session.session_date.isoformat()
            or constraints["currency"] != security.currency
        ):
            raise UnifiedEvidenceContractViolation(
                "Liquidity constraints must bind to the completed session and currency"
            )


def _required_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UnifiedEvidenceContractViolation(f"{label} must be an object")
    return value


def _required_sha256(payload: dict[str, Any], name: str) -> str:
    value = required_string(payload, name)
    if SHA256_PATTERN.fullmatch(value) is None:
        raise UnifiedEvidenceContractViolation(
            f"{name} must be a lowercase sha256 content hash"
        )
    return value


def _required_uuid_string(payload: dict[str, Any], name: str) -> str:
    value = required_string(payload, name)
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise UnifiedEvidenceContractViolation(
            f"{name} must be a canonical UUID"
        ) from exc


def _optional_uuid_string(payload: dict[str, Any], name: str) -> str | None:
    if name not in payload or payload[name] is None:
        return None
    return _required_uuid_string(payload, name)


def _require_exact_keys(
    payload: dict[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(payload) != expected:
        raise UnifiedEvidenceContractViolation(
            f"{label} fields must equal {sorted(expected)}"
        )


def _require_allowed_keys(
    payload: dict[str, Any],
    allowed: set[str],
    required: set[str],
    label: str,
) -> None:
    unknown = set(payload) - allowed
    missing = required - set(payload)
    if unknown or missing:
        raise UnifiedEvidenceContractViolation(
            f"{label} has unknown {sorted(unknown)} or missing {sorted(missing)} fields"
        )


def _validate_layer_boundary(
    payload: dict[str, Any],
    *,
    layer: EvidenceLayer,
    state: DataState,
    lineage_hash: str,
) -> tuple[str | None, tuple[EvidenceParentReference, ...]]:
    if layer == EvidenceLayer.NORMALIZED_OBSERVATION:
        raw_manifest = required_object(payload, "rawManifest")
        _require_exact_keys(
            raw_manifest,
            {"storageClass", "payloadStoredInGit", "sourceContentHash"},
            "rawManifest",
        )
        if (
            raw_manifest.get("storageClass") != PRIVATE_RAW_STORAGE_CLASS
            or raw_manifest.get("payloadStoredInGit") is not False
        ):
            raise UnifiedEvidenceContractViolation(
                "Licensed raw payloads must remain in private Git-ignored storage"
            )
        if _required_sha256(raw_manifest, "sourceContentHash") != lineage_hash:
            raise UnifiedEvidenceContractViolation(
                "Raw manifest and lineage content hashes must match"
            )
        if "derivation" in payload:
            raise UnifiedEvidenceContractViolation(
                "Normalized observations cannot declare engine derivation"
            )
        return None, ()

    if "rawManifest" in payload:
        raise UnifiedEvidenceContractViolation(
            "Engine-derived evidence references parent evidence, not raw payloads"
        )
    derivation = required_object(payload, "derivation")
    _require_exact_keys(
        derivation,
        {
            "derivationVersion",
            "inputEvidenceReferences",
            "outputContentHash",
        },
        "derivation",
    )
    version = required_string(derivation, "derivationVersion")
    raw_references = derivation.get("inputEvidenceReferences")
    if not isinstance(raw_references, list) or not all(
        isinstance(item, dict) for item in raw_references
    ):
        raise UnifiedEvidenceContractViolation(
            "Engine derivation input evidence references must be a list"
        )
    if state == DataState.VALID and not raw_references:
        raise UnifiedEvidenceContractViolation(
            "VALID engine derivation requires explicit input evidence references"
        )
    if state != DataState.VALID and raw_references:
        raise UnifiedEvidenceContractViolation(
            "Non-VALID engine derivation cannot claim input evidence parents"
        )
    references = tuple(
        EvidenceParentReference.parse(item) for item in raw_references
    )
    if (
        len({item.evidence_id for item in references}) != len(references)
        or len({item.normalized_record_hash for item in references})
        != len(references)
    ):
        raise UnifiedEvidenceContractViolation(
            "Engine derivation input evidence references must be unique"
        )
    if (
        _required_sha256(derivation, "outputContentHash")
        != _required_sha256(required_object(payload, "lineage"), "normalizedRecordHash")
    ):
        raise UnifiedEvidenceContractViolation(
            "Derivation output hash must bind to the canonical record hash"
        )
    return version, references
