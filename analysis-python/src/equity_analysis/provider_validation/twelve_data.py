import json
import time
from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from equity_analysis.provider_validation.models import (
    CorporateActionSummary,
    PriceSummary,
)

TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"


class TwelveDataValidationError(RuntimeError):
    """Raised when Twelve Data cannot return a usable acceptance response."""


class TwelveDataValidationClient:
    def __init__(
        self,
        api_key: str,
        opener: Callable[..., Any] = urlopen,
        timeout_seconds: float = 20.0,
        minimum_request_interval_seconds: float = 0.0,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Twelve Data API key is required")
        if minimum_request_interval_seconds < 0:
            raise ValueError("Minimum request interval cannot be negative")
        self._api_key = api_key
        self._opener = opener
        self._timeout_seconds = timeout_seconds
        self._minimum_request_interval_seconds = minimum_request_interval_seconds
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._last_request_started_at: float | None = None

    def fetch_price_summary(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> PriceSummary:
        payload = self._request(
            "time_series",
            {
                "symbol": symbol.upper(),
                "interval": "1day",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "order": "ASC",
                "adjust": "all",
                "outputsize": 5000,
            },
        )
        values = payload.get("values")
        meta = payload.get("meta", {})
        if not isinstance(values, list) or not values:
            raise TwelveDataValidationError(
                f"Twelve Data returned no daily prices for {symbol.upper()}"
            )
        try:
            dates = tuple(date.fromisoformat(str(item["datetime"])) for item in values)
            return PriceSummary(
                symbol=str(meta.get("symbol", symbol)).upper(),
                adjustment_mode="all",
                observation_count=len(values),
                first_date=min(dates),
                last_date=max(dates),
                exchange=str(meta["exchange"]),
                instrument_type=str(meta["type"]).upper().replace(" ", "_"),
                currency=str(meta["currency"]).upper(),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise TwelveDataValidationError(
                f"Twelve Data returned malformed prices for {symbol.upper()}"
            ) from error

    def fetch_splits_summary(self, symbol: str) -> CorporateActionSummary:
        payload = self._request("splits", {"symbol": symbol.upper(), "range": "full"})
        return self._parse_actions(symbol, "split", payload.get("splits"), "date")

    def fetch_dividends_summary(self, symbol: str) -> CorporateActionSummary:
        payload = self._request(
            "dividends",
            {"symbol": symbol.upper(), "range": "full", "adjust": "false"},
        )
        return self._parse_actions(symbol, "dividend", payload.get("dividends"), "ex_date")

    def _request(self, endpoint: str, parameters: dict[str, Any]) -> dict[str, Any]:
        self._wait_for_request_slot()
        query = urlencode(parameters)
        request = Request(
            f"{TWELVE_DATA_BASE_URL}/{endpoint}?{query}",
            headers={
                "Accept": "application/json",
                "Authorization": f"apikey {self._api_key}",
                "User-Agent": "equity-intelligence-platform/0.1",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                payload = json.load(response)
        except HTTPError as error:
            try:
                payload = json.load(error)
                message = str(payload.get("message", f"HTTP {error.code}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                message = f"HTTP {error.code}"
            raise TwelveDataValidationError(
                f"Twelve Data {endpoint} rejected the request: {message}"
            ) from error
        except (OSError, TimeoutError, json.JSONDecodeError) as error:
            raise TwelveDataValidationError(
                f"Twelve Data {endpoint} request failed"
            ) from error
        if not isinstance(payload, dict):
            raise TwelveDataValidationError(
                f"Twelve Data {endpoint} returned a non-object response"
            )
        if payload.get("status") == "error" or payload.get("code"):
            message = str(payload.get("message", "provider error"))
            raise TwelveDataValidationError(
                f"Twelve Data {endpoint} rejected the request: {message}"
            )
        return payload

    def _wait_for_request_slot(self) -> None:
        now = self._monotonic()
        if self._last_request_started_at is not None:
            elapsed = now - self._last_request_started_at
            remaining = self._minimum_request_interval_seconds - elapsed
            if remaining > 0:
                self._sleeper(remaining)
                now = self._monotonic()
        self._last_request_started_at = now

    @staticmethod
    def _parse_actions(
        symbol: str,
        action_type: str,
        values: Any,
        date_field: str,
    ) -> CorporateActionSummary:
        if not isinstance(values, list):
            raise TwelveDataValidationError(
                f"Twelve Data returned malformed {action_type} history for {symbol.upper()}"
            )
        try:
            dates = tuple(date.fromisoformat(str(item[date_field])) for item in values)
        except (KeyError, TypeError, ValueError) as error:
            raise TwelveDataValidationError(
                f"Twelve Data returned malformed {action_type} dates for {symbol.upper()}"
            ) from error
        return CorporateActionSummary(
            symbol=symbol.upper(),
            action_type=action_type,
            observation_count=len(dates),
            first_date=min(dates) if dates else None,
            last_date=max(dates) if dates else None,
        )
