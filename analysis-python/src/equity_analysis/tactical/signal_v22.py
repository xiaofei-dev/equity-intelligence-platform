from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import date, datetime
from statistics import fmean
from typing import Any

from equity_analysis.tactical.contracts_v22 import (
    TACTICAL_FEATURE_V22_VERSION,
    TACTICAL_INPUT_V22_SCHEMA,
    TACTICAL_SIGNAL_V22_VERSION,
    Actionability,
    ComponentScoreV22,
    EventEvidenceV22,
    EventRiskLevel,
    EvidenceState,
    HorizonAssessmentV22,
    HorizonOutlook,
    SeriesEvidenceV22,
    SetupThesis,
    TacticalAssessmentV22,
    TacticalBarV22,
    TacticalContextV22,
    TacticalHorizon,
)
from equity_analysis.tactical.features_v22 import (
    TacticalFeatureSetV22,
    clip,
    extract_features_v22,
)

_HASH_PATTERN = re.compile(r"(?:sha256:)?[0-9a-fA-F]{64}")


def _json_default(value: Any) -> str:
    if isinstance(value, date | datetime):
        return value.isoformat()
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        default=_json_default,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest().upper()


def _require_hash(value: str | None, label: str) -> None:
    if value is None or _HASH_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a SHA-256 value")


def _require_aware(value: datetime | None, label: str) -> None:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _validate_bar(bar: TacticalBarV22) -> None:
    if not bar.session_complete:
        raise ValueError("Tactical v2.2 rejects incomplete sessions")
    if (
        bar.open_price <= 0
        or bar.high_price <= 0
        or bar.low_price <= 0
        or bar.close_price <= 0
        or bar.volume <= 0
        or bar.adjustment_factor <= 0
    ):
        raise ValueError(
            "Tactical bars require positive adjusted OHLCV and adjustment factors"
        )
    if bar.high_price < max(
        bar.open_price,
        bar.close_price,
        bar.low_price,
    ):
        raise ValueError("Bar high must not be below open, close, or low")
    if bar.low_price > min(
        bar.open_price,
        bar.close_price,
        bar.high_price,
    ):
        raise ValueError("Bar low must not be above open, close, or high")


def _validate_series(
    evidence: SeriesEvidenceV22,
    *,
    label: str,
    context: TacticalContextV22,
) -> None:
    if evidence.state != EvidenceState.VALID:
        return
    if not evidence.provider or not evidence.provider.strip():
        raise ValueError(f"{label} provider is required for valid evidence")
    _require_hash(evidence.source_hash, f"{label} source_hash")
    _require_aware(evidence.available_at, f"{label} available_at")
    _require_aware(evidence.ingested_at, f"{label} ingested_at")
    if evidence.available_at > context.decision_cutoff:
        raise ValueError(f"{label} evidence was not available at the decision cutoff")
    if evidence.ingested_at > context.decision_cutoff:
        raise ValueError(f"{label} evidence was ingested after the decision cutoff")
    if not evidence.bars:
        raise ValueError(f"{label} valid evidence requires bars")
    dates = tuple(item.trading_date for item in evidence.bars)
    if tuple(sorted(dates)) != dates or len(set(dates)) != len(dates):
        raise ValueError(f"{label} bars must be chronological and unique")
    for bar in evidence.bars:
        _validate_bar(bar)
        if bar.trading_date > context.as_of_date:
            raise ValueError(f"{label} contains a future session")


def _validate_event(event: EventEvidenceV22, context: TacticalContextV22) -> None:
    if event.state == EvidenceState.VALID:
        if event.risk_level is None:
            raise ValueError("Valid event evidence requires an explicit risk level")
        _require_hash(event.source_hash, "event source_hash")
        _require_aware(event.available_at, "event available_at")
        _require_aware(event.ingested_at, "event ingested_at")
        if event.available_at > context.decision_cutoff:
            raise ValueError("Event evidence was not available at the decision cutoff")
        if event.ingested_at > context.decision_cutoff:
            raise ValueError("Event evidence was ingested after the decision cutoff")
    elif event.risk_level is not None:
        raise ValueError("Non-valid event evidence cannot carry a risk level")


def _validate_context(context: TacticalContextV22) -> None:
    if not context.security_id.strip():
        raise ValueError("security_id is required")
    if not context.market_benchmark_id.strip():
        raise ValueError("market_benchmark_id is required")
    if not context.sector_mapping_version.strip():
        raise ValueError("sector_mapping_version is required")
    _require_hash(context.sector_mapping_hash, "sector_mapping_hash")
    _require_aware(context.decision_cutoff, "decision_cutoff")
    if context.as_of_date > context.decision_cutoff.date():
        raise ValueError("as_of_date cannot be after the decision cutoff")
    _validate_series(context.security, label="security", context=context)
    _validate_series(context.market, label="market", context=context)
    _validate_series(context.sector, label="sector", context=context)
    _validate_event(context.event, context)


def _align(
    context: TacticalContextV22,
) -> tuple[
    tuple[TacticalBarV22, ...],
    tuple[TacticalBarV22, ...],
    tuple[TacticalBarV22, ...],
]:
    security = {item.trading_date: item for item in context.security.bars}
    market = {item.trading_date: item for item in context.market.bars}
    sector = {item.trading_date: item for item in context.sector.bars}
    shared_dates = tuple(sorted(security.keys() & market.keys() & sector.keys()))
    if len(shared_dates) < 21:
        raise ValueError("Tactical v2.2 requires at least 21 shared completed sessions")
    if shared_dates[-1] != context.as_of_date:
        raise ValueError("All price series must include the as-of completed session")
    return (
        tuple(security[item] for item in shared_dates),
        tuple(market[item] for item in shared_dates),
        tuple(sector[item] for item in shared_dates),
    )


def _missing_component(
    state: EvidenceState,
    reason: str,
) -> ComponentScoreV22:
    return ComponentScoreV22(state=state, score=None, reasons=(reason,))


def _outlook(score: float | None) -> HorizonOutlook:
    if score is None:
        return HorizonOutlook.INSUFFICIENT_DATA
    if score >= 60:
        return HorizonOutlook.FAVORABLE
    if score >= 40:
        return HorizonOutlook.NEUTRAL
    return HorizonOutlook.UNFAVORABLE


def _required_series_missing(context: TacticalContextV22) -> tuple[str, ...]:
    missing: list[str] = []
    if context.security.state != EvidenceState.VALID:
        missing.append("security_completed_daily_prices")
    if context.market.state != EvidenceState.VALID:
        missing.append("market_benchmark_completed_daily_prices")
    if context.sector.state != EvidenceState.VALID:
        missing.append("sector_benchmark_completed_daily_prices")
    if not context.sector_benchmark_id:
        missing.append("sector_benchmark_identity")
    return tuple(missing)


def _insufficient_assessment(
    context: TacticalContextV22,
    input_hash: str,
    missing: tuple[str, ...],
) -> TacticalAssessmentV22:
    first_state = next(
        (
            evidence.state
            for evidence in (context.security, context.market, context.sector)
            if evidence.state != EvidenceState.VALID
        ),
        EvidenceState.MISSING,
    )
    unavailable = _missing_component(
        first_state,
        "A required price series is not valid; no neutral value was substituted.",
    )
    market_component = _missing_component(
        context.market.state,
        "Market regime requires valid completed benchmark sessions.",
    )
    sector_component = _missing_component(
        context.sector.state,
        "Sector regime requires valid completed benchmark sessions.",
    )
    horizons = tuple(
        HorizonAssessmentV22(
            horizon=horizon,
            trading_days=horizon.trading_days,
            selected_thesis=SetupThesis.NONE,
            continuation_eligible=False,
            mean_reversion_eligible=False,
            continuation_score=None,
            mean_reversion_score=None,
            opportunity_score=None,
            entry_value_score=None,
            risk_score=None,
            outlook=HorizonOutlook.INSUFFICIENT_DATA,
            actionability=Actionability.INSUFFICIENT_DATA,
            confidence="LOW",
            maximum_risk_unit_multiplier=0.0,
            missing_inputs=missing,
            reasons=(
                "Required evidence is missing, stale, invalid, or not applicable.",
            ),
        )
        for horizon in TacticalHorizon
    )
    return TacticalAssessmentV22(
        version=TACTICAL_SIGNAL_V22_VERSION,
        input_schema_version=TACTICAL_INPUT_V22_SCHEMA,
        feature_version=TACTICAL_FEATURE_V22_VERSION,
        input_hash=input_hash,
        decision_domain="SHORT_TERM_SPECULATION",
        data_cadence="COMPLETED_DAILY_SESSION",
        as_of_date=context.as_of_date,
        decision_cutoff=context.decision_cutoff,
        effective_from="NEXT_COMPLETED_SESSION_OPEN",
        signal_ttl_completed_sessions=1,
        security_id=context.security_id,
        market_benchmark_id=context.market_benchmark_id,
        sector_benchmark_id=context.sector_benchmark_id,
        continuation_quality=unavailable,
        mean_reversion_potential=unavailable,
        rebound_readiness=unavailable,
        falling_knife_risk=unavailable,
        chase_risk=unavailable,
        volatility_risk=unavailable,
        liquidity=unavailable,
        market_regime=market_component,
        sector_regime=sector_component,
        market_relative_strength=unavailable,
        sector_relative_strength=unavailable,
        event_risk_state=context.event.state,
        event_risk_level=context.event.risk_level,
        horizons=horizons,
        warnings=(
            "Tactical v2.2 preserved the invalid evidence state and abstained.",
        ),
    )


def _average_component(
    values: dict[TacticalHorizon, float],
    reason: str,
) -> ComponentScoreV22:
    if not values:
        return _missing_component(EvidenceState.MISSING, reason)
    return ComponentScoreV22(
        state=EvidenceState.VALID,
        score=round(fmean(values.values()), 2),
        reasons=(reason,),
    )


def _select_thesis(
    continuation_eligible: bool,
    mean_reversion_eligible: bool,
) -> SetupThesis:
    if continuation_eligible and mean_reversion_eligible:
        return SetupThesis.CONFLICT
    if continuation_eligible:
        return SetupThesis.CONTINUATION
    if mean_reversion_eligible:
        return SetupThesis.MEAN_REVERSION
    return SetupThesis.NONE


def _score_or(component: ComponentScoreV22, fallback: float) -> float:
    return component.score if component.score is not None else fallback


def _entry_action(
    *,
    thesis: SetupThesis,
    features: TacticalFeatureSetV22,
    context: TacticalContextV22,
    entry_value: float | None,
) -> Actionability:
    if thesis == SetupThesis.NONE:
        return Actionability.NO_SETUP
    if thesis == SetupThesis.CONFLICT:
        return Actionability.WATCH_ONLY
    if features.liquidity.state != EvidenceState.VALID:
        return Actionability.RISK_BLOCKED
    if features.liquidity.score is None or features.liquidity.score < 35:
        return Actionability.RISK_BLOCKED
    if features.volatility_risk.score is None or features.volatility_risk.score >= 80:
        return Actionability.RISK_BLOCKED
    if context.event.state != EvidenceState.VALID:
        return Actionability.WATCH_ONLY
    if context.event.risk_level == EventRiskLevel.HIGH:
        return Actionability.RISK_BLOCKED
    if thesis == SetupThesis.CONTINUATION:
        if features.chase_risk.score is None or features.chase_risk.score >= 60:
            return Actionability.WAIT_FOR_PULLBACK
        if entry_value is None or entry_value < 60:
            return Actionability.WAIT_FOR_PULLBACK
    elif entry_value is None or entry_value < 55:
        return Actionability.WATCH_ONLY
    if features.liquidity.score < 50:
        return Actionability.LIMITED_ENTRY
    if context.event.risk_level == EventRiskLevel.ELEVATED:
        return Actionability.LIMITED_ENTRY
    if thesis == SetupThesis.MEAN_REVERSION:
        return Actionability.LIMITED_ENTRY
    return Actionability.ENTRY


def _horizon_assessment(
    horizon: TacticalHorizon,
    features: TacticalFeatureSetV22,
    context: TacticalContextV22,
    aligned_count: int,
) -> HorizonAssessmentV22:
    continuation = features.continuation_by_horizon.get(horizon)
    mean_reversion = features.mean_reversion_by_horizon.get(horizon)
    missing: list[str] = []
    if continuation is None or mean_reversion is None:
        missing.append(f"{horizon.value.lower()}_completed_history")
        return HorizonAssessmentV22(
            horizon=horizon,
            trading_days=horizon.trading_days,
            selected_thesis=SetupThesis.NONE,
            continuation_eligible=False,
            mean_reversion_eligible=False,
            continuation_score=None,
            mean_reversion_score=None,
            opportunity_score=None,
            entry_value_score=None,
            risk_score=None,
            outlook=HorizonOutlook.INSUFFICIENT_DATA,
            actionability=Actionability.INSUFFICIENT_DATA,
            confidence="LOW",
            maximum_risk_unit_multiplier=0.0,
            missing_inputs=tuple(missing),
            reasons=("The horizon lacks its complete lookback window.",),
        )

    continuation_threshold = {
        TacticalHorizon.ONE_WEEK: 58.0,
        TacticalHorizon.ONE_MONTH: 60.0,
        TacticalHorizon.THREE_MONTHS: 62.0,
    }[horizon]
    reversion_threshold = {
        TacticalHorizon.ONE_WEEK: 60.0,
        TacticalHorizon.ONE_MONTH: 58.0,
        TacticalHorizon.THREE_MONTHS: 56.0,
    }[horizon]
    readiness_threshold = {
        TacticalHorizon.ONE_WEEK: 55.0,
        TacticalHorizon.ONE_MONTH: 52.0,
        TacticalHorizon.THREE_MONTHS: 48.0,
    }[horizon]
    market_regime = features.market_regime.score or 0.0
    sector_regime = features.sector_regime.score or 0.0
    continuation_eligible = (
        continuation >= continuation_threshold
        and not (market_regime < 35 and sector_regime < 35)
    )
    mean_reversion_eligible = (
        mean_reversion >= reversion_threshold
        and _score_or(features.mean_reversion_potential, 0.0) >= 60
        and _score_or(features.rebound_readiness, 0.0) >= readiness_threshold
        and _score_or(features.falling_knife_risk, 100.0) < 70
        and features.reversal_structure_present
    )
    thesis = _select_thesis(continuation_eligible, mean_reversion_eligible)
    opportunity = max(continuation, mean_reversion)
    entry_value = (
        features.continuation_entry_value
        if thesis == SetupThesis.CONTINUATION
        else features.mean_reversion_entry_value
        if thesis == SetupThesis.MEAN_REVERSION
        else None
    )
    risk = max(
        _score_or(features.volatility_risk, 100.0),
        _score_or(features.chase_risk, 100.0)
        if thesis == SetupThesis.CONTINUATION
        else _score_or(features.falling_knife_risk, 100.0),
    )
    actionability = _entry_action(
        thesis=thesis,
        features=features,
        context=context,
        entry_value=entry_value,
    )
    if context.event.state != EvidenceState.VALID:
        missing.append("deterministic_event_risk")
    reasons = [
        "Continuation and mean reversion were evaluated independently.",
    ]
    if thesis == SetupThesis.NONE:
        reasons.append("Neither thesis passed its horizon-specific eligibility gates.")
    elif thesis == SetupThesis.CONFLICT:
        reasons.append("Both theses passed; the unresolved conflict prevents an entry.")
    elif thesis == SetupThesis.CONTINUATION:
        reasons.append("Continuation alone passed the horizon-specific gates.")
    else:
        reasons.append("Mean reversion alone passed the horizon-specific gates.")
    if actionability == Actionability.WAIT_FOR_PULLBACK:
        reasons.append("Chase risk or entry value requires a pullback.")
    if context.event.state != EvidenceState.VALID:
        reasons.append("Unknown event risk caps actionability without a neutral substitute.")

    confidence = (
        "LOW"
        if missing or aligned_count < 90
        else "MEDIUM"
        if aligned_count < 126 or risk >= 60
        else "HIGH"
    )
    maximum_risk_unit_multiplier = (
        1.0
        if actionability == Actionability.ENTRY
        else 0.25
        if actionability == Actionability.LIMITED_ENTRY
        else 0.0
    )
    return HorizonAssessmentV22(
        horizon=horizon,
        trading_days=horizon.trading_days,
        selected_thesis=thesis,
        continuation_eligible=continuation_eligible,
        mean_reversion_eligible=mean_reversion_eligible,
        continuation_score=round(continuation, 2),
        mean_reversion_score=round(mean_reversion, 2),
        opportunity_score=round(opportunity, 2),
        entry_value_score=(
            round(entry_value, 2) if entry_value is not None else None
        ),
        risk_score=round(clip(risk), 2),
        outlook=_outlook(opportunity),
        actionability=actionability,
        confidence=confidence,
        maximum_risk_unit_multiplier=maximum_risk_unit_multiplier,
        missing_inputs=tuple(missing),
        reasons=tuple(reasons),
    )


def evaluate_tactical_signal_v22(
    context: TacticalContextV22,
) -> TacticalAssessmentV22:
    """Evaluate independent tactical theses using completed, cutoff-valid evidence."""

    _validate_context(context)
    input_hash = _canonical_hash(asdict(context))
    missing = _required_series_missing(context)
    if missing:
        return _insufficient_assessment(context, input_hash, missing)

    security, market, sector = _align(context)
    features = extract_features_v22(security, market, sector)
    horizons = tuple(
        _horizon_assessment(
            horizon,
            features,
            context,
            len(security),
        )
        for horizon in TacticalHorizon
    )
    warnings: list[str] = []
    if context.event.state != EvidenceState.VALID:
        warnings.append(
            "Deterministic event evidence is unavailable; no neutral event score was used."
        )
    if features.liquidity.state != EvidenceState.VALID:
        warnings.append(
            "Liquidity evidence is invalid because recent adjustment semantics changed."
        )
    if any(
        item.actionability == Actionability.RISK_BLOCKED for item in horizons
    ):
        warnings.append("At least one horizon is blocked by a non-compensating risk gate.")

    return TacticalAssessmentV22(
        version=TACTICAL_SIGNAL_V22_VERSION,
        input_schema_version=TACTICAL_INPUT_V22_SCHEMA,
        feature_version=TACTICAL_FEATURE_V22_VERSION,
        input_hash=input_hash,
        decision_domain="SHORT_TERM_SPECULATION",
        data_cadence="COMPLETED_DAILY_SESSION",
        as_of_date=context.as_of_date,
        decision_cutoff=context.decision_cutoff,
        effective_from="NEXT_COMPLETED_SESSION_OPEN",
        signal_ttl_completed_sessions=1,
        security_id=context.security_id,
        market_benchmark_id=context.market_benchmark_id,
        sector_benchmark_id=context.sector_benchmark_id,
        continuation_quality=_average_component(
            features.continuation_by_horizon,
            "Continuation quality is the mean of available horizon-specific scores.",
        ),
        mean_reversion_potential=features.mean_reversion_potential,
        rebound_readiness=features.rebound_readiness,
        falling_knife_risk=features.falling_knife_risk,
        chase_risk=features.chase_risk,
        volatility_risk=features.volatility_risk,
        liquidity=features.liquidity,
        market_regime=features.market_regime,
        sector_regime=features.sector_regime,
        market_relative_strength=_average_component(
            features.market_relative_by_horizon,
            "Market-relative strength is evaluated independently by horizon.",
        ),
        sector_relative_strength=_average_component(
            features.sector_relative_by_horizon,
            "Sector-relative strength is evaluated independently by horizon.",
        ),
        event_risk_state=context.event.state,
        event_risk_level=context.event.risk_level,
        horizons=horizons,
        warnings=tuple(warnings),
    )


def serialize_tactical_assessment_v22(
    assessment: TacticalAssessmentV22,
) -> str:
    """Serialize a v2.2 assessment canonically for hashing and replay."""

    return _canonical_json(asdict(assessment))
