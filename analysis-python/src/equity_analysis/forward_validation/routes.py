from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException

from equity_analysis.config import Settings
from equity_analysis.forward_validation.models import (
    EnrollmentAccepted,
    EnrollmentRequest,
    ForwardExperimentAccepted,
    ForwardExperimentRequest,
    ForwardExperimentStatus,
)
from equity_analysis.forward_validation.persistence import (
    ForwardConflictError,
    ForwardRepository,
)

router = APIRouter(prefix="/internal/v1/forward-validation", tags=["forward-validation"])


def get_repository() -> ForwardRepository:
    database_url = Settings.from_environment().analytics_database_url
    if not database_url:
        raise HTTPException(
            status_code=503,
            detail={"code": "FORWARD_VALIDATION_NOT_CONFIGURED", "message": "Database unavailable"},
        )
    return ForwardRepository(database_url)


@router.post("/experiments", response_model=ForwardExperimentAccepted, status_code=202)
def create_experiment(
    request: ForwardExperimentRequest,
    repository: Annotated[ForwardRepository, Depends(get_repository)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ForwardExperimentAccepted:
    if not idempotency_key:
        raise HTTPException(status_code=400, detail={"code": "IDEMPOTENCY_KEY_REQUIRED"})
    try:
        return repository.create_experiment(request, idempotency_key)
    except ForwardConflictError as error:
        raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_CONFLICT"}) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": "INVALID_EXPERIMENT"}) from error


@router.get("/experiments/{experiment_id}", response_model=ForwardExperimentStatus)
def get_experiment(
    experiment_id: UUID,
    repository: Annotated[ForwardRepository, Depends(get_repository)],
) -> ForwardExperimentStatus:
    result = repository.status(experiment_id)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "EXPERIMENT_NOT_FOUND"})
    return result


@router.post(
    "/experiments/{experiment_id}/enrollments",
    response_model=EnrollmentAccepted,
    status_code=201,
)
def create_enrollment(
    experiment_id: UUID,
    request: EnrollmentRequest,
    repository: Annotated[ForwardRepository, Depends(get_repository)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> EnrollmentAccepted:
    if not idempotency_key:
        raise HTTPException(status_code=400, detail={"code": "IDEMPOTENCY_KEY_REQUIRED"})
    try:
        return repository.enroll(experiment_id, request, idempotency_key)
    except ForwardConflictError as error:
        raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_CONFLICT"}) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": "INVALID_ENROLLMENT"}) from error


@router.get("/experiments/{experiment_id}/signals")
def get_signals(
    experiment_id: UUID,
    repository: Annotated[ForwardRepository, Depends(get_repository)],
) -> list[dict[str, Any]]:
    return repository.rows(experiment_id, "signals")


@router.get("/experiments/{experiment_id}/observations")
def get_observations(
    experiment_id: UUID,
    repository: Annotated[ForwardRepository, Depends(get_repository)],
) -> list[dict[str, Any]]:
    return repository.rows(experiment_id, "observations")


@router.get("/experiments/{experiment_id}/reports/{report_type}")
def get_report(
    experiment_id: UUID,
    report_type: str,
    repository: Annotated[ForwardRepository, Depends(get_repository)],
) -> dict[str, Any]:
    result = repository.report(experiment_id, report_type)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "REPORT_NOT_FOUND"})
    return result
