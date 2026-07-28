"""Stable provider-neutral interfaces for versioned analytics models."""

from equity_analysis.analytics_interface.contracts import (
    AiBoundary,
    AnalyticsInputCapability,
    AnalyticsModelId,
    LongHorizonModelRequest,
    ModelResultEnvelope,
    ModelTiming,
    ProviderProvenance,
    RequestEvidence,
    TacticalModelRequest,
)
from equity_analysis.analytics_interface.providers import (
    DailyPriceAnalyticsAdapter,
    LongHorizonInputSnapshot,
    PreassembledLongHorizonAdapter,
    TacticalInputQuery,
    create_daily_price_analytics_adapter,
)
from equity_analysis.analytics_interface.runtime import (
    AnalyticsModelFacade,
    AnalyticsModelRegistry,
    create_default_model_facade,
)

__all__ = [
    "AiBoundary",
    "AnalyticsInputCapability",
    "AnalyticsModelFacade",
    "AnalyticsModelId",
    "AnalyticsModelRegistry",
    "DailyPriceAnalyticsAdapter",
    "LongHorizonInputSnapshot",
    "LongHorizonModelRequest",
    "ModelResultEnvelope",
    "ModelTiming",
    "PreassembledLongHorizonAdapter",
    "ProviderProvenance",
    "RequestEvidence",
    "TacticalInputQuery",
    "TacticalModelRequest",
    "create_daily_price_analytics_adapter",
    "create_default_model_facade",
]
