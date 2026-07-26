from datetime import date
from typing import Protocol

from equity_analysis.market_data.models import DailyPriceSeries


class MarketDataProviderError(RuntimeError):
    """Raised when a market data provider cannot return a valid response."""


class MarketDataProvider(Protocol):
    def fetch_daily_prices(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> DailyPriceSeries: ...
