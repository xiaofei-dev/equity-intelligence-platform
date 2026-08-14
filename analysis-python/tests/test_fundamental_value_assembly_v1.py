from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.dual_system_contract import ModelApplicability
from equity_analysis.evidence_foundation import (
    EvidenceSelectionRequest,
    ModelApplicabilityRouting,
    PersistedSelectorAggregate,
    UnifiedEvidenceContractViolation,
    select_evidence,
)
from equity_analysis.evidence_foundation.persistence_v1 import _request_id
from equity_analysis.fundamental_value.contracts_v1 import (
    Applicability,
    CompanyType,
    DataState,
)
from equity_analysis.fundamental_value.core_v1 import (
    ASSUMPTION_POLICY_VERSION,
    FORMULA_VERSION,
)
from equity_analysis.fundamental_value.evidence_assembly_v1 import (
    APPLICABILITY_ROUTING_VERSION,
    OPERAND_REQUIREMENTS,
    AssemblyVersionSetV1,
    AssemblyViolation,
    FundamentalValueAssemblyByIdRequestV1,
    FundamentalValueAssemblyRequestV1,
    OperandSelectorRequestIdV1,
    VerifiedSelectorBindingV1,
    _assemble_verified_fundamental_value_inputs_v1,
    assemble_fundamental_value_from_v22_v1,
    verify_manifest_content_hash,
)

assemble_fundamental_value_inputs_v1 = _assemble_verified_fundamental_value_inputs_v1

V22_FIXTURE = (
    Path(__file__).parents[2]
    / "contracts"
    / "unified-market-data-evidence-v1"
    / "selector-request.example.json"
)
ASSEMBLY_FIXTURE = (
    Path(__file__).parents[2]
    / "contracts"
    / "fundamental-value-v1"
    / "evidence-assembly-manifest.example.json"
)


def _base_payload() -> dict:
    return json.loads(V22_FIXTURE.read_text(encoding="utf-8"))


def _aggregate(payload: dict) -> PersistedSelectorAggregate:
    request = EvidenceSelectionRequest.parse(payload)
    result = select_evidence(request)
    return PersistedSelectorAggregate(str(_request_id(request)), request, result)


def _classification(
    company_type: str = "MATURE_OPERATING_COMPANY",
    *,
    ticker: str = "EXM",
) -> VerifiedSelectorBindingV1:
    payload = _base_payload()
    payload["security"]["ticker"] = ticker
    payload["selectorPolicy"] = {
        "selectorVersion": "deterministic-evidence-selector-v1.0.0",
        "policyVersion": "fundamental-value-company-type-selection-v1.0.0",
        "domain": "CLASSIFICATION",
        "fieldCode": "COMPANY_TYPE",
        "requiredLayer": "NORMALIZED_OBSERVATION",
        "domainConstraints": {
            "taxonomyVersion": "fundamental-value-company-type-v1",
            "effectiveOn": "2026-07-29",
        },
        "providerFallbackPriority": ["provider-primary"],
        "requiredStrictnessClass": "STRICT_IDENTITY_AND_CHRONOLOGY",
        "requiredClaimClass": "STRICT_PIT",
        "requiredNormalizationVersion": "canonical-classification-v1.0.0",
    }
    candidate = payload["candidates"][0]
    payload["candidates"] = [candidate]
    candidate["evidenceId"] = "10000000-0000-4000-8000-000000000001"
    candidate["domain"] = "CLASSIFICATION"
    candidate["security"]["ticker"] = ticker
    candidate["strictnessClass"] = "STRICT_IDENTITY_AND_CHRONOLOGY"
    candidate["claimClass"] = "STRICT_PIT"
    candidate["lineage"]["normalizationVersion"] = "canonical-classification-v1.0.0"
    candidate["lineage"]["freshnessPolicyVersion"] = "classification-current-v1.0.0"
    candidate["lineage"]["normalizedRecordHash"] = "sha256:" + ("1" * 64)
    candidate["canonicalData"] = {
        "taxonomyCode": "FV_COMPANY_TYPE",
        "taxonomyVersion": "fundamental-value-company-type-v1",
        "sectorCode": "TEST_SECTOR",
        "industryCode": "TEST_INDUSTRY",
        "companyType": company_type,
        "effectiveFrom": "2020-01-01",
    }
    aggregate = _aggregate(payload)
    return VerifiedSelectorBindingV1.from_persisted("company_type", aggregate)


def _routing(
    classification: VerifiedSelectorBindingV1,
    company_type: str = "MATURE_OPERATING_COMPANY",
    applicability: ModelApplicability = ModelApplicability.APPLICABLE,
) -> ModelApplicabilityRouting:
    selected = classification.aggregate.result.selected
    assert selected is not None
    return ModelApplicabilityRouting.create(
        routing_id="20000000-0000-4000-8000-000000000001",
        company_id=classification.aggregate.request.security.company_id,
        classification_evidence_id=selected.evidence_id,
        company_type=company_type,
        applicability=applicability,
        specialized_model_code=(
            f"{company_type}_SPECIALIZED_V1"
            if applicability == ModelApplicability.SPECIALIZED_MODEL_REQUIRED
            else None
        ),
        routing_version=APPLICABILITY_ROUTING_VERSION,
        routing_revision=1,
        effective_at=datetime(2026, 7, 29, 20, 4, tzinfo=UTC),
    )


def _daily_price(
    *,
    value: str = "100",
    currency: str = "USD",
) -> VerifiedSelectorBindingV1:
    payload = _base_payload()
    payload["candidates"] = [payload["candidates"][0]]
    payload["candidates"][0]["evidenceId"] = "30000000-0000-4000-8000-000000000001"
    payload["candidates"][0]["canonicalData"]["close"] = value
    payload["candidates"][0]["canonicalData"]["currency"] = currency
    payload["candidates"][0]["canonicalData"]["adjustmentMode"] = "UNADJUSTED"
    payload["selectorPolicy"]["domainConstraints"]["currency"] = currency
    payload["selectorPolicy"]["domainConstraints"]["adjustmentMode"] = "UNADJUSTED"
    aggregate = _aggregate(payload)
    return VerifiedSelectorBindingV1.from_persisted("reference_price", aggregate)


def _fundamental(
    operand: str,
    metric_code: str,
    *,
    value: str,
    unit: str,
    currency: str | None,
    fiscal_period: str,
    evidence_suffix: int,
) -> VerifiedSelectorBindingV1:
    payload = _base_payload()
    payload["selectorPolicy"] = {
        "selectorVersion": "deterministic-evidence-selector-v1.0.0",
        "policyVersion": f"fundamental-value-{operand.replace('_', '-')}-selection-v1.0.0",
        "domain": "FUNDAMENTAL",
        "fieldCode": metric_code,
        "requiredLayer": "NORMALIZED_OBSERVATION",
        "domainConstraints": {
            "metricCode": metric_code,
            "periodEnd": "2026-06-30",
            "unit": unit,
            "currency": currency,
        },
        "providerFallbackPriority": ["provider-primary"],
        "requiredStrictnessClass": "STRICT_IDENTITY_AND_CHRONOLOGY",
        "requiredClaimClass": "STRICT_PIT",
        "requiredNormalizationVersion": "canonical-fundamental-v1.0.0",
    }
    candidate = payload["candidates"][0]
    payload["candidates"] = [candidate]
    candidate["evidenceId"] = f"40000000-0000-4000-8000-{evidence_suffix:012d}"
    candidate["domain"] = "FUNDAMENTAL"
    candidate["strictnessClass"] = "STRICT_IDENTITY_AND_CHRONOLOGY"
    candidate["claimClass"] = "STRICT_PIT"
    candidate["lineage"]["normalizationVersion"] = "canonical-fundamental-v1.0.0"
    candidate["lineage"]["freshnessPolicyVersion"] = "fundamental-quarterly-freshness-v1.0.0"
    candidate["lineage"]["normalizedRecordHash"] = "sha256:" + f"{evidence_suffix:x}"[-1] * 64
    candidate["canonicalData"] = {
        "metricCode": metric_code,
        "numericValue": value,
        "unit": unit,
        "currency": currency,
        "periodStart": None if fiscal_period == "INSTANT" else "2025-07-01",
        "periodEnd": "2026-06-30",
        "fiscalPeriod": fiscal_period,
        "formType": "10-K",
        "accessionNumber": f"0000000000-26-{evidence_suffix:06d}",
        "filedAt": "2026-07-15T12:00:00Z",
        "mappingVersion": "fundamental-value-mapping-v1.0.0",
    }
    return VerifiedSelectorBindingV1.from_persisted(operand, _aggregate(payload))


def _request(
    *,
    classification: VerifiedSelectorBindingV1 | None = None,
    routing: ModelApplicabilityRouting | None = None,
    bindings: tuple[VerifiedSelectorBindingV1, ...] = (),
    versions: AssemblyVersionSetV1 | None = None,
) -> FundamentalValueAssemblyRequestV1:
    selected_classification = classification or _classification()
    return FundamentalValueAssemblyRequestV1(
        routing=routing or _routing(selected_classification),
        classification=selected_classification,
        operand_bindings=bindings,
        versions=versions or AssemblyVersionSetV1(),
    )


class _SyntheticV22Repository:
    def __init__(
        self,
        *,
        routing: ModelApplicabilityRouting,
        bindings: tuple[VerifiedSelectorBindingV1, ...],
    ) -> None:
        self.routings = {routing.routing_id: routing}
        self.selectors = {binding.aggregate.request_id: binding.aggregate for binding in bindings}
        self.forced_routing: ModelApplicabilityRouting | None = None

    def load_selector_aggregate(self, request_id: str) -> PersistedSelectorAggregate:
        try:
            return self.selectors[request_id]
        except KeyError as error:
            raise LookupError(request_id) from error

    def load_applicability_routing(self, routing_id: str) -> ModelApplicabilityRouting:
        if self.forced_routing is not None:
            return self.forced_routing
        try:
            return self.routings[routing_id]
        except KeyError as error:
            raise LookupError(routing_id) from error


def _by_id_request(
    classification: VerifiedSelectorBindingV1,
    routing: ModelApplicabilityRouting,
    bindings: tuple[VerifiedSelectorBindingV1, ...] = (),
) -> FundamentalValueAssemblyByIdRequestV1:
    anchor = classification.aggregate.request
    return FundamentalValueAssemblyByIdRequestV1(
        routing_id=routing.routing_id,
        classification_request_id=classification.aggregate.request_id,
        operand_request_ids=tuple(
            OperandSelectorRequestIdV1(binding.operand_code, binding.aggregate.request_id)
            for binding in bindings
        ),
        expected_security=anchor.security,
        expected_completed_session=anchor.completed_session,
        expected_decision_cutoff=anchor.decision_cutoff,
        expected_sealed_ingestion_cutoff=anchor.sealed_ingestion_cutoff,
    )


def test_public_assembly_rehydrates_v22_records_by_persisted_ids() -> None:
    classification = _classification()
    routing = _routing(classification)
    price = _daily_price()
    repository = _SyntheticV22Repository(routing=routing, bindings=(classification, price))

    actual = assemble_fundamental_value_from_v22_v1(
        repository, _by_id_request(classification, routing, (price,))
    )
    expected = assemble_fundamental_value_inputs_v1(
        _request(classification=classification, routing=routing, bindings=(price,))
    )

    assert actual.manifest_content_hash == expected.manifest_content_hash


@pytest.mark.parametrize(
    ("replacement", "reason"),
    (
        ("security", "PERSISTED_SECURITY_IDENTITY_MISMATCH"),
        ("session", "PERSISTED_COMPLETED_SESSION_MISMATCH"),
        ("decision", "PERSISTED_DECISION_CUTOFF_MISMATCH"),
        ("sealed", "PERSISTED_SEALED_INGESTION_CUTOFF_MISMATCH"),
    ),
)
def test_public_assembly_rejects_expected_anchor_mismatch(replacement: str, reason: str) -> None:
    classification = _classification()
    routing = _routing(classification)
    repository = _SyntheticV22Repository(routing=routing, bindings=(classification,))
    request = _by_id_request(classification, routing)
    anchor = classification.aggregate.request
    changes = {
        "security": {"expected_security": replace(anchor.security, ticker="OTHER")},
        "session": {
            "expected_completed_session": replace(
                anchor.completed_session, session_date=date(2026, 7, 28)
            )
        },
        "decision": {"expected_decision_cutoff": anchor.decision_cutoff - timedelta(seconds=1)},
        "sealed": {
            "expected_sealed_ingestion_cutoff": (
                anchor.sealed_ingestion_cutoff + timedelta(seconds=1)
            )
        },
    }

    with pytest.raises(AssemblyViolation, match=reason):
        assemble_fundamental_value_from_v22_v1(repository, replace(request, **changes[replacement]))


def test_public_assembly_rejects_missing_or_mismatched_persisted_ids() -> None:
    classification = _classification()
    routing = _routing(classification)
    repository = _SyntheticV22Repository(routing=routing, bindings=(classification,))
    request = _by_id_request(classification, routing)

    with pytest.raises(AssemblyViolation, match="PERSISTED_SELECTOR_REQUEST_NOT_FOUND"):
        assemble_fundamental_value_from_v22_v1(
            repository,
            replace(
                request,
                classification_request_id="90000000-0000-4000-8000-000000000001",
            ),
        )
    repository.selectors[request.classification_request_id] = replace(
        classification.aggregate,
        request_id="90000000-0000-4000-8000-000000000002",
    )
    with pytest.raises(AssemblyViolation, match="PERSISTED_SELECTOR_REQUEST_ID_MISMATCH"):
        assemble_fundamental_value_from_v22_v1(repository, request)


def test_public_assembly_rejects_missing_or_mismatched_routing_id() -> None:
    classification = _classification()
    routing = _routing(classification)
    repository = _SyntheticV22Repository(routing=routing, bindings=(classification,))
    request = _by_id_request(classification, routing)

    with pytest.raises(AssemblyViolation, match="PERSISTED_APPLICABILITY_ROUTING_NOT_FOUND"):
        assemble_fundamental_value_from_v22_v1(
            repository,
            replace(request, routing_id="90000000-0000-4000-8000-000000000003"),
        )
    repository.forced_routing = ModelApplicabilityRouting.create(
        routing_id="90000000-0000-4000-8000-000000000004",
        company_id=routing.company_id,
        classification_evidence_id=routing.classification_evidence_id,
        company_type=routing.company_type,
        applicability=routing.applicability,
        specialized_model_code=routing.specialized_model_code,
        routing_version=routing.routing_version,
        routing_revision=routing.routing_revision,
        effective_at=routing.effective_at,
    )
    with pytest.raises(AssemblyViolation, match="PERSISTED_APPLICABILITY_ROUTING_ID_MISMATCH"):
        assemble_fundamental_value_from_v22_v1(repository, request)


@pytest.mark.parametrize("projection_years", (2, 11, True, False, 5.0, "5"))
def test_projection_years_rejects_out_of_domain_values(projection_years: object) -> None:
    classification = _classification("BANK", ticker="NBN")
    routing = _routing(classification, "BANK", ModelApplicability.SPECIALIZED_MODEL_REQUIRED)
    with pytest.raises(AssemblyViolation, match="PROJECTION_YEARS_OUT_OF_RANGE"):
        replace(_by_id_request(classification, routing), projection_years=projection_years)
    with pytest.raises(AssemblyViolation, match="PROJECTION_YEARS_OUT_OF_RANGE"):
        replace(
            _request(classification=classification, routing=routing),
            projection_years=projection_years,
        )


def test_projection_years_is_manifest_and_hash_bound() -> None:
    classification = _classification("BANK", ticker="NBN")
    routing = _routing(classification, "BANK", ModelApplicability.SPECIALIZED_MODEL_REQUIRED)
    horizon_3 = assemble_fundamental_value_inputs_v1(
        replace(_request(classification=classification, routing=routing), projection_years=3)
    )
    horizon_10 = assemble_fundamental_value_inputs_v1(
        replace(_request(classification=classification, routing=routing), projection_years=10)
    )
    assert horizon_3.projection_years == 3
    assert horizon_10.projection_years == 10
    assert horizon_3.manifest_payload()["projectionYears"] == 3
    assert horizon_10.manifest_payload()["projectionYears"] == 10
    assert horizon_3.manifest_content_hash != horizon_10.manifest_content_hash
    with pytest.raises(AssemblyViolation, match="ASSEMBLY_MANIFEST_CONTENT_HASH_DRIFT"):
        verify_manifest_content_hash(replace(horizon_3, projection_years=10))


@pytest.mark.parametrize(
    ("operand_request_ids", "reason"),
    (
        ([], "OPERAND_REQUEST_IDS_MUST_BE_TUPLE"),
        ("reference_price", "OPERAND_REQUEST_IDS_MUST_BE_TUPLE"),
        ({"reference_price": "id"}, "OPERAND_REQUEST_IDS_MUST_BE_TUPLE"),
        (("reference_price",), "OPERAND_REQUEST_ID_MEMBER_INVALID"),
        (({"operand_code": "reference_price"},), "OPERAND_REQUEST_ID_MEMBER_INVALID"),
    ),
)
def test_operand_request_ids_is_deeply_immutable(operand_request_ids: object, reason: str) -> None:
    classification = _classification()
    routing = _routing(classification)
    with pytest.raises(AssemblyViolation, match=reason):
        replace(
            _by_id_request(classification, routing),
            operand_request_ids=operand_request_ids,
        )


@pytest.mark.parametrize(
    ("operand", "metric", "value", "unit", "currency", "period", "suffix"),
    (
        ("diluted_shares", "DILUTED_SHARES", "10", "SHARES", None, "TTM", 101),
        ("cash", "CASH_AND_EQUIVALENTS", "20", "CURRENCY", "USD", "INSTANT", 102),
        ("debt", "TOTAL_DEBT", "30", "CURRENCY", "USD", "INSTANT", 103),
        ("ebit", "OPERATING_INCOME", "40", "CURRENCY", "USD", "TTM", 104),
        (
            "capital_expenditures",
            "CAPITAL_EXPENDITURE",
            "50",
            "CURRENCY",
            "USD",
            "TTM",
            105,
        ),
        (
            "normalized_free_cash_flow",
            "FREE_CASH_FLOW",
            "60",
            "CURRENCY",
            "USD",
            "TTM",
            106,
        ),
    ),
)
def test_each_direct_fundamental_operand_binds_positively(
    operand: str,
    metric: str,
    value: str,
    unit: str,
    currency: str | None,
    period: str,
    suffix: int,
) -> None:
    binding = _fundamental(
        operand,
        metric,
        value=value,
        unit=unit,
        currency=currency,
        fiscal_period=period,
        evidence_suffix=suffix,
    )
    result = assemble_fundamental_value_inputs_v1(_request(bindings=(binding,)))
    assembled = next(item for item in result.operands if item.operand_code == operand)
    assert assembled.state == DataState.VALID
    assert assembled.metric_evidence.value == Decimal(value)
    assert result.core_invocation_authorized is False


def test_assembly_state_reason_parity_is_fail_closed() -> None:
    missing = assemble_fundamental_value_inputs_v1(_request())
    assert missing.state != DataState.VALID
    assert missing.reason_codes
    with pytest.raises(AssemblyViolation, match="NON_VALID_ASSEMBLY_REQUIRES_REASON_CODES"):
        replace(missing, reason_codes=())
    valid = replace(missing, state=DataState.VALID, reason_codes=())
    assert valid.reason_codes == ()
    assert valid.manifest_payload()["reasonCodes"] == []
    with pytest.raises(AssemblyViolation, match="VALID_ASSEMBLY_CANNOT_HAVE_REASON_CODES"):
        replace(valid, reason_codes=("ASSEMBLY_COMPLETE",))


def test_unrelated_nonvalid_selector_cannot_be_relabelled_as_an_operand() -> None:
    payload = _base_payload()
    payload["candidates"] = [payload["candidates"][0]]
    candidate = payload["candidates"][0]
    candidate["state"] = "STALE"
    candidate["reasonCode"] = "FRESHNESS_WINDOW_EXCEEDED"
    candidate.pop("canonicalData")
    unrelated = VerifiedSelectorBindingV1.from_persisted("cash", _aggregate(payload))
    with pytest.raises(AssemblyViolation, match="FUNDAMENTAL_OPERAND_DOMAIN_INVALID"):
        assemble_fundamental_value_inputs_v1(_request(bindings=(unrelated,)))


def test_distinct_requests_selecting_same_evidence_fail_closed() -> None:
    price = _daily_price()
    request = price.aggregate.request
    rejected = replace(
        request.candidates[0],
        evidence_id="30000000-0000-4000-8000-000000000099",
        provider_code="provider-secondary",
        source_record_id="secondary-record",
        source_content_hash="sha256:" + "9" * 64,
        normalized_record_hash="sha256:" + "8" * 64,
    )
    changed_request = replace(
        request,
        policy=replace(
            request.policy,
            provider_fallback_priority=("provider-primary", "provider-secondary"),
        ),
        candidates=(request.candidates[0], rejected),
    )
    duplicate = VerifiedSelectorBindingV1.from_persisted(
        "cash",
        PersistedSelectorAggregate(
            str(_request_id(changed_request)),
            changed_request,
            select_evidence(changed_request),
        ),
    )
    assert price.aggregate.request_id != duplicate.aggregate.request_id
    with pytest.raises(AssemblyViolation, match="DUPLICATE_SELECTED_EVIDENCE_ID"):
        assemble_fundamental_value_inputs_v1(_request(bindings=(price, duplicate)))


def test_vendor_named_adapter_lineage_is_retained_without_provider_values() -> None:
    price = _daily_price()
    request = price.aggregate.request
    candidate = request.candidates[0]
    changed_candidate = replace(
        candidate,
        provider_code="EODHD",
        provider_schema_version="eodhd-eod-v1",
        adapter_version="eodhd-canonical-price-adapter-v1.0.0",
    )
    changed_request = replace(
        request,
        policy=replace(request.policy, provider_fallback_priority=("EODHD",)),
        candidates=(changed_candidate,),
    )
    binding = VerifiedSelectorBindingV1.from_persisted(
        "reference_price",
        PersistedSelectorAggregate(
            str(_request_id(changed_request)),
            changed_request,
            select_evidence(changed_request),
        ),
    )
    result = assemble_fundamental_value_inputs_v1(_request(bindings=(binding,)))
    manifest = json.dumps(result.manifest_payload(), sort_keys=True)
    assert "eodhd-eod-v1" in manifest
    assert "eodhd-canonical-price-adapter-v1.0.0" in manifest
    assert '"providerCode"' not in manifest


def test_mature_assembly_enumerates_every_operand_and_fails_closed_on_v22_gaps() -> None:
    result = assemble_fundamental_value_inputs_v1(_request(bindings=(_daily_price(),)))
    assert result.state == DataState.MISSING
    assert result.applicability == Applicability.APPLICABLE
    assert result.inputs is None
    assert result.core_invocation_authorized is False
    assert {operand.operand_code for operand in result.operands} == {
        requirement.operand_code for requirement in OPERAND_REQUIREMENTS
    }
    reference = next(
        operand for operand in result.operands if operand.operand_code == "reference_price"
    )
    assert reference.state == DataState.VALID
    acquisition = next(
        operand for operand in result.operands if operand.operand_code == "acquisition_discipline"
    )
    assert acquisition.state == DataState.MISSING
    assert "ACQUISITION_DISCIPLINE_POLICY_EVIDENCE_REQUIRED" in acquisition.reason_codes


def test_manifest_is_reproducible_hashed_and_contains_no_values_or_provider_identity() -> None:
    first = assemble_fundamental_value_inputs_v1(_request(bindings=(_daily_price(),)))
    second = assemble_fundamental_value_inputs_v1(_request(bindings=(_daily_price(),)))
    assert first.manifest_content_hash == second.manifest_content_hash
    verify_manifest_content_hash(first)
    encoded = json.dumps(first.manifest_payload(), sort_keys=True)
    for forbidden in (
        "numericValue",
        "providerCode",
        "provider-primary",
        "rawStorageReference",
        '"value"',
        "finalPortfolioWeight",
        '"trade"',
    ):
        assert forbidden not in encoded
    with pytest.raises(AssemblyViolation, match="ASSEMBLY_MANIFEST_CONTENT_HASH_DRIFT"):
        verify_manifest_content_hash(replace(first, manifest_content_hash="sha256:" + ("0" * 64)))


def test_manifest_hash_changes_with_evidence_hash_or_revision() -> None:
    baseline_binding = _daily_price()
    baseline = assemble_fundamental_value_inputs_v1(_request(bindings=(baseline_binding,)))
    selected = baseline_binding.aggregate.result.selected
    assert selected is not None
    changed_candidate = replace(
        selected,
        source_revision=selected.source_revision + 1,
        normalized_record_hash="sha256:" + ("9" * 64),
    )
    changed_request = replace(
        baseline_binding.aggregate.request,
        candidates=(changed_candidate,),
    )
    changed_result = select_evidence(changed_request)
    changed_aggregate = PersistedSelectorAggregate(
        str(_request_id(changed_request)), changed_request, changed_result
    )
    changed = assemble_fundamental_value_inputs_v1(
        _request(
            bindings=(
                VerifiedSelectorBindingV1.from_persisted("reference_price", changed_aggregate),
            )
        )
    )
    assert changed.manifest_content_hash != baseline.manifest_content_hash

    with pytest.raises(AssemblyViolation, match="SELECTED_EVIDENCE_SEAL_DRIFT"):
        assemble_fundamental_value_inputs_v1(
            _request(bindings=(replace(baseline_binding, aggregate=changed_aggregate),))
        )


@pytest.mark.parametrize(
    "field",
    (
        "security_id",
        "company_id",
        "instrument_id",
        "share_class_id",
        "listing_id",
        "ticker_assignment_id",
        "ticker",
        "mic",
        "currency",
    ),
)
def test_mixed_durable_or_listing_identity_fails_closed(field: str) -> None:
    binding = _daily_price()
    security = binding.aggregate.request.security
    changed_value = (
        "99999999-9999-4999-8999-999999999999"
        if field.endswith("_id")
        else {"ticker": "OTHER", "mic": "XNAS", "currency": "CAD"}[field]
    )
    changed_security = replace(security, **{field: changed_value})
    changed_request = replace(binding.aggregate.request, security=changed_security)
    changed_aggregate = PersistedSelectorAggregate(
        str(_request_id(changed_request)),
        changed_request,
        select_evidence(changed_request),
    )
    changed_binding = VerifiedSelectorBindingV1.from_persisted("reference_price", changed_aggregate)
    with pytest.raises(AssemblyViolation, match="MIXED_DURABLE_SECURITY_IDENTITY"):
        assemble_fundamental_value_inputs_v1(_request(bindings=(changed_binding,)))


def test_wrong_completed_session_or_cutoff_fails_closed() -> None:
    binding = _daily_price()
    changed_session = replace(
        binding.aggregate.request.completed_session,
        calendar_version="wrong-calendar-version",
    )
    changed_request = replace(
        binding.aggregate.request,
        completed_session=changed_session,
    )
    aggregate = PersistedSelectorAggregate(
        str(_request_id(changed_request)), changed_request, select_evidence(changed_request)
    )
    with pytest.raises(AssemblyViolation, match="MIXED_COMPLETED_SESSION_OR_CALENDAR"):
        assemble_fundamental_value_inputs_v1(
            _request(
                bindings=(VerifiedSelectorBindingV1.from_persisted("reference_price", aggregate),)
            )
        )

    changed_request = replace(
        binding.aggregate.request,
        decision_cutoff=binding.aggregate.request.decision_cutoff + timedelta(minutes=1),
    )
    aggregate = PersistedSelectorAggregate(
        str(_request_id(changed_request)), changed_request, select_evidence(changed_request)
    )
    with pytest.raises(AssemblyViolation, match="MIXED_DECISION_CUTOFF"):
        assemble_fundamental_value_inputs_v1(
            _request(
                bindings=(VerifiedSelectorBindingV1.from_persisted("reference_price", aggregate),)
            )
        )


def test_selector_hash_and_version_drift_fail_closed() -> None:
    binding = _daily_price()
    with pytest.raises(AssemblyViolation, match="SELECTOR_REQUEST_HASH_DRIFT"):
        assemble_fundamental_value_inputs_v1(
            _request(bindings=(replace(binding, request_content_hash="sha256:" + ("0" * 64)),))
        )
    with pytest.raises(AssemblyViolation, match="SELECTOR_RESULT_HASH_DRIFT"):
        assemble_fundamental_value_inputs_v1(
            _request(bindings=(replace(binding, result_content_hash="sha256:" + ("0" * 64)),))
        )
    with pytest.raises(AssemblyViolation, match="ASSEMBLY_VERSION_SET_DRIFT"):
        assemble_fundamental_value_inputs_v1(
            _request(
                versions=replace(
                    AssemblyVersionSetV1(),
                    formula_version="fundamental-value-formulas-v1.0.0",
                )
            )
        )
    assert AssemblyVersionSetV1().formula_version == FORMULA_VERSION
    assert AssemblyVersionSetV1().assumption_policy_version == ASSUMPTION_POLICY_VERSION


@pytest.mark.parametrize(
    ("kind", "reason"),
    (
        ("policy", "REFERENCE_PRICE_POLICY_VERSION_DRIFT"),
        ("normalization", "REFERENCE_PRICE_REQUIRED_NORMALIZATION_VERSION_DRIFT"),
        ("freshness", "REFERENCE_PRICE_FRESHNESS_VERSION_DRIFT"),
    ),
)
def test_selected_evidence_version_drift_fails_closed(kind: str, reason: str) -> None:
    binding = _daily_price()
    request = binding.aggregate.request
    selected = binding.aggregate.result.selected
    assert selected is not None
    policy = request.policy
    candidate = selected
    if kind == "policy":
        policy = replace(policy, policy_version="drifted-daily-policy-v2")
    elif kind == "normalization":
        candidate = replace(candidate, normalization_version="drifted-normalization-v2")
        policy = replace(policy, required_normalization_version="drifted-normalization-v2")
    else:
        candidate = replace(candidate, freshness_policy_version="drifted-freshness-v2")
    changed_request = replace(request, policy=policy, candidates=(candidate,))
    changed_aggregate = PersistedSelectorAggregate(
        str(_request_id(changed_request)),
        changed_request,
        select_evidence(changed_request),
    )
    changed_binding = VerifiedSelectorBindingV1.from_persisted("reference_price", changed_aggregate)
    with pytest.raises(AssemblyViolation, match=reason):
        assemble_fundamental_value_inputs_v1(_request(bindings=(changed_binding,)))


def test_duplicate_operand_request_and_selected_evidence_fail_closed() -> None:
    price = _daily_price()
    with pytest.raises(AssemblyViolation, match="DUPLICATE_OPERAND_BINDING"):
        assemble_fundamental_value_inputs_v1(_request(bindings=(price, price)))

    duplicate_evidence = replace(price, operand_code="cash")
    with pytest.raises(AssemblyViolation, match="DUPLICATE_SELECTOR_REQUEST_ID"):
        assemble_fundamental_value_inputs_v1(_request(bindings=(price, duplicate_evidence)))


@pytest.mark.parametrize(
    ("unit", "currency", "fiscal_period", "value", "reason"),
    (
        ("USD", "USD", "INSTANT", "10", "FUNDAMENTAL_DOMAIN_CONSTRAINTS_INVALID"),
        ("CURRENCY", None, "INSTANT", "10", "FUNDAMENTAL_DOMAIN_CONSTRAINTS_INVALID"),
        ("CURRENCY", "USD", "TTM", "10", "FUNDAMENTAL_PERIOD_SEMANTICS_MISMATCH"),
        ("CURRENCY", "USD", "INSTANT", "-1", "FUNDAMENTAL_SIGN_SEMANTICS_MISMATCH"),
    ),
)
def test_unit_currency_period_and_sign_semantics_fail_closed(
    unit: str,
    currency: str | None,
    fiscal_period: str,
    value: str,
    reason: str,
) -> None:
    cash = _fundamental(
        "cash",
        "CASH_AND_EQUIVALENTS",
        value=value,
        unit=unit,
        currency=currency,
        fiscal_period=fiscal_period,
        evidence_suffix=2,
    )
    with pytest.raises(AssemblyViolation, match=reason):
        assemble_fundamental_value_inputs_v1(_request(bindings=(cash,)))


def test_wrong_canonical_metric_code_cannot_fill_an_operand() -> None:
    wrong_cash = _fundamental(
        "cash",
        "TOTAL_DEBT",
        value="10",
        unit="CURRENCY",
        currency="USD",
        fiscal_period="INSTANT",
        evidence_suffix=3,
    )
    with pytest.raises(AssemblyViolation, match="FUNDAMENTAL_METRIC_CODE_MISMATCH"):
        assemble_fundamental_value_inputs_v1(_request(bindings=(wrong_cash,)))


def test_stale_future_ambiguous_and_conflicting_results_never_invoke_core() -> None:
    stale_payload = _base_payload()
    stale_payload["candidates"] = [stale_payload["candidates"][0]]
    candidate = stale_payload["candidates"][0]
    candidate["evidenceId"] = "50000000-0000-4000-8000-000000000001"
    candidate["state"] = "STALE"
    candidate["reasonCode"] = "FRESHNESS_WINDOW_EXCEEDED"
    candidate.pop("canonicalData")
    stale_payload["selectorPolicy"]["domainConstraints"]["adjustmentMode"] = "UNADJUSTED"
    stale = VerifiedSelectorBindingV1.from_persisted("reference_price", _aggregate(stale_payload))
    result = assemble_fundamental_value_inputs_v1(_request(bindings=(stale,)))
    assert result.state == DataState.STALE
    assert result.inputs is None
    assert result.core_invocation_authorized is False

    future_payload = _base_payload()
    future_payload["candidates"] = [future_payload["candidates"][0]]
    future_payload["selectorPolicy"]["domainConstraints"]["adjustmentMode"] = "UNADJUSTED"
    future = future_payload["candidates"][0]
    future["lineage"]["availableAt"] = "2026-07-29T20:06:00Z"
    future["lineage"]["retrievedAt"] = "2026-07-29T20:06:30Z"
    future["lineage"]["ingestedAt"] = "2026-07-29T20:07:00Z"
    binding = VerifiedSelectorBindingV1.from_persisted(
        "reference_price", _aggregate(future_payload)
    )
    result = assemble_fundamental_value_inputs_v1(_request(bindings=(binding,)))
    reference = next(
        operand for operand in result.operands if operand.operand_code == "reference_price"
    )
    assert reference.state == DataState.EXCLUDED
    assert result.inputs is None

    ambiguous_payload = _base_payload()
    ambiguous_payload["selectorPolicy"]["domainConstraints"]["adjustmentMode"] = "UNADJUSTED"
    ambiguous = copy.deepcopy(ambiguous_payload["candidates"][0])
    ambiguous["evidenceId"] = "50000000-0000-4000-8000-000000000002"
    ambiguous["lineage"]["normalizedRecordHash"] = "sha256:" + ("e" * 64)
    ambiguous_payload["candidates"].append(ambiguous)
    binding = VerifiedSelectorBindingV1.from_persisted(
        "reference_price", _aggregate(ambiguous_payload)
    )
    result = assemble_fundamental_value_inputs_v1(_request(bindings=(binding,)))
    assert result.state == DataState.INVALID
    assert result.inputs is None


def test_provider_native_leakage_is_rejected_by_v22_before_assembly() -> None:
    payload = _base_payload()
    payload["candidates"][0]["providerNativeValue"] = "100"
    with pytest.raises(UnifiedEvidenceContractViolation, match="unknown fields"):
        _aggregate(payload)


def test_nbn_bank_routing_precedes_operands_and_generic_core_is_impossible() -> None:
    classification = _classification("BANK", ticker="NBN")
    routing = _routing(
        classification,
        "BANK",
        ModelApplicability.SPECIALIZED_MODEL_REQUIRED,
    )
    result = assemble_fundamental_value_inputs_v1(
        _request(classification=classification, routing=routing)
    )
    assert result.company_type == CompanyType.BANK
    assert result.applicability == Applicability.SPECIALIZED_MODEL_REQUIRED
    assert result.state == DataState.NOT_APPLICABLE
    assert result.operands == ()
    assert result.inputs is None
    assert result.core_invocation_authorized is False


def test_routing_classification_id_and_version_drift_fail_closed() -> None:
    classification = _classification()
    base = _routing(classification)
    wrong_id = ModelApplicabilityRouting.create(
        routing_id=base.routing_id,
        company_id=base.company_id,
        classification_evidence_id="99999999-9999-4999-8999-999999999999",
        company_type=base.company_type,
        applicability=base.applicability,
        specialized_model_code=None,
        routing_version=base.routing_version,
        routing_revision=base.routing_revision,
        effective_at=base.effective_at,
    )
    with pytest.raises(AssemblyViolation, match="ROUTING_CLASSIFICATION_EVIDENCE_ID_MISMATCH"):
        assemble_fundamental_value_inputs_v1(
            _request(classification=classification, routing=wrong_id)
        )
    wrong_version = ModelApplicabilityRouting.create(
        routing_id=base.routing_id,
        company_id=base.company_id,
        classification_evidence_id=base.classification_evidence_id,
        company_type=base.company_type,
        applicability=base.applicability,
        specialized_model_code=None,
        routing_version="fundamental-value-applicability-v2.0.0",
        routing_revision=base.routing_revision,
        effective_at=base.effective_at,
    )
    with pytest.raises(AssemblyViolation, match="APPLICABILITY_ROUTING_VERSION_DRIFT"):
        assemble_fundamental_value_inputs_v1(
            _request(classification=classification, routing=wrong_version)
        )


def test_git_safe_nbn_manifest_fixture_is_canonical_and_hash_bound() -> None:
    fixture = json.loads(ASSEMBLY_FIXTURE.read_text(encoding="utf-8"))
    classification = _classification("BANK", ticker="NBN")
    routing = _routing(
        classification,
        "BANK",
        ModelApplicability.SPECIALIZED_MODEL_REQUIRED,
    )
    result = assemble_fundamental_value_inputs_v1(
        _request(classification=classification, routing=routing)
    )
    assert fixture["manifest"] == result.manifest_payload()
    assert fixture["manifestContentHash"] == result.manifest_content_hash


@pytest.mark.parametrize(
    ("company_type", "applicability", "expected"),
    (
        ("INSURER", ModelApplicability.SPECIALIZED_MODEL_REQUIRED, CompanyType.INSURER),
        ("REIT", ModelApplicability.SPECIALIZED_MODEL_REQUIRED, CompanyType.REIT),
        ("RESOURCE", ModelApplicability.SPECIALIZED_MODEL_REQUIRED, CompanyType.RESOURCE),
        (
            "BIOTECHNOLOGY",
            ModelApplicability.SPECIALIZED_MODEL_REQUIRED,
            CompanyType.BIOTECHNOLOGY,
        ),
        ("FINANCIAL", ModelApplicability.SPECIALIZED_MODEL_REQUIRED, CompanyType.FINANCIAL),
        (
            "SPECIAL_SITUATION",
            ModelApplicability.SPECIALIZED_MODEL_REQUIRED,
            CompanyType.INCOMPATIBLE_CONGLOMERATE,
        ),
        ("BENCHMARK", ModelApplicability.NOT_APPLICABLE, CompanyType.BENCHMARK),
        (
            "INSUFFICIENT_PUBLIC_HISTORY",
            ModelApplicability.INSUFFICIENT_EVIDENCE,
            CompanyType.INSUFFICIENT_PUBLIC_HISTORY,
        ),
    ),
)
def test_specialized_and_insufficient_routes_never_assemble_operands(
    company_type: str,
    applicability: ModelApplicability,
    expected: CompanyType,
) -> None:
    classification = _classification(company_type)
    routing = _routing(classification, company_type, applicability)
    result = assemble_fundamental_value_inputs_v1(
        _request(classification=classification, routing=routing)
    )
    assert result.company_type == expected
    assert result.applicability != Applicability.APPLICABLE
    assert result.operands == ()
    assert result.inputs is None


@pytest.mark.parametrize(
    "operand",
    (
        "incremental_return_on_invested_capital",
        "acquisition_discipline",
        "shareholder_distribution_coverage",
    ),
)
def test_capital_allocation_operand_incompleteness_is_explicit(operand: str) -> None:
    result = assemble_fundamental_value_inputs_v1(_request())
    assembled = next(item for item in result.operands if item.operand_code == operand)
    assert assembled.state == DataState.MISSING
    assert assembled.metric_evidence.value is None
    assert operand.upper() in assembled.reason_codes[0]
