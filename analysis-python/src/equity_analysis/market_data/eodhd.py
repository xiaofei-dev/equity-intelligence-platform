import json
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from email.message import Message
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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
from equity_analysis.provider_validation.models import (
    FinancialRecordDiagnostic,
    HistoricalMarketValueObservation,
    NormalizedFinancialObservation,
    ProviderFieldMappingDiagnostic,
    ProviderRequestMetric,
)

EODHD_BASE_URL = "https://eodhd.com/api"
EODHD_DESCRIPTOR = ProviderDescriptor(
    code="eodhd",
    name="EODHD",
    provider_schema_version="eodhd-api-v1",
    parser_version="eodhd-parser-v1.3.0",
    capabilities=frozenset(
        {
            ProviderCapability.DAILY_PRICES,
            ProviderCapability.CORPORATE_ACTIONS,
            ProviderCapability.SECURITY_METADATA,
        }
    ),
    use_classification=ProviderUseClassification.DOCUMENTED_CANDIDATE,
)

EODHD_FINANCIAL_FIELD_MAP = {
    "totalRevenue": "revenue",
    "operatingIncome": "operating_income",
    "grossProfit": "gross_profit",
    "ebitda": "ebitda",
    "EBITDA": "ebitda",
    "interestExpense": "interest_expense",
    "interestExpenseNonOperating": "interest_expense",
    "netIncome": "net_income",
    "incomeTaxExpense": "income_tax",
    "incomeBeforeTax": "pretax_income",
    "totalAssets": "total_assets",
    "totalLiab": "total_liabilities",
    "totalStockholderEquity": "stockholders_equity",
    "cash": "cash_and_equivalents",
    "cashAndEquivalents": "cash_and_equivalents",
    "shortLongTermDebtTotal": "total_debt",
    "longTermDebt": "long_term_debt",
    "totalCashFromOperatingActivities": "operating_cash_flow",
    "capitalExpenditures": "capital_expenditure",
    "commonStockSharesOutstanding": "shares_outstanding",
    "weightedAverageShsOutDil": "diluted_weighted_average_shares",
    "dilutedWeightedAverageShares": "diluted_weighted_average_shares",
    "weightedAverageSharesDiluted": "diluted_weighted_average_shares",
}
EODHD_FINANCIAL_FIELD_PRIORITY = {
    "revenue": ("totalRevenue",),
    "operating_income": ("operatingIncome",),
    "gross_profit": ("grossProfit",),
    "ebitda": ("ebitda", "EBITDA"),
    "interest_expense": ("interestExpense", "interestExpenseNonOperating"),
    "net_income": ("netIncome",),
    "income_tax": ("incomeTaxExpense",),
    "pretax_income": ("incomeBeforeTax",),
    "total_assets": ("totalAssets",),
    "total_liabilities": ("totalLiab",),
    "stockholders_equity": ("totalStockholderEquity",),
    "cash_and_equivalents": ("cash", "cashAndEquivalents"),
    "total_debt": ("shortLongTermDebtTotal",),
    "long_term_debt": ("longTermDebt",),
    "operating_cash_flow": ("totalCashFromOperatingActivities",),
    "capital_expenditure": ("capitalExpenditures",),
    "shares_outstanding": ("commonStockSharesOutstanding",),
    "diluted_weighted_average_shares": (
        "weightedAverageShsOutDil",
        "dilutedWeightedAverageShares",
        "weightedAverageSharesDiluted",
    ),
}
EODHD_ENDPOINT_WEIGHTS = {
    "fundamentals": 10,
    "eod": 1,
    "div": 1,
    "splits": 1,
    "historical-market-cap": 1,
}


class EodhdProvider:
    def __init__(
        self,
        api_key: str,
        opener: Callable[..., Any] = urlopen,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        sleeper: Callable[[float], None] = time.sleep,
        request_observer: Callable[[ProviderRequestMetric], None] | None = None,
        request_authorizer: Callable[[int], None] | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("EODHD API key is required")
        if max_retries < 0:
            raise ValueError("Maximum retries cannot be negative")
        self._api_key = api_key
        self._opener = opener
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._sleeper = sleeper
        self._request_observer = request_observer
        self._request_authorizer = request_authorizer
        self._fundamentals_cache: dict[str, dict[str, Any]] = {}
        self._financial_diagnostics: dict[
            str, tuple[FinancialRecordDiagnostic, ...]
        ] = {}

    @property
    def descriptor(self) -> ProviderDescriptor:
        return EODHD_DESCRIPTOR

    @staticmethod
    def map_symbol(symbol: str) -> str:
        normalized = symbol.strip().upper()
        return normalized if "." in normalized else f"{normalized}.US"

    def fetch_daily_prices(
        self, symbol: str, start_date: date, end_date: date
    ) -> DailyPriceSeries:
        requested = symbol.strip().upper()
        provider_symbol = self.map_symbol(requested)
        payload = self._request(
            f"eod/{provider_symbol}",
            {"from": start_date.isoformat(), "to": end_date.isoformat(), "period": "d"},
        )
        if not isinstance(payload, list) or not payload:
            raise MarketDataProviderError(
                f"EODHD returned no daily prices for {requested}", "EMPTY_RESULT"
            )
        try:
            bars = tuple(
                DailyPriceBar(
                    trading_date=date.fromisoformat(str(item["date"])),
                    open_price=Decimal(str(item["open"])),
                    high_price=Decimal(str(item["high"])),
                    low_price=Decimal(str(item["low"])),
                    close_price=Decimal(str(item["close"])),
                    adjusted_close=(
                        Decimal(str(item["adjusted_close"]))
                        if item.get("adjusted_close") is not None
                        else None
                    ),
                    volume=int(item["volume"]),
                )
                for item in payload
            )
            for bar in bars:
                self._validate_bar(bar)
        except (KeyError, TypeError, ValueError, InvalidOperation) as error:
            raise MarketDataProviderError(
                f"EODHD returned malformed prices for {requested}", "MALFORMED_RESPONSE"
            ) from error
        now = datetime.now(UTC)
        return DailyPriceSeries(
            security=self.fetch_security_metadata(requested),
            provider_descriptor=self.descriptor,
            requested_symbol=requested,
            provider_symbol=provider_symbol,
            adjustment_mode=AdjustmentMode.TOTAL_RETURN_ADJUSTED,
            bars=bars,
            source_reference=f"eodhd:eod:{provider_symbol}",
            available_at=now,
            retrieved_at=now,
        )

    def fetch_security_metadata(self, symbol: str) -> SecurityMetadata:
        requested = symbol.strip().upper()
        provider_symbol = self.map_symbol(requested)
        payload = self._fundamentals(provider_symbol)
        if not isinstance(payload, dict):
            raise MarketDataProviderError(
                f"EODHD returned malformed metadata for {requested}", "MALFORMED_RESPONSE"
            )
        general = payload.get("General", payload)
        if not isinstance(general, dict):
            raise MarketDataProviderError(
                f"EODHD returned malformed metadata for {requested}", "MALFORMED_RESPONSE"
            )
        return SecurityMetadata(
            symbol=requested,
            name=str(general.get("Name") or requested),
            exchange=str(general.get("Exchange") or "UNKNOWN"),
            instrument_type=str(general.get("Type") or "UNKNOWN").upper().replace(" ", "_"),
            currency=str(general.get("CurrencyCode") or "USD").upper(),
            exchange_timezone=str(general.get("ExchangeTimezoneName") or "America/New_York"),
        )

    def fetch_corporate_actions(
        self, symbol: str, start_date: date, end_date: date
    ) -> CorporateActionSeries:
        requested = symbol.strip().upper()
        provider_symbol = self.map_symbol(requested)
        parameters = {"from": start_date.isoformat(), "to": end_date.isoformat()}
        dividends = self._request(f"div/{provider_symbol}", parameters)
        splits = self._request(f"splits/{provider_symbol}", parameters)
        try:
            actions = [
                CorporateAction(
                    action_type="DIVIDEND",
                    effective_date=date.fromisoformat(str(item["date"])),
                    amount=Decimal(str(item["value"])),
                    currency=str(item.get("currency") or "USD").upper(),
                )
                for item in self._as_list(dividends)
            ]
            actions.extend(
                CorporateAction(
                    action_type="SPLIT",
                    effective_date=date.fromisoformat(str(item["date"])),
                    split_from=self._split_ratio(item["split"])[0],
                    split_to=self._split_ratio(item["split"])[1],
                )
                for item in self._as_list(splits)
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as error:
            raise MarketDataProviderError(
                f"EODHD returned malformed corporate actions for {requested}",
                "MALFORMED_RESPONSE",
            ) from error
        now = datetime.now(UTC)
        return CorporateActionSeries(
            provider_descriptor=self.descriptor,
            requested_symbol=requested,
            provider_symbol=provider_symbol,
            actions=tuple(actions),
            source_reference=f"eodhd:corporate-actions:{provider_symbol}",
            available_at=now,
        )

    def fetch_financial_statements(
        self, symbol: str
    ) -> tuple[NormalizedFinancialObservation, ...]:
        requested = symbol.strip().upper()
        provider_symbol = self.map_symbol(requested)
        payload = self._fundamentals(provider_symbol)
        if not isinstance(payload, dict):
            raise MarketDataProviderError(
                f"EODHD returned malformed fundamentals for {requested}",
                "MALFORMED_RESPONSE",
            )
        financials = payload.get("Financials")
        if not isinstance(financials, dict):
            raise MarketDataProviderError(
                f"EODHD returned no financial statements for {requested}",
                "MISSING_FUNDAMENTALS",
            )
        now = datetime.now(UTC)
        observations: list[NormalizedFinancialObservation] = []
        diagnostics: list[FinancialRecordDiagnostic] = []
        statement_names = {
            "Income_Statement": "INCOME_STATEMENT",
            "Balance_Sheet": "BALANCE_SHEET",
            "Cash_Flow": "CASH_FLOW",
        }
        try:
            for provider_statement, statement_type in statement_names.items():
                statement = financials.get(provider_statement, {})
                if not isinstance(statement, dict):
                    raise TypeError("statement must be an object")
                for provider_period, period_type in (
                    ("yearly", "ANNUAL"),
                    ("quarterly", "QUARTERLY"),
                ):
                    records = statement.get(provider_period, {})
                    if not isinstance(records, dict):
                        raise TypeError("period collection must be an object")
                    for record in records.values():
                        if not isinstance(record, dict):
                            raise TypeError("financial record must be an object")
                        period_end = date.fromisoformat(str(record["date"]))
                        currency = str(record.get("currency_symbol") or "USD").upper()
                        values = self._normalized_financial_values(record)
                        canonical = {
                            "symbol": requested,
                            "providerSymbol": provider_symbol,
                            "statementType": statement_type,
                            "periodType": period_type,
                            "fiscalPeriodEnd": period_end.isoformat(),
                            "currency": currency,
                            "values": {
                                key: str(value) if value is not None else None
                                for key, value in sorted(values.items())
                            },
                        }
                        observations.append(
                            NormalizedFinancialObservation(
                                symbol=requested,
                                provider_symbol=provider_symbol,
                                statement_type=statement_type,
                                period_type=period_type,
                                fiscal_period_end=period_end,
                                currency=currency,
                                values=values,
                                source_reference=(
                                    f"eodhd:fundamentals:{provider_symbol}:{provider_period}"
                                ),
                                content_hash=self._canonical_hash(canonical),
                                provider_schema_version=(
                                    self.descriptor.provider_schema_version
                                ),
                                parser_version=self.descriptor.parser_version,
                                effective_at=datetime.combine(
                                    period_end, datetime.min.time(), tzinfo=UTC
                                ),
                                ingested_at=now,
                            )
                        )
                        mapped_fields = tuple(
                            ProviderFieldMappingDiagnostic(
                                provider_field=provider_field,
                                normalized_field=normalized,
                                presence=(
                                    "PRESENT_NULL"
                                    if record[provider_field] in (None, "", "NA", "None")
                                    else "PRESENT_NONNULL"
                                ),
                            )
                            for provider_field, normalized in sorted(
                                EODHD_FINANCIAL_FIELD_MAP.items()
                            )
                            if provider_field in record
                        )
                        diagnostics.append(
                            FinancialRecordDiagnostic(
                                statement_type=statement_type,
                                period_type=period_type,
                                fiscal_period_end=period_end,
                                source_reference=(
                                    f"eodhd:fundamentals:{provider_symbol}:{provider_period}"
                                ),
                                content_hash=self._canonical_hash(canonical),
                                provider_fields_observed=tuple(sorted(record)),
                                mapped_fields=mapped_fields,
                                provider_fields_present_but_null=tuple(
                                    item.provider_field
                                    for item in mapped_fields
                                    if item.presence == "PRESENT_NULL"
                                ),
                            )
                        )
        except (InvalidOperation, KeyError, TypeError, ValueError) as error:
            raise MarketDataProviderError(
                f"EODHD returned malformed fundamentals for {requested}",
                "MALFORMED_RESPONSE",
            ) from error
        if not observations:
            raise MarketDataProviderError(
                f"EODHD returned no financial statements for {requested}",
                "MISSING_FUNDAMENTALS",
            )
        self._financial_diagnostics[requested] = tuple(
            sorted(
                diagnostics,
                key=lambda item: (
                    item.fiscal_period_end,
                    item.period_type,
                    item.statement_type,
                ),
            )
        )
        return tuple(
            sorted(
                observations,
                key=lambda item: (
                    item.fiscal_period_end,
                    item.period_type,
                    item.statement_type,
                ),
            )
        )

    def financial_diagnostics(
        self, symbol: str
    ) -> tuple[FinancialRecordDiagnostic, ...]:
        return self._financial_diagnostics.get(symbol.strip().upper(), ())

    @classmethod
    def _normalized_financial_values(
        cls, record: dict[str, Any]
    ) -> dict[str, Decimal | None]:
        values: dict[str, Decimal | None] = {}
        for normalized_field, provider_fields in EODHD_FINANCIAL_FIELD_PRIORITY.items():
            present_fields = tuple(
                provider_field
                for provider_field in provider_fields
                if provider_field in record
            )
            if not present_fields:
                continue
            resolved_value = None
            for provider_field in present_fields:
                candidate = cls._optional_decimal(record[provider_field])
                if candidate is not None:
                    resolved_value = candidate
                    break
            values[normalized_field] = resolved_value
        return values

    def fetch_historical_market_cap(
        self, symbol: str, start_date: date, end_date: date
    ) -> tuple[HistoricalMarketValueObservation, ...]:
        requested = symbol.strip().upper()
        provider_symbol = self.map_symbol(requested)
        payload = self._request(
            f"historical-market-cap/{provider_symbol}",
            {"from": start_date.isoformat(), "to": end_date.isoformat()},
        )
        if isinstance(payload, dict):
            payload = payload.get("data", list(payload.values()))
        if not isinstance(payload, list) or not payload:
            raise MarketDataProviderError(
                f"EODHD returned no historical market capitalization for {requested}",
                "MISSING_HISTORICAL_MARKET_VALUE",
            )
        now = datetime.now(UTC)
        try:
            observations = []
            for item in payload:
                effective_at = date.fromisoformat(str(item["date"]))
                value = Decimal(
                    str(
                        item.get("market_cap")
                        or item.get("marketCap")
                        or item.get("value")
                    )
                )
                if value <= 0:
                    raise ValueError("market capitalization must be positive")
                canonical = {
                    "symbol": requested,
                    "providerSymbol": provider_symbol,
                    "effectiveAt": effective_at.isoformat(),
                    "marketCapitalization": str(value),
                }
                observations.append(
                    HistoricalMarketValueObservation(
                        symbol=requested,
                        provider_symbol=provider_symbol,
                        effective_at=effective_at,
                        market_capitalization=value,
                        source_reference=f"eodhd:historical-market-cap:{provider_symbol}",
                        content_hash=self._canonical_hash(canonical),
                        provider_schema_version=self.descriptor.provider_schema_version,
                        parser_version=self.descriptor.parser_version,
                        ingested_at=now,
                    )
                )
        except (InvalidOperation, KeyError, TypeError, ValueError) as error:
            raise MarketDataProviderError(
                f"EODHD returned malformed historical market capitalization for {requested}",
                "MALFORMED_RESPONSE",
            ) from error
        return tuple(observations)

    def _request(self, endpoint: str, parameters: dict[str, Any]) -> Any:
        query = urlencode({**parameters, "api_token": self._api_key, "fmt": "json"})
        request = Request(
            f"{EODHD_BASE_URL}/{endpoint}?{query}",
            headers={
                "Accept": "application/json",
                "User-Agent": "equity-intelligence-platform/0.1",
            },
        )
        for attempt in range(self._max_retries + 1):
            endpoint_category = endpoint.split("/", 1)[0]
            if self._request_authorizer is not None:
                self._request_authorizer(
                    EODHD_ENDPOINT_WEIGHTS.get(endpoint_category, 1)
                )
            started_at = time.monotonic()
            try:
                with self._opener(request, timeout=self._timeout_seconds) as response:
                    payload = json.load(response)
                    self._observe_request(
                        endpoint, attempt + 1, "SUCCESS", started_at
                    )
                    return payload
            except HTTPError as error:
                self._observe_request(
                    endpoint,
                    attempt + 1,
                    "RETRY" if (
                        (error.code == 429 or 500 <= error.code < 600)
                        and attempt < self._max_retries
                    ) else "FAILED",
                    started_at,
                    "RATE_LIMITED" if error.code == 429 else f"HTTP_{error.code}",
                )
                if error.code == 429 or 500 <= error.code < 600:
                    if attempt < self._max_retries:
                        self._sleeper(self._retry_delay(attempt, error.headers))
                        continue
                code = "RATE_LIMITED" if error.code == 429 else f"HTTP_{error.code}"
                raise MarketDataProviderError("EODHD request was rejected", code) from None
            except (OSError, TimeoutError, json.JSONDecodeError):
                self._observe_request(
                    endpoint,
                    attempt + 1,
                    "RETRY" if attempt < self._max_retries else "FAILED",
                    started_at,
                    "EODHD_REQUEST_FAILED",
                )
                if attempt < self._max_retries:
                    self._sleeper(2**attempt)
                    continue
                raise MarketDataProviderError(
                    "EODHD request failed", "EODHD_REQUEST_FAILED"
                ) from None
        raise AssertionError("Retry loop did not terminate")

    def _fundamentals(self, provider_symbol: str) -> dict[str, Any]:
        cached = self._fundamentals_cache.get(provider_symbol)
        if cached is not None:
            return cached
        payload = self._request(f"fundamentals/{provider_symbol}", {})
        if not isinstance(payload, dict):
            raise MarketDataProviderError(
                f"EODHD returned malformed fundamentals for {provider_symbol}",
                "MALFORMED_RESPONSE",
            )
        self._fundamentals_cache[provider_symbol] = payload
        return payload

    def _observe_request(
        self,
        endpoint: str,
        attempt: int,
        status: str,
        started_at: float,
        error_code: str | None = None,
    ) -> None:
        if self._request_observer is None:
            return
        endpoint_category = endpoint.split("/", 1)[0]
        self._request_observer(
            ProviderRequestMetric(
                provider="eodhd",
                endpoint_category=endpoint_category,
                attempt=attempt,
                status=status,
                duration_ms=max(int((time.monotonic() - started_at) * 1000), 0),
                weighted_calls=EODHD_ENDPOINT_WEIGHTS.get(endpoint_category, 1),
                error_code=error_code,
            )
        )

    @staticmethod
    def _optional_decimal(value: Any) -> Decimal | None:
        if value in (None, "", "NA", "None"):
            return None
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError("financial value must be finite")
        return result

    @staticmethod
    def _canonical_hash(value: dict[str, Any]) -> str:
        from hashlib import sha256

        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return sha256(payload).hexdigest()

    @staticmethod
    def _retry_delay(attempt: int, headers: Message | None) -> float:
        if headers is not None:
            value = headers.get("Retry-After")
            if value:
                try:
                    return max(float(value), 0.0)
                except ValueError:
                    pass
        return float(2**attempt)

    @staticmethod
    def _as_list(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            raise ValueError("expected a list")
        return payload

    @staticmethod
    def _split_ratio(value: Any) -> tuple[Decimal, Decimal]:
        left, right = str(value).replace("/", ":").split(":", 1)
        # EODHD expresses the ratio as new shares to old shares.
        return Decimal(right), Decimal(left)

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
