from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator

from equity_analysis.config import Settings
from equity_analysis.market_data.provider import MarketDataProviderError
from equity_analysis.market_data.repository import DailyPriceRepository
from equity_analysis.market_data.service import (
    DailyPriceIngestionService,
    SymbolIngestionResult,
)
from equity_analysis.market_data.twelve_data import TwelveDataClient

router = APIRouter(prefix="/internal/v1/market-data", tags=["market-data"])


class DailyPriceIngestionRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=20)
    start_date: date
    end_date: date

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, symbols: list[str]) -> list[str]:
        normalized = [symbol.strip().upper() for symbol in symbols]
        if any(not symbol or not symbol.replace(".", "").isalnum() for symbol in normalized):
            raise ValueError("Symbols must contain only letters, numbers, or periods")
        return normalized

    @model_validator(mode="after")
    def validate_date_range(self) -> "DailyPriceIngestionRequest":
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class DailyPriceIngestionResponse(BaseModel):
    provider: str
    results: list[SymbolIngestionResult]
    total_rows_upserted: int


def get_ingestion_service() -> DailyPriceIngestionService:
    settings = Settings.from_environment()
    if settings.market_data_provider != "twelve_data":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "MARKET_DATA_PROVIDER_UNSUPPORTED",
                "message": "Configured market data provider is not supported",
            },
        )
    if not settings.twelve_data_api_key or not settings.analytics_database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "MARKET_DATA_NOT_CONFIGURED",
                "message": "Market data ingestion is not configured",
            },
        )
    return DailyPriceIngestionService(
        provider=TwelveDataClient(settings.twelve_data_api_key),
        repository=DailyPriceRepository(settings.analytics_database_url),
    )


@router.post(
    "/daily-prices/ingest",
    response_model=DailyPriceIngestionResponse,
    status_code=status.HTTP_200_OK,
)
def ingest_daily_prices(
    request: DailyPriceIngestionRequest,
    service: Annotated[DailyPriceIngestionService, Depends(get_ingestion_service)],
) -> DailyPriceIngestionResponse:
    try:
        results = service.ingest(
            symbols=tuple(request.symbols),
            start_date=request.start_date,
            end_date=request.end_date,
        )
    except MarketDataProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "MARKET_DATA_PROVIDER_ERROR",
                "message": str(error),
            },
        ) from error

    return DailyPriceIngestionResponse(
        provider="twelve_data",
        results=list(results),
        total_rows_upserted=sum(result.rows_upserted for result in results),
    )
