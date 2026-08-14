from __future__ import annotations

# Long SQL literals intentionally retain one-to-one column ordering with V23.
# ruff: noqa: E501
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.rows import dict_row

from equity_analysis.evidence_foundation.contracts_v1 import SecurityIdentity
from equity_analysis.fundamental_value.contracts_v1 import (
    AGGREGATION_VERSION,
    MODEL_VERSION,
    RISK_CAP_VERSION,
    STRATEGY_VERSION,
    Applicability,
    CompanyType,
    DataState,
    MethodRole,
    ModelEvidenceLabel,
    ValuationMethod,
)
from equity_analysis.fundamental_value.core_v1 import (
    ASSUMPTION_POLICY_VERSION,
    FORMULA_VERSION,
    METHOD_WEIGHTS,
    ClaimCeiling,
    CoreViolation,
    DimensionResult,
    FundamentalValueAssessmentV1,
    FundamentalValueInputsV1,
    MetricEvidence,
    OrderedRange,
    RiskCapResult,
    ThesisCondition,
    ValuationResult,
    _assessment_hash,
    _inputs_hash,
    canonical_decimal_text,
    evaluate_fundamental_value_v1,
)
from equity_analysis.fundamental_value.evidence_assembly_v1 import (
    MANIFEST_VERSION,
    OPERAND_REQUIREMENTS,
    AssembledOperandV1,
    AssemblyVersionSetV1,
    EvidenceSealV1,
    FundamentalValueAssemblyResultV1,
    OperandSourceKind,
    verify_manifest_content_hash,
)
from equity_analysis.fundamental_value.operand_producers_v1 import (
    PRODUCTION_OPERAND_PRODUCERS_V1,
    OperandProducerRegistryV1,
    ProducerParentObservationV1,
    ProducerViolation,
)

ASSEMBLY_PERSISTENCE_VERSION = "fundamental-value-assembly-persistence-v1.0.0"
ASSESSMENT_PERSISTENCE_VERSION = "fundamental-value-assessment-persistence-v1.0.0"
SLEEVE = "LONG_TERM_CORE"
HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")

DIMENSION_CODES = (
    "COMPANY_QUALITY",
    "FINANCIAL_RESILIENCE",
    "EARNINGS_AND_CASH_FLOW_QUALITY",
    "CAPITAL_ALLOCATION_QUALITY",
    "DOWNSIDE_RISK",
)
RANGE_CODES = ("FAIR_VALUE", "MARGIN_OF_SAFETY", "EXPECTED_RETURN")
CONDITION_CODES = {
    "THESIS": (
        "QUALITY_AT_LEAST_65",
        "RESILIENCE_AT_LEAST_60",
        "CONSERVATIVE_MARGIN_OF_SAFETY_AT_LEAST_15_PERCENT",
    ),
    "COUNTER_THESIS": ("DOWNSIDE_RISK_AT_LEAST_60", "NET_DEBT_TO_EBITDA_ABOVE_3"),
    "INVALIDATION": (
        "ROIC_BELOW_8_PERCENT",
        "INTEREST_COVERAGE_BELOW_3",
        "CENTRAL_MARGIN_OF_SAFETY_BELOW_ZERO",
    ),
}


class FundamentalValuePersistenceViolation(ValueError):
    """Raised when V23 content is not an exact typed replay."""


class FundamentalValuePersistenceConflict(RuntimeError):
    """Raised when an immutable V23 identity is reused with different content."""


@dataclass(frozen=True)
class OperandEvidenceParentV1:
    operand_code: str
    parent_ordinal: int
    evidence_id: str
    source_content_hash: str
    normalized_record_hash: str
    source_revision: int
    effective_at: datetime
    available_at: datetime
    ingested_at: datetime
    dependency_code: str = ""
    domain: str | None = None
    field_code: str | None = None
    unit: str | None = None
    currency: str | None = None
    fiscal_period: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    canonical_value: Decimal | None = None
    content_hash: str = ""

    def __post_init__(self) -> None:
        _canonical_uuid(self.evidence_id, "OPERAND_PARENT_EVIDENCE_ID_INVALID")
        if type(self.parent_ordinal) is not int or self.parent_ordinal < 1:
            raise FundamentalValuePersistenceViolation("OPERAND_PARENT_ORDINAL_INVALID")
        if not self.operand_code.strip() or self.source_revision < 1:
            raise FundamentalValuePersistenceViolation("OPERAND_PARENT_IDENTITY_INVALID")
        if not self.dependency_code:
            object.__setattr__(self, "dependency_code", "SELECTED_CANONICAL_OPERAND")
        if any(
            HASH_PATTERN.fullmatch(value) is None
            for value in (self.source_content_hash, self.normalized_record_hash)
        ):
            raise FundamentalValuePersistenceViolation("OPERAND_PARENT_HASH_INVALID")
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.effective_at, self.available_at, self.ingested_at)
        ):
            raise FundamentalValuePersistenceViolation("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
        if not self.effective_at <= self.available_at <= self.ingested_at:
            raise FundamentalValuePersistenceViolation("OPERAND_PARENT_CHRONOLOGY_INVALID")
        expected = _operand_parent_hash(self)
        if self.content_hash and self.content_hash != expected:
            raise FundamentalValuePersistenceViolation("OPERAND_PARENT_CONTENT_HASH_DRIFT")
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)


@dataclass(frozen=True)
class OperandOutputBindingV1:
    operand_code: str
    output_version: str
    output_content_hash: str
    producer_contract_content_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.operand_code.strip() or not self.output_version.strip():
            raise FundamentalValuePersistenceViolation("OPERAND_OUTPUT_VERSION_INVALID")
        if HASH_PATTERN.fullmatch(self.output_content_hash) is None:
            raise FundamentalValuePersistenceViolation("OPERAND_OUTPUT_HASH_INVALID")
        if self.producer_contract_content_hash is not None and HASH_PATTERN.fullmatch(
            self.producer_contract_content_hash
        ) is None:
            raise FundamentalValuePersistenceViolation("PRODUCER_CONTRACT_HASH_INVALID")

    @classmethod
    def create(
        cls,
        operand: AssembledOperandV1,
        output_version: str,
        parents: tuple[OperandEvidenceParentV1, ...],
        producer_contract_content_hash: str | None = None,
    ) -> OperandOutputBindingV1:
        return cls(
            operand.operand_code,
            output_version,
            _operand_output_hash(operand, output_version, parents),
            producer_contract_content_hash,
        )


@dataclass(frozen=True)
class DeterministicInputSealV1:
    seal_version: str
    content_hash: str

    def __post_init__(self) -> None:
        if self.seal_version != "fundamental-value-private-input-seal-v1.0.0":
            raise FundamentalValuePersistenceViolation("INPUT_SEAL_VERSION_DRIFT")
        if HASH_PATTERN.fullmatch(self.content_hash) is None:
            raise FundamentalValuePersistenceViolation("INPUT_SEAL_HASH_INVALID")


@dataclass(frozen=True)
class FundamentalValuePersistenceRecordV1:
    assembly_id: str
    assembly: FundamentalValueAssemblyResultV1
    assessment_id: str | None
    assessment: FundamentalValueAssessmentV1 | None
    assembly_revision: int = 1
    supersedes_assembly_id: str | None = None
    operand_evidence_parents: tuple[OperandEvidenceParentV1, ...] = ()
    operand_output_bindings: tuple[OperandOutputBindingV1, ...] = ()
    input_seal: DeterministicInputSealV1 | None = None

    def __post_init__(self) -> None:
        _canonical_uuid(self.assembly_id, "ASSEMBLY_ID_INVALID")
        if self.assessment_id is not None:
            _canonical_uuid(self.assessment_id, "ASSESSMENT_ID_INVALID")
        if self.supersedes_assembly_id is not None:
            _canonical_uuid(self.supersedes_assembly_id, "SUPERSEDED_ASSEMBLY_ID_INVALID")
        if type(self.assembly_revision) is not int or self.assembly_revision < 1:
            raise FundamentalValuePersistenceViolation("ASSEMBLY_REVISION_INVALID")
        if (self.assessment_id is None) != (self.assessment is None):
            raise FundamentalValuePersistenceViolation("ASSESSMENT_ID_AND_VALUE_MUST_COEXIST")
        if type(self.operand_evidence_parents) is not tuple:
            raise FundamentalValuePersistenceViolation("OPERAND_PARENT_SET_MUST_BE_TUPLE")
        object.__setattr__(
            self,
            "operand_evidence_parents",
            _complete_parent_set(self.assembly, self.operand_evidence_parents),
        )
        object.__setattr__(
            self,
            "operand_output_bindings",
            _complete_output_bindings(
                self.assembly,
                self.operand_evidence_parents,
                self.operand_output_bindings,
            ),
        )
        expected_seal = deterministic_input_seal_v1(
            self.assembly,
            self.operand_evidence_parents,
            self.operand_output_bindings,
        )
        if self.input_seal is not None and self.input_seal != expected_seal:
            raise FundamentalValuePersistenceViolation("INPUT_SEAL_CONTENT_DRIFT")
        object.__setattr__(self, "input_seal", expected_seal)
        validate_persistence_record_v1(self)


class FundamentalValuePersistenceBackendV1(Protocol):
    def load(self, assembly_id: str) -> FundamentalValuePersistenceRecordV1: ...

    def insert(self, record: FundamentalValuePersistenceRecordV1) -> None: ...


class FundamentalValueRepositoryV1:
    """Typed exact-replay boundary for the append-only V23 store."""

    def __init__(
        self,
        backend: FundamentalValuePersistenceBackendV1,
        *,
        producer_registry: OperandProducerRegistryV1 = PRODUCTION_OPERAND_PRODUCERS_V1,
    ) -> None:
        self._backend = backend
        self._producer_registry = producer_registry

    def persist(
        self,
        assembly: FundamentalValueAssemblyResultV1,
        assessment: FundamentalValueAssessmentV1 | None = None,
        *,
        assembly_revision: int = 1,
        supersedes_assembly_id: str | None = None,
        operand_evidence_parents: tuple[OperandEvidenceParentV1, ...] = (),
        operand_output_bindings: tuple[OperandOutputBindingV1, ...] = (),
    ) -> FundamentalValuePersistenceRecordV1:
        normalized_parents = _complete_parent_set(assembly, operand_evidence_parents)
        normalized_outputs = _complete_output_bindings(
            assembly, normalized_parents, operand_output_bindings
        )
        assembly_id = deterministic_assembly_id_v1(
            assembly, normalized_parents, normalized_outputs
        )
        assessment_id = (
            deterministic_assessment_id_v1(assessment, assembly_id) if assessment else None
        )
        record = FundamentalValuePersistenceRecordV1(
            assembly_id,
            assembly,
            assessment_id,
            assessment,
            assembly_revision,
            supersedes_assembly_id,
            normalized_parents,
            normalized_outputs,
        )
        _validate_operand_producers(record, self._producer_registry)
        try:
            existing = self._backend.load(assembly_id)
        except LookupError:
            try:
                self._backend.insert(record)
            except FundamentalValuePersistenceConflict as error:
                try:
                    existing = self._backend.load(assembly_id)
                except LookupError as error:
                    raise FundamentalValuePersistenceConflict(
                        "V23 uniqueness conflict is not an exact replay"
                    ) from error
                if existing != record:
                    raise FundamentalValuePersistenceConflict(
                        "V23 immutable identity conflicts with persisted content"
                    ) from error
                _validate_operand_producers(existing, self._producer_registry)
                return existing
            return record
        if existing != record:
            raise FundamentalValuePersistenceConflict(
                "V23 immutable identity conflicts with persisted content"
            )
        _validate_operand_producers(existing, self._producer_registry)
        return existing

    def load(self, assembly_id: str) -> FundamentalValuePersistenceRecordV1:
        record = self._backend.load(assembly_id)
        validate_persistence_record_v1(record)
        _validate_operand_producers(record, self._producer_registry)
        return record


class PostgresFundamentalValueBackendV1:
    """Normalized PostgreSQL V23 storage; every read rebuilds typed objects."""

    def __init__(
        self,
        database_url: str,
        *,
        connect: Any = psycopg.connect,
        producer_registry: OperandProducerRegistryV1 = PRODUCTION_OPERAND_PRODUCERS_V1,
    ) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise ValueError("Analytics database URL is required")
        self._database_url = database_url
        self._connect = connect
        self._producer_registry = producer_registry

    def insert(self, record: FundamentalValuePersistenceRecordV1) -> None:
        validate_persistence_record_v1(record)
        _validate_operand_producers(record, self._producer_registry)
        try:
            with self._connect(self._database_url, row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    self._insert_assembly(cursor, record)
                    if record.assessment is not None:
                        self._insert_assessment(cursor, record)
        except psycopg.errors.UniqueViolation as error:
            raise FundamentalValuePersistenceConflict(
                "V23 immutable identity uniqueness conflict"
            ) from error
        except psycopg.errors.RaiseException as error:
            if any(
                reason in str(error)
                for reason in (
                    "Fundamental Value assembly must supersede the latest revision",
                    "Initial Fundamental Value assembly must start revision one",
                )
            ):
                raise FundamentalValuePersistenceConflict(
                    "V23 immutable identity revision conflict"
                ) from error
            raise

    def load(self, assembly_id: str) -> FundamentalValuePersistenceRecordV1:
        checked_id = UUID(assembly_id)
        with self._connect(self._database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(_SELECT_ASSEMBLY, {"assembly_id": checked_id})
                root = cursor.fetchone()
                if root is None:
                    raise LookupError(f"Fundamental Value assembly {assembly_id} was not found")
                cursor.execute(
                    """SELECT reason_code FROM analytics.fundamental_value_assembly_reason_v1
                       WHERE assembly_id=%(assembly_id)s ORDER BY reason_ordinal""",
                    {"assembly_id": checked_id},
                )
                assembly_reasons = tuple(row["reason_code"] for row in cursor.fetchall())
                cursor.execute(
                    """SELECT operand.*, result.selector_version,
                              result.reason_code AS selector_reason_code,
                              evidence.domain AS selected_domain,
                              evidence.canonical_data AS selected_canonical_data
                       FROM analytics.fundamental_value_assembly_operand_v1 operand
                       LEFT JOIN analytics.evidence_selection_result_v1 result
                         ON result.request_id=operand.selector_request_id
                       LEFT JOIN analytics.canonical_evidence_v1 evidence
                         ON evidence.evidence_id=operand.selected_evidence_id
                       WHERE operand.assembly_id=%(assembly_id)s
                       ORDER BY operand.operand_ordinal""",
                    {"assembly_id": checked_id},
                )
                operand_rows = tuple(cursor.fetchall())
                cursor.execute(
                    """SELECT operand_ordinal, reason_code
                       FROM analytics.fundamental_value_operand_reason_v1
                       WHERE assembly_id=%(assembly_id)s
                       ORDER BY operand_ordinal, reason_ordinal""",
                    {"assembly_id": checked_id},
                )
                operand_reason_rows = tuple(cursor.fetchall())
                cursor.execute(
                    """SELECT parent.*, operand.operand_code, operand.source_kind,
                              evidence.domain,
                              evidence.canonical_data
                       FROM analytics.fundamental_value_operand_evidence_v1 parent
                       JOIN analytics.fundamental_value_assembly_operand_v1 operand
                        ON operand.assembly_id=parent.assembly_id
                        AND operand.operand_ordinal=parent.operand_ordinal
                       JOIN analytics.canonical_evidence_v1 evidence
                         ON evidence.evidence_id=parent.evidence_id
                       WHERE parent.assembly_id=%(assembly_id)s
                       ORDER BY parent.operand_ordinal,parent.parent_ordinal""",
                    {"assembly_id": checked_id},
                )
                operand_parents = tuple(_operand_parent_from_row(row) for row in cursor.fetchall())
                cursor.execute(
                    """SELECT * FROM analytics.fundamental_value_assessment_v1
                       WHERE assembly_id=%(assembly_id)s""",
                    {"assembly_id": checked_id},
                )
                assessment_root = cursor.fetchone()
                assessment_rows = (
                    self._load_assessment_rows(cursor, assessment_root["assessment_id"])
                    if assessment_root is not None
                    else None
                )
        assembly = _assembly_from_rows(root, assembly_reasons, operand_rows, operand_reason_rows)
        operand_outputs = _output_bindings_from_rows(
            assembly, operand_rows, operand_parents
        )
        assessment = (
            _assessment_from_rows(assessment_root, assessment_rows)
            if assessment_root is not None and assessment_rows is not None
            else None
        )
        record = FundamentalValuePersistenceRecordV1(
            assembly_id=str(root["assembly_id"]),
            assembly=assembly,
            assessment_id=(str(assessment_root["assessment_id"]) if assessment_root else None),
            assessment=assessment,
            assembly_revision=root["assembly_revision"],
            supersedes_assembly_id=(
                str(root["supersedes_assembly_id"])
                if root["supersedes_assembly_id"] is not None
                else None
            ),
            operand_evidence_parents=operand_parents,
            operand_output_bindings=operand_outputs,
        )
        assert record.input_seal is not None
        if (
            root.get("input_seal_version") != record.input_seal.seal_version
            or root.get("input_seal_content_hash") != record.input_seal.content_hash
        ):
            raise FundamentalValuePersistenceViolation("INPUT_SEAL_PERSISTED_DRIFT")
        validate_persistence_record_v1(record)
        _validate_operand_producers(record, self._producer_registry)
        return record

    def _insert_assembly(self, cursor: Any, record: FundamentalValuePersistenceRecordV1) -> None:
        assembly = record.assembly
        assert record.input_seal is not None
        security = assembly.security
        cursor.execute(
            """SELECT completed_session_id FROM analytics.evidence_selection_request_v1
               WHERE request_id=%(request_id)s""",
            {"request_id": UUID(assembly.classification_seal.request_id)},
        )
        session = cursor.fetchone()
        if session is None:
            raise FundamentalValuePersistenceViolation("CLASSIFICATION_REQUEST_NOT_PERSISTED")
        classification = assembly.classification_seal
        cursor.execute(
            _INSERT_ASSEMBLY,
            {
                "assembly_id": UUID(record.assembly_id),
                "contract_version": ASSEMBLY_PERSISTENCE_VERSION,
                "manifest_version": MANIFEST_VERSION,
                "assembly_version": assembly.versions.assembly_version,
                **{
                    name: UUID(getattr(security, name))
                    for name in (
                        "security_id",
                        "company_id",
                        "instrument_id",
                        "share_class_id",
                        "listing_id",
                        "ticker_assignment_id",
                    )
                },
                "classification_request_id": UUID(assembly.classification_seal.request_id),
                "classification_evidence_id": UUID(assembly.classification_evidence_id),
                "ticker": security.ticker,
                "mic": security.mic,
                "currency": security.currency,
                "completed_session_id": session["completed_session_id"],
                "classification_request_content_hash": classification.request_content_hash,
                "classification_result_content_hash": classification.result_content_hash,
                "classification_source_content_hash": classification.source_content_hash,
                "classification_normalized_record_hash": classification.normalized_record_hash,
                "classification_source_revision": classification.source_revision,
                "classification_effective_at": classification.effective_at,
                "classification_available_at": classification.available_at,
                "classification_ingested_at": classification.ingested_at,
                "classification_selector_policy_version": classification.selector_policy_version,
                "classification_selector_version": classification.selector_version,
                "classification_freshness_policy_version": classification.freshness_policy_version,
                "classification_normalization_version": classification.normalization_version,
                "classification_provider_schema_version": classification.provider_schema_version,
                "classification_adapter_version": classification.adapter_version,
                "applicability_routing_id": UUID(assembly.routing_id),
                "applicability_routing_content_hash": assembly.routing_content_hash,
                "applicability_routing_revision": assembly.routing_revision,
                "decision_cutoff": assembly.decision_cutoff,
                "sealed_ingestion_cutoff": assembly.sealed_ingestion_cutoff,
                "company_type": assembly.company_type.value,
                "applicability": assembly.applicability.value,
                "state": assembly.state.value,
                "projection_years": assembly.projection_years,
                **_version_parameters(assembly.versions),
                "core_invocation_authorized": assembly.core_invocation_authorized,
                "core_input_hash": (
                    _inputs_hash(assembly.inputs) if assembly.inputs is not None else None
                ),
                "input_seal_version": record.input_seal.seal_version,
                "input_seal_content_hash": record.input_seal.content_hash,
                "expected_operand_count": len(assembly.operands),
                "expected_reason_count": len(assembly.reason_codes),
                "manifest_content_hash": assembly.manifest_content_hash,
                "assembly_revision": record.assembly_revision,
                "supersedes_assembly_id": (
                    UUID(record.supersedes_assembly_id)
                    if record.supersedes_assembly_id is not None
                    else None
                ),
            },
        )
        for ordinal, reason in enumerate(assembly.reason_codes, 1):
            cursor.execute(
                """INSERT INTO analytics.fundamental_value_assembly_reason_v1
                   (assembly_id, reason_ordinal, reason_code)
                   VALUES (%(assembly_id)s,%(ordinal)s,%(reason)s)""",
                {"assembly_id": UUID(record.assembly_id), "ordinal": ordinal, "reason": reason},
            )
        total_operand_reasons = 0
        total_operand_evidence = 0
        requirements = {item.operand_code: item for item in OPERAND_REQUIREMENTS}
        parents_by_code: dict[str, list[OperandEvidenceParentV1]] = {}
        for parent in record.operand_evidence_parents:
            parents_by_code.setdefault(parent.operand_code, []).append(parent)
        for ordinal, operand in enumerate(assembly.operands, 1):
            requirement = requirements[operand.operand_code]
            seal = operand.evidence_seal
            _validate_direct_operand_against_v22(cursor, operand, requirement.source_kind)
            output = next(
                (
                    item
                    for item in record.operand_output_bindings
                    if item.operand_code == operand.operand_code
                ),
                None,
            )
            seal_parameters = _seal_parameters(seal)
            if output is not None:
                seal_parameters["derivation_version"] = output.output_version
            cursor.execute(
                _INSERT_OPERAND,
                {
                    "assembly_id": UUID(record.assembly_id),
                    "operand_ordinal": ordinal,
                    "operand_code": operand.operand_code,
                    "source_kind": requirement.source_kind.value,
                    "required_for_core": requirement.required_for_core,
                    "state": operand.state.value,
                    "numeric_value": decimal_text(operand.metric_evidence.value),
                    **seal_parameters,
                    "output_content_hash": (
                        output.output_content_hash if output is not None else None
                    ),
                    "producer_contract_content_hash": (
                        output.producer_contract_content_hash if output is not None else None
                    ),
                    "expected_reason_count": len(operand.reason_codes),
                    "expected_evidence_count": len(parents_by_code.get(operand.operand_code, ())),
                },
            )
            for parent in parents_by_code.get(operand.operand_code, ()):
                cursor.execute(
                    _INSERT_OPERAND_EVIDENCE,
                    {
                        "assembly_id": UUID(record.assembly_id),
                        "operand_ordinal": ordinal,
                        "parent_ordinal": parent.parent_ordinal,
                        "evidence_id": UUID(parent.evidence_id),
                        "source_content_hash": parent.source_content_hash,
                        "normalized_record_hash": parent.normalized_record_hash,
                        "source_revision": parent.source_revision,
                        "dependency_code": parent.dependency_code,
                        "effective_at": parent.effective_at,
                        "available_at": parent.available_at,
                        "ingested_at": parent.ingested_at,
                    },
                )
                total_operand_evidence += 1
            for reason_ordinal, reason in enumerate(operand.reason_codes, 1):
                cursor.execute(
                    """INSERT INTO analytics.fundamental_value_operand_reason_v1
                       (assembly_id,operand_ordinal,reason_ordinal,reason_code)
                       VALUES (%(assembly_id)s,%(operand_ordinal)s,%(reason_ordinal)s,%(reason)s)""",
                    {
                        "assembly_id": UUID(record.assembly_id),
                        "operand_ordinal": ordinal,
                        "reason_ordinal": reason_ordinal,
                        "reason": reason,
                    },
                )
                total_operand_reasons += 1
        cursor.execute(
            """INSERT INTO analytics.fundamental_value_assembly_seal_v1
               (assembly_id,operand_count,assembly_reason_count,operand_reason_count,
                operand_evidence_count)
               VALUES (%(assembly_id)s,%(operands)s,%(reasons)s,%(operand_reasons)s,
                       %(operand_evidence)s)""",
            {
                "assembly_id": UUID(record.assembly_id),
                "operands": len(assembly.operands),
                "reasons": len(assembly.reason_codes),
                "operand_reasons": total_operand_reasons,
                "operand_evidence": total_operand_evidence,
            },
        )

    def _insert_assessment(self, cursor: Any, record: FundamentalValuePersistenceRecordV1) -> None:
        assessment = record.assessment
        assert assessment is not None and record.assessment_id is not None
        assessment_id = UUID(record.assessment_id)
        dimensions = _assessment_dimensions(assessment)
        ranges = _assessment_ranges(assessment)
        conditions = _assessment_conditions(assessment)
        cursor.execute(
            _INSERT_ASSESSMENT,
            {
                "assessment_id": assessment_id,
                "assembly_id": UUID(record.assembly_id),
                "contract_version": ASSESSMENT_PERSISTENCE_VERSION,
                "sleeve": SLEEVE,
                "company_type": assessment.company_type.value,
                "applicability": assessment.applicability.value,
                "currency": assessment.currency,
                "projection_years": assessment.projection_years,
                "reference_price": decimal_text(assessment.reference_price.value),
                "claim_ceiling": assessment.claim_ceiling.value,
                "model_evidence_label": assessment.model_evidence_label.value,
                "risk_cap_ceiling": decimal_text(assessment.risk_cap.ceiling),
                "model_version": assessment.model_version,
                "strategy_version": assessment.strategy_version,
                "formula_version": assessment.formula_version,
                "assumption_policy_version": assessment.assumption_policy_version,
                "aggregation_version": assessment.aggregation_version,
                "risk_policy_version": assessment.risk_policy_version,
                "input_hash": assessment.input_hash,
                "result_content_hash": assessment.content_hash,
                "deterministic_ranking_authorized": assessment.deterministic_ranking_authorized,
                "final_portfolio_weight_authorized": assessment.final_portfolio_weight_authorized,
                "automatic_brokerage_execution_authorized": assessment.automatic_brokerage_execution_authorized,
                "expected_dimension_count": len(dimensions),
                "expected_method_count": len(assessment.valuations),
                "expected_range_count": len(ranges),
                "expected_condition_count": len(conditions),
                "expected_risk_reason_count": len(assessment.risk_cap.binding_reasons),
            },
        )
        component_reason_count = 0
        for ordinal, (code, item) in enumerate(dimensions, 1):
            cursor.execute(
                _INSERT_DIMENSION,
                {
                    "assessment_id": assessment_id,
                    "ordinal": ordinal,
                    "code": code,
                    "state": item.state.value,
                    "score": decimal_text(item.score),
                    "reason_count": len(item.reason_codes),
                },
            )
            component_reason_count += _insert_component_reasons(
                cursor, assessment_id, "DIMENSION", code, item.reason_codes
            )
        scenario_count = 0
        for ordinal, item in enumerate(assessment.valuations, 1):
            cursor.execute(
                _INSERT_METHOD,
                {
                    "assessment_id": assessment_id,
                    "ordinal": ordinal,
                    "code": item.method.value,
                    "role": (
                        MethodRole.CROSS_CHECK_ONLY.value
                        if item.method == ValuationMethod.COMPARABLE_CROSS_CHECK
                        else MethodRole.PRIMARY.value
                    ),
                    "weight": decimal_text(METHOD_WEIGHTS[item.method]),
                    "state": item.state.value,
                    "terminal": decimal_text(item.terminal_value_share),
                    "reason_count": len(item.reason_codes),
                },
            )
            if item.state == DataState.VALID:
                for scenario_ordinal, (scenario_code, value) in enumerate(
                    zip(
                        ("LOW", "CENTRAL", "HIGH"), (item.low, item.central, item.high), strict=True
                    ),
                    1,
                ):
                    cursor.execute(
                        _INSERT_SCENARIO,
                        {
                            "assessment_id": assessment_id,
                            "method_ordinal": ordinal,
                            "ordinal": scenario_ordinal,
                            "code": scenario_code,
                            "value": decimal_text(value),
                        },
                    )
                    scenario_count += 1
            component_reason_count += _insert_component_reasons(
                cursor, assessment_id, "VALUATION_METHOD", item.method.value, item.reason_codes
            )
        for ordinal, (code, item) in enumerate(ranges, 1):
            cursor.execute(
                _INSERT_RANGE,
                {
                    "assessment_id": assessment_id,
                    "ordinal": ordinal,
                    "code": code,
                    "state": item.state.value,
                    "low": decimal_text(item.low),
                    "central": decimal_text(item.central),
                    "high": decimal_text(item.high),
                    "reason_count": len(item.reason_codes),
                },
            )
            component_reason_count += _insert_component_reasons(
                cursor, assessment_id, "ORDERED_RANGE", code, item.reason_codes
            )
        for kind, ordinal, item in conditions:
            cursor.execute(
                _INSERT_CONDITION,
                {
                    "assessment_id": assessment_id,
                    "kind": kind,
                    "ordinal": ordinal,
                    "code": item.code,
                    "state": item.state.value,
                    "observed": decimal_text(item.observed_value),
                    "threshold": decimal_text(item.threshold),
                    "satisfied": item.satisfied,
                    "reason_count": len(item.reason_codes),
                },
            )
            component_reason_count += _insert_component_reasons(
                cursor, assessment_id, "CONDITION", item.code, item.reason_codes
            )
        for ordinal, reason in enumerate(assessment.risk_cap.binding_reasons, 1):
            cursor.execute(
                """INSERT INTO analytics.fundamental_value_risk_cap_reason_v1
                (assessment_id,reason_ordinal,reason_code) VALUES (%(id)s,%(ordinal)s,%(reason)s)""",
                {"id": assessment_id, "ordinal": ordinal, "reason": reason},
            )
        cursor.execute(
            _INSERT_ASSESSMENT_SEAL,
            {
                "assessment_id": assessment_id,
                "dimensions": len(dimensions),
                "methods": len(assessment.valuations),
                "scenarios": scenario_count,
                "ranges": len(ranges),
                "conditions": len(conditions),
                "component_reasons": component_reason_count,
                "risk_reasons": len(assessment.risk_cap.binding_reasons),
            },
        )

    def _load_assessment_rows(
        self, cursor: Any, assessment_id: UUID
    ) -> dict[str, tuple[dict[str, Any], ...]]:
        result: dict[str, tuple[dict[str, Any], ...]] = {}
        queries = {
            "dimensions": "SELECT * FROM analytics.fundamental_value_dimension_v1 WHERE assessment_id=%(id)s ORDER BY dimension_ordinal",
            "methods": "SELECT * FROM analytics.fundamental_value_valuation_method_v1 WHERE assessment_id=%(id)s ORDER BY method_ordinal",
            "scenarios": "SELECT * FROM analytics.fundamental_value_valuation_scenario_v1 WHERE assessment_id=%(id)s ORDER BY method_ordinal,scenario_ordinal",
            "ranges": "SELECT * FROM analytics.fundamental_value_ordered_range_v1 WHERE assessment_id=%(id)s ORDER BY range_ordinal",
            "conditions": "SELECT * FROM analytics.fundamental_value_condition_v1 WHERE assessment_id=%(id)s ORDER BY CASE condition_kind WHEN 'THESIS' THEN 1 WHEN 'COUNTER_THESIS' THEN 2 ELSE 3 END,condition_ordinal",
            "component_reasons": "SELECT * FROM analytics.fundamental_value_component_reason_v1 WHERE assessment_id=%(id)s ORDER BY component_kind,component_code,reason_ordinal",
            "risk_reasons": "SELECT * FROM analytics.fundamental_value_risk_cap_reason_v1 WHERE assessment_id=%(id)s ORDER BY reason_ordinal",
        }
        for key, query in queries.items():
            cursor.execute(query, {"id": assessment_id})
            result[key] = tuple(cursor.fetchall())
        return result


def deterministic_assembly_id_v1(
    assembly: FundamentalValueAssemblyResultV1,
    parents: tuple[OperandEvidenceParentV1, ...] = (),
    outputs: tuple[OperandOutputBindingV1, ...] = (),
) -> str:
    verify_manifest_content_hash(assembly)
    normalized_parents = _complete_parent_set(assembly, parents)
    normalized_outputs = _complete_output_bindings(assembly, normalized_parents, outputs)
    seal = deterministic_input_seal_v1(assembly, normalized_parents, normalized_outputs)
    return str(
        uuid5(
            NAMESPACE_URL,
            f"{ASSEMBLY_PERSISTENCE_VERSION}:{assembly.manifest_content_hash}:{seal.content_hash}",
        )
    )


def deterministic_assessment_id_v1(
    assessment: FundamentalValueAssessmentV1,
    assembly_id: str,
) -> str:
    _validate_assessment(assessment)
    _canonical_uuid(assembly_id, "ASSESSMENT_ASSEMBLY_ID_INVALID")
    return str(
        uuid5(
            NAMESPACE_URL,
            f"{ASSESSMENT_PERSISTENCE_VERSION}:{assembly_id}:{assessment.content_hash}",
        )
    )


def validate_persistence_record_v1(record: FundamentalValuePersistenceRecordV1) -> None:
    assembly = record.assembly
    verify_manifest_content_hash(assembly)
    assembly.versions.validate()
    if record.input_seal != deterministic_input_seal_v1(
        assembly,
        record.operand_evidence_parents,
        record.operand_output_bindings,
    ):
        raise FundamentalValuePersistenceViolation("INPUT_SEAL_CONTENT_DRIFT")
    if record.assembly_id != deterministic_assembly_id_v1(
        assembly,
        record.operand_evidence_parents,
        record.operand_output_bindings,
    ):
        raise FundamentalValuePersistenceViolation("ASSEMBLY_ID_CONTENT_DRIFT")
    if (
        assembly.company_type == CompanyType.MATURE_OPERATING_COMPANY
        and assembly.applicability == Applicability.APPLICABLE
    ):
        if len(assembly.operands) != len(OPERAND_REQUIREMENTS):
            raise FundamentalValuePersistenceViolation(
                "APPLICABLE_ASSEMBLY_OPERAND_CARDINALITY_INVALID"
            )
    elif assembly.operands:
        raise FundamentalValuePersistenceViolation(
            "NONAPPLICABLE_ASSEMBLY_CANNOT_HAVE_GENERIC_OPERANDS"
        )
    if tuple(item.operand_code for item in assembly.operands) != tuple(
        requirement.operand_code for requirement in OPERAND_REQUIREMENTS[: len(assembly.operands)]
    ):
        raise FundamentalValuePersistenceViolation("ASSEMBLY_OPERAND_CARDINALITY_OR_ORDER_INVALID")
    if len(set(item.operand_code for item in assembly.operands)) != len(assembly.operands):
        raise FundamentalValuePersistenceViolation("ASSEMBLY_OPERAND_DUPLICATE")
    for operand in assembly.operands:
        _validate_operand(operand)
    selected_evidence_ids = (assembly.classification_evidence_id,) + tuple(
        operand.evidence_seal.evidence_id
        for operand in assembly.operands
        if operand.evidence_seal is not None and operand.evidence_seal.evidence_id is not None
    )
    if len(set(selected_evidence_ids)) != len(selected_evidence_ids):
        raise FundamentalValuePersistenceViolation("DUPLICATE_SELECTED_EVIDENCE_ID")
    _validate_parent_set(assembly, record.operand_evidence_parents)
    _validate_output_bindings(
        assembly,
        record.operand_evidence_parents,
        record.operand_output_bindings,
    )
    core_eligible = (
        assembly.company_type == CompanyType.MATURE_OPERATING_COMPANY
        and assembly.state == DataState.VALID
        and assembly.applicability == Applicability.APPLICABLE
        and assembly.inputs is not None
        and len(assembly.operands) == len(OPERAND_REQUIREMENTS)
        and all(
            operand.state == DataState.VALID
            for operand, requirement in zip(
                assembly.operands, OPERAND_REQUIREMENTS, strict=True
            )
            if requirement.required_for_core
        )
    )
    if assembly.core_invocation_authorized != core_eligible:
        raise FundamentalValuePersistenceViolation(
            "CORE_INVOCATION_AUTHORITY_BICONDITIONAL"
        )
    if assembly.core_invocation_authorized:
        if _inputs_from_assembly(assembly) != assembly.inputs:
            raise FundamentalValuePersistenceViolation("ASSEMBLY_INPUT_REHYDRATION_DRIFT")
    elif assembly.inputs is not None:
        raise FundamentalValuePersistenceViolation("NONUSABLE_ASSEMBLY_CANNOT_CARRY_INPUTS")
    if record.assessment is None:
        return
    assessment = record.assessment
    assert record.assessment_id is not None
    if record.assessment_id != deterministic_assessment_id_v1(assessment, record.assembly_id):
        raise FundamentalValuePersistenceViolation("ASSESSMENT_ID_CONTENT_DRIFT")
    if not assembly.core_invocation_authorized or assembly.inputs is None:
        raise FundamentalValuePersistenceViolation("ASSESSMENT_REQUIRES_USABLE_ASSEMBLY")
    _validate_assessment(assessment)
    if assessment.input_hash != _inputs_hash(assembly.inputs):
        raise FundamentalValuePersistenceViolation("ASSESSMENT_INPUT_HASH_BINDING_DRIFT")
    if (
        assessment.company_type != assembly.company_type
        or assessment.applicability != assembly.applicability
        or assessment.projection_years != assembly.projection_years
        or assessment.currency != assembly.security.currency
        or assessment.reference_price != assembly.inputs.reference_price
    ):
        raise FundamentalValuePersistenceViolation("ASSESSMENT_ASSEMBLY_BINDING_DRIFT")
    version_pairs = (
        (assessment.model_version, assembly.versions.model_version),
        (assessment.strategy_version, assembly.versions.strategy_version),
        (assessment.formula_version, assembly.versions.formula_version),
        (assessment.assumption_policy_version, assembly.versions.assumption_policy_version),
        (assessment.aggregation_version, assembly.versions.aggregation_version),
        (assessment.risk_policy_version, assembly.versions.risk_policy_version),
    )
    if any(left != right for left, right in version_pairs):
        raise FundamentalValuePersistenceViolation("ASSESSMENT_VERSION_BINDING_DRIFT")
    try:
        expected_assessment = evaluate_fundamental_value_v1(
            assembly.inputs,
            model_evidence_label=assessment.model_evidence_label,
        )
    except (CoreViolation, ArithmeticError, ValueError) as error:
        raise FundamentalValuePersistenceViolation(
            "ASSESSMENT_CORE_RECOMPUTATION_DRIFT"
        ) from error
    if assessment.claim_ceiling != expected_assessment.claim_ceiling:
        raise FundamentalValuePersistenceViolation("ASSESSMENT_CLAIM_CEILING_DRIFT")
    if assessment.risk_cap != expected_assessment.risk_cap:
        raise FundamentalValuePersistenceViolation("ASSESSMENT_RISK_CAP_DRIFT")
    if expected_assessment != assessment:
        raise FundamentalValuePersistenceViolation("ASSESSMENT_CORE_RECOMPUTATION_DRIFT")


def _validate_operand(operand: AssembledOperandV1) -> None:
    if operand.metric_evidence.state != operand.state:
        raise FundamentalValuePersistenceViolation("OPERAND_METRIC_STATE_DRIFT")
    if operand.state == DataState.VALID:
        if operand.reason_codes or operand.metric_evidence.value is None:
            raise FundamentalValuePersistenceViolation("VALID_OPERAND_SHAPE_INVALID")
    elif operand.metric_evidence.value is not None or not operand.reason_codes:
        raise FundamentalValuePersistenceViolation("NONVALID_OPERAND_SHAPE_INVALID")
    if operand.evidence_seal is not None:
        seal = operand.evidence_seal
        if seal.operand_code != operand.operand_code or seal.state != operand.state:
            raise FundamentalValuePersistenceViolation("OPERAND_EVIDENCE_SEAL_DRIFT")
        if operand.state == DataState.VALID and (
            seal.evidence_id is None
            or seal.source_content_hash is None
            or seal.normalized_record_hash is None
            or seal.source_revision is None
        ):
            raise FundamentalValuePersistenceViolation("VALID_OPERAND_EVIDENCE_SEAL_INCOMPLETE")


def _complete_parent_set(
    assembly: FundamentalValueAssemblyResultV1,
    explicit: tuple[OperandEvidenceParentV1, ...],
) -> tuple[OperandEvidenceParentV1, ...]:
    by_code = {parent.operand_code for parent in explicit}
    parents = list(explicit)
    requirements = {item.operand_code: item for item in OPERAND_REQUIREMENTS}
    for operand in assembly.operands:
        if (
            operand.state == DataState.VALID
            and operand.evidence_seal is not None
            and operand.operand_code not in by_code
        ):
            seal = operand.evidence_seal
            if seal is None or seal.evidence_id is None:
                raise FundamentalValuePersistenceViolation("DIRECT_OPERAND_PARENT_SEAL_MISSING")
            parents.append(_parent_from_evidence_seal(operand.operand_code, 1, seal))
    return tuple(
        sorted(
            parents,
            key=lambda item: (tuple(requirements).index(item.operand_code), item.parent_ordinal),
        )
    )


def _validate_parent_set(
    assembly: FundamentalValueAssemblyResultV1,
    parents: tuple[OperandEvidenceParentV1, ...],
) -> None:
    requirements = {item.operand_code: item for item in OPERAND_REQUIREMENTS}
    operands = {item.operand_code: item for item in assembly.operands}
    grouped: dict[str, list[OperandEvidenceParentV1]] = {}
    for parent in parents:
        if parent.operand_code not in operands:
            raise FundamentalValuePersistenceViolation("OPERAND_PARENT_CODE_UNKNOWN")
        if parent.evidence_id == assembly.classification_evidence_id:
            raise FundamentalValuePersistenceViolation("CLASSIFICATION_EVIDENCE_REUSED_AS_OPERAND")
        grouped.setdefault(parent.operand_code, []).append(parent)
    direct_evidence_ids: set[str] = set()
    for code, operand in operands.items():
        requirement = requirements[code]
        items = grouped.get(code, [])
        if tuple(item.parent_ordinal for item in items) != tuple(range(1, len(items) + 1)):
            raise FundamentalValuePersistenceViolation("OPERAND_PARENT_ORDINALS_NOT_CONTIGUOUS")
        if operand.state != DataState.VALID:
            if items:
                raise FundamentalValuePersistenceViolation("NONVALID_OPERAND_CANNOT_HAVE_PARENTS")
            continue
        if not items:
            raise FundamentalValuePersistenceViolation("VALID_OPERAND_REQUIRES_PARENTS")
        if len({item.evidence_id for item in items}) != len(items):
            raise FundamentalValuePersistenceViolation("DUPLICATE_OPERAND_PARENT_EVIDENCE_ID")
        if requirement.source_kind in {
            OperandSourceKind.DAILY_PRICE,
            OperandSourceKind.DIRECT_FUNDAMENTAL,
        }:
            seal = operand.evidence_seal
            if (
                len(items) != 1
                or seal is None
                or items[0] != _parent_from_evidence_seal(code, 1, seal)
            ):
                raise FundamentalValuePersistenceViolation("DIRECT_OPERAND_PARENT_BINDING_DRIFT")
            if items[0].evidence_id in direct_evidence_ids:
                raise FundamentalValuePersistenceViolation("DUPLICATE_DIRECT_EVIDENCE_BINDING")
            direct_evidence_ids.add(items[0].evidence_id)


def _parent_from_evidence_seal(
    operand_code: str,
    ordinal: int,
    seal: EvidenceSealV1,
) -> OperandEvidenceParentV1:
    required = (
        seal.evidence_id,
        seal.source_content_hash,
        seal.normalized_record_hash,
        seal.source_revision,
        seal.effective_at,
        seal.available_at,
        seal.ingested_at,
    )
    if any(value is None for value in required):
        raise FundamentalValuePersistenceViolation("OPERAND_PARENT_SEAL_INCOMPLETE")
    return OperandEvidenceParentV1(
        operand_code=operand_code,
        parent_ordinal=ordinal,
        evidence_id=seal.evidence_id or "",
        source_content_hash=seal.source_content_hash or "",
        normalized_record_hash=seal.normalized_record_hash or "",
        source_revision=seal.source_revision or 0,
        effective_at=seal.effective_at,  # type: ignore[arg-type]
        available_at=seal.available_at,  # type: ignore[arg-type]
        ingested_at=seal.ingested_at,  # type: ignore[arg-type]
        dependency_code=f"SELECTED_CANONICAL_{operand_code.upper()}",
    )


def _operand_parent_hash(parent: OperandEvidenceParentV1) -> str:
    payload = {
        "operandCode": parent.operand_code,
        "parentOrdinal": parent.parent_ordinal,
        "evidenceId": parent.evidence_id,
        "sourceContentHash": parent.source_content_hash,
        "normalizedRecordHash": parent.normalized_record_hash,
        "sourceRevision": parent.source_revision,
        "dependencyCode": parent.dependency_code,
        "domain": parent.domain,
        "fieldCode": parent.field_code,
        "unit": parent.unit,
        "currency": parent.currency,
        "fiscalPeriod": parent.fiscal_period,
        "periodStart": parent.period_start,
        "periodEnd": parent.period_end,
        "canonicalValue": decimal_text(parent.canonical_value),
        "effectiveAt": _utc_instant(parent.effective_at),
        "availableAt": _utc_instant(parent.available_at),
        "ingestedAt": _utc_instant(parent.ingested_at),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _complete_output_bindings(
    assembly: FundamentalValueAssemblyResultV1,
    parents: tuple[OperandEvidenceParentV1, ...],
    explicit: tuple[OperandOutputBindingV1, ...],
) -> tuple[OperandOutputBindingV1, ...]:
    if type(explicit) is not tuple:
        raise FundamentalValuePersistenceViolation("OPERAND_OUTPUT_SET_MUST_BE_TUPLE")
    by_code = {item.operand_code: item for item in explicit}
    if len(by_code) != len(explicit):
        raise FundamentalValuePersistenceViolation("DUPLICATE_OPERAND_OUTPUT_BINDING")
    parent_map: dict[str, tuple[OperandEvidenceParentV1, ...]] = {}
    for operand_code in {item.operand_code for item in parents}:
        parent_map[operand_code] = tuple(
            item for item in parents if item.operand_code == operand_code
        )
    requirements = {item.operand_code: item for item in OPERAND_REQUIREMENTS}
    for operand in assembly.operands:
        requirement = requirements[operand.operand_code]
        if (
            operand.state == DataState.VALID
            and requirement.source_kind
            in {OperandSourceKind.DERIVATION_REQUIRED, OperandSourceKind.POLICY_EVIDENCE_REQUIRED}
            and operand.operand_code not in by_code
            and operand.evidence_seal is not None
            and operand.evidence_seal.derivation_version
        ):
            version = operand.evidence_seal.derivation_version
            by_code[operand.operand_code] = OperandOutputBindingV1(
                operand.operand_code,
                version,
                _operand_output_hash(operand, version, parent_map.get(operand.operand_code, ())),
            )
    order = {item.operand_code: index for index, item in enumerate(OPERAND_REQUIREMENTS)}
    return tuple(sorted(by_code.values(), key=lambda item: order.get(item.operand_code, 999)))


def _validate_output_bindings(
    assembly: FundamentalValueAssemblyResultV1,
    parents: tuple[OperandEvidenceParentV1, ...],
    outputs: tuple[OperandOutputBindingV1, ...],
) -> None:
    output_map = {item.operand_code: item for item in outputs}
    parent_map: dict[str, tuple[OperandEvidenceParentV1, ...]] = {}
    for operand_code in {item.operand_code for item in parents}:
        parent_map[operand_code] = tuple(
            item for item in parents if item.operand_code == operand_code
        )
    requirements = {item.operand_code: item for item in OPERAND_REQUIREMENTS}
    for operand in assembly.operands:
        requirement = requirements[operand.operand_code]
        requires_output = operand.state == DataState.VALID and requirement.source_kind in {
            OperandSourceKind.DERIVATION_REQUIRED,
            OperandSourceKind.POLICY_EVIDENCE_REQUIRED,
        }
        binding = output_map.get(operand.operand_code)
        if requires_output != (binding is not None):
            raise FundamentalValuePersistenceViolation("OPERAND_OUTPUT_BINDING_CARDINALITY_INVALID")
        if binding is not None and binding.output_content_hash != _operand_output_hash(
            operand,
            binding.output_version,
            parent_map.get(operand.operand_code, ()),
        ):
            raise FundamentalValuePersistenceViolation("OPERAND_OUTPUT_CONTENT_HASH_DRIFT")


def _operand_output_hash(
    operand: AssembledOperandV1,
    output_version: str,
    parents: tuple[OperandEvidenceParentV1, ...],
) -> str:
    payload = {
        "operandCode": operand.operand_code,
        "state": operand.state.value,
        "value": decimal_text(operand.metric_evidence.value),
        "reasonCodes": list(operand.reason_codes),
        "outputVersion": output_version,
        "parentContentHashes": [item.content_hash for item in parents],
    }
    return _canonical_hash(payload)


def _validate_operand_producers(
    record: FundamentalValuePersistenceRecordV1,
    registry: OperandProducerRegistryV1,
) -> None:
    requirements = {item.operand_code: item for item in OPERAND_REQUIREMENTS}
    outputs = {item.operand_code: item for item in record.operand_output_bindings}
    for operand in record.assembly.operands:
        requirement = requirements[operand.operand_code]
        if operand.state != DataState.VALID or requirement.source_kind not in {
            OperandSourceKind.DERIVATION_REQUIRED,
            OperandSourceKind.POLICY_EVIDENCE_REQUIRED,
        }:
            continue
        contract = registry.get(operand.operand_code)
        if contract is None:
            raise FundamentalValuePersistenceViolation("OPERAND_PRODUCER_UNAVAILABLE")
        binding = outputs.get(operand.operand_code)
        if (
            binding is None
            or binding.output_version != contract.contract_version
            or binding.producer_contract_content_hash != contract.content_hash
        ):
            raise FundamentalValuePersistenceViolation("OPERAND_PRODUCER_CONTRACT_DRIFT")
        parents = tuple(
            parent
            for parent in record.operand_evidence_parents
            if parent.operand_code == operand.operand_code
        )
        observations = tuple(
            ProducerParentObservationV1(
                parent.dependency_code,
                parent.evidence_id,
                parent.domain or "",
                parent.field_code or "",
                parent.unit or "",
                parent.currency,
                parent.fiscal_period or "",
                parent.period_start,
                parent.period_end or "",
                parent.canonical_value if parent.canonical_value is not None else Decimal("NaN"),
            )
            for parent in parents
        )
        if any(
            slot.currency_rule == "MATCH_OUTPUT"
            and observation.currency != record.assembly.security.currency
            for slot, observation in zip(contract.parent_slots, observations, strict=True)
        ):
            raise FundamentalValuePersistenceViolation(
                "OPERAND_PRODUCER_PARENT_CURRENCY_DRIFT"
            )
        try:
            produced = contract.evaluate(observations)
        except ProducerViolation as error:
            raise FundamentalValuePersistenceViolation(str(error)) from error
        if produced != operand.metric_evidence.value:
            raise FundamentalValuePersistenceViolation("OPERAND_PRODUCER_OUTPUT_DRIFT")


def deterministic_input_seal_v1(
    assembly: FundamentalValueAssemblyResultV1,
    parents: tuple[OperandEvidenceParentV1, ...],
    outputs: tuple[OperandOutputBindingV1, ...],
) -> DeterministicInputSealV1:
    payload = {
        "sealVersion": "fundamental-value-private-input-seal-v1.0.0",
        "manifestContentHash": assembly.manifest_content_hash,
        "state": assembly.state.value,
        "reasonCodes": list(assembly.reason_codes),
        "companyType": assembly.company_type.value,
        "applicability": assembly.applicability.value,
        "security": {
            "securityId": assembly.security.security_id,
            "companyId": assembly.security.company_id,
            "instrumentId": assembly.security.instrument_id,
            "shareClassId": assembly.security.share_class_id,
            "listingId": assembly.security.listing_id,
            "tickerAssignmentId": assembly.security.ticker_assignment_id,
            "ticker": assembly.security.ticker,
            "mic": assembly.security.mic,
            "currency": assembly.security.currency,
        },
        "completedSessionDate": assembly.completed_session_date,
        "decisionCutoff": _utc_instant(assembly.decision_cutoff),
        "sealedIngestionCutoff": _utc_instant(assembly.sealed_ingestion_cutoff),
        "routingId": assembly.routing_id,
        "routingContentHash": assembly.routing_content_hash,
        "routingRevision": assembly.routing_revision,
        "classificationEvidenceId": assembly.classification_evidence_id,
        "versions": assembly.versions.to_manifest(),
        "projectionYears": assembly.projection_years,
        "coreInvocationAuthorized": assembly.core_invocation_authorized,
        "inputHash": _inputs_hash(assembly.inputs) if assembly.inputs is not None else None,
        "operands": [
            {
                "operandCode": item.operand_code,
                "state": item.state.value,
                "value": decimal_text(item.metric_evidence.value),
                "reasonCodes": list(item.reason_codes),
                "evidence": item.evidence_seal.to_manifest() if item.evidence_seal else None,
            }
            for item in assembly.operands
        ],
        "parents": [
            {
                "operandCode": item.operand_code,
                "parentOrdinal": item.parent_ordinal,
                "contentHash": item.content_hash,
            }
            for item in parents
        ],
        "outputs": [
            {
                "operandCode": item.operand_code,
                "outputVersion": item.output_version,
                "outputContentHash": item.output_content_hash,
                "producerContractContentHash": item.producer_contract_content_hash,
            }
            for item in outputs
        ],
    }
    return DeterministicInputSealV1(
        "fundamental-value-private-input-seal-v1.0.0",
        _canonical_hash(payload),
    )


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _utc_instant(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FundamentalValuePersistenceViolation("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _validate_assessment(assessment: FundamentalValueAssessmentV1) -> None:
    if assessment.content_hash != _assessment_hash(assessment):
        raise FundamentalValuePersistenceViolation("ASSESSMENT_CONTENT_HASH_DRIFT")
    if HASH_PATTERN.fullmatch(assessment.input_hash) is None:
        raise FundamentalValuePersistenceViolation("ASSESSMENT_INPUT_HASH_INVALID")
    if assessment.model_evidence_label != ModelEvidenceLabel.NOT_VALIDATED:
        raise FundamentalValuePersistenceViolation(
            "ASSESSMENT_MODEL_EVIDENCE_LABEL_NOT_FROZEN"
        )
    if (
        assessment.company_type != CompanyType.MATURE_OPERATING_COMPANY
        or assessment.applicability != Applicability.APPLICABLE
        or assessment.reference_price.state != DataState.VALID
    ):
        raise FundamentalValuePersistenceViolation("ASSESSMENT_APPLICABILITY_INVALID")
    if (
        assessment.model_version != MODEL_VERSION
        or assessment.strategy_version != STRATEGY_VERSION
        or assessment.formula_version != FORMULA_VERSION
        or assessment.assumption_policy_version != ASSUMPTION_POLICY_VERSION
        or assessment.aggregation_version != AGGREGATION_VERSION
        or assessment.risk_policy_version != RISK_CAP_VERSION
    ):
        raise FundamentalValuePersistenceViolation("ASSESSMENT_VERSION_SET_DRIFT")
    if any(
        (
            assessment.deterministic_ranking_authorized,
            assessment.final_portfolio_weight_authorized,
            assessment.automatic_brokerage_execution_authorized,
        )
    ):
        raise FundamentalValuePersistenceViolation("ASSESSMENT_AUTHORITY_ESCALATION")
    dimensions = _assessment_dimensions(assessment)
    if len(dimensions) != 5:
        raise FundamentalValuePersistenceViolation("ASSESSMENT_DIMENSION_CARDINALITY_INVALID")
    if tuple(item.method for item in assessment.valuations) != tuple(ValuationMethod):
        raise FundamentalValuePersistenceViolation("ASSESSMENT_METHOD_CARDINALITY_OR_ORDER_INVALID")
    for item in assessment.valuations:
        if item.method != ValuationMethod.FCFF_DCF and item.terminal_value_share is not None:
            raise FundamentalValuePersistenceViolation("TERMINAL_VALUE_SHARE_METHOD_INVALID")
    _validate_condition_set("THESIS", assessment.thesis_evidence)
    _validate_condition_set("COUNTER_THESIS", assessment.counter_thesis_evidence)
    _validate_condition_set("INVALIDATION", assessment.invalidation_conditions)


def _validate_condition_set(kind: str, conditions: tuple[ThesisCondition, ...]) -> None:
    if tuple(item.code for item in conditions) != CONDITION_CODES[kind]:
        raise FundamentalValuePersistenceViolation(f"{kind}_CONDITION_CARDINALITY_OR_ORDER_INVALID")


def _assessment_dimensions(
    assessment: FundamentalValueAssessmentV1,
) -> tuple[tuple[str, DimensionResult], ...]:
    return (
        (DIMENSION_CODES[0], assessment.company_quality),
        (DIMENSION_CODES[1], assessment.financial_resilience),
        (DIMENSION_CODES[2], assessment.earnings_and_cash_flow_quality),
        (DIMENSION_CODES[3], assessment.capital_allocation_quality),
        (DIMENSION_CODES[4], assessment.downside_risk),
    )


def _inputs_from_assembly(assembly: FundamentalValueAssemblyResultV1) -> FundamentalValueInputsV1:
    values = {operand.operand_code: operand.metric_evidence for operand in assembly.operands}
    if set(values) != {requirement.operand_code for requirement in OPERAND_REQUIREMENTS}:
        raise FundamentalValuePersistenceViolation("ASSEMBLY_INPUT_OPERAND_SET_INCOMPLETE")
    return FundamentalValueInputsV1(
        company_type=assembly.company_type,
        applicability=assembly.applicability,
        projection_years=assembly.projection_years,
        currency=assembly.security.currency,
        **values,
    )


def _canonical_uuid(value: str, reason: str) -> None:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as error:
        raise FundamentalValuePersistenceViolation(reason) from error
    if str(parsed) != value:
        raise FundamentalValuePersistenceViolation(reason)


def decimal_text(value: Decimal | None) -> str | None:
    """Return the non-exponent Decimal representation used by the V23 adapter."""

    if value is None:
        return None
    try:
        return canonical_decimal_text(value)
    except CoreViolation as error:
        raise FundamentalValuePersistenceViolation(
            "NONFINITE_DECIMAL_CANNOT_BE_PERSISTED"
        ) from error


def decimal_from_database(value: Any, *, nullable: bool = False) -> Decimal | None:
    if value is None:
        if nullable:
            return None
        raise FundamentalValuePersistenceViolation("REQUIRED_DECIMAL_MISSING")
    result = Decimal(str(value))
    if not result.is_finite():
        raise FundamentalValuePersistenceViolation("NONFINITE_DATABASE_DECIMAL")
    return result


def _version_parameters(versions: AssemblyVersionSetV1) -> dict[str, str]:
    return {
        "evidence_contract_version": versions.evidence_contract_version,
        "selector_version": versions.selector_version,
        "applicability_routing_version": versions.applicability_routing_version,
        "model_version": versions.model_version,
        "strategy_version": versions.strategy_version,
        "formula_version": versions.formula_version,
        "assumption_policy_version": versions.assumption_policy_version,
        "aggregation_version": versions.aggregation_version,
        "risk_policy_version": versions.risk_policy_version,
    }


def _seal_parameters(seal: EvidenceSealV1 | None) -> dict[str, Any]:
    if seal is None:
        return {name: None for name in _SEAL_PARAMETER_NAMES}
    return {
        "selector_request_id": UUID(seal.request_id),
        "selected_evidence_id": UUID(seal.evidence_id) if seal.evidence_id else None,
        "request_content_hash": seal.request_content_hash,
        "result_content_hash": seal.result_content_hash,
        "source_content_hash": seal.source_content_hash,
        "normalized_record_hash": seal.normalized_record_hash,
        "source_revision": seal.source_revision,
        "effective_at": seal.effective_at,
        "available_at": seal.available_at,
        "ingested_at": seal.ingested_at,
        "selector_policy_version": seal.selector_policy_version,
        "freshness_policy_version": seal.freshness_policy_version,
        "normalization_version": seal.normalization_version,
        "provider_schema_version": seal.provider_schema_version,
        "adapter_version": seal.adapter_version,
        "tolerance_policy_version": seal.tolerance_policy_version,
        "derivation_version": seal.derivation_version,
    }


def _insert_component_reasons(
    cursor: Any,
    assessment_id: UUID,
    kind: str,
    code: str,
    reasons: tuple[str, ...],
) -> int:
    for ordinal, reason in enumerate(reasons, 1):
        cursor.execute(
            """INSERT INTO analytics.fundamental_value_component_reason_v1
               (assessment_id,component_kind,component_code,reason_ordinal,reason_code)
               VALUES (%(id)s,%(kind)s,%(code)s,%(ordinal)s,%(reason)s)""",
            {"id": assessment_id, "kind": kind, "code": code, "ordinal": ordinal, "reason": reason},
        )
    return len(reasons)


def _assessment_ranges(
    assessment: FundamentalValueAssessmentV1,
) -> tuple[tuple[str, OrderedRange], ...]:
    return (
        (RANGE_CODES[0], assessment.fair_value),
        (RANGE_CODES[1], assessment.margin_of_safety),
        (RANGE_CODES[2], assessment.expected_return),
    )


def _assessment_conditions(
    assessment: FundamentalValueAssessmentV1,
) -> tuple[tuple[str, int, ThesisCondition], ...]:
    return tuple(
        (kind, ordinal, item)
        for kind, items in (
            ("THESIS", assessment.thesis_evidence),
            ("COUNTER_THESIS", assessment.counter_thesis_evidence),
            ("INVALIDATION", assessment.invalidation_conditions),
        )
        for ordinal, item in enumerate(items, 1)
    )


def _assembly_from_rows(
    root: dict[str, Any],
    assembly_reasons: tuple[str, ...],
    operand_rows: tuple[dict[str, Any], ...],
    operand_reason_rows: tuple[dict[str, Any], ...],
) -> FundamentalValueAssemblyResultV1:
    reasons_by_ordinal: dict[int, list[str]] = {}
    for row in operand_reason_rows:
        reasons_by_ordinal.setdefault(row["operand_ordinal"], []).append(row["reason_code"])
    operands = tuple(
        _operand_from_row(row, tuple(reasons_by_ordinal.get(row["operand_ordinal"], ())))
        for row in operand_rows
    )
    security = SecurityIdentity(
        security_id=str(root["security_id"]),
        company_id=str(root["company_id"]),
        instrument_id=str(root["instrument_id"]),
        share_class_id=str(root["share_class_id"]),
        listing_id=str(root["listing_id"]),
        ticker_assignment_id=str(root["ticker_assignment_id"]),
        ticker=root["ticker"],
        mic=root["mic"],
        currency=root["currency"],
    )
    versions = AssemblyVersionSetV1(
        evidence_contract_version=root["evidence_contract_version"],
        selector_version=root["selector_version"],
        applicability_routing_version=root["applicability_routing_version"],
        model_version=root["model_version"],
        strategy_version=root["strategy_version"],
        formula_version=root["formula_version"],
        assumption_policy_version=root["assumption_policy_version"],
        aggregation_version=root["aggregation_version"],
        risk_policy_version=root["risk_policy_version"],
        assembly_version=root["assembly_version"],
    )
    classification_seal = EvidenceSealV1(
        operand_code="company_type",
        request_id=str(root["classification_request_id"]),
        request_content_hash=root["classification_request_content_hash"],
        result_content_hash=root["classification_result_content_hash"],
        selector_policy_version=root["classification_policy_version"],
        selector_version=root["selector_version"],
        state=DataState.VALID,
        reason_code=root["classification_reason_code"],
        evidence_id=str(root["classification_evidence_id"]),
        source_content_hash=root["classification_source_content_hash"],
        normalized_record_hash=root["classification_normalized_record_hash"],
        source_revision=root["classification_source_revision"],
        effective_at=root["classification_effective_at"],
        available_at=root["classification_available_at"],
        ingested_at=root["classification_ingested_at"],
        freshness_policy_version=root["classification_freshness_policy_version"],
        normalization_version=root["classification_normalization_version"],
        provider_schema_version=root["classification_provider_schema_version"],
        adapter_version=root["classification_adapter_version"],
        tolerance_policy_version=root["classification_tolerance_policy_version"],
        derivation_version=root["classification_derivation_version"],
    )
    draft = FundamentalValueAssemblyResultV1(
        state=DataState(root["state"]),
        reason_codes=assembly_reasons,
        company_type=CompanyType(root["company_type"]),
        applicability=Applicability(root["applicability"]),
        security=security,
        routing_id=str(root["applicability_routing_id"]),
        routing_content_hash=root["routing_content_hash"],
        routing_revision=root["routing_revision"],
        classification_evidence_id=str(root["classification_evidence_id"]),
        classification_seal=classification_seal,
        completed_session_date=root["session_date"].isoformat(),
        decision_cutoff=root["decision_cutoff"],
        sealed_ingestion_cutoff=root["sealed_ingestion_cutoff"],
        versions=versions,
        projection_years=root["projection_years"],
        operands=operands,
        inputs=None,
        manifest_content_hash=root["manifest_content_hash"],
        core_invocation_authorized=root["core_invocation_authorized"],
    )
    inputs = _inputs_from_assembly(draft) if draft.core_invocation_authorized else None
    expected_input_hash = _inputs_hash(inputs) if inputs is not None else None
    if root.get("core_input_hash") != expected_input_hash:
        raise FundamentalValuePersistenceViolation("ASSEMBLY_CORE_INPUT_HASH_DRIFT")
    return FundamentalValueAssemblyResultV1(**{**draft.__dict__, "inputs": inputs})


def _operand_from_row(row: dict[str, Any], reasons: tuple[str, ...]) -> AssembledOperandV1:
    state = DataState(row["state"])
    value = decimal_from_database(row["numeric_value"], nullable=True)
    if row["selected_evidence_id"] is not None:
        canonical_value = _canonical_v22_numeric_value(
            row.get("selected_domain"), row.get("selected_canonical_data")
        )
        if value != canonical_value:
            raise FundamentalValuePersistenceViolation(
                "DIRECT_EVIDENCE_CANONICAL_VALUE_DRIFT"
            )
    metric = (
        MetricEvidence(state, value=value)
        if state == DataState.VALID
        else MetricEvidence(
            state, reason_code=reasons[0] if reasons else "PERSISTED_REASON_MISSING"
        )
    )
    seal = None
    if row["selector_request_id"] is not None:
        seal = EvidenceSealV1(
            operand_code=row["operand_code"],
            request_id=str(row["selector_request_id"]),
            request_content_hash=row["request_content_hash"],
            result_content_hash=row["result_content_hash"],
            selector_policy_version=row["selector_policy_version"],
            selector_version=row["selector_version"],
            state=state,
            reason_code=row["selector_reason_code"],
            evidence_id=str(row["selected_evidence_id"]) if row["selected_evidence_id"] else None,
            source_content_hash=row["source_content_hash"],
            normalized_record_hash=row["normalized_record_hash"],
            source_revision=row["source_revision"],
            effective_at=row["effective_at"],
            available_at=row["available_at"],
            ingested_at=row["ingested_at"],
            freshness_policy_version=row["freshness_policy_version"],
            normalization_version=row["normalization_version"],
            provider_schema_version=row["provider_schema_version"],
            adapter_version=row["adapter_version"],
            tolerance_policy_version=row["tolerance_policy_version"],
            derivation_version=row["derivation_version"],
        )
    return AssembledOperandV1(row["operand_code"], state, reasons, seal, metric)


def _validate_direct_operand_against_v22(
    cursor: Any,
    operand: AssembledOperandV1,
    source_kind: OperandSourceKind,
) -> None:
    if source_kind not in {
        OperandSourceKind.DAILY_PRICE,
        OperandSourceKind.DIRECT_FUNDAMENTAL,
    }:
        return
    seal = operand.evidence_seal
    if seal is None or seal.evidence_id is None:
        if operand.state == DataState.VALID:
            raise FundamentalValuePersistenceViolation(
                "DIRECT_EVIDENCE_CANONICAL_VALUE_MISSING"
            )
        return
    cursor.execute(
        """SELECT domain,canonical_data FROM analytics.canonical_evidence_v1
           WHERE evidence_id=%(evidence_id)s""",
        {"evidence_id": UUID(seal.evidence_id)},
    )
    row = cursor.fetchone()
    if row is None:
        raise FundamentalValuePersistenceViolation("DIRECT_EVIDENCE_NOT_PERSISTED")
    canonical_value = _canonical_v22_numeric_value(row["domain"], row["canonical_data"])
    if operand.metric_evidence.value != canonical_value:
        raise FundamentalValuePersistenceViolation("DIRECT_EVIDENCE_CANONICAL_VALUE_DRIFT")


def _canonical_v22_numeric_value(domain: Any, canonical_data: Any) -> Decimal:
    if not isinstance(canonical_data, dict):
        raise FundamentalValuePersistenceViolation(
            "DIRECT_EVIDENCE_CANONICAL_VALUE_MISSING"
        )
    key = "close" if str(domain) == "DAILY_PRICE" else "numericValue"
    if key not in canonical_data:
        raise FundamentalValuePersistenceViolation(
            "DIRECT_EVIDENCE_CANONICAL_VALUE_MISSING"
        )
    try:
        return decimal_from_database(canonical_data[key])  # type: ignore[return-value]
    except (TypeError, ValueError) as error:
        raise FundamentalValuePersistenceViolation(
            "DIRECT_EVIDENCE_CANONICAL_VALUE_INVALID"
        ) from error


def _output_bindings_from_rows(
    assembly: FundamentalValueAssemblyResultV1,
    operand_rows: tuple[dict[str, Any], ...],
    parents: tuple[OperandEvidenceParentV1, ...],
) -> tuple[OperandOutputBindingV1, ...]:
    requirements = {item.operand_code: item for item in OPERAND_REQUIREMENTS}
    operands = {item.operand_code: item for item in assembly.operands}
    parents_by_code: dict[str, tuple[OperandEvidenceParentV1, ...]] = {}
    for code in {item.operand_code for item in parents}:
        parents_by_code[code] = tuple(item for item in parents if item.operand_code == code)
    outputs = []
    for row in operand_rows:
        code = row["operand_code"]
        requirement = requirements[code]
        if DataState(row["state"]) != DataState.VALID or requirement.source_kind not in {
            OperandSourceKind.DERIVATION_REQUIRED,
            OperandSourceKind.POLICY_EVIDENCE_REQUIRED,
        }:
            continue
        version = row["derivation_version"]
        if not isinstance(version, str) or not version.strip():
            raise FundamentalValuePersistenceViolation("OPERAND_OUTPUT_VERSION_MISSING")
        outputs.append(
            OperandOutputBindingV1(
                code,
                version,
                _operand_output_hash(operands[code], version, parents_by_code.get(code, ())),
                row["producer_contract_content_hash"],
            )
        )
        if outputs[-1].output_content_hash != row["output_content_hash"]:
            raise FundamentalValuePersistenceViolation(
                "OPERAND_OUTPUT_PERSISTED_HASH_DRIFT"
            )
    return tuple(outputs)


def _operand_parent_from_row(row: dict[str, Any]) -> OperandEvidenceParentV1:
    canonical = row.get("canonical_data") or {}
    governed = row.get("source_kind") in {
        OperandSourceKind.DERIVATION_REQUIRED.value,
        OperandSourceKind.POLICY_EVIDENCE_REQUIRED.value,
    }
    return OperandEvidenceParentV1(
        operand_code=row["operand_code"],
        parent_ordinal=row["parent_ordinal"],
        evidence_id=str(row["evidence_id"]),
        source_content_hash=row["source_content_hash"],
        normalized_record_hash=row["normalized_record_hash"],
        source_revision=row["source_revision"],
        effective_at=row["effective_at"],
        available_at=row["available_at"],
        ingested_at=row["ingested_at"],
        dependency_code=row["dependency_code"],
        domain=row.get("domain") if governed else None,
        field_code=canonical.get("metricCode") if governed else None,
        unit=canonical.get("unit") if governed else None,
        currency=canonical.get("currency") if governed else None,
        fiscal_period=canonical.get("fiscalPeriod") if governed else None,
        period_start=canonical.get("periodStart") if governed else None,
        period_end=canonical.get("periodEnd") if governed else None,
        canonical_value=(
            decimal_from_database(canonical.get("numericValue"), nullable=True)
            if governed and isinstance(canonical, dict)
            else None
        ),
    )


def _assessment_from_rows(
    root: dict[str, Any], rows: dict[str, tuple[dict[str, Any], ...]]
) -> FundamentalValueAssessmentV1:
    for row in rows["methods"]:
        method = ValuationMethod(row["method_code"])
        persisted_weight = decimal_from_database(row["method_weight"])
        if persisted_weight != METHOD_WEIGHTS[method]:
            raise FundamentalValuePersistenceViolation("VALUATION_METHOD_WEIGHT_DRIFT")
    component_reasons: dict[tuple[str, str], list[str]] = {}
    for row in rows["component_reasons"]:
        component_reasons.setdefault((row["component_kind"], row["component_code"]), []).append(
            row["reason_code"]
        )
    dimensions = tuple(
        DimensionResult(
            DataState(row["state"]),
            decimal_from_database(row["score"], nullable=True),
            tuple(component_reasons.get(("DIMENSION", row["dimension_code"]), ())),
        )
        for row in rows["dimensions"]
    )
    scenarios: dict[int, list[Decimal]] = {}
    for row in rows["scenarios"]:
        value = decimal_from_database(row["fair_value_per_share"])
        assert value is not None
        scenarios.setdefault(row["method_ordinal"], []).append(value)
    valuations = []
    for row in rows["methods"]:
        values = scenarios.get(row["method_ordinal"], [])
        values += [None] * (3 - len(values))
        valuations.append(
            ValuationResult(
                ValuationMethod(row["method_code"]),
                DataState(row["state"]),
                values[0],
                values[1],
                values[2],
                tuple(component_reasons.get(("VALUATION_METHOD", row["method_code"]), ())),
                decimal_from_database(row["terminal_value_share"], nullable=True),
            )
        )
    ranges = tuple(
        OrderedRange(
            DataState(row["state"]),
            decimal_from_database(row["low_value"], nullable=True),
            decimal_from_database(row["central_value"], nullable=True),
            decimal_from_database(row["high_value"], nullable=True),
            tuple(component_reasons.get(("ORDERED_RANGE", row["range_code"]), ())),
        )
        for row in rows["ranges"]
    )
    condition_groups: dict[str, list[ThesisCondition]] = {key: [] for key in CONDITION_CODES}
    for row in rows["conditions"]:
        condition_groups[row["condition_kind"]].append(
            ThesisCondition(
                row["condition_code"],
                DataState(row["state"]),
                decimal_from_database(row["observed_value"], nullable=True),
                decimal_from_database(row["threshold_value"], nullable=True),
                row["satisfied"],
                tuple(component_reasons.get(("CONDITION", row["condition_code"]), ())),
            )
        )
    reference_price = decimal_from_database(root["reference_price"])
    assert reference_price is not None
    return FundamentalValueAssessmentV1(
        company_type=CompanyType.MATURE_OPERATING_COMPANY,
        applicability=Applicability.APPLICABLE,
        reference_price=MetricEvidence.valid(reference_price),
        currency=root["currency"],
        projection_years=root["projection_years"],
        company_quality=dimensions[0],
        financial_resilience=dimensions[1],
        earnings_and_cash_flow_quality=dimensions[2],
        capital_allocation_quality=dimensions[3],
        valuations=tuple(valuations),
        fair_value=ranges[0],
        margin_of_safety=ranges[1],
        expected_return=ranges[2],
        downside_risk=dimensions[4],
        claim_ceiling=ClaimCeiling(root["claim_ceiling"]),
        thesis_evidence=tuple(condition_groups["THESIS"]),
        counter_thesis_evidence=tuple(condition_groups["COUNTER_THESIS"]),
        invalidation_conditions=tuple(condition_groups["INVALIDATION"]),
        risk_cap=RiskCapResult(
            decimal_from_database(root["risk_cap_ceiling"]),
            tuple(row["reason_code"] for row in rows["risk_reasons"]),
        ),
        model_evidence_label=ModelEvidenceLabel(root["model_evidence_label"]),
        model_version=root["model_version"],
        strategy_version=root["strategy_version"],
        formula_version=root["formula_version"],
        aggregation_version=root["aggregation_version"],
        risk_policy_version=root["risk_policy_version"],
        assumption_policy_version=root["assumption_policy_version"],
        input_hash=root["input_hash"],
        content_hash=root["result_content_hash"],
        deterministic_ranking_authorized=root["deterministic_ranking_authorized"],
        final_portfolio_weight_authorized=root["final_portfolio_weight_authorized"],
        automatic_brokerage_execution_authorized=root["automatic_brokerage_execution_authorized"],
    )


_SEAL_PARAMETER_NAMES = (
    "selector_request_id",
    "selected_evidence_id",
    "request_content_hash",
    "result_content_hash",
    "source_content_hash",
    "normalized_record_hash",
    "source_revision",
    "effective_at",
    "available_at",
    "ingested_at",
    "selector_policy_version",
    "freshness_policy_version",
    "normalization_version",
    "provider_schema_version",
    "adapter_version",
    "tolerance_policy_version",
    "derivation_version",
)

_INSERT_ASSEMBLY = """INSERT INTO analytics.fundamental_value_assembly_v1 (
assembly_id,contract_version,manifest_version,assembly_version,security_id,company_id,
instrument_id,share_class_id,listing_id,ticker_assignment_id,ticker,mic,currency,
completed_session_id,classification_request_id,classification_evidence_id,
classification_request_content_hash,classification_result_content_hash,
classification_source_content_hash,classification_normalized_record_hash,
classification_source_revision,classification_effective_at,classification_available_at,
classification_ingested_at,classification_selector_policy_version,classification_selector_version,
classification_freshness_policy_version,classification_normalization_version,
classification_provider_schema_version,classification_adapter_version,
applicability_routing_id,applicability_routing_content_hash,applicability_routing_revision,
decision_cutoff,sealed_ingestion_cutoff,
company_type,applicability,state,projection_years,evidence_contract_version,selector_version,
applicability_routing_version,model_version,strategy_version,formula_version,
assumption_policy_version,aggregation_version,risk_policy_version,core_invocation_authorized,
core_input_hash,input_seal_version,input_seal_content_hash,
expected_operand_count,expected_reason_count,manifest_content_hash,assembly_revision,
supersedes_assembly_id) VALUES (
%(assembly_id)s,%(contract_version)s,%(manifest_version)s,%(assembly_version)s,%(security_id)s,
%(company_id)s,%(instrument_id)s,%(share_class_id)s,%(listing_id)s,%(ticker_assignment_id)s,
%(ticker)s,%(mic)s,%(currency)s,%(completed_session_id)s,%(classification_request_id)s,
%(classification_evidence_id)s,%(classification_request_content_hash)s,
%(classification_result_content_hash)s,%(classification_source_content_hash)s,
%(classification_normalized_record_hash)s,%(classification_source_revision)s,
%(classification_effective_at)s,%(classification_available_at)s,%(classification_ingested_at)s,
%(classification_selector_policy_version)s,%(classification_selector_version)s,
%(classification_freshness_policy_version)s,%(classification_normalization_version)s,
%(classification_provider_schema_version)s,%(classification_adapter_version)s,
%(applicability_routing_id)s,%(applicability_routing_content_hash)s,
%(applicability_routing_revision)s,
%(decision_cutoff)s,%(sealed_ingestion_cutoff)s,%(company_type)s,%(applicability)s,%(state)s,
%(projection_years)s,%(evidence_contract_version)s,%(selector_version)s,
%(applicability_routing_version)s,%(model_version)s,%(strategy_version)s,%(formula_version)s,
%(assumption_policy_version)s,%(aggregation_version)s,%(risk_policy_version)s,
%(core_invocation_authorized)s,%(core_input_hash)s,%(input_seal_version)s,
%(input_seal_content_hash)s,%(expected_operand_count)s,%(expected_reason_count)s,
%(manifest_content_hash)s,%(assembly_revision)s,%(supersedes_assembly_id)s)"""

_INSERT_OPERAND = """INSERT INTO analytics.fundamental_value_assembly_operand_v1 (
assembly_id,operand_ordinal,operand_code,source_kind,required_for_core,state,numeric_value,
selector_request_id,selected_evidence_id,request_content_hash,result_content_hash,
source_content_hash,normalized_record_hash,source_revision,effective_at,available_at,ingested_at,
selector_policy_version,freshness_policy_version,normalization_version,provider_schema_version,
adapter_version,tolerance_policy_version,derivation_version,output_content_hash,
producer_contract_content_hash,
expected_reason_count,
expected_evidence_count) VALUES (
%(assembly_id)s,%(operand_ordinal)s,%(operand_code)s,%(source_kind)s,%(required_for_core)s,%(state)s,
%(numeric_value)s,%(selector_request_id)s,%(selected_evidence_id)s,%(request_content_hash)s,
%(result_content_hash)s,%(source_content_hash)s,%(normalized_record_hash)s,%(source_revision)s,
%(effective_at)s,%(available_at)s,%(ingested_at)s,%(selector_policy_version)s,
%(freshness_policy_version)s,%(normalization_version)s,%(provider_schema_version)s,
%(adapter_version)s,%(tolerance_policy_version)s,%(derivation_version)s,
%(output_content_hash)s,%(producer_contract_content_hash)s,%(expected_reason_count)s,
%(expected_evidence_count)s)"""

_INSERT_OPERAND_EVIDENCE = """INSERT INTO analytics.fundamental_value_operand_evidence_v1
(assembly_id,operand_ordinal,parent_ordinal,evidence_id,source_content_hash,
normalized_record_hash,source_revision,dependency_code,effective_at,available_at,ingested_at)
VALUES (%(assembly_id)s,%(operand_ordinal)s,%(parent_ordinal)s,%(evidence_id)s,
%(source_content_hash)s,%(normalized_record_hash)s,%(source_revision)s,%(dependency_code)s,%(effective_at)s,
%(available_at)s,%(ingested_at)s)"""

_INSERT_ASSESSMENT = """INSERT INTO analytics.fundamental_value_assessment_v1 (
assessment_id,assembly_id,contract_version,sleeve,company_type,applicability,currency,
projection_years,reference_price,claim_ceiling,model_evidence_label,risk_cap_ceiling,
model_version,strategy_version,formula_version,
assumption_policy_version,aggregation_version,risk_policy_version,input_hash,result_content_hash,
deterministic_ranking_authorized,final_portfolio_weight_authorized,
automatic_brokerage_execution_authorized,expected_dimension_count,expected_method_count,
expected_range_count,expected_condition_count,expected_risk_reason_count) VALUES (
%(assessment_id)s,%(assembly_id)s,%(contract_version)s,%(sleeve)s,%(company_type)s,
%(applicability)s,%(currency)s,%(projection_years)s,%(reference_price)s,%(claim_ceiling)s,
%(model_evidence_label)s,%(risk_cap_ceiling)s,%(model_version)s,
%(strategy_version)s,%(formula_version)s,%(assumption_policy_version)s,%(aggregation_version)s,
%(risk_policy_version)s,%(input_hash)s,%(result_content_hash)s,%(deterministic_ranking_authorized)s,
%(final_portfolio_weight_authorized)s,%(automatic_brokerage_execution_authorized)s,
%(expected_dimension_count)s,%(expected_method_count)s,%(expected_range_count)s,
%(expected_condition_count)s,%(expected_risk_reason_count)s)"""

_INSERT_DIMENSION = """INSERT INTO analytics.fundamental_value_dimension_v1
(assessment_id,dimension_ordinal,dimension_code,state,score,expected_reason_count)
VALUES (%(assessment_id)s,%(ordinal)s,%(code)s,%(state)s,%(score)s,%(reason_count)s)"""
_INSERT_METHOD = """INSERT INTO analytics.fundamental_value_valuation_method_v1
(assessment_id,method_ordinal,method_code,method_role,method_weight,state,terminal_value_share,
expected_reason_count) VALUES (%(assessment_id)s,%(ordinal)s,%(code)s,%(role)s,%(weight)s,%(state)s,
%(terminal)s,%(reason_count)s)"""
_INSERT_SCENARIO = """INSERT INTO analytics.fundamental_value_valuation_scenario_v1
(assessment_id,method_ordinal,scenario_ordinal,scenario_code,fair_value_per_share)
VALUES (%(assessment_id)s,%(method_ordinal)s,%(ordinal)s,%(code)s,%(value)s)"""
_INSERT_RANGE = """INSERT INTO analytics.fundamental_value_ordered_range_v1
(assessment_id,range_ordinal,range_code,state,low_value,central_value,high_value,expected_reason_count)
VALUES (%(assessment_id)s,%(ordinal)s,%(code)s,%(state)s,%(low)s,%(central)s,%(high)s,%(reason_count)s)"""
_INSERT_CONDITION = """INSERT INTO analytics.fundamental_value_condition_v1
(assessment_id,condition_kind,condition_ordinal,condition_code,state,observed_value,threshold_value,
satisfied,expected_reason_count) VALUES (%(assessment_id)s,%(kind)s,%(ordinal)s,%(code)s,%(state)s,
%(observed)s,%(threshold)s,%(satisfied)s,%(reason_count)s)"""
_INSERT_ASSESSMENT_SEAL = """INSERT INTO analytics.fundamental_value_assessment_seal_v1
(assessment_id,dimension_count,method_count,scenario_count,range_count,condition_count,
component_reason_count,risk_reason_count) VALUES (%(assessment_id)s,%(dimensions)s,%(methods)s,
%(scenarios)s,%(ranges)s,%(conditions)s,%(component_reasons)s,%(risk_reasons)s)"""

_SELECT_ASSEMBLY = """SELECT assembly.*, session.session_date,
assembly.applicability_routing_content_hash AS routing_content_hash,
assembly.applicability_routing_revision AS routing_revision,
assembly.classification_selector_policy_version AS classification_policy_version,
assembly.classification_request_content_hash,
assembly.classification_result_content_hash,
result.reason_code AS classification_reason_code,
assembly.classification_source_content_hash,
assembly.classification_normalized_record_hash,
assembly.classification_source_revision,
assembly.classification_effective_at,
assembly.classification_available_at,
assembly.classification_ingested_at,
assembly.classification_freshness_policy_version,
assembly.classification_normalization_version,
assembly.classification_provider_schema_version,
assembly.classification_adapter_version,
evidence.tolerance_policy_version AS classification_tolerance_policy_version,
evidence.derivation_version AS classification_derivation_version
FROM analytics.fundamental_value_assembly_v1 assembly
JOIN analytics.evidence_selection_request_v1 request ON request.request_id=assembly.classification_request_id
JOIN analytics.evidence_completed_session_v1 session ON session.id=request.completed_session_id
JOIN analytics.evidence_selection_result_v1 result ON result.request_id=request.request_id
JOIN analytics.canonical_evidence_v1 evidence ON evidence.evidence_id=assembly.classification_evidence_id
JOIN analytics.model_applicability_routing_v1 route ON route.routing_id=assembly.applicability_routing_id
WHERE assembly.assembly_id=%(assembly_id)s"""
