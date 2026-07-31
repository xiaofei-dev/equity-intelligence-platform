from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from equity_analysis.analytics_interface.contracts import canonical_hash

FUTURE_PRICE_EVIDENCE_VERSION = "FUTURE-COMPLETED-SESSION-PRICE-EVIDENCE-v1.0.0"
RAW_HTTP_CAPTURE_VERSION = "RAW-HTTP-TRANSPORT-CAPTURE-v1.0.0"
YAHOO_CHART_NORMALIZATION_VERSION = "YAHOO-CHART-DAILY-NORMALIZATION-v1.0.0"
ACTION_ADJUSTMENT_BINDING_VERSION = "ACTION-ADJUSTED-PRICE-BINDING-v1.0.0"
ADTV_POLICY_VERSION = "ADTV-20-RAW-CLOSE-X-RAW-VOLUME-v1.0.0"
NETWORK_CONFIRMATION = "I_CONFIRM_FUTURE_PRICE_EVIDENCE_LIVE_CAPTURE"
ADTV_WINDOW_SESSIONS = 20


class FuturePriceEvidenceError(RuntimeError):
    pass


class CalendarAuthority(StrEnum):
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"


class EvidenceState(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class RawHttpTransportCapture:
    request_identity: str
    endpoint_category: str
    requested_url: str
    final_url: str
    http_status: int
    sanitized_headers: tuple[tuple[str, str], ...]
    response_body_sha256: str
    response_body_storage_reference: str
    response_envelope_hash: str
    response_envelope_storage_reference: str
    captured_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.captured_at, "capturedAt")
        _require_sha256(self.response_body_sha256, "response body SHA-256")
        _require_sha256(self.response_envelope_hash, "response envelope hash")
        if self.http_status < 100 or self.http_status > 599:
            raise ValueError("HTTP status is outside the valid range")
        if self.response_body_sha256 == self.response_envelope_hash:
            raise ValueError("Body and envelope hashes must bind distinct bytes")


@dataclass(frozen=True)
class OfficialCalendarReview:
    authority: CalendarAuthority
    target_session: date
    official_source_url: str
    raw_body_sha256: str
    raw_body_storage_reference: str
    retrieved_at: datetime
    reviewed_at: datetime
    reviewed_by: str
    confirms_scheduled_session: bool
    confirms_regular_or_published_early_close: bool
    review_hash: str

    def __post_init__(self) -> None:
        _require_sha256(self.raw_body_sha256, "official calendar body hash")
        _require_aware(self.retrieved_at, "calendar retrievedAt")
        _require_aware(self.reviewed_at, "calendar reviewedAt")
        if self.reviewed_at < self.retrieved_at:
            raise ValueError("Calendar review cannot precede retrieval")
        if not self.reviewed_by.strip():
            raise ValueError("Calendar evidence requires a named reviewer")
        expected = canonical_hash(
            {
                "authority": self.authority.value,
                "targetSession": self.target_session,
                "officialSourceUrl": self.official_source_url,
                "rawBodySha256": self.raw_body_sha256,
                "rawBodyStorageReference": self.raw_body_storage_reference,
                "retrievedAt": self.retrieved_at,
                "reviewedAt": self.reviewed_at,
                "reviewedBy": self.reviewed_by,
                "confirmsScheduledSession": self.confirms_scheduled_session,
                "confirmsRegularOrPublishedEarlyClose": (
                    self.confirms_regular_or_published_early_close
                ),
            }
        )
        if self.review_hash != expected:
            raise ValueError("Calendar review hash mismatch")


@dataclass(frozen=True)
class DualAuthorityCompletedSessionEvidence:
    target_session: date
    completed_session_cutoff: datetime
    nyse: OfficialCalendarReview
    nasdaq: OfficialCalendarReview
    evidence_hash: str

    def __post_init__(self) -> None:
        _require_aware(self.completed_session_cutoff, "completedSessionCutoff")
        if self.nyse.authority != CalendarAuthority.NYSE:
            raise ValueError("NYSE review is required")
        if self.nasdaq.authority != CalendarAuthority.NASDAQ:
            raise ValueError("Nasdaq review is required")
        for review in (self.nyse, self.nasdaq):
            if review.target_session != self.target_session:
                raise ValueError("Calendar review target session mismatch")
            if not (
                review.confirms_scheduled_session
                and review.confirms_regular_or_published_early_close
            ):
                raise ValueError("Both authorities must affirm the target session")
        if self.completed_session_cutoff < max(
            self.nyse.reviewed_at,
            self.nasdaq.reviewed_at,
        ):
            raise ValueError("Completed-session cutoff cannot precede calendar review")
        expected = canonical_hash(
            {
                "targetSession": self.target_session,
                "completedSessionCutoff": self.completed_session_cutoff,
                "nyseReviewHash": self.nyse.review_hash,
                "nasdaqReviewHash": self.nasdaq.review_hash,
            }
        )
        if self.evidence_hash != expected:
            raise ValueError("Dual-authority calendar evidence hash mismatch")


@dataclass(frozen=True)
class CompletedPriceBar:
    trading_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    adjusted_close: Decimal
    volume: int

    def __post_init__(self) -> None:
        if (
            min(
                self.open_price,
                self.high_price,
                self.low_price,
                self.close_price,
                self.adjusted_close,
            )
            <= 0
        ):
            raise ValueError("Completed price bars require positive prices")
        if self.low_price > min(
            self.open_price,
            self.close_price,
            self.high_price,
        ) or self.high_price < max(
            self.open_price,
            self.close_price,
            self.low_price,
        ):
            raise ValueError("Completed price bar OHLC ordering is invalid")
        if self.volume < 0:
            raise ValueError("Completed price bar volume cannot be negative")


@dataclass(frozen=True)
class ActionAdjustedPriceBinding:
    version: str
    symbol: str
    target_session: date
    raw_transport_body_hash: str
    raw_bar_set_hash: str
    selected_action_set_hash: str
    adjusted_bar_set_hash: str
    adjustment_mode: str
    adjustment_policy_version: str
    provider_revision_key: str
    source_revision_status: str
    binding_hash: str


@dataclass(frozen=True)
class AdtvMetricObservation:
    metric_name: str
    metric_version: str
    symbol: str
    observation_date: date
    completed_session_count: int
    currency: str
    numeric_value: Decimal
    price_volume_input_hash: str
    available_at: datetime
    ingested_at: datetime
    status: str
    observation_hash: str


@dataclass(frozen=True)
class NormalizedFuturePriceEvidence:
    version: str
    symbol: str
    target_session: date
    provider: str
    provider_schema_version: str
    normalization_version: str
    raw_transport: RawHttpTransportCapture
    calendar_evidence_hash: str
    bars: tuple[CompletedPriceBar, ...]
    action_binding: ActionAdjustedPriceBinding
    adtv: AdtvMetricObservation
    available_at: datetime
    ingested_at: datetime
    evidence_hash: str


def build_calendar_review(
    *,
    authority: CalendarAuthority,
    target_session: date,
    official_source_url: str,
    raw_body_sha256: str,
    raw_body_storage_reference: str,
    retrieved_at: datetime,
    reviewed_at: datetime,
    reviewed_by: str,
    confirms_scheduled_session: bool,
    confirms_regular_or_published_early_close: bool,
) -> OfficialCalendarReview:
    payload = {
        "authority": authority.value,
        "targetSession": target_session,
        "officialSourceUrl": official_source_url,
        "rawBodySha256": raw_body_sha256,
        "rawBodyStorageReference": raw_body_storage_reference,
        "retrievedAt": retrieved_at,
        "reviewedAt": reviewed_at,
        "reviewedBy": reviewed_by,
        "confirmsScheduledSession": confirms_scheduled_session,
        "confirmsRegularOrPublishedEarlyClose": (confirms_regular_or_published_early_close),
    }
    return OfficialCalendarReview(
        authority=authority,
        target_session=target_session,
        official_source_url=official_source_url,
        raw_body_sha256=raw_body_sha256,
        raw_body_storage_reference=raw_body_storage_reference,
        retrieved_at=retrieved_at,
        reviewed_at=reviewed_at,
        reviewed_by=reviewed_by,
        confirms_scheduled_session=confirms_scheduled_session,
        confirms_regular_or_published_early_close=(confirms_regular_or_published_early_close),
        review_hash=canonical_hash(payload),
    )


def build_dual_authority_evidence(
    *,
    target_session: date,
    completed_session_cutoff: datetime,
    nyse: OfficialCalendarReview,
    nasdaq: OfficialCalendarReview,
) -> DualAuthorityCompletedSessionEvidence:
    payload = {
        "targetSession": target_session,
        "completedSessionCutoff": completed_session_cutoff,
        "nyseReviewHash": nyse.review_hash,
        "nasdaqReviewHash": nasdaq.review_hash,
    }
    return DualAuthorityCompletedSessionEvidence(
        target_session=target_session,
        completed_session_cutoff=completed_session_cutoff,
        nyse=nyse,
        nasdaq=nasdaq,
        evidence_hash=canonical_hash(payload),
    )


_ALLOWED_RESPONSE_HEADERS = frozenset(
    {
        "age",
        "cache-control",
        "content-encoding",
        "content-length",
        "content-type",
        "date",
        "etag",
        "last-modified",
    }
)


def capture_raw_http_response(
    *,
    storage_root: Path,
    request_identity: str,
    endpoint_category: str,
    requested_url: str,
    final_url: str,
    http_status: int,
    headers: dict[str, str],
    body: bytes,
    captured_at: datetime,
) -> RawHttpTransportCapture:
    """Persist exact transport bytes and a separate immutable response envelope."""

    _require_aware(captured_at, "capturedAt")
    body_hash = hashlib.sha256(body).hexdigest().upper()
    body_relative = Path("raw-http") / body_hash[:2] / f"{body_hash}.bin"
    body_path = storage_root / body_relative
    _write_exact(body_path, body)
    sanitized_headers = tuple(
        sorted(
            (
                str(key).lower(),
                str(value),
            )
            for key, value in headers.items()
            if str(key).lower() in _ALLOWED_RESPONSE_HEADERS
        )
    )
    envelope_body = {
        "schemaVersion": RAW_HTTP_CAPTURE_VERSION,
        "requestIdentity": request_identity,
        "endpointCategory": endpoint_category,
        "requestedUrl": requested_url,
        "finalUrl": final_url,
        "httpStatus": http_status,
        "sanitizedHeaders": sanitized_headers,
        "responseBodySha256": body_hash,
        "responseBodyStorageReference": body_relative.as_posix(),
        "capturedAt": captured_at.astimezone(UTC).isoformat(),
        "hashSemantics": "EXACT_HTTP_RESPONSE_BODY_BYTES",
    }
    envelope_hash = _normalized_hash(canonical_hash(envelope_body))
    envelope = {
        **envelope_body,
        "responseEnvelopeHash": envelope_hash,
    }
    envelope_relative = Path("raw-http-envelopes") / envelope_hash[:2] / f"{envelope_hash}.json"
    envelope_path = storage_root / envelope_relative
    _write_exact(
        envelope_path,
        (json.dumps(envelope, indent=2, ensure_ascii=False) + "\n").encode(),
    )
    return RawHttpTransportCapture(
        request_identity=request_identity,
        endpoint_category=endpoint_category,
        requested_url=requested_url,
        final_url=final_url,
        http_status=http_status,
        sanitized_headers=sanitized_headers,
        response_body_sha256=body_hash,
        response_body_storage_reference=body_relative.as_posix(),
        response_envelope_hash=envelope_hash,
        response_envelope_storage_reference=envelope_relative.as_posix(),
        captured_at=captured_at,
    )


def normalize_yahoo_chart_capture(
    *,
    storage_root: Path,
    symbol: str,
    target_session: date,
    raw_capture: RawHttpTransportCapture,
    calendar_evidence: DualAuthorityCompletedSessionEvidence,
) -> NormalizedFuturePriceEvidence:
    """Normalize a direct Yahoo Chart JSON response, never a DataFrame hash."""

    if raw_capture.endpoint_category != "YAHOO_CHART_JSON":
        raise FuturePriceEvidenceError("DIRECT_YAHOO_CHART_JSON_REQUIRED")
    if raw_capture.http_status != 200:
        raise FuturePriceEvidenceError("YAHOO_CHART_HTTP_STATUS_NOT_200")
    if calendar_evidence.target_session != target_session:
        raise FuturePriceEvidenceError("COMPLETED_SESSION_EVIDENCE_MISMATCH")
    body_path = _safe_storage_path(
        storage_root,
        raw_capture.response_body_storage_reference,
    )
    body = body_path.read_bytes()
    if hashlib.sha256(body).hexdigest().upper() != raw_capture.response_body_sha256:
        raise FuturePriceEvidenceError("RAW_TRANSPORT_BODY_HASH_MISMATCH")
    payload = json.loads(body)
    chart = payload.get("chart", {})
    if chart.get("error") is not None:
        raise FuturePriceEvidenceError("YAHOO_CHART_PROVIDER_ERROR")
    results = chart.get("result") or []
    if len(results) != 1:
        raise FuturePriceEvidenceError("YAHOO_CHART_RESULT_CARDINALITY_INVALID")
    result = results[0]
    meta = result.get("meta") or {}
    if str(meta.get("symbol", "")).upper() != symbol.upper():
        raise FuturePriceEvidenceError("YAHOO_CHART_SYMBOL_MISMATCH")
    timezone_name = str(meta.get("exchangeTimezoneName") or "")
    try:
        exchange_zone = ZoneInfo(timezone_name)
    except Exception as error:
        raise FuturePriceEvidenceError("YAHOO_CHART_TIMEZONE_INVALID") from error
    timestamps = result.get("timestamp") or []
    quote_rows = result.get("indicators", {}).get("quote") or []
    adjusted_rows = result.get("indicators", {}).get("adjclose") or []
    if len(quote_rows) != 1 or len(adjusted_rows) != 1:
        raise FuturePriceEvidenceError("YAHOO_CHART_INDICATOR_SHAPE_INVALID")
    quote = quote_rows[0]
    adjusted = adjusted_rows[0].get("adjclose") or []
    required = ("open", "high", "low", "close", "volume")
    if any(len(quote.get(key) or []) != len(timestamps) for key in required):
        raise FuturePriceEvidenceError("YAHOO_CHART_QUOTE_LENGTH_MISMATCH")
    if len(adjusted) != len(timestamps):
        raise FuturePriceEvidenceError("YAHOO_CHART_ADJUSTED_LENGTH_MISMATCH")
    bars: list[CompletedPriceBar] = []
    for index, timestamp in enumerate(timestamps):
        session = datetime.fromtimestamp(int(timestamp), UTC).astimezone(exchange_zone).date()
        values = tuple(quote[key][index] for key in required)
        if any(value is None for value in (*values, adjusted[index])):
            continue
        if session > target_session:
            raise FuturePriceEvidenceError("YAHOO_CHART_CONTAINS_FUTURE_SESSION")
        bars.append(
            CompletedPriceBar(
                trading_date=session,
                open_price=Decimal(str(values[0])),
                high_price=Decimal(str(values[1])),
                low_price=Decimal(str(values[2])),
                close_price=Decimal(str(values[3])),
                volume=int(values[4]),
                adjusted_close=Decimal(str(adjusted[index])),
            )
        )
    if not bars or bars[-1].trading_date != target_session:
        raise FuturePriceEvidenceError("TARGET_COMPLETED_SESSION_BAR_MISSING")
    if tuple(item.trading_date for item in bars) != tuple(
        sorted({item.trading_date for item in bars})
    ):
        raise FuturePriceEvidenceError("YAHOO_CHART_SESSION_ORDER_INVALID")
    if len(bars) < ADTV_WINDOW_SESSIONS:
        raise FuturePriceEvidenceError("ADTV_20_COMPLETED_SESSIONS_MISSING")
    events = result.get("events") or {}
    selected_events = {
        category: tuple(
            sorted(
                (
                    {
                        "eventId": str(event_id),
                        "eventDate": event.get("date"),
                        "amount": event.get("amount"),
                        "numerator": event.get("numerator"),
                        "denominator": event.get("denominator"),
                        "splitRatio": event.get("splitRatio"),
                    }
                    for event_id, event in (events.get(category) or {}).items()
                ),
                key=lambda item: item["eventId"],
            )
        )
        for category in ("dividends", "splits")
    }
    raw_bar_set_hash = canonical_hash(
        tuple(
            {
                "tradingDate": item.trading_date,
                "open": item.open_price,
                "high": item.high_price,
                "low": item.low_price,
                "close": item.close_price,
                "volume": item.volume,
            }
            for item in bars
        )
    )
    adjusted_bar_set_hash = canonical_hash(
        tuple(
            {
                "tradingDate": item.trading_date,
                "adjustedClose": item.adjusted_close,
            }
            for item in bars
        )
    )
    action_set_hash = canonical_hash(selected_events)
    binding_payload = {
        "version": ACTION_ADJUSTMENT_BINDING_VERSION,
        "symbol": symbol.upper(),
        "targetSession": target_session,
        "rawTransportBodyHash": raw_capture.response_body_sha256,
        "rawBarSetHash": raw_bar_set_hash,
        "selectedActionSetHash": action_set_hash,
        "adjustedBarSetHash": adjusted_bar_set_hash,
        "adjustmentMode": "TOTAL_RETURN_ADJUSTED",
        "adjustmentPolicyVersion": "YAHOO-ADJCLOSE-RATIO-OHLC-v1.0.0",
        "providerRevisionKey": raw_capture.response_body_sha256,
        "sourceRevisionStatus": "AS_OBSERVED_AT_CAPTURE",
    }
    action_binding = ActionAdjustedPriceBinding(
        version=ACTION_ADJUSTMENT_BINDING_VERSION,
        symbol=symbol.upper(),
        target_session=target_session,
        raw_transport_body_hash=raw_capture.response_body_sha256,
        raw_bar_set_hash=raw_bar_set_hash,
        selected_action_set_hash=action_set_hash,
        adjusted_bar_set_hash=adjusted_bar_set_hash,
        adjustment_mode="TOTAL_RETURN_ADJUSTED",
        adjustment_policy_version="YAHOO-ADJCLOSE-RATIO-OHLC-v1.0.0",
        provider_revision_key=raw_capture.response_body_sha256,
        source_revision_status="AS_OBSERVED_AT_CAPTURE",
        binding_hash=canonical_hash(binding_payload),
    )
    adtv_window = tuple(bars[-ADTV_WINDOW_SESSIONS:])
    adtv_value = sum(
        (item.close_price * Decimal(item.volume) for item in adtv_window),
        Decimal("0"),
    ) / Decimal(ADTV_WINDOW_SESSIONS)
    adtv_input_hash = canonical_hash(
        tuple(
            {
                "tradingDate": item.trading_date,
                "rawClose": item.close_price,
                "rawVolume": item.volume,
            }
            for item in adtv_window
        )
    )
    adtv_payload = {
        "metricName": "average_daily_dollar_volume",
        "metricVersion": ADTV_POLICY_VERSION,
        "symbol": symbol.upper(),
        "observationDate": target_session,
        "completedSessionCount": ADTV_WINDOW_SESSIONS,
        "currency": "USD",
        "numericValue": adtv_value,
        "priceVolumeInputHash": adtv_input_hash,
        "availableAt": raw_capture.captured_at,
        "ingestedAt": raw_capture.captured_at,
        "status": "VALIDATED",
    }
    adtv = AdtvMetricObservation(
        metric_name="average_daily_dollar_volume",
        metric_version=ADTV_POLICY_VERSION,
        symbol=symbol.upper(),
        observation_date=target_session,
        completed_session_count=ADTV_WINDOW_SESSIONS,
        currency="USD",
        numeric_value=adtv_value,
        price_volume_input_hash=adtv_input_hash,
        available_at=raw_capture.captured_at,
        ingested_at=raw_capture.captured_at,
        status="VALIDATED",
        observation_hash=canonical_hash(adtv_payload),
    )
    evidence_payload = {
        "version": FUTURE_PRICE_EVIDENCE_VERSION,
        "symbol": symbol.upper(),
        "targetSession": target_session,
        "provider": "yahoo-chart-direct",
        "providerSchemaVersion": "yahoo-chart-v8-json",
        "normalizationVersion": YAHOO_CHART_NORMALIZATION_VERSION,
        "rawTransportBodyHash": raw_capture.response_body_sha256,
        "rawTransportEnvelopeHash": raw_capture.response_envelope_hash,
        "calendarEvidenceHash": calendar_evidence.evidence_hash,
        "actionBindingHash": action_binding.binding_hash,
        "adtvObservationHash": adtv.observation_hash,
        "availableAt": raw_capture.captured_at,
        "ingestedAt": raw_capture.captured_at,
    }
    return NormalizedFuturePriceEvidence(
        version=FUTURE_PRICE_EVIDENCE_VERSION,
        symbol=symbol.upper(),
        target_session=target_session,
        provider="yahoo-chart-direct",
        provider_schema_version="yahoo-chart-v8-json",
        normalization_version=YAHOO_CHART_NORMALIZATION_VERSION,
        raw_transport=raw_capture,
        calendar_evidence_hash=calendar_evidence.evidence_hash,
        bars=tuple(bars),
        action_binding=action_binding,
        adtv=adtv,
        available_at=raw_capture.captured_at,
        ingested_at=raw_capture.captured_at,
        evidence_hash=canonical_hash(evidence_payload),
    )


def git_safe_receipt(evidence: NormalizedFuturePriceEvidence) -> dict[str, Any]:
    """Return lineage/status only; all numeric observations remain controlled."""

    body = {
        "version": FUTURE_PRICE_EVIDENCE_VERSION,
        "symbol": evidence.symbol,
        "targetSession": evidence.target_session.isoformat(),
        "provider": evidence.provider,
        "providerSchemaVersion": evidence.provider_schema_version,
        "normalizationVersion": evidence.normalization_version,
        "rawTransportBodyHash": evidence.raw_transport.response_body_sha256,
        "rawTransportEnvelopeHash": evidence.raw_transport.response_envelope_hash,
        "calendarEvidenceHash": evidence.calendar_evidence_hash,
        "actionBindingHash": evidence.action_binding.binding_hash,
        "adjustmentMode": evidence.action_binding.adjustment_mode,
        "providerRevisionKey": evidence.action_binding.provider_revision_key,
        "sourceRevisionStatus": evidence.action_binding.source_revision_status,
        "adtvMetricVersion": evidence.adtv.metric_version,
        "adtvObservationHash": evidence.adtv.observation_hash,
        "adtvStatus": evidence.adtv.status,
        "completedSessionCount": evidence.adtv.completed_session_count,
        "availableAt": evidence.available_at.isoformat(),
        "ingestedAt": evidence.ingested_at.isoformat(),
        "evidenceHash": evidence.evidence_hash,
        "rawProviderValuesIncluded": False,
    }
    return {**body, "receiptHash": canonical_hash(body)}


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _require_sha256(value: str, label: str) -> None:
    normalized = _normalized_hash(value)
    if len(normalized) != 64 or any(
        character not in "0123456789ABCDEF" for character in normalized
    ):
        raise ValueError(f"{label} must be SHA-256")


def _normalized_hash(value: str) -> str:
    return value.removeprefix("sha256:").upper()


def _write_exact(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise FuturePriceEvidenceError("CONTENT_ADDRESSED_STORAGE_COLLISION")
        return
    with path.open("xb") as handle:
        handle.write(content)


def _safe_storage_path(root: Path, reference: str) -> Path:
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts:
        raise FuturePriceEvidenceError("UNSAFE_CONTROLLED_STORAGE_REFERENCE")
    resolved_root = root.resolve()
    path = (resolved_root / relative).resolve()
    if resolved_root not in path.parents:
        raise FuturePriceEvidenceError("UNSAFE_CONTROLLED_STORAGE_REFERENCE")
    if not path.is_file():
        raise FuturePriceEvidenceError("RAW_TRANSPORT_BODY_MISSING")
    return path
