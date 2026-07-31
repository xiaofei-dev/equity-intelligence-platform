from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from controlled_data import require_artifact_controlled_references

from equity_analysis.historical_validation.tactical_v22_diagnostic import (
    HistoricalSeriesV22,
)
from equity_analysis.historical_validation.tactical_v22_tier1_retrospective import (
    _bars_through,
    _build_sector_proxy,
    _top_quintile,
)
from equity_analysis.tactical.contracts_v22 import TacticalBarV22


def _series(identifier: str, *, multiplier: float) -> HistoricalSeriesV22:
    start = date(2020, 1, 1)
    bars = tuple(
        TacticalBarV22(
            trading_date=start + timedelta(days=index),
            open_price=(100 + index) * multiplier,
            high_price=(101 + index) * multiplier,
            low_price=(99 + index) * multiplier,
            close_price=(100.5 + index) * multiplier,
            volume=1_000_000 + index,
        )
        for index in range(5)
    )
    return HistoricalSeriesV22(
        identifier=identifier,
        source_hash=(identifier.encode("utf-8").hex() * 64)[:64],
        available_at=datetime(2026, 7, 30, tzinfo=UTC),
        ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
        bars=bars,
    )


def test_sector_proxy_is_deterministic_and_uses_only_same_or_prior_day_prices() -> None:
    sources = {
        "AAA": _series("AAA", multiplier=1.0),
        "BBB": _series("BBB", multiplier=2.0),
    }
    sessions = tuple(bar.trading_date for bar in sources["AAA"].bars)
    first = _build_sector_proxy(
        sector="Technology",
        members=("AAA", "BBB"),
        series_by_symbol=sources,
        sessions=sessions,
        mapping_hash="a" * 64,
    )
    future_changed = {
        **sources,
        "AAA": HistoricalSeriesV22(
            **{
                **sources["AAA"].__dict__,
                "bars": (
                    *sources["AAA"].bars[:-1],
                    TacticalBarV22(
                        trading_date=sources["AAA"].bars[-1].trading_date,
                        open_price=9999,
                        high_price=10000,
                        low_price=9998,
                        close_price=9999,
                        volume=1_000_000,
                    ),
                ),
            }
        ),
    }
    second = _build_sector_proxy(
        sector="Technology",
        members=("AAA", "BBB"),
        series_by_symbol=future_changed,
        sessions=sessions,
        mapping_hash="a" * 64,
    )
    assert first.bars[:-1] == second.bars[:-1]
    assert first.bars[-1] != second.bars[-1]


def test_top_quintile_uses_frozen_score_and_symbol_tie_break() -> None:
    rows = tuple(
        {
            "symbol": symbol,
            "score": Decimal(score),
        }
        for symbol, score in (
            ("A", "10"),
            ("B", "20"),
            ("C", "30"),
            ("D", "40"),
            ("E", "50"),
            ("F", "50"),
        )
    )
    assert tuple(row["symbol"] for row in _top_quintile(rows, field="score")) == (
        "E",
        "F",
    )


def test_feature_slice_excludes_future_prices() -> None:
    series = _series("AAA", multiplier=1.0)
    decision_date = series.bars[2].trading_date
    selected = _bars_through(series, decision_date)
    assert selected
    assert max(bar.trading_date for bar in selected) == decision_date
    assert all(bar.trading_date <= decision_date for bar in selected)


def test_git_safe_tier1_artifact_is_canonical_and_complete() -> None:
    root = Path(__file__).resolve().parents[2]
    path = (
        root
        / "docs/generated/tactical-v2-2-tier1-retrospective-manifest-v1.json"
    )
    if not path.is_file():
        pytest.skip("Git-safe Tactical v2.2 retrospective is unavailable")
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = {
        key: value
        for key, value in payload.items()
        if key != "artifactContentHash"
    }
    from equity_analysis.analytics_interface.contracts import canonical_hash

    assert canonical_hash(body) == payload["artifactContentHash"]
    assert payload["population"]["exactUniverseCount"] == 66
    assert payload["population"]["assessedCandidateCount"] == 55
    assert payload["execution"]["providerNetworkRequests"] == 0
    assert payload["execution"]["futurePriceUsedInFeatureInputs"] is False
    assert payload["derivedLicensedMetricsIncluded"] is False
    runner_binding = payload["sourceBindings"]["tier1Runner"]
    runner_path = root / runner_binding["path"]
    assert hashlib.sha256(runner_path.read_bytes()).hexdigest().upper() == (
        runner_binding["fileSha256"]
    )
    assert {
        row["horizonCompletedSessions"] for row in payload["horizons"]
    } == {5, 20, 60}
    for horizon in payload["horizons"]:
        assert set(horizon["benchmarks"]) == {
            "SPY",
            "SECTOR",
            "EQUAL_WEIGHT",
            "PURE_MOMENTUM",
            "PURE_VALUE",
            "PURE_QUALITY",
        }
        assert horizon["terminalPopulationCounts"]["EXCLUDED"] == 9 * 27
        assert horizon["terminalPopulationCounts"]["NOT_APPLICABLE"] == 2 * 27
        assert "averageTopMinusBottomNetReturn" not in horizon
        assert "averageRankInformationCoefficient" not in horizon
        assert all(
            benchmark["metricValuesStoredInControlledResult"]
            for benchmark in horizon["benchmarks"].values()
        )


def test_controlled_tier1_result_hash_when_available() -> None:
    root = Path(__file__).resolve().parents[2]
    path = (
        root
        / "docs/generated/tactical-v2-2-tier1-retrospective-manifest-v1.json"
    )
    require_artifact_controlled_references(
        root,
        (path.relative_to(root),),
        purpose="Tactical v2.2 Tier 1 controlled result verification",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    controlled = root / payload["controlledResult"]["path"]
    assert hashlib.sha256(controlled.read_bytes()).hexdigest().upper() == (
        payload["controlledResult"]["fileSha256"]
    )
