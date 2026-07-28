from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from equity_analysis.market_intelligence.models import (
    DeterministicViewState,
    FactState,
    Horizon,
    ProfileInput,
    ProfileState,
    RankedSecurity,
    RankingState,
    RankMetric,
    ScreeningRequest,
    ScreeningResult,
    SecurityProfile,
    SortDirection,
)

MARKET_INTELLIGENCE_VERSION = "MARKET-INTELLIGENCE-SCREENING-v1.0.0"
_REQUIRED_HORIZONS = frozenset(Horizon)


def build_security_profile(payload: ProfileInput, as_of: datetime) -> SecurityProfile:
    exclusions: list[str] = []
    if payload.classification is None:
        exclusions.append("CLASSIFICATION_MISSING")
    elif payload.classification.effective_at > as_of:
        exclusions.append("CLASSIFICATION_NOT_YET_EFFECTIVE")

    fact_states = {fact.name: fact.state for fact in payload.facts}
    for required in ("market_cap", "latest_price", "average_daily_dollar_volume"):
        if fact_states.get(required) != FactState.VALID:
            exclusions.append(f"REQUIRED_FACT_{required.upper()}_NOT_VALID")

    views = {view.horizon: view.deterministic_view for view in payload.horizons}
    for horizon in _REQUIRED_HORIZONS:
        view = views.get(horizon)
        if view is None:
            exclusions.append(f"HORIZON_{horizon}_MISSING")
        elif view.as_of > as_of or view.effective_at > as_of:
            exclusions.append(f"HORIZON_{horizon}_NOT_AVAILABLE")
        elif view.expires_at is not None and view.expires_at < as_of:
            exclusions.append(f"HORIZON_{horizon}_STALE")

    if payload.objective_rating_status != "SCORED":
        exclusions.append("OBJECTIVE_RATING_NOT_SCORE_ELIGIBLE")
    if payload.objective_quality_score is None or payload.objective_valuation_score is None:
        exclusions.append("OBJECTIVE_DIMENSION_SCORE_MISSING")
    if payload.valuation.state != FactState.VALID:
        exclusions.append("VALUATION_EVIDENCE_NOT_VALID")
    if payload.classification is not None and not any(
        cohort.is_sufficient for cohort in payload.comparable_cohorts
    ):
        exclusions.append("COMPARABLE_COHORT_TOO_SMALL")

    non_valid_facts = tuple(
        f"{fact.name}:{fact.state}" for fact in payload.facts if fact.state != FactState.VALID
    )
    profile_state = (
        ProfileState.COMPLETE
        if not non_valid_facts and payload.classification is not None
        else ProfileState.PARTIAL
    )
    ranking_state = RankingState.ELIGIBLE if not exclusions else RankingState.NOT_ELIGIBLE
    explanation = (
        "Security-master and classification fields are observed facts with lineage.",
        "Objective Rating v1, tactical, and long-horizon outputs remain separate "
        "versioned deterministic assessments.",
        "Provider acceptance is not used as scoring or ranking eligibility.",
        "Missing, invalid, stale, and not-applicable states are never converted to zero.",
        "AI narrative is explanatory only and cannot set scores or ranks.",
    )
    return SecurityProfile(
        contract_version=MARKET_INTELLIGENCE_VERSION,
        security=payload.security,
        classification=payload.classification,
        comparable_cohorts=payload.comparable_cohorts,
        facts=payload.facts,
        objective_quality_score=payload.objective_quality_score,
        objective_valuation_score=payload.objective_valuation_score,
        objective_rating_status=payload.objective_rating_status,
        objective_rating_version=payload.objective_rating_version,
        horizons=payload.horizons,
        valuation=payload.valuation,
        profile_state=profile_state,
        ranking_state=ranking_state,
        ranking_exclusions=tuple(dict.fromkeys(exclusions)),
        explainability=explanation,
        ai_narrative=payload.ai_narrative,
    )


def screen_profiles(
    profiles: tuple[SecurityProfile, ...],
    request: ScreeningRequest,
) -> ScreeningResult:
    candidates: list[tuple[SecurityProfile, Decimal]] = []
    exclusions: dict[str, tuple[str, ...]] = {}
    for profile in profiles:
        reasons = _filter_reasons(profile, request)
        value = _metric_value(profile, request.rank_by, request.as_of)
        if value is None:
            reasons.append("RANK_METRIC_NOT_ELIGIBLE")
        if reasons:
            exclusions[profile.security.security_id] = tuple(dict.fromkeys(reasons))
            continue
        candidates.append((profile, value))

    reverse = request.direction == SortDirection.DESCENDING
    candidates.sort(
        key=lambda item: (
            item[1],
            item[0].security.security_id,
        ),
        reverse=reverse,
    )
    ranked = tuple(
        RankedSecurity(
            rank=index,
            security_id=profile.security.security_id,
            symbol=profile.security.symbol,
            sector_code=profile.classification.sector_code,  # type: ignore[union-attr]
            industry_code=profile.classification.industry_code,  # type: ignore[union-attr]
            metric=request.rank_by,
            value=value,
            profile=profile,
        )
        for index, (profile, value) in enumerate(candidates[: request.limit], start=1)
    )
    sector_count = len({item.sector_code for item in ranked})
    return ScreeningResult(
        contract_version=MARKET_INTELLIGENCE_VERSION,
        as_of=request.as_of,
        rank_by=request.rank_by,
        direction=request.direction,
        eligible_count=len(candidates),
        excluded_count=len(exclusions),
        items=ranked,
        exclusions=exclusions,
        acceptance={
            "sectorCoverageCount": sector_count,
            "securityCoverageCount": len(profiles),
            "freshProfileCount": sum(
                not any("STALE" in reason for reason in profile.ranking_exclusions)
                for profile in profiles
            ),
            "rankingEligibleCount": len(candidates),
            "explainableCount": sum(bool(profile.explainability) for profile in profiles),
            "gateStatus": "PASS" if candidates else "NO_ELIGIBLE_RESULTS",
        },
    )


def _filter_reasons(
    profile: SecurityProfile,
    request: ScreeningRequest,
) -> list[str]:
    reasons: list[str] = []
    filters = request.filters
    classification = profile.classification
    if classification is None:
        return ["CLASSIFICATION_MISSING"]
    if filters.sectors and classification.sector_code not in filters.sectors:
        reasons.append("SECTOR_FILTER_MISMATCH")
    if filters.industries and classification.industry_code not in filters.industries:
        reasons.append("INDUSTRY_FILTER_MISMATCH")
    if filters.company_types and classification.company_type not in filters.company_types:
        reasons.append("COMPANY_TYPE_FILTER_MISMATCH")
    if filters.symbols and profile.security.symbol not in filters.symbols:
        reasons.append("SYMBOL_FILTER_MISMATCH")
    available_horizons = {view.horizon for view in profile.horizons}
    if filters.horizons and not set(filters.horizons).issubset(available_horizons):
        reasons.append("HORIZON_FILTER_MISMATCH")
    if filters.require_ranking_eligible and profile.ranking_state != RankingState.ELIGIBLE:
        reasons.extend(profile.ranking_exclusions or ("PROFILE_NOT_RANKING_ELIGIBLE",))
    return reasons


def _metric_value(
    profile: SecurityProfile,
    metric: RankMetric,
    as_of: datetime,
) -> Decimal | None:
    if metric == RankMetric.OBJECTIVE_QUALITY:
        return profile.objective_quality_score
    if metric == RankMetric.OBJECTIVE_VALUATION:
        return profile.objective_valuation_score
    if metric == RankMetric.LONG_HORIZON:
        return _horizon_score(profile, Horizon.TWELVE_MONTHS_PLUS, as_of)
    if metric == RankMetric.TACTICAL_ONE_WEEK:
        return _horizon_score(profile, Horizon.ONE_WEEK, as_of)
    if metric == RankMetric.TACTICAL_ONE_MONTH:
        return _horizon_score(profile, Horizon.ONE_MONTH, as_of)
    if metric == RankMetric.TACTICAL_THREE_MONTHS:
        return _horizon_score(profile, Horizon.THREE_MONTHS, as_of)
    values = (
        profile.valuation.objective_valuation_score,
        profile.valuation.long_horizon_valuation_score,
        profile.valuation.own_history_percentile,
    )
    if profile.valuation.state != FactState.VALID or any(value is None for value in values):
        return None
    return sum((value for value in values if value is not None), Decimal()) / Decimal(3)


def _horizon_score(
    profile: SecurityProfile,
    horizon: Horizon,
    as_of: datetime,
) -> Decimal | None:
    for item in profile.horizons:
        view = item.deterministic_view
        if (
            item.horizon == horizon
            and view.state == DeterministicViewState.ASSESSED
            and view.as_of <= as_of
            and view.effective_at <= as_of
            and (view.expires_at is None or view.expires_at >= as_of)
        ):
            return view.score
    return None
