from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    model_validator,
)
from pydantic.alias_generators import to_camel

from equity_analysis.config import Settings

from .evidence_assembly_v11 import (
    REQUIRED_HISTORY,
    PostgresQuantV22RepositoryV11,
    QuantCrossSectionAssemblyByIdV11,
    QuantEvidenceAssemblyViolation,
    SeriesAssemblyByIdV11,
    SeriesRole,
    assemble_quant_cross_section_from_v22_v11,
)
from .research_decision_v11 import (
    QuantResearchDecisionViolation,
    build_quant_research_decision_v11,
)
from .research_persistence_v11 import (
    QuantResearchDecisionRepositoryV11,
    QuantResearchPersistenceConflict,
    QuantResearchPersistenceViolation,
)

INTERNAL_QUANT_COMMAND_VERSION = "internal-quant-research-command-v1.1.0"

router = APIRouter(prefix="/internal/v1/quant-trading", tags=["quant-trading"])


def _canonical_uuid(value: Any) -> UUID:
    if type(value) is not str:
        raise ValueError("UUID must be a canonical string")
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError("UUID must use canonical lowercase hyphenated form")
    return parsed


def _strict_instant(value: Any) -> datetime:
    if type(value) is not str:
        raise ValueError("Timestamp must be an RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Timestamp must be an RFC 3339 instant") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.microsecond != 0:
        raise ValueError("Timestamp must be a whole-second RFC 3339 instant")
    return parsed.astimezone(UTC)


CanonicalUuid = Annotated[UUID, BeforeValidator(_canonical_uuid)]
StrictInstant = Annotated[datetime, BeforeValidator(_strict_instant)]


class _ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )


class QuantSeriesCommandV11(_ContractModel):
    security_id: CanonicalUuid
    role: Literal["SECURITY", "MARKET_BENCHMARK_SPY"]
    price_request_ids: list[CanonicalUuid] = Field(
        min_length=REQUIRED_HISTORY,
        max_length=REQUIRED_HISTORY,
    )

    @model_validator(mode="after")
    def validate_request_ids(self) -> QuantSeriesCommandV11:
        if len(set(self.price_request_ids)) != len(self.price_request_ids):
            raise ValueError("Price request IDs must be unique")
        return self


class QuantResearchCommandV11(_ContractModel):
    contract_version: Literal["internal-quant-research-command-v1.1.0"]
    rebalance_ordinal: StrictInt = Field(ge=0)
    expected_security_ids: list[CanonicalUuid] = Field(min_length=20)
    market: QuantSeriesCommandV11
    members: list[QuantSeriesCommandV11] = Field(min_length=20)
    decision_cutoff: StrictInstant
    sealed_ingestion_cutoff: StrictInstant

    @model_validator(mode="after")
    def validate_denominator(self) -> QuantResearchCommandV11:
        if self.rebalance_ordinal % 5 != 0:
            raise ValueError("Rebalance ordinal must use the five-session schedule")
        expected = [str(value) for value in self.expected_security_ids]
        if expected != sorted(set(expected)):
            raise ValueError("Expected security IDs must be sorted and unique")
        if self.market.role != SeriesRole.MARKET_BENCHMARK_SPY.value:
            raise ValueError("Market series must be SPY")
        if any(item.role != SeriesRole.SECURITY.value for item in self.members):
            raise ValueError("Member series must be securities")
        if [str(item.security_id) for item in self.members] != expected:
            raise ValueError("Member series must exactly match the denominator")
        request_ids = [
            str(request_id)
            for item in (self.market, *self.members)
            for request_id in item.price_request_ids
        ]
        if len(set(request_ids)) != len(request_ids):
            raise ValueError("Request IDs cannot be reused across series")
        if self.decision_cutoff > self.sealed_ingestion_cutoff:
            raise ValueError("Decision cutoff cannot follow the sealed cutoff")
        return self


def get_quant_v22_repository() -> PostgresQuantV22RepositoryV11:
    return PostgresQuantV22RepositoryV11(_database_url())


def get_quant_decision_repository() -> QuantResearchDecisionRepositoryV11:
    return QuantResearchDecisionRepositoryV11(_database_url())


def _database_url() -> str:
    value = Settings.from_environment().analytics_database_url
    if not value:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "QUANT_RESEARCH_NOT_CONFIGURED"},
        )
    return value


@router.post("/research-decisions", status_code=status.HTTP_201_CREATED)
def create_quant_research_decision(
    command: QuantResearchCommandV11,
    evidence_repository: Annotated[
        PostgresQuantV22RepositoryV11, Depends(get_quant_v22_repository)
    ],
    decision_repository: Annotated[
        QuantResearchDecisionRepositoryV11, Depends(get_quant_decision_repository)
    ],
) -> dict[str, Any]:
    try:
        assembly = assemble_quant_cross_section_from_v22_v11(
            evidence_repository,
            _assembly_request(command),
        )
        decision = build_quant_research_decision_v11(assembly)
        return decision_repository.persist(decision).payload
    except LookupError as error:
        raise _not_found() from error
    except QuantResearchPersistenceConflict as error:
        raise _integrity_conflict() from error
    except (
        QuantEvidenceAssemblyViolation,
        QuantResearchDecisionViolation,
        QuantResearchPersistenceViolation,
    ) as error:
        raise _integrity_conflict() from error


@router.get("/research-decisions/{decision_id}")
def read_quant_research_decision(
    decision_id: CanonicalUuid,
    repository: Annotated[
        QuantResearchDecisionRepositoryV11, Depends(get_quant_decision_repository)
    ],
) -> dict[str, Any]:
    try:
        persisted = repository.load(str(decision_id))
        if persisted.decision_id != str(decision_id):
            raise QuantResearchPersistenceConflict("QUANT_DECISION_READBACK_ID_DRIFT")
        return persisted.payload
    except LookupError as error:
        raise _not_found() from error
    except (
        QuantResearchPersistenceConflict,
        QuantResearchPersistenceViolation,
    ) as error:
        raise _integrity_conflict() from error


def _assembly_request(
    command: QuantResearchCommandV11,
) -> QuantCrossSectionAssemblyByIdV11:
    return QuantCrossSectionAssemblyByIdV11(
        rebalance_ordinal=command.rebalance_ordinal,
        expected_security_ids=tuple(str(value) for value in command.expected_security_ids),
        market=_series_request(command.market),
        members=tuple(_series_request(item) for item in command.members),
        decision_cutoff=command.decision_cutoff,
        sealed_ingestion_cutoff=command.sealed_ingestion_cutoff,
    )


def _series_request(command: QuantSeriesCommandV11) -> SeriesAssemblyByIdV11:
    return SeriesAssemblyByIdV11(
        security_id=str(command.security_id),
        role=SeriesRole(command.role),
        price_request_ids=tuple(str(value) for value in command.price_request_ids),
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "QUANT_RESEARCH_REFERENCE_NOT_FOUND"},
    )


def _integrity_conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "QUANT_RESEARCH_INTEGRITY_CONFLICT"},
    )
