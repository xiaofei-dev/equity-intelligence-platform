from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    service: str
    status: Literal["UP"]


app = FastAPI(
    title="Equity Analytics API",
    description="Internal analytics API for screening, backtesting, and evidence review.",
    version="0.1.0",
)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(service="analysis-python", status="UP")
