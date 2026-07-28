from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from equity_analysis.analytics_interface.contracts import (
    AiBoundary,
    AnalyticsInterfaceError,
    LongHorizonModelRequest,
    ModelTiming,
    ProviderProvenance,
    RequestEvidence,
    TacticalModelRequest,
)
from equity_analysis.analytics_interface.runtime import create_default_model_facade
from equity_analysis.research_rating.long_horizon_v1 import (
    LONG_HORIZON_VERSION,
    CompanyModel,
    LongHorizonInputs,
)
from equity_analysis.tactical.signal_v2 import (
    TACTICAL_SIGNAL_VERSION,
    EntryStage,
    PriorReversalContext,
    TacticalBar,
)

router = APIRouter(
    prefix="/internal/v1/analytics/models",
    tags=["analytics-models"],
)
_facade = create_default_model_facade()


class ModelTimingRequest(BaseModel):
    as_of: datetime
    effective_at: datetime
    expires_at: datetime | None = None

    def to_domain(self) -> ModelTiming:
        return ModelTiming(
            as_of=self.as_of,
            effective_at=self.effective_at,
            expires_at=self.expires_at,
        )


class ProviderProvenanceRequest(BaseModel):
    provider_code: str = Field(min_length=1)
    provider_schema_version: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    available_at: datetime
    retrieved_at: datetime
    adjustment_mode: str | None = None

    def to_domain(self) -> ProviderProvenance:
        return ProviderProvenance(**self.model_dump())


class EvidenceRequest(BaseModel):
    evidence_hash: str = Field(min_length=1)
    providers: list[ProviderProvenanceRequest] = Field(min_length=1)
    missing_inputs: list[str] = Field(default_factory=list)
    ai_boundary: AiBoundary = AiBoundary.DETERMINISTIC_ONLY

    def to_domain(self) -> RequestEvidence:
        return RequestEvidence(
            evidence_hash=self.evidence_hash,
            providers=tuple(provider.to_domain() for provider in self.providers),
            missing_inputs=tuple(self.missing_inputs),
            ai_boundary=self.ai_boundary,
        )


class LongHorizonInputsRequest(BaseModel):
    symbol: str = Field(min_length=1)
    company_model: CompanyModel
    price_earnings: float | None = None
    price_book: float | None = None
    enterprise_value_ebitda: float | None = None
    peg: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    return_on_equity: float | None = None
    revenue_growth_yoy: float | None = None
    earnings_growth_yoy: float | None = None
    current_ratio: float | None = None
    debt_to_equity: float | None = None
    nonperforming_assets: float | None = None
    tier_one_leverage: float | None = None
    recent_public_trading_days: int | None = Field(default=None, ge=0)
    evidence_confidence: float = Field(default=1.0, ge=0, le=1)

    def to_domain(self) -> LongHorizonInputs:
        return LongHorizonInputs(**self.model_dump())


class LongHorizonEvaluationRequest(BaseModel):
    model_id: Literal["LONG_HORIZON_RESEARCH"] = "LONG_HORIZON_RESEARCH"
    model_version: str = LONG_HORIZON_VERSION
    timing: ModelTimingRequest
    evidence: EvidenceRequest
    inputs: LongHorizonInputsRequest


class TacticalBarRequest(BaseModel):
    trading_date: date
    open_price: float = Field(gt=0)
    high_price: float = Field(gt=0)
    low_price: float = Field(gt=0)
    close_price: float = Field(gt=0)
    volume: int = Field(ge=0)
    adjustment_factor: float = Field(default=1.0, gt=0)
    session_complete: bool = True

    def to_domain(self) -> TacticalBar:
        return TacticalBar(**self.model_dump())


class PriorReversalContextRequest(BaseModel):
    entry_stage: EntryStage
    invalidation_level: float = Field(gt=0)
    established_as_of: date

    def to_domain(self) -> PriorReversalContext:
        return PriorReversalContext(**self.model_dump())


class TacticalEvaluationRequest(BaseModel):
    model_id: Literal["DAILY_TACTICAL_SIGNAL"] = "DAILY_TACTICAL_SIGNAL"
    model_version: str = TACTICAL_SIGNAL_VERSION
    symbol: str = Field(min_length=1)
    benchmark_symbol: str = Field(min_length=1)
    timing: ModelTimingRequest
    evidence: EvidenceRequest
    security_bars: list[TacticalBarRequest] = Field(min_length=21)
    benchmark_bars: list[TacticalBarRequest] = Field(min_length=21)
    event_drift_score: float = Field(default=50.0, ge=0, le=100)
    prior_reversal_context: PriorReversalContextRequest | None = None


@router.post("/long-horizon/evaluate")
def evaluate_long_horizon_model(
    payload: LongHorizonEvaluationRequest,
) -> dict[str, Any]:
    try:
        result = _facade.evaluate(
            LongHorizonModelRequest(
                timing=payload.timing.to_domain(),
                evidence=payload.evidence.to_domain(),
                inputs=payload.inputs.to_domain(),
                model_version=payload.model_version,
            )
        )
    except (AnalyticsInterfaceError, ValueError) as error:
        raise _invalid_request(error) from error
    return asdict(result)


@router.post("/tactical/evaluate")
def evaluate_tactical_model(
    payload: TacticalEvaluationRequest,
) -> dict[str, Any]:
    try:
        result = _facade.evaluate(
            TacticalModelRequest(
                model_version=payload.model_version,
                symbol=payload.symbol,
                benchmark_symbol=payload.benchmark_symbol,
                timing=payload.timing.to_domain(),
                evidence=payload.evidence.to_domain(),
                security_bars=tuple(
                    bar.to_domain() for bar in payload.security_bars
                ),
                benchmark_bars=tuple(
                    bar.to_domain() for bar in payload.benchmark_bars
                ),
                event_drift_score=payload.event_drift_score,
                prior_reversal_context=(
                    payload.prior_reversal_context.to_domain()
                    if payload.prior_reversal_context is not None
                    else None
                ),
            )
        )
    except (AnalyticsInterfaceError, ValueError) as error:
        raise _invalid_request(error) from error
    return asdict(result)


def _invalid_request(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": getattr(error, "code", "INVALID_ANALYTICS_MODEL_REQUEST"),
            "message": str(error),
        },
    )
