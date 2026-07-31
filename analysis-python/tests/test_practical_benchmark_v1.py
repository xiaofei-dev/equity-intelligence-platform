from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.historical_validation.practical_benchmark_v1 import (
    DecisionState,
    EvidenceTier,
    PracticalBenchmarkError,
    PracticalBenchmarkPolicy,
    PracticalDecisionRow,
    build_methodology_artifact,
    evaluate_practical_benchmarks,
    serialize_practical_report,
)

MODEL = "TACTICAL-SIGNAL-v2.2.0"
START = datetime(2020, 1, 2, 21, tzinfo=UTC)


def _rows(
    *,
    slices: int = 6,
    securities: int = 10,
    include_optional_benchmarks: bool = True,
    include_paths: bool = True,
) -> tuple[PracticalDecisionRow, ...]:
    rows: list[PracticalDecisionRow] = []
    for slice_index in range(slices):
        decision = START + timedelta(days=slice_index * 40)
        spy = Decimal("0.01") + Decimal(slice_index) / Decimal("1000")
        equal_weight = spy + Decimal("0.005")
        for security_index in range(securities):
            forward_return = (
                Decimal(security_index) / Decimal("100")
                + Decimal(slice_index) / Decimal("1000")
            )
            path = (
                forward_return / Decimal("4"),
                forward_return / Decimal("2"),
                forward_return * Decimal("0.75"),
                forward_return,
            )
            rows.append(
                PracticalDecisionRow(
                    decision_id=f"decision-{slice_index}",
                    decision_time=decision,
                    decision_session_index=slice_index * 20,
                    model_id="TACTICAL",
                    model_version=MODEL,
                    signal_dimension="TACTICAL_RANKING",
                    horizon_sessions=20,
                    eligible_universe_count=securities,
                    security_id=f"security-{security_index}",
                    symbol=f"S{security_index}",
                    state=DecisionState.ASSESSED,
                    score=Decimal(security_index),
                    security_forward_return=forward_return,
                    spy_forward_return=spy,
                    equal_weight_forward_return=(
                        equal_weight if include_optional_benchmarks else None
                    ),
                    sector_forward_return=(
                        spy + Decimal("0.002")
                        if include_optional_benchmarks
                        else None
                    ),
                    sector="TECH" if security_index % 2 == 0 else "INDUSTRIALS",
                    size_band="LARGE" if security_index < 5 else "MID",
                    regime="UP" if slice_index % 2 == 0 else "DOWN",
                    cumulative_path_returns=path if include_paths else (),
                    outcome_available_at=decision + timedelta(days=30),
                )
            )
    return tuple(rows)


def _policy(**overrides: object) -> PracticalBenchmarkPolicy:
    values: dict[str, object] = {
        "model_id": "TACTICAL",
        "model_version": MODEL,
        "evidence_tier": EvidenceTier.CURRENT_UNIVERSE_NON_PIT,
        "signal_dimension": "TACTICAL_RANKING",
        "target_securities_per_slice": 100,
        "minimum_assessed_per_slice": 5,
        "minimum_slice_coverage": Decimal("0.50"),
        "bootstrap_replications": 200,
    }
    values.update(overrides)
    return PracticalBenchmarkPolicy(**values)  # type: ignore[arg-type]


def test_favorable_monotonic_model_beats_spy_and_bottom_after_cost() -> None:
    report = evaluate_practical_benchmarks(_rows(), _policy())

    aggregate = report["aggregateMetrics"][0]
    assert aggregate["assessedSliceCount"] == 6
    assert aggregate["medianRankInformationCoefficient"] == Decimal("1.00000000")
    assert aggregate["meanTopMinusBottomNetSpread"] > Decimal("0")
    assert aggregate["positiveTopVsSpyDateRate"] == Decimal("1.00000000")
    top_spy = aggregate["portfolios"]["TOP"]["SPY"]
    assert top_spy["meanExcessReturn"] > Decimal("0")
    assert top_spy["hitRate"] == Decimal("1.00000000")
    assert top_spy["meanTurnover"] < Decimal("0.20")
    assert top_spy["exploratoryInterval"]["status"] == (
        "AVAILABLE_EXPLORATORY_BLOCK_BOOTSTRAP"
    )


def test_costs_are_turnover_based_and_initial_portfolio_pays_full_cost() -> None:
    report = evaluate_practical_benchmarks(_rows(slices=2), _policy())
    first, second = report["sliceMetrics"]

    assert first["portfolios"]["TOP"]["turnover"] == Decimal("1")
    assert first["portfolios"]["TOP"]["cost"] == Decimal("0.00400000")
    assert second["portfolios"]["TOP"]["turnover"] == Decimal("0E-8")
    assert second["portfolios"]["TOP"]["cost"] == Decimal("0E-8")


def test_optional_benchmarks_remain_missing_without_blocking_spy() -> None:
    report = evaluate_practical_benchmarks(
        _rows(include_optional_benchmarks=False),
        _policy(),
    )

    first = report["sliceMetrics"][0]
    aggregate = report["aggregateMetrics"][0]
    assert first["benchmarkAvailability"]["SPY"] == "AVAILABLE"
    assert first["benchmarkAvailability"]["EQUAL_WEIGHT"] == "MISSING"
    assert first["benchmarkAvailability"]["SECTOR"] == "MISSING"
    assert aggregate["portfolios"]["TOP"]["SPY"]["status"] == "AVAILABLE"
    assert aggregate["portfolios"]["TOP"]["EQUAL_WEIGHT"]["status"] == (
        "MISSING_BENCHMARK"
    )


def test_path_metrics_include_drawdown_mae_mfe_and_volatility() -> None:
    rows = list(_rows(slices=1))
    top = rows[-1]
    rows[-1] = PracticalDecisionRow(
        **{
            **top.__dict__,
            "security_forward_return": Decimal("0.08"),
            "cumulative_path_returns": (
                Decimal("0.05"),
                Decimal("-0.10"),
                Decimal("0.02"),
                Decimal("0.08"),
            ),
        }
    )
    report = evaluate_practical_benchmarks(tuple(rows), _policy())
    risk = report["sliceMetrics"][0]["portfolios"]["TOP"]["pathRisk"]

    assert risk["status"] == "AVAILABLE"
    assert risk["maximumDrawdown"] < ZERO
    assert risk["maximumAdverseExcursion"] < ZERO
    assert risk["maximumFavorableExcursion"] > ZERO
    assert risk["annualizedRealizedVolatility"] > ZERO


ZERO = Decimal("0")


def test_explicit_non_assessed_states_drive_coverage_and_abstention() -> None:
    rows = list(_rows(slices=1))
    for index in range(6, 10):
        original = rows[index]
        rows[index] = PracticalDecisionRow(
            decision_id=original.decision_id,
            decision_time=original.decision_time,
            decision_session_index=original.decision_session_index,
            model_id=original.model_id,
            model_version=original.model_version,
            signal_dimension=original.signal_dimension,
            horizon_sessions=original.horizon_sessions,
            eligible_universe_count=original.eligible_universe_count,
            security_id=original.security_id,
            symbol=original.symbol,
            state=DecisionState.MISSING_INPUT,
            score=None,
            security_forward_return=None,
            spy_forward_return=None,
            sector=original.sector,
            size_band=original.size_band,
            regime=original.regime,
        )
    report = evaluate_practical_benchmarks(tuple(rows), _policy())
    result = report["sliceMetrics"][0]

    assert result["status"] == "ASSESSED"
    assert result["coverage"] == Decimal("0.60000000")
    assert result["abstentionRate"] == Decimal("0.40000000")
    assert result["stateCounts"]["MISSING_INPUT"] == 4


def test_insufficient_coverage_does_not_create_portfolio_metrics() -> None:
    rows = list(_rows(slices=1))
    for index in range(4, 10):
        original = rows[index]
        rows[index] = PracticalDecisionRow(
            decision_id=original.decision_id,
            decision_time=original.decision_time,
            decision_session_index=original.decision_session_index,
            model_id=original.model_id,
            model_version=original.model_version,
            signal_dimension=original.signal_dimension,
            horizon_sessions=original.horizon_sessions,
            eligible_universe_count=original.eligible_universe_count,
            security_id=original.security_id,
            symbol=original.symbol,
            state=DecisionState.ABSTAINED,
            score=None,
            security_forward_return=None,
            spy_forward_return=None,
        )
    report = evaluate_practical_benchmarks(tuple(rows), _policy())

    assert report["sliceMetrics"][0]["status"] == "INSUFFICIENT_SLICE_COVERAGE"
    assert report["sliceMetrics"][0]["portfolios"] is None
    assert report["aggregateMetrics"][0]["assessedSliceCount"] == 0


def test_sector_size_and_regime_stability_are_diagnostic() -> None:
    report = evaluate_practical_benchmarks(_rows(), _policy())
    stability = report["aggregateMetrics"][0]["stability"]

    assert {row["label"] for row in stability["sector"]} == {
        "TECH",
        "INDUSTRIALS",
    }
    assert {row["label"] for row in stability["sizeBand"]} == {"MID"}
    assert {row["label"] for row in stability["regime"]} == {"UP", "DOWN"}


def test_model_identity_and_duplicate_rows_fail_closed() -> None:
    rows = _rows(slices=1)
    with pytest.raises(PracticalBenchmarkError, match="model identity"):
        evaluate_practical_benchmarks(rows, _policy(model_version="OTHER"))
    with pytest.raises(PracticalBenchmarkError, match="duplicate decision row"):
        evaluate_practical_benchmarks(rows + (rows[0],), _policy())


def test_long_horizon_dimensions_must_be_evaluated_separately() -> None:
    rows = tuple(
        PracticalDecisionRow(
            **{
                **row.__dict__,
                "model_id": "LONG_HORIZON",
                "model_version": "LONG-HORIZON-v1.1.0",
                "signal_dimension": "COMPANY_QUALITY",
            }
        )
        for row in _rows(slices=1)
    )
    quality_policy = PracticalBenchmarkPolicy(
        model_id="LONG_HORIZON",
        model_version="LONG-HORIZON-v1.1.0",
        signal_dimension="COMPANY_QUALITY",
        evidence_tier=EvidenceTier.CURRENT_UNIVERSE_NON_PIT,
        target_securities_per_slice=100,
        minimum_assessed_per_slice=5,
        bootstrap_replications=100,
    )
    report = evaluate_practical_benchmarks(rows, quality_policy)
    assert report["signalDimension"] == "COMPANY_QUALITY"

    with pytest.raises(PracticalBenchmarkError, match="signal dimension"):
        evaluate_practical_benchmarks(
            rows,
            PracticalBenchmarkPolicy(
                model_id="LONG_HORIZON",
                model_version="LONG-HORIZON-v1.1.0",
                signal_dimension="EXPECTED_RETURN",
                evidence_tier=EvidenceTier.CURRENT_UNIVERSE_NON_PIT,
                target_securities_per_slice=100,
                minimum_assessed_per_slice=5,
                bootstrap_replications=100,
            ),
        )


def test_lower_score_can_be_preregistered_as_better_for_downside_risk() -> None:
    report = evaluate_practical_benchmarks(
        _rows(slices=1),
        _policy(higher_score_is_better=False),
    )

    assert report["sliceMetrics"][0]["portfolios"]["TOP"]["securityIds"] == [
        "security-0",
        "security-1",
    ]
    assert report["aggregateMetrics"][0]["medianRankInformationCoefficient"] == (
        Decimal("-1.00000000")
    )


def test_lookahead_and_path_mismatch_fail_closed() -> None:
    base = _rows(slices=1)[0]
    with pytest.raises(PracticalBenchmarkError, match="after decision"):
        PracticalDecisionRow(
            **{**base.__dict__, "outcome_available_at": base.decision_time}
        )
    with pytest.raises(PracticalBenchmarkError, match="terminal return"):
        PracticalDecisionRow(
            **{**base.__dict__, "cumulative_path_returns": (Decimal("0.99"),)}
        )


def test_methodology_artifact_and_report_are_canonical_and_value_free() -> None:
    methodology = build_methodology_artifact()
    assert methodology["supportedModels"][0]["frozenVersion"] == MODEL
    assert "perfect accuracy" in methodology["acceptanceSemantics"]["notRequired"]
    report = evaluate_practical_benchmarks(_rows(slices=1), _policy())
    encoded = serialize_practical_report(report)
    decoded = json.loads(encoded)
    assert decoded["artifactContentHash"] == report["artifactContentHash"]
    assert decoded["modelOutputsRetuned"] is False
    assert decoded["calibratedProbabilityClaimed"] is False
    assert decoded["statisticalUnit"]["dateWeighted"] is True
    assert decoded["statisticalUnit"]["securityRowsTreatedAsIndependentEvidence"] is False
    repository_root = Path(__file__).resolve().parents[2]
    persisted = json.loads(
        (
            repository_root
            / "docs"
            / "generated"
            / "practical-tier1-benchmark-evaluation-policy-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert persisted == methodology


def test_current_universe_non_pit_limitations_are_explicit() -> None:
    report = evaluate_practical_benchmarks(_rows(slices=1), _policy())
    limitations = " ".join(report["limitations"])

    assert "survivorship bias" in limitations
    assert "look-ahead and revision bias" in limitations
    assert "untouched holdout" in limitations
