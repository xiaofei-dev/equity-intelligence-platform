from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from equity_analysis.config import Settings
from equity_analysis.screening.models import (
    RatingPage,
    ScreeningRunAccepted,
    ScreeningRunRequest,
    ScreeningRunStatus,
)
from equity_analysis.screening.persistence import (
    ScreeningConflictError,
    ScreeningNotReadyError,
    ScreeningRepository,
)
from equity_analysis.screening.snapshot import (
    DataSnapshotRepository,
    SnapshotConflictError,
    SnapshotRequest,
)

router = APIRouter(prefix="/internal/v1/screening", tags=["screening"])
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="screening")


class SnapshotCreateRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    snapshot_key: str
    as_of_time: datetime
    ingestion_cutoff: datetime
    universe_version: str
    market_normalization_version: str
    fundamental_normalization_version: str
    action_normalization_version: str


class SnapshotAccepted(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    snapshot_id: UUID
    snapshot_key: str
    status: str


def get_repository() -> ScreeningRepository:
    settings = Settings.from_environment()
    if not settings.analytics_database_url:
        raise HTTPException(
            status_code=503,
            detail={"code": "SCREENING_NOT_CONFIGURED", "message": "Database is not configured"},
        )
    return ScreeningRepository(settings.analytics_database_url)


@router.post("/snapshots", response_model=SnapshotAccepted, status_code=201)
def create_snapshot(request: SnapshotCreateRequest) -> SnapshotAccepted:
    settings = Settings.from_environment()
    try:
        snapshot_id = DataSnapshotRepository(
            settings.analytics_database_url
        ).create_and_seal(SnapshotRequest(**request.model_dump()))
    except SnapshotConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "SNAPSHOT_KEY_CONFLICT", "message": str(error)},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_SNAPSHOT_REQUEST", "message": str(error)},
        ) from error
    return SnapshotAccepted(
        snapshot_id=snapshot_id,
        snapshot_key=request.snapshot_key,
        status="READY",
    )


@router.post("/runs", response_model=ScreeningRunAccepted, status_code=202)
def create_run(
    request: ScreeningRunRequest,
    background_tasks: BackgroundTasks,
    repository: Annotated[ScreeningRepository, Depends(get_repository)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ScreeningRunAccepted:
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail={"code": "IDEMPOTENCY_KEY_REQUIRED", "message": "Idempotency-Key is required"},
        )
    try:
        accepted = repository.create_run(request, idempotency_key)
    except ScreeningConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "IDEMPOTENCY_KEY_CONFLICT", "message": str(error)},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_SCREENING_REQUEST", "message": str(error)},
        ) from error
    background_tasks.add_task(repository.execute, UUID(accepted.run_id))
    return accepted


@router.get("/runs/{run_id}", response_model=ScreeningRunStatus)
def get_run(
    run_id: UUID,
    repository: Annotated[ScreeningRepository, Depends(get_repository)],
) -> ScreeningRunStatus:
    result = repository.get_status(run_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "RUN_NOT_FOUND", "message": "Run not found"},
        )
    return result


@router.get("/runs/{run_id}/ratings", response_model=RatingPage)
def get_ratings(
    run_id: UUID,
    repository: Annotated[ScreeningRepository, Depends(get_repository)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RatingPage:
    try:
        return repository.ratings(run_id, cursor, limit)
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "RUN_NOT_FOUND", "message": str(error)},
        ) from error
    except (ScreeningNotReadyError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "RESULT_NOT_READY", "message": str(error)},
        ) from error


def recover_pending_runs() -> None:
    try:
        repository = get_repository()
        for run_id in repository.claim_pending():
            _executor.submit(repository.execute, run_id)
    except Exception:
        # Readiness remains available; task endpoints expose configuration errors.
        return
