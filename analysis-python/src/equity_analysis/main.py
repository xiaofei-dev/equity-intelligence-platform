from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from equity_analysis.analytics_interface.routes import (
    router as analytics_model_router,
)
from equity_analysis.forward_validation.routes import router as forward_validation_router
from equity_analysis.market_data.routes import router as market_data_router
from equity_analysis.market_intelligence.routes import router as market_intelligence_router
from equity_analysis.screening.routes import recover_pending_runs
from equity_analysis.screening.routes import router as screening_router
from equity_analysis.tactical.routes import router as tactical_router


class HealthResponse(BaseModel):
    service: str
    status: Literal["UP"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    recover_pending_runs()
    yield


app = FastAPI(
    title="Equity Analytics API",
    description="Internal analytics API for screening, backtesting, and evidence review.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(market_data_router)
app.include_router(market_intelligence_router)
app.include_router(screening_router)
app.include_router(forward_validation_router)
app.include_router(tactical_router)
app.include_router(analytics_model_router)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(service="analysis-python", status="UP")
