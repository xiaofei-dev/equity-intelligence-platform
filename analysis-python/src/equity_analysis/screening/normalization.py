from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_EVEN, Decimal
from types import MappingProxyType

from equity_analysis.screening.config import FACTOR_DEFINITIONS
from equity_analysis.screening.models import (
    CohortLevel,
    CompanyType,
    FactorInput,
    FactorResult,
    FactorStatus,
    SecurityObservation,
)

SCORE_QUANTUM = Decimal("0.0001")
SECTOR_SIZE_MINIMUM = 20
SECTOR_MINIMUM = 30
GENERAL_MINIMUM = 100


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _percentile(sorted_values: tuple[Decimal, ...], probability: Decimal) -> Decimal:
    if not sorted_values:
        raise ValueError("Cannot calculate a percentile for an empty cohort")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = probability * Decimal(len(sorted_values) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    fraction = position - Decimal(lower_index)
    return sorted_values[lower_index] + (
        sorted_values[upper_index] - sorted_values[lower_index]
    ) * fraction


def _percentile_rank(sorted_values: tuple[Decimal, ...], value: Decimal) -> Decimal:
    if len(sorted_values) < 2:
        raise ValueError("A percentile rank requires at least two values")
    less = sum(item < value for item in sorted_values)
    equal = sum(item == value for item in sorted_values)
    numerator = Decimal(less) + Decimal(equal - 1) / Decimal(2)
    return Decimal("100") * numerator / Decimal(len(sorted_values) - 1)


def _valid_factor(observation: SecurityObservation, factor_name: str) -> FactorInput | None:
    return next(
        (
            factor
            for factor in observation.factors
            if factor.name == factor_name
            and factor.status == FactorStatus.VALID
            and factor.value is not None
        ),
        None,
    )


def _select_cohort(
    observation: SecurityObservation,
    factor_name: str,
    observations: tuple[SecurityObservation, ...],
) -> tuple[CohortLevel, tuple[Decimal, ...]] | None:
    eligible = tuple(
        candidate
        for candidate in observations
        if candidate.company_type == CompanyType.MATURE_OPERATING_COMPANY
        and _valid_factor(candidate, factor_name) is not None
    )
    candidates = (
        (
            CohortLevel.SECTOR_SIZE_COMPANY_TYPE,
            tuple(
                candidate
                for candidate in eligible
                if candidate.sector == observation.sector
                and candidate.size_cohort == observation.size_cohort
            ),
            SECTOR_SIZE_MINIMUM,
        ),
        (
            CohortLevel.SECTOR_COMPANY_TYPE,
            tuple(
                candidate for candidate in eligible if candidate.sector == observation.sector
            ),
            SECTOR_MINIMUM,
        ),
        (CohortLevel.GENERAL_COMPANY, eligible, GENERAL_MINIMUM),
    )
    for level, cohort, minimum in candidates:
        if len(cohort) >= minimum:
            values = tuple(
                sorted(
                    factor.value
                    for candidate in cohort
                    if (factor := _valid_factor(candidate, factor_name)) is not None
                    and factor.value is not None
                )
            )
            return level, values
    return None


def normalize_observations(
    observations: Iterable[SecurityObservation],
) -> Mapping[str, tuple[FactorResult, ...]]:
    observation_tuple = tuple(observations)
    results: dict[str, tuple[FactorResult, ...]] = {}
    for observation in observation_tuple:
        normalized: list[FactorResult] = []
        for factor in observation.factors:
            definition = FACTOR_DEFINITIONS.get(factor.name)
            if factor.status != FactorStatus.VALID or factor.value is None:
                normalized.append(
                    FactorResult(
                        name=factor.name,
                        status=factor.status,
                        raw_value=factor.value,
                        reason=factor.reason,
                    )
                )
                continue
            if definition is None:
                normalized.append(
                    FactorResult(
                        name=factor.name,
                        status=FactorStatus.INVALID,
                        raw_value=factor.value,
                        reason="Factor is not defined by the active rating version",
                    )
                )
                continue
            cohort = _select_cohort(observation, factor.name, observation_tuple)
            if cohort is None:
                normalized.append(
                    FactorResult(
                        name=factor.name,
                        status=FactorStatus.INVALID,
                        raw_value=factor.value,
                        reason="COHORT_TOO_SMALL",
                    )
                )
                continue
            cohort_level, sorted_values = cohort
            lower = _percentile(sorted_values, Decimal("0.05"))
            upper = _percentile(sorted_values, Decimal("0.95"))
            winsorized = min(max(factor.value, lower), upper)
            winsorized_cohort = tuple(min(max(value, lower), upper) for value in sorted_values)
            score = _percentile_rank(tuple(sorted(winsorized_cohort)), winsorized)
            if not definition.higher_is_better:
                score = Decimal("100") - score
            normalized.append(
                FactorResult(
                    name=factor.name,
                    status=FactorStatus.VALID,
                    raw_value=factor.value,
                    winsorized_value=_quantize(winsorized),
                    normalized_score=_quantize(score),
                    cohort_level=cohort_level,
                    cohort_size=len(sorted_values),
                )
            )
        results[observation.security_id] = tuple(normalized)
    return MappingProxyType(results)
