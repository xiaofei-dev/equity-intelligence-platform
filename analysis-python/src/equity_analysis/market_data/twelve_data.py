import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from equity_analysis.market_data.models import (
    AdjustmentMode,
    DailyPriceBar,
    DailyPriceSeries,
    ProviderCapability,
    ProviderDescriptor,
    ProviderUseClassification,
    SecurityMetadata,
)
from equity_analysis.market_data.provider import MarketDataProviderError

TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"
PROVIDER_NAME = "twelve_data"
ADJUSTMENT_MODE = AdjustmentMode.SPLIT_ADJUSTED
TWELVE_DATA_DESCRIPTOR = ProviderDescriptor(
    code=PROVIDER_NAME,
    name="Twelve Data",
    provider_schema_version="time-series-v1",
    parser_version="twelve-data-time-series-v1.1.0",
    capabilities=frozenset(
        {
            ProviderCapability.DAILY_PRICES,
            ProviderCapability.CORPORATE_ACTIONS,
            ProviderCapability.SECURITY_METADATA,
        }
    ),
    use_classification=ProviderUseClassification.VALIDATED_LIMITED,
)


class TwelveDataClient:
    def __init__(
        self,
        api_key: str,
        opener: Callable[..., Any] = urlopen,
        timeout_seconds: float = 15.0,
    ) -> None:
        if not api_key:
            raise ValueError("Twelve Data API key is required")
        self._api_key = api_key
        self._opener = opener
        self._timeout_seconds = timeout_seconds

    @property
    def descriptor(self) -> ProviderDescriptor:
        return TWELVE_DATA_DESCRIPTOR

    def fetch_daily_prices(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> DailyPriceSeries:
        normalized_symbol = symbol.strip().upper()
        query = urlencode(
            {
                "symbol": normalized_symbol,
                "interval": "1day",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "order": "ASC",
                "adjust": "splits",
                "outputsize": 5000,
            }
        )
        request = Request(
            f"{TWELVE_DATA_BASE_URL}/time_series?{query}",
            headers={
                "Authorization": f"apikey {self._api_key}",
                "Accept": "application/json",
                "User-Agent": "equity-intelligence-platform/0.1",
            },
        )

        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                payload = json.load(response)
        except (OSError, TimeoutError, json.JSONDecodeError) as error:
            raise MarketDataProviderError(
                f"Twelve Data request failed for {normalized_symbol}"
            ) from error

        return self._parse_response(normalized_symbol, payload)

    def _parse_response(self, symbol: str, payload: dict[str, Any]) -> DailyPriceSeries:
        if payload.get("status") == "error" or "values" not in payload:
            provider_message = str(payload.get("message", "missing time-series values"))
            raise MarketDataProviderError(
                f"Twelve Data returned an error for {symbol}: {provider_message}"
            )

        meta = payload.get("meta", {})
        try:
            security = SecurityMetadata(
                symbol=str(meta.get("symbol", symbol)).upper(),
                name=str(meta.get("name", symbol)),
                exchange=str(meta["exchange"]),
                instrument_type=str(meta["type"]).upper().replace(" ", "_"),
                currency=str(meta["currency"]).upper(),
                exchange_timezone=str(meta["exchange_timezone"]),
            )
            bars = tuple(
                DailyPriceBar(
                    trading_date=date.fromisoformat(value["datetime"]),
                    open_price=Decimal(value["open"]),
                    high_price=Decimal(value["high"]),
                    low_price=Decimal(value["low"]),
                    close_price=Decimal(value["close"]),
                    volume=int(value["volume"]),
                )
                for value in payload["values"]
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as error:
            raise MarketDataProviderError(
                f"Twelve Data returned malformed data for {symbol}"
            ) from error

        if not bars:
            raise MarketDataProviderError(f"Twelve Data returned no daily prices for {symbol}")

        retrieved_at = datetime.now(UTC)
        return DailyPriceSeries(
            security=security,
            provider_descriptor=self.descriptor,
            requested_symbol=symbol,
            provider_symbol=security.symbol,
            adjustment_mode=ADJUSTMENT_MODE,
            bars=bars,
            source_reference=f"twelve-data:time-series:{security.symbol}",
            available_at=retrieved_at,
            retrieved_at=retrieved_at,
        )
