from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from equity_analysis.historical_validation.governance_v1 import (
    OutcomeDependence,
    validate_complete_population,
    validate_formal_outcome_dependence,
)

HISTORICAL_VALIDATION_PROTOCOL_V2 = (
    "HISTORICAL-VALIDATION-PROTOCOL-v2.0.0"
)
_SHA256_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")


class ModelTrack(StrEnum):
    TACTICAL = "TACTICAL"
    LONG_HORIZON = "LONG_HORIZON"


class BenchmarkKind(StrEnum):
    SPY = "SPY"
    SECTOR = "SECTOR"
    EQUAL_WEIGHT = "EQUAL_WEIGHT"
    PURE_MOMENTUM = "PURE_MOMENTUM"
    PURE_VALUE = "PURE_VALUE"
    PURE_QUALITY = "PURE_QUALITY"


class AvailabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PopulationTerminalState(StrEnum):
    ASSESSED = "ASSESSED"
    MISSING = "MISSING"
    INVALID = "INVALID"
    STALE = "STALE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SPECIALIZED_MODEL_REQUIRED = "SPECIALIZED_MODEL_REQUIRED"
    EXCLUDED = "EXCLUDED"


class ResamplingMethod(StrEnum):
    NONE = "NONE"
    BLOCK_BOOTSTRAP = "BLOCK_BOOTSTRAP"
    CLUSTER_BOOTSTRAP = "CLUSTER_BOOTSTRAP"
    IID_BOOTSTRAP = "IID_BOOTSTRAP"


class ValidationMetric(StrEnum):
    RANK_INFORMATION_COEFFICIENT = "RANK_INFORMATION_COEFFICIENT"
    TOP_MINUS_BOTTOM = "TOP_MINUS_BOTTOM"
    TOP_VERSUS_BENCHMARK = "TOP_VERSUS_BENCHMARK"
    MAXIMUM_DRAWDOWN = "MAXIMUM_DRAWDOWN"
    DOWNSIDE_CAPTURE = "DOWNSIDE_CAPTURE"
    TURNOVER = "TURNOVER"
    COVERAGE = "COVERAGE"
    MISSING_COUNT = "MISSING_COUNT"
    EXCLUDED_COUNT = "EXCLUDED_COUNT"


REQUIRED_FORMAL_BENCHMARKS = tuple(BenchmarkKind)
REQUIRED_METRICS = tuple(ValidationMetric)
TRACK_MAXIMUM_HORIZON = {
    ModelTrack.TACTICAL: 60,
    ModelTrack.LONG_HORIZON: 252,
}


@dataclass(frozen=True)
class BenchmarkEvidence:
    kind: BenchmarkKind
    identifier: str
    availability_status: AvailabilityStatus
    evidence_hash: str | None
    reason: str | None = None


@dataclass(frozen=True)
class LiquiditySensitiveCostPolicy:
    fixed_round_trip_bps: Decimal
    base_slippage_one_way_bps: Decimal
    impact_bps_at_full_participation: Decimal
    maximum_impact_one_way_bps: Decimal
    version: str = "LIQUIDITY-SENSITIVE-COST-v1.0.0"

    def round_trip_cost_rate(
        self,
        *,
        order_notional: Decimal,
        average_daily_dollar_volume: Decimal,
    ) -> Decimal:
        _validate_cost_policy(self)
        if order_notional <= 0:
            raise ValueError("Order notional must be positive")
        if average_daily_dollar_volume <= 0:
            raise ValueError("Average daily dollar volume must be positive")
        participation = order_notional / average_daily_dollar_volume
        impact = min(
            self.maximum_impact_one_way_bps,
            self.impact_bps_at_full_participation * participation.sqrt(),
        )
        total_bps = (
            self.fixed_round_trip_bps
            + Decimal(2) * (self.base_slippage_one_way_bps + impact)
        )
        return total_bps / Decimal(10_000)


@dataclass(frozen=True)
class ValidationProtocolV2:
    model_track: ModelTrack
    model_version: str
    horizons_trading_sessions: tuple[int, ...]
    purge_sessions: int
    embargo_sessions: int
    outcome_dependence: OutcomeDependence
    resampling_method: ResamplingMethod
    benchmarks: tuple[BenchmarkEvidence, ...]
    cost_policy: LiquiditySensitiveCostPolicy
    required_metrics: tuple[ValidationMetric, ...] = REQUIRED_METRICS
    complete_population_required: bool = True
    version: str = HISTORICAL_VALIDATION_PROTOCOL_V2

    @property
    def maximum_horizon_sessions(self) -> int:
        return max(self.horizons_trading_sessions)


def _canonical_payload(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): _canonical_payload(item)
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
        }
    if isinstance(value, tuple | list):
        return [_canonical_payload(item) for item in value]
    return value


def canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        _canonical_payload(payload),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def protocol_payload(protocol: ValidationProtocolV2) -> dict[str, Any]:
    validate_protocol(protocol, formal=False)
    return _canonical_payload(asdict(protocol))  # type: ignore[return-value]


def protocol_hash(protocol: ValidationProtocolV2) -> str:
    return canonical_hash(protocol_payload(protocol))


def _validate_cost_policy(policy: LiquiditySensitiveCostPolicy) -> None:
    fields = (
        policy.fixed_round_trip_bps,
        policy.base_slippage_one_way_bps,
        policy.impact_bps_at_full_participation,
        policy.maximum_impact_one_way_bps,
    )
    if any(not value.is_finite() or value < 0 for value in fields):
        raise ValueError("Cost-policy basis points must be finite and non-negative")
    if not policy.version:
        raise ValueError("Cost-policy version is required")


def validate_benchmarks(
    benchmarks: tuple[BenchmarkEvidence, ...],
    *,
    formal: bool,
) -> None:
    kinds = tuple(item.kind for item in benchmarks)
    if len(kinds) != len(set(kinds)):
        raise ValueError("Benchmark kinds must be unique")
    if formal and set(kinds) != set(REQUIRED_FORMAL_BENCHMARKS):
        raise ValueError("Formal validation requires the complete benchmark set")
    for item in benchmarks:
        if not item.identifier.strip():
            raise ValueError(f"Benchmark identifier is required for {item.kind.value}")
        if item.availability_status == AvailabilityStatus.AVAILABLE:
            if (
                item.evidence_hash is None
                or not _SHA256_PATTERN.fullmatch(item.evidence_hash)
            ):
                raise ValueError(
                    f"Available benchmark requires a SHA-256 hash: {item.kind.value}"
                )
        elif formal:
            raise ValueError(
                f"Formal benchmark is not available: {item.kind.value} "
                f"({item.availability_status.value})"
            )
        if (
            item.availability_status != AvailabilityStatus.AVAILABLE
            and not item.reason
        ):
            raise ValueError(
                f"Unavailable benchmark requires a reason: {item.kind.value}"
            )


def validate_formal_resampling(
    outcome_dependence: OutcomeDependence,
    resampling_method: ResamplingMethod,
) -> None:
    validate_formal_outcome_dependence(outcome_dependence)
    if resampling_method == ResamplingMethod.IID_BOOTSTRAP:
        raise ValueError("Ordinary IID bootstrap cannot enter a formal gate")
    if (
        outcome_dependence == OutcomeDependence.PURGED_BLOCK
        and resampling_method != ResamplingMethod.BLOCK_BOOTSTRAP
    ):
        raise ValueError("Dependent purged slices require block bootstrap")


def validate_protocol(
    protocol: ValidationProtocolV2,
    *,
    formal: bool,
) -> None:
    if not protocol.model_version.strip():
        raise ValueError("Model version is required")
    horizons = protocol.horizons_trading_sessions
    if (
        not horizons
        or tuple(sorted(set(horizons))) != horizons
        or any(item <= 0 for item in horizons)
    ):
        raise ValueError("Horizons must be unique, positive, and sorted")
    required_horizon = TRACK_MAXIMUM_HORIZON[protocol.model_track]
    if max(horizons) != required_horizon:
        raise ValueError(
            f"{protocol.model_track.value} maximum horizon must be "
            f"{required_horizon} sessions"
        )
    if protocol.purge_sessions < required_horizon:
        raise ValueError("Purge must cover the maximum horizon")
    if protocol.embargo_sessions < required_horizon:
        raise ValueError("Embargo must cover the maximum horizon")
    if not protocol.complete_population_required:
        raise ValueError("Complete frozen-population snapshots are mandatory")
    if tuple(protocol.required_metrics) != REQUIRED_METRICS:
        raise ValueError("Validation metric contract cannot be weakened")
    _validate_cost_policy(protocol.cost_policy)
    validate_benchmarks(protocol.benchmarks, formal=formal)
    if formal:
        validate_formal_resampling(
            protocol.outcome_dependence,
            protocol.resampling_method,
        )


def validate_population_snapshot(
    frozen_security_ids: tuple[str, ...],
    terminal_states: dict[str, PopulationTerminalState],
) -> None:
    validate_complete_population(
        frozen_security_ids,
        {security_id: state.value for security_id, state in terminal_states.items()},
    )
