from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from equity_analysis.analytics_interface.routes import (
    router as analytics_model_router,
)
from equity_analysis.evidence_foundation.routes_v1 import (
    router as evidence_foundation_router,
)
from equity_analysis.forward_validation.routes import router as forward_validation_router
from equity_analysis.fundamental_value.current_routes_v1 import (
    router as current_fundamental_value_router,
)
from equity_analysis.fundamental_value.routes_v1 import router as fundamental_value_router
from equity_analysis.market_data.routes import router as market_data_router
from equity_analysis.market_intelligence.routes import router as market_intelligence_router
from equity_analysis.portfolio_context.routes_v1 import router as portfolio_context_router
from equity_analysis.portfolio_decision.routes_v1 import router as portfolio_decision_router
from equity_analysis.quant_trading.routes_v11 import router as quant_trading_router
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
app.include_router(evidence_foundation_router)
app.include_router(fundamental_value_router)
app.include_router(current_fundamental_value_router)
app.include_router(quant_trading_router)
app.include_router(portfolio_context_router)
app.include_router(portfolio_decision_router)


@app.exception_handler(RequestValidationError)
async def stable_fundamental_value_validation_error(
    request: Request, error: RequestValidationError
):
    if request.url.path.startswith("/internal/v1/fundamental-value/"):
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "INVALID_FUNDAMENTAL_VALUE_ID_CONTRACT"}},
        )
    if request.url.path.startswith("/internal/v1/quant-trading/"):
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "INVALID_QUANT_RESEARCH_CONTRACT"}},
        )
    if request.url.path.startswith("/internal/v1/portfolio-context/"):
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "INVALID_PORTFOLIO_RISK_CONTRACT"}},
        )
    if request.url.path.startswith((
        "/internal/v1/portfolio-decisions/",
        "/internal/v1/portfolio-decision-scenarios/",
    )):
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "INVALID_PORTFOLIO_DECISION_CONTRACT"}},
        )
    return await request_validation_exception_handler(request, error)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(service="analysis-python", status="UP")
