from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from equity_analysis.analytics_interface.contracts import (
    AnalyticsCapabilityError,
    AnalyticsInputCapability,
    LongHorizonModelRequest,
    ModelTiming,
    ProviderProvenance,
    RequestEvidence,
    TacticalModelRequest,
    canonical_hash,
)
from equity_analysis.config import Settings
from equity_analysis.market_data.factory import create_market_data_provider
from equity_analysis.market_data.models import (
    AdjustmentMode,
    DailyPriceBar,
    DailyPriceSeries,
    ProviderCapability,
)
from equity_analysis.market_data.provider import DailyPriceProvider
from equity_analysis.research_rating.long_horizon_v1 import LongHorizonInputs
from equity_analysis.tactical.signal_v2 import TacticalBar


class AnalyticsInputAdapter(Protocol):
    @property
    def capabilities(self) -> frozenset[AnalyticsInputCapability]: ...


@dataclass(frozen=True)
class TacticalInputQuery:
    symbol: str
    benchmark_symbol: str
    start_date: date
    end_date: date
    timing: ModelTiming
    event_drift_score: float = 50.0


@dataclass(frozen=True)
class LongHorizonInputSnapshot:
    timing: ModelTiming
    inputs: LongHorizonInputs
    evidence: RequestEvidence


class DailyPriceAnalyticsAdapter:
    """Translate any normalized daily-price provider into a tactical request.

    EODHD, yfinance, Twelve Data, or a future provider can use this boundary
    without exposing provider-native symbols or response fields to the model.
    """

    def __init__(self, provider: DailyPriceProvider) -> None:
        self._provider = provider

    @property
    def capabilities(self) -> frozenset[AnalyticsInputCapability]:
        if ProviderCapability.DAILY_PRICES not in self._provider.descriptor.capabilities:
            return frozenset()
        return frozenset({AnalyticsInputCapability.ADJUSTED_DAILY_PRICES})

    def build_tactical_request(self, query: TacticalInputQuery) -> TacticalModelRequest:
        self._require(AnalyticsInputCapability.ADJUSTED_DAILY_PRICES)
        security = self._provider.fetch_daily_prices(
            query.symbol,
            query.start_date,
            query.end_date,
        )
        benchmark = self._provider.fetch_daily_prices(
            query.benchmark_symbol,
            query.start_date,
            query.end_date,
        )
        security_bars = _normalized_tactical_bars(security)
        benchmark_bars = _normalized_tactical_bars(benchmark)
        providers = (_provenance(security), _provenance(benchmark))
        evidence_hash = canonical_hash(
            {
                "providerEvidence": [
                    {
                        "providerCode": item.provider_code,
                        "sourceReference": item.source_reference,
                        "contentHash": item.content_hash,
                    }
                    for item in providers
                ]
            }
        )
        return TacticalModelRequest(
            symbol=query.symbol.strip().upper(),
            benchmark_symbol=query.benchmark_symbol.strip().upper(),
            timing=query.timing,
            evidence=RequestEvidence(
                evidence_hash=evidence_hash,
                providers=providers,
            ),
            security_bars=security_bars,
            benchmark_bars=benchmark_bars,
            event_drift_score=query.event_drift_score,
        )

    def build_long_horizon_request(
        self,
        _snapshot: LongHorizonInputSnapshot,
    ) -> LongHorizonModelRequest:
        self._require(AnalyticsInputCapability.NORMALIZED_LONG_HORIZON_INPUTS)
        raise AssertionError("Capability check did not fail")

    def _require(self, capability: AnalyticsInputCapability) -> None:
        if capability not in self.capabilities:
            raise AnalyticsCapabilityError(
                (
                    f"Provider {self._provider.descriptor.code} does not expose "
                    f"{capability.value} through this analytics adapter"
                ),
                "ANALYTICS_INPUT_CAPABILITY_UNSUPPORTED",
            )


class PreassembledLongHorizonAdapter:
    """Accept an upstream provider-neutral factor snapshot.

    Provider-specific financial parsing remains upstream. This adapter prevents
    native provider field names from becoming part of the rating contract.
    """

    @property
    def capabilities(self) -> frozenset[AnalyticsInputCapability]:
        return frozenset(
            {AnalyticsInputCapability.NORMALIZED_LONG_HORIZON_INPUTS}
        )

    @staticmethod
    def build_long_horizon_request(
        snapshot: LongHorizonInputSnapshot,
    ) -> LongHorizonModelRequest:
        return LongHorizonModelRequest(
            timing=snapshot.timing,
            evidence=snapshot.evidence,
            inputs=snapshot.inputs,
        )


def create_daily_price_analytics_adapter(
    settings: Settings,
) -> DailyPriceAnalyticsAdapter:
    """Reuse the configured provider factory behind the analytics boundary."""

    return DailyPriceAnalyticsAdapter(create_market_data_provider(settings))


def _normalized_tactical_bars(series: DailyPriceSeries) -> tuple[TacticalBar, ...]:
    if (
        series.adjustment_mode == AdjustmentMode.UNADJUSTED
        and any(bar.adjusted_close is None for bar in series.bars)
    ):
        raise AnalyticsCapabilityError(
            "Tactical input requires split-adjusted prices",
            "ADJUSTED_DAILY_PRICES_REQUIRED",
        )
    return tuple(_normalized_tactical_bar(bar) for bar in series.bars)


def _normalized_tactical_bar(bar: DailyPriceBar) -> TacticalBar:
    factor = (
        bar.adjusted_close / bar.close_price
        if bar.adjusted_close is not None and bar.close_price != 0
        else Decimal("1")
    )
    return TacticalBar(
        trading_date=bar.trading_date,
        open_price=float(bar.open_price * factor),
        high_price=float(bar.high_price * factor),
        low_price=float(bar.low_price * factor),
        close_price=float(
            bar.adjusted_close
            if bar.adjusted_close is not None
            else bar.close_price
        ),
        volume=bar.volume,
        adjustment_factor=float(factor),
        session_complete=True,
    )


def _provenance(series: DailyPriceSeries) -> ProviderProvenance:
    descriptor = series.provider_descriptor
    return ProviderProvenance(
        provider_code=descriptor.code,
        provider_schema_version=descriptor.provider_schema_version,
        parser_version=descriptor.parser_version,
        source_reference=series.source_reference,
        content_hash=series.content_hash,
        available_at=series.available_at,
        retrieved_at=series.retrieved_at,
        adjustment_mode=series.adjustment_mode.value,
    )
