from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class SecurityMetadata:
    symbol: str
    name: str
    exchange: str
    instrument_type: str
    currency: str
    exchange_timezone: str


@dataclass(frozen=True)
class DailyPriceBar:
    trading_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int


@dataclass(frozen=True)
class DailyPriceSeries:
    security: SecurityMetadata
    provider: str
    adjustment_mode: str
    bars: tuple[DailyPriceBar, ...]
