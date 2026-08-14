from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from equity_analysis.dual_system_contract import (
    DataState as V22DataState,
)
from equity_analysis.dual_system_contract import (
    EvidenceClaimClass,
    EvidenceStrictness,
    ModelApplicability,
)
from equity_analysis.evidence_foundation.contracts_v1 import (
    CONTRACT_VERSION as EVIDENCE_CONTRACT_VERSION,
)
from equity_analysis.evidence_foundation.contracts_v1 import (
    SELECTOR_VERSION,
    CompletedSession,
    EvidenceDomain,
    EvidenceLayer,
    SecurityIdentity,
)
from equity_analysis.evidence_foundation.persistence_v1 import (
    ModelApplicabilityRouting,
    PersistedSelectorAggregate,
    _request_hash,
    _request_id,
    _result_hash,
)
from equity_analysis.evidence_foundation.selector_v1 import select_evidence
from equity_analysis.fundamental_value.contracts_v1 import (
    AGGREGATION_VERSION,
    MODEL_VERSION,
    RISK_CAP_VERSION,
    STRATEGY_VERSION,
    Applicability,
    CompanyType,
    DataState,
)
from equity_analysis.fundamental_value.core_v1 import (
    ASSUMPTION_POLICY_VERSION,
    FORMULA_VERSION,
    FundamentalValueInputsV1,
    MetricEvidence,
)

ASSEMBLY_VERSION = "fundamental-value-v22-assembly-v1.0.0"
APPLICABILITY_ROUTING_VERSION = "fundamental-value-applicability-v1.0.0"
MANIFEST_VERSION = "fundamental-value-assembly-manifest-v1.0.0"
CLASSIFICATION_POLICY_VERSION = "fundamental-value-company-type-selection-v1.0.0"
CLASSIFICATION_NORMALIZATION_VERSION = "canonical-classification-v1.0.0"
CLASSIFICATION_FRESHNESS_VERSION = "classification-current-v1.0.0"
DAILY_PRICE_POLICY_VERSION = "daily-price-selection-v1.0.0"
DAILY_PRICE_NORMALIZATION_VERSION = "canonical-equity-v1.0.0"
DAILY_PRICE_FRESHNESS_VERSION = "daily-price-completed-session-v1.0.0"
FUNDAMENTAL_NORMALIZATION_VERSION = "canonical-fundamental-v1.0.0"
FUNDAMENTAL_FRESHNESS_VERSION = "fundamental-quarterly-freshness-v1.0.0"
FUNDAMENTAL_MAPPING_VERSION = "fundamental-value-mapping-v1.0.0"
HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
MIN_PROJECTION_YEARS = 3
MAX_PROJECTION_YEARS = 10


class AssemblyViolation(ValueError):
    """Raised when sealed V22 evidence cannot be assembled safely."""


class OperandSourceKind(StrEnum):
    DAILY_PRICE = "DAILY_PRICE"
    DIRECT_FUNDAMENTAL = "DIRECT_FUNDAMENTAL"
    DERIVATION_REQUIRED = "DERIVATION_REQUIRED"
    POLICY_EVIDENCE_REQUIRED = "POLICY_EVIDENCE_REQUIRED"


@dataclass(frozen=True)
class AssemblyVersionSetV1:
    evidence_contract_version: str = EVIDENCE_CONTRACT_VERSION
    selector_version: str = SELECTOR_VERSION
    applicability_routing_version: str = APPLICABILITY_ROUTING_VERSION
    model_version: str = MODEL_VERSION
    strategy_version: str = STRATEGY_VERSION
    formula_version: str = FORMULA_VERSION
    assumption_policy_version: str = ASSUMPTION_POLICY_VERSION
    aggregation_version: str = AGGREGATION_VERSION
    risk_policy_version: str = RISK_CAP_VERSION
    assembly_version: str = ASSEMBLY_VERSION

    def validate(self) -> None:
        if self != AssemblyVersionSetV1():
            raise AssemblyViolation("ASSEMBLY_VERSION_SET_DRIFT")

    def to_manifest(self) -> dict[str, str]:
        return {
            "evidenceContractVersion": self.evidence_contract_version,
            "selectorVersion": self.selector_version,
            "applicabilityRoutingVersion": self.applicability_routing_version,
            "modelVersion": self.model_version,
            "strategyVersion": self.strategy_version,
            "formulaVersion": self.formula_version,
            "assumptionPolicyVersion": self.assumption_policy_version,
            "aggregationVersion": self.aggregation_version,
            "riskPolicyVersion": self.risk_policy_version,
            "assemblyVersion": self.assembly_version,
        }


@dataclass(frozen=True)
class OperandRequirementV1:
    operand_code: str
    source_kind: OperandSourceKind
    field_code: str | None
    unit: str | None
    currency_bound: bool
    fiscal_period: str | None
    nonnegative: bool
    required_for_core: bool = True


@dataclass(frozen=True)
class VerifiedSelectorBindingV1:
    operand_code: str
    aggregate: PersistedSelectorAggregate
    request_content_hash: str
    result_content_hash: str
    selected_evidence_id: str | None
    selected_source_content_hash: str | None
    selected_normalized_record_hash: str | None
    selected_source_revision: int | None

    @classmethod
    def from_persisted(
        cls,
        operand_code: str,
        aggregate: PersistedSelectorAggregate,
    ) -> VerifiedSelectorBindingV1:
        selected = aggregate.result.selected
        return cls(
            operand_code=operand_code,
            aggregate=aggregate,
            request_content_hash=_request_hash(aggregate.request),
            result_content_hash=_result_hash(aggregate.request, aggregate.result),
            selected_evidence_id=selected.evidence_id if selected is not None else None,
            selected_source_content_hash=(
                selected.source_content_hash if selected is not None else None
            ),
            selected_normalized_record_hash=(
                selected.normalized_record_hash if selected is not None else None
            ),
            selected_source_revision=(selected.source_revision if selected is not None else None),
        )

    def validate_seal(self) -> None:
        if not self.operand_code.strip():
            raise AssemblyViolation("EMPTY_OPERAND_BINDING")
        for content_hash in (self.request_content_hash, self.result_content_hash):
            if HASH_PATTERN.fullmatch(content_hash) is None:
                raise AssemblyViolation("SELECTOR_CONTENT_HASH_INVALID")
        if self.aggregate.request_id != str(_request_id(self.aggregate.request)):
            raise AssemblyViolation("SELECTOR_REQUEST_ID_DRIFT")
        if self.request_content_hash != _request_hash(self.aggregate.request):
            raise AssemblyViolation("SELECTOR_REQUEST_HASH_DRIFT")
        if self.result_content_hash != _result_hash(self.aggregate.request, self.aggregate.result):
            raise AssemblyViolation("SELECTOR_RESULT_HASH_DRIFT")
        if self.aggregate.result != select_evidence(self.aggregate.request):
            raise AssemblyViolation("SELECTOR_RESULT_REPLAY_DRIFT")
        if self.aggregate.result.selector_version != SELECTOR_VERSION:
            raise AssemblyViolation("SELECTOR_VERSION_DRIFT")
        selected = self.aggregate.result.selected
        actual_seal = (
            (
                selected.evidence_id,
                selected.source_content_hash,
                selected.normalized_record_hash,
                selected.source_revision,
            )
            if selected is not None
            else (None, None, None, None)
        )
        expected_seal = (
            self.selected_evidence_id,
            self.selected_source_content_hash,
            self.selected_normalized_record_hash,
            self.selected_source_revision,
        )
        if actual_seal != expected_seal:
            raise AssemblyViolation("SELECTED_EVIDENCE_SEAL_DRIFT")


@dataclass(frozen=True)
class EvidenceSealV1:
    operand_code: str
    request_id: str
    request_content_hash: str
    result_content_hash: str
    selector_policy_version: str
    selector_version: str
    state: DataState
    reason_code: str
    evidence_id: str | None
    source_content_hash: str | None
    normalized_record_hash: str | None
    source_revision: int | None
    effective_at: datetime | None
    available_at: datetime | None
    ingested_at: datetime | None
    freshness_policy_version: str | None
    normalization_version: str | None
    provider_schema_version: str | None
    adapter_version: str | None
    tolerance_policy_version: str | None
    derivation_version: str | None

    def to_manifest(self) -> dict[str, Any]:
        return {
            "operandCode": self.operand_code,
            "requestId": self.request_id,
            "requestContentHash": self.request_content_hash,
            "resultContentHash": self.result_content_hash,
            "selectorPolicyVersion": self.selector_policy_version,
            "selectorVersion": self.selector_version,
            "state": self.state.value,
            "reasonCode": self.reason_code,
            "evidenceId": self.evidence_id,
            "sourceContentHash": self.source_content_hash,
            "normalizedRecordHash": self.normalized_record_hash,
            "sourceRevision": self.source_revision,
            "effectiveAt": _instant(self.effective_at),
            "availableAt": _instant(self.available_at),
            "ingestedAt": _instant(self.ingested_at),
            "freshnessPolicyVersion": self.freshness_policy_version,
            "normalizationVersion": self.normalization_version,
            "providerSchemaVersion": self.provider_schema_version,
            "adapterVersion": self.adapter_version,
            "tolerancePolicyVersion": self.tolerance_policy_version,
            "derivationVersion": self.derivation_version,
        }


@dataclass(frozen=True)
class AssembledOperandV1:
    operand_code: str
    state: DataState
    reason_codes: tuple[str, ...]
    evidence_seal: EvidenceSealV1 | None
    metric_evidence: MetricEvidence

    def to_manifest(self) -> dict[str, Any]:
        return {
            "operandCode": self.operand_code,
            "state": self.state.value,
            "reasonCodes": list(self.reason_codes),
            "evidence": (
                self.evidence_seal.to_manifest() if self.evidence_seal is not None else None
            ),
        }


@dataclass(frozen=True)
class FundamentalValueAssemblyRequestV1:
    routing: ModelApplicabilityRouting
    classification: VerifiedSelectorBindingV1
    operand_bindings: tuple[VerifiedSelectorBindingV1, ...]
    versions: AssemblyVersionSetV1 = AssemblyVersionSetV1()
    projection_years: int = 5

    def __post_init__(self) -> None:
        _validate_projection_years(self.projection_years)


@dataclass(frozen=True)
class OperandSelectorRequestIdV1:
    operand_code: str
    request_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.operand_code, str) or not self.operand_code.strip():
            raise AssemblyViolation("EMPTY_OPERAND_REQUEST_CODE")
        _validate_canonical_uuid(self.request_id, "OPERAND_SELECTOR_REQUEST_ID_INVALID")


@dataclass(frozen=True)
class FundamentalValueAssemblyByIdRequestV1:
    routing_id: str
    classification_request_id: str
    operand_request_ids: tuple[OperandSelectorRequestIdV1, ...]
    expected_security: SecurityIdentity
    expected_completed_session: CompletedSession
    expected_decision_cutoff: datetime
    expected_sealed_ingestion_cutoff: datetime
    versions: AssemblyVersionSetV1 = AssemblyVersionSetV1()
    projection_years: int = 5

    def __post_init__(self) -> None:
        _validate_canonical_uuid(self.routing_id, "APPLICABILITY_ROUTING_ID_INVALID")
        _validate_canonical_uuid(
            self.classification_request_id, "CLASSIFICATION_SELECTOR_REQUEST_ID_INVALID"
        )
        if type(self.operand_request_ids) is not tuple:
            raise AssemblyViolation("OPERAND_REQUEST_IDS_MUST_BE_TUPLE")
        if not all(type(item) is OperandSelectorRequestIdV1 for item in self.operand_request_ids):
            raise AssemblyViolation("OPERAND_REQUEST_ID_MEMBER_INVALID")
        for durable_id in self.expected_security.durable_tuple:
            _validate_canonical_uuid(durable_id, "EXPECTED_SECURITY_IDENTITY_INVALID")
        _validate_projection_years(self.projection_years)
        if (
            self.expected_decision_cutoff.tzinfo is None
            or self.expected_sealed_ingestion_cutoff.tzinfo is None
            or self.expected_decision_cutoff > self.expected_sealed_ingestion_cutoff
        ):
            raise AssemblyViolation("EXPECTED_DECISION_TIMING_INVALID")


class FundamentalValueV22RepositoryV1(Protocol):
    """Trusted-adapter seam; production provenance requires V22 repository readback."""

    def load_selector_aggregate(self, request_id: str) -> PersistedSelectorAggregate: ...

    def load_applicability_routing(self, routing_id: str) -> ModelApplicabilityRouting: ...


@dataclass(frozen=True)
class FundamentalValueAssemblyResultV1:
    state: DataState
    reason_codes: tuple[str, ...]
    company_type: CompanyType
    applicability: Applicability
    security: SecurityIdentity
    routing_id: str
    routing_content_hash: str
    routing_revision: int
    classification_evidence_id: str
    classification_seal: EvidenceSealV1
    completed_session_date: str
    decision_cutoff: datetime
    sealed_ingestion_cutoff: datetime
    projection_years: int
    versions: AssemblyVersionSetV1
    operands: tuple[AssembledOperandV1, ...]
    inputs: FundamentalValueInputsV1 | None
    manifest_content_hash: str
    core_invocation_authorized: bool = False

    def __post_init__(self) -> None:
        if self.state == DataState.VALID and self.reason_codes:
            raise AssemblyViolation("VALID_ASSEMBLY_CANNOT_HAVE_REASON_CODES")
        if self.state != DataState.VALID and not self.reason_codes:
            raise AssemblyViolation("NON_VALID_ASSEMBLY_REQUIRES_REASON_CODES")

    def manifest_payload(self) -> dict[str, Any]:
        payload = {
            "manifestVersion": MANIFEST_VERSION,
            "state": self.state.value,
            "reasonCodes": list(self.reason_codes),
            "companyType": self.company_type.value,
            "applicability": self.applicability.value,
            "security": {
                "securityId": self.security.security_id,
                "companyId": self.security.company_id,
                "instrumentId": self.security.instrument_id,
                "shareClassId": self.security.share_class_id,
                "listingId": self.security.listing_id,
                "tickerAssignmentId": self.security.ticker_assignment_id,
                "ticker": self.security.ticker,
                "mic": self.security.mic,
                "currency": self.security.currency,
            },
            "routing": {
                "routingId": self.routing_id,
                "routingContentHash": self.routing_content_hash,
                "routingRevision": self.routing_revision,
                "classificationEvidenceId": self.classification_evidence_id,
                "classificationEvidence": self.classification_seal.to_manifest(),
            },
            "timing": {
                "completedSessionDate": self.completed_session_date,
                "decisionCutoff": _instant(self.decision_cutoff),
                "sealedIngestionCutoff": _instant(self.sealed_ingestion_cutoff),
            },
            "projectionYears": self.projection_years,
            "versions": self.versions.to_manifest(),
            "operands": [operand.to_manifest() for operand in self.operands],
            "coreInvocationAuthorized": self.core_invocation_authorized,
        }
        _reject_manifest_leakage(payload)
        return payload


OPERAND_REQUIREMENTS = (
    OperandRequirementV1(
        "reference_price", OperandSourceKind.DAILY_PRICE, "CLOSE_PRICE", None, True, None, True
    ),
    OperandRequirementV1(
        "diluted_shares",
        OperandSourceKind.DIRECT_FUNDAMENTAL,
        "DILUTED_SHARES",
        "SHARES",
        False,
        "TTM",
        True,
    ),
    OperandRequirementV1(
        "cash",
        OperandSourceKind.DIRECT_FUNDAMENTAL,
        "CASH_AND_EQUIVALENTS",
        "CURRENCY",
        True,
        "INSTANT",
        True,
    ),
    OperandRequirementV1(
        "debt",
        OperandSourceKind.DIRECT_FUNDAMENTAL,
        "TOTAL_DEBT",
        "CURRENCY",
        True,
        "INSTANT",
        True,
    ),
    OperandRequirementV1(
        "ebit",
        OperandSourceKind.DIRECT_FUNDAMENTAL,
        "OPERATING_INCOME",
        "CURRENCY",
        True,
        "TTM",
        False,
    ),
    OperandRequirementV1(
        "tax_rate", OperandSourceKind.DERIVATION_REQUIRED, None, "RATIO", False, "TTM", False
    ),
    OperandRequirementV1(
        "depreciation_and_amortization",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "CURRENCY",
        True,
        "TTM",
        True,
    ),
    OperandRequirementV1(
        "capital_expenditures",
        OperandSourceKind.DIRECT_FUNDAMENTAL,
        "CAPITAL_EXPENDITURE",
        "CURRENCY",
        True,
        "TTM",
        True,
    ),
    OperandRequirementV1(
        "change_in_working_capital",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "CURRENCY",
        True,
        "TTM",
        False,
    ),
    OperandRequirementV1(
        "normalized_free_cash_flow",
        OperandSourceKind.DIRECT_FUNDAMENTAL,
        "FREE_CASH_FLOW",
        "CURRENCY",
        True,
        "TTM",
        False,
    ),
    OperandRequirementV1(
        "normalized_after_tax_operating_earnings",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "CURRENCY",
        True,
        "TTM",
        False,
    ),
    OperandRequirementV1(
        "ebitda", OperandSourceKind.DERIVATION_REQUIRED, None, "CURRENCY", True, "TTM", False
    ),
    OperandRequirementV1(
        "comparable_ev_to_ebitda",
        OperandSourceKind.POLICY_EVIDENCE_REQUIRED,
        None,
        "RATIO",
        False,
        None,
        False,
        False,
    ),
    OperandRequirementV1(
        "conservative_growth_rate",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "RATIO",
        False,
        None,
        False,
    ),
    OperandRequirementV1(
        "discount_rate",
        OperandSourceKind.POLICY_EVIDENCE_REQUIRED,
        None,
        "RATIO",
        False,
        None,
        False,
    ),
    OperandRequirementV1(
        "terminal_growth_rate",
        OperandSourceKind.POLICY_EVIDENCE_REQUIRED,
        None,
        "RATIO",
        False,
        None,
        False,
    ),
    OperandRequirementV1(
        "net_distribution_yield",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "RATIO",
        False,
        "TTM",
        False,
        False,
    ),
    OperandRequirementV1(
        "return_on_invested_capital",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "RATIO",
        False,
        "TTM",
        False,
    ),
    OperandRequirementV1(
        "operating_margin",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "RATIO",
        False,
        "TTM",
        False,
    ),
    OperandRequirementV1(
        "free_cash_flow_margin",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "RATIO",
        False,
        "TTM",
        False,
    ),
    OperandRequirementV1(
        "earnings_stability",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "RATIO",
        False,
        None,
        False,
    ),
    OperandRequirementV1(
        "cash_flow_stability",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "RATIO",
        False,
        None,
        False,
    ),
    OperandRequirementV1(
        "net_debt_to_ebitda",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "RATIO",
        False,
        "TTM",
        False,
    ),
    OperandRequirementV1(
        "interest_coverage",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "RATIO",
        False,
        "TTM",
        False,
    ),
    OperandRequirementV1(
        "current_ratio",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "RATIO",
        False,
        "INSTANT",
        False,
    ),
    OperandRequirementV1(
        "diluted_share_growth",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "RATIO",
        False,
        None,
        False,
    ),
    OperandRequirementV1(
        "cash_flow_to_net_income",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "RATIO",
        False,
        "TTM",
        False,
    ),
    OperandRequirementV1(
        "incremental_return_on_invested_capital",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "RATIO",
        False,
        None,
        False,
    ),
    OperandRequirementV1(
        "acquisition_discipline",
        OperandSourceKind.POLICY_EVIDENCE_REQUIRED,
        None,
        "RATIO",
        False,
        None,
        False,
    ),
    OperandRequirementV1(
        "shareholder_distribution_coverage",
        OperandSourceKind.DERIVATION_REQUIRED,
        None,
        "RATIO",
        False,
        "TTM",
        False,
    ),
    OperandRequirementV1(
        "cyclicality_risk",
        OperandSourceKind.POLICY_EVIDENCE_REQUIRED,
        None,
        "SCORE",
        False,
        None,
        False,
    ),
    OperandRequirementV1(
        "concentration_risk",
        OperandSourceKind.POLICY_EVIDENCE_REQUIRED,
        None,
        "SCORE",
        False,
        None,
        False,
    ),
    OperandRequirementV1(
        "event_risk", OperandSourceKind.POLICY_EVIDENCE_REQUIRED, None, "SCORE", False, None, False
    ),
    OperandRequirementV1(
        "debt_maturity_schedule",
        OperandSourceKind.POLICY_EVIDENCE_REQUIRED,
        None,
        "COVERAGE",
        False,
        None,
        False,
        False,
    ),
)
REQUIREMENT_BY_OPERAND = {item.operand_code: item for item in OPERAND_REQUIREMENTS}


def assemble_fundamental_value_from_v22_v1(
    repository: FundamentalValueV22RepositoryV1,
    request: FundamentalValueAssemblyByIdRequestV1,
) -> FundamentalValueAssemblyResultV1:
    request.versions.validate()
    references: dict[str, str] = {}
    request_ids = {request.classification_request_id}
    for reference in request.operand_request_ids:
        if reference.operand_code in references:
            raise AssemblyViolation("DUPLICATE_OPERAND_REQUEST_REFERENCE")
        if reference.request_id in request_ids:
            raise AssemblyViolation("DUPLICATE_PERSISTED_SELECTOR_REQUEST_ID")
        references[reference.operand_code] = reference.request_id
        request_ids.add(reference.request_id)
    try:
        routing = repository.load_applicability_routing(request.routing_id)
    except LookupError as error:
        raise AssemblyViolation("PERSISTED_APPLICABILITY_ROUTING_NOT_FOUND") from error
    if routing.routing_id != request.routing_id:
        raise AssemblyViolation("PERSISTED_APPLICABILITY_ROUTING_ID_MISMATCH")
    classification = _load_repository_binding(
        repository,
        operand_code="company_type",
        request_id=request.classification_request_id,
    )
    anchor = classification.aggregate.request
    if anchor.security != request.expected_security:
        raise AssemblyViolation("PERSISTED_SECURITY_IDENTITY_MISMATCH")
    if anchor.completed_session != request.expected_completed_session:
        raise AssemblyViolation("PERSISTED_COMPLETED_SESSION_MISMATCH")
    if anchor.decision_cutoff != request.expected_decision_cutoff:
        raise AssemblyViolation("PERSISTED_DECISION_CUTOFF_MISMATCH")
    if anchor.sealed_ingestion_cutoff != request.expected_sealed_ingestion_cutoff:
        raise AssemblyViolation("PERSISTED_SEALED_INGESTION_CUTOFF_MISMATCH")
    bindings = tuple(
        _load_repository_binding(
            repository,
            operand_code=operand_code,
            request_id=request_id,
        )
        for operand_code, request_id in references.items()
    )
    return _assemble_verified_fundamental_value_inputs_v1(
        FundamentalValueAssemblyRequestV1(
            routing=routing,
            classification=classification,
            operand_bindings=bindings,
            versions=request.versions,
            projection_years=request.projection_years,
        )
    )


def _load_repository_binding(
    repository: FundamentalValueV22RepositoryV1,
    *,
    operand_code: str,
    request_id: str,
) -> VerifiedSelectorBindingV1:
    try:
        aggregate = repository.load_selector_aggregate(request_id)
    except LookupError as error:
        raise AssemblyViolation("PERSISTED_SELECTOR_REQUEST_NOT_FOUND") from error
    if aggregate.request_id != request_id:
        raise AssemblyViolation("PERSISTED_SELECTOR_REQUEST_ID_MISMATCH")
    return VerifiedSelectorBindingV1.from_persisted(operand_code, aggregate)


def _assemble_verified_fundamental_value_inputs_v1(
    request: FundamentalValueAssemblyRequestV1,
) -> FundamentalValueAssemblyResultV1:
    request.versions.validate()
    classification = request.classification
    classification.validate_seal()
    anchor = classification.aggregate.request
    security = anchor.security
    _validate_classification_and_routing(request.routing, classification)
    company_type = _core_company_type(request.routing.company_type)
    applicability = _core_applicability(request.routing.applicability, company_type)
    if request.routing.effective_at > anchor.decision_cutoff:
        raise AssemblyViolation("APPLICABILITY_ROUTING_AFTER_DECISION_CUTOFF")

    if applicability != Applicability.APPLICABLE:
        return _result(
            state=(
                DataState.NOT_APPLICABLE
                if applicability
                in {Applicability.SPECIALIZED_MODEL_REQUIRED, Applicability.NOT_APPLICABLE}
                else DataState.MISSING
            ),
            reasons=(f"APPLICABILITY_{applicability.value}",),
            company_type=company_type,
            applicability=applicability,
            security=security,
            routing=request.routing,
            classification_seal=_evidence_seal(classification),
            anchor=anchor,
            versions=request.versions,
            projection_years=request.projection_years,
            operands=(),
            inputs=None,
        )

    bindings = _validate_binding_set(request.operand_bindings)
    operands: list[AssembledOperandV1] = []
    selected_ids: set[str] = {request.routing.classification_evidence_id}
    for requirement in OPERAND_REQUIREMENTS:
        binding = bindings.get(requirement.operand_code)
        if binding is None:
            operands.append(_missing_operand(requirement, "OPERAND_SELECTOR_BINDING_MISSING"))
            continue
        binding.validate_seal()
        _validate_cross_selection(anchor, binding.aggregate.request)
        selected = binding.aggregate.result.selected
        if selected is not None:
            if selected.evidence_id in selected_ids:
                raise AssemblyViolation("DUPLICATE_SELECTED_EVIDENCE_ID")
            selected_ids.add(selected.evidence_id)
        operands.append(_assemble_operand(requirement, binding, security))

    required_failures = tuple(
        operand
        for operand in operands
        if REQUIREMENT_BY_OPERAND[operand.operand_code].required_for_core
        and operand.state != DataState.VALID
    )
    inputs = None
    if not required_failures:
        values = {operand.operand_code: operand.metric_evidence for operand in operands}
        inputs = FundamentalValueInputsV1(
            company_type=company_type,
            applicability=applicability,
            projection_years=request.projection_years,
            currency=security.currency,
            **values,
        )
    state = (
        _state_precedence(tuple(operand.state for operand in required_failures))
        if required_failures
        else DataState.VALID
    )
    reasons = (
        tuple(sorted({reason for operand in required_failures for reason in operand.reason_codes}))
        if required_failures
        else ()
    )
    return _result(
        state=state,
        reasons=reasons,
        company_type=company_type,
        applicability=applicability,
        security=security,
        routing=request.routing,
        classification_seal=_evidence_seal(classification),
        anchor=anchor,
        versions=request.versions,
        projection_years=request.projection_years,
        operands=tuple(operands),
        inputs=inputs,
    )


def _assemble_operand(
    requirement: OperandRequirementV1,
    binding: VerifiedSelectorBindingV1,
    security: SecurityIdentity,
) -> AssembledOperandV1:
    result = binding.aggregate.result
    seal = _evidence_seal(binding)
    _validate_operand_selector_policy(requirement, binding.aggregate.request, security)
    if result.state != V22DataState.VALID or result.selected is None:
        state = DataState(result.state.value)
        reason = result.reason_code or "NONVALID_SELECTOR_RESULT"
        return AssembledOperandV1(
            requirement.operand_code,
            state,
            (reason,),
            seal,
            MetricEvidence(state, reason_code=reason),
        )
    if requirement.source_kind in {
        OperandSourceKind.DERIVATION_REQUIRED,
        OperandSourceKind.POLICY_EVIDENCE_REQUIRED,
    }:
        raise AssemblyViolation("UNEXPECTED_DIRECT_BINDING_FOR_DERIVED_OPERAND")
    candidate = result.selected
    if candidate.available_at > binding.aggregate.request.decision_cutoff:
        raise AssemblyViolation("EVIDENCE_AVAILABLE_AFTER_DECISION_CUTOFF")
    if candidate.ingested_at > binding.aggregate.request.sealed_ingestion_cutoff:
        raise AssemblyViolation("EVIDENCE_INGESTED_AFTER_SEALED_CUTOFF")
    if candidate.source_revision < 1:
        raise AssemblyViolation("SOURCE_REVISION_INVALID")
    data = candidate.canonical_data
    if data is None:
        raise AssemblyViolation("VALID_SELECTED_EVIDENCE_HAS_NO_CANONICAL_DATA")
    if requirement.source_kind == OperandSourceKind.DAILY_PRICE:
        if (
            data["sessionDate"]
            != binding.aggregate.request.completed_session.session_date.isoformat()
        ):
            raise AssemblyViolation("REFERENCE_PRICE_SESSION_MISMATCH")
        if data["currency"] != security.currency:
            raise AssemblyViolation("REFERENCE_PRICE_CURRENCY_MISMATCH")
        if data["adjustmentMode"] != "UNADJUSTED":
            raise AssemblyViolation("REFERENCE_PRICE_ADJUSTMENT_MODE_INVALID")
        if candidate.normalization_version != DAILY_PRICE_NORMALIZATION_VERSION:
            raise AssemblyViolation("REFERENCE_PRICE_NORMALIZATION_VERSION_DRIFT")
        if candidate.freshness_policy_version != DAILY_PRICE_FRESHNESS_VERSION:
            raise AssemblyViolation("REFERENCE_PRICE_FRESHNESS_VERSION_DRIFT")
        value = Decimal(data["close"])
    else:
        if data["metricCode"] != requirement.field_code:
            raise AssemblyViolation("FUNDAMENTAL_METRIC_CODE_MISMATCH")
        if data["unit"] != requirement.unit:
            raise AssemblyViolation("FUNDAMENTAL_UNIT_MISMATCH")
        if candidate.normalization_version != FUNDAMENTAL_NORMALIZATION_VERSION:
            raise AssemblyViolation("FUNDAMENTAL_NORMALIZATION_VERSION_DRIFT")
        if candidate.freshness_policy_version != FUNDAMENTAL_FRESHNESS_VERSION:
            raise AssemblyViolation("FUNDAMENTAL_FRESHNESS_VERSION_DRIFT")
        if data["mappingVersion"] != FUNDAMENTAL_MAPPING_VERSION:
            raise AssemblyViolation("FUNDAMENTAL_MAPPING_VERSION_DRIFT")
        expected_currency = security.currency if requirement.currency_bound else None
        if data["currency"] != expected_currency:
            raise AssemblyViolation("FUNDAMENTAL_CURRENCY_MISMATCH")
        if (
            requirement.fiscal_period is not None
            and data["fiscalPeriod"] != requirement.fiscal_period
        ):
            raise AssemblyViolation("FUNDAMENTAL_PERIOD_SEMANTICS_MISMATCH")
        if data["periodEnd"] > binding.aggregate.request.completed_session.session_date.isoformat():
            raise AssemblyViolation("FUNDAMENTAL_PERIOD_AFTER_COMPLETED_SESSION")
        value = Decimal(data["numericValue"])
    if requirement.nonnegative and value < 0:
        raise AssemblyViolation("FUNDAMENTAL_SIGN_SEMANTICS_MISMATCH")
    return AssembledOperandV1(
        requirement.operand_code,
        DataState.VALID,
        (),
        seal,
        MetricEvidence.valid(value),
    )


def _validate_operand_selector_policy(requirement: OperandRequirementV1, request, security) -> None:
    policy = request.policy
    if requirement.source_kind in {
        OperandSourceKind.DERIVATION_REQUIRED,
        OperandSourceKind.POLICY_EVIDENCE_REQUIRED,
    }:
        raise AssemblyViolation("UNEXPECTED_DIRECT_BINDING_FOR_DERIVED_OPERAND")
    if policy.required_layer != EvidenceLayer.NORMALIZED_OBSERVATION:
        raise AssemblyViolation("OPERAND_SELECTOR_LAYER_INVALID")
    if policy.required_strictness_class != EvidenceStrictness.STRICT_IDENTITY_AND_CHRONOLOGY:
        raise AssemblyViolation("OPERAND_SELECTOR_STRICTNESS_INVALID")
    if requirement.source_kind == OperandSourceKind.DAILY_PRICE:
        if policy.required_claim_class != EvidenceClaimClass.CURRENT_ONLY:
            raise AssemblyViolation("OPERAND_SELECTOR_CLAIM_CLASS_INVALID")
        if policy.domain != EvidenceDomain.DAILY_PRICE or policy.field_code != "CLOSE_PRICE":
            raise AssemblyViolation("REFERENCE_PRICE_SELECTOR_SEMANTICS_INVALID")
        if policy.policy_version != DAILY_PRICE_POLICY_VERSION:
            raise AssemblyViolation("REFERENCE_PRICE_POLICY_VERSION_DRIFT")
        if policy.required_normalization_version != DAILY_PRICE_NORMALIZATION_VERSION:
            raise AssemblyViolation("REFERENCE_PRICE_REQUIRED_NORMALIZATION_VERSION_DRIFT")
        constraints = policy.domain_constraints
        expected_constraints = {
            "sessionDate": request.completed_session.session_date.isoformat(),
            "adjustmentMode": "UNADJUSTED",
            "currency": security.currency,
            "mic": security.mic,
            "listingId": security.listing_id,
        }
        if constraints != expected_constraints:
            raise AssemblyViolation("REFERENCE_PRICE_DOMAIN_CONSTRAINTS_INVALID")
        return
    if policy.domain != EvidenceDomain.FUNDAMENTAL:
        raise AssemblyViolation("FUNDAMENTAL_OPERAND_DOMAIN_INVALID")
    if policy.required_claim_class != EvidenceClaimClass.STRICT_PIT:
        raise AssemblyViolation("OPERAND_SELECTOR_CLAIM_CLASS_INVALID")
    if policy.field_code != requirement.field_code:
        raise AssemblyViolation("FUNDAMENTAL_METRIC_CODE_MISMATCH")
    expected_policy = (
        f"fundamental-value-{requirement.operand_code.replace('_', '-')}-selection-v1.0.0"
    )
    if policy.policy_version != expected_policy:
        raise AssemblyViolation("FUNDAMENTAL_SELECTOR_POLICY_VERSION_DRIFT")
    if policy.required_normalization_version != FUNDAMENTAL_NORMALIZATION_VERSION:
        raise AssemblyViolation("FUNDAMENTAL_REQUIRED_NORMALIZATION_VERSION_DRIFT")
    constraints = policy.domain_constraints
    if (
        constraints.get("metricCode") != requirement.field_code
        or constraints.get("unit") != requirement.unit
        or constraints.get("currency")
        != (security.currency if requirement.currency_bound else None)
        or set(constraints) != {"metricCode", "periodEnd", "unit", "currency"}
        or constraints.get("periodEnd") > request.completed_session.session_date.isoformat()
    ):
        raise AssemblyViolation("FUNDAMENTAL_DOMAIN_CONSTRAINTS_INVALID")


def _missing_operand(
    requirement: OperandRequirementV1,
    missing_reason: str,
) -> AssembledOperandV1:
    reason = (
        f"{requirement.operand_code.upper()}_V22_DERIVATION_REQUIRED"
        if requirement.source_kind == OperandSourceKind.DERIVATION_REQUIRED
        else (
            f"{requirement.operand_code.upper()}_POLICY_EVIDENCE_REQUIRED"
            if requirement.source_kind == OperandSourceKind.POLICY_EVIDENCE_REQUIRED
            else missing_reason
        )
    )
    return AssembledOperandV1(
        requirement.operand_code,
        DataState.MISSING,
        (reason,),
        None,
        MetricEvidence.missing(reason),
    )


def _validate_classification_and_routing(
    routing: ModelApplicabilityRouting,
    classification: VerifiedSelectorBindingV1,
) -> None:
    aggregate = classification.aggregate
    result = aggregate.result
    if classification.operand_code != "company_type":
        raise AssemblyViolation("CLASSIFICATION_BINDING_CODE_INVALID")
    if aggregate.request.policy.domain != EvidenceDomain.CLASSIFICATION:
        raise AssemblyViolation("CLASSIFICATION_DOMAIN_INVALID")
    if aggregate.request.policy.field_code != "COMPANY_TYPE":
        raise AssemblyViolation("CLASSIFICATION_FIELD_INVALID")
    if result.state != V22DataState.VALID or result.selected is None:
        raise AssemblyViolation("CLASSIFICATION_EVIDENCE_NOT_VALID")
    selected = result.selected
    if selected.evidence_id != routing.classification_evidence_id:
        raise AssemblyViolation("ROUTING_CLASSIFICATION_EVIDENCE_ID_MISMATCH")
    if selected.security.company_id != routing.company_id:
        raise AssemblyViolation("ROUTING_COMPANY_ID_MISMATCH")
    if selected.canonical_data is None:
        raise AssemblyViolation("CLASSIFICATION_CANONICAL_DATA_MISSING")
    if selected.canonical_data["companyType"] != routing.company_type:
        raise AssemblyViolation("ROUTING_COMPANY_TYPE_MISMATCH")
    if aggregate.request.policy.policy_version != CLASSIFICATION_POLICY_VERSION:
        raise AssemblyViolation("CLASSIFICATION_POLICY_VERSION_DRIFT")
    if selected.normalization_version != CLASSIFICATION_NORMALIZATION_VERSION:
        raise AssemblyViolation("CLASSIFICATION_NORMALIZATION_VERSION_DRIFT")
    if selected.freshness_policy_version != CLASSIFICATION_FRESHNESS_VERSION:
        raise AssemblyViolation("CLASSIFICATION_FRESHNESS_VERSION_DRIFT")
    if routing.routing_version != APPLICABILITY_ROUTING_VERSION:
        raise AssemblyViolation("APPLICABILITY_ROUTING_VERSION_DRIFT")


def _validate_binding_set(
    bindings: tuple[VerifiedSelectorBindingV1, ...],
) -> dict[str, VerifiedSelectorBindingV1]:
    result: dict[str, VerifiedSelectorBindingV1] = {}
    request_ids: set[str] = set()
    for binding in bindings:
        if binding.operand_code not in REQUIREMENT_BY_OPERAND:
            raise AssemblyViolation("UNKNOWN_OPERAND_BINDING")
        if binding.operand_code in result:
            raise AssemblyViolation("DUPLICATE_OPERAND_BINDING")
        if binding.aggregate.request_id in request_ids:
            raise AssemblyViolation("DUPLICATE_SELECTOR_REQUEST_ID")
        result[binding.operand_code] = binding
        request_ids.add(binding.aggregate.request_id)
    return result


def _validate_cross_selection(anchor, candidate) -> None:
    if candidate.security != anchor.security:
        raise AssemblyViolation("MIXED_DURABLE_SECURITY_IDENTITY")
    if candidate.completed_session != anchor.completed_session:
        raise AssemblyViolation("MIXED_COMPLETED_SESSION_OR_CALENDAR")
    if candidate.decision_cutoff != anchor.decision_cutoff:
        raise AssemblyViolation("MIXED_DECISION_CUTOFF")
    if candidate.sealed_ingestion_cutoff != anchor.sealed_ingestion_cutoff:
        raise AssemblyViolation("MIXED_SEALED_INGESTION_CUTOFF")
    if candidate.contract_version != EVIDENCE_CONTRACT_VERSION:
        raise AssemblyViolation("EVIDENCE_CONTRACT_VERSION_DRIFT")
    if candidate.policy.selector_version != SELECTOR_VERSION:
        raise AssemblyViolation("SELECTOR_VERSION_DRIFT")


def _evidence_seal(binding: VerifiedSelectorBindingV1) -> EvidenceSealV1:
    result = binding.aggregate.result
    selected = result.selected
    return EvidenceSealV1(
        operand_code=binding.operand_code,
        request_id=binding.aggregate.request_id,
        request_content_hash=binding.request_content_hash,
        result_content_hash=binding.result_content_hash,
        selector_policy_version=binding.aggregate.request.policy.policy_version,
        selector_version=result.selector_version,
        state=DataState(result.state.value),
        reason_code=result.reason_code,
        evidence_id=selected.evidence_id if selected is not None else None,
        source_content_hash=(selected.source_content_hash if selected is not None else None),
        normalized_record_hash=(selected.normalized_record_hash if selected is not None else None),
        source_revision=selected.source_revision if selected is not None else None,
        effective_at=selected.effective_at if selected is not None else None,
        available_at=selected.available_at if selected is not None else None,
        ingested_at=selected.ingested_at if selected is not None else None,
        freshness_policy_version=(
            selected.freshness_policy_version if selected is not None else None
        ),
        normalization_version=(selected.normalization_version if selected is not None else None),
        provider_schema_version=(
            selected.provider_schema_version if selected is not None else None
        ),
        adapter_version=selected.adapter_version if selected is not None else None,
        tolerance_policy_version=(
            selected.tolerance_policy_version if selected is not None else None
        ),
        derivation_version=selected.derivation_version if selected is not None else None,
    )


def _core_company_type(v22_company_type: str) -> CompanyType:
    direct = {
        "MATURE_OPERATING_COMPANY": CompanyType.MATURE_OPERATING_COMPANY,
        "BANK": CompanyType.BANK,
        "INSURER": CompanyType.INSURER,
        "REIT": CompanyType.REIT,
        "RESOURCE": CompanyType.RESOURCE,
        "BIOTECHNOLOGY": CompanyType.BIOTECHNOLOGY,
        "FINANCIAL": CompanyType.FINANCIAL,
        "SPECIAL_SITUATION": CompanyType.INCOMPATIBLE_CONGLOMERATE,
        "BENCHMARK": CompanyType.BENCHMARK,
    }
    return direct.get(v22_company_type, CompanyType.INSUFFICIENT_PUBLIC_HISTORY)


def _core_applicability(
    applicability: ModelApplicability,
    company_type: CompanyType,
) -> Applicability:
    if company_type == CompanyType.MATURE_OPERATING_COMPANY:
        return Applicability.APPLICABLE
    if company_type in {
        CompanyType.BANK,
        CompanyType.INSURER,
        CompanyType.REIT,
        CompanyType.RESOURCE,
        CompanyType.BIOTECHNOLOGY,
        CompanyType.FINANCIAL,
        CompanyType.INCOMPATIBLE_CONGLOMERATE,
    }:
        return Applicability.SPECIALIZED_MODEL_REQUIRED
    if company_type == CompanyType.BENCHMARK:
        return Applicability.NOT_APPLICABLE
    if applicability == ModelApplicability.APPLICABLE:
        raise AssemblyViolation("AMBIGUOUS_COMPANY_TYPE_CANNOT_BECOME_APPLICABLE")
    return Applicability.INSUFFICIENT_EVIDENCE


def _result(
    *,
    state: DataState,
    reasons: tuple[str, ...],
    company_type: CompanyType,
    applicability: Applicability,
    security: SecurityIdentity,
    routing: ModelApplicabilityRouting,
    classification_seal: EvidenceSealV1,
    anchor,
    versions: AssemblyVersionSetV1,
    projection_years: int,
    operands: tuple[AssembledOperandV1, ...],
    inputs: FundamentalValueInputsV1 | None,
) -> FundamentalValueAssemblyResultV1:
    draft = FundamentalValueAssemblyResultV1(
        state=state,
        reason_codes=reasons,
        company_type=company_type,
        applicability=applicability,
        security=security,
        routing_id=routing.routing_id,
        routing_content_hash=routing.routing_content_hash,
        routing_revision=routing.routing_revision,
        classification_evidence_id=routing.classification_evidence_id,
        classification_seal=classification_seal,
        completed_session_date=anchor.completed_session.session_date.isoformat(),
        decision_cutoff=anchor.decision_cutoff,
        sealed_ingestion_cutoff=anchor.sealed_ingestion_cutoff,
        projection_years=projection_years,
        versions=versions,
        operands=operands,
        inputs=inputs,
        manifest_content_hash="",
        core_invocation_authorized=inputs is not None and state == DataState.VALID,
    )
    payload = draft.manifest_payload()
    content_hash = _content_hash(payload)
    return FundamentalValueAssemblyResultV1(
        **{**draft.__dict__, "manifest_content_hash": content_hash}
    )


def _state_precedence(states: tuple[DataState, ...]) -> DataState:
    for state in (
        DataState.INVALID,
        DataState.STALE,
        DataState.MISSING,
        DataState.EXCLUDED,
        DataState.NOT_APPLICABLE,
    ):
        if state in states:
            return state
    return DataState.VALID


def _validate_projection_years(value: int) -> None:
    if type(value) is not int or not MIN_PROJECTION_YEARS <= value <= MAX_PROJECTION_YEARS:
        raise AssemblyViolation("PROJECTION_YEARS_OUT_OF_RANGE")


def _validate_canonical_uuid(value: Any, reason: str) -> None:
    if not isinstance(value, str):
        raise AssemblyViolation(reason)
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise AssemblyViolation(reason) from error
    if str(parsed) != value:
        raise AssemblyViolation(reason)


def _content_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _instant(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _reject_manifest_leakage(payload: Any) -> None:
    forbidden = {
        "numericValue",
        "providerCode",
        "providerNativeValue",
        "rawPayload",
        "rawStorageReference",
        "observationReference",
        "score",
        "rank",
        "recommendation",
        "finalPortfolioWeight",
        "trade",
        "order",
    }
    if isinstance(payload, dict):
        leaked = forbidden.intersection(payload)
        if leaked:
            raise AssemblyViolation("MANIFEST_PROVIDER_OR_DECISION_VALUE_LEAKAGE")
        for value in payload.values():
            _reject_manifest_leakage(value)
    elif isinstance(payload, list):
        for value in payload:
            _reject_manifest_leakage(value)


def verify_manifest_content_hash(
    result: FundamentalValueAssemblyResultV1,
) -> None:
    if result.manifest_content_hash != _content_hash(result.manifest_payload()):
        raise AssemblyViolation("ASSEMBLY_MANIFEST_CONTENT_HASH_DRIFT")
    UUID(result.routing_id)
