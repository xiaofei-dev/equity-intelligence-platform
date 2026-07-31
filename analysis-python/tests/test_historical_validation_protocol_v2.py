from __future__ import annotations

from decimal import Decimal

import pytest

from equity_analysis.historical_validation.governance_v1 import (
    OutcomeDependence,
)
from equity_analysis.historical_validation.protocol_v2 import (
    REQUIRED_METRICS,
    AvailabilityStatus,
    BenchmarkEvidence,
    BenchmarkKind,
    LiquiditySensitiveCostPolicy,
    ModelTrack,
    PopulationTerminalState,
    ResamplingMethod,
    ValidationProtocolV2,
    protocol_hash,
    validate_benchmarks,
    validate_formal_resampling,
    validate_population_snapshot,
    validate_protocol,
)

HASH = "A" * 64


def _benchmarks(
    *,
    missing: BenchmarkKind | None = None,
) -> tuple[BenchmarkEvidence, ...]:
    return tuple(
        BenchmarkEvidence(
            kind=kind,
            identifier=f"{kind.value}-v1",
            availability_status=(
                AvailabilityStatus.MISSING
                if kind == missing
                else AvailabilityStatus.AVAILABLE
            ),
            evidence_hash=None if kind == missing else HASH,
            reason="No dated sector mapping" if kind == missing else None,
        )
        for kind in BenchmarkKind
    )


def _costs() -> LiquiditySensitiveCostPolicy:
    return LiquiditySensitiveCostPolicy(
        fixed_round_trip_bps=Decimal("20"),
        base_slippage_one_way_bps=Decimal("5"),
        impact_bps_at_full_participation=Decimal("100"),
        maximum_impact_one_way_bps=Decimal("50"),
    )


def _protocol(**overrides) -> ValidationProtocolV2:
    values = {
        "model_track": ModelTrack.TACTICAL,
        "model_version": "TACTICAL-SIGNAL-v2.2.0",
        "horizons_trading_sessions": (5, 20, 60),
        "purge_sessions": 60,
        "embargo_sessions": 60,
        "outcome_dependence": OutcomeDependence.PURGED_BLOCK,
        "resampling_method": ResamplingMethod.BLOCK_BOOTSTRAP,
        "benchmarks": _benchmarks(),
        "cost_policy": _costs(),
        "required_metrics": REQUIRED_METRICS,
    }
    values.update(overrides)
    return ValidationProtocolV2(**values)


def test_protocol_hash_is_deterministic_and_binds_costs() -> None:
    first = protocol_hash(_protocol())
    assert first == protocol_hash(_protocol())
    assert first != protocol_hash(
        _protocol(
            cost_policy=LiquiditySensitiveCostPolicy(
                fixed_round_trip_bps=Decimal("21"),
                base_slippage_one_way_bps=Decimal("5"),
                impact_bps_at_full_participation=Decimal("100"),
                maximum_impact_one_way_bps=Decimal("50"),
            )
        )
    )


def test_formal_protocol_requires_full_available_benchmark_set() -> None:
    validate_protocol(_protocol(), formal=True)
    with pytest.raises(ValueError, match="not available"):
        validate_protocol(
            _protocol(benchmarks=_benchmarks(missing=BenchmarkKind.SECTOR)),
            formal=True,
        )
    validate_benchmarks(
        _benchmarks(missing=BenchmarkKind.SECTOR),
        formal=False,
    )
    broken_hash = (
        BenchmarkEvidence(
            kind=BenchmarkKind.SPY,
            identifier="SPY-v1",
            availability_status=AvailabilityStatus.AVAILABLE,
            evidence_hash="Z" * 64,
        ),
    )
    with pytest.raises(ValueError, match="SHA-256"):
        validate_benchmarks(broken_hash, formal=False)


def test_protocol_requires_track_horizon_purge_and_embargo() -> None:
    with pytest.raises(ValueError, match="maximum horizon"):
        validate_protocol(
            _protocol(horizons_trading_sessions=(5, 20)),
            formal=False,
        )
    with pytest.raises(ValueError, match="Purge"):
        validate_protocol(_protocol(purge_sessions=59), formal=False)
    with pytest.raises(ValueError, match="Embargo"):
        validate_protocol(_protocol(embargo_sessions=59), formal=False)


def test_formal_dependent_slices_require_block_bootstrap() -> None:
    validate_formal_resampling(
        OutcomeDependence.PURGED_BLOCK,
        ResamplingMethod.BLOCK_BOOTSTRAP,
    )
    with pytest.raises(ValueError, match="block bootstrap"):
        validate_formal_resampling(
            OutcomeDependence.PURGED_BLOCK,
            ResamplingMethod.CLUSTER_BOOTSTRAP,
        )
    with pytest.raises(ValueError, match="IID"):
        validate_formal_resampling(
            OutcomeDependence.NON_OVERLAPPING,
            ResamplingMethod.IID_BOOTSTRAP,
        )
    with pytest.raises(ValueError, match="diagnostic only"):
        validate_formal_resampling(
            OutcomeDependence.OVERLAPPING_DIAGNOSTIC,
            ResamplingMethod.BLOCK_BOOTSTRAP,
        )


def test_cost_policy_combines_fixed_and_liquidity_sensitive_costs() -> None:
    liquid = _costs().round_trip_cost_rate(
        order_notional=Decimal("10000"),
        average_daily_dollar_volume=Decimal("100000000"),
    )
    illiquid = _costs().round_trip_cost_rate(
        order_notional=Decimal("10000"),
        average_daily_dollar_volume=Decimal("100000"),
    )

    assert liquid > Decimal("0.003")
    assert illiquid > liquid
    assert illiquid <= Decimal("0.013")


def test_complete_population_requires_every_terminal_state() -> None:
    validate_population_snapshot(
        ("security-a", "security-b"),
        {
            "security-a": PopulationTerminalState.ASSESSED,
            "security-b": PopulationTerminalState.MISSING,
        },
    )
    with pytest.raises(ValueError, match="missing"):
        validate_population_snapshot(
            ("security-a", "security-b"),
            {"security-a": PopulationTerminalState.ASSESSED},
        )
