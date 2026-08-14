from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

import equity_analysis.fundamental_value.persistence_v1 as persistence_module
from equity_analysis.evidence_foundation.contracts_v1 import SecurityIdentity
from equity_analysis.fundamental_value.contracts_v1 import (
    Applicability,
    CompanyType,
    DataState,
    ModelEvidenceLabel,
)
from equity_analysis.fundamental_value.core_v1 import (
    ClaimCeiling,
    CoreViolation,
    FundamentalValueInputsV1,
    MetricEvidence,
    RiskCapResult,
    _assessment_hash,
    evaluate_fundamental_value_v1,
)
from equity_analysis.fundamental_value.evidence_assembly_v1 import (
    OPERAND_REQUIREMENTS,
    AssembledOperandV1,
    AssemblyVersionSetV1,
    EvidenceSealV1,
    FundamentalValueAssemblyResultV1,
    _content_hash,
)
from equity_analysis.fundamental_value.operand_producers_v1 import (
    OperandProducerContractV1,
    OperandProducerRegistryV1,
    ParentSlotContractV1,
    ProducerParentObservationV1,
    ProducerViolation,
)
from equity_analysis.fundamental_value.persistence_v1 import (
    FundamentalValuePersistenceConflict,
    FundamentalValuePersistenceRecordV1,
    FundamentalValuePersistenceViolation,
    FundamentalValueRepositoryV1,
    OperandEvidenceParentV1,
    OperandOutputBindingV1,
    _parent_from_evidence_seal,
    decimal_from_database,
    decimal_text,
    deterministic_assembly_id_v1,
    deterministic_assessment_id_v1,
    deterministic_input_seal_v1,
)


class _MemoryBackend:
    def __init__(self) -> None:
        self.records: dict[str, FundamentalValuePersistenceRecordV1] = {}
        self.insert_count = 0

    def load(self, assembly_id: str) -> FundamentalValuePersistenceRecordV1:
        try:
            return self.records[assembly_id]
        except KeyError as error:
            raise LookupError(assembly_id) from error

    def insert(self, record: FundamentalValuePersistenceRecordV1) -> None:
        self.insert_count += 1
        if record.assembly_id in self.records:
            raise FundamentalValuePersistenceConflict("duplicate")
        self.records[record.assembly_id] = record


def _identity_evaluator(parents: tuple[ProducerParentObservationV1, ...]) -> Decimal:
    return parents[0].value


def _producer_contract(requirement) -> OperandProducerContractV1:
    unit = requirement.unit or "RATIO"
    currency_rule = (
        "MATCH_OUTPUT" if requirement.currency_bound else "NOT_APPLICABLE"
    )
    period = requirement.fiscal_period or "INSTANT"
    return OperandProducerContractV1(
        operand_code=requirement.operand_code,
        source_kind=requirement.source_kind.value,
        contract_version=(
            "fundamental-value-"
            + requirement.operand_code.replace("_", "-")
            + (
                "-derivation-v1.0.0"
                if requirement.source_kind.value == "DERIVATION_REQUIRED"
                else "-policy-evidence-v1.0.0"
            )
        ),
        evaluator_id="test-only-identity-evaluator-v1",
        governance_status="TEST_ONLY",
        parent_slots=(
            ParentSlotContractV1(
                role_code=f"TEST_ONLY_{requirement.operand_code.upper()}_P01",
                domain="FUNDAMENTAL",
                field_code=f"TEST_ONLY_{requirement.operand_code.upper()}",
                unit=unit,
                currency_rule=currency_rule,
                fiscal_period=period,
                period_identity="CURRENT_COMPLETED_PERIOD",
                period_start="2025-07-01" if period != "INSTANT" else None,
                period_end="2026-06-30",
            ),
        ),
        output_semantics=f"TEST_ONLY_IDENTITY_{unit}",
        evaluator=_identity_evaluator,
    )


TEST_ONLY_PRODUCER_CONTRACTS = tuple(
    _producer_contract(requirement)
    for requirement in OPERAND_REQUIREMENTS
    if "REQUIRED" in requirement.source_kind.value
)
TEST_ONLY_PRODUCER_REGISTRY = OperandProducerRegistryV1(
    TEST_ONLY_PRODUCER_CONTRACTS,
    allow_test_only=True,
)


def _test_repository(backend=None):
    return FundamentalValueRepositoryV1(
        backend or _MemoryBackend(),
        producer_registry=TEST_ONLY_PRODUCER_REGISTRY,
    )


def _bindings(assembly):
    parents = []
    outputs = []
    requirements = {item.operand_code: item for item in OPERAND_REQUIREMENTS}
    for operand in assembly.operands:
        if operand.state != DataState.VALID or operand.evidence_seal is None:
            continue
        seal = operand.evidence_seal
        requirement = requirements[operand.operand_code]
        if "REQUIRED" not in requirement.source_kind.value:
            parents.append(_parent_from_evidence_seal(operand.operand_code, 1, seal))
            continue
        contract = TEST_ONLY_PRODUCER_REGISTRY.get(operand.operand_code)
        assert contract is not None
        slot = contract.parent_slots[0]
        operand_parents = [OperandEvidenceParentV1(
            operand.operand_code,
            1,
            str(uuid5(NAMESPACE_URL, f"{seal.evidence_id}:{slot.role_code}")),
            seal.source_content_hash,
            seal.normalized_record_hash,
            seal.source_revision,
            seal.effective_at,
            seal.available_at,
            seal.ingested_at,
            slot.role_code,
            slot.domain,
            slot.field_code,
            slot.unit,
            assembly.security.currency if slot.currency_rule == "MATCH_OUTPUT" else None,
            slot.fiscal_period,
            "2025-07-01" if slot.fiscal_period != "INSTANT" else None,
            "2026-06-30",
            operand.metric_evidence.value,
        )]
        parents.extend(operand_parents)
        outputs.append(OperandOutputBindingV1.create(
            operand,
            contract.contract_version,
            tuple(operand_parents),
            contract.content_hash,
        ))
    return tuple(parents), tuple(outputs)


def _persist(repository, assembly, assessment=None):
    parents, outputs = _bindings(assembly)
    return repository.persist(
        assembly,
        assessment,
        operand_evidence_parents=parents,
        operand_output_bindings=outputs,
    )


def _assembly_id(assembly):
    parents, outputs = _bindings(assembly)
    return deterministic_assembly_id_v1(assembly, parents, outputs)


def _hash(character: str) -> str:
    return "sha256:" + (character * 64)


def _bank_assembly() -> FundamentalValueAssemblyResultV1:
    security = SecurityIdentity(
        security_id="11111111-1111-4111-8111-111111111111",
        company_id="22222222-2222-4222-8222-222222222222",
        instrument_id="33333333-3333-4333-8333-333333333333",
        share_class_id="44444444-4444-4444-8444-444444444444",
        listing_id="55555555-5555-4555-8555-555555555555",
        ticker_assignment_id="66666666-6666-4666-8666-666666666666",
        ticker="NBN",
        mic="XNYS",
        currency="USD",
    )
    classification = EvidenceSealV1(
        operand_code="company_type",
        request_id="77777777-7777-4777-8777-777777777777",
        request_content_hash=_hash("1"),
        result_content_hash=_hash("2"),
        selector_policy_version="fundamental-value-company-type-selection-v1.0.0",
        selector_version="deterministic-evidence-selector-v1.0.0",
        state=DataState.VALID,
        reason_code="SELECTED_BY_VERSIONED_PROVIDER_FALLBACK",
        evidence_id="88888888-8888-4888-8888-888888888888",
        source_content_hash=_hash("3"),
        normalized_record_hash=_hash("4"),
        source_revision=1,
        effective_at=datetime(2026, 7, 29, 20, tzinfo=UTC),
        available_at=datetime(2026, 7, 29, 20, 1, tzinfo=UTC),
        ingested_at=datetime(2026, 7, 29, 20, 2, tzinfo=UTC),
        freshness_policy_version="classification-current-v1.0.0",
        normalization_version="canonical-classification-v1.0.0",
        provider_schema_version="synthetic-schema-v1",
        adapter_version="synthetic-adapter-v1",
        tolerance_policy_version=None,
        derivation_version=None,
    )
    draft = FundamentalValueAssemblyResultV1(
        state=DataState.NOT_APPLICABLE,
        reason_codes=("APPLICABILITY_SPECIALIZED_MODEL_REQUIRED",),
        company_type=CompanyType.BANK,
        applicability=Applicability.SPECIALIZED_MODEL_REQUIRED,
        security=security,
        routing_id="99999999-9999-4999-8999-999999999999",
        routing_content_hash=_hash("5"),
        routing_revision=1,
        classification_evidence_id=classification.evidence_id or "",
        classification_seal=classification,
        completed_session_date="2026-07-29",
        decision_cutoff=datetime(2026, 7, 29, 20, 5, tzinfo=UTC),
        sealed_ingestion_cutoff=datetime(2026, 7, 29, 20, 6, tzinfo=UTC),
        versions=AssemblyVersionSetV1(),
        projection_years=5,
        operands=(),
        inputs=None,
        manifest_content_hash="",
        core_invocation_authorized=False,
    )
    return replace(draft, manifest_content_hash=_content_hash(draft.manifest_payload()))


def _core_inputs() -> FundamentalValueInputsV1:
    payload = json.loads(
        (
            Path(__file__).parents[2]
            / "contracts"
            / "fundamental-value-v1"
            / "core-assessment.example.json"
        ).read_text(encoding="utf-8")
    )
    return FundamentalValueInputsV1(
        company_type=CompanyType(payload["companyType"]),
        applicability=Applicability(payload["applicability"]),
        projection_years=payload["projectionYears"],
        currency=payload["currency"],
        **{name: MetricEvidence.valid(value) for name, value in payload["validInputs"].items()},
    )


def _valid_assembly() -> FundamentalValueAssemblyResultV1:
    inputs = _core_inputs()
    template = _bank_assembly()
    classification = replace(
        template.classification_seal,
        evidence_id="c0000000-0000-4000-8000-000000000001",
    )
    operands = tuple(
        AssembledOperandV1(
            requirement.operand_code,
            DataState.VALID,
            (),
            EvidenceSealV1(
                operand_code=requirement.operand_code,
                request_id=f"b0000000-0000-4000-8000-{ordinal:012d}",
                request_content_hash=_hash("6"),
                result_content_hash=_hash("7"),
                selector_policy_version="synthetic-persistence-fixture-v1",
                selector_version="deterministic-evidence-selector-v1.0.0",
                state=DataState.VALID,
                reason_code="SELECTED_BY_VERSIONED_PROVIDER_FALLBACK",
                evidence_id=f"a0000000-0000-4000-8000-{ordinal:012d}",
                source_content_hash=_hash("8"),
                normalized_record_hash=_hash("9"),
                source_revision=1,
                effective_at=datetime(2026, 7, 29, 20, tzinfo=UTC),
                available_at=datetime(2026, 7, 29, 20, 1, tzinfo=UTC),
                ingested_at=datetime(2026, 7, 29, 20, 2, tzinfo=UTC),
                freshness_policy_version="synthetic-freshness-v1",
                normalization_version="synthetic-normalization-v1",
                provider_schema_version="synthetic-schema-v1",
                adapter_version="synthetic-adapter-v1",
                tolerance_policy_version=None,
                derivation_version=(
                    "fundamental-value-"
                    + requirement.operand_code.replace("_", "-")
                    + (
                        "-derivation-v1.0.0"
                        if requirement.source_kind.value == "DERIVATION_REQUIRED"
                        else "-policy-evidence-v1.0.0"
                    )
                    if "REQUIRED" in requirement.source_kind.value
                    else None
                ),
            ),
            getattr(inputs, requirement.operand_code),
        )
        for ordinal, requirement in enumerate(OPERAND_REQUIREMENTS, start=1)
    )
    draft = replace(
        template,
        state=DataState.VALID,
        reason_codes=(),
        company_type=CompanyType.MATURE_OPERATING_COMPANY,
        applicability=Applicability.APPLICABLE,
        security=replace(template.security, ticker="SYN"),
        classification_evidence_id=classification.evidence_id or "",
        classification_seal=classification,
        operands=operands,
        inputs=inputs,
        manifest_content_hash="",
        core_invocation_authorized=True,
    )
    return replace(draft, manifest_content_hash=_content_hash(draft.manifest_payload()))


def test_specialized_assembly_exact_replay_is_idempotent() -> None:
    backend = _MemoryBackend()
    repository = FundamentalValueRepositoryV1(backend)
    assembly = _bank_assembly()

    first = _persist(repository, assembly)
    replay = _persist(repository, assembly)

    assert first == replay == repository.load(first.assembly_id)
    assert backend.insert_count == 1
    assert first.assessment is None
    assert first.assembly.inputs is None


def test_deterministic_ids_and_hash_tamper_fail_closed() -> None:
    assembly = _bank_assembly()
    assert _assembly_id(assembly) == _assembly_id(assembly)

    with pytest.raises(ValueError, match="CONTENT_HASH_DRIFT"):
        deterministic_assembly_id_v1(replace(assembly, manifest_content_hash=_hash("0")))


def test_immutable_identity_reuse_with_revision_drift_conflicts() -> None:
    assembly = _bank_assembly()
    backend = _MemoryBackend()
    repository = FundamentalValueRepositoryV1(backend)
    persisted = _persist(repository, assembly)
    backend.records[persisted.assembly_id] = replace(persisted, assembly_revision=2)

    with pytest.raises(FundamentalValuePersistenceConflict, match="immutable identity"):
        _persist(repository, assembly)


def test_assessment_codec_enforces_known_hash_versions_and_cardinalities() -> None:
    assessment = evaluate_fundamental_value_v1(_core_inputs())
    assembly_id = deterministic_assembly_id_v1(_valid_assembly())

    assert assessment.content_hash == _hash_value_from_fixture("resultHash")
    assert deterministic_assessment_id_v1(
        assessment, assembly_id
    ) == deterministic_assessment_id_v1(assessment, assembly_id)

    with pytest.raises(FundamentalValuePersistenceViolation, match="CONTENT_HASH_DRIFT"):
        deterministic_assessment_id_v1(
            replace(assessment, content_hash=_hash("0")), assembly_id
        )
    truncated = replace(assessment, valuations=assessment.valuations[:-1], content_hash="")
    truncated = replace(truncated, content_hash=_assessment_hash(truncated))
    with pytest.raises(FundamentalValuePersistenceViolation, match="METHOD_CARDINALITY"):
        deterministic_assessment_id_v1(truncated, assembly_id)


def test_decimal_database_boundary_uses_plain_finite_text() -> None:
    assert decimal_text(Decimal("1E+3")) == "1000"
    assert decimal_text(Decimal("0.0100")) == "0.0100"
    assert decimal_from_database("0.0100") == Decimal("0.0100")
    assert decimal_from_database(None, nullable=True) is None
    with pytest.raises(FundamentalValuePersistenceViolation, match="NONFINITE"):
        decimal_text(Decimal("NaN"))


def test_duplicate_operand_and_classification_evidence_fails_closed() -> None:
    assembly = _valid_assembly()
    first = assembly.operands[0]
    assert first.evidence_seal is not None
    duplicate = replace(
        first,
        evidence_seal=replace(
            first.evidence_seal,
            evidence_id=assembly.classification_evidence_id,
        ),
    )
    drifted = replace(
        assembly,
        operands=(duplicate, *assembly.operands[1:]),
        manifest_content_hash="",
    )
    drifted = replace(drifted, manifest_content_hash=_content_hash(drifted.manifest_payload()))

    with pytest.raises(FundamentalValuePersistenceViolation, match="DUPLICATE_SELECTED"):
        FundamentalValuePersistenceRecordV1(
            deterministic_assembly_id_v1(drifted),
            drifted,
            None,
            None,
        )


def test_self_hashed_assessment_arithmetic_drift_fails_core_recomputation() -> None:
    assembly = _valid_assembly()
    assessment = evaluate_fundamental_value_v1(assembly.inputs)
    altered_range = replace(
        assessment.fair_value,
        central=assessment.fair_value.central + Decimal("0.01"),
    )
    altered = replace(assessment, fair_value=altered_range, content_hash="")
    altered = replace(altered, content_hash=_assessment_hash(altered))

    with pytest.raises(FundamentalValuePersistenceViolation, match="CORE_RECOMPUTATION"):
        assembly_id = _assembly_id(assembly)
        parents, outputs = _bindings(assembly)
        FundamentalValuePersistenceRecordV1(
            assembly_id,
            assembly,
            deterministic_assessment_id_v1(altered, assembly_id),
            altered,
            operand_evidence_parents=parents,
            operand_output_bindings=outputs,
        )


def test_private_input_seal_binds_values_and_utc_instants() -> None:
    assembly = _valid_assembly()
    record = _persist(_test_repository(), assembly)
    changed_operand = replace(
        assembly.operands[0],
        metric_evidence=MetricEvidence.valid(
            assembly.operands[0].metric_evidence.value + Decimal("0.01")
        ),
    )
    changed = replace(assembly, operands=(changed_operand, *assembly.operands[1:]))
    changed_seal = deterministic_input_seal_v1(
        changed, record.operand_evidence_parents, record.operand_output_bindings
    )
    assert changed_seal.content_hash != record.input_seal.content_hash

    parent = record.operand_evidence_parents[0]
    equivalent_parent = replace(
        parent,
        effective_at=parent.effective_at.astimezone(timezone(-timedelta(hours=7))),
        available_at=parent.available_at.astimezone(timezone(-timedelta(hours=7))),
        ingested_at=parent.ingested_at.astimezone(timezone(-timedelta(hours=7))),
        content_hash="",
    )
    assert equivalent_parent.content_hash == parent.content_hash
    with pytest.raises(FundamentalValuePersistenceViolation, match="TIMEZONE_AWARE"):
        replace(parent, effective_at=parent.effective_at.replace(tzinfo=None), content_hash="")


def test_core_invocation_authority_is_biconditional() -> None:
    assembly = _valid_assembly()
    unauthorized = replace(assembly, core_invocation_authorized=False, manifest_content_hash="")
    unauthorized = replace(
        unauthorized,
        manifest_content_hash=_content_hash(unauthorized.manifest_payload()),
    )
    with pytest.raises(FundamentalValuePersistenceViolation, match="BICONDITIONAL"):
        _persist(_test_repository(), unauthorized)


def test_applicable_cardinality_and_optional_operands_are_frozen() -> None:
    assembly = _valid_assembly()
    prefix = replace(
        assembly,
        state=DataState.MISSING,
        reason_codes=("INCOMPLETE",),
        operands=assembly.operands[:1],
        inputs=None,
        core_invocation_authorized=False,
        manifest_content_hash="",
    )
    prefix = replace(prefix, manifest_content_hash=_content_hash(prefix.manifest_payload()))
    with pytest.raises(FundamentalValuePersistenceViolation, match="CARDINALITY_INVALID"):
        FundamentalValueRepositoryV1(_MemoryBackend()).persist(prefix)

    optional_codes = {"comparable_ev_to_ebitda", "net_distribution_yield", "debt_maturity_schedule"}
    reason = "OPTIONAL_EVIDENCE_MISSING"
    operands = tuple(
        replace(
            operand,
            state=DataState.MISSING,
            reason_codes=(reason,),
            evidence_seal=None,
            metric_evidence=MetricEvidence.missing(reason),
        )
        if operand.operand_code in optional_codes
        else operand
        for operand in assembly.operands
    )
    inputs = replace(
        assembly.inputs,
        **{code: MetricEvidence.missing(reason) for code in optional_codes},
    )
    optional_missing = replace(
        assembly,
        operands=operands,
        inputs=inputs,
        manifest_content_hash="",
    )
    optional_missing = replace(
        optional_missing,
        manifest_content_hash=_content_hash(optional_missing.manifest_payload()),
    )
    persisted = _persist(_test_repository(), optional_missing)
    assert persisted.assembly.core_invocation_authorized is True


def test_stage_four_assessment_label_is_frozen_not_validated() -> None:
    assembly = _valid_assembly()
    assessment = evaluate_fundamental_value_v1(
        assembly.inputs,
        model_evidence_label=ModelEvidenceLabel.DEVELOPMENT_OBSERVED,
    )
    with pytest.raises(FundamentalValuePersistenceViolation, match="NOT_FROZEN"):
        _persist(_test_repository(), assembly, assessment)


def test_claim_ceiling_and_risk_cap_elevation_fail_closed() -> None:
    assembly = _valid_assembly()
    assessment = evaluate_fundamental_value_v1(assembly.inputs)
    elevated = replace(
        assessment,
        claim_ceiling=ClaimCeiling.LIMITED_MISSING_ADVANCED_EVIDENCE,
        risk_cap=RiskCapResult(Decimal("0.05"), ("FABRICATED_ELEVATION",)),
        content_hash="",
    )
    elevated = replace(elevated, content_hash=_assessment_hash(elevated))
    with pytest.raises(
        FundamentalValuePersistenceViolation,
        match="CLAIM_CEILING_DRIFT|RISK_CAP_DRIFT",
    ):
        _persist(_test_repository(), assembly, elevated)


def test_output_version_hash_and_unrelated_parent_reuse_fail_closed() -> None:
    assembly = _valid_assembly()
    record = _persist(_test_repository(), assembly)
    output = record.operand_output_bindings[0]
    version_drift = (
        replace(output, output_version="unregistered-v1"),
        *record.operand_output_bindings[1:],
    )
    with pytest.raises(
        FundamentalValuePersistenceViolation,
        match="OUTPUT_CONTENT_HASH_DRIFT|OUTPUT_VERSION_DRIFT",
    ):
        FundamentalValuePersistenceRecordV1(
            deterministic_assembly_id_v1(
                assembly, record.operand_evidence_parents, version_drift
            ),
            assembly,
            None,
            None,
            operand_evidence_parents=record.operand_evidence_parents,
            operand_output_bindings=version_drift,
        )
    hash_drift = (
        replace(output, output_content_hash=_hash("0")),
        *record.operand_output_bindings[1:],
    )
    with pytest.raises(FundamentalValuePersistenceViolation, match="OUTPUT_CONTENT_HASH_DRIFT"):
        FundamentalValuePersistenceRecordV1(
            deterministic_assembly_id_v1(
                assembly, record.operand_evidence_parents, hash_drift
            ),
            assembly,
            None,
            None,
            operand_evidence_parents=record.operand_evidence_parents,
            operand_output_bindings=hash_drift,
        )


def test_production_registry_is_empty_and_fails_closed() -> None:
    assembly = _valid_assembly()
    with pytest.raises(FundamentalValuePersistenceViolation, match="PRODUCER_UNAVAILABLE"):
        _persist(FundamentalValueRepositoryV1(_MemoryBackend()), assembly)


def test_duplicate_parent_evidence_and_plus_one_evaluator_fail_closed() -> None:
    contract = TEST_ONLY_PRODUCER_CONTRACTS[0]
    slot = contract.parent_slots[0]
    two_slot_contract = replace(
        contract,
        parent_slots=(slot, replace(slot, role_code=f"{slot.role_code}_SECOND")),
        content_hash="",
    )
    observation = ProducerParentObservationV1(
        slot.role_code,
        "10000000-0000-4000-8000-000000000001",
        slot.domain,
        slot.field_code,
        slot.unit,
        "USD" if slot.currency_rule == "MATCH_OUTPUT" else None,
        slot.fiscal_period,
        "2025-07-01" if slot.fiscal_period != "INSTANT" else None,
        "2026-06-30",
        Decimal("1"),
    )
    with pytest.raises(ProducerViolation, match="DUPLICATE_PRODUCER_PARENT"):
        two_slot_contract.evaluate(
            (observation, replace(observation, role_code=f"{slot.role_code}_SECOND"))
        )

    def plus_one(parents: tuple[ProducerParentObservationV1, ...]) -> Decimal:
        return parents[0].value + Decimal("1")

    plus_one_contract = replace(contract, evaluator=plus_one)
    mismatch_registry = OperandProducerRegistryV1(
        (plus_one_contract, *TEST_ONLY_PRODUCER_CONTRACTS[1:]),
        allow_test_only=True,
    )
    repository = FundamentalValueRepositoryV1(
        _MemoryBackend(), producer_registry=mismatch_registry
    )
    with pytest.raises(FundamentalValuePersistenceViolation, match="PRODUCER_OUTPUT_DRIFT"):
        _persist(repository, _valid_assembly())


def test_producer_currency_rule_vocabulary_and_semantics_match_v23() -> None:
    slot = TEST_ONLY_PRODUCER_CONTRACTS[0].parent_slots[0]
    with pytest.raises(ProducerViolation, match="CURRENCY_RULE_INVALID"):
        replace(slot, currency_rule="NONE")

    not_applicable = replace(slot, currency_rule="NOT_APPLICABLE")
    contract = replace(
        TEST_ONLY_PRODUCER_CONTRACTS[0],
        parent_slots=(not_applicable,),
        content_hash="",
    )
    observation = ProducerParentObservationV1(
        not_applicable.role_code,
        "10000000-0000-4000-8000-000000000001",
        not_applicable.domain,
        not_applicable.field_code,
        not_applicable.unit,
        None,
        not_applicable.fiscal_period,
        not_applicable.period_start,
        not_applicable.period_end,
        Decimal("1"),
    )
    assert contract.evaluate((observation,)) == Decimal("1")
    with pytest.raises(ProducerViolation, match="PARENT_SEMANTICS_DRIFT"):
        contract.evaluate((replace(observation, currency="USD"),))


def test_core_replay_exception_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    assembly = _valid_assembly()
    assessment = evaluate_fundamental_value_v1(assembly.inputs)

    def fail_replay(*args, **kwargs):
        raise CoreViolation("corrupt persisted input")

    monkeypatch.setattr(persistence_module, "evaluate_fundamental_value_v1", fail_replay)
    assembly_id = _assembly_id(assembly)
    parents, outputs = _bindings(assembly)
    with pytest.raises(FundamentalValuePersistenceViolation, match="CORE_RECOMPUTATION_DRIFT"):
        FundamentalValuePersistenceRecordV1(
            assembly_id,
            assembly,
            deterministic_assessment_id_v1(assessment, assembly_id),
            assessment,
            operand_evidence_parents=parents,
            operand_output_bindings=outputs,
        )


def test_assessment_identity_binds_assembly_identity() -> None:
    assessment = evaluate_fundamental_value_v1(_core_inputs())
    first = "10000000-0000-4000-8000-000000000001"
    second = "10000000-0000-4000-8000-000000000002"
    assert deterministic_assessment_id_v1(
        assessment, first
    ) != deterministic_assessment_id_v1(assessment, second)


def _hash_value_from_fixture(name: str) -> str:
    payload = json.loads(
        (
            Path(__file__).parents[2]
            / "contracts"
            / "fundamental-value-v1"
            / "core-assessment.example.json"
        ).read_text(encoding="utf-8")
    )
    return payload["expected"][name]
