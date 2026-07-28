from dataclasses import dataclass
from datetime import date

from equity_analysis.market_data.provider import MarketDataProvider
from equity_analysis.market_data.repository import DailyPriceRepository


@dataclass(frozen=True)
class SymbolIngestionResult:
    symbol: str
    rows_upserted: int
    status: str = "SUCCEEDED"
    error_code: str | None = None
    message: str | None = None


class DailyPriceIngestionService:
    def __init__(
        self,
        provider: MarketDataProvider,
        repository: DailyPriceRepository,
    ) -> None:
        self._provider = provider
        self._repository = repository

    @property
    def provider_code(self) -> str:
        return self._provider.descriptor.code

    def ingest(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> tuple[SymbolIngestionResult, ...]:
        results = []
        for symbol in dict.fromkeys(symbol.strip().upper() for symbol in symbols):
            try:
                results.append(self._ingest_symbol(symbol, start_date, end_date))
            except Exception as error:
                from equity_analysis.market_data.provider import MarketDataProviderError

                if not isinstance(error, MarketDataProviderError):
                    raise
                results.append(
                    SymbolIngestionResult(
                        symbol=symbol,
                        rows_upserted=0,
                        status="FAILED",
                        error_code=error.code,
                        message=str(error),
                    )
                )
        return tuple(results)

    def _ingest_symbol(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> SymbolIngestionResult:
        series = self._provider.fetch_daily_prices(symbol, start_date, end_date)
        rows_upserted = self._repository.upsert(series)
        return SymbolIngestionResult(symbol=symbol, rows_upserted=rows_upserted)
