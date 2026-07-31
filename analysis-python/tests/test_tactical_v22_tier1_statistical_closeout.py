from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from controlled_data import require_repository_paths

from equity_analysis.historical_validation.slice_diagnostic_v22 import (
    _verify_canonical_artifact,
)
from equity_analysis.historical_validation.tactical_v22_tier1_statistical_closeout import (
    BOOTSTRAP_REPLICATIONS,
    MINIMUM_BLOCKS_FOR_INTERVAL,
    _block_bootstrap_interval,
    _dependency_blocks,
)


def _decision(index: int, value: str) -> dict[str, object]:
    return {
        "decisionSessionIndex": index,
        "sampleId": f"S-{index}",
        "value": value,
    }


def test_dependency_blocks_join_only_overlapping_outcome_windows() -> None:
    rows = (
        _decision(10, "1"),
        _decision(14, "2"),
        _decision(30, "3"),
        _decision(34, "4"),
        _decision(50, "5"),
    )
    blocks = _dependency_blocks(rows, horizon=5)
    assert tuple(len(block) for block in blocks) == (2, 2, 1)


def test_block_interval_is_deterministic_and_dependency_aware() -> None:
    blocks = tuple(
        (_decision(index * 10, str(index)),)
        for index in range(MINIMUM_BLOCKS_FOR_INTERVAL)
    )
    first = _block_bootstrap_interval(
        blocks,
        metric=lambda row: Decimal(str(row["value"])),
        seed=123,
        replications=250,
    )
    second = _block_bootstrap_interval(
        blocks,
        metric=lambda row: Decimal(str(row["value"])),
        seed=123,
        replications=250,
    )
    assert first == second
    assert first["status"] == (
        "AVAILABLE_EXPLORATORY_DEPENDENCY_BLOCK_INTERVAL"
    )
    assert first["independentBlockCount"] == MINIMUM_BLOCKS_FOR_INTERVAL
    assert Decimal(str(first["lower"])) <= Decimal(str(first["upper"]))


def test_block_interval_refuses_too_few_independent_blocks() -> None:
    blocks = tuple(
        (_decision(index * 10, str(index)),)
        for index in range(MINIMUM_BLOCKS_FOR_INTERVAL - 1)
    )
    interval = _block_bootstrap_interval(
        blocks,
        metric=lambda row: Decimal(str(row["value"])),
        seed=123,
        replications=100,
    )
    assert interval["status"] == (
        "INSUFFICIENT_INDEPENDENT_DEPENDENCY_BLOCKS"
    )
    assert interval["lower"] is None
    assert interval["upper"] is None


def test_closeout_artifact_is_canonical_bounded_and_non_executable() -> None:
    root = Path(__file__).resolve().parents[2]
    relative_path = (
        "docs/generated/"
        "tactical-v2-2-tier1-statistical-closeout-2026-07-30.json"
    )
    require_repository_paths(
        root,
        (relative_path,),
        purpose="Tactical v2.2 Tier 1 licensed closeout verification",
    )
    path = root / relative_path
    artifact = _verify_canonical_artifact(path)
    assert artifact["modelVersion"] == "TACTICAL-SIGNAL-v2.2.0"
    assert artifact["overallAssessment"]["status"] == (
        "MIXED_DIAGNOSTIC_EVIDENCE"
    )
    assert artifact["crossCuttingLimitations"]["probabilityCalibration"] == (
        "NOT_APPLICABLE_UNCALIBRATED_ORDINAL_MODEL"
    )
    assert artifact["crossCuttingLimitations"]["entryAndLimitedEntry"] == (
        "NOT_VALIDATED_NO_EXECUTABLE_EPISODES"
    )
    assert artifact["crossCuttingLimitations"]["pureValueBenchmark"] == (
        "MISSING"
    )
    assert artifact["execution"] == {
        "commitPushOrDeploy": False,
        "databaseConnections": 0,
        "modelExecuted": False,
        "modelWeightsOrThresholdsChanged": False,
        "probabilitiesAdded": False,
        "providerNetworkRequests": 0,
        "sourceResultsOverwritten": False,
    }
    assert [row["horizonCompletedSessions"] for row in artifact["horizons"]] == [
        5,
        20,
        60,
    ]
    assert [row["dependencyBlockCount"] for row in artifact["horizons"]] == [
        27,
        20,
        12,
    ]
    assert all(
        row["bootstrap"]["replications"] == BOOTSTRAP_REPLICATIONS
        for row in artifact["horizons"]
    )
    assert all(
        row["sizeStability"]["status"].startswith("MISSING_")
        for row in artifact["horizons"]
    )
