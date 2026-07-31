from __future__ import annotations

import calendar
import hashlib
import json
import math
import random
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.historical_validation.protocol_v2 import (
    BenchmarkKind,
    LiquiditySensitiveCostPolicy,
)
from equity_analysis.historical_validation.tactical_v22_diagnostic import (
    HistoricalSeriesV22,
    load_hash_verified_yahoo_cache_v22,
)

HISTORICAL_SLICE_PLAN_V22 = "HISTORICAL-DQV-SLICE-PLAN-v2.2.0"
HISTORICAL_SLICE_DIAGNOSTIC_V22 = (
    "HISTORICAL-DQV-SLICE-DIAGNOSTIC-v2.2.0"
)
HISTORICAL_SLICE_GIT_SAFE_CLOSEOUT_V22 = (
    "HISTORICAL-DQV-SLICE-DIAGNOSTIC-CLOSEOUT-v2.2.0"
)
TACTICAL_MODEL_VERSION = "TACTICAL-SIGNAL-v2.2.0"
LONG_HORIZON_MODEL_VERSION = "LONG-HORIZON-RESEARCH-v1.1.0"
RANDOM_SEED = 20260729
HORIZONS = (5, 20, 60, 126, 252)
TACTICAL_HORIZONS = (5, 20, 60)
FIXED_OFFSETS_MONTHS = (3, 6, 9, 12, 18, 24, 48, 72, 120)
AGE_BANDS = (
    ("RECENT_3_TO_9_MONTHS", 3, 9),
    ("PRIOR_1_TO_3_YEARS", 12, 36),
    ("OLDER_4_TO_10_YEARS", 48, 120),
)
SAMPLES_PER_BAND = 6
MINIMUM_SESSION_SPACING = 15
VALUE_SCALE = Decimal("0.00000001")
ZERO = Decimal(0)
_DATE_LINE = re.compile(
    rb'^\s*"tradingDate":\s*"(?P<date>\d{4}-\d{2}-\d{2})",?\s*$'
)


class HistoricalSliceDiagnosticV22Error(ValueError):
    pass


@dataclass(frozen=True)
class SliceAnchorV22:
    sample_id: str
    selection_method: str
    stratum: str
    decision_date: date
    session_index: int
    matured_horizons: tuple[int, ...]


@dataclass(frozen=True)
class PortfolioPathMetricV22:
    gross_return: Decimal
    cost_rate: Decimal
    net_return: Decimal
    maximum_adverse_excursion: Decimal
    maximum_favorable_excursion: Decimal
    maximum_drawdown: Decimal
    downside_deviation: Decimal
    holding_count: int
    coverage: Decimal


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _display_path(path: Path, repository_root: Path) -> str:
    try:
        return path.resolve().relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _q(value: Decimal) -> Decimal:
    return value.quantize(VALUE_SCALE, rounding=ROUND_HALF_EVEN)


def _normalized_hash(value: str) -> str:
    return value.removeprefix("sha256:").lower()


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
        }
    return value


def _verify_canonical_artifact(
    path: Path,
    *,
    hash_field: str = "artifactContentHash",
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HistoricalSliceDiagnosticV22Error(
            f"Artifact is unreadable: {path}"
        ) from error
    if not isinstance(payload, dict):
        raise HistoricalSliceDiagnosticV22Error(
            f"Artifact must be an object: {path}"
        )
    expected = payload.get(hash_field)
    if not isinstance(expected, str):
        raise HistoricalSliceDiagnosticV22Error(
            f"Artifact has no {hash_field}: {path}"
        )
    body = {key: value for key, value in payload.items() if key != hash_field}
    if _normalized_hash(canonical_hash(body)) != _normalized_hash(expected):
        raise HistoricalSliceDiagnosticV22Error(
            f"Artifact canonical hash mismatch: {path}"
        )
    return payload


def _subtract_months(value: date, months: int) -> date:
    year = value.year - months // 12
    month = value.month - months % 12
    if month <= 0:
        year -= 1
        month += 12
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _extract_date_only_sessions(
    payload_path: Path,
    *,
    expected_file_sha256: str,
    expected_bar_count: int,
) -> tuple[date, ...]:
    """Extract only trading-date lines before any outcome value is parsed."""

    if _file_sha256(payload_path) != expected_file_sha256.upper():
        raise HistoricalSliceDiagnosticV22Error(
            "DATE_ONLY_SOURCE_FILE_HASH_MISMATCH"
        )
    sessions: list[date] = []
    with payload_path.open("rb") as handle:
        for line in handle:
            match = _DATE_LINE.match(line)
            if match is not None:
                sessions.append(
                    date.fromisoformat(match.group("date").decode("ascii"))
                )
    result = tuple(sessions)
    if len(result) != expected_bar_count:
        raise HistoricalSliceDiagnosticV22Error(
            "DATE_ONLY_SOURCE_BAR_COUNT_MISMATCH"
        )
    if result != tuple(sorted(set(result))):
        raise HistoricalSliceDiagnosticV22Error(
            "DATE_ONLY_SOURCE_SESSIONS_NOT_UNIQUE_SORTED"
        )
    return result


def _matured_horizons(
    index: int,
    session_count: int,
) -> tuple[int, ...]:
    return tuple(
        horizon for horizon in HORIZONS if index + horizon < session_count
    )


def _select_spaced_indices(
    candidates: tuple[int, ...],
    *,
    count: int,
    generator: random.Random,
) -> tuple[int, ...]:
    shuffled = list(candidates)
    generator.shuffle(shuffled)
    selected: list[int] = []
    for candidate in shuffled:
        if all(
            abs(candidate - existing) >= MINIMUM_SESSION_SPACING
            for existing in selected
        ):
            selected.append(candidate)
        if len(selected) == count:
            return tuple(sorted(selected))
    raise HistoricalSliceDiagnosticV22Error(
        "SLICE_STRATUM_CANNOT_SATISFY_SPACING"
    )


def _last_session_on_or_before(
    sessions: tuple[date, ...],
    target: date,
) -> int | None:
    for index in range(len(sessions) - 1, -1, -1):
        if sessions[index] <= target:
            return index
    return None


def build_sealed_slice_plan(
    *,
    manifest_path: Path,
    storage_root: Path,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    """Build the deterministic plan without loading any OHLCV outcome value."""

    manifest = _verify_canonical_artifact(manifest_path)
    if manifest.get("status") != "COMPLETE":
        raise HistoricalSliceDiagnosticV22Error(
            "HISTORICAL_PRICE_MANIFEST_NOT_COMPLETE"
        )
    spy_rows = [
        row for row in manifest.get("records", ()) if row.get("symbol") == "SPY"
    ]
    if len(spy_rows) != 1:
        raise HistoricalSliceDiagnosticV22Error(
            "DATE_ONLY_SPY_RECEIPT_NOT_UNIQUE"
        )
    spy = spy_rows[0]
    payload_path = storage_root / str(spy["payloadStorageReference"])
    sessions = _extract_date_only_sessions(
        payload_path,
        expected_file_sha256=str(spy["payloadFileSha256"]),
        expected_bar_count=int(spy["barCount"]),
    )
    effective_as_of = as_of_date or sessions[-1]
    if effective_as_of > sessions[-1]:
        raise HistoricalSliceDiagnosticV22Error(
            "SLICE_AS_OF_EXCEEDS_FROZEN_HISTORY"
        )

    generator = random.Random(RANDOM_SEED)
    random_anchors: list[SliceAnchorV22] = []
    for band_name, minimum_months, maximum_months in AGE_BANDS:
        start = _subtract_months(effective_as_of, maximum_months)
        end = _subtract_months(effective_as_of, minimum_months)
        candidates = tuple(
            index
            for index, session in enumerate(sessions)
            if start <= session <= end
        )
        selected = _select_spaced_indices(
            candidates,
            count=SAMPLES_PER_BAND,
            generator=generator,
        )
        for ordinal, index in enumerate(selected, start=1):
            random_anchors.append(
                SliceAnchorV22(
                    sample_id=f"RANDOM-{band_name}-{ordinal:02d}",
                    selection_method="STRATIFIED_RANDOM_COMPLETED_SESSION",
                    stratum=band_name,
                    decision_date=sessions[index],
                    session_index=index,
                    matured_horizons=_matured_horizons(
                        index,
                        len(sessions),
                    ),
                )
            )

    fixed_anchors: list[SliceAnchorV22] = []
    for offset in FIXED_OFFSETS_MONTHS:
        target = _subtract_months(effective_as_of, offset)
        index = _last_session_on_or_before(sessions, target)
        if index is None:
            continue
        fixed_anchors.append(
            SliceAnchorV22(
                sample_id=f"OFFSET-{offset:03d}-MONTHS",
                selection_method=(
                    "LAST_COMPLETED_SESSION_ON_OR_BEFORE_OFFSET"
                ),
                stratum=f"OFFSET_{offset}_MONTHS",
                decision_date=sessions[index],
                session_index=index,
                matured_horizons=_matured_horizons(index, len(sessions)),
            )
        )

    bindings = {
        "historicalPriceManifest": {
            "path": _display_path(manifest_path, manifest_path.parents[2]),
            "fileSha256": _file_sha256(manifest_path),
            "artifactContentHash": manifest["artifactContentHash"],
        },
        "dateOnlySpyPayload": {
            "path": _display_path(payload_path, manifest_path.parents[2]),
            "fileSha256": str(spy["payloadFileSha256"]).upper(),
            "payloadContentHash": str(spy["payloadContentHash"]),
            "barCount": int(spy["barCount"]),
        },
    }
    body = {
        "artifactType": "HISTORICAL_DQV_SLICE_PLAN",
        "schemaVersion": HISTORICAL_SLICE_PLAN_V22,
        "protocolVersion": "FORWARD-DQV-EVALUATION-PROTOCOL-v2.2.0",
        "evaluationRole": "DEVELOPMENT_OBSERVED",
        "claimCeiling": "DIAGNOSTIC_ONLY",
        "formalGateEligible": False,
        "untouchedHoldout": False,
        "outcomesWereObservableBeforePlan": True,
        "seed": RANDOM_SEED,
        "asOfCompletedSession": effective_as_of.isoformat(),
        "sessionCount": len(sessions),
        "firstSession": sessions[0].isoformat(),
        "lastSession": sessions[-1].isoformat(),
        "horizonsCompletedSessions": list(HORIZONS),
        "samplesPerRandomBand": SAMPLES_PER_BAND,
        "minimumRandomSessionSpacing": MINIMUM_SESSION_SPACING,
        "randomAnchors": [
            _json_value(asdict(anchor)) for anchor in random_anchors
        ],
        "fixedOffsetAnchors": [
            _json_value(asdict(anchor)) for anchor in fixed_anchors
        ],
        "sourceBindings": bindings,
        "selectionBoundary": {
            "dateOnlyFieldsReadBeforeSeal": ["tradingDate"],
            "ohlcvOrOutcomeValuesLoadedBeforeSeal": False,
            "planHashGeneratedBeforeOutcomeLoad": True,
            "selectionAfterReplayAllowed": False,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_immutable_json(path: Path, payload: dict[str, Any]) -> str:
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise HistoricalSliceDiagnosticV22Error(
                f"IMMUTABLE_ARTIFACT_CONFLICT[{path}]"
            )
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return hashlib.sha256(encoded).hexdigest().upper()


def _bar_map(series: HistoricalSeriesV22) -> dict[date, Any]:
    return {
        bar.trading_date: bar
        for bar in series.bars
        if bar.session_complete and bar.volume > 0
    }


def _cost_policy() -> LiquiditySensitiveCostPolicy:
    return LiquiditySensitiveCostPolicy(
        fixed_round_trip_bps=Decimal("2"),
        base_slippage_one_way_bps=Decimal("1"),
        impact_bps_at_full_participation=Decimal("25"),
        maximum_impact_one_way_bps=Decimal("50"),
        version="LIQUIDITY-SENSITIVE-COST-v1.0.0",
    )


def _security_path(
    series: HistoricalSeriesV22,
    sessions: tuple[date, ...],
    *,
    decision_index: int,
    horizon: int,
    order_notional: Decimal,
) -> tuple[
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    Decimal,
] | None:
    if decision_index < 126 or decision_index + horizon >= len(sessions):
        return None
    bars = _bar_map(series)
    decision_date = sessions[decision_index]
    entry_date = sessions[decision_index + 1]
    exit_date = sessions[decision_index + horizon]
    decision = bars.get(decision_date)
    entry = bars.get(entry_date)
    exit_bar = bars.get(exit_date)
    if decision is None or entry is None or exit_bar is None:
        return None
    entry_price = Decimal(str(entry.open_price))
    exit_price = Decimal(str(exit_bar.close_price))
    if entry_price <= 0 or exit_price <= 0:
        return None
    path_bars = [
        bars.get(session)
        for session in sessions[decision_index + 1 : decision_index + horizon + 1]
    ]
    if any(item is None for item in path_bars):
        return None
    valid_path = [item for item in path_bars if item is not None]
    gross = _q(exit_price / entry_price - Decimal(1))
    mae = _q(
        min(Decimal(str(item.low_price)) / entry_price - Decimal(1) for item in valid_path)
    )
    mfe = _q(
        max(Decimal(str(item.high_price)) / entry_price - Decimal(1) for item in valid_path)
    )
    closes = [entry_price, *[Decimal(str(item.close_price)) for item in valid_path]]
    peak = closes[0]
    max_drawdown = ZERO
    daily_returns: list[Decimal] = []
    for previous, current in zip(closes, closes[1:], strict=False):
        peak = max(peak, current)
        max_drawdown = min(max_drawdown, current / peak - Decimal(1))
        daily_returns.append(current / previous - Decimal(1))
    downside = [min(item, ZERO) for item in daily_returns]
    downside_deviation = (
        (sum(item * item for item in downside) / Decimal(len(downside))).sqrt()
        if downside
        else ZERO
    )
    trailing = [
        bars.get(session)
        for session in sessions[decision_index - 19 : decision_index + 1]
    ]
    if any(item is None for item in trailing):
        return None
    adtv = sum(
        Decimal(str(item.close_price)) * Decimal(item.volume)
        for item in trailing
        if item is not None
    ) / Decimal(20)
    if adtv <= 0:
        return None
    cost = _q(
        _cost_policy().round_trip_cost_rate(
            order_notional=order_notional,
            average_daily_dollar_volume=adtv,
        )
    )
    return gross, cost, mae, mfe, _q(max_drawdown), _q(downside_deviation)


def _momentum_score(
    series: HistoricalSeriesV22,
    sessions: tuple[date, ...],
    *,
    decision_index: int,
) -> Decimal | None:
    if decision_index < 126:
        return None
    bars = _bar_map(series)
    current = bars.get(sessions[decision_index])
    previous = bars.get(sessions[decision_index - 126])
    if current is None or previous is None or previous.close_price <= 0:
        return None
    return _q(
        Decimal(str(current.close_price))
        / Decimal(str(previous.close_price))
        - Decimal(1)
    )


def _aggregate_portfolio(
    rows: tuple[
        tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal], ...
    ],
    *,
    population_count: int,
) -> PortfolioPathMetricV22 | None:
    if not rows:
        return None
    count = Decimal(len(rows))
    gross = _q(sum((row[0] for row in rows), ZERO) / count)
    cost = _q(sum((row[1] for row in rows), ZERO) / count)
    return PortfolioPathMetricV22(
        gross_return=gross,
        cost_rate=cost,
        net_return=_q(gross - cost),
        maximum_adverse_excursion=_q(
            sum((row[2] for row in rows), ZERO) / count
        ),
        maximum_favorable_excursion=_q(
            sum((row[3] for row in rows), ZERO) / count
        ),
        maximum_drawdown=_q(
            sum((row[4] for row in rows), ZERO) / count
        ),
        downside_deviation=_q(
            sum((row[5] for row in rows), ZERO) / count
        ),
        holding_count=len(rows),
        coverage=_q(Decimal(len(rows)) / Decimal(population_count)),
    )


def _aggregate_benchmark_diagnostics(
    slices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    aggregates: list[dict[str, Any]] = []
    numeric_fields = (
        "gross_return",
        "cost_rate",
        "net_return",
        "maximum_adverse_excursion",
        "maximum_favorable_excursion",
        "maximum_drawdown",
        "downside_deviation",
        "coverage",
    )
    for horizon in HORIZONS:
        horizon_rows = [
            row
            for row in slices
            if row["horizonCompletedSessions"] == horizon
        ]
        for kind in BenchmarkKind:
            rows = [
                row["benchmarks"][kind.value]
                for row in horizon_rows
            ]
            available = [
                row for row in rows if row["metrics"] is not None
            ]
            if not available:
                aggregates.append(
                    {
                        "horizonCompletedSessions": horizon,
                        "benchmark": kind.value,
                        "status": "MISSING",
                        "observationCount": 0,
                        "reason": rows[0]["reason"] if rows else "NO_MATURED_SLICE",
                        "metrics": None,
                    }
                )
                continue
            metrics: dict[str, Any] = {}
            for field in numeric_fields:
                values = [
                    Decimal(str(row["metrics"][field]))
                    for row in available
                ]
                metrics[field] = format(
                    _q(sum(values, ZERO) / Decimal(len(values))),
                    "f",
                )
            spy_down_rows = [
                row
                for row in horizon_rows
                if row["benchmarks"]["SPY"]["metrics"] is not None
                and Decimal(
                    str(row["benchmarks"]["SPY"]["metrics"]["net_return"])
                )
                < 0
                and row["benchmarks"][kind.value]["metrics"] is not None
            ]
            downside_capture: Decimal | None = None
            if spy_down_rows:
                benchmark_down = sum(
                    (
                        Decimal(
                            str(
                                row["benchmarks"][kind.value]["metrics"][
                                    "net_return"
                                ]
                            )
                        )
                        for row in spy_down_rows
                    ),
                    ZERO,
                ) / Decimal(len(spy_down_rows))
                spy_down = sum(
                    (
                        Decimal(
                            str(
                                row["benchmarks"]["SPY"]["metrics"][
                                    "net_return"
                                ]
                            )
                        )
                        for row in spy_down_rows
                    ),
                    ZERO,
                ) / Decimal(len(spy_down_rows))
                if spy_down != 0:
                    downside_capture = _q(benchmark_down / spy_down)
            metrics["downside_capture_vs_spy"] = (
                format(downside_capture, "f")
                if downside_capture is not None
                else None
            )
            metrics["downsideObservationCount"] = len(spy_down_rows)
            aggregates.append(
                {
                    "horizonCompletedSessions": horizon,
                    "benchmark": kind.value,
                    "status": "AVAILABLE_DIAGNOSTIC_ONLY",
                    "observationCount": len(available),
                    "reason": available[0]["reason"],
                    "metrics": metrics,
                }
            )
    return aggregates


def _benchmark_rows(
    *,
    series_by_identifier: Mapping[str, HistoricalSeriesV22],
    security_ids: tuple[str, ...],
    sessions: tuple[date, ...],
    decision_index: int,
    horizon: int,
    order_notional: Decimal,
) -> dict[str, Any]:
    paths: dict[str, tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]] = {}
    momentum: dict[str, Decimal] = {}
    for security_id in security_ids:
        series = series_by_identifier.get(security_id)
        if series is None:
            continue
        path = _security_path(
            series,
            sessions,
            decision_index=decision_index,
            horizon=horizon,
            order_notional=order_notional,
        )
        score = _momentum_score(
            series,
            sessions,
            decision_index=decision_index,
        )
        if path is not None:
            paths[security_id] = path
        if score is not None:
            momentum[security_id] = score
    equal_weight = _aggregate_portfolio(
        tuple(paths[key] for key in sorted(paths)),
        population_count=len(security_ids),
    )
    ordered_momentum = sorted(
        (
            (security_id, score)
            for security_id, score in momentum.items()
            if security_id in paths
        ),
        key=lambda item: (item[1], item[0]),
    )
    selection_count = (
        max(1, math.ceil(len(ordered_momentum) * 0.2))
        if ordered_momentum
        else 0
    )
    selected = tuple(
        security_id
        for security_id, _score in ordered_momentum[-selection_count:]
    )
    pure_momentum = _aggregate_portfolio(
        tuple(paths[key] for key in selected),
        population_count=len(security_ids),
    )
    spy_series = series_by_identifier.get("SPY")
    spy_path = (
        _security_path(
            spy_series,
            sessions,
            decision_index=decision_index,
            horizon=horizon,
            order_notional=order_notional,
        )
        if spy_series is not None
        else None
    )
    spy = (
        _aggregate_portfolio((spy_path,), population_count=1)
        if spy_path is not None
        else None
    )

    def available(
        identifier: str,
        metric: PortfolioPathMetricV22 | None,
        *,
        limitation: str,
    ) -> dict[str, Any]:
        if metric is None:
            return {
                "identifier": identifier,
                "status": "MISSING",
                "reason": "INSUFFICIENT_HASH_VERIFIED_PRICE_PATH",
                "metrics": None,
            }
        return {
            "identifier": identifier,
            "status": "AVAILABLE_DIAGNOSTIC_ONLY",
            "reason": limitation,
            "metrics": _json_value(asdict(metric)),
        }

    return {
        BenchmarkKind.SPY.value: available(
            "SPY",
            spy,
            limitation="CURRENT_REVISION_EX_POST_TOTAL_RETURN_PRICE",
        ),
        BenchmarkKind.SECTOR.value: {
            "identifier": "DATED_SECTOR_ETF",
            "status": "MISSING",
            "reason": "HISTORICAL_DATED_SECTOR_MAPPING_AND_ETF_SERIES_MISSING",
            "metrics": None,
        },
        BenchmarkKind.EQUAL_WEIGHT.value: available(
            "CURRENT_UNIVERSE_EQUAL_WEIGHT",
            equal_weight,
            limitation="CURRENT_UNIVERSE_RETROSPECTIVE_SURVIVORSHIP_BIAS",
        ),
        BenchmarkKind.PURE_MOMENTUM.value: available(
            "TRAILING_126_SESSION_TOP_QUINTILE",
            pure_momentum,
            limitation=(
                "CURRENT_UNIVERSE_RETROSPECTIVE_PRICE_ONLY_SELECTION"
            ),
        ),
        BenchmarkKind.PURE_VALUE.value: {
            "identifier": "PURE_VALUE",
            "status": "MISSING",
            "reason": "HISTORICAL_PIT_VALUE_SCORE_EVIDENCE_MISSING",
            "metrics": None,
        },
        BenchmarkKind.PURE_QUALITY.value: {
            "identifier": "PURE_QUALITY",
            "status": "MISSING",
            "reason": "HISTORICAL_PIT_QUALITY_SCORE_EVIDENCE_MISSING",
            "metrics": None,
        },
    }


def _load_universe(universe_path: Path) -> tuple[dict[str, Any], tuple[str, ...]]:
    payload = json.loads(universe_path.read_text(encoding="utf-8"))
    roles = payload.get("roles")
    if not isinstance(roles, dict):
        raise HistoricalSliceDiagnosticV22Error("UNIVERSE_ROLES_MISSING")
    security_ids = tuple(
        str(symbol)
        for role in ("PRIMARY", "RESERVE")
        for symbol in roles.get(role, ())
    )
    if len(security_ids) != 55 or len(set(security_ids)) != 55:
        raise HistoricalSliceDiagnosticV22Error(
            "UNIVERSE_PRIMARY_RESERVE_POPULATION_CHANGED"
        )
    return payload, security_ids


def _binding(path: Path, repository_root: Path) -> dict[str, str]:
    payload = _verify_canonical_artifact(path)
    return {
        "path": _display_path(path, repository_root),
        "fileSha256": _file_sha256(path),
        "artifactContentHash": str(payload["artifactContentHash"]),
    }


def run_sealed_historical_diagnostic(
    *,
    plan_path: Path,
    manifest_path: Path,
    storage_root: Path,
    universe_path: Path,
    tactical_freeze_path: Path,
    long_horizon_freeze_path: Path,
    protocol_fixture_path: Path,
    controlled_output_root: Path,
    order_notional: Decimal = Decimal("10000"),
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Load outcomes only after verifying the already persisted sealed plan."""

    if not plan_path.is_file():
        raise HistoricalSliceDiagnosticV22Error(
            "SEALED_PLAN_MUST_EXIST_BEFORE_OUTCOME_LOAD"
        )
    plan = _verify_canonical_artifact(plan_path)
    if (
        plan.get("schemaVersion") != HISTORICAL_SLICE_PLAN_V22
        or plan.get("formalGateEligible") is not False
        or plan.get("untouchedHoldout") is not False
    ):
        raise HistoricalSliceDiagnosticV22Error(
            "SEALED_PLAN_CONTRACT_MISMATCH"
        )
    manifest_binding = plan["sourceBindings"]["historicalPriceManifest"]
    if (
        _file_sha256(manifest_path) != manifest_binding["fileSha256"]
        or _verify_canonical_artifact(manifest_path)["artifactContentHash"]
        != manifest_binding["artifactContentHash"]
    ):
        raise HistoricalSliceDiagnosticV22Error(
            "SEALED_PLAN_SOURCE_MANIFEST_DRIFT"
        )
    universe, security_ids = _load_universe(universe_path)
    repository_root = universe_path.resolve().parents[3]
    manifest, series_by_identifier = load_hash_verified_yahoo_cache_v22(
        manifest_path=manifest_path,
        storage_root=storage_root,
    )
    if set(security_ids) - set(series_by_identifier):
        raise HistoricalSliceDiagnosticV22Error(
            "FROZEN_DIAGNOSTIC_PRICE_POPULATION_INCOMPLETE"
        )
    spy = series_by_identifier.get("SPY")
    if spy is None:
        raise HistoricalSliceDiagnosticV22Error("SPY_SERIES_MISSING")
    sessions = tuple(
        bar.trading_date
        for bar in spy.bars
        if bar.session_complete and bar.volume > 0
    )
    if (
        len(sessions) != int(plan["sessionCount"])
        or sessions[0].isoformat() != plan["firstSession"]
        or sessions[-1].isoformat() != plan["lastSession"]
    ):
        raise HistoricalSliceDiagnosticV22Error(
            "SEALED_PLAN_SESSION_CALENDAR_DRIFT"
        )

    source_bindings = {
        "slicePlan": _binding(plan_path, repository_root),
        "historicalPriceManifest": _binding(
            manifest_path,
            repository_root,
        ),
        "tacticalFreeze": _binding(
            tactical_freeze_path,
            repository_root,
        ),
        "longHorizonFreeze": _binding(
            long_horizon_freeze_path,
            repository_root,
        ),
        "forwardDqvProtocol": _binding(
            protocol_fixture_path,
            repository_root,
        ),
        "universe": {
            "path": _display_path(universe_path, repository_root),
            "fileSha256": _file_sha256(universe_path),
            "universeVersion": universe.get("universeVersion"),
        },
    }
    anchors = [
        *plan["randomAnchors"],
        *plan["fixedOffsetAnchors"],
    ]
    slices: list[dict[str, Any]] = []
    model_rows: list[dict[str, Any]] = []
    for anchor in anchors:
        decision_index = int(anchor["session_index"])
        for horizon in anchor["matured_horizons"]:
            benchmark_rows = _benchmark_rows(
                series_by_identifier=series_by_identifier,
                security_ids=security_ids,
                sessions=sessions,
                decision_index=decision_index,
                horizon=int(horizon),
                order_notional=order_notional,
            )
            slices.append(
                {
                    "sampleId": anchor["sample_id"],
                    "selectionMethod": anchor["selection_method"],
                    "stratum": anchor["stratum"],
                    "decisionDate": anchor["decision_date"],
                    "horizonCompletedSessions": int(horizon),
                    "benchmarks": benchmark_rows,
                }
            )
            track = (
                "TACTICAL"
                if int(horizon) in TACTICAL_HORIZONS
                else "LONG_HORIZON"
            )
            reasons = (
                [
                    "HISTORICAL_EVENT_EVIDENCE_NOT_PIT_READY",
                    "HISTORICAL_DATED_SECTOR_MAPPING_NOT_PIT_READY",
                    "MODEL_INPUT_EVIDENCE_INCOMPLETE",
                ]
                if track == "TACTICAL"
                else [
                    "HISTORICAL_FUNDAMENTAL_INPUTS_NOT_PIT_READY",
                    "HISTORICAL_REVISION_LINEAGE_INCOMPLETE",
                    "HISTORICAL_MEMBERSHIP_NOT_PIT",
                    "MODEL_INPUT_EVIDENCE_INCOMPLETE",
                ]
            )
            model_rows.append(
                {
                    "sampleId": anchor["sample_id"],
                    "decisionDate": anchor["decision_date"],
                    "horizonCompletedSessions": int(horizon),
                    "track": track,
                    "modelVersion": (
                        TACTICAL_MODEL_VERSION
                        if track == "TACTICAL"
                        else LONG_HORIZON_MODEL_VERSION
                    ),
                    "status": "REJECTED_FOR_MODEL_EVALUATION",
                    "reasonCodes": reasons,
                    "population": {
                        "total": 55,
                        "assessed": 0,
                        "missing": 55,
                        "invalid": 0,
                        "excluded": 0,
                        "abstained": 0,
                        "coverage": "0.00000000",
                    },
                    "grossReturn": None,
                    "costRate": None,
                    "netReturn": None,
                    "maximumAdverseExcursion": None,
                    "maximumFavorableExcursion": None,
                    "maximumDrawdown": None,
                    "downsideDeviation": None,
                }
            )

    controlled_body = {
        "artifactType": "HISTORICAL_DQV_SLICE_DIAGNOSTIC_CONTROLLED",
        "schemaVersion": HISTORICAL_SLICE_DIAGNOSTIC_V22,
        "evaluationRole": "DEVELOPMENT_OBSERVED",
        "claimCeiling": "DIAGNOSTIC_ONLY",
        "formalGateEligible": False,
        "untouchedHoldout": False,
        "outcomesWereObservableBeforeProtocol": True,
        "slicePlanHash": plan["artifactContentHash"],
        "sourceBindings": source_bindings,
        "slices": slices,
        "benchmarkAggregates": _aggregate_benchmark_diagnostics(slices),
        "modelTrackRows": model_rows,
        "execution": {
            "planPersistedAndVerifiedBeforeOutcomeLoad": True,
            "providerNetworkRequests": 0,
            "databaseReads": 0,
            "databaseWrites": 0,
            "modelsExecuted": False,
            "modelWeightsOrThresholdsChanged": False,
            "benchmarkMetricsComputed": True,
            "rawProviderValuesIncluded": False,
            "derivedLicensedMetricsIncluded": True,
            "automaticTradingAuthorized": False,
        },
    }
    controlled = {
        **controlled_body,
        "artifactContentHash": canonical_hash(controlled_body),
    }
    controlled_hash = controlled["artifactContentHash"].removeprefix(
        "sha256:"
    )
    controlled_path = (
        controlled_output_root / f"{controlled_hash}.json"
    )
    controlled_file_hash = write_immutable_json(controlled_path, controlled)

    benchmark_availability = {
        "SPY": "AVAILABLE_DIAGNOSTIC_ONLY",
        "SECTOR": "MISSING",
        "EQUAL_WEIGHT": "AVAILABLE_DIAGNOSTIC_ONLY",
        "PURE_MOMENTUM": "AVAILABLE_DIAGNOSTIC_ONLY",
        "PURE_VALUE": "MISSING",
        "PURE_QUALITY": "MISSING",
    }
    tactical_rows = [
        row for row in model_rows if row["track"] == "TACTICAL"
    ]
    long_rows = [
        row for row in model_rows if row["track"] == "LONG_HORIZON"
    ]
    git_safe_body = {
        "artifactType": "HISTORICAL_DQV_SLICE_DIAGNOSTIC_CLOSEOUT",
        "schemaVersion": HISTORICAL_SLICE_GIT_SAFE_CLOSEOUT_V22,
        "evaluationRole": "DEVELOPMENT_OBSERVED",
        "claimCeiling": "DIAGNOSTIC_ONLY",
        "formalGateEligible": False,
        "untouchedHoldout": False,
        "terminalStatus": "CLOSED_WITHOUT_MODEL_VALIDATION",
        "sourceBindings": source_bindings,
        "controlledResult": {
            "storageType": "GITIGNORED_LOCAL",
            "path": _display_path(controlled_path, repository_root),
            "fileSha256": controlled_file_hash,
            "artifactContentHash": controlled["artifactContentHash"],
            "rawProviderValuesIncluded": False,
            "derivedLicensedMetricsIncluded": True,
        },
        "sliceSummary": {
            "randomAnchorCount": len(plan["randomAnchors"]),
            "fixedOffsetAnchorCount": len(plan["fixedOffsetAnchors"]),
            "totalAnchorCount": len(anchors),
            "maturedAnchorHorizonCount": len(slices),
            "benchmarkMetricSliceCount": len(slices),
            "tacticalModelEvaluatedSliceCount": 0,
            "tacticalRejectedSliceCount": len(tactical_rows),
            "longHorizonModelEvaluatedSliceCount": 0,
            "longHorizonRejectedSliceCount": len(long_rows),
        },
        "benchmarkAvailability": benchmark_availability,
        "population": {
            "mode": "CURRENT_UNIVERSE_RETROSPECTIVE",
            "securityCount": len(security_ids),
            "historicalMembershipClaimed": False,
            "survivorshipBiasPresent": True,
        },
        "claimBoundary": {
            "historicalEngineeringDiagnosticsAllowed": True,
            "historicalModelValidationClaimAllowed": False,
            "formalForwardDqvSatisfied": False,
            "statisticalEdgeProven": False,
            "favorableSliceSelectionAllowed": False,
            "retuningFromObservedOutcomesAllowed": False,
            "statement": (
                "Only SPY, current-universe equal-weight, and price-only "
                "momentum benchmark path diagnostics were constructable. "
                "Tactical v2.2 and Long Horizon v1.1 model evaluation was "
                "rejected because required historical point-in-time evidence "
                "is missing. These already observable outcomes are not an "
                "untouched holdout and cannot support a formal validation claim."
            ),
        },
        "execution": {
            "planHashGeneratedBeforeOutcomeLoad": True,
            "providerNetworkRequests": 0,
            "databaseWrites": 0,
            "modelsExecuted": False,
            "scoresOrRanksGenerated": False,
            "weightsOrThresholdsChanged": False,
            "rawProviderValuesIncluded": False,
            "automaticTradingAuthorized": False,
        },
    }
    git_safe = {
        **git_safe_body,
        "artifactContentHash": canonical_hash(git_safe_body),
    }
    return controlled, git_safe, controlled_path
