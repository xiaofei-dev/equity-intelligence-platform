import math
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from equity_analysis.market_data.models import (
    AdjustmentMode,
    CorporateAction,
    CorporateActionSeries,
    DailyPriceBar,
    DailyPriceSeries,
    ProviderCapability,
    ProviderDescriptor,
    ProviderUseClassification,
    SecurityMetadata,
)
from equity_analysis.market_data.provider import MarketDataProviderError

YFINANCE_DESCRIPTOR = ProviderDescriptor(
    code="yfinance",
    name="Yahoo Finance via yfinance",
    provider_schema_version="yfinance-download-v1",
    parser_version="yfinance-parser-v1.0.0",
    capabilities=frozenset(
        {
            ProviderCapability.DAILY_PRICES,
            ProviderCapability.CORPORATE_ACTIONS,
            ProviderCapability.SECURITY_METADATA,
        }
    ),
    use_classification=ProviderUseClassification.DEVELOPMENT_FALLBACK,
)


class YFinanceProvider:
    def __init__(
        self,
        downloader: Callable[..., Any] | None = None,
        ticker_factory: Callable[[str], Any] | None = None,
    ) -> None:
        if downloader is None or ticker_factory is None:
            try:
                import yfinance as yf
            except ImportError as error:
                raise ValueError("yfinance is required for the yfinance provider") from error
            downloader = downloader or yf.download
            ticker_factory = ticker_factory or yf.Ticker
        self._downloader = downloader
        self._ticker_factory = ticker_factory

    @property
    def descriptor(self) -> ProviderDescriptor:
        return YFINANCE_DESCRIPTOR

    def fetch_daily_prices(
        self, symbol: str, start_date: date, end_date: date
    ) -> DailyPriceSeries:
        requested_symbol = symbol.strip().upper()
        try:
            frame = self._downloader(
                requested_symbol,
                start=start_date.isoformat(),
                end=(end_date + timedelta(days=1)).isoformat(),
                auto_adjust=False,
                actions=False,
                progress=False,
                threads=False,
            )
        except Exception as error:
            raise MarketDataProviderError(
                f"yfinance request failed for {requested_symbol}", "YFINANCE_REQUEST_FAILED"
            ) from error
        if getattr(frame, "empty", True):
            raise MarketDataProviderError(
                f"yfinance returned no daily prices for {requested_symbol}",
                "EMPTY_RESULT",
            )

        columns = self._column_map(tuple(frame.columns), requested_symbol)
        required = ("Open", "High", "Low", "Close", "Volume")
        if any(name not in columns for name in required):
            raise MarketDataProviderError(
                f"yfinance returned malformed prices for {requested_symbol}",
                "MALFORMED_RESPONSE",
            )
        bars = []
        rejected_bar_count = 0
        try:
            for index, row in frame.iterrows():
                values = {name: row[column] for name, column in columns.items()}
                volume_value = values["Volume"]
                numeric_values = tuple(
                    values[name] for name in required if name != "Volume"
                ) + (volume_value,)
                if any(self._is_missing(value) for value in numeric_values):
                    rejected_bar_count += 1
                    continue
                trading_date = (
                    index.date()
                    if hasattr(index, "date")
                    else date.fromisoformat(str(index))
                )
                bar = DailyPriceBar(
                    trading_date=trading_date,
                    open_price=Decimal(str(values["Open"])),
                    high_price=Decimal(str(values["High"])),
                    low_price=Decimal(str(values["Low"])),
                    close_price=Decimal(str(values["Close"])),
                    volume=int(volume_value),
                    adjusted_close=(
                        None
                        if "Adj Close" not in values or self._is_missing(values["Adj Close"])
                        else Decimal(str(values["Adj Close"]))
                    ),
                )
                self._validate_bar(bar)
                bars.append(bar)
        except (InvalidOperation, TypeError, ValueError, OverflowError) as error:
            raise MarketDataProviderError(
                f"yfinance returned malformed prices for {requested_symbol}",
                "MALFORMED_RESPONSE",
            ) from error
        if not bars:
            raise MarketDataProviderError(
                f"yfinance returned no daily prices for {requested_symbol}", "EMPTY_RESULT"
            )
        now = datetime.now(UTC)
        return DailyPriceSeries(
            security=self.fetch_security_metadata(requested_symbol),
            provider_descriptor=self.descriptor,
            requested_symbol=requested_symbol,
            provider_symbol=requested_symbol,
            adjustment_mode=(
                AdjustmentMode.TOTAL_RETURN_ADJUSTED
                if any(bar.adjusted_close is not None for bar in bars)
                else AdjustmentMode.UNADJUSTED
            ),
            bars=tuple(bars),
            source_reference=f"yfinance:download:{requested_symbol}",
            available_at=now,
            retrieved_at=now,
            rejected_bar_count=rejected_bar_count,
        )

    def fetch_security_metadata(self, symbol: str) -> SecurityMetadata:
        normalized = symbol.strip().upper()
        try:
            ticker = self._ticker_factory(normalized)
            info = getattr(ticker, "fast_info", {}) or {}
            details = getattr(ticker, "info", {}) or {}
        except Exception as error:
            raise MarketDataProviderError(
                f"yfinance metadata request failed for {normalized}",
                "YFINANCE_METADATA_FAILED",
            ) from error
        return SecurityMetadata(
            symbol=normalized,
            name=str(details.get("longName") or details.get("shortName") or normalized),
            exchange=str(details.get("exchange") or info.get("exchange") or "UNKNOWN"),
            instrument_type=str(details.get("quoteType") or "UNKNOWN").upper(),
            currency=str(details.get("currency") or info.get("currency") or "USD").upper(),
            exchange_timezone=str(
                details.get("exchangeTimezoneName") or "America/New_York"
            ),
        )

    def fetch_corporate_actions(
        self, symbol: str, start_date: date, end_date: date
    ) -> CorporateActionSeries:
        normalized = symbol.strip().upper()
        try:
            actions = self._ticker_factory(normalized).actions
            parsed = []
            for index, row in actions.iterrows():
                action_date = (
                    index.date()
                    if hasattr(index, "date")
                    else date.fromisoformat(str(index))
                )
                if not start_date <= action_date <= end_date:
                    continue
                dividend = row.get("Dividends")
                split = row.get("Stock Splits")
                if not self._is_missing(dividend) and Decimal(str(dividend)) != 0:
                    parsed.append(
                        CorporateAction(
                            action_type="DIVIDEND",
                            effective_date=action_date,
                            amount=Decimal(str(dividend)),
                            currency="USD",
                        )
                    )
                if not self._is_missing(split) and Decimal(str(split)) != 0:
                    parsed.append(
                        CorporateAction(
                            action_type="SPLIT",
                            effective_date=action_date,
                            split_from=Decimal("1"),
                            split_to=Decimal(str(split)),
                        )
                    )
        except Exception as error:
            raise MarketDataProviderError(
                f"yfinance corporate-action request failed for {normalized}",
                "YFINANCE_ACTIONS_FAILED",
            ) from error
        now = datetime.now(UTC)
        return CorporateActionSeries(
            provider_descriptor=self.descriptor,
            requested_symbol=normalized,
            provider_symbol=normalized,
            actions=tuple(parsed),
            source_reference=f"yfinance:actions:{normalized}",
            available_at=now,
        )

    @staticmethod
    def _column_map(columns: tuple[Any, ...], symbol: str) -> dict[str, Any]:
        result = {}
        expected = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
        for column in columns:
            if isinstance(column, tuple):
                names = tuple(str(part) for part in column)
                field = next((part for part in names if part in expected), None)
                ticker = next((part for part in names if part.upper() == symbol), None)
                if field and (ticker or len(names) == 1):
                    result[field] = column
            elif str(column) in expected:
                result[str(column)] = column
        return result

    @staticmethod
    def _is_missing(value: Any) -> bool:
        return value is None or (isinstance(value, float) and math.isnan(value))

    @staticmethod
    def _validate_bar(bar: DailyPriceBar) -> None:
        if bar.volume < 0 or min(
            bar.open_price, bar.high_price, bar.low_price, bar.close_price
        ) < 0:
            raise ValueError("negative market value")
        if (
            bar.high_price < max(bar.open_price, bar.low_price, bar.close_price)
            or bar.low_price > min(bar.open_price, bar.high_price, bar.close_price)
        ):
            raise ValueError("invalid OHLC range")
