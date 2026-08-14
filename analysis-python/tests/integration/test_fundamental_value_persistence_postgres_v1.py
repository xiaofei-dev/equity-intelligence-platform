from __future__ import annotations

import copy
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from test_evidence_persistence_postgres_v1 import (
    DATABASE_URL,
    FUNDAMENTAL_VALUE_TEST_PROVIDER,
    REQUEST_FIXTURE,
    IntegrationSeed,
    _fundamental_value_by_id_request,
    _fundamental_value_selector,
    _seed_security_identity,
    _selection_command,
)

import equity_analysis.fundamental_value.routes_v1 as fundamental_routes
from equity_analysis.dual_system_contract import ModelApplicability
from equity_analysis.evidence_foundation import (
    EvidenceSelectionRequest,
    ModelApplicabilityRouting,
    PersistedEvidenceEnvelope,
)
from equity_analysis.evidence_foundation.persistence_v1 import candidate_to_payload
from equity_analysis.fundamental_value.contracts_v1 import Applicability, CompanyType, DataState
from equity_analysis.fundamental_value.core_v1 import (
    FundamentalValueInputsV1,
    MetricEvidence,
    evaluate_fundamental_value_v1,
)
from equity_analysis.fundamental_value.evidence_assembly_v1 import (
    APPLICABILITY_ROUTING_VERSION,
    OPERAND_REQUIREMENTS,
    AssembledOperandV1,
    AssemblyVersionSetV1,
    FundamentalValueAssemblyResultV1,
    VerifiedSelectorBindingV1,
    _content_hash,
    _evidence_seal,
    assemble_fundamental_value_from_v22_v1,
)
from equity_analysis.fundamental_value.operand_producers_v1 import (
    OperandProducerContractV1,
    OperandProducerRegistryV1,
    ParentSlotContractV1,
)
from equity_analysis.fundamental_value.persistence_v1 import (
    FundamentalValuePersistenceConflict,
    FundamentalValuePersistenceViolation,
    FundamentalValueRepositoryV1,
    OperandEvidenceParentV1,
    OperandOutputBindingV1,
    PostgresFundamentalValueBackendV1,
)
from equity_analysis.main import app

pytest_plugins = ("test_evidence_persistence_postgres_v1",)
pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for PostgreSQL integration acceptance",
)

CORE_FIXTURE = (
    Path(__file__).parents[3]
    / "contracts"
    / "fundamental-value-v1"
    / "core-assessment.example.json"
)


def _test_identity(parents):
    return parents[0].value


def _test_producer_registry() -> OperandProducerRegistryV1:
    contracts = tuple(
        OperandProducerContractV1(
            operand_code=requirement.operand_code,
            source_kind=requirement.source_kind.value,
            contract_version=(
                f"test-only-{requirement.operand_code.replace('_', '-')}-producer-v1.0.0"
            ),
            evaluator_id="test-only-identity-decimal-v1",
            governance_status="TEST_ONLY",
            parent_slots=(ParentSlotContractV1(
                role_code="TEST_INPUT",
                domain="FUNDAMENTAL",
                field_code="FREE_CASH_FLOW",
                unit="CURRENCY",
                currency_rule="MATCH_OUTPUT",
                fiscal_period="TTM",
                period_identity="EXACT_PERIOD_END",
                period_start="2025-07-01",
                period_end="2026-06-30",
            ),),
            output_semantics="CONTROLLED_SYNTHETIC_DECIMAL",
            evaluator=_test_identity,
        )
        for requirement in OPERAND_REQUIREMENTS
        if requirement.source_kind.value in {
            "DERIVATION_REQUIRED", "POLICY_EVIDENCE_REQUIRED"
        }
    )
    return OperandProducerRegistryV1(contracts, allow_test_only=True)


TEST_PRODUCERS = _test_producer_registry()


def _repository(*, test_producers: bool = False) -> FundamentalValueRepositoryV1:
    backend = PostgresFundamentalValueBackendV1(
        DATABASE_URL or "",
        producer_registry=(
            TEST_PRODUCERS if test_producers else OperandProducerRegistryV1()
        ),
    )
    if test_producers:
        return FundamentalValueRepositoryV1(backend, producer_registry=TEST_PRODUCERS)
    return FundamentalValueRepositoryV1(backend)


def _routing(seed: IntegrationSeed, classification) -> ModelApplicabilityRouting:
    selected = classification.result.selected
    assert selected is not None
    try:
        latest = seed.repository.load_latest_applicability_routing(
            classification.request.security.company_id,
            APPLICABILITY_ROUTING_VERSION,
        )
    except LookupError:
        revision = 1
        supersedes_routing_id = None
        effective_at = selected.ingested_at
    else:
        revision = latest.routing_revision + 1
        supersedes_routing_id = latest.routing_id
        effective_at = max(
            selected.ingested_at,
            latest.effective_at + timedelta(microseconds=1),
        )
    routing = ModelApplicabilityRouting.create(
        routing_id=str(uuid4()),
        company_id=classification.request.security.company_id,
        classification_evidence_id=selected.evidence_id,
        company_type="MATURE_OPERATING_COMPANY",
        applicability=ModelApplicability.APPLICABLE,
        specialized_model_code=None,
        routing_version=APPLICABILITY_ROUTING_VERSION,
        routing_revision=revision,
        effective_at=effective_at,
        supersedes_routing_id=supersedes_routing_id,
    )
    seed.repository.persist_applicability_routing(routing)
    return routing


def test_v23_round_trips_current_honest_missing_assembly_and_fails_closed(
    v22_seed: IntegrationSeed,
) -> None:
    marker = f"v23missing{uuid4().hex[:8]}"
    classification = _fundamental_value_selector(
        v22_seed,
        company_type="MATURE_OPERATING_COMPANY",
        suffix=f"{marker}-classification",
    )
    cash = _fundamental_value_selector(
        v22_seed,
        operand="cash",
        suffix=f"{marker}-cash",
    )
    routing = _routing(v22_seed, classification)
    assembly = assemble_fundamental_value_from_v22_v1(
        v22_seed.repository,
        _fundamental_value_by_id_request(routing, classification, cash),
    )
    assert assembly.state == DataState.MISSING
    assert assembly.inputs is None
    repository = _repository()

    persisted = repository.persist(assembly)
    assert repository.persist(assembly) == persisted
    assert repository.load(persisted.assembly_id) == persisted
    with pytest.raises(LookupError):
        repository.load(str(uuid4()))

    with _tampered_manifest_hash(persisted.assembly_id):
        with pytest.raises((ValueError, FundamentalValuePersistenceViolation)):
            repository.load(persisted.assembly_id)

    backend = PostgresFundamentalValueBackendV1(DATABASE_URL or "")
    conflicting = replace(persisted, assembly_revision=2)
    with pytest.raises(FundamentalValuePersistenceConflict):
        backend.insert(conflicting)


def test_stage5_internal_route_persists_real_v22_missing_by_ids(
    v22_seed: IntegrationSeed,
) -> None:
    marker = f"stage5missing{uuid4().hex[:8]}"
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            security = _seed_security_identity(
                cursor, token=marker, ticker=f"S{marker[-10:].upper()}"
            )
    classification = _fundamental_value_selector(
        v22_seed,
        company_type="MATURE_OPERATING_COMPANY",
        security=security,
        suffix=f"{marker}-classification",
    )
    cash = _fundamental_value_selector(
        v22_seed, operand="cash", security=security, suffix=f"{marker}-cash"
    )
    routing = _routing(v22_seed, classification)
    repository = _repository()
    app.dependency_overrides[fundamental_routes.get_evidence_repository] = (
        lambda: v22_seed.repository
    )
    app.dependency_overrides[fundamental_routes.get_fundamental_repository] = (
        lambda: repository
    )
    try:
        response = TestClient(app).post(
            "/internal/v1/fundamental-value/decisions",
            json={
                "contractVersion": fundamental_routes.INTERNAL_COMMAND_VERSION,
                "routingId": routing.routing_id,
                "classificationRequestId": str(classification.request_id),
                "operandRequestIds": [
                    {"operandCode": "cash", "requestId": str(cash.request_id)}
                ],
                "projectionYears": 5,
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "MISSING"
    assert payload["assessmentId"] is None
    assert payload["coreInvocationAuthorized"] is False
    assert repository.load(payload["assemblyId"]).assembly.state == DataState.MISSING


def test_v23_round_trips_controlled_synthetic_valid_assembly_and_assessment(
    v22_seed: IntegrationSeed,
) -> None:
    marker = f"v23valid{uuid4().hex[:8]}"
    security = _stable_controlled_valid_security()
    classification = _fundamental_value_selector(
        v22_seed,
        company_type="MATURE_OPERATING_COMPANY",
        security=security,
        suffix=f"{marker}-classification",
    )
    routing = _routing(v22_seed, classification)
    payload = json.loads(CORE_FIXTURE.read_text(encoding="utf-8"))
    metrics = {code: MetricEvidence.valid(value) for code, value in payload["validInputs"].items()}
    inputs = FundamentalValueInputsV1(
        company_type=CompanyType.MATURE_OPERATING_COMPANY,
        applicability=Applicability.APPLICABLE,
        projection_years=payload["projectionYears"],
        currency=payload["currency"],
        **metrics,
    )
    _seed_test_producer_contracts()
    operands = []
    parent_bindings = []
    for ordinal, requirement in enumerate(OPERAND_REQUIREMENTS, 1):
        is_direct = requirement.source_kind.value in {"DAILY_PRICE", "DIRECT_FUNDAMENTAL"}
        aggregates = (
            (_controlled_operand_selector(
                v22_seed,
                requirement.operand_code,
                requirement.source_kind.value,
                security,
                metrics[requirement.operand_code].value,
                f"{marker}-operand-{ordinal}",
            ),)
            if is_direct
            else (_controlled_operand_selector(
                v22_seed,
                requirement.operand_code,
                "CONTROLLED_PARENT",
                security=security,
                value=metrics[requirement.operand_code].value,
                marker=f"{marker}-test-parent-{ordinal}",
            ),)
        )
        aggregate = aggregates[0]
        binding = VerifiedSelectorBindingV1.from_persisted(requirement.operand_code, aggregate)
        selected = aggregate.result.selected
        assert selected is not None
        if not is_direct:
            for parent_ordinal, parent_aggregate in enumerate(aggregates, 1):
                parent_selected = parent_aggregate.result.selected
                assert parent_selected is not None
                parent_bindings.append(OperandEvidenceParentV1(
                    operand_code=requirement.operand_code,
                    parent_ordinal=parent_ordinal,
                    evidence_id=parent_selected.evidence_id,
                    source_content_hash=parent_selected.source_content_hash,
                    normalized_record_hash=parent_selected.normalized_record_hash,
                    source_revision=parent_selected.source_revision,
                    effective_at=parent_selected.effective_at,
                    available_at=parent_selected.available_at,
                    ingested_at=parent_selected.ingested_at,
                    dependency_code="TEST_INPUT",
                    domain="FUNDAMENTAL",
                    field_code="FREE_CASH_FLOW",
                    unit="CURRENCY",
                    currency=security["currency"],
                    fiscal_period="TTM",
                    period_start="2025-07-01",
                    period_end="2026-06-30",
                    canonical_value=metrics[requirement.operand_code].value,
                ))
        operands.append(
            AssembledOperandV1(
                requirement.operand_code,
                DataState.VALID,
                (),
                _evidence_seal(binding) if is_direct else None,
                metrics[requirement.operand_code],
            )
        )
    anchor = classification.request
    classification_binding = VerifiedSelectorBindingV1.from_persisted(
        "company_type", classification
    )
    classification_seal = _evidence_seal(classification_binding)
    draft = FundamentalValueAssemblyResultV1(
        state=DataState.VALID,
        reason_codes=(),
        company_type=CompanyType.MATURE_OPERATING_COMPANY,
        applicability=Applicability.APPLICABLE,
        security=anchor.security,
        routing_id=routing.routing_id,
        routing_content_hash=routing.routing_content_hash,
        routing_revision=routing.routing_revision,
        classification_evidence_id=routing.classification_evidence_id,
        classification_seal=classification_seal,
        completed_session_date=anchor.completed_session.session_date.isoformat(),
        decision_cutoff=anchor.decision_cutoff,
        sealed_ingestion_cutoff=anchor.sealed_ingestion_cutoff,
        projection_years=inputs.projection_years,
        versions=AssemblyVersionSetV1(),
        operands=tuple(operands),
        inputs=inputs,
        manifest_content_hash="",
        core_invocation_authorized=True,
    )
    assembly = replace(draft, manifest_content_hash=_content_hash(draft.manifest_payload()))
    assessment = evaluate_fundamental_value_v1(inputs)
    outputs = []
    for requirement, operand in zip(OPERAND_REQUIREMENTS, operands, strict=True):
        if "REQUIRED" not in requirement.source_kind.value:
            continue
        contract = TEST_PRODUCERS.get(requirement.operand_code)
        assert contract is not None
        parents = tuple(
            item for item in parent_bindings if item.operand_code == requirement.operand_code
        )
        outputs.append(OperandOutputBindingV1.create(
            operand,
            contract.contract_version,
            parents,
            producer_contract_content_hash=contract.content_hash,
        ))

    repository = _repository(test_producers=True)
    assembly_revision, supersedes_assembly_id = _next_assembly_revision(security)
    persisted = repository.persist(
        assembly,
        assessment,
        assembly_revision=assembly_revision,
        supersedes_assembly_id=supersedes_assembly_id,
        operand_evidence_parents=tuple(parent_bindings),
        operand_output_bindings=tuple(outputs),
    )
    with pytest.raises(
        FundamentalValuePersistenceViolation, match="OPERAND_PRODUCER_UNAVAILABLE"
    ):
        PostgresFundamentalValueBackendV1(DATABASE_URL or "").insert(persisted)
    with pytest.raises(
        FundamentalValuePersistenceViolation, match="OPERAND_PRODUCER_UNAVAILABLE"
    ):
        PostgresFundamentalValueBackendV1(DATABASE_URL or "").load(
            persisted.assembly_id
        )
    assert PostgresFundamentalValueBackendV1(
        DATABASE_URL or "", producer_registry=TEST_PRODUCERS
    ).load(persisted.assembly_id) == persisted
    loaded = repository.load(persisted.assembly_id)

    assert loaded == persisted
    assert loaded.assembly.inputs == inputs
    assert loaded.assessment == assessment
    assert loaded.assessment is not None
    assert loaded.assessment.model_evidence_label.value == "NOT_VALIDATED"
    assert loaded.assessment.final_portfolio_weight_authorized is False
    assert persisted.assessment_id is not None
    _assert_method_weight_tamper_rejected(persisted.assessment_id)

    replaced_parent = parent_bindings[0]
    replacement_aggregate = _controlled_operand_selector(
        v22_seed,
        replaced_parent.operand_code,
        "CONTROLLED_PARENT",
        security=security,
        value=next(
            operand.metric_evidence.value
            for operand in operands
            if operand.operand_code == replaced_parent.operand_code
        ),
        marker=f"{marker}-evidence-only-revision",
    )
    replacement_selected = replacement_aggregate.result.selected
    assert replacement_selected is not None
    replacement_parent = OperandEvidenceParentV1(
        operand_code=replaced_parent.operand_code,
        parent_ordinal=replaced_parent.parent_ordinal,
        evidence_id=replacement_selected.evidence_id,
        source_content_hash=replacement_selected.source_content_hash,
        normalized_record_hash=replacement_selected.normalized_record_hash,
        source_revision=replacement_selected.source_revision,
        effective_at=replacement_selected.effective_at,
        available_at=replacement_selected.available_at,
        ingested_at=replacement_selected.ingested_at,
        dependency_code="TEST_INPUT",
        domain="FUNDAMENTAL",
        field_code="FREE_CASH_FLOW",
        unit="CURRENCY",
        currency=security["currency"],
        fiscal_period="TTM",
        period_start="2025-07-01",
        period_end="2026-06-30",
        canonical_value=replaced_parent.canonical_value,
    )
    revision_parents = tuple(
        replacement_parent if item == replaced_parent else item for item in parent_bindings
    )
    revision_outputs = _output_bindings(tuple(operands), revision_parents)
    revision = repository.persist(
        assembly,
        assessment,
        assembly_revision=assembly_revision + 1,
        supersedes_assembly_id=persisted.assembly_id,
        operand_evidence_parents=revision_parents,
        operand_output_bindings=revision_outputs,
    )
    assert revision.assembly_id != persisted.assembly_id
    assert revision.assessment_id != persisted.assessment_id
    assert revision.assessment is not None
    assert revision.assessment.content_hash == persisted.assessment.content_hash
    assert repository.load(revision.assembly_id) == revision

    with _tampered_operand_value(revision.assembly_id, 1):
        with pytest.raises(FundamentalValuePersistenceViolation):
            repository.load(revision.assembly_id)
    _assert_label_and_cap_elevation_rejected(revision.assessment_id)
    _assert_nonfinite_numeric_values_rejected(revision.assembly_id, revision.assessment_id)
    _assert_ordinary_writer_cannot_bypass(revision.assembly_id)


def test_v23_round_trips_nbn_specialized_zero_operands(v22_seed: IntegrationSeed) -> None:
    marker = f"v23nbn{uuid4().hex[:8]}"
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            security = _seed_security_identity(
                cursor,
                token=marker,
                ticker=f"N{marker[-10:].upper()}",
            )
    classification = _fundamental_value_selector(
        v22_seed,
        company_type="BANK",
        security=security,
        suffix=f"{marker}-classification",
    )
    selected = classification.result.selected
    assert selected is not None
    routing = ModelApplicabilityRouting.create(
        routing_id=str(uuid4()),
        company_id=classification.request.security.company_id,
        classification_evidence_id=selected.evidence_id,
        company_type="BANK",
        applicability=ModelApplicability.SPECIALIZED_MODEL_REQUIRED,
        specialized_model_code="BANK_MODEL_REQUIRED",
        routing_version=APPLICABILITY_ROUTING_VERSION,
        routing_revision=1,
        effective_at=selected.ingested_at,
    )
    v22_seed.repository.persist_applicability_routing(routing)
    repository = _repository()
    app.dependency_overrides[fundamental_routes.get_evidence_repository] = (
        lambda: v22_seed.repository
    )
    app.dependency_overrides[fundamental_routes.get_fundamental_repository] = (
        lambda: repository
    )
    try:
        client = TestClient(app)
        response = client.post(
            "/internal/v1/fundamental-value/decisions",
            json={
                "contractVersion": fundamental_routes.INTERNAL_COMMAND_VERSION,
                "routingId": routing.routing_id,
                "classificationRequestId": str(classification.request_id),
                "operandRequestIds": [],
                "projectionYears": 5,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["companyType"] == "BANK"
        assert payload["applicability"] == "SPECIALIZED_MODEL_REQUIRED"
        assert payload["coreInvocationAuthorized"] is False
        assert payload["assessmentId"] is None
        readback = client.get(
            "/internal/v1/fundamental-value/decisions/" + payload["assemblyId"]
        )
    finally:
        app.dependency_overrides.clear()
    assert readback.status_code == 200
    assert readback.json() == payload
    persisted = repository.load(payload["assemblyId"])
    assert persisted.assembly.operands == ()
    assert persisted.assessment is None


def test_v23_concurrent_initial_insert_has_one_winner(v22_seed: IntegrationSeed) -> None:
    marker = f"v23race{uuid4().hex[:8]}"
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            security = _seed_security_identity(
                cursor,
                token=marker,
                ticker=f"R{marker[-10:].upper()}",
            )
    classification = _fundamental_value_selector(
        v22_seed,
        company_type="MATURE_OPERATING_COMPANY",
        security=security,
        suffix=f"{marker}-classification",
    )
    cash = _fundamental_value_selector(
        v22_seed,
        operand="cash",
        security=security,
        suffix=f"{marker}-cash",
    )
    routing = _routing(v22_seed, classification)
    base = assemble_fundamental_value_from_v22_v1(
        v22_seed.repository,
        _fundamental_value_by_id_request(routing, classification, cash),
    )
    variants = tuple(
        replace(
            draft,
            manifest_content_hash=_content_hash(draft.manifest_payload()),
        )
        for draft in (
            replace(
                base,
                reason_codes=(*base.reason_codes, "CONCURRENT_A"),
                manifest_content_hash="",
            ),
            replace(
                base,
                reason_codes=(*base.reason_codes, "CONCURRENT_B"),
                manifest_content_hash="",
            ),
        )
    )
    barrier = Barrier(2)

    class BarrierBackend(PostgresFundamentalValueBackendV1):
        def insert(self, record):
            barrier.wait(timeout=10)
            return super().insert(record)

    def persist_variant(assembly):
        repository = FundamentalValueRepositoryV1(BarrierBackend(DATABASE_URL or ""))
        try:
            return repository.persist(assembly)
        except FundamentalValuePersistenceConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(persist_variant, variants))

    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert sum(isinstance(item, FundamentalValuePersistenceConflict) for item in outcomes) == 1


def test_v23_concurrent_distinct_revision_two_has_one_winner_and_replays(
    v22_seed: IntegrationSeed,
) -> None:
    marker = f"v23rev2race{uuid4().hex[:8]}"
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            security = _seed_security_identity(
                cursor,
                token=marker,
                ticker=f"Q{marker[-10:].upper()}",
            )
    classification = _fundamental_value_selector(
        v22_seed,
        company_type="MATURE_OPERATING_COMPANY",
        security=security,
        suffix=f"{marker}-classification",
    )
    cash = _fundamental_value_selector(
        v22_seed,
        operand="cash",
        security=security,
        suffix=f"{marker}-cash",
    )
    routing = _routing(v22_seed, classification)
    revision_one_assembly = assemble_fundamental_value_from_v22_v1(
        v22_seed.repository,
        _fundamental_value_by_id_request(routing, classification, cash),
    )
    revision_one = _repository().persist(revision_one_assembly)
    variants = tuple(
        replace(draft, manifest_content_hash=_content_hash(draft.manifest_payload()))
        for draft in (
            replace(
                revision_one_assembly,
                reason_codes=(*revision_one_assembly.reason_codes, "REVISION_TWO_A"),
                manifest_content_hash="",
            ),
            replace(
                revision_one_assembly,
                reason_codes=(*revision_one_assembly.reason_codes, "REVISION_TWO_B"),
                manifest_content_hash="",
            ),
        )
    )
    barrier = Barrier(2)

    class BarrierBackend(PostgresFundamentalValueBackendV1):
        def insert(self, record):
            barrier.wait(timeout=10)
            return super().insert(record)

    def propose(assembly):
        repository = FundamentalValueRepositoryV1(BarrierBackend(DATABASE_URL or ""))
        try:
            return repository.persist(
                assembly,
                assembly_revision=2,
                supersedes_assembly_id=revision_one.assembly_id,
            )
        except FundamentalValuePersistenceConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(propose, variants))

    winners = tuple(item for item in outcomes if not isinstance(item, Exception))
    assert len(winners) == 1
    assert sum(isinstance(item, FundamentalValuePersistenceConflict) for item in outcomes) == 1
    winner = winners[0]
    assert _repository().persist(
        winner.assembly,
        assembly_revision=2,
        supersedes_assembly_id=revision_one.assembly_id,
    ) == winner


def _controlled_operand_selector(
    seed: IntegrationSeed,
    operand_code: str,
    source_kind: str,
    security: dict[str, str],
    value,
    marker: str,
    parent_ordinal: int = 1,
):
    base = candidate_to_payload(seed.primary_envelope.candidate)
    source_hash = "sha256:" + hashlib.sha256(f"{marker}:source".encode()).hexdigest()
    base["evidenceId"] = str(uuid4())
    base["security"] = copy.deepcopy(security)
    base["strictnessClass"] = "STRICT_IDENTITY_AND_CHRONOLOGY"
    base["observationReference"] = f"integration:{marker}"
    base["lineage"].update(
        {
            "sourceRecordId": str(uuid4()),
            "sourceRevision": 1,
            "sourceContentHash": source_hash,
            "normalizedRecordHash": (
                "sha256:" + hashlib.sha256(f"{marker}:normalized".encode()).hexdigest()
            ),
        }
    )
    base["rawManifest"]["sourceContentHash"] = source_hash
    if source_kind in {"DAILY_PRICE", "DIRECT_FUNDAMENTAL"}:
        base["lineage"]["providerCode"] = FUNDAMENTAL_VALUE_TEST_PROVIDER
    payload = json.loads(REQUEST_FIXTURE.read_text(encoding="utf-8"))
    payload["security"] = copy.deepcopy(security)
    payload["completedSession"] = _selection_command(seed.request)["completedSession"]
    payload["decisionTiming"] = _selection_command(seed.request)["decisionTiming"]
    if source_kind == "DAILY_PRICE":
        base["claimClass"] = "CURRENT_ONLY"
        base["lineage"].update(
            {
                "normalizationVersion": "canonical-equity-v1.0.0",
                "freshnessPolicyVersion": "daily-price-completed-session-v1.0.0",
            }
        )
        base["canonicalData"].update({"adjustmentMode": "UNADJUSTED", "close": str(value)})
        payload["selectorPolicy"] = {
            "selectorVersion": "deterministic-evidence-selector-v1.0.0",
            "policyVersion": "daily-price-selection-v1.0.0",
            "domain": "DAILY_PRICE",
            "fieldCode": "CLOSE_PRICE",
            "requiredLayer": "NORMALIZED_OBSERVATION",
            "domainConstraints": {
                "sessionDate": payload["completedSession"]["sessionDate"],
                "adjustmentMode": "UNADJUSTED",
                "currency": security["currency"],
                "mic": security["mic"],
                "listingId": security["listingId"],
            },
            "providerFallbackPriority": [base["lineage"]["providerCode"]],
            "requiredStrictnessClass": "STRICT_IDENTITY_AND_CHRONOLOGY",
            "requiredClaimClass": "CURRENT_ONLY",
            "requiredNormalizationVersion": "canonical-equity-v1.0.0",
        }
    else:
        direct_codes = {
            "diluted_shares": ("DILUTED_SHARES", "SHARES", None, "TTM"),
            "cash": ("CASH_AND_EQUIVALENTS", "CURRENCY", security["currency"], "INSTANT"),
            "debt": ("TOTAL_DEBT", "CURRENCY", security["currency"], "INSTANT"),
            "ebit": ("OPERATING_INCOME", "CURRENCY", security["currency"], "TTM"),
            "capital_expenditures": (
                "CAPITAL_EXPENDITURE",
                "CURRENCY",
                security["currency"],
                "TTM",
            ),
            "normalized_free_cash_flow": (
                "FREE_CASH_FLOW",
                "CURRENCY",
                security["currency"],
                "TTM",
            ),
        }
        if operand_code in direct_codes:
            metric_code, unit, currency, fiscal_period = direct_codes[operand_code]
        else:
            metric_code, unit, fiscal_period = "FREE_CASH_FLOW", "CURRENCY", "TTM"
            currency = security["currency"]
        base["domain"] = "FUNDAMENTAL"
        base["claimClass"] = "STRICT_PIT"
        base["lineage"].update(
            {
                "normalizationVersion": "canonical-fundamental-v1.0.0",
                "freshnessPolicyVersion": "fundamental-quarterly-freshness-v1.0.0",
            }
        )
        base["canonicalData"] = {
            "metricCode": metric_code,
            "numericValue": str(value),
            "unit": unit,
            "currency": currency,
            "periodStart": "2025-07-01" if fiscal_period == "TTM" else None,
            "periodEnd": "2026-06-30",
            "fiscalPeriod": fiscal_period,
            "formType": "10-K",
            "accessionNumber": (
                "0000000000-26-"
                f"{int(hashlib.sha256(marker.encode()).hexdigest()[:6], 16) % 1_000_000:06d}"
            ),
            "filedAt": "2026-07-15T12:00:00Z",
            "mappingVersion": "fundamental-value-mapping-v1.0.0",
        }
        payload["selectorPolicy"] = {
            "selectorVersion": "deterministic-evidence-selector-v1.0.0",
            "policyVersion": (
                f"test-only-fundamental-value-{operand_code.replace('_', '-')}-selection"
                f"-parent-{parent_ordinal}-{seed.token}-v1.0.0"
                if source_kind == "CONTROLLED_PARENT"
                else f"fundamental-value-{operand_code.replace('_', '-')}-selection-v1.0.0"
            ),
            "domain": "FUNDAMENTAL",
            "fieldCode": metric_code,
            "requiredLayer": "NORMALIZED_OBSERVATION",
            "domainConstraints": {
                "metricCode": metric_code,
                "periodEnd": "2026-06-30",
                "unit": unit,
                "currency": currency,
            },
            "providerFallbackPriority": [base["lineage"]["providerCode"]],
            "requiredStrictnessClass": "STRICT_IDENTITY_AND_CHRONOLOGY",
            "requiredClaimClass": "STRICT_PIT",
            "requiredNormalizationVersion": "canonical-fundamental-v1.0.0",
        }
    payload["candidates"] = [base]
    request = EvidenceSelectionRequest.parse(payload)
    seed.repository.persist_candidate(
        PersistedEvidenceEnvelope(
            request.candidates[0],
            f"storage/private/test/{seed.token}/fv-v23/{marker}",
        )
    )
    return seed.repository.execute_selector(request)


def _stable_controlled_valid_security() -> dict[str, str]:
    """Reuse one TEST_ONLY listing because the frozen daily policy binds listing identity."""

    ticker = "FVITVALID"
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT s.public_id AS security_id, c.company_id, i.instrument_id,
                       sc.share_class_id, l.listing_id, ta.ticker_assignment_id,
                       ta.ticker, l.mic, l.currency
                FROM analytics.evidence_ticker_assignment_v1 ta
                JOIN analytics.evidence_listing_identity_v1 l
                  ON l.listing_id = ta.listing_id
                JOIN analytics.evidence_share_class_identity_v1 sc
                  ON sc.share_class_id = l.share_class_id
                JOIN analytics.evidence_instrument_identity_v1 i
                  ON i.instrument_id = sc.instrument_id
                JOIN analytics.evidence_company_identity_v1 c
                  ON c.company_id = i.company_id
                JOIN analytics.security s ON s.public_id = l.security_id
                WHERE ta.ticker = %(ticker)s
                """,
                {"ticker": ticker},
            )
            row = cursor.fetchone()
            if row is None:
                return _seed_security_identity(
                    cursor, token="stable-fv-valid-v1", ticker=ticker
                )
    return {
        "securityId": str(row["security_id"]),
        "companyId": str(row["company_id"]),
        "instrumentId": str(row["instrument_id"]),
        "shareClassId": str(row["share_class_id"]),
        "listingId": str(row["listing_id"]),
        "tickerAssignmentId": str(row["ticker_assignment_id"]),
        "ticker": row["ticker"],
        "mic": row["mic"],
        "currency": row["currency"],
    }


def _next_assembly_revision(security: dict[str, str]) -> tuple[int, str | None]:
    """Append to the stable TEST_ONLY identity across repeated pytest processes."""

    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT assembly_id, assembly_revision
                FROM analytics.fundamental_value_assembly_v1
                WHERE security_id = %(security_id)s
                  AND company_id = %(company_id)s
                  AND instrument_id = %(instrument_id)s
                  AND share_class_id = %(share_class_id)s
                  AND listing_id = %(listing_id)s
                  AND ticker_assignment_id = %(ticker_assignment_id)s
                  AND assembly_version = 'fundamental-value-v22-assembly-v1.0.0'
                ORDER BY assembly_revision DESC
                LIMIT 1
                """,
                {
                    "security_id": security["securityId"],
                    "company_id": security["companyId"],
                    "instrument_id": security["instrumentId"],
                    "share_class_id": security["shareClassId"],
                    "listing_id": security["listingId"],
                    "ticker_assignment_id": security["tickerAssignmentId"],
                },
            )
            latest = cursor.fetchone()
    if latest is None:
        return 1, None
    return latest["assembly_revision"] + 1, str(latest["assembly_id"])


def _output_bindings(
    operands: tuple[AssembledOperandV1, ...],
    parents: tuple[OperandEvidenceParentV1, ...],
) -> tuple[OperandOutputBindingV1, ...]:
    outputs = []
    for requirement, operand in zip(OPERAND_REQUIREMENTS, operands, strict=True):
        if "REQUIRED" not in requirement.source_kind.value:
            continue
        contract = TEST_PRODUCERS.get(requirement.operand_code)
        assert contract is not None
        operand_parents = tuple(
            item for item in parents if item.operand_code == requirement.operand_code
        )
        outputs.append(OperandOutputBindingV1.create(
            operand,
            contract.contract_version,
            operand_parents,
            producer_contract_content_hash=contract.content_hash,
        ))
    return tuple(outputs)


def _seed_test_producer_contracts() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            for contract in TEST_PRODUCERS.contracts:
                cursor.execute(
                    """
                    INSERT INTO analytics.fundamental_value_operand_producer_contract_v1
                    (operand_code, source_kind, contract_version, evaluator_id,
                     governance_status, output_semantics, contract_content_hash,
                     parent_slot_count)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (operand_code, contract_version) DO NOTHING
                    """,
                    (
                        contract.operand_code, contract.source_kind,
                        contract.contract_version, contract.evaluator_id,
                        contract.governance_status, contract.output_semantics,
                        contract.content_hash, len(contract.parent_slots),
                    ),
                )
                for ordinal, slot in enumerate(contract.parent_slots, 1):
                    cursor.execute(
                        """
                        INSERT INTO analytics.fundamental_value_producer_parent_slot_v1
                        (operand_code, contract_version, parent_ordinal, role_code,
                         domain, field_code,
                         unit, currency_rule, fiscal_period, period_identity,
                         period_start, period_end)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (operand_code, contract_version, parent_ordinal) DO NOTHING
                        """,
                        (
                            contract.operand_code, contract.contract_version, ordinal,
                            slot.role_code, slot.domain,
                            slot.field_code, slot.unit, slot.currency_rule,
                            slot.fiscal_period, slot.period_identity,
                            slot.period_start, slot.period_end,
                        ),
                    )


@contextmanager
def _tampered_operand_value(assembly_id: str, ordinal: int):
    table = "fundamental_value_assembly_operand_v1"
    trigger = f"tr_{table}_append_only"
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE analytics.{table} DISABLE TRIGGER {trigger}")
            cursor.execute(
                f"SELECT numeric_value FROM analytics.{table} "
                "WHERE assembly_id=%s AND operand_ordinal=%s",
                (UUID(assembly_id), ordinal),
            )
            original = cursor.fetchone()["numeric_value"]
            cursor.execute(
                f"UPDATE analytics.{table} SET numeric_value=numeric_value+1 "
                "WHERE assembly_id=%s AND operand_ordinal=%s",
                (UUID(assembly_id), ordinal),
            )
            cursor.execute(f"ALTER TABLE analytics.{table} ENABLE TRIGGER {trigger}")
    try:
        yield
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"ALTER TABLE analytics.{table} DISABLE TRIGGER {trigger}")
                cursor.execute(
                    f"UPDATE analytics.{table} SET numeric_value=%s "
                    "WHERE assembly_id=%s AND operand_ordinal=%s",
                    (original, UUID(assembly_id), ordinal),
                )
                cursor.execute(f"ALTER TABLE analytics.{table} ENABLE TRIGGER {trigger}")


def _assert_label_and_cap_elevation_rejected(assessment_id: str | None) -> None:
    assert assessment_id is not None
    cases = (
        ("model_evidence_label='FORWARD_SUPPORTED'",),
        ("risk_cap_ceiling=0.05",),
        (
            "claim_ceiling='LIMITED_MISSING_ADVANCED_EVIDENCE', "
            "risk_cap_ceiling=0.02",
        ),
        (
            "claim_ceiling='BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY', "
            "risk_cap_ceiling=0.01",
        ),
    )
    for (assignment,) in cases:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE analytics.fundamental_value_assessment_v1 "
                    "DISABLE TRIGGER tr_fundamental_value_assessment_v1_append_only"
                )
                with pytest.raises(psycopg.errors.CheckViolation):
                    cursor.execute(
                        "UPDATE analytics.fundamental_value_assessment_v1 "
                        f"SET {assignment} WHERE assessment_id=%s",
                        (UUID(assessment_id),),
                    )
                connection.rollback()


def _assert_ordinary_writer_cannot_bypass(assembly_id: str) -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET ROLE analytics_writer")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute(
                    "INSERT INTO analytics.fundamental_value_assembly_reason_v1 "
                    "(assembly_id, reason_ordinal, reason_code) VALUES (%s, 999, 'BYPASS')",
                    (UUID(assembly_id),),
                )
            connection.rollback()


def _assert_nonfinite_numeric_values_rejected(
    assembly_id: str,
    assessment_id: str | None,
) -> None:
    assert assessment_id is not None
    cases = (
        (
            "fundamental_value_assembly_operand_v1",
            "numeric_value",
            "assembly_id=%s AND operand_ordinal=1",
            (UUID(assembly_id),),
            "'NaN'::numeric",
        ),
        (
            "fundamental_value_assessment_v1",
            "reference_price",
            "assessment_id=%s",
            (UUID(assessment_id),),
            "'Infinity'::numeric",
        ),
        (
            "fundamental_value_dimension_v1",
            "score",
            "assessment_id=%s AND dimension_ordinal=1",
            (UUID(assessment_id),),
            "'-Infinity'::numeric",
        ),
        (
            "fundamental_value_valuation_method_v1",
            "terminal_value_share",
            "assessment_id=%s AND method_ordinal=1",
            (UUID(assessment_id),),
            "'NaN'::numeric",
        ),
        (
            "fundamental_value_valuation_scenario_v1",
            "fair_value_per_share",
            "assessment_id=%s AND method_ordinal=1 AND scenario_ordinal=1",
            (UUID(assessment_id),),
            "'Infinity'::numeric",
        ),
        (
            "fundamental_value_ordered_range_v1",
            "central_value",
            "assessment_id=%s AND range_code='FAIR_VALUE'",
            (UUID(assessment_id),),
            "'NaN'::numeric",
        ),
        (
            "fundamental_value_condition_v1",
            "observed_value",
            "assessment_id=%s AND condition_ordinal=1",
            (UUID(assessment_id),),
            "'-Infinity'::numeric",
        ),
    )
    for table, column, predicate, parameters, value_sql in cases:
        trigger = f"tr_{table}_append_only"
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"ALTER TABLE analytics.{table} DISABLE TRIGGER {trigger}")
                with pytest.raises(psycopg.errors.CheckViolation):
                    cursor.execute(
                        f"UPDATE analytics.{table} SET {column}={value_sql} "
                        f"WHERE {predicate}",
                        parameters,
                    )
                connection.rollback()


def _assert_method_weight_tamper_rejected(assessment_id: str) -> None:
    table = "fundamental_value_valuation_method_v1"
    trigger = f"tr_{table}_append_only"
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE analytics.{table} DISABLE TRIGGER {trigger}")
            with pytest.raises(psycopg.errors.CheckViolation):
                cursor.execute(
                    f"UPDATE analytics.{table} SET method_weight=0.34 "
                    "WHERE assessment_id=%s AND method_code='FCFF_DCF'",
                    (UUID(assessment_id),),
                )
            connection.rollback()


@contextmanager
def _tampered_manifest_hash(assembly_id: str):
    table = "fundamental_value_assembly_v1"
    trigger = f"tr_{table}_append_only"
    original: str
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE analytics.{table} DISABLE TRIGGER {trigger}")
            cursor.execute(
                f"SELECT manifest_content_hash FROM analytics.{table} WHERE assembly_id=%s",
                (UUID(assembly_id),),
            )
            original = cursor.fetchone()["manifest_content_hash"]
            cursor.execute(
                f"UPDATE analytics.{table} SET manifest_content_hash=%s WHERE assembly_id=%s",
                ("sha256:" + ("0" * 64), UUID(assembly_id)),
            )
            cursor.execute(f"ALTER TABLE analytics.{table} ENABLE TRIGGER {trigger}")
    try:
        yield
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"ALTER TABLE analytics.{table} DISABLE TRIGGER {trigger}")
                cursor.execute(
                    f"UPDATE analytics.{table} SET manifest_content_hash=%s WHERE assembly_id=%s",
                    (original, UUID(assembly_id)),
                )
                cursor.execute(f"ALTER TABLE analytics.{table} ENABLE TRIGGER {trigger}")
