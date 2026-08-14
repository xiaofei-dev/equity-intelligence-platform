from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    model_validator,
)
from pydantic.alias_generators import to_camel

from equity_analysis.config import Settings
from equity_analysis.evidence_foundation.contracts_v1 import UnifiedEvidenceContractViolation
from equity_analysis.evidence_foundation.persistence_v1 import EvidenceFoundationRepository
from equity_analysis.fundamental_value.core_v1 import (
    canonical_decimal_text,
    evaluate_fundamental_value_v1,
)
from equity_analysis.fundamental_value.evidence_assembly_v1 import (
    AssemblyViolation,
    FundamentalValueAssemblyByIdRequestV1,
    OperandSelectorRequestIdV1,
    assemble_fundamental_value_from_v22_v1,
)
from equity_analysis.fundamental_value.persistence_v1 import (
    ASSESSMENT_PERSISTENCE_VERSION,
    FundamentalValuePersistenceConflict,
    FundamentalValuePersistenceViolation,
    FundamentalValueRepositoryV1,
    PostgresFundamentalValueBackendV1,
)

INTERNAL_COMMAND_VERSION = "internal-fundamental-value-command-v1.0.0"
INTERNAL_RESULT_VERSION = "internal-fundamental-value-result-v1.1.0"
ASSEMBLY_NOT_FOUND_REASONS = frozenset(
    {
        "PERSISTED_APPLICABILITY_ROUTING_NOT_FOUND",
        "PERSISTED_SELECTOR_REQUEST_NOT_FOUND",
    }
)

router = APIRouter(prefix="/internal/v1/fundamental-value", tags=["fundamental-value"])


def _canonical_uuid(value: Any) -> UUID:
    if not isinstance(value, str):
        raise ValueError("UUID must be a canonical string")
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError("UUID must use canonical lowercase hyphenated form")
    return parsed


CanonicalUuid = Annotated[UUID, BeforeValidator(_canonical_uuid)]


class _ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )


class OperandRequestIdCommandV1(_ContractModel):
    operand_code: StrictStr = Field(min_length=1, max_length=128)
    request_id: CanonicalUuid


class FundamentalValueCommandV1(_ContractModel):
    contract_version: Literal["internal-fundamental-value-command-v1.0.0"]
    routing_id: CanonicalUuid
    classification_request_id: CanonicalUuid
    operand_request_ids: list[OperandRequestIdCommandV1] = Field(max_length=34)
    projection_years: StrictInt = Field(ge=3, le=10)

    @model_validator(mode="after")
    def validate_unique_operands(self) -> FundamentalValueCommandV1:
        codes = [item.operand_code for item in self.operand_request_ids]
        request_ids = [item.request_id for item in self.operand_request_ids]
        if len(codes) != len(set(codes)) or len(request_ids) != len(set(request_ids)):
            raise ValueError("Operand codes and request IDs must be unique")
        return self


class FundamentalValueIdentityV11(_ContractModel):
    security_id: str
    company_id: str
    instrument_id: str
    share_class_id: str
    listing_id: str
    ticker_assignment_id: str
    ticker: str
    mic: str
    currency: str
    completed_session_date: str


class FundamentalValueProjectionV1(_ContractModel):
    contract_version: Literal["internal-fundamental-value-result-v1.1.0"] = (
        INTERNAL_RESULT_VERSION
    )
    assembly_id: str
    assessment_id: str | None
    identity: FundamentalValueIdentityV11
    state: str
    applicability: str
    company_type: str
    reason_codes: list[str]
    core_invocation_authorized: bool
    manifest_content_hash: str
    input_seal_content_hash: str
    decision_cutoff: str
    sealed_ingestion_cutoff: str
    model_evidence_label: Literal["NOT_VALIDATED"] | None
    claim_ceiling: str | None
    risk_cap_ceiling: str | None
    deterministic_assessment: dict[str, Any] | None
    final_portfolio_weight_authorized: Literal[False] = False
    automatic_brokerage_execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_assessment_identity(self) -> FundamentalValueProjectionV1:
        _canonical_uuid(self.assembly_id)
        if self.deterministic_assessment is None:
            if self.assessment_id is not None:
                raise ValueError("Assessment identity requires an assessment")
            return self
        content_hash = self.deterministic_assessment.get("contentHash")
        if not isinstance(content_hash, str):
            raise ValueError("Assessment content hash is required")
        expected = str(
            uuid5(
                NAMESPACE_URL,
                f"{ASSESSMENT_PERSISTENCE_VERSION}:{self.assembly_id}:{content_hash}",
            )
        )
        if self.assessment_id != expected:
            raise ValueError("Assessment identity does not match immutable content")
        return self


def get_evidence_repository() -> EvidenceFoundationRepository:
    return EvidenceFoundationRepository(_database_url())


def get_fundamental_repository() -> FundamentalValueRepositoryV1:
    return FundamentalValueRepositoryV1(PostgresFundamentalValueBackendV1(_database_url()))


def _database_url() -> str:
    url = Settings.from_environment().analytics_database_url
    if not url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "FUNDAMENTAL_VALUE_NOT_CONFIGURED"},
        )
    return url


@router.post("/decisions", response_model=FundamentalValueProjectionV1)
def create_decision(
    command: FundamentalValueCommandV1,
    evidence_repository: Annotated[
        EvidenceFoundationRepository, Depends(get_evidence_repository)
    ],
    fundamental_repository: Annotated[
        FundamentalValueRepositoryV1, Depends(get_fundamental_repository)
    ],
) -> FundamentalValueProjectionV1:
    try:
        classification = evidence_repository.load_selector_aggregate(
            str(command.classification_request_id)
        )
        request = _assembly_request(command, classification.request)
        assembly = assemble_fundamental_value_from_v22_v1(evidence_repository, request)
        if not assembly.core_invocation_authorized and command.operand_request_ids and not (
            assembly.applicability.value == "APPLICABLE"
        ):
            raise AssemblyViolation("SPECIALIZED_ROUTE_CANNOT_ACCEPT_GENERIC_OPERANDS")
        assessment = (
            evaluate_fundamental_value_v1(assembly.inputs)
            if assembly.core_invocation_authorized and assembly.inputs is not None
            else None
        )
        record = fundamental_repository.persist(assembly, assessment)
    except LookupError as error:
        raise _not_found(error) from error
    except FundamentalValuePersistenceConflict as error:
        raise _conflict(error) from error
    except FundamentalValuePersistenceViolation as error:
        raise _conflict(error) from error
    except UnifiedEvidenceContractViolation as error:
        raise _evidence_conflict(error) from error
    except AssemblyViolation as error:
        if str(error) in ASSEMBLY_NOT_FOUND_REASONS:
            raise _not_found(error) from error
        raise _invalid(error) from error
    except ValueError as error:
        raise _invalid(error) from error
    return _projection(record)


@router.get("/decisions/{assembly_id}", response_model=FundamentalValueProjectionV1)
def read_decision(
    assembly_id: CanonicalUuid,
    repository: Annotated[
        FundamentalValueRepositoryV1, Depends(get_fundamental_repository)
    ],
) -> FundamentalValueProjectionV1:
    try:
        requested_assembly_id = str(assembly_id)
        record = repository.load(requested_assembly_id)
        if record.assembly_id != requested_assembly_id:
            raise FundamentalValuePersistenceViolation("ASSEMBLY_ID_READBACK_DRIFT")
        return _projection(record)
    except LookupError as error:
        raise _not_found(error) from error
    except FundamentalValuePersistenceViolation as error:
        raise _conflict(error) from error


def _assembly_request(
    command: FundamentalValueCommandV1, classification_request: Any
) -> FundamentalValueAssemblyByIdRequestV1:
    return FundamentalValueAssemblyByIdRequestV1(
        routing_id=str(command.routing_id),
        classification_request_id=str(command.classification_request_id),
        operand_request_ids=tuple(
            OperandSelectorRequestIdV1(item.operand_code, str(item.request_id))
            for item in command.operand_request_ids
        ),
        expected_security=classification_request.security,
        expected_completed_session=classification_request.completed_session,
        expected_decision_cutoff=classification_request.decision_cutoff,
        expected_sealed_ingestion_cutoff=classification_request.sealed_ingestion_cutoff,
        projection_years=command.projection_years,
    )


def _projection(record: Any) -> FundamentalValueProjectionV1:
    assessment = record.assessment
    return FundamentalValueProjectionV1(
        assembly_id=record.assembly_id,
        assessment_id=record.assessment_id,
        identity=FundamentalValueIdentityV11(
            security_id=record.assembly.security.security_id,
            company_id=record.assembly.security.company_id,
            instrument_id=record.assembly.security.instrument_id,
            share_class_id=record.assembly.security.share_class_id,
            listing_id=record.assembly.security.listing_id,
            ticker_assignment_id=record.assembly.security.ticker_assignment_id,
            ticker=record.assembly.security.ticker,
            mic=record.assembly.security.mic,
            currency=record.assembly.security.currency,
            completed_session_date=record.assembly.completed_session_date,
        ),
        state=record.assembly.state.value,
        applicability=record.assembly.applicability.value,
        company_type=record.assembly.company_type.value,
        reason_codes=list(record.assembly.reason_codes),
        core_invocation_authorized=record.assembly.core_invocation_authorized,
        manifest_content_hash=record.assembly.manifest_content_hash,
        input_seal_content_hash=record.input_seal.content_hash,
        decision_cutoff=_instant(record.assembly.decision_cutoff),
        sealed_ingestion_cutoff=_instant(record.assembly.sealed_ingestion_cutoff),
        model_evidence_label=(assessment.model_evidence_label.value if assessment else None),
        claim_ceiling=(assessment.claim_ceiling.value if assessment else None),
        risk_cap_ceiling=(
            canonical_decimal_text(assessment.risk_cap.ceiling) if assessment else None
        ),
        deterministic_assessment=_safe_value(assessment) if assessment else None,
    )


def _safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _instant(value)
    if is_dataclass(value):
        return {
            _camel(field.name): _safe_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, tuple | list):
        return [_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {_camel(str(key)): _safe_value(item) for key, item in value.items()}
    return value


def _camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(item.capitalize() for item in tail)


def _instant(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _not_found(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "FUNDAMENTAL_VALUE_REFERENCE_NOT_FOUND"},
    )


def _invalid(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": "INVALID_FUNDAMENTAL_VALUE_ID_CONTRACT"},
    )


def _conflict(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "FUNDAMENTAL_VALUE_INTEGRITY_CONFLICT"},
    )


def _evidence_conflict(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "EVIDENCE_FOUNDATION_INTEGRITY_CONFLICT"},
    )
