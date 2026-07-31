from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any
from uuid import uuid5

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.daily_refresh.universe import (
    SECURITY_NAMESPACE,
    load_closed_test_universe,
)
from equity_analysis.historical_validation.model_freeze_v1 import (
    verify_model_freeze_artifact,
)
from equity_analysis.historical_validation.protocol_v2 import (
    BenchmarkKind,
    LiquiditySensitiveCostPolicy,
)
from equity_analysis.historical_validation.slice_diagnostic_v22 import (
    _verify_canonical_artifact,
    write_immutable_json,
)
from equity_analysis.historical_validation.tactical_v22_diagnostic import (
    HistoricalSeriesV22,
    load_hash_verified_yahoo_cache_v22,
)
from equity_analysis.tactical.contracts_v22 import (
    Actionability,
    EventEvidenceV22,
    EvidenceState,
    SeriesEvidenceV22,
    TacticalBarV22,
    TacticalContextV22,
)
from equity_analysis.tactical.signal_v22 import evaluate_tactical_signal_v22

TIER1_SCHEMA_VERSION = "TACTICAL-V2.2-TIER1-RETROSPECTIVE-v1.0.0"
TIER1_CONTROLLED_SCHEMA_VERSION = (
    "TACTICAL-V2.2-TIER1-RETROSPECTIVE-CONTROLLED-v1.0.0"
)
MODEL_VERSION = "TACTICAL-SIGNAL-v2.2.0"
SECTOR_PROXY_POLICY_VERSION = (
    "CURRENT-UNIVERSE-SECTOR-DAILY-REBALANCED-PROXY-v1.0.0"
)
MOMENTUM_POLICY_VERSION = "PURE-MOMENTUM-12-1-v2.1.0"
MOMENTUM_START_OFFSET = 252
MOMENTUM_END_OFFSET = 21
HORIZONS = (5, 20, 60)
VALUE_SCALE = Decimal("0.00000001")
ZERO = Decimal(0)


class Tier1RetrospectiveError(ValueError):
    pass


def _q(value: Decimal) -> Decimal:
    return value.quantize(VALUE_SCALE, rounding=ROUND_HALF_EVEN)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    return value


def _display_path(path: Path, repository_root: Path) -> str:
    try:
        return path.resolve().relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _binding(
    path: Path,
    *,
    repository_root: Path,
    canonical: bool = True,
) -> dict[str, str]:
    result = {
        "path": _display_path(path, repository_root),
        "fileSha256": _file_sha256(path),
    }
    if canonical:
        payload = _verify_canonical_artifact(path)
        result["artifactContentHash"] = str(payload["artifactContentHash"])
    return result


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return _q(sum(values, ZERO) / Decimal(len(values)))


def _average_ranks(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [ZERO] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        rank = Decimal(cursor + 1 + end) / Decimal(2)
        for index in range(cursor, end):
            ranks[ordered[index][0]] = rank
        cursor = end
    return tuple(ranks)


def _pearson(
    left: tuple[Decimal, ...],
    right: tuple[Decimal, ...],
) -> Decimal | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left, ZERO) / Decimal(len(left))
    right_mean = sum(right, ZERO) / Decimal(len(right))
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    )
    denominator = (
        sum((value - left_mean) ** 2 for value in left)
        * sum((value - right_mean) ** 2 for value in right)
    ).sqrt()
    if denominator == ZERO:
        return None
    return _q(numerator / denominator)


def _rank_ic(rows: tuple[dict[str, Any], ...]) -> Decimal | None:
    return _pearson(
        _average_ranks(tuple(Decimal(str(row["score"])) for row in rows)),
        _average_ranks(
            tuple(Decimal(str(row["netReturn"])) for row in rows)
        ),
    )


def _cost_policy() -> LiquiditySensitiveCostPolicy:
    return LiquiditySensitiveCostPolicy(
        fixed_round_trip_bps=Decimal("2"),
        base_slippage_one_way_bps=Decimal("1"),
        impact_bps_at_full_participation=Decimal("25"),
        maximum_impact_one_way_bps=Decimal("50"),
        version="LIQUIDITY-SENSITIVE-COST-v1.0.0",
    )


def _bar_map(series: HistoricalSeriesV22) -> dict[date, TacticalBarV22]:
    return {
        bar.trading_date: bar
        for bar in series.bars
        if bar.session_complete and bar.volume > 0
    }


def _bars_through(
    series: HistoricalSeriesV22,
    decision_date: date,
) -> tuple[TacticalBarV22, ...]:
    eligible = tuple(
        bar
        for bar in series.bars
        if bar.session_complete and bar.trading_date <= decision_date
    )
    # The frozen signal's longest feature window is 120 sessions. Retaining
    # 253 completed sessions is conservative and prevents runtime from growing
    # with evidence that no frozen feature can read.
    return eligible[-253:]


def _series_evidence(
    series: HistoricalSeriesV22,
    decision_date: date,
) -> SeriesEvidenceV22:
    return SeriesEvidenceV22(
        state=EvidenceState.VALID,
        provider="yfinance-hash-verified-current-revision-cache",
        source_hash=series.source_hash,
        available_at=series.available_at,
        ingested_at=series.ingested_at,
        bars=_bars_through(series, decision_date),
    )


def _path(
    series: HistoricalSeriesV22,
    sessions: tuple[date, ...],
    *,
    decision_index: int,
    horizon: int,
    order_notional: Decimal,
) -> dict[str, Decimal] | None:
    if decision_index + horizon >= len(sessions):
        return None
    bars = _bar_map(series)
    decision_date = sessions[decision_index]
    entry_date = sessions[decision_index + 1]
    exit_date = sessions[decision_index + horizon]
    required = sessions[decision_index + 1 : decision_index + horizon + 1]
    if any(session not in bars for session in required):
        return None
    entry = Decimal(str(bars[entry_date].open_price))
    terminal = Decimal(str(bars[exit_date].close_price))
    if entry <= 0 or terminal <= 0:
        return None
    trailing = [
        bar
        for session, bar in sorted(bars.items())
        if session <= decision_date
    ][-20:]
    if len(trailing) != 20:
        return None
    adtv = sum(
        Decimal(str(bar.close_price)) * Decimal(bar.volume)
        for bar in trailing
    ) / Decimal(20)
    if adtv <= 0:
        return None
    cost = _q(
        _cost_policy().round_trip_cost_rate(
            order_notional=order_notional,
            average_daily_dollar_volume=adtv,
        )
    )
    path_bars = tuple(bars[session] for session in required)
    gross = _q(terminal / entry - Decimal(1))
    return {
        "grossReturn": gross,
        "costRate": cost,
        "netReturn": _q(gross - cost),
        "maximumAdverseExcursion": _q(
            min(
                Decimal(str(bar.low_price)) / entry - Decimal(1)
                for bar in path_bars
            )
        ),
        "maximumFavorableExcursion": _q(
            max(
                Decimal(str(bar.high_price)) / entry - Decimal(1)
                for bar in path_bars
            )
        ),
        "averageDailyDollarVolume": _q(adtv),
    }


def _load_current_sector_map(
    path: Path,
    symbols: tuple[str, ...],
) -> tuple[dict[str, str], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("candidates")
    if not isinstance(rows, list):
        raise Tier1RetrospectiveError("CURRENT_CLASSIFICATION_ROWS_MISSING")
    mapping = {
        str(row["symbol"]).upper(): str(row["sector"])
        for row in rows
        if str(row.get("symbol", "")).upper() in symbols
    }
    if set(mapping) != set(symbols):
        missing = ",".join(sorted(set(symbols) - set(mapping)))
        raise Tier1RetrospectiveError(
            f"CURRENT_CLASSIFICATION_INCOMPLETE[{missing}]"
        )
    return mapping, canonical_hash(mapping)


def _build_sector_proxy(
    *,
    sector: str,
    members: tuple[str, ...],
    series_by_symbol: Mapping[str, HistoricalSeriesV22],
    sessions: tuple[date, ...],
    mapping_hash: str,
) -> HistoricalSeriesV22:
    member_maps = {
        symbol: _bar_map(series_by_symbol[symbol]) for symbol in members
    }
    index_close = Decimal("100")
    bars: list[TacticalBarV22] = []
    for prior_date, session in zip(sessions[:-1], sessions[1:], strict=True):
        rows = [
            (member_maps[symbol][prior_date], member_maps[symbol][session])
            for symbol in members
            if prior_date in member_maps[symbol]
            and session in member_maps[symbol]
        ]
        if not rows:
            continue
        count = Decimal(len(rows))
        open_ratio = sum(
            Decimal(str(current.open_price))
            / Decimal(str(previous.close_price))
            for previous, current in rows
        ) / count
        high_ratio = sum(
            Decimal(str(current.high_price))
            / Decimal(str(previous.close_price))
            for previous, current in rows
        ) / count
        low_ratio = sum(
            Decimal(str(current.low_price))
            / Decimal(str(previous.close_price))
            for previous, current in rows
        ) / count
        close_ratio = sum(
            Decimal(str(current.close_price))
            / Decimal(str(previous.close_price))
            for previous, current in rows
        ) / count
        open_price = index_close * open_ratio
        close_price = index_close * close_ratio
        high_price = max(
            index_close * high_ratio,
            open_price,
            close_price,
        )
        low_price = min(
            index_close * low_ratio,
            open_price,
            close_price,
        )
        dollar_volume = sum(
            Decimal(str(current.close_price)) * Decimal(current.volume)
            for _previous, current in rows
        )
        volume = max(1, int(dollar_volume / max(close_price, Decimal("1"))))
        bars.append(
            TacticalBarV22(
                trading_date=session,
                open_price=float(open_price),
                high_price=float(high_price),
                low_price=float(low_price),
                close_price=float(close_price),
                volume=volume,
                adjustment_factor=1.0,
                session_complete=True,
            )
        )
        index_close = close_price
    sources = tuple(
        sorted(series_by_symbol[symbol].source_hash for symbol in members)
    )
    source_hash = hashlib.sha256(
        json.dumps(
            {
                "policy": SECTOR_PROXY_POLICY_VERSION,
                "sector": sector,
                "members": members,
                "mappingHash": mapping_hash,
                "sourceHashes": sources,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return HistoricalSeriesV22(
        identifier=f"CURRENT-SECTOR-PROXY:{sector}",
        source_hash=source_hash,
        available_at=max(
            series_by_symbol[symbol].available_at for symbol in members
        ),
        ingested_at=max(
            series_by_symbol[symbol].ingested_at for symbol in members
        ),
        bars=tuple(bars),
    )


def _momentum_12_1(
    series: HistoricalSeriesV22,
    sessions: tuple[date, ...],
    decision_index: int,
) -> Decimal | None:
    if decision_index < MOMENTUM_START_OFFSET:
        return None
    bars = _bar_map(series)
    start = bars.get(sessions[decision_index - MOMENTUM_START_OFFSET])
    end = bars.get(sessions[decision_index - MOMENTUM_END_OFFSET])
    if start is None or end is None or start.close_price <= 0:
        return None
    return _q(
        Decimal(str(end.close_price))
        / Decimal(str(start.close_price))
        - Decimal(1)
    )


def _top_quintile(
    rows: tuple[dict[str, Any], ...],
    *,
    field: str,
) -> tuple[dict[str, Any], ...]:
    ordered = sorted(
        rows,
        key=lambda row: (Decimal(str(row[field])), str(row["symbol"])),
    )
    count = max(1, math.ceil(len(ordered) * 0.2))
    return tuple(ordered[-count:])


def _portfolio_metric(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
    if not rows:
        return None
    return {
        "holdingCount": len(rows),
        "grossReturn": _mean(
            tuple(Decimal(str(row["grossReturn"])) for row in rows)
        ),
        "costRate": _mean(
            tuple(Decimal(str(row["costRate"])) for row in rows)
        ),
        "netReturn": _mean(
            tuple(Decimal(str(row["netReturn"])) for row in rows)
        ),
        "maximumAdverseExcursion": _mean(
            tuple(
                Decimal(str(row["maximumAdverseExcursion"]))
                for row in rows
            )
        ),
        "maximumFavorableExcursion": _mean(
            tuple(
                Decimal(str(row["maximumFavorableExcursion"]))
                for row in rows
            )
        ),
    }


def _volatility(values: tuple[Decimal, ...]) -> Decimal | None:
    if len(values) < 2:
        return None
    average = sum(values, ZERO) / Decimal(len(values))
    variance = sum((value - average) ** 2 for value in values) / Decimal(
        len(values)
    )
    return _q(variance.sqrt())


def _maximum_drawdown(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    wealth = Decimal(1)
    peak = Decimal(1)
    drawdown = ZERO
    for value in values:
        wealth *= Decimal(1) + value
        peak = max(peak, wealth)
        drawdown = min(drawdown, wealth / peak - Decimal(1))
    return _q(drawdown)


def _capture(
    model: tuple[Decimal, ...],
    benchmark: tuple[Decimal, ...],
    *,
    positive: bool,
) -> tuple[Decimal | None, int]:
    pairs = tuple(
        (model_value, benchmark_value)
        for model_value, benchmark_value in zip(
            model,
            benchmark,
            strict=True,
        )
        if (benchmark_value > ZERO if positive else benchmark_value < ZERO)
    )
    if not pairs:
        return None, 0
    model_mean = _mean(tuple(item[0] for item in pairs))
    benchmark_mean = _mean(tuple(item[1] for item in pairs))
    if model_mean is None or benchmark_mean in {None, ZERO}:
        return None, len(pairs)
    return _q(model_mean / benchmark_mean), len(pairs)


def _turnover(decisions: tuple[dict[str, Any], ...]) -> Decimal | None:
    if len(decisions) < 2:
        return None
    values: list[Decimal] = []
    ordered = sorted(
        decisions,
        key=lambda row: (row["decisionDate"], row["sampleId"]),
    )
    for previous, current in zip(ordered, ordered[1:], strict=False):
        left = set(previous["scoreRankedSelection"])
        right = set(current["scoreRankedSelection"])
        denominator = max(len(left), len(right))
        values.append(
            ZERO
            if denominator == 0
            else Decimal(1)
            - Decimal(len(left & right)) / Decimal(denominator)
        )
    return _mean(tuple(values))


def _stability_rows(
    decisions: tuple[dict[str, Any], ...],
    *,
    grouping_field: str,
) -> tuple[dict[str, Any], ...]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for decision in decisions:
        grouped[str(decision[grouping_field])].append(decision)
    result: list[dict[str, Any]] = []
    for group, group_rows in sorted(grouped.items()):
        group_decisions = tuple(group_rows)
        model_returns = tuple(
            Decimal(str(row["scoreRankedPortfolio"]["netReturn"]))
            for row in group_decisions
            if row["scoreRankedPortfolio"] is not None
        )
        rank_values = tuple(
            value
            for value in (
                _rank_ic(tuple(row["securityRows"]))
                for row in group_decisions
            )
            if value is not None
        )
        result.append(
            {
                "group": group,
                "decisionCount": len(group_decisions),
                "averageNetReturn": _mean(model_returns),
                "hitRate": (
                    _q(
                        Decimal(sum(value > ZERO for value in model_returns))
                        / Decimal(len(model_returns))
                    )
                    if model_returns
                    else None
                ),
                "averageRankInformationCoefficient": _mean(rank_values),
            }
        )
    return tuple(result)


def _benchmark_row(
    *,
    identifier: str,
    metric: dict[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    return {
        "identifier": identifier,
        "status": (
            "AVAILABLE_DIAGNOSTIC_ONLY" if metric is not None else "MISSING"
        ),
        "reason": reason,
        "metrics": metric,
    }


def _time_band(anchor: Mapping[str, Any]) -> str:
    stratum = str(anchor["stratum"])
    if stratum in {
        "RECENT_3_TO_9_MONTHS",
        "PRIOR_1_TO_3_YEARS",
        "OLDER_4_TO_10_YEARS",
    }:
        return stratum
    if stratum.startswith("OFFSET_") and stratum.endswith("_MONTHS"):
        months = int(stratum.removeprefix("OFFSET_").removesuffix("_MONTHS"))
        if months <= 9:
            return "RECENT_3_TO_9_MONTHS"
        if months <= 36:
            return "PRIOR_1_TO_3_YEARS"
        return "OLDER_4_TO_10_YEARS"
    return "OTHER"


def _aggregate_horizon(
    decisions: tuple[dict[str, Any], ...],
    *,
    horizon: int,
) -> dict[str, Any]:
    assessed_rows = tuple(
        row for decision in decisions for row in decision["securityRows"]
    )
    rank_ics = tuple(
        value
        for value in (
            _rank_ic(tuple(decision["securityRows"]))
            for decision in decisions
        )
        if value is not None
    )
    top_rows_by_decision = tuple(
        tuple(decision["scoreRankedSelection"]) for decision in decisions
    )
    top_net = tuple(
        Decimal(str(decision["scoreRankedPortfolio"]["netReturn"]))
        for decision in decisions
        if decision["scoreRankedPortfolio"] is not None
    )
    spy_net = tuple(
        Decimal(str(decision["benchmarks"]["SPY"]["metrics"]["netReturn"]))
        for decision in decisions
        if decision["scoreRankedPortfolio"] is not None
        and decision["benchmarks"]["SPY"]["metrics"] is not None
    )
    spreads: list[Decimal] = []
    for decision in decisions:
        rows = tuple(decision["securityRows"])
        if len(rows) < 4:
            continue
        top = _top_quintile(rows, field="score")
        bottom = tuple(
            sorted(
                rows,
                key=lambda row: (
                    Decimal(str(row["score"])),
                    str(row["symbol"]),
                ),
            )[: len(top)]
        )
        top_mean = _mean(
            tuple(Decimal(str(row["netReturn"])) for row in top)
        )
        bottom_mean = _mean(
            tuple(Decimal(str(row["netReturn"])) for row in bottom)
        )
        if top_mean is not None and bottom_mean is not None:
            spreads.append(_q(top_mean - bottom_mean))
    benchmark_aggregates: dict[str, Any] = {}
    for kind in BenchmarkKind:
        rows = tuple(decision["benchmarks"][kind.value] for decision in decisions)
        available = tuple(
            row for row in rows if row["metrics"] is not None
        )
        benchmark_mean = _mean(
            tuple(
                Decimal(str(row["metrics"]["netReturn"]))
                for row in available
            )
        )
        top_mean = _mean(top_net)
        benchmark_aggregates[kind.value] = {
            "status": (
                "AVAILABLE_DIAGNOSTIC_ONLY" if available else "MISSING"
            ),
            "observationCount": len(available),
            "averageNetReturn": benchmark_mean,
            "scoreRankedModelMinusBenchmark": (
                _q(top_mean - benchmark_mean)
                if top_mean is not None and benchmark_mean is not None
                else None
            ),
            "reason": rows[0]["reason"] if rows else "NO_MATURED_DECISION",
        }
    actionability = Counter(
        str(row["actionability"]) for row in assessed_rows
    )
    thesis = Counter(str(row["selectedThesis"]) for row in assessed_rows)
    terminal = Counter(
        state
        for decision in decisions
        for state in decision["terminalPopulation"].values()
    )
    volatility = _volatility(top_net)
    average_top = _mean(top_net)
    upside_capture, upside_count = _capture(
        top_net,
        spy_net,
        positive=True,
    )
    downside_capture, downside_count = _capture(
        top_net,
        spy_net,
        positive=False,
    )
    ordered_non_overlapping: list[dict[str, Any]] = []
    last_terminal_index = -1
    for decision in sorted(
        decisions,
        key=lambda row: (row["decisionSessionIndex"], row["sampleId"]),
    ):
        if int(decision["decisionSessionIndex"]) <= last_terminal_index:
            continue
        ordered_non_overlapping.append(decision)
        last_terminal_index = int(decision["decisionSessionIndex"]) + horizon
    non_overlapping_returns = tuple(
        Decimal(str(row["scoreRankedPortfolio"]["netReturn"]))
        for row in ordered_non_overlapping
        if row["scoreRankedPortfolio"] is not None
    )
    return {
        "horizonCompletedSessions": horizon,
        "decisionCount": len(decisions),
        "assessedSecurityObservationCount": len(assessed_rows),
        "coverage": _q(
            Decimal(len(assessed_rows))
            / Decimal(max(1, len(decisions) * 55))
        ),
        "averageRankInformationCoefficient": _mean(rank_ics),
        "averageTopMinusBottomNetReturn": _mean(tuple(spreads)),
        "scoreRankedTopQuintile": {
            "episodeCount": len(top_net),
            "averageHoldingCount": _mean(
                tuple(
                    Decimal(len(rows)) for rows in top_rows_by_decision
                )
            ),
            "averageNetReturn": _mean(top_net),
            "hitRate": (
                _q(
                    Decimal(sum(value > ZERO for value in top_net))
                    / Decimal(len(top_net))
                )
                if top_net
                else None
            ),
            "worstNetReturn": min(top_net) if top_net else None,
            "returnVolatility": volatility,
            "meanToVolatilityRatio": (
                _q(average_top / volatility)
                if average_top is not None
                and volatility not in {None, ZERO}
                else None
            ),
            "upsideCaptureVsSpy": upside_capture,
            "upsideCaptureObservationCount": upside_count,
            "downsideCaptureVsSpy": downside_capture,
            "downsideCaptureObservationCount": downside_count,
            "averageOneWaySelectionTurnover": _turnover(decisions),
            "averageCostRate": _mean(
                tuple(
                    Decimal(
                        str(decision["scoreRankedPortfolio"]["costRate"])
                    )
                    for decision in decisions
                    if decision["scoreRankedPortfolio"] is not None
                )
            ),
            "averageMaximumAdverseExcursion": _mean(
                tuple(
                    Decimal(
                        str(
                            decision["scoreRankedPortfolio"][
                                "maximumAdverseExcursion"
                            ]
                        )
                    )
                    for decision in decisions
                    if decision["scoreRankedPortfolio"] is not None
                )
            ),
            "averageMaximumFavorableExcursion": _mean(
                tuple(
                    Decimal(
                        str(
                            decision["scoreRankedPortfolio"][
                                "maximumFavorableExcursion"
                            ]
                        )
                    )
                    for decision in decisions
                    if decision["scoreRankedPortfolio"] is not None
                )
            ),
            "nonOverlappingEpisodeCount": len(non_overlapping_returns),
            "nonOverlappingCompoundedMaximumDrawdown": _maximum_drawdown(
                non_overlapping_returns
            ),
        },
        "executableEntryEpisodeCount": sum(
            actionability[state]
            for state in (
                Actionability.ENTRY.value,
                Actionability.LIMITED_ENTRY.value,
            )
        ),
        "actionabilityCounts": dict(sorted(actionability.items())),
        "thesisCounts": dict(sorted(thesis.items())),
        "terminalPopulationCounts": dict(sorted(terminal.items())),
        "benchmarks": benchmark_aggregates,
        "regimeStability": _stability_rows(
            decisions,
            grouping_field="marketRegime",
        ),
        "timeStability": _stability_rows(
            decisions,
            grouping_field="timeBand",
        ),
    }


def run_tactical_v22_tier1_retrospective(
    *,
    repository_root: Path,
    plan_path: Path,
    manifest_path: Path,
    storage_root: Path,
    universe_path: Path,
    classification_path: Path,
    freeze_path: Path,
    controlled_output_root: Path,
    order_notional: Decimal = Decimal("10000"),
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    plan = _verify_canonical_artifact(plan_path)
    if (
        plan.get("evaluationRole") != "DEVELOPMENT_OBSERVED"
        or plan.get("formalGateEligible") is not False
        or plan.get("untouchedHoldout") is not False
    ):
        raise Tier1RetrospectiveError("SEALED_DEVELOPMENT_PLAN_REQUIRED")
    freeze = _verify_canonical_artifact(freeze_path)
    verify_model_freeze_artifact(repository_root, freeze)
    if freeze.get("modelVersion") != MODEL_VERSION:
        raise Tier1RetrospectiveError("TACTICAL_MODEL_FREEZE_VERSION_MISMATCH")

    manifest, series_by_symbol = load_hash_verified_yahoo_cache_v22(
        manifest_path=manifest_path,
        storage_root=storage_root,
    )
    universe = load_closed_test_universe(universe_path)
    assessed_symbols = tuple(
        symbol
        for role in ("PRIMARY", "RESERVE")
        for symbol in universe.members_by_role[role]
    )
    if len(assessed_symbols) != 55:
        raise Tier1RetrospectiveError("EXACT_55_ASSESSED_POPULATION_REQUIRED")
    required_series = set(assessed_symbols) | {"SPY"}
    if required_series - set(series_by_symbol):
        raise Tier1RetrospectiveError("HISTORICAL_PRICE_CACHE_INCOMPLETE")
    sector_by_symbol, sector_mapping_hash = _load_current_sector_map(
        classification_path,
        assessed_symbols,
    )
    members_by_sector: dict[str, list[str]] = defaultdict(list)
    for symbol in assessed_symbols:
        members_by_sector[sector_by_symbol[symbol]].append(symbol)

    spy = series_by_symbol["SPY"]
    sessions = tuple(
        bar.trading_date
        for bar in spy.bars
        if bar.session_complete and bar.volume > 0
    )
    sector_series = {
        sector: _build_sector_proxy(
            sector=sector,
            members=tuple(sorted(members)),
            series_by_symbol=series_by_symbol,
            sessions=sessions,
            mapping_hash=sector_mapping_hash,
        )
        for sector, members in members_by_sector.items()
    }
    diagnostic_cutoff = max(
        series.available_at for series in series_by_symbol.values()
    )
    if diagnostic_cutoff.tzinfo is None:
        diagnostic_cutoff = diagnostic_cutoff.replace(tzinfo=UTC)

    role_by_symbol = {
        symbol: role
        for role, symbols in universe.members_by_role.items()
        for symbol in symbols
    }
    public_id_by_symbol = {
        symbol: str(uuid5(SECURITY_NAMESPACE, f"US:{symbol}"))
        for symbol in universe.symbols
    }
    decisions: list[dict[str, Any]] = []
    for anchor in [*plan["randomAnchors"], *plan["fixedOffsetAnchors"]]:
        decision_date = date.fromisoformat(str(anchor["decision_date"]))
        decision_index = int(anchor["session_index"])
        for horizon in HORIZONS:
            if horizon not in tuple(int(item) for item in anchor["matured_horizons"]):
                continue
            rows: list[dict[str, Any]] = []
            terminal = {
                public_id_by_symbol[symbol]: (
                    "NOT_APPLICABLE"
                    if role_by_symbol[symbol] == "REFERENCE_ONLY"
                    else "EXCLUDED"
                    if role_by_symbol[symbol] == "EXCLUDED"
                    else "MISSING"
                )
                for symbol in universe.symbols
            }
            sector_paths: dict[str, dict[str, Decimal] | None] = {}
            for sector, series in sector_series.items():
                sector_paths[sector] = _path(
                    series,
                    sessions,
                    decision_index=decision_index,
                    horizon=horizon,
                    order_notional=order_notional,
                )
            for symbol in assessed_symbols:
                security = series_by_symbol[symbol]
                sector = sector_by_symbol[symbol]
                security_path = _path(
                    security,
                    sessions,
                    decision_index=decision_index,
                    horizon=horizon,
                    order_notional=order_notional,
                )
                sector_path = sector_paths[sector]
                if security_path is None or sector_path is None:
                    continue
                try:
                    assessment = evaluate_tactical_signal_v22(
                        TacticalContextV22(
                            security_id=public_id_by_symbol[symbol],
                            decision_cutoff=diagnostic_cutoff,
                            as_of_date=decision_date,
                            security=_series_evidence(
                                security,
                                decision_date,
                            ),
                            market_benchmark_id="SPY",
                            market=_series_evidence(spy, decision_date),
                            sector_benchmark_id=(
                                f"CURRENT-SECTOR-PROXY:{sector}"
                            ),
                            sector=_series_evidence(
                                sector_series[sector],
                                decision_date,
                            ),
                            event=EventEvidenceV22(
                                state=EvidenceState.MISSING,
                                risk_level=None,
                                source_hash=None,
                                available_at=None,
                                ingested_at=None,
                            ),
                            sector_mapping_version=(
                                SECTOR_PROXY_POLICY_VERSION
                            ),
                            sector_mapping_hash=sector_mapping_hash,
                        )
                    )
                except ValueError:
                    terminal[public_id_by_symbol[symbol]] = "INVALID"
                    continue
                horizon_result = next(
                    item
                    for item in assessment.horizons
                    if item.trading_days == horizon
                )
                if horizon_result.opportunity_score is None:
                    continue
                momentum = _momentum_12_1(
                    security,
                    sessions,
                    decision_index,
                )
                rows.append(
                    {
                        "publicSecurityId": public_id_by_symbol[symbol],
                        "symbol": symbol,
                        "sector": sector,
                        "score": Decimal(
                            str(horizon_result.opportunity_score)
                        ),
                        "entryValueScore": (
                            Decimal(str(horizon_result.entry_value_score))
                            if horizon_result.entry_value_score is not None
                            else None
                        ),
                        "riskScore": (
                            Decimal(str(horizon_result.risk_score))
                            if horizon_result.risk_score is not None
                            else None
                        ),
                        "selectedThesis": horizon_result.selected_thesis.value,
                        "outlook": horizon_result.outlook.value,
                        "actionability": horizon_result.actionability.value,
                        "missingInputs": horizon_result.missing_inputs,
                        "grossReturn": security_path["grossReturn"],
                        "costRate": security_path["costRate"],
                        "netReturn": security_path["netReturn"],
                        "maximumAdverseExcursion": security_path[
                            "maximumAdverseExcursion"
                        ],
                        "maximumFavorableExcursion": security_path[
                            "maximumFavorableExcursion"
                        ],
                        "sectorBenchmarkNetReturn": sector_path["netReturn"],
                        "sectorBenchmarkGrossReturn": sector_path[
                            "grossReturn"
                        ],
                        "sectorBenchmarkCostRate": sector_path["costRate"],
                        "momentum12Minus1": momentum,
                        "marketRegimeScore": (
                            Decimal(str(assessment.market_regime.score))
                            if assessment.market_regime.score is not None
                            else None
                        ),
                        "inputHash": assessment.input_hash,
                        "maximumFeatureDate": decision_date,
                    }
                )
                terminal[public_id_by_symbol[symbol]] = "ASSESSED"
            row_tuple = tuple(rows)
            selected = _top_quintile(row_tuple, field="score")
            score_ranked_portfolio = _portfolio_metric(selected)
            market_path = _path(
                spy,
                sessions,
                decision_index=decision_index,
                horizon=horizon,
                order_notional=order_notional,
            )
            momentum_candidates = tuple(
                row for row in row_tuple if row["momentum12Minus1"] is not None
            )
            momentum_selected = (
                _top_quintile(momentum_candidates, field="momentum12Minus1")
                if momentum_candidates
                else ()
            )
            matched_sector_rows = tuple(
                {
                    **row,
                    "grossReturn": row["sectorBenchmarkGrossReturn"],
                    "costRate": row["sectorBenchmarkCostRate"],
                    "netReturn": row["sectorBenchmarkNetReturn"],
                    "maximumAdverseExcursion": ZERO,
                    "maximumFavorableExcursion": ZERO,
                }
                for row in selected
            )
            benchmark_rows = {
                BenchmarkKind.SPY.value: _benchmark_row(
                    identifier="SPY",
                    metric=_portfolio_metric(
                        (
                            {
                                "grossReturn": market_path["grossReturn"],
                                "costRate": market_path["costRate"],
                                "netReturn": market_path["netReturn"],
                                "maximumAdverseExcursion": market_path[
                                    "maximumAdverseExcursion"
                                ],
                                "maximumFavorableExcursion": market_path[
                                    "maximumFavorableExcursion"
                                ],
                            },
                        )
                    )
                    if market_path is not None
                    else None,
                    reason="CURRENT_REVISION_EX_POST_TOTAL_RETURN_PRICE",
                ),
                BenchmarkKind.SECTOR.value: _benchmark_row(
                    identifier=(
                        "CURRENT-CLASSIFICATION-MATCHED-SECTOR-PROXY"
                    ),
                    metric=_portfolio_metric(matched_sector_rows),
                    reason=(
                        "CURRENT_CLASSIFICATION_RETROSPECTIVE_NOT_PIT;"
                        "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS"
                    ),
                ),
                BenchmarkKind.EQUAL_WEIGHT.value: _benchmark_row(
                    identifier="CURRENT-UNIVERSE-EQUAL-WEIGHT",
                    metric=_portfolio_metric(row_tuple),
                    reason="CURRENT_UNIVERSE_RETROSPECTIVE_SURVIVORSHIP_BIAS",
                ),
                BenchmarkKind.PURE_MOMENTUM.value: _benchmark_row(
                    identifier="PURE-MOMENTUM-12-1-TOP-QUINTILE",
                    metric=_portfolio_metric(momentum_selected),
                    reason=(
                        "CURRENT_UNIVERSE_RETROSPECTIVE_PRICE_ONLY_SELECTION"
                    ),
                ),
                BenchmarkKind.PURE_VALUE.value: _benchmark_row(
                    identifier="PURE-VALUE",
                    metric=None,
                    reason="HISTORICAL_PIT_VALUE_SCORE_EVIDENCE_MISSING",
                ),
                BenchmarkKind.PURE_QUALITY.value: _benchmark_row(
                    identifier="PURE-QUALITY",
                    metric=None,
                    reason="HISTORICAL_PIT_QUALITY_SCORE_EVIDENCE_MISSING",
                ),
            }
            decisions.append(
                {
                    "sampleId": anchor["sample_id"],
                    "selectionMethod": anchor["selection_method"],
                    "stratum": anchor["stratum"],
                    "decisionDate": decision_date,
                    "decisionSessionIndex": decision_index,
                    "horizonCompletedSessions": horizon,
                    "timeBand": _time_band(anchor),
                    "marketRegime": (
                        "BULL"
                        if rows
                        and rows[0]["marketRegimeScore"] is not None
                        and Decimal(str(rows[0]["marketRegimeScore"]))
                        >= Decimal("60")
                        else "BEAR"
                        if rows
                        and rows[0]["marketRegimeScore"] is not None
                        and Decimal(str(rows[0]["marketRegimeScore"]))
                        <= Decimal("40")
                        else "NEUTRAL"
                    ),
                    "securityRows": row_tuple,
                    "scoreRankedSelection": tuple(
                        row["publicSecurityId"] for row in selected
                    ),
                    "scoreRankedPortfolio": score_ranked_portfolio,
                    "benchmarks": benchmark_rows,
                    "terminalPopulation": terminal,
                }
            )

    source_bindings = {
        "tier1Runner": _binding(
            Path(__file__),
            repository_root=repository_root,
            canonical=False,
        ),
        "sealedSlicePlan": _binding(
            plan_path,
            repository_root=repository_root,
        ),
        "historicalPriceManifest": _binding(
            manifest_path,
            repository_root=repository_root,
        ),
        "tacticalModelFreeze": _binding(
            freeze_path,
            repository_root=repository_root,
        ),
        "closedTestUniverse": _binding(
            universe_path,
            repository_root=repository_root,
            canonical=False,
        ),
        "currentClassificationFixture": _binding(
            classification_path,
            repository_root=repository_root,
            canonical=False,
        ),
    }
    horizon_rows = tuple(
        _aggregate_horizon(
            tuple(
                decision
                for decision in decisions
                if decision["horizonCompletedSessions"] == horizon
            ),
            horizon=horizon,
        )
        for horizon in HORIZONS
    )
    controlled_body = {
        "artifactType": "TACTICAL_V22_TIER1_RETROSPECTIVE_CONTROLLED",
        "schemaVersion": TIER1_CONTROLLED_SCHEMA_VERSION,
        "modelVersion": MODEL_VERSION,
        "evaluationRole": "DEVELOPMENT_OBSERVED",
        "claimCeiling": "DIAGNOSTIC_ONLY",
        "formalGateEligible": False,
        "untouchedHoldout": False,
        "sourceBindings": source_bindings,
        "currentClassificationMappingHash": sector_mapping_hash,
        "sectorProxyPolicyVersion": SECTOR_PROXY_POLICY_VERSION,
        "costPolicy": asdict(_cost_policy()),
        "orderNotional": order_notional,
        "decisions": tuple(decisions),
        "horizons": horizon_rows,
        "execution": {
            "providerNetworkRequests": 0,
            "modelWeightsOrThresholdsChanged": False,
            "futurePriceUsedInFeatureInputs": False,
            "maximumFeatureDateEqualsDecisionDate": True,
            "rawProviderValuesIncluded": False,
            "derivedLicensedMetricsIncluded": True,
            "automaticTradingAuthorized": False,
        },
    }
    controlled = {
        **controlled_body,
        "artifactContentHash": canonical_hash(_json_value(controlled_body)),
    }
    controlled_hash = str(controlled["artifactContentHash"]).removeprefix(
        "sha256:"
    )
    controlled_path = controlled_output_root / f"{controlled_hash}.json"
    controlled_file_hash = write_immutable_json(
        controlled_path,
        _json_value(controlled),
    )
    benchmark_availability = {
        BenchmarkKind.SPY.value: "AVAILABLE_DIAGNOSTIC_ONLY",
        BenchmarkKind.SECTOR.value: "AVAILABLE_DIAGNOSTIC_ONLY_NON_PIT",
        BenchmarkKind.EQUAL_WEIGHT.value: "AVAILABLE_DIAGNOSTIC_ONLY",
        BenchmarkKind.PURE_MOMENTUM.value: "AVAILABLE_DIAGNOSTIC_ONLY",
        BenchmarkKind.PURE_VALUE.value: "MISSING",
        BenchmarkKind.PURE_QUALITY.value: "MISSING",
    }
    git_safe_body = {
        "artifactType": "TACTICAL_V22_TIER1_RETROSPECTIVE_CLOSEOUT",
        "schemaVersion": TIER1_SCHEMA_VERSION,
        "modelVersion": MODEL_VERSION,
        "evaluationRole": "DEVELOPMENT_OBSERVED",
        "claimCeiling": "DIAGNOSTIC_ONLY",
        "formalGateEligible": False,
        "untouchedHoldout": False,
        "terminalStatus": "COMPLETED_WITH_LIMITATIONS",
        "sourceBindings": source_bindings,
        "controlledResult": {
            "storageType": "GITIGNORED_LOCAL",
            "path": _display_path(controlled_path, repository_root),
            "fileSha256": controlled_file_hash,
            "artifactContentHash": controlled["artifactContentHash"],
            "rawProviderValuesIncluded": False,
            "derivedLicensedMetricsIncluded": True,
        },
        "population": {
            "exactUniverseCount": 66,
            "assessedCandidateCount": 55,
            "referenceOnlyCount": 2,
            "excludedCount": 9,
            "mode": "CURRENT_UNIVERSE_RETROSPECTIVE",
            "historicalMembershipClaimed": False,
            "survivorshipBiasPresent": True,
            "classificationPointInTime": False,
        },
        "sliceSummary": {
            "anchorCount": len(
                {
                    str(decision["sampleId"]) for decision in decisions
                }
            ),
            "maturedDecisionHorizonCount": len(decisions),
            "firstDecisionDate": min(
                decision["decisionDate"] for decision in decisions
            ),
            "lastDecisionDate": max(
                decision["decisionDate"] for decision in decisions
            ),
        },
        "benchmarkAvailability": benchmark_availability,
        "horizons": [
            {
                "horizonCompletedSessions": horizon["horizonCompletedSessions"],
                "decisionCount": horizon["decisionCount"],
                "assessedSecurityObservationCount": horizon[
                    "assessedSecurityObservationCount"
                ],
                "executableEntryEpisodeCount": horizon[
                    "executableEntryEpisodeCount"
                ],
                "terminalPopulationCounts": horizon[
                    "terminalPopulationCounts"
                ],
                "actionabilityCounts": horizon["actionabilityCounts"],
                "thesisCounts": horizon["thesisCounts"],
                "benchmarks": {
                    benchmark: {
                        "status": benchmark_availability[benchmark],
                        "metricValuesStoredInControlledResult": True,
                    }
                    for benchmark in sorted(benchmark_availability)
                },
            }
            for horizon in horizon_rows
        ],
        "claimBoundary": {
            "historicalEngineeringSanityEvidenceAllowed": True,
            "formalHistoricalValidationClaimAllowed": False,
            "formalForwardDqvSatisfied": False,
            "statisticalEdgeProven": False,
            "parameterRetuningFromResultsAllowed": False,
            "scoreRankingEvaluatedDespiteEventAbstention": True,
            "statement": (
                "Frozen Tactical v2.2 opportunity scores were replayed with "
                "only price features dated on or before each decision. Missing "
                "historical deterministic-event evidence retained the frozen "
                "WATCH_ONLY actionability ceiling. Results test score-ranking "
                "sanity, not executable recommendations or an untouched holdout."
            ),
        },
        "knownLimitations": (
            "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS",
            "CURRENT_CLASSIFICATION_RETROSPECTIVE_NOT_PIT",
            "CURRENT_REVISION_TOTAL_RETURN_PRICE",
            "HISTORICAL_DETERMINISTIC_EVENT_EVIDENCE_MISSING",
            "HISTORICAL_PIT_VALUE_SCORE_EVIDENCE_MISSING",
            "HISTORICAL_PIT_QUALITY_SCORE_EVIDENCE_MISSING",
            "SEALED_ANCHOR_OUTCOMES_ALREADY_OBSERVABLE",
            "OVERLAPPING_RANDOM_ANCHOR_OUTCOMES_NOT_INDEPENDENT",
        ),
        "execution": {
            "providerNetworkRequests": 0,
            "modelExecuted": True,
            "modelWeightsOrThresholdsChanged": False,
            "futurePriceUsedInFeatureInputs": False,
            "rawProviderValuesIncluded": False,
            "automaticTradingAuthorized": False,
        },
        "rawProviderValuesIncluded": False,
        "derivedLicensedMetricsIncluded": False,
    }
    git_safe = {
        **git_safe_body,
        "artifactContentHash": canonical_hash(_json_value(git_safe_body)),
    }
    return _json_value(controlled), _json_value(git_safe), controlled_path
