from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any

from equity_analysis.research_rating.long_horizon_v1 import (
    LONG_HORIZON_VERSION,
    LongHorizonInputs,
)
from equity_analysis.tactical.signal_v2 import (
    TACTICAL_SIGNAL_VERSION,
    PriorReversalContext,
    TacticalBar,
)

REQUEST_SCHEMA_VERSION = "analytics-model-request-v1.0.0"
RESULT_SCHEMA_VERSION = "analytics-model-result-v1.0.0"


class AnalyticsModelId(StrEnum):
    LONG_HORIZON_RESEARCH = "LONG_HORIZON_RESEARCH"
    DAILY_TACTICAL_SIGNAL = "DAILY_TACTICAL_SIGNAL"


class ModelRunStatus(StrEnum):
    ASSESSED = "ASSESSED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class MissingDataState(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class AiBoundary(StrEnum):
    DETERMINISTIC_ONLY = "DETERMINISTIC_ONLY"
    VALIDATED_EXTERNAL_OVERLAY_ONLY = "VALIDATED_EXTERNAL_OVERLAY_ONLY"


class AiOverlayStatus(StrEnum):
    NOT_EXECUTED = "NOT_EXECUTED"


class AnalyticsInputCapability(StrEnum):
    ADJUSTED_DAILY_PRICES = "ADJUSTED_DAILY_PRICES"
    NORMALIZED_LONG_HORIZON_INPUTS = "NORMALIZED_LONG_HORIZON_INPUTS"


class AnalyticsInterfaceError(RuntimeError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class AnalyticsCapabilityError(AnalyticsInterfaceError):
    pass


class AnalyticsModelResolutionError(AnalyticsInterfaceError):
    pass


class AnalyticsModelInputError(AnalyticsInterfaceError):
    pass


@dataclass(frozen=True)
class ProviderProvenance:
    provider_code: str
    provider_schema_version: str
    parser_version: str
    source_reference: str
    content_hash: str
    available_at: datetime
    retrieved_at: datetime
    adjustment_mode: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "provider_code",
            "provider_schema_version",
            "parser_version",
            "source_reference",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        _validate_hash(self.content_hash, "Provider content hash")
        _validate_aware(self.available_at, "Provider available_at")
        _validate_aware(self.retrieved_at, "Provider retrieved_at")
        lowered = self.source_reference.lower()
        if any(secret in lowered for secret in ("api_token=", "apikey=", "api_key=")):
            raise ValueError("Provider source reference must not contain credentials")


@dataclass(frozen=True)
class ModelTiming:
    as_of: datetime
    effective_at: datetime
    expires_at: datetime | None

    def __post_init__(self) -> None:
        _validate_aware(self.as_of, "Model as_of")
        _validate_aware(self.effective_at, "Model effective_at")
        if self.effective_at < self.as_of:
            raise ValueError("Model effective_at cannot precede as_of")
        if self.expires_at is not None:
            _validate_aware(self.expires_at, "Model expires_at")
            if self.expires_at <= self.effective_at:
                raise ValueError("Model expires_at must follow effective_at")


@dataclass(frozen=True)
class RequestEvidence:
    evidence_hash: str
    providers: tuple[ProviderProvenance, ...]
    missing_inputs: tuple[str, ...] = ()
    ai_boundary: AiBoundary = AiBoundary.DETERMINISTIC_ONLY

    def __post_init__(self) -> None:
        _validate_hash(self.evidence_hash, "Evidence hash")
        if not self.providers:
            raise ValueError("At least one provider provenance record is required")
        if len(set(self.missing_inputs)) != len(self.missing_inputs):
            raise ValueError("Missing inputs must be unique")


@dataclass(frozen=True)
class LongHorizonModelRequest:
    timing: ModelTiming
    evidence: RequestEvidence
    inputs: LongHorizonInputs
    model_id: AnalyticsModelId = AnalyticsModelId.LONG_HORIZON_RESEARCH
    model_version: str = LONG_HORIZON_VERSION
    schema_version: str = REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.inputs.symbol.strip():
            raise ValueError("Long-horizon symbol is required")
        _validate_evidence_cutoff(self.timing, self.evidence)

    @property
    def symbol(self) -> str:
        return self.inputs.symbol.strip().upper()

    @property
    def input_hash(self) -> str:
        return canonical_hash(
            {
                "modelId": self.model_id,
                "modelVersion": self.model_version,
                "normalizedInputs": self.inputs,
            }
        )


@dataclass(frozen=True)
class TacticalModelRequest:
    symbol: str
    benchmark_symbol: str
    timing: ModelTiming
    evidence: RequestEvidence
    security_bars: tuple[TacticalBar, ...]
    benchmark_bars: tuple[TacticalBar, ...]
    event_drift_score: float = 50.0
    prior_reversal_context: PriorReversalContext | None = None
    model_id: AnalyticsModelId = AnalyticsModelId.DAILY_TACTICAL_SIGNAL
    model_version: str = TACTICAL_SIGNAL_VERSION
    schema_version: str = REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.benchmark_symbol.strip():
            raise ValueError("Tactical symbol and benchmark symbol are required")
        if not 0 <= self.event_drift_score <= 100:
            raise ValueError("Event drift score must be between zero and 100")
        _validate_evidence_cutoff(self.timing, self.evidence)
        _validate_tactical_bar_cutoff(
            self.timing,
            self.security_bars,
            "Security",
        )
        _validate_tactical_bar_cutoff(
            self.timing,
            self.benchmark_bars,
            "Benchmark",
        )

    @property
    def input_hash(self) -> str:
        return canonical_hash(
            {
                "modelId": self.model_id,
                "modelVersion": self.model_version,
                "symbol": self.symbol.strip().upper(),
                "benchmarkSymbol": self.benchmark_symbol.strip().upper(),
                "securityBars": self.security_bars,
                "benchmarkBars": self.benchmark_bars,
                "eventDriftScore": self.event_drift_score,
                "priorReversalContext": self.prior_reversal_context,
            }
        )


ModelRequest = LongHorizonModelRequest | TacticalModelRequest


@dataclass(frozen=True)
class ModelResultEnvelope:
    request_schema_version: str
    schema_version: str
    model_id: AnalyticsModelId
    model_version: str
    symbol: str
    status: ModelRunStatus
    missing_data_state: MissingDataState
    missing_inputs: tuple[str, ...]
    as_of: datetime
    effective_at: datetime
    expires_at: datetime | None
    input_hash: str
    evidence_hash: str
    provider_provenance: tuple[ProviderProvenance, ...]
    deterministic_result: dict[str, Any]
    ai_boundary: AiBoundary
    ai_overlay_status: AiOverlayStatus = AiOverlayStatus.NOT_EXECUTED
    ai_overlay_result: None = None


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def dataclass_payload(value: Any) -> dict[str, Any]:
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError("Expected a dataclass instance")
    return {
        item.name: _json_value(getattr(value, item.name))
        for item in fields(value)
    }


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            key: _json_value(item)
            for key, item in asdict(value).items()
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        normalized = value.astimezone(UTC)
        return normalized.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    raise TypeError(f"Unsupported canonical value type: {type(value).__name__}")


def _validate_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _validate_hash(value: str, label: str) -> None:
    normalized = value.removeprefix("sha256:")
    if len(normalized) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in normalized
    ):
        raise ValueError(f"{label} must be a SHA-256 value")


def _validate_evidence_cutoff(
    timing: ModelTiming,
    evidence: RequestEvidence,
) -> None:
    if any(provider.available_at > timing.as_of for provider in evidence.providers):
        raise ValueError("Provider evidence cannot be available after the model cutoff")
    if any(provider.retrieved_at > timing.as_of for provider in evidence.providers):
        raise ValueError("Provider evidence cannot be retrieved after the model cutoff")


def _validate_tactical_bar_cutoff(
    timing: ModelTiming,
    bars: tuple[TacticalBar, ...],
    label: str,
) -> None:
    if any(bar.trading_date > timing.as_of.date() for bar in bars):
        raise ValueError(f"{label} bars cannot be dated after the model cutoff")
