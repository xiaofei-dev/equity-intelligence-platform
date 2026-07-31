from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from controlled_data import require_artifact_controlled_references

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.historical_validation.practical_tactical_v22 import (
    MODEL_VERSION,
    PracticalTacticalV22Error,
    run_practical_tactical_v22_backtest,
)


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_real_frozen_tactical_scores_run_through_practical_contract(
    tmp_path: Path,
) -> None:
    root = _root()
    retrospective_path = (
        root
        / "docs/generated/"
        "tactical-v2-2-tier1-retrospective-manifest-v1.json"
    )
    require_artifact_controlled_references(
        root,
        (retrospective_path.relative_to(root),),
        purpose="Practical Tactical v2.2 controlled backtest",
    )
    controlled, git_safe, controlled_path = (
        run_practical_tactical_v22_backtest(
            repository_root=root,
            retrospective_path=retrospective_path,
            yahoo_storage_root=root
            / "storage/historical-validation/yahoo-daily-price-cache-v1",
            controlled_output_root=tmp_path,
        )
    )

    assert controlled_path.exists()
    assert controlled["modelVersion"] == MODEL_VERSION
    assert controlled["execution"] == {
        "frozenTacticalSignalsExecutedBySource": True,
        "sourceDecisionSliceCount": 81,
        "sourceSecurityDecisionRowCount": 4452,
        "practicalBenchmarkContractExecuted": True,
        "providerNetworkRequests": 0,
        "modelWeightsOrThresholdsChanged": False,
        "aiUsedInRanking": False,
        "automaticTradingAuthorized": False,
    }
    report = controlled["practicalReport"]
    assert report["sliceCount"] == 81
    assert report["rowCount"] == 4452
    assert report["horizons"] == [5, 20, 60]
    assert all(
        item["assessedSliceCount"] == 27
        for item in report["aggregateMetrics"]
    )
    assert all(
        Decimal(item["meanCoverage"]) >= Decimal("0.98")
        for item in report["aggregateMetrics"]
    )
    assert git_safe["population"]["targetAssessedPerSlice"] == 55
    assert git_safe["population"]["minimumAssessedPerSlice"] == 54
    assert git_safe["population"]["maximumAssessedPerSlice"] == 55
    assert git_safe["claimBoundary"]["realFrozenHistoricalScoresExecuted"]
    assert not git_safe["claimBoundary"]["outcomesOnlyAnalysis"]
    assert git_safe["derivedLicensedMetricsIncluded"] is False
    assert "aggregateMetrics" not in git_safe
    assert (
        git_safe["transactionCostPolicy"]["roundTripBasisPoints"]
        == "40"
    )
    persisted_controlled = json.loads(
        controlled_path.read_text(encoding="utf-8")
    )
    controlled_body = dict(persisted_controlled)
    controlled_hash = controlled_body.pop("artifactContentHash")
    assert canonical_hash(controlled_body) == controlled_hash
    serialized_git_safe = json.loads(json.dumps(git_safe))
    git_safe_body = dict(serialized_git_safe)
    git_safe_hash = git_safe_body.pop("artifactContentHash")
    assert canonical_hash(git_safe_body) == git_safe_hash


def test_source_retrospective_hash_drift_fails_closed(
    tmp_path: Path,
) -> None:
    root = _root()
    source = json.loads(
        (
            root
            / "docs/generated/"
            "tactical-v2-2-tier1-retrospective-manifest-v1.json"
        ).read_text(encoding="utf-8")
    )
    source["claimCeiling"] = "FORMAL_VALIDATION"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(
        PracticalTacticalV22Error,
        match="Artifact content hash mismatch",
    ):
        run_practical_tactical_v22_backtest(
            repository_root=root,
            retrospective_path=tampered,
            yahoo_storage_root=root
            / "storage/historical-validation/yahoo-daily-price-cache-v1",
            controlled_output_root=tmp_path / "controlled",
        )
