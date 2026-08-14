"""Bounded current-price acquisition and assessment execution for three securities."""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, DecimalException
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

from equity_analysis.fundamental_value.current_assessment_v1 import (
    CONTRACT_VERSION as ASSESSMENT_CONTRACT_VERSION,
)
from equity_analysis.fundamental_value.current_assessment_v1 import (
    CurrentApplicabilitySealV1,
    CurrentCompletedSessionSealV1,
    CurrentFundamentalAssessmentV1,
    CurrentPriceSelectionSealV1,
    CurrentSourceSealV1,
    build_current_fundamental_assessment_v1,
    create_current_completed_session_seal_v1,
    current_fundamental_assessment_to_wire_v1,
    source_seal_from_bytes_v1,
)
from equity_analysis.fundamental_value.identity_projection_v2 import (
    ProjectedIdentityMemberV2,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    ProviderWireRequest,
    TransportResponse,
)
from equity_analysis.fundamental_value.prospective_company_quality_http_transport_v1 import (
    StdlibAcquisitionHttpTransport,
)
from equity_analysis.provider_validation.execution_safety import (
    ExecutionLease,
    PhysicalRequestJournal,
)

EXECUTION_VERSION = "FV-CURRENT-ASSESSMENT-EXECUTION-v1.0.0"
PRICE_NORMALIZATION_VERSION = "FV-CURRENT-YAHOO-PRICE-NORMALIZATION-v1.0.0"
TARGET_SYMBOLS = ("GOOG", "FOX", "MSFT")
PHYSICAL_REQUEST_CEILING = 3
RETRY_LIMIT = 0
_UPPER_HASH = re.compile(r"[0-9A-F]{64}\Z")
_LOWER_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_RUN_ID = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,127}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)


class CurrentAssessmentExecutionStop(RuntimeError):
    """Fail-closed execution stop with a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class YahooTransportV1(Protocol):
    def send(self, request: ProviderWireRequest) -> TransportResponse: ...


class CurrentEvidenceRegistrarV1(Protocol):
    def register(
        self,
        *,
        identity: ProjectedIdentityMemberV2,
        completed_session: CurrentCompletedSessionSealV1,
        fundamentals_raw: bytes,
        fundamentals_payload: dict[str, Any],
        fundamentals_source: CurrentSourceSealV1,
        price_raw: bytes,
        price_payload: dict[str, Any],
        price_source: CurrentSourceSealV1,
        decision_cutoff: datetime,
    ) -> tuple[CurrentApplicabilitySealV1, CurrentPriceSelectionSealV1]: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class CurrentEodhdPriceHttpTransportV1:
    """No-retry, no-proxy EODHD EOD transport for a sealed current-price plan."""

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        if type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= 120:
            raise ValueError("EODHD_PRICE_TIMEOUT_INVALID")
        self._timeout = float(timeout_seconds)

    def send(self, request: ProviderWireRequest) -> TransportResponse:
        key = os.environ.get("EODHD_API_KEY", "")
        if not key or len(key) > 512 or re.fullmatch(r"[A-Za-z0-9._~-]+", key) is None:
            raise CurrentAssessmentExecutionStop("EODHD_API_KEY_INVALID")
        if (
            type(request) is not ProviderWireRequest
            or request.provider != "EODHD"
            or request.method != "GET"
            or re.fullmatch(
                r"/api/eod/[A-Z0-9][A-Z0-9.-]{0,31}\.US\?fmt=json"
                r"&from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}&period=d",
                request.endpoint_path,
            )
            is None
            or request.headers != (("accept", "application/json"),)
            or request.body is not None
            or request.body_sha256 is not None
        ):
            raise CurrentAssessmentExecutionStop("EODHD_PRICE_WIRE_REQUEST_INVALID")
        url = "https://eodhd.com" + request.endpoint_path + "&api_token=" + quote(key, safe="")
        outgoing = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "equity-platform/0.1"},
            method="GET",
        )
        response: object | None = None
        try:
            opener = build_opener(ProxyHandler({}), _NoRedirect())
            try:
                response = opener.open(outgoing, timeout=self._timeout)
            except HTTPError as error:
                response = error
            status = int(getattr(response, "status", 0))
            if not 100 <= status <= 599 or not hasattr(response, "read"):
                raise CurrentAssessmentExecutionStop("EODHD_PRICE_RESPONSE_INVALID")
            if hasattr(response, "geturl") and response.geturl() != url:
                raise CurrentAssessmentExecutionStop("EODHD_PRICE_TARGET_DRIFT")
            body = response.read(20_000_001)
            if type(body) is not bytes or len(body) > 20_000_000:
                raise CurrentAssessmentExecutionStop("EODHD_PRICE_BODY_INVALID")
            if key.encode("ascii") in body:
                raise CurrentAssessmentExecutionStop("EODHD_SECRET_REFLECTION_BLOCKED")
            allowed = {
                "content-type",
                "date",
                "ratelimit-limit",
                "ratelimit-remaining",
                "ratelimit-reset",
                "retry-after",
            }
            headers = tuple(
                sorted(
                    (str(name).lower(), str(value).strip())
                    for name, value in response.headers.items()
                    if str(name).lower() in allowed
                )
            )
            if len({name for name, _value in headers}) != len(headers):
                raise CurrentAssessmentExecutionStop("EODHD_PRICE_HEADER_DUPLICATE")
            if any(key in name or key in value for name, value in headers):
                raise CurrentAssessmentExecutionStop("EODHD_SECRET_REFLECTION_BLOCKED")
            return TransportResponse(status, headers, body)
        except CurrentAssessmentExecutionStop:
            raise
        except (URLError, TimeoutError, ssl.SSLError, OSError):
            raise CurrentAssessmentExecutionStop("EODHD_PRICE_TRANSPORT_UNKNOWN") from None
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    close()


@dataclass(frozen=True)
class CurrentPriceRequestV1:
    ordinal: int
    symbol: str
    security_id: str
    company_id: str
    instrument_id: str
    share_class_id: str
    listing_id: str
    ticker_assignment_id: str
    mic: str
    currency: str
    endpoint_path: str
    request_identity: str


@dataclass(frozen=True)
class CurrentAssessmentExecutionPlanV1:
    run_id: str
    preflight_sealed_at: datetime
    start_date: date
    end_date: date
    identity_projection_content_hash: str
    requests: tuple[CurrentPriceRequestV1, ...]
    plan_hash: str
    price_provider: str = "YAHOO_CHART"
    network_authorized: bool = False
    retry_limit: int = RETRY_LIMIT
    physical_request_ceiling: int = PHYSICAL_REQUEST_CEILING


@dataclass(frozen=True)
class CurrentAssessmentExecutionResultV1:
    status: str
    run_id: str
    plan_hash: str
    assessment_hashes: tuple[str, ...]
    assessment_paths: tuple[str, ...]
    physical_requests: int
    replayed_requests: int
    manifest_path: str
    decision_cutoff: datetime


def _canonical(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None or value.microsecond:
            raise CurrentAssessmentExecutionStop("TIMESTAMP_BOUNDARY_INVALID")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if hasattr(value, "__dataclass_fields__"):
        return {key: _canonical(getattr(value, key)) for key in value.__dataclass_fields__}
    return value


def _hash(value: object) -> str:
    raw = json.dumps(
        _canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest().upper()


def _immutable_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(_canonical(value), indent=2, sort_keys=True) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != raw:
            raise CurrentAssessmentExecutionStop("IMMUTABLE_FILE_CONFLICT")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _plan_body(value: CurrentAssessmentExecutionPlanV1) -> dict[str, Any]:
    return {
        "executionVersion": EXECUTION_VERSION,
        "runId": value.run_id,
        "preflightSealedAt": value.preflight_sealed_at,
        "startDate": value.start_date,
        "endDate": value.end_date,
        "identityProjectionContentHash": value.identity_projection_content_hash,
        "requests": value.requests,
        "priceProvider": value.price_provider,
        "retryLimit": value.retry_limit,
        "physicalRequestCeiling": value.physical_request_ceiling,
        "networkAuthorized": value.network_authorized,
    }


def validate_current_assessment_execution_plan_v1(
    value: CurrentAssessmentExecutionPlanV1,
) -> None:
    if type(value) is not CurrentAssessmentExecutionPlanV1:
        raise CurrentAssessmentExecutionStop("EXECUTION_PLAN_TYPE_INVALID")
    if _SAFE_RUN_ID.fullmatch(value.run_id) is None:
        raise CurrentAssessmentExecutionStop("EXECUTION_RUN_ID_INVALID")
    if _LOWER_HASH.fullmatch(value.identity_projection_content_hash) is None:
        raise CurrentAssessmentExecutionStop("EXECUTION_PROJECTION_HASH_INVALID")
    if type(value.requests) is not tuple or len(value.requests) != PHYSICAL_REQUEST_CEILING:
        raise CurrentAssessmentExecutionStop("EXECUTION_REQUEST_COUNT_DRIFT")
    if tuple(item.symbol for item in value.requests) != TARGET_SYMBOLS:
        raise CurrentAssessmentExecutionStop("EXECUTION_SYMBOL_SET_DRIFT")
    if tuple(item.ordinal for item in value.requests) != (1, 2, 3):
        raise CurrentAssessmentExecutionStop("EXECUTION_REQUEST_ORDER_DRIFT")
    if len({item.request_identity for item in value.requests}) != len(value.requests):
        raise CurrentAssessmentExecutionStop("EXECUTION_REQUEST_IDENTITY_DUPLICATE")
    if value.retry_limit != 0 or value.physical_request_ceiling != 3:
        raise CurrentAssessmentExecutionStop("EXECUTION_BUDGET_DRIFT")
    if value.price_provider not in {"YAHOO_CHART", "EODHD_EOD"}:
        raise CurrentAssessmentExecutionStop("EXECUTION_PRICE_PROVIDER_INVALID")
    if value.start_date > value.end_date or value.end_date != value.preflight_sealed_at.date():
        raise CurrentAssessmentExecutionStop("EXECUTION_DATE_RANGE_DRIFT")
    for item in value.requests:
        expected_path = (
            (
                f"/v8/finance/chart/{item.symbol}?range=10d&interval=1d&events=div%2Csplits"
                "&includeAdjustedClose=true"
            )
            if value.price_provider == "YAHOO_CHART"
            else (
                f"/api/eod/{item.symbol}.US?fmt=json&from={value.start_date.isoformat()}"
                f"&to={value.end_date.isoformat()}&period=d"
            )
        )
        if (
            item.mic not in {"XNAS", "XNYS"}
            or item.currency != "USD"
            or any(
                _UUID.fullmatch(identifier) is None
                for identifier in (
                    item.security_id,
                    item.company_id,
                    item.instrument_id,
                    item.share_class_id,
                    item.listing_id,
                    item.ticker_assignment_id,
                )
            )
            or _UPPER_HASH.fullmatch(item.request_identity) is None
            or item.endpoint_path != expected_path
        ):
            raise CurrentAssessmentExecutionStop("EXECUTION_REQUEST_SCOPE_DRIFT")
        expected_identity = _hash(
            {
                "executionVersion": EXECUTION_VERSION,
                "planRunId": value.run_id,
                "ordinal": item.ordinal,
                "symbol": item.symbol,
                "securityId": item.security_id,
                "companyId": item.company_id,
                "instrumentId": item.instrument_id,
                "shareClassId": item.share_class_id,
                "listingId": item.listing_id,
                "tickerAssignmentId": item.ticker_assignment_id,
                "mic": item.mic,
                "currency": item.currency,
                "priceProvider": value.price_provider,
                "endpointPath": item.endpoint_path,
                "preflightSealedAt": value.preflight_sealed_at,
            }
        )
        if item.request_identity != expected_identity:
            raise CurrentAssessmentExecutionStop("EXECUTION_REQUEST_IDENTITY_DRIFT")
    if value.plan_hash != _hash(_plan_body(value)):
        raise CurrentAssessmentExecutionStop("EXECUTION_PLAN_HASH_DRIFT")


def build_current_assessment_execution_plan_v1(
    *,
    run_id: str,
    preflight_sealed_at: datetime,
    identity_projection_content_hash: str,
    identities: tuple[ProjectedIdentityMemberV2, ...],
    network_authorized: bool,
    price_provider: str = "YAHOO_CHART",
) -> CurrentAssessmentExecutionPlanV1:
    if (
        type(run_id) is not str
        or _SAFE_RUN_ID.fullmatch(run_id) is None
        or type(network_authorized) is not bool
        or type(identities) is not tuple
        or tuple(item.ticker for item in identities) != TARGET_SYMBOLS
    ):
        raise CurrentAssessmentExecutionStop("EXECUTION_PLAN_INPUT_INVALID")
    if preflight_sealed_at.tzinfo is None or preflight_sealed_at.utcoffset() is None:
        raise CurrentAssessmentExecutionStop("PREFLIGHT_SEALED_AT_TIMEZONE_REQUIRED")
    sealed_at = preflight_sealed_at.astimezone(UTC)
    if sealed_at.microsecond:
        raise CurrentAssessmentExecutionStop("PREFLIGHT_SEALED_AT_WHOLE_SECOND_REQUIRED")
    requests = []
    for ordinal, identity in enumerate(identities, start=1):
        path = (
            (
                f"/v8/finance/chart/{identity.ticker}?range=10d&interval=1d&events=div%2Csplits"
                "&includeAdjustedClose=true"
            )
            if price_provider == "YAHOO_CHART"
            else (
                f"/api/eod/{identity.ticker}.US?fmt=json&from="
                f"{(sealed_at.date() - timedelta(days=14)).isoformat()}"
                f"&to={sealed_at.date().isoformat()}&period=d"
            )
        )
        request_identity = _hash(
            {
                "executionVersion": EXECUTION_VERSION,
                "planRunId": run_id,
                "ordinal": ordinal,
                "symbol": identity.ticker,
                "securityId": identity.security_id,
                "companyId": identity.company_id,
                "instrumentId": identity.instrument_id,
                "shareClassId": identity.share_class_id,
                "listingId": identity.listing_id,
                "tickerAssignmentId": identity.ticker_assignment_id,
                "mic": identity.mic,
                "currency": identity.currency,
                "priceProvider": price_provider,
                "endpointPath": path,
                "preflightSealedAt": sealed_at,
            }
        )
        requests.append(
            CurrentPriceRequestV1(
                ordinal,
                identity.ticker,
                identity.security_id,
                identity.company_id,
                identity.instrument_id,
                identity.share_class_id,
                identity.listing_id,
                identity.ticker_assignment_id,
                identity.mic,
                identity.currency,
                path,
                request_identity,
            )
        )
    provisional = CurrentAssessmentExecutionPlanV1(
        run_id=run_id,
        preflight_sealed_at=sealed_at,
        start_date=sealed_at.date() - timedelta(days=14),
        end_date=sealed_at.date(),
        identity_projection_content_hash=identity_projection_content_hash,
        requests=tuple(requests),
        plan_hash="",
        price_provider=price_provider,
        network_authorized=network_authorized,
    )
    plan = CurrentAssessmentExecutionPlanV1(
        **{**provisional.__dict__, "plan_hash": _hash(_plan_body(provisional))}
    )
    validate_current_assessment_execution_plan_v1(plan)
    return plan


def _decode_yahoo_price(
    request: CurrentPriceRequestV1,
    response: TransportResponse,
) -> tuple[dict[str, Any], datetime]:
    if response.status_code != 200:
        raise CurrentAssessmentExecutionStop(f"YAHOO_HTTP_{response.status_code}")
    header_values = tuple(value for name, value in response.headers if name.lower() == "date")
    if len(header_values) != 1:
        raise CurrentAssessmentExecutionStop("YAHOO_RESPONSE_DATE_HEADER_INVALID")
    try:
        observed_at = parsedate_to_datetime(header_values[0]).astimezone(UTC)
    except (TypeError, ValueError, OverflowError) as error:
        raise CurrentAssessmentExecutionStop("YAHOO_RESPONSE_DATE_HEADER_INVALID") from error
    if observed_at.microsecond:
        raise CurrentAssessmentExecutionStop("YAHOO_RESPONSE_DATE_FRACTIONAL")
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CurrentAssessmentExecutionStop("YAHOO_RESPONSE_JSON_INVALID") from error
    if type(payload) is not dict or set(payload) != {"chart"}:
        raise CurrentAssessmentExecutionStop("YAHOO_RESPONSE_KEYS_INVALID")
    chart = payload["chart"]
    if type(chart) is not dict or chart.get("error") is not None:
        raise CurrentAssessmentExecutionStop("YAHOO_CHART_ERROR")
    results = chart.get("result")
    if type(results) is not list or len(results) != 1 or type(results[0]) is not dict:
        raise CurrentAssessmentExecutionStop("YAHOO_RESULT_CARDINALITY_INVALID")
    result = results[0]
    meta = result.get("meta")
    if type(meta) is not dict or meta.get("symbol") != request.symbol:
        raise CurrentAssessmentExecutionStop("YAHOO_SYMBOL_IDENTITY_DRIFT")
    if meta.get("exchangeTimezoneName") != "America/New_York":
        raise CurrentAssessmentExecutionStop("YAHOO_TIMEZONE_DRIFT")
    if str(meta.get("exchangeName", "")).upper() not in {"NMS", "NGM", "NCM", "NASDAQ"}:
        raise CurrentAssessmentExecutionStop("YAHOO_MIC_DRIFT")
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    if type(timestamps) is not list or type(indicators) is not dict:
        raise CurrentAssessmentExecutionStop("YAHOO_RESPONSE_SHAPE_INVALID")
    quotes = indicators.get("quote")
    if type(quotes) is not list or len(quotes) != 1 or type(quotes[0]) is not dict:
        raise CurrentAssessmentExecutionStop("YAHOO_QUOTE_SHAPE_INVALID")
    quote = quotes[0]
    fields = ("open", "high", "low", "close", "volume")
    if any(type(quote.get(field)) is not list for field in fields):
        raise CurrentAssessmentExecutionStop("YAHOO_QUOTE_COLUMNS_INVALID")
    if any(len(quote[field]) != len(timestamps) for field in fields):
        raise CurrentAssessmentExecutionStop("YAHOO_QUOTE_CARDINALITY_INVALID")
    bars: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        if type(timestamp) is not int or timestamp <= 0:
            raise CurrentAssessmentExecutionStop("YAHOO_TIMESTAMP_INVALID")
        values = {field: quote[field][index] for field in fields}
        if any(values[field] is None for field in fields):
            continue
        if any(type(values[field]) not in {int, float} for field in fields[:-1]):
            raise CurrentAssessmentExecutionStop("YAHOO_PRICE_NUMBER_INVALID")
        if type(values["volume"]) is not int or values["volume"] < 0:
            raise CurrentAssessmentExecutionStop("YAHOO_VOLUME_INVALID")
        try:
            decimal_prices = {field: Decimal(str(values[field])) for field in fields[:-1]}
        except (DecimalException, TypeError, ValueError) as error:
            raise CurrentAssessmentExecutionStop("YAHOO_PRICE_DOMAIN_INVALID") from error
        if any(not item.is_finite() or item <= 0 for item in decimal_prices.values()):
            raise CurrentAssessmentExecutionStop("YAHOO_PRICE_DOMAIN_INVALID")
        prices = {field: format(value, "f") for field, value in decimal_prices.items()}
        session_date = (
            datetime.fromtimestamp(timestamp, UTC).astimezone(ZoneInfo("America/New_York")).date()
        )
        bars.append(
            {
                "tradingDate": session_date.isoformat(),
                "raw": {**prices, "adjustedClose": prices["close"]},
                "tactical": {**prices, "sessionComplete": True},
                "volume": values["volume"],
                "adjustmentFactor": "1",
            }
        )
    if not bars or tuple(item["tradingDate"] for item in bars) != tuple(
        sorted({item["tradingDate"] for item in bars})
    ):
        raise CurrentAssessmentExecutionStop("YAHOO_COMPLETED_BARS_INVALID")
    latest_timestamp = timestamps[-1]
    if type(latest_timestamp) is not int or observed_at < datetime.fromtimestamp(
        latest_timestamp, UTC
    ) + timedelta(hours=6, minutes=30):
        raise CurrentAssessmentExecutionStop("YAHOO_SESSION_NOT_COMPLETED")
    body = {
        "schemaVersion": PRICE_NORMALIZATION_VERSION,
        "symbol": request.symbol,
        "securityId": request.security_id,
        "mic": request.mic,
        "providerCode": "yfinance",
        "providerSchemaVersion": "yahoo-chart-v8",
        "parserVersion": PRICE_NORMALIZATION_VERSION,
        "sourceReference": f"yahoo-chart:{request.symbol}:10d:1d",
        "sourceResponseSha256": hashlib.sha256(response.body).hexdigest().upper(),
        "availableAt": observed_at.isoformat().replace("+00:00", "Z"),
        "retrievedAt": observed_at.isoformat().replace("+00:00", "Z"),
        "barCount": len(bars),
        "bars": bars,
    }
    return {**body, "contentHash": _hash(body)}, observed_at


def _decode_eodhd_price(
    request: CurrentPriceRequestV1,
    response: TransportResponse,
) -> tuple[dict[str, Any], datetime]:
    if response.status_code != 200:
        raise CurrentAssessmentExecutionStop(f"EODHD_PRICE_HTTP_{response.status_code}")
    header_values = tuple(value for name, value in response.headers if name.lower() == "date")
    if len(header_values) != 1:
        raise CurrentAssessmentExecutionStop("EODHD_PRICE_DATE_HEADER_INVALID")
    try:
        observed_at = parsedate_to_datetime(header_values[0]).astimezone(UTC)
    except (TypeError, ValueError, OverflowError) as error:
        raise CurrentAssessmentExecutionStop("EODHD_PRICE_DATE_HEADER_INVALID") from error
    if observed_at.microsecond:
        raise CurrentAssessmentExecutionStop("EODHD_PRICE_DATE_FRACTIONAL")
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CurrentAssessmentExecutionStop("EODHD_PRICE_JSON_INVALID") from error
    if type(payload) is not list or not payload:
        raise CurrentAssessmentExecutionStop("EODHD_PRICE_ROWS_MISSING")
    bars: list[dict[str, Any]] = []
    try:
        for row in payload:
            if type(row) is not dict:
                raise CurrentAssessmentExecutionStop("EODHD_PRICE_ROW_INVALID")
            session = date.fromisoformat(str(row["date"]))
            prices = {field: Decimal(str(row[field])) for field in ("open", "high", "low", "close")}
            adjusted = Decimal(str(row.get("adjusted_close", row["close"])))
            volume = row["volume"]
            if (
                any(not item.is_finite() or item <= 0 for item in prices.values())
                or not adjusted.is_finite()
                or adjusted <= 0
                or type(volume) is not int
                or volume < 0
                or prices["low"] > min(prices["open"], prices["close"])
                or prices["high"] < max(prices["open"], prices["close"])
            ):
                raise CurrentAssessmentExecutionStop("EODHD_PRICE_DOMAIN_INVALID")
            rendered = {field: format(value, "f") for field, value in prices.items()}
            bars.append(
                {
                    "tradingDate": session.isoformat(),
                    "raw": {**rendered, "adjustedClose": format(adjusted, "f")},
                    "tactical": {**rendered, "sessionComplete": True},
                    "volume": volume,
                    "adjustmentFactor": format(adjusted / prices["close"], "f"),
                }
            )
    except (KeyError, ValueError, DecimalException) as error:
        raise CurrentAssessmentExecutionStop("EODHD_PRICE_ROW_INVALID") from error
    dates = tuple(item["tradingDate"] for item in bars)
    if dates != tuple(sorted(set(dates))) or date.fromisoformat(dates[-1]) > observed_at.date():
        raise CurrentAssessmentExecutionStop("EODHD_PRICE_DATE_ORDER_INVALID")
    eastern_observed = observed_at.astimezone(ZoneInfo("America/New_York"))
    if date.fromisoformat(dates[-1]) == eastern_observed.date() and (
        eastern_observed.hour,
        eastern_observed.minute,
    ) < (16, 0):
        raise CurrentAssessmentExecutionStop("EODHD_PRICE_SESSION_NOT_COMPLETED")
    body = {
        "schemaVersion": "FV-CURRENT-EODHD-PRICE-NORMALIZATION-v1.0.0",
        "symbol": request.symbol,
        "securityId": request.security_id,
        "mic": request.mic,
        "providerCode": "eodhd",
        "providerSchemaVersion": "eodhd-api-v1",
        "parserVersion": "FV-CURRENT-EODHD-PRICE-NORMALIZATION-v1.0.0",
        "sourceReference": f"eodhd:eod:{request.symbol}.US",
        "sourceResponseSha256": hashlib.sha256(response.body).hexdigest().upper(),
        "availableAt": observed_at.isoformat().replace("+00:00", "Z"),
        "retrievedAt": observed_at.isoformat().replace("+00:00", "Z"),
        "barCount": len(bars),
        "bars": bars,
    }
    return {**body, "contentHash": _hash(body)}, observed_at


def decode_current_eodhd_price_response_v1(
    request: CurrentPriceRequestV1,
    response: TransportResponse,
) -> tuple[dict[str, Any], datetime]:
    """Decode one already-captured EODHD price response without transport access."""

    return _decode_eodhd_price(request, response)


def _response_from_replay(response: object) -> TransportResponse:
    if not hasattr(response, "read"):
        raise CurrentAssessmentExecutionStop("REPLAY_RESPONSE_INVALID")
    body = response.read()
    return TransportResponse(
        status_code=int(response.status),
        headers=tuple(sorted((str(k).lower(), str(v)) for k, v in response.headers.items())),
        body=body,
    )


def execute_current_assessment_v1(
    plan: CurrentAssessmentExecutionPlanV1,
    *,
    identities: tuple[ProjectedIdentityMemberV2, ...],
    evidence_registrar: CurrentEvidenceRegistrarV1,
    fundamentals: dict[str, tuple[bytes, dict[str, Any], CurrentSourceSealV1]],
    storage_root: Path,
    transport: YahooTransportV1 | None = None,
    sealed_at: datetime | None = None,
) -> CurrentAssessmentExecutionResultV1:
    """Execute exactly three sealed price calls or exact checkpoint replays."""

    validate_current_assessment_execution_plan_v1(plan)
    if tuple(item.ticker for item in identities) != TARGET_SYMBOLS:
        raise CurrentAssessmentExecutionStop("EXECUTION_IDENTITY_SET_DRIFT")
    for request, identity in zip(plan.requests, identities, strict=True):
        if (
            request.symbol,
            request.security_id,
            request.company_id,
            request.instrument_id,
            request.share_class_id,
            request.listing_id,
            request.ticker_assignment_id,
            request.mic,
            request.currency,
        ) != (
            identity.ticker,
            identity.security_id,
            identity.company_id,
            identity.instrument_id,
            identity.share_class_id,
            identity.listing_id,
            identity.ticker_assignment_id,
            identity.mic,
            identity.currency,
        ):
            raise CurrentAssessmentExecutionStop("EXECUTION_DURABLE_IDENTITY_DRIFT")
    if set(fundamentals) != set(TARGET_SYMBOLS):
        raise CurrentAssessmentExecutionStop("FUNDAMENTAL_SOURCE_SET_DRIFT")
    root = storage_root.resolve() / plan.run_id
    plan_path = root / "plan.json"
    _immutable_json(plan_path, _canonical({**_plan_body(plan), "planHash": plan.plan_hash}))
    manifest_path = root / "manifest.json"
    existing_manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CurrentAssessmentExecutionStop("EXISTING_MANIFEST_INVALID") from error
        body = {key: item for key, item in manifest.items() if key != "contentHash"}
        if (
            manifest.get("contentHash") != _hash(body)
            or manifest.get("status") != "COMPLETE"
            or manifest.get("planHash") != plan.plan_hash
            or manifest.get("runId") != plan.run_id
        ):
            raise CurrentAssessmentExecutionStop("EXISTING_MANIFEST_DRIFT")
        hashes = manifest.get("assessmentHashes")
        paths = manifest.get("assessmentPaths")
        if (
            type(hashes) is not list
            or type(paths) is not list
            or len(hashes) != 3
            or len(paths) != 3
        ):
            raise CurrentAssessmentExecutionStop("EXISTING_MANIFEST_CARDINALITY_DRIFT")
        for expected_hash, relative_path in zip(hashes, paths, strict=True):
            if type(relative_path) is not str or Path(relative_path).is_absolute():
                raise CurrentAssessmentExecutionStop("EXISTING_ASSESSMENT_PATH_INVALID")
            path = (storage_root.resolve() / relative_path).resolve()
            if storage_root.resolve() not in path.parents or not path.is_file():
                raise CurrentAssessmentExecutionStop("EXISTING_ASSESSMENT_MISSING")
            try:
                assessment_wire = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise CurrentAssessmentExecutionStop("EXISTING_ASSESSMENT_INVALID") from error
            assessment_body = {
                key: item for key, item in assessment_wire.items() if key != "content_hash"
            }
            if (
                assessment_wire.get("content_hash") != expected_hash
                or "content_hash" not in assessment_wire
                or _hash(assessment_body) != str(expected_hash).removeprefix("sha256:").upper()
            ):
                raise CurrentAssessmentExecutionStop("EXISTING_ASSESSMENT_HASH_DRIFT")
        # A Git-ignored manifest is an execution checkpoint, not durable proof of
        # the V22/V26 evidence graph. Continue through typed checkpoint replay,
        # V22 registration, and deterministic assessment reconstruction.
        existing_manifest = manifest
    journal = PhysicalRequestJournal(root / "journals", plan.run_id)
    preflight = {
        "sliceId": plan.plan_hash,
        "symbols": list(TARGET_SYMBOLS),
        "executionVersion": EXECUTION_VERSION,
        "networkAuthorized": plan.network_authorized,
        "retryLimit": 0,
        "physicalRequestCeiling": 3,
    }
    run_event_root = root / "journals" / plan.run_id / "run"
    if run_event_root.exists():
        try:
            journal.resume_preflight(preflight)
        except RuntimeError as error:
            raise CurrentAssessmentExecutionStop(str(error)) from error
    else:
        journal.preflight(preflight)
    resolved_transport = transport or (
        StdlibAcquisitionHttpTransport()
        if plan.price_provider == "YAHOO_CHART"
        else CurrentEodhdPriceHttpTransportV1()
    )
    physical_requests = 0
    replayed_requests = 0
    acquired_prices: list[
        tuple[
            CurrentPriceRequestV1,
            ProjectedIdentityMemberV2,
            bytes,
            dict[str, Any],
            datetime,
        ]
    ] = []
    with ExecutionLease(root / ".execution.lock", plan.run_id):
        for request, identity in zip(plan.requests, identities, strict=True):
            state, replay = journal.resume(request.symbol, request.request_identity)
            if state == "UNKNOWN":
                raise CurrentAssessmentExecutionStop("UNKNOWN_TRANSPORT_OUTCOME")
            if state == "SKIP":
                assert replay is not None
                response = _response_from_replay(replay)
                replayed_requests += 1
            else:
                if not plan.network_authorized:
                    raise CurrentAssessmentExecutionStop("NETWORK_NOT_AUTHORIZED")
                if physical_requests >= plan.physical_request_ceiling:
                    raise CurrentAssessmentExecutionStop("PHYSICAL_REQUEST_CEILING_EXCEEDED")
                attempt_id = journal.next_attempt_id(request.symbol, request.request_identity)
                journal.intent(
                    symbol=request.symbol,
                    request_identity=request.request_identity,
                    endpoint_category=plan.price_provider,
                    attempt_id=attempt_id,
                    configured_weight=1,
                )
                started = time.perf_counter()
                try:
                    response = resolved_transport.send(
                        ProviderWireRequest(
                            request_identity=request.request_identity,
                            provider=(
                                "YAHOO_CHART" if plan.price_provider == "YAHOO_CHART" else "EODHD"
                            ),
                            method="GET",
                            endpoint_path=request.endpoint_path,
                            headers=(("accept", "application/json"),),
                            body=None,
                            body_sha256=None,
                        )
                    )
                    physical_requests += 1
                    journal.completed(
                        symbol=request.symbol,
                        request_identity=request.request_identity,
                        endpoint_category=plan.price_provider,
                        attempt_id=attempt_id,
                        configured_weight=1,
                        duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
                        status=response.status_code,
                        headers=dict(response.headers),
                        body=response.body,
                    )
                except BaseException as error:
                    raise CurrentAssessmentExecutionStop("UNKNOWN_TRANSPORT_OUTCOME") from error
            price_payload, observed_at = (
                _decode_yahoo_price(request, response)
                if plan.price_provider == "YAHOO_CHART"
                else _decode_eodhd_price(request, response)
            )
            if not (
                plan.preflight_sealed_at - timedelta(minutes=2)
                <= observed_at
                <= plan.preflight_sealed_at + timedelta(minutes=15)
            ):
                raise CurrentAssessmentExecutionStop("PRICE_RESPONSE_DATE_OUTSIDE_PLAN")
            price_dates = tuple(
                date.fromisoformat(str(item["tradingDate"])) for item in price_payload["bars"]
            )
            if price_dates[0] < plan.start_date or price_dates[-1] > plan.end_date:
                raise CurrentAssessmentExecutionStop("PRICE_DATE_OUTSIDE_PLAN")
            acquired_prices.append(
                (request, identity, response.body, price_payload, observed_at)
            )

    if sealed_at is not None and (
        sealed_at.tzinfo is None or sealed_at.utcoffset() is None
    ):
        raise CurrentAssessmentExecutionStop("SEALED_AT_TIMEZONE_REQUIRED")
    decision_cutoff = (
        datetime.now(UTC).replace(microsecond=0)
        if sealed_at is None
        else sealed_at.astimezone(UTC)
    )
    if decision_cutoff.microsecond:
        raise CurrentAssessmentExecutionStop("SEALED_AT_WHOLE_SECOND_REQUIRED")
    if decision_cutoff < max(item[4] for item in acquired_prices):
        raise CurrentAssessmentExecutionStop("INGESTION_BEFORE_PROVIDER_AVAILABILITY")
    assessments: list[CurrentFundamentalAssessmentV1] = []
    assessment_paths: list[str] = []
    session_completion: dict[tuple[str, date], datetime] = {}
    for _, identity, _, price_payload, observed_at in acquired_prices:
        price_date = max(
            date.fromisoformat(str(item["tradingDate"]))
            for item in price_payload["bars"]
        )
        key = (identity.mic, price_date)
        session_completion[key] = max(observed_at, session_completion.get(key, observed_at))
    for request, identity, raw_price, price_payload, observed_at in acquired_prices:
        response_hash = hashlib.sha256(raw_price).hexdigest().upper()
        checkpoint_reference = str(
            (
                root
                / "journals"
                / plan.run_id
                / "requests"
                / request.symbol
                / request.request_identity
                / "responses"
                / f"{response_hash}.bin"
            ).relative_to(storage_root.resolve())
        )
        price_source = source_seal_from_bytes_v1(
            provider_code=("YAHOO" if plan.price_provider == "YAHOO_CHART" else "EODHD"),
            schema_version=str(price_payload["schemaVersion"]),
            source_reference=checkpoint_reference,
            raw=raw_price,
            canonical_payload=price_payload,
            available_at=observed_at,
            retrieved_at=None,
            ingested_at=decision_cutoff,
            source_revision=1,
            adapter_version=(
                "FV-CURRENT-YAHOO-PRICE-ADAPTER-v1.0.0"
                if plan.price_provider == "YAHOO_CHART"
                else "FV-CURRENT-EODHD-PRICE-ADAPTER-v1.0.0"
            ),
            normalization_version=str(price_payload["schemaVersion"]),
            freshness_policy_version="FV-CURRENT-PRICE-5D-v1.0.0",
            request_identity=request.request_identity,
            plan_hash=plan.plan_hash,
            checkpoint_reference=checkpoint_reference,
        )
        fundamental_raw, fundamental_payload, fundamental_source = fundamentals[request.symbol]
        price_date = max(
            date.fromisoformat(str(item["tradingDate"]))
            for item in price_payload["bars"]
        )
        completed_session = create_current_completed_session_seal_v1(
            session_date=price_date,
            completed_at=session_completion[(identity.mic, price_date)],
            mic=identity.mic,
        )
        applicability_seal, price_selection_seal = evidence_registrar.register(
            identity=identity,
            completed_session=completed_session,
            fundamentals_raw=fundamental_raw,
            fundamentals_payload=fundamental_payload,
            fundamentals_source=fundamental_source,
            price_raw=raw_price,
            price_payload=price_payload,
            price_source=price_source,
            decision_cutoff=decision_cutoff,
        )
        assessment = build_current_fundamental_assessment_v1(
            identity=identity,
            completed_session=completed_session,
            applicability_seal=applicability_seal,
            price_selection_seal=price_selection_seal,
            fundamentals_raw=fundamental_raw,
            fundamentals_payload=fundamental_payload,
            fundamentals_source=fundamental_source,
            price_raw=raw_price,
            price_payload=price_payload,
            price_source=price_source,
            decision_cutoff=decision_cutoff,
        )
        assessment_path = (
            root
            / "assessments"
            / (f"{request.symbol}-{assessment.content_hash.removeprefix('sha256:')}.json")
        )
        _immutable_json(assessment_path, current_fundamental_assessment_to_wire_v1(assessment))
        assessments.append(assessment)
        assessment_paths.append(str(assessment_path.relative_to(storage_root.resolve())))
    manifest_body = {
        "executionVersion": EXECUTION_VERSION,
        "assessmentContractVersion": ASSESSMENT_CONTRACT_VERSION,
        "status": "COMPLETE",
        "runId": plan.run_id,
        "planHash": plan.plan_hash,
        "priceProvider": plan.price_provider,
        "decisionCutoff": decision_cutoff,
        "assessmentHashes": [item.content_hash for item in assessments],
        "assessmentPaths": assessment_paths,
        "physicalRequests": physical_requests,
        "replayedRequests": replayed_requests,
        "retryLimit": 0,
        "networkAuthorized": plan.network_authorized,
    }
    canonical_manifest = _canonical({**manifest_body, "contentHash": _hash(manifest_body)})
    if type(canonical_manifest) is not dict:
        raise CurrentAssessmentExecutionStop("MANIFEST_SERIALIZATION_INVALID")
    manifest = canonical_manifest
    if existing_manifest is None:
        _immutable_json(manifest_path, manifest)
        journal.finalize("COMPLETE", manifest)
    elif (
        existing_manifest.get("assessmentHashes")
        != [item.content_hash for item in assessments]
        or existing_manifest.get("assessmentPaths") != assessment_paths
        or existing_manifest.get("decisionCutoff")
        != _canonical(decision_cutoff)
    ):
        raise CurrentAssessmentExecutionStop("EXISTING_MANIFEST_TYPED_REPLAY_DRIFT")
    return CurrentAssessmentExecutionResultV1(
        "COMPLETE",
        plan.run_id,
        plan.plan_hash,
        tuple(item.content_hash for item in assessments),
        tuple(assessment_paths),
        physical_requests,
        replayed_requests,
        str(manifest_path.relative_to(storage_root.resolve())),
        decision_cutoff,
    )


__all__ = [
    "EXECUTION_VERSION",
    "CurrentAssessmentExecutionPlanV1",
    "CurrentAssessmentExecutionResultV1",
    "CurrentAssessmentExecutionStop",
    "CurrentPriceRequestV1",
    "build_current_assessment_execution_plan_v1",
    "decode_current_eodhd_price_response_v1",
    "execute_current_assessment_v1",
    "validate_current_assessment_execution_plan_v1",
]
