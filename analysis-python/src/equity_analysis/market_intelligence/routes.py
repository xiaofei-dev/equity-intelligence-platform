from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from equity_analysis.config import Settings
from equity_analysis.market_intelligence.models import (
    MarketIntelligenceFacets,
    MarketIntelligenceProfileEnvelope,
    ProfileInput,
    ScreeningRequest,
    ScreeningResultPage,
    ScreeningRunMetadata,
    SecurityProfile,
    SecuritySearchPage,
    SnapshotScreeningRequest,
)
from equity_analysis.market_intelligence.persistence import (
    MarketIntelligenceConflictError,
    MarketIntelligenceCursorError,
    MarketIntelligenceNotFoundError,
    MarketIntelligenceRepository,
    MarketIntelligenceSnapshotError,
)
from equity_analysis.market_intelligence.pipeline import MarketIntelligenceAssembler
from equity_analysis.market_intelligence.service import (
    build_security_profile,
    screen_profiles,
)

router = APIRouter(
    prefix="/internal/v1/market-intelligence",
    tags=["market-intelligence"],
)


class ProfileBuildRequest(ProfileInput):
    as_of: datetime


class ScreenRequest(ScreeningRequest):
    profiles: tuple[SecurityProfile, ...]


class DurableProfileBuildRequest(ProfileBuildRequest):
    data_snapshot_id: UUID


class DurableScreenRequest(ScreeningRequest):
    profile_ids: tuple[UUID, ...]
    data_snapshot_id: UUID
    universe_version: str


class DurableProfileResponse(BaseModel):
    profile_id: UUID
    profile: SecurityProfile


class DurableScreenResponse(BaseModel):
    run_id: UUID
    result: dict[str, Any]


@router.post("/profiles/build", response_model=SecurityProfile)
def build_profile(payload: ProfileBuildRequest) -> SecurityProfile:
    return build_security_profile(
        ProfileInput.model_validate(payload.model_dump(exclude={"as_of"})),
        payload.as_of,
    )


@router.post("/screen")
def screen(payload: ScreenRequest) -> dict[str, Any]:
    result = screen_profiles(
        payload.profiles,
        ScreeningRequest.model_validate(payload.model_dump(exclude={"profiles"})),
    )
    return result.model_dump(mode="json", by_alias=True)


@router.post("/profiles/build-durable", response_model=DurableProfileResponse)
def build_durable_profile(
    _payload: DurableProfileBuildRequest,
) -> DurableProfileResponse:
    raise HTTPException(
        status_code=410,
        detail={
            "code": "SNAPSHOT_DRIVEN_PROFILE_BUILD_REQUIRED",
            "message": (
                "Durable profiles are assembled only from a READY data snapshot "
                "through the screening-runs resource"
            ),
        },
    )


@router.get("/profiles/{profile_id}", response_model=MarketIntelligenceProfileEnvelope)
def get_durable_profile(profile_id: UUID) -> MarketIntelligenceProfileEnvelope:
    try:
        return _repository().load_profile_envelope(profile_id)
    except MarketIntelligenceNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/screen-durable", response_model=DurableScreenResponse)
def screen_durable(
    _payload: DurableScreenRequest,
    _idempotency_key: str = Header(alias="Idempotency-Key"),
) -> DurableScreenResponse:
    raise HTTPException(
        status_code=410,
        detail={
            "code": "SNAPSHOT_DRIVEN_SCREENING_REQUIRED",
            "message": (
                "Durable screening accepts a READY snapshot and universe, "
                "not caller-supplied profile IDs"
            ),
        },
    )


@router.get("/screening-runs/{run_id}", response_model=ScreeningRunMetadata)
def get_durable_screening_result(run_id: UUID) -> ScreeningRunMetadata:
    try:
        return _repository().load_run_metadata(run_id)
    except (MarketIntelligenceNotFoundError, MarketIntelligenceSnapshotError) as error:
        _raise_market_intelligence_error(error)


@router.post(
    "/screening-runs",
    response_model=ScreeningRunMetadata,
    status_code=201,
)
def create_snapshot_screening_run(
    payload: SnapshotScreeningRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> ScreeningRunMetadata:
    repository = _repository()
    try:
        assembled = _assembler().assemble_snapshot(
            data_snapshot_id=payload.data_snapshot_id,
            universe_version=payload.universe_version,
        )
        if assembled.snapshot.as_of != payload.as_of:
            raise MarketIntelligenceSnapshotError(
                "Request asOf must exactly match the sealed data snapshot"
            )
        profile_pairs = tuple(
            (profile_id, repository.load_profile(profile_id))
            for profile_id in assembled.profile_ids
        )
        request = ScreeningRequest.model_validate(
            payload.model_dump(exclude={"data_snapshot_id", "universe_version"})
        )
        result = screen_profiles(
            tuple(item[1] for item in profile_pairs),
            request,
        )
        profile_ids = {
            profile.security.security_id: profile_id
            for profile_id, profile in profile_pairs
        }
        run_id = repository.persist_screening_run(
            request,
            result,
            profile_ids,
            idempotency_key=idempotency_key,
            data_snapshot_id=payload.data_snapshot_id,
            universe_version=payload.universe_version,
        )
        repository.persist_decision_snapshot_event(
            data_snapshot_id=payload.data_snapshot_id,
            universe_version=payload.universe_version,
            objective_screening_run_id=assembled.objective_screening_run_id,
            profile_ids=assembled.profile_ids,
            screening_run_ids=(run_id,),
            as_of=payload.as_of,
        )
        return repository.load_run_metadata(run_id)
    except (
        MarketIntelligenceConflictError,
        MarketIntelligenceSnapshotError,
    ) as error:
        _raise_market_intelligence_error(error)


@router.get(
    "/screening-runs/{run_id}/metadata",
    response_model=ScreeningRunMetadata,
)
def get_screening_run_metadata(run_id: UUID) -> ScreeningRunMetadata:
    try:
        return _repository().load_run_metadata(run_id)
    except (MarketIntelligenceNotFoundError, MarketIntelligenceSnapshotError) as error:
        _raise_market_intelligence_error(error)


@router.get(
    "/screening-runs/{run_id}/results",
    response_model=ScreeningResultPage,
)
def get_screening_run_results(
    run_id: UUID,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> ScreeningResultPage:
    try:
        return _repository().load_screening_page(run_id, cursor=cursor, limit=limit)
    except (
        MarketIntelligenceCursorError,
        MarketIntelligenceNotFoundError,
        MarketIntelligenceSnapshotError,
    ) as error:
        _raise_market_intelligence_error(error)


@router.get(
    "/securities/{security_id}/profiles/latest",
    response_model=MarketIntelligenceProfileEnvelope,
)
def get_latest_security_profile(
    security_id: UUID,
    as_of: datetime | None = None,
) -> MarketIntelligenceProfileEnvelope:
    try:
        repository = _repository()
        profile_id, _profile = repository.load_latest_profile(
            security_id,
            as_of=as_of or datetime.now(UTC),
        )
        return repository.load_profile_envelope(profile_id)
    except MarketIntelligenceNotFoundError as error:
        _raise_market_intelligence_error(error)


@router.get("/securities", response_model=SecuritySearchPage)
def search_securities(
    data_snapshot_id: UUID,
    query: str = "",
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> SecuritySearchPage:
    try:
        return _repository().search_securities(
            data_snapshot_id,
            query=query,
            cursor=cursor,
            limit=limit,
        )
    except (MarketIntelligenceCursorError, MarketIntelligenceSnapshotError) as error:
        _raise_market_intelligence_error(error)


@router.get("/facets", response_model=MarketIntelligenceFacets)
def get_market_intelligence_facets(
    data_snapshot_id: UUID,
) -> MarketIntelligenceFacets:
    try:
        return _repository().load_facets(data_snapshot_id)
    except MarketIntelligenceSnapshotError as error:
        _raise_market_intelligence_error(error)


def _repository() -> MarketIntelligenceRepository:
    return MarketIntelligenceRepository(Settings.from_environment().analytics_database_url)


def _assembler() -> MarketIntelligenceAssembler:
    return MarketIntelligenceAssembler(Settings.from_environment().analytics_database_url)


def _raise_market_intelligence_error(error: ValueError) -> None:
    status = (
        404
        if isinstance(error, MarketIntelligenceNotFoundError)
        else 409
        if isinstance(error, MarketIntelligenceConflictError)
        else 400
    )
    raise HTTPException(
        status_code=status,
        detail={
            "code": getattr(error, "code", "INVALID_MARKET_INTELLIGENCE_REQUEST"),
            "message": str(error),
        },
    ) from error
