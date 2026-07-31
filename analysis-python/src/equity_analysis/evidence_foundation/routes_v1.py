from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator
from pydantic.alias_generators import to_camel

from equity_analysis.config import Settings
from equity_analysis.evidence_foundation.contracts_v1 import (
    CONTRACT_VERSION,
    EvidenceSelectionRequest,
)
from equity_analysis.evidence_foundation.persistence_v1 import (
    EvidenceFoundationIntegrityConflict,
    EvidenceFoundationRepository,
    ModelApplicabilityRouting,
    PersistedSelectorAggregate,
    candidate_to_payload,
)

SELECTION_COMMAND_VERSION = "internal-evidence-selection-command-v1.0.0"
SELECTION_RESULT_VERSION = "internal-evidence-selection-result-v1.0.0"
APPLICABILITY_PROJECTION_VERSION = (
    "internal-model-applicability-projection-v1.0.0"
)

router = APIRouter(
    prefix="/internal/v1/evidence-foundation",
    tags=["evidence-foundation"],
)


class _InternalContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )


class EvidenceSelectionCommandV1(_InternalContractModel):
    contract_version: Literal[
        "internal-evidence-selection-command-v1.0.0"
    ]
    evidence_contract_version: Literal[
        "unified-market-data-evidence-foundation-v1.0.0"
    ]
    decision_timing: dict[str, Any]
    security: dict[str, Any]
    completed_session: dict[str, Any]
    selector_policy: dict[str, Any]
    candidate_evidence_ids: list[StrictStr] = Field(max_length=1000)

    @field_validator("candidate_evidence_ids")
    @classmethod
    def validate_candidate_evidence_ids(cls, values: list[str]) -> list[str]:
        normalized = [str(UUID(value)) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Candidate evidence identifiers must be unique")
        return normalized


class EvidenceRejectionProjectionV1(_InternalContractModel):
    evidence_id: str
    reason_code: str


class EvidenceSelectionProjectionV1(_InternalContractModel):
    contract_version: Literal[
        "internal-evidence-selection-result-v1.0.0"
    ] = SELECTION_RESULT_VERSION
    evidence_contract_version: Literal[
        "unified-market-data-evidence-foundation-v1.0.0"
    ] = CONTRACT_VERSION
    request_id: str
    selector_version: str
    state: str
    reason_code: str | None
    selected_evidence_id: str | None
    rejections: list[EvidenceRejectionProjectionV1]


class ModelApplicabilityProjectionV1(_InternalContractModel):
    contract_version: Literal[
        "internal-model-applicability-projection-v1.0.0"
    ] = APPLICABILITY_PROJECTION_VERSION
    routing_id: str
    company_id: str
    classification_evidence_id: str
    model_family: Literal["FUNDAMENTAL_VALUE"] = "FUNDAMENTAL_VALUE"
    company_type: str
    applicability: str
    specialized_model_code: str | None
    routing_version: str
    routing_revision: int
    effective_at: str
    routing_content_hash: str
    supersedes_routing_id: str | None


def get_evidence_repository() -> EvidenceFoundationRepository:
    settings = Settings.from_environment()
    if not settings.analytics_database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "EVIDENCE_FOUNDATION_NOT_CONFIGURED",
                "message": "The internal evidence foundation database is not configured",
            },
        )
    return EvidenceFoundationRepository(settings.analytics_database_url)


@router.post(
    "/selections",
    response_model=EvidenceSelectionProjectionV1,
    status_code=status.HTTP_201_CREATED,
)
def execute_evidence_selection(
    command: EvidenceSelectionCommandV1,
    response: Response,
    repository: Annotated[
        EvidenceFoundationRepository,
        Depends(get_evidence_repository),
    ],
) -> EvidenceSelectionProjectionV1:
    try:
        candidates = tuple(
            repository.load_candidate(evidence_id).candidate
            for evidence_id in command.candidate_evidence_ids
        )
        request = EvidenceSelectionRequest.parse(
            {
                "contractVersion": command.evidence_contract_version,
                "decisionTiming": command.decision_timing,
                "security": command.security,
                "completedSession": command.completed_session,
                "selectorPolicy": command.selector_policy,
                "candidates": [
                    candidate_to_payload(candidate) for candidate in candidates
                ],
            }
        )
        aggregate = repository.execute_selector(request)
    except (
        EvidenceFoundationIntegrityConflict,
        psycopg.IntegrityError,
    ) as error:
        raise _integrity_conflict(error) from error
    except LookupError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise _invalid_contract(error) from error
    if aggregate.replayed:
        response.status_code = status.HTTP_200_OK
    return _selection_projection(aggregate)


@router.get(
    "/selections/{request_id}",
    response_model=EvidenceSelectionProjectionV1,
)
def read_evidence_selection(
    request_id: UUID,
    repository: Annotated[
        EvidenceFoundationRepository,
        Depends(get_evidence_repository),
    ],
) -> EvidenceSelectionProjectionV1:
    try:
        aggregate = repository.load_selector_aggregate(str(request_id))
    except LookupError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise _invalid_contract(error) from error
    return _selection_projection(aggregate)


@router.get(
    "/model-applicability/{company_id}",
    response_model=ModelApplicabilityProjectionV1,
)
def read_model_applicability(
    company_id: UUID,
    repository: Annotated[
        EvidenceFoundationRepository,
        Depends(get_evidence_repository),
    ],
    routing_version: Annotated[
        StrictStr,
        Query(alias="routingVersion", min_length=1, max_length=128),
    ],
) -> ModelApplicabilityProjectionV1:
    try:
        routing = repository.load_latest_applicability_routing(
            str(company_id),
            routing_version,
        )
    except LookupError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise _invalid_contract(error) from error
    return _applicability_projection(routing)


def _selection_projection(
    aggregate: PersistedSelectorAggregate,
) -> EvidenceSelectionProjectionV1:
    result = aggregate.result
    return EvidenceSelectionProjectionV1(
        request_id=aggregate.request_id,
        selector_version=result.selector_version,
        state=result.state.value,
        reason_code=result.reason_code,
        selected_evidence_id=(
            result.selected.evidence_id if result.selected is not None else None
        ),
        rejections=[
            EvidenceRejectionProjectionV1(
                evidence_id=evidence_id,
                reason_code=reason_code,
            )
            for evidence_id, reason_code in result.rejection_reasons
        ],
    )


def _applicability_projection(
    routing: ModelApplicabilityRouting,
) -> ModelApplicabilityProjectionV1:
    return ModelApplicabilityProjectionV1(
        routing_id=routing.routing_id,
        company_id=routing.company_id,
        classification_evidence_id=routing.classification_evidence_id,
        company_type=routing.company_type,
        applicability=routing.applicability.value,
        specialized_model_code=routing.specialized_model_code,
        routing_version=routing.routing_version,
        routing_revision=routing.routing_revision,
        effective_at=_instant(routing.effective_at),
        routing_content_hash=routing.routing_content_hash,
        supersedes_routing_id=routing.supersedes_routing_id,
    )


def _instant(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _not_found(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "EVIDENCE_FOUNDATION_NOT_FOUND", "message": str(error)},
    )


def _invalid_contract(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "INVALID_EVIDENCE_FOUNDATION_CONTRACT", "message": str(error)},
    )


def _integrity_conflict(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "EVIDENCE_FOUNDATION_INTEGRITY_CONFLICT",
            "message": str(error),
        },
    )
