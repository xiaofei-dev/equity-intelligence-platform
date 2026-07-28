from datetime import date
from typing import Protocol

from equity_analysis.market_data.models import (
    CorporateActionSeries,
    DailyPriceSeries,
    ProviderDescriptor,
    SecurityMetadata,
)


class MarketDataProviderError(RuntimeError):
    """Raised when a market data provider cannot return a valid response."""

    def __init__(self, message: str, code: str = "PROVIDER_ERROR") -> None:
        super().__init__(message)
        self.code = code


class DailyPriceProvider(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    def fetch_daily_prices(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> DailyPriceSeries: ...


MarketDataProvider = DailyPriceProvider


class CorporateActionProvider(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    def fetch_corporate_actions(
        self, symbol: str, start_date: date, end_date: date
    ) -> CorporateActionSeries: ...


class SecurityReferenceProvider(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    def fetch_security_metadata(self, symbol: str) -> SecurityMetadata: ...
