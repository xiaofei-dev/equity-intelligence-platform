import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum


class AdjustmentMode(StrEnum):
    UNADJUSTED = "UNADJUSTED"
    SPLIT_ADJUSTED = "SPLIT_ADJUSTED"
    TOTAL_RETURN_ADJUSTED = "TOTAL_RETURN_ADJUSTED"

    @classmethod
    def from_storage(cls, value: str) -> "AdjustmentMode":
        legacy = {
            "none": cls.UNADJUSTED,
            "splits": cls.SPLIT_ADJUSTED,
            "all": cls.TOTAL_RETURN_ADJUSTED,
        }
        normalized = value.lower()
        return legacy[normalized] if normalized in legacy else cls(value.upper())


class ProviderCapability(StrEnum):
    DAILY_PRICES = "DAILY_PRICES"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    SECURITY_METADATA = "SECURITY_METADATA"
    FUNDAMENTALS = "FUNDAMENTALS"
    HISTORICAL_MARKET_VALUE = "HISTORICAL_MARKET_VALUE"
    IDENTIFIER_HISTORY = "IDENTIFIER_HISTORY"
    DELISTED_SECURITIES = "DELISTED_SECURITIES"


class ProviderUseClassification(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    DEVELOPMENT_FALLBACK = "DEVELOPMENT_FALLBACK"
    DOCUMENTED_CANDIDATE = "DOCUMENTED_CANDIDATE"
    VALIDATED_LIMITED = "VALIDATED_LIMITED"


class CapabilityStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    NOT_ENTITLED = "NOT_ENTITLED"
    NOT_VERIFIED = "NOT_VERIFIED"


@dataclass(frozen=True)
class ProviderDescriptor:
    code: str
    name: str
    provider_schema_version: str
    parser_version: str
    capabilities: frozenset[ProviderCapability]
    use_classification: ProviderUseClassification


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
    adjusted_close: Decimal | None = None


@dataclass(frozen=True)
class DailyPriceSeries:
    security: SecurityMetadata
    provider_descriptor: ProviderDescriptor
    requested_symbol: str
    provider_symbol: str
    adjustment_mode: AdjustmentMode
    bars: tuple[DailyPriceBar, ...]
    source_reference: str
    available_at: datetime
    retrieved_at: datetime
    provider_record_id: str | None = None
    effective_at: datetime | None = None
    rejected_bar_count: int = 0

    @property
    def provider(self) -> str:
        return self.provider_descriptor.code

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(
            [
                {
                    "date": bar.trading_date.isoformat(),
                    "open": str(bar.open_price),
                    "high": str(bar.high_price),
                    "low": str(bar.low_price),
                    "close": str(bar.close_price),
                    "adjustedClose": (
                        str(bar.adjusted_close)
                        if bar.adjusted_close is not None
                        else None
                    ),
                    "volume": bar.volume,
                }
                for bar in self.bars
            ],
            sort_keys=True,
            separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    @classmethod
    def now(cls) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class CorporateAction:
    action_type: str
    effective_date: date
    amount: Decimal | None = None
    currency: str | None = None
    split_from: Decimal | None = None
    split_to: Decimal | None = None


@dataclass(frozen=True)
class CorporateActionSeries:
    provider_descriptor: ProviderDescriptor
    requested_symbol: str
    provider_symbol: str
    actions: tuple[CorporateAction, ...]
    source_reference: str
    available_at: datetime
    status: CapabilityStatus = CapabilityStatus.SUPPORTED
