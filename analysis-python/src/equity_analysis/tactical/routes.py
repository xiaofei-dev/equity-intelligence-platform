from dataclasses import asdict
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from equity_analysis.tactical.signal_v2 import (
    EntryStage,
    PriorReversalContext,
    TacticalBar,
    evaluate_tactical_signal,
)

router = APIRouter(prefix="/internal/v1/tactical", tags=["tactical"])


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
        return TacticalBar(
            trading_date=self.trading_date,
            open_price=self.open_price,
            high_price=self.high_price,
            low_price=self.low_price,
            close_price=self.close_price,
            volume=self.volume,
            adjustment_factor=self.adjustment_factor,
            session_complete=self.session_complete,
        )


class PriorReversalContextRequest(BaseModel):
    entry_stage: EntryStage
    invalidation_level: float = Field(gt=0)
    established_as_of: date

    def to_domain(self) -> PriorReversalContext:
        return PriorReversalContext(
            entry_stage=self.entry_stage,
            invalidation_level=self.invalidation_level,
            established_as_of=self.established_as_of,
        )


class TacticalEvaluationRequest(BaseModel):
    security_bars: list[TacticalBarRequest] = Field(min_length=21)
    benchmark_bars: list[TacticalBarRequest] = Field(min_length=21)
    event_drift_score: float = Field(default=50.0, ge=0, le=100)
    prior_reversal_context: PriorReversalContextRequest | None = None


@router.post("/evaluate")
def evaluate_tactical(
    request: TacticalEvaluationRequest,
) -> dict[str, Any]:
    try:
        result = evaluate_tactical_signal(
            tuple(bar.to_domain() for bar in request.security_bars),
            tuple(bar.to_domain() for bar in request.benchmark_bars),
            event_drift_score=request.event_drift_score,
            prior_reversal_context=(
                request.prior_reversal_context.to_domain()
                if request.prior_reversal_context is not None
                else None
            ),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_TACTICAL_INPUT",
                "message": str(error),
            },
        ) from error
    return asdict(result)
