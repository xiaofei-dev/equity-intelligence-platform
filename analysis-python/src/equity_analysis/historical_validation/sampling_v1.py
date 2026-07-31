from __future__ import annotations

import calendar
import hashlib
import json
import random
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum

HISTORICAL_SLICE_PLAN_VERSION = "HISTORICAL-TIME-SLICE-PLAN-v1.1.0"
DEFAULT_HORIZONS = (5, 20, 60, 126, 252)


class HistoricalAgeBand(StrEnum):
    RECENT = "RECENT_3_TO_9_MONTHS"
    MEDIUM = "MEDIUM_1_TO_3_YEARS"
    OLDER = "OLDER_4_TO_10_YEARS"


@dataclass(frozen=True)
class HistoricalSamplePoint:
    sample_id: str
    age_band: HistoricalAgeBand
    decision_date: date
    session_index: int
    matured_horizons: tuple[int, ...]


@dataclass(frozen=True)
class HistoricalSlicePlan:
    version: str
    as_of_date: date
    seed: int
    requested_samples_per_band: int
    minimum_session_spacing: int
    horizons: tuple[int, ...]
    benchmark_first_date: date
    benchmark_last_date: date
    benchmark_session_count: int
    random_samples: tuple[HistoricalSamplePoint, ...]
    monthly_samples: tuple[HistoricalSamplePoint, ...]
    plan_hash: str


def _subtract_months(value: date, months: int) -> date:
    year = value.year - months // 12
    month = value.month - months % 12
    if month <= 0:
        year -= 1
        month += 12
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: value.isoformat() if isinstance(value, date) else value,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def _matured_horizons(
    session_index: int,
    session_count: int,
    horizons: tuple[int, ...],
) -> tuple[int, ...]:
    return tuple(
        horizon
        for horizon in horizons
        if session_index + horizon < session_count
    )


def _age_band_bounds(
    as_of_date: date,
) -> dict[HistoricalAgeBand, tuple[date, date]]:
    return {
        HistoricalAgeBand.RECENT: (
            _subtract_months(as_of_date, 9),
            _subtract_months(as_of_date, 3),
        ),
        HistoricalAgeBand.MEDIUM: (
            _subtract_months(as_of_date, 36),
            _subtract_months(as_of_date, 12),
        ),
        HistoricalAgeBand.OLDER: (
            _subtract_months(as_of_date, 120),
            _subtract_months(as_of_date, 48),
        ),
    }


def _select_spaced_indices(
    candidates: tuple[int, ...],
    *,
    count: int,
    minimum_spacing: int,
    generator: random.Random,
) -> tuple[int, ...]:
    shuffled = list(candidates)
    generator.shuffle(shuffled)
    selected: list[int] = []
    for candidate in shuffled:
        if all(abs(candidate - existing) >= minimum_spacing for existing in selected):
            selected.append(candidate)
        if len(selected) == count:
            return tuple(sorted(selected))
    raise ValueError(
        "Historical band cannot satisfy requested sample count and session spacing"
    )


def _monthly_indices(
    sessions: tuple[date, ...],
    *,
    start_date: date,
    end_date: date,
) -> tuple[int, ...]:
    latest_by_month: dict[tuple[int, int], int] = {}
    for index, session_date in enumerate(sessions):
        if start_date <= session_date <= end_date:
            latest_by_month[(session_date.year, session_date.month)] = index
    return tuple(latest_by_month[key] for key in sorted(latest_by_month))


def build_historical_slice_plan(
    benchmark_sessions: tuple[date, ...],
    *,
    as_of_date: date,
    seed: int = 20260729,
    samples_per_band: int = 6,
    minimum_session_spacing: int = 15,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> HistoricalSlicePlan:
    """Seal deterministic random and month-end dates before reading outcomes."""

    sessions = tuple(sorted(set(benchmark_sessions)))
    if len(sessions) != len(benchmark_sessions):
        raise ValueError("Benchmark sessions must be unique and sorted")
    if not sessions or sessions[-1] > as_of_date:
        raise ValueError("Benchmark sessions must end on or before the as-of date")
    if samples_per_band < 1 or minimum_session_spacing < 1:
        raise ValueError("Sample count and spacing must be positive")
    if not horizons or len(set(horizons)) != len(horizons) or min(horizons) <= 0:
        raise ValueError("Horizons must be unique positive session counts")

    bounds = _age_band_bounds(as_of_date)
    generator = random.Random(seed)
    random_samples: list[HistoricalSamplePoint] = []
    for band in HistoricalAgeBand:
        start_date, end_date = bounds[band]
        candidates = tuple(
            index
            for index, session_date in enumerate(sessions)
            if start_date <= session_date <= end_date
        )
        selected = _select_spaced_indices(
            candidates,
            count=samples_per_band,
            minimum_spacing=minimum_session_spacing,
            generator=generator,
        )
        for ordinal, index in enumerate(selected, start=1):
            random_samples.append(
                HistoricalSamplePoint(
                    sample_id=f"RANDOM-{band.value}-{ordinal:02d}",
                    age_band=band,
                    decision_date=sessions[index],
                    session_index=index,
                    matured_horizons=_matured_horizons(
                        index,
                        len(sessions),
                        horizons,
                    ),
                )
            )

    monthly_samples: list[HistoricalSamplePoint] = []
    for band in HistoricalAgeBand:
        start_date, end_date = bounds[band]
        for ordinal, index in enumerate(
            _monthly_indices(
                sessions,
                start_date=start_date,
                end_date=end_date,
            ),
            start=1,
        ):
            monthly_samples.append(
                HistoricalSamplePoint(
                    sample_id=f"MONTH_END-{band.value}-{ordinal:03d}",
                    age_band=band,
                    decision_date=sessions[index],
                    session_index=index,
                    matured_horizons=_matured_horizons(
                        index,
                        len(sessions),
                        horizons,
                    ),
                )
            )

    unhashed = {
        "version": HISTORICAL_SLICE_PLAN_VERSION,
        "asOfDate": as_of_date,
        "seed": seed,
        "requestedSamplesPerBand": samples_per_band,
        "minimumSessionSpacing": minimum_session_spacing,
        "horizons": horizons,
        "benchmarkFirstDate": sessions[0],
        "benchmarkLastDate": sessions[-1],
        "benchmarkSessionCount": len(sessions),
        "randomSamples": [asdict(item) for item in random_samples],
        "monthlySamples": [asdict(item) for item in monthly_samples],
    }
    return HistoricalSlicePlan(
        version=HISTORICAL_SLICE_PLAN_VERSION,
        as_of_date=as_of_date,
        seed=seed,
        requested_samples_per_band=samples_per_band,
        minimum_session_spacing=minimum_session_spacing,
        horizons=horizons,
        benchmark_first_date=sessions[0],
        benchmark_last_date=sessions[-1],
        benchmark_session_count=len(sessions),
        random_samples=tuple(random_samples),
        monthly_samples=tuple(monthly_samples),
        plan_hash=_canonical_hash(unhashed),
    )
