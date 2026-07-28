from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from equity_analysis.config import Settings
from equity_analysis.market_intelligence.models import (
    ProfileInput,
    ScreeningRequest,
    SecurityProfile,
)
from equity_analysis.market_intelligence.persistence import (
    MarketIntelligenceConflictError,
    MarketIntelligenceNotFoundError,
    MarketIntelligenceRepository,
)
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
    data_snapshot_id: UUID | None = None


class DurableScreenRequest(ScreeningRequest):
    profile_ids: tuple[UUID, ...]
    data_snapshot_id: UUID | None = None


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
    payload: DurableProfileBuildRequest,
) -> DurableProfileResponse:
    repository = _repository()
    profile = build_security_profile(
        ProfileInput.model_validate(payload.model_dump(exclude={"as_of", "data_snapshot_id"})),
        payload.as_of,
    )
    profile_id = repository.persist_profile(
        profile,
        snapshot_as_of=payload.as_of,
        data_snapshot_id=payload.data_snapshot_id,
    )
    return DurableProfileResponse(
        profile_id=profile_id,
        profile=repository.load_profile(profile_id),
    )


@router.get("/profiles/{profile_id}", response_model=SecurityProfile)
def get_durable_profile(profile_id: UUID) -> SecurityProfile:
    try:
        return _repository().load_profile(profile_id)
    except MarketIntelligenceNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/screen-durable", response_model=DurableScreenResponse)
def screen_durable(
    payload: DurableScreenRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> DurableScreenResponse:
    repository = _repository()
    profiles = tuple(repository.load_profile(profile_id) for profile_id in payload.profile_ids)
    request = ScreeningRequest.model_validate(
        payload.model_dump(exclude={"profile_ids", "data_snapshot_id"})
    )
    result = screen_profiles(profiles, request)
    profile_ids = {
        profile.security.security_id: profile_id
        for profile_id, profile in zip(payload.profile_ids, profiles, strict=True)
    }
    try:
        run_id = repository.persist_screening_run(
            request,
            result,
            profile_ids,
            idempotency_key=idempotency_key,
            data_snapshot_id=payload.data_snapshot_id,
        )
    except MarketIntelligenceConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return DurableScreenResponse(
        run_id=run_id,
        result=repository.load_screening_result(run_id).model_dump(mode="json", by_alias=True),
    )


@router.get("/screening-runs/{run_id}")
def get_durable_screening_result(run_id: UUID) -> dict[str, Any]:
    try:
        return _repository().load_screening_result(run_id).model_dump(mode="json", by_alias=True)
    except MarketIntelligenceNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _repository() -> MarketIntelligenceRepository:
    return MarketIntelligenceRepository(Settings.from_environment().analytics_database_url)
