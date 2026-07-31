from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from equity_analysis.market_data.models import ProviderDescriptor
from equity_analysis.provider_validation.models import NormalizedFinancialObservation

CURRENT_CLASSIFICATION_TAXONOMY = "PROVIDER_CURRENT"
CURRENT_CLASSIFICATION_TAXONOMY_VERSION = "v1.0.0"
CURRENT_ONLY_SEMANTICS = "CURRENT_ONLY"
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class ObservationState(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    INVALID = "INVALID"


@dataclass(frozen=True)
class CurrentCompanyProfileObservation:
    state: ObservationState
    effective_at: datetime
    legal_name: str | None = None
    taxonomy_code: str | None = None
    taxonomy_version: str | None = None
    sector_code: str | None = None
    sector_name: str | None = None
    industry_code: str | None = None
    industry_name: str | None = None
    reason_code: str | None = None
    semantics: str = CURRENT_ONLY_SEMANTICS

    def __post_init__(self) -> None:
        values = (
            self.legal_name,
            self.taxonomy_code,
            self.taxonomy_version,
            self.sector_code,
            self.sector_name,
            self.industry_code,
            self.industry_name,
        )
        if self.effective_at.tzinfo is None:
            raise ValueError("Current profile effective time must include a timezone")
        if self.semantics != CURRENT_ONLY_SEMANTICS:
            raise ValueError("Company profile observations must be current-only")
        if self.state == ObservationState.VALID:
            if any(value is None for value in values) or self.reason_code is not None:
                raise ValueError("VALID company profiles require complete classification")
        elif any(value is not None for value in values) or not self.reason_code:
            raise ValueError("Non-VALID company profiles require only a reason code")


@dataclass(frozen=True)
class CurrentMarketCapitalizationObservation:
    state: ObservationState
    effective_at: datetime
    value: Decimal | None = None
    currency: str | None = None
    reason_code: str | None = None
    semantics: str = CURRENT_ONLY_SEMANTICS

    def __post_init__(self) -> None:
        if self.effective_at.tzinfo is None:
            raise ValueError("Current market-cap time must include a timezone")
        if self.semantics != CURRENT_ONLY_SEMANTICS:
            raise ValueError("Market-cap observations must be current-only")
        if self.state == ObservationState.VALID:
            if (
                self.value is None
                or self.value <= 0
                or self.currency is None
                or len(self.currency) != 3
                or self.reason_code is not None
            ):
                raise ValueError("VALID market capitalization requires value and currency")
        elif self.value is not None or self.currency is not None or not self.reason_code:
            raise ValueError("Non-VALID market capitalization requires only a reason code")


@dataclass(frozen=True)
class FundamentalsEnvelope:
    provider_descriptor: ProviderDescriptor
    requested_symbol: str
    provider_symbol: str
    source_reference: str
    content_hash: str
    available_at: datetime
    retrieved_at: datetime
    financial_observations: tuple[NormalizedFinancialObservation, ...]
    company_profile: CurrentCompanyProfileObservation
    market_capitalization: CurrentMarketCapitalizationObservation
    semantics: str = CURRENT_ONLY_SEMANTICS

    def __post_init__(self) -> None:
        if not self.requested_symbol or not self.provider_symbol:
            raise ValueError("Fundamentals envelope requires provider and requested symbols")
        if not self.source_reference:
            raise ValueError("Fundamentals envelope requires a source reference")
        if not _SHA256_PATTERN.fullmatch(self.content_hash):
            raise ValueError("Fundamentals envelope requires an exact SHA-256 source hash")
        if self.available_at.tzinfo is None or self.retrieved_at.tzinfo is None:
            raise ValueError("Fundamentals envelope timestamps must include timezones")
        if self.retrieved_at < self.available_at:
            raise ValueError("Fundamentals retrieval cannot precede availability")
        if self.semantics != CURRENT_ONLY_SEMANTICS:
            raise ValueError("Fundamentals envelopes must be current-only")
        if not self.financial_observations:
            raise ValueError("Fundamentals envelope requires financial observations")
        symbols = {item.symbol for item in self.financial_observations}
        if symbols != {self.requested_symbol}:
            raise ValueError("Financial observations must match the envelope symbol")
        effective_at = self.company_profile.effective_at
        if effective_at != self.market_capitalization.effective_at:
            raise ValueError("Current observations must share one effective boundary")

    @property
    def effective_at(self) -> datetime:
        return self.company_profile.effective_at


def normalize_current_company_profile(
    *,
    legal_name: object,
    sector: object,
    industry: object,
    effective_at: datetime,
) -> CurrentCompanyProfileObservation:
    fields = (
        ("PROFILE_LEGAL_NAME", legal_name, 255),
        ("PROFILE_SECTOR", sector, 255),
        ("PROFILE_INDUSTRY", industry, 255),
    )
    normalized: list[str] = []
    for code, value, maximum_length in fields:
        if value is None or (isinstance(value, str) and not value.strip()):
            return CurrentCompanyProfileObservation(
                state=ObservationState.MISSING,
                effective_at=effective_at,
                reason_code=f"{code}_MISSING",
            )
        if not isinstance(value, str) or len(value.strip()) > maximum_length:
            return CurrentCompanyProfileObservation(
                state=ObservationState.INVALID,
                effective_at=effective_at,
                reason_code=f"{code}_INVALID",
            )
        normalized.append(" ".join(value.split()))
    name, sector_name, industry_name = normalized
    return CurrentCompanyProfileObservation(
        state=ObservationState.VALID,
        effective_at=effective_at,
        legal_name=name,
        taxonomy_code=CURRENT_CLASSIFICATION_TAXONOMY,
        taxonomy_version=CURRENT_CLASSIFICATION_TAXONOMY_VERSION,
        sector_code=_classification_code("SECTOR", sector_name),
        sector_name=sector_name,
        industry_code=_classification_code(
            "INDUSTRY",
            f"{sector_name.casefold()}\0{industry_name.casefold()}",
        ),
        industry_name=industry_name,
    )


def normalize_current_market_capitalization(
    *,
    value: object,
    currency: object,
    effective_at: datetime,
) -> CurrentMarketCapitalizationObservation:
    if value is None or (isinstance(value, str) and not value.strip()):
        return CurrentMarketCapitalizationObservation(
            state=ObservationState.MISSING,
            effective_at=effective_at,
            reason_code="MARKET_CAP_MISSING",
        )
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        parsed = Decimal("NaN")
    if not parsed.is_finite() or parsed <= 0:
        return CurrentMarketCapitalizationObservation(
            state=ObservationState.INVALID,
            effective_at=effective_at,
            reason_code="MARKET_CAP_INVALID",
        )
    if currency is None or (isinstance(currency, str) and not currency.strip()):
        return CurrentMarketCapitalizationObservation(
            state=ObservationState.MISSING,
            effective_at=effective_at,
            reason_code="MARKET_CAP_CURRENCY_MISSING",
        )
    if not isinstance(currency, str) or len(currency.strip()) != 3:
        return CurrentMarketCapitalizationObservation(
            state=ObservationState.INVALID,
            effective_at=effective_at,
            reason_code="MARKET_CAP_CURRENCY_INVALID",
        )
    return CurrentMarketCapitalizationObservation(
        state=ObservationState.VALID,
        effective_at=effective_at,
        value=parsed,
        currency=currency.strip().upper(),
    )


def _classification_code(level: str, value: str) -> str:
    digest = hashlib.sha256(value.casefold().encode()).hexdigest()[:24].upper()
    return f"{level}-{digest}"
