from datetime import UTC, datetime
from decimal import Decimal

import pytest

from equity_analysis.screening.config import (
    FACTOR_DEFINITIONS,
    NEAR_TERM_WEIGHTS,
    QC_VERSION,
    QC_WEIGHTS,
    UQ_VERSION,
    UQ_WEIGHTS,
)
from equity_analysis.screening.engine import rate
from equity_analysis.screening.models import (
    AssessmentStatus,
    CohortLevel,
    CompanyType,
    CoverageState,
    FactorInput,
    FactorStatus,
    Horizon,
    RatingRequest,
    SecurityObservation,
    SizeCohort,
)

AS_OF = datetime(2026, 7, 25, 20, 0, tzinfo=UTC)
SIZE_COHORTS = tuple(SizeCohort)


def factor_value(name: str, quality_index: int) -> Decimal:
    definition = FACTOR_DEFINITIONS[name]
    value = Decimal(quality_index)
    return value if definition.higher_is_better else Decimal("101") - value


def observation(
    index: int,
    *,
    size: SizeCohort,
    company_type: CompanyType = CompanyType.MATURE_OPERATING_COMPANY,
    missing_factor: str | None = None,
) -> SecurityObservation:
    factors = tuple(
        FactorInput(
            name=name,
            value=None if name == missing_factor else factor_value(name, index),
            status=FactorStatus.MISSING if name == missing_factor else FactorStatus.VALID,
            reason="Source field was not available" if name == missing_factor else None,
        )
        for name in FACTOR_DEFINITIONS
    )
    return SecurityObservation(
        security_id=f"sec-{size.value.lower()}-{index:03d}",
        symbol=f"T{size.value[0]}{index:03d}",
        as_of_time=AS_OF,
        sector="Industrials",
        size_cohort=size,
        company_type=company_type,
        factors=factors,
    )


def cohort() -> tuple[SecurityObservation, ...]:
    return tuple(
        observation(index, size=size)
        for size in SIZE_COHORTS
        for index in range(1, 26)
    )


def request(observations: tuple[SecurityObservation, ...]) -> RatingRequest:
    return RatingRequest(
        as_of_time=AS_OF,
        data_snapshot_id="fixture-2026-07-25",
        universe_version="universe-us-general-company-v1.0.0",
        strategy_versions=(QC_VERSION, UQ_VERSION),
        observations=observations,
    )


def test_all_versioned_weight_sets_sum_to_one() -> None:
    assert sum(QC_WEIGHTS.values()) == Decimal("1")
    assert sum(UQ_WEIGHTS.values()) == Decimal("1")
    assert sum(NEAR_TERM_WEIGHTS.values()) == Decimal("1")


def long_term(rating):
    return next(item for item in rating.horizon_assessments if item.horizon == Horizon.LONG_TERM)


def near_term(rating):
    return next(item for item in rating.horizon_assessments if item.horizon == Horizon.NEAR_TERM)


def test_identical_inputs_and_versions_reproduce_identical_results() -> None:
    rating_request = request(cohort())

    first = rate(rating_request)
    second = rate(rating_request)

    assert first == second
    assert first[0].model_dump_json() == second[0].model_dump_json()


def test_contributions_sum_to_displayed_scores_and_horizons_stay_separate() -> None:
    ratings = rate(request(cohort()))
    highest = next(item for item in ratings if item.security_id == "sec-small-025")

    for strategy in long_term(highest).strategy_ratings:
        assert strategy.score == sum(item.contribution for item in strategy.contributions)
    near = near_term(highest)
    assert near.strategy_ratings[0].score == sum(
        item.contribution for item in near.strategy_ratings[0].contributions
    )
    medium = next(
        item for item in highest.horizon_assessments if item.horizon == Horizon.MEDIUM_TERM
    )
    assert medium.status == AssessmentStatus.NOT_DEFINED
    assert medium.score is None
    assert highest.quality_score is not None
    assert highest.valuation_score is not None


def test_better_factor_values_do_not_receive_worse_normalized_scores() -> None:
    ratings = rate(request(cohort()))
    low = next(item for item in ratings if item.security_id == "sec-small-001")
    high = next(item for item in ratings if item.security_id == "sec-small-025")
    low_factors = {item.name: item for item in low.factor_results}
    high_factors = {item.name: item for item in high.factor_results}

    for factor_name in FACTOR_DEFINITIONS:
        assert (
            high_factors[factor_name].normalized_score
            >= low_factors[factor_name].normalized_score
        )


def test_equal_economic_positions_are_comparable_across_size_cohorts() -> None:
    ratings = rate(request(cohort()))
    same_position = [
        next(item for item in ratings if item.security_id == f"sec-{size.value.lower()}-013")
        for size in SIZE_COHORTS
    ]

    assert len({item.quality_score for item in same_position}) == 1
    assert len({item.valuation_score for item in same_position}) == 1
    assert {
        factor.cohort_level for item in same_position for factor in item.factor_results
    } == {CohortLevel.SECTOR_SIZE_COMPANY_TYPE}


def test_missing_required_factor_produces_insufficient_data_not_zero() -> None:
    observations = list(cohort())
    observations[0] = observation(
        1,
        size=SizeCohort.SMALL,
        missing_factor="roic",
    )

    rating = rate(request(tuple(observations)))[0]

    assert rating.coverage_state == CoverageState.INSUFFICIENT_DATA
    assert rating.quality_score is None
    assert rating.valuation_score is None
    assert "roic" in rating.missing_reasons
    assert all(
        strategy.score is None
        for strategy in long_term(rating).strategy_ratings
        if "roic" in strategy.missing_factors
    )


@pytest.mark.parametrize(
    "company_type",
    [
        CompanyType.FINANCIAL,
        CompanyType.REIT,
        CompanyType.RESOURCE,
        CompanyType.BIOTECHNOLOGY,
        CompanyType.EMERGING_GROWTH,
        CompanyType.SPECIAL_SITUATION,
    ],
)
def test_specialized_company_types_never_enter_general_company_ranking(
    company_type: CompanyType,
) -> None:
    observations = cohort() + (
        observation(25, size=SizeCohort.MEGA, company_type=company_type),
    )

    rating = rate(request(observations))[-1]

    assert rating.coverage_state == CoverageState.SPECIALIZED_MODEL_REQUIRED
    assert long_term(rating).status == AssessmentStatus.NOT_APPLICABLE
    assert rating.quality_score is None
    assert rating.valuation_score is None


def test_unsupported_strategy_version_fails_explicitly() -> None:
    rating_request = request(cohort()).model_copy(
        update={"strategy_versions": ("UNKNOWN-v1.0.0",)}
    )

    with pytest.raises(ValueError, match="Unsupported strategy version"):
        rate(rating_request)
