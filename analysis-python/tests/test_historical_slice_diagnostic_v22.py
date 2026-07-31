from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.historical_validation.slice_diagnostic_v22 import (
    FIXED_OFFSETS_MONTHS,
    HISTORICAL_SLICE_PLAN_V22,
    RANDOM_SEED,
    HistoricalSliceDiagnosticV22Error,
    _aggregate_benchmark_diagnostics,
    build_sealed_slice_plan,
    run_sealed_historical_diagnostic,
    write_immutable_json,
)
from equity_analysis.provider_validation.expansion_gate import file_hash


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _real_paths() -> dict[str, Path]:
    root = _root()
    return {
        "manifest": (
            root
            / "docs/generated/"
            "historical-yahoo-price-cache-20260729T-HISTORICAL-V1-R2-manifest.json"
        ),
        "storage": (
            root / "storage/historical-validation/yahoo-daily-price-cache-v1"
        ),
        "universe": (
            root
            / "analysis-python/resources/universes/"
            "market-intelligence-closed-test-us-v1.json"
        ),
        "tactical": root / "docs/generated/tactical-v2-2-model-freeze.json",
        "long": root / "docs/generated/long-horizon-v1-1-model-freeze.json",
        "protocol": (
            root
            / "docs/generated/"
            "forward-decision-quality-validation-v2-2-protocol-fixture.json"
        ),
    }


def _require_real_cache() -> dict[str, Path]:
    paths = _real_paths()
    if not all(path.exists() for path in paths.values()):
        pytest.skip("Hash-verified local historical evidence is unavailable")
    return paths


def test_real_slice_plan_is_deterministic_and_sealed_before_outcomes() -> None:
    paths = _require_real_cache()

    first = build_sealed_slice_plan(
        manifest_path=paths["manifest"],
        storage_root=paths["storage"],
    )
    second = build_sealed_slice_plan(
        manifest_path=paths["manifest"],
        storage_root=paths["storage"],
    )

    assert first == second
    assert first["schemaVersion"] == HISTORICAL_SLICE_PLAN_V22
    assert first["seed"] == RANDOM_SEED
    assert first["formalGateEligible"] is False
    assert first["untouchedHoldout"] is False
    assert len(first["randomAnchors"]) == 18
    assert len(first["fixedOffsetAnchors"]) == len(FIXED_OFFSETS_MONTHS)
    assert {
        row["stratum"] for row in first["randomAnchors"]
    } == {
        "RECENT_3_TO_9_MONTHS",
        "PRIOR_1_TO_3_YEARS",
        "OLDER_4_TO_10_YEARS",
    }
    assert first["selectionBoundary"] == {
        "dateOnlyFieldsReadBeforeSeal": ["tradingDate"],
        "ohlcvOrOutcomeValuesLoadedBeforeSeal": False,
        "planHashGeneratedBeforeOutcomeLoad": True,
        "selectionAfterReplayAllowed": False,
    }
    body = {
        key: value
        for key, value in first.items()
        if key != "artifactContentHash"
    }
    assert canonical_hash(body) == first["artifactContentHash"]


def test_outcome_loader_requires_persisted_plan(tmp_path: Path) -> None:
    paths = _require_real_cache()

    with pytest.raises(
        HistoricalSliceDiagnosticV22Error,
        match="SEALED_PLAN_MUST_EXIST_BEFORE_OUTCOME_LOAD",
    ):
        run_sealed_historical_diagnostic(
            plan_path=tmp_path / "missing.json",
            manifest_path=paths["manifest"],
            storage_root=paths["storage"],
            universe_path=paths["universe"],
            tactical_freeze_path=paths["tactical"],
            long_horizon_freeze_path=paths["long"],
            protocol_fixture_path=paths["protocol"],
            controlled_output_root=tmp_path / "controlled",
        )


def test_real_diagnostic_runs_benchmarks_but_rejects_model_claims(
    tmp_path: Path,
) -> None:
    paths = _require_real_cache()
    plan_path = tmp_path / "plan.json"
    plan = build_sealed_slice_plan(
        manifest_path=paths["manifest"],
        storage_root=paths["storage"],
    )
    write_immutable_json(plan_path, plan)

    controlled, closeout, controlled_path = (
        run_sealed_historical_diagnostic(
            plan_path=plan_path,
            manifest_path=paths["manifest"],
            storage_root=paths["storage"],
            universe_path=paths["universe"],
            tactical_freeze_path=paths["tactical"],
            long_horizon_freeze_path=paths["long"],
            protocol_fixture_path=paths["protocol"],
            controlled_output_root=tmp_path / "controlled",
        )
    )

    assert controlled_path.is_file()
    assert controlled["execution"][
        "planPersistedAndVerifiedBeforeOutcomeLoad"
    ] is True
    assert controlled["execution"]["providerNetworkRequests"] == 0
    assert controlled["execution"]["modelsExecuted"] is False
    assert len(controlled["slices"]) == 120
    assert len(controlled["modelTrackRows"]) == 120
    for row in controlled["slices"]:
        assert {
            key: value["status"]
            for key, value in row["benchmarks"].items()
        } == {
            "EQUAL_WEIGHT": "AVAILABLE_DIAGNOSTIC_ONLY",
            "PURE_MOMENTUM": "AVAILABLE_DIAGNOSTIC_ONLY",
            "PURE_QUALITY": "MISSING",
            "PURE_VALUE": "MISSING",
            "SECTOR": "MISSING",
            "SPY": "AVAILABLE_DIAGNOSTIC_ONLY",
        }
    assert all(
        row["status"] == "REJECTED_FOR_MODEL_EVALUATION"
        and row["population"]["coverage"] == "0.00000000"
        and row["netReturn"] is None
        for row in controlled["modelTrackRows"]
    )
    assert len(controlled["benchmarkAggregates"]) == 30
    assert closeout["terminalStatus"] == "CLOSED_WITHOUT_MODEL_VALIDATION"
    assert closeout["claimCeiling"] == "DIAGNOSTIC_ONLY"
    assert closeout["formalGateEligible"] is False
    assert closeout["untouchedHoldout"] is False
    assert closeout["sliceSummary"] == {
        "randomAnchorCount": 18,
        "fixedOffsetAnchorCount": 9,
        "totalAnchorCount": 27,
        "maturedAnchorHorizonCount": 120,
        "benchmarkMetricSliceCount": 120,
        "tacticalModelEvaluatedSliceCount": 0,
        "tacticalRejectedSliceCount": 81,
        "longHorizonModelEvaluatedSliceCount": 0,
        "longHorizonRejectedSliceCount": 39,
    }
    serialized_closeout = json.dumps(closeout, sort_keys=True)
    for forbidden in (
        '"gross_return"',
        '"net_return"',
        '"maximum_drawdown"',
        '"value"',
        '"score"',
    ):
        assert forbidden not in serialized_closeout


def test_plan_rejects_source_manifest_drift(tmp_path: Path) -> None:
    paths = _require_real_cache()
    plan_path = tmp_path / "plan.json"
    plan = build_sealed_slice_plan(
        manifest_path=paths["manifest"],
        storage_root=paths["storage"],
    )
    write_immutable_json(plan_path, plan)
    changed_manifest = tmp_path / "manifest.json"
    changed_manifest.write_bytes(paths["manifest"].read_bytes() + b"\n")

    with pytest.raises(
        HistoricalSliceDiagnosticV22Error,
        match="SEALED_PLAN_SOURCE_MANIFEST_DRIFT",
    ):
        run_sealed_historical_diagnostic(
            plan_path=plan_path,
            manifest_path=changed_manifest,
            storage_root=paths["storage"],
            universe_path=paths["universe"],
            tactical_freeze_path=paths["tactical"],
            long_horizon_freeze_path=paths["long"],
            protocol_fixture_path=paths["protocol"],
            controlled_output_root=tmp_path / "controlled",
        )


def test_downside_capture_is_derived_only_for_available_benchmarks() -> None:
    slices = []
    start = date(2020, 1, 1)
    for index, spy_return in enumerate(
        (Decimal("-0.10"), Decimal("-0.05"), Decimal("0.03"))
    ):
        metrics = {
            "gross_return": format(spy_return, "f"),
            "cost_rate": "0.00100000",
            "net_return": format(spy_return, "f"),
            "maximum_adverse_excursion": "-0.10000000",
            "maximum_favorable_excursion": "0.05000000",
            "maximum_drawdown": "-0.08000000",
            "downside_deviation": "0.02000000",
            "holding_count": 1,
            "coverage": "1.00000000",
        }
        benchmark_rows = {}
        for kind in (
            "SPY",
            "EQUAL_WEIGHT",
            "PURE_MOMENTUM",
        ):
            adjusted = dict(metrics)
            if kind == "EQUAL_WEIGHT":
                adjusted["net_return"] = format(spy_return / 2, "f")
            benchmark_rows[kind] = {
                "status": "AVAILABLE_DIAGNOSTIC_ONLY",
                "reason": "fixture",
                "metrics": adjusted,
            }
        for kind in ("SECTOR", "PURE_VALUE", "PURE_QUALITY"):
            benchmark_rows[kind] = {
                "status": "MISSING",
                "reason": "fixture missing",
                "metrics": None,
            }
        slices.append(
            {
                "decisionDate": (start + timedelta(days=index)).isoformat(),
                "horizonCompletedSessions": 5,
                "benchmarks": benchmark_rows,
            }
        )

    aggregates = _aggregate_benchmark_diagnostics(slices)
    equal_weight = next(
        row
        for row in aggregates
        if row["horizonCompletedSessions"] == 5
        and row["benchmark"] == "EQUAL_WEIGHT"
    )
    sector = next(
        row
        for row in aggregates
        if row["horizonCompletedSessions"] == 5
        and row["benchmark"] == "SECTOR"
    )
    assert equal_weight["metrics"]["downside_capture_vs_spy"] == "0.50000000"
    assert equal_weight["metrics"]["downsideObservationCount"] == 2
    assert sector["status"] == "MISSING"
    assert sector["metrics"] is None


def test_committed_artifacts_are_hash_bound_and_git_safe() -> None:
    root = _root()
    plan_path = root / "docs/generated/historical-dqv-v2-2-slice-plan.json"
    closeout_path = (
        root
        / "docs/generated/"
        "historical-dqv-v2-2-slice-diagnostic-closeout.json"
    )
    if not plan_path.is_file() or not closeout_path.is_file():
        pytest.skip("Historical DQV v2.2 artifacts are unavailable")
    for path in (plan_path, closeout_path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        body = {
            key: value
            for key, value in payload.items()
            if key != "artifactContentHash"
        }
        assert canonical_hash(body) == payload["artifactContentHash"]
        assert len(file_hash(path)) == 64
    closeout = json.loads(closeout_path.read_text(encoding="utf-8"))
    assert closeout["execution"]["providerNetworkRequests"] == 0
    assert closeout["execution"]["databaseWrites"] == 0
    assert closeout["execution"]["modelsExecuted"] is False
    assert closeout["execution"]["scoresOrRanksGenerated"] is False
