from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

TACTICAL_SIGNAL_V22_VERSION = "TACTICAL-SIGNAL-v2.2.0"
TACTICAL_INPUT_V22_SCHEMA = "TACTICAL-INPUT-v2.2.0"
TACTICAL_FEATURE_V22_VERSION = "TACTICAL-FEATURES-v2.2.0"


class EvidenceState(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SetupThesis(StrEnum):
    NONE = "NONE"
    CONTINUATION = "CONTINUATION"
    MEAN_REVERSION = "MEAN_REVERSION"
    CONFLICT = "CONFLICT"


class TacticalHorizon(StrEnum):
    ONE_WEEK = "ONE_WEEK"
    ONE_MONTH = "ONE_MONTH"
    THREE_MONTHS = "THREE_MONTHS"

    @property
    def trading_days(self) -> int:
        return {
            TacticalHorizon.ONE_WEEK: 5,
            TacticalHorizon.ONE_MONTH: 20,
            TacticalHorizon.THREE_MONTHS: 60,
        }[self]


class HorizonOutlook(StrEnum):
    FAVORABLE = "FAVORABLE"
    NEUTRAL = "NEUTRAL"
    UNFAVORABLE = "UNFAVORABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class Actionability(StrEnum):
    WATCH_ONLY = "WATCH_ONLY"
    WAIT_FOR_PULLBACK = "WAIT_FOR_PULLBACK"
    LIMITED_ENTRY = "LIMITED_ENTRY"
    ENTRY = "ENTRY"
    RISK_BLOCKED = "RISK_BLOCKED"
    NO_SETUP = "NO_SETUP"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class EventRiskLevel(StrEnum):
    NONE = "NONE"
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


@dataclass(frozen=True)
class TacticalBarV22:
    trading_date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    adjustment_factor: float = 1.0
    session_complete: bool = True


@dataclass(frozen=True)
class SeriesEvidenceV22:
    state: EvidenceState
    provider: str | None
    source_hash: str | None
    available_at: datetime | None
    ingested_at: datetime | None
    bars: tuple[TacticalBarV22, ...] = ()


@dataclass(frozen=True)
class EventEvidenceV22:
    state: EvidenceState
    risk_level: EventRiskLevel | None
    source_hash: str | None
    available_at: datetime | None
    ingested_at: datetime | None
    event_type: str | None = None
    event_at: datetime | None = None


@dataclass(frozen=True)
class TacticalContextV22:
    security_id: str
    decision_cutoff: datetime
    as_of_date: date
    security: SeriesEvidenceV22
    market_benchmark_id: str
    market: SeriesEvidenceV22
    sector_benchmark_id: str | None
    sector: SeriesEvidenceV22
    event: EventEvidenceV22
    sector_mapping_version: str
    sector_mapping_hash: str


@dataclass(frozen=True)
class ComponentScoreV22:
    state: EvidenceState
    score: float | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class HorizonAssessmentV22:
    horizon: TacticalHorizon
    trading_days: int
    selected_thesis: SetupThesis
    continuation_eligible: bool
    mean_reversion_eligible: bool
    continuation_score: float | None
    mean_reversion_score: float | None
    opportunity_score: float | None
    entry_value_score: float | None
    risk_score: float | None
    outlook: HorizonOutlook
    actionability: Actionability
    confidence: str
    maximum_risk_unit_multiplier: float
    missing_inputs: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TacticalAssessmentV22:
    version: str
    input_schema_version: str
    feature_version: str
    input_hash: str
    decision_domain: str
    data_cadence: str
    as_of_date: date
    decision_cutoff: datetime
    effective_from: str
    signal_ttl_completed_sessions: int
    security_id: str
    market_benchmark_id: str
    sector_benchmark_id: str | None
    continuation_quality: ComponentScoreV22
    mean_reversion_potential: ComponentScoreV22
    rebound_readiness: ComponentScoreV22
    falling_knife_risk: ComponentScoreV22
    chase_risk: ComponentScoreV22
    volatility_risk: ComponentScoreV22
    liquidity: ComponentScoreV22
    market_regime: ComponentScoreV22
    sector_regime: ComponentScoreV22
    market_relative_strength: ComponentScoreV22
    sector_relative_strength: ComponentScoreV22
    event_risk_state: EvidenceState
    event_risk_level: EventRiskLevel | None
    horizons: tuple[HorizonAssessmentV22, ...]
    warnings: tuple[str, ...]
