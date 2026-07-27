from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal

from equity_analysis.screening.config import (
    NEAR_TERM_VERSION,
    NEAR_TERM_WEIGHTS,
    QC_VERSION,
    QC_WEIGHTS,
    UQ_VERSION,
    UQ_WEIGHTS,
)
from equity_analysis.screening.models import (
    AssessmentStatus,
    CompanyType,
    CoverageState,
    ErrorCode,
    FactorContribution,
    FactorResult,
    FactorStatus,
    Horizon,
    HorizonAssessment,
    RatingRequest,
    SecurityObservation,
    SecurityRating,
    StrategyRating,
)
from equity_analysis.screening.normalization import normalize_observations

SCORE_QUANTUM = Decimal("0.0001")
SUPPORTED_STRATEGIES = frozenset({QC_VERSION, UQ_VERSION})


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _score_strategy(
    strategy_version: str,
    weights: Mapping[str, Decimal],
    factors: Mapping[str, FactorResult],
) -> StrategyRating:
    missing = tuple(
        factor_name
        for factor_name in weights
        if factor_name not in factors
        or factors[factor_name].status != FactorStatus.VALID
        or factors[factor_name].normalized_score is None
    )
    if missing:
        return StrategyRating(
            strategy_version=strategy_version,
            status=AssessmentStatus.INSUFFICIENT_DATA,
            missing_factors=missing,
            error_code=ErrorCode.INSUFFICIENT_DATA,
        )
    contributions = tuple(
        FactorContribution(
            factor_name=factor_name,
            normalized_score=factors[factor_name].normalized_score,
            weight=weight,
            contribution=_quantize(factors[factor_name].normalized_score * weight),
        )
        for factor_name, weight in weights.items()
        if factors[factor_name].normalized_score is not None
    )
    return StrategyRating(
        strategy_version=strategy_version,
        status=AssessmentStatus.SCORED,
        score=_quantize(sum(item.contribution for item in contributions)),
        contributions=contributions,
    )


def _component_score(
    rating: StrategyRating,
    factor_names: frozenset[str],
    total_weight: Decimal,
) -> Decimal | None:
    if rating.status != AssessmentStatus.SCORED:
        return None
    return _quantize(
        sum(
            contribution.contribution
            for contribution in rating.contributions
            if contribution.factor_name in factor_names
        )
        / total_weight
    )


def _near_term_label(score: Decimal) -> str:
    if score >= Decimal("66.6667"):
        return "FAVORABLE"
    if score <= Decimal("33.3333"):
        return "UNFAVORABLE"
    return "NEUTRAL"


def _lineage(observation: SecurityObservation):
    unique = {}
    for factor in observation.factors:
        for item in factor.lineage:
            key = (item.provider, item.source_reference, item.content_hash)
            unique[key] = item
    return tuple(unique[key] for key in sorted(unique))


def _unsupported_rating(observation: SecurityObservation) -> SecurityRating:
    unsupported = StrategyRating(
        strategy_version=QC_VERSION,
        status=AssessmentStatus.NOT_APPLICABLE,
        error_code=ErrorCode.UNSUPPORTED_COMPANY_TYPE,
    )
    unsupported_uq = unsupported.model_copy(update={"strategy_version": UQ_VERSION})
    return SecurityRating(
        security_id=observation.security_id,
        symbol=observation.symbol,
        as_of_time=observation.as_of_time,
        coverage_state=CoverageState.SPECIALIZED_MODEL_REQUIRED,
        company_type=observation.company_type,
        size_cohort=observation.size_cohort,
        horizon_assessments=(
            HorizonAssessment(
                horizon=Horizon.NEAR_TERM,
                status=AssessmentStatus.NOT_APPLICABLE,
                label="NOT_APPLICABLE",
            ),
            HorizonAssessment(
                horizon=Horizon.MEDIUM_TERM,
                status=AssessmentStatus.NOT_DEFINED,
                label="NOT_DEFINED",
            ),
            HorizonAssessment(
                horizon=Horizon.LONG_TERM,
                status=AssessmentStatus.NOT_APPLICABLE,
                label="SPECIALIZED_MODEL_REQUIRED",
                strategy_ratings=(unsupported, unsupported_uq),
            ),
        ),
        risk_flags=observation.risk_flags,
        missing_reasons=("General-company rating model is not applicable",),
        lineage=_lineage(observation),
    )


def rate(request: RatingRequest) -> tuple[SecurityRating, ...]:
    unsupported_versions = set(request.strategy_versions) - SUPPORTED_STRATEGIES
    if unsupported_versions:
        versions = ", ".join(sorted(unsupported_versions))
        raise ValueError(f"Unsupported strategy version: {versions}")
    normalized = normalize_observations(request.observations)
    ratings: list[SecurityRating] = []
    for observation in request.observations:
        if observation.company_type != CompanyType.MATURE_OPERATING_COMPANY:
            ratings.append(_unsupported_rating(observation))
            continue
        factor_results = normalized[observation.security_id]
        factor_map = {factor.name: factor for factor in factor_results}
        qc = _score_strategy(QC_VERSION, QC_WEIGHTS, factor_map)
        uq = _score_strategy(UQ_VERSION, UQ_WEIGHTS, factor_map)
        near_term = _score_strategy(NEAR_TERM_VERSION, NEAR_TERM_WEIGHTS, factor_map)
        requested = tuple(
            rating for rating in (qc, uq) if rating.strategy_version in request.strategy_versions
        )
        long_status = (
            AssessmentStatus.SCORED
            if requested and all(item.status == AssessmentStatus.SCORED for item in requested)
            else AssessmentStatus.INSUFFICIENT_DATA
        )
        near_status = near_term.status
        near_score = near_term.score
        missing = tuple(
            sorted(
                {
                    factor
                    for strategy in (*requested, near_term)
                    for factor in strategy.missing_factors
                }
            )
        )
        coverage = (
            CoverageState.QUANT_ELIGIBLE
            if long_status == AssessmentStatus.SCORED
            else CoverageState.INSUFFICIENT_DATA
        )
        quality_score = _component_score(
            qc,
            frozenset(QC_WEIGHTS) - {"valuation_guardrail"},
            Decimal("0.95"),
        )
        valuation_score = _component_score(
            uq,
            frozenset({"earnings_yield", "fcf_yield", "historical_fcf_yield_percentile"}),
            Decimal("0.45"),
        )
        ratings.append(
            SecurityRating(
                security_id=observation.security_id,
                symbol=observation.symbol,
                as_of_time=observation.as_of_time,
                coverage_state=coverage,
                company_type=observation.company_type,
                size_cohort=observation.size_cohort,
                quality_score=quality_score,
                valuation_score=valuation_score,
                factor_results=factor_results,
                horizon_assessments=(
                    HorizonAssessment(
                        horizon=Horizon.NEAR_TERM,
                        status=near_status,
                        score=near_score,
                        label=(
                            _near_term_label(near_score)
                            if near_score is not None
                            else "INSUFFICIENT_DATA"
                        ),
                        strategy_ratings=(near_term,),
                    ),
                    HorizonAssessment(
                        horizon=Horizon.MEDIUM_TERM,
                        status=AssessmentStatus.NOT_DEFINED,
                        label="NOT_DEFINED",
                    ),
                    HorizonAssessment(
                        horizon=Horizon.LONG_TERM,
                        status=long_status,
                        label=(
                            "SCORED"
                            if long_status == AssessmentStatus.SCORED
                            else "INSUFFICIENT_DATA"
                        ),
                        strategy_ratings=requested,
                    ),
                ),
                risk_flags=observation.risk_flags,
                missing_reasons=missing,
                lineage=_lineage(observation),
            )
        )
    return _assign_ranks(tuple(ratings))


def _assign_ranks(ratings: tuple[SecurityRating, ...]) -> tuple[SecurityRating, ...]:
    ranks: dict[tuple[str, str], int] = {}
    versions = (QC_VERSION, UQ_VERSION)
    for version in versions:
        sortable: list[tuple[str, Decimal]] = []
        for security in ratings:
            long_term = next(
                item for item in security.horizon_assessments if item.horizon == Horizon.LONG_TERM
            )
            strategy = next(
                (
                    item
                    for item in long_term.strategy_ratings
                    if item.strategy_version == version
                    and item.status == AssessmentStatus.SCORED
                    and item.score is not None
                ),
                None,
            )
            if strategy is not None and strategy.score is not None:
                sortable.append((security.security_id, strategy.score))
        for index, (security_id, _score) in enumerate(
            sorted(sortable, key=lambda item: (-item[1], item[0])),
            start=1,
        ):
            ranks[(security_id, version)] = index

    updated: list[SecurityRating] = []
    for security in ratings:
        horizons: list[HorizonAssessment] = []
        for horizon in security.horizon_assessments:
            strategies = tuple(
                strategy.model_copy(
                    update={"rank": ranks.get((security.security_id, strategy.strategy_version))}
                )
                for strategy in horizon.strategy_ratings
            )
            horizons.append(horizon.model_copy(update={"strategy_ratings": strategies}))
        updated.append(security.model_copy(update={"horizon_assessments": tuple(horizons)}))
    return tuple(updated)
