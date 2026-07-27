from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from equity_analysis.provider_validation.models import (
    DiscretePeriodObservation,
    SecFactObservation,
    TtmObservation,
)

TTM_YTD_BRIDGE_VERSION = "TTM-YTD-BRIDGE-v1.0.0"
TTM_WEIGHTED_YTD_BRIDGE_VERSION = "TTM-WEIGHTED-YTD-BRIDGE-v1.0.0"
DERIVATION_QUANTUM = Decimal("0.00000001")
DISCRETE_PERIOD_VERSION = "DISCRETE-FROM-CUMULATIVE-v1.0.0"


class FundamentalDerivationError(ValueError):
    """Raised when financial observations cannot support a deterministic derivation."""


def derive_ttm_from_annual_and_ytd(
    annual: SecFactObservation,
    current_ytd: SecFactObservation,
    prior_ytd: SecFactObservation,
    as_of_time: datetime,
) -> TtmObservation:
    if as_of_time.tzinfo is None or as_of_time.utcoffset() is None:
        raise FundamentalDerivationError("TTM cutoff must include a timezone")
    observations = (annual, current_ytd, prior_ytd)
    if any(item.available_at > as_of_time for item in observations):
        raise FundamentalDerivationError("TTM inputs must be available by the cutoff")
    if len({item.metric_code for item in observations}) != 1:
        raise FundamentalDerivationError("TTM inputs must use the same metric")
    if len({item.unit for item in observations}) != 1:
        raise FundamentalDerivationError("TTM inputs must use the same unit")
    if any(item.period_start is None for item in observations):
        raise FundamentalDerivationError("TTM duration inputs require period starts")

    assert annual.period_start is not None
    assert current_ytd.period_start is not None
    assert prior_ytd.period_start is not None
    annual_days = (annual.period_end - annual.period_start).days
    current_ytd_days = (current_ytd.period_end - current_ytd.period_start).days
    prior_ytd_days = (prior_ytd.period_end - prior_ytd.period_start).days
    if not 330 <= annual_days <= 380:
        raise FundamentalDerivationError("Annual input must cover approximately one year")
    if current_ytd_days <= 0 or abs(current_ytd_days - prior_ytd_days) > 14:
        raise FundamentalDerivationError("YTD inputs must cover comparable durations")
    if not (
        prior_ytd.period_start >= annual.period_start
        and prior_ytd.period_end < annual.period_end
        and current_ytd.period_start > annual.period_end
    ):
        raise FundamentalDerivationError("TTM periods are not chronologically compatible")

    accessions = tuple(
        dict.fromkeys(item.accession_number for item in observations)
    )
    return TtmObservation(
        metric_code=annual.metric_code,
        unit=annual.unit,
        value=annual.value + current_ytd.value - prior_ytd.value,
        period_end=current_ytd.period_end,
        available_at=max(item.available_at for item in observations),
        formula_version=TTM_YTD_BRIDGE_VERSION,
        lineage_accessions=accessions,
    )


def derive_ttm_weighted_average_from_annual_and_ytd(
    annual: SecFactObservation,
    current_ytd: SecFactObservation,
    prior_ytd: SecFactObservation,
    as_of_time: datetime,
) -> TtmObservation:
    base = derive_ttm_from_annual_and_ytd(
        annual,
        current_ytd,
        prior_ytd,
        as_of_time,
    )
    assert annual.period_start is not None
    assert current_ytd.period_start is not None
    assert prior_ytd.period_start is not None
    annual_days = (annual.period_end - annual.period_start).days + 1
    current_ytd_days = (current_ytd.period_end - current_ytd.period_start).days + 1
    prior_ytd_days = (prior_ytd.period_end - prior_ytd.period_start).days + 1
    ttm_days = annual_days + current_ytd_days - prior_ytd_days
    if ttm_days <= 0:
        raise FundamentalDerivationError(
            "Weighted-average TTM duration must be positive"
        )
    weighted_value = (
        annual.value * annual_days
        + current_ytd.value * current_ytd_days
        - prior_ytd.value * prior_ytd_days
    ) / Decimal(ttm_days)
    return base.model_copy(
        update={
            "value": weighted_value.quantize(
                DERIVATION_QUANTUM,
                rounding=ROUND_HALF_EVEN,
            ),
            "formula_version": TTM_WEIGHTED_YTD_BRIDGE_VERSION,
        }
    )


def derive_discrete_period_from_cumulative(
    current: SecFactObservation,
    previous: SecFactObservation | None,
    as_of_time: datetime,
) -> DiscretePeriodObservation:
    if as_of_time.tzinfo is None or as_of_time.utcoffset() is None:
        raise FundamentalDerivationError("Discrete-period cutoff must include a timezone")
    if current.period_start is None:
        raise FundamentalDerivationError("Cumulative input requires a period start")
    inputs = (current,) if previous is None else (current, previous)
    if any(item.available_at > as_of_time for item in inputs):
        raise FundamentalDerivationError(
            "Discrete-period inputs must be available by the cutoff"
        )
    if previous is None:
        period_start = current.period_start
        value = current.value
    else:
        if previous.period_start is None:
            raise FundamentalDerivationError("Cumulative input requires a period start")
        if current.metric_code != previous.metric_code:
            raise FundamentalDerivationError(
                "Discrete-period inputs must use the same metric"
            )
        if current.unit != previous.unit:
            raise FundamentalDerivationError(
                "Discrete-period inputs must use the same unit"
            )
        if (
            current.period_start != previous.period_start
            or current.period_end <= previous.period_end
        ):
            raise FundamentalDerivationError(
                "Cumulative periods must share a start and increase chronologically"
            )
        period_start = previous.period_end + timedelta(days=1)
        value = current.value - previous.value
    return DiscretePeriodObservation(
        metric_code=current.metric_code,
        unit=current.unit,
        value=value,
        period_start=period_start,
        period_end=current.period_end,
        available_at=max(item.available_at for item in inputs),
        formula_version=DISCRETE_PERIOD_VERSION,
        lineage_accessions=tuple(
            dict.fromkeys(item.accession_number for item in inputs)
        ),
    )
