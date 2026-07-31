from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from controlled_data import require_repository_paths

from equity_analysis.historical_validation.governance_v1 import (
    ClaimCeiling,
    EvaluationRole,
)
from equity_analysis.historical_validation.protocol_v2 import (
    AvailabilityStatus,
    BenchmarkEvidence,
    BenchmarkKind,
)
from equity_analysis.historical_validation.tactical_v22_diagnostic import (
    DiagnosticSchedule,
    DiagnosticStatus,
    FreezeBinding,
    HistoricalDiagnosticInputsV22,
    HistoricalSeriesV22,
    build_tactical_v22_blocked_terminal_artifact,
    build_tactical_v22_diagnostic_preflight,
    load_hash_verified_yahoo_cache_v22,
    run_tactical_v22_historical_diagnostic,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    file_hash,
)
from equity_analysis.tactical.contracts_v22 import (
    EventEvidenceV22,
    EventRiskLevel,
    EvidenceState,
    TacticalBarV22,
)

HASH_A = "A" * 64
HASH_B = "B" * 64
TACTICAL_FREEZE_CONTENT_HASH = (
    "A596080CD7936A6881A38E759C597934DAE1125EC83026DF6DB0434F6FE31910"
)
TACTICAL_FREEZE_HASH = (
    "D6E3EDB1160856ADE700C37D42A4C9E2CDDA3B88A4080DBC8ED73354B4C5BF99"
)
TACTICAL_FREEZE_FILE_SHA = (
    "5D541315F62990BC5F44A4E421F404D737F6FFCF039E586B18BA362A113DC49F"
)
HISTORICAL_CACHE_MANIFEST_FILE_SHA = (
    "E322AC57C00BB4018AC883A2F0EF3461299D7D97725B0791C75EA01846D08E27"
)
TACTICAL_TERMINAL_ARTIFACT_FILE_SHA = (
    "43FCFCFB4066BDFCF530308C8B04DDC409B6D6E6CFDB4DA0098424A9A207B7A0"
)
TACTICAL_TERMINAL_ARTIFACT_CONTENT_HASH = (
    "E389CB70CEAB19854DB13B22652CC547C4618B12F4E28947DB03297D59632C7A"
)


def _write_freeze(path: Path) -> FreezeBinding:
    payload = {
        "artifactType": "MODEL_FREEZE",
        "schemaVersion": "fixture-v1",
        "modelVersion": "TACTICAL-SIGNAL-v2.2.0",
        "freezeHash": HASH_B,
    }
    payload["artifactContentHash"] = canonical_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    file_sha = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    return FreezeBinding(
        path=path,
        expected_file_sha256=file_sha,
        expected_content_hash=payload["artifactContentHash"],
        expected_freeze_hash=HASH_B,
    )


def _sessions(count: int) -> tuple[date, ...]:
    cursor = date(2023, 1, 3)
    values: list[date] = []
    while len(values) < count:
        if cursor.weekday() < 5:
            values.append(cursor)
        cursor += timedelta(days=1)
    return tuple(values)


def _series(
    identifier: str,
    *,
    daily_return: float,
    sessions: tuple[date, ...],
) -> HistoricalSeriesV22:
    price = 100.0
    bars: list[TacticalBarV22] = []
    for index, trading_date in enumerate(sessions):
        open_price = price
        close_price = price * (1.0 + daily_return + (index % 7 - 3) * 0.00002)
        bars.append(
            TacticalBarV22(
                trading_date=trading_date,
                open_price=open_price,
                high_price=max(open_price, close_price) * 1.003,
                low_price=min(open_price, close_price) * 0.997,
                close_price=close_price,
                volume=2_000_000 + index * 1_000,
            )
        )
        price = close_price
    observed = datetime(2026, 7, 29, 22, tzinfo=UTC)
    return HistoricalSeriesV22(
        identifier=identifier,
        source_hash=hashlib.sha256(identifier.encode()).hexdigest().upper(),
        available_at=observed,
        ingested_at=observed,
        bars=tuple(bars),
    )


def _benchmarks(
    *,
    missing: BenchmarkKind | None = None,
) -> tuple[BenchmarkEvidence, ...]:
    return tuple(
        BenchmarkEvidence(
            kind=kind,
            identifier=f"{kind.value}-fixture-v1",
            availability_status=(
                AvailabilityStatus.MISSING
                if kind == missing
                else AvailabilityStatus.AVAILABLE
            ),
            evidence_hash=None if kind == missing else HASH_A,
            reason="Fixture evidence intentionally missing" if kind == missing else None,
        )
        for kind in BenchmarkKind
    )


def _inputs() -> HistoricalDiagnosticInputsV22:
    sessions = _sessions(560)
    series = {
        "SPY": _series("SPY", daily_return=0.0002, sessions=sessions),
        "XLK": _series("XLK", daily_return=0.0003, sessions=sessions),
        "XLI": _series("XLI", daily_return=0.0001, sessions=sessions),
        "S1": _series("S1", daily_return=0.0010, sessions=sessions),
        "S2": _series("S2", daily_return=0.0007, sessions=sessions),
        "S3": _series("S3", daily_return=-0.0001, sessions=sessions),
        "S4": _series("S4", daily_return=0.0004, sessions=sessions),
    }
    return HistoricalDiagnosticInputsV22(
        frozen_security_ids=("S1", "S2", "S3", "S4"),
        series_by_identifier=series,
        market_benchmark_id="SPY",
        sector_benchmark_by_security={
            "S1": "XLK",
            "S2": "XLK",
            "S3": "XLI",
            "S4": "XLI",
        },
        sector_mapping_version="SECTOR-MAP-fixture-v1",
        sector_mapping_hash=HASH_B,
        diagnostic_cutoff=datetime(2026, 7, 30, 1, tzinfo=UTC),
        order_notional=Decimal("10000"),
    )


def _event_resolver(
    _security_id: str,
    _decision_date: date,
    _cutoff: datetime,
) -> EventEvidenceV22:
    observed = datetime(2026, 7, 29, 22, tzinfo=UTC)
    return EventEvidenceV22(
        state=EvidenceState.VALID,
        risk_level=EventRiskLevel.NONE,
        source_hash=HASH_A,
        available_at=observed,
        ingested_at=observed,
        event_type="POINT_IN_TIME_FIXTURE_EVENT_CALENDAR",
    )


def _score_resolver(
    kind: BenchmarkKind,
    _decision_date: date,
    security_ids: tuple[str, ...],
) -> dict[str, Decimal] | None:
    if kind not in {BenchmarkKind.PURE_VALUE, BenchmarkKind.PURE_QUALITY}:
        return None
    multiplier = Decimal(1 if kind == BenchmarkKind.PURE_VALUE else -1)
    return {
        security_id: multiplier * Decimal(index)
        for index, security_id in enumerate(security_ids, start=1)
    }


def test_missing_freeze_blocks_without_outcome_metrics(tmp_path: Path) -> None:
    report = run_tactical_v22_historical_diagnostic(
        freeze_binding=FreezeBinding(path=tmp_path / "missing-freeze.json"),
        inputs=_inputs(),
        benchmarks=_benchmarks(),
        event_resolver=_event_resolver,
        benchmark_score_resolver=_score_resolver,
    )

    assert report.status == DiagnosticStatus.BLOCKED
    assert report.horizons == ()
    assert "MODEL_FREEZE_ARTIFACT_MISSING" in report.blockers
    assert report.evaluation_role == EvaluationRole.DEVELOPMENT_OBSERVED
    assert report.claim_ceiling == ClaimCeiling.DIAGNOSTIC_ONLY
    assert report.untouched_holdout_available is False
    assert report.network_requests_executed is False


def test_missing_benchmark_is_explicit_and_never_replaced_with_zero(
    tmp_path: Path,
) -> None:
    report = run_tactical_v22_historical_diagnostic(
        freeze_binding=_write_freeze(tmp_path / "freeze.json"),
        inputs=_inputs(),
        benchmarks=_benchmarks(missing=BenchmarkKind.PURE_VALUE),
        event_resolver=_event_resolver,
        benchmark_score_resolver=_score_resolver,
    )

    assert report.status == DiagnosticStatus.BLOCKED
    assert report.horizons == ()
    value = next(
        item
        for item in report.benchmark_evidence
        if item.kind == BenchmarkKind.PURE_VALUE
    )
    assert value.availability_status == AvailabilityStatus.MISSING
    assert value.evidence_hash is None
    assert "BENCHMARK_PURE_VALUE_MISSING" in report.blockers


def test_preflight_invokes_unified_protocol_and_walk_forward_plans(
    tmp_path: Path,
) -> None:
    preflight, plans = build_tactical_v22_diagnostic_preflight(
        freeze_binding=_write_freeze(tmp_path / "freeze.json"),
        inputs=_inputs(),
        benchmarks=_benchmarks(),
        event_resolver=_event_resolver,
        benchmark_score_resolver=_score_resolver,
    )

    assert preflight.status == DiagnosticStatus.READY
    assert set(preflight.protocol_hashes) == {
        DiagnosticSchedule.NON_OVERLAPPING.value,
        DiagnosticSchedule.OVERLAPPING_DIAGNOSTIC.value,
    }
    assert set(plans) == set(DiagnosticSchedule)
    assert all(plan.model_version == "TACTICAL-SIGNAL-v2.2.0" for plan in plans.values())
    assert all(plan.folds for plan in plans.values())


def test_complete_synthetic_diagnostic_reports_both_schedules_and_horizons(
    tmp_path: Path,
) -> None:
    arguments = {
        "freeze_binding": _write_freeze(tmp_path / "freeze.json"),
        "inputs": _inputs(),
        "benchmarks": _benchmarks(),
        "event_resolver": _event_resolver,
        "benchmark_score_resolver": _score_resolver,
        "source_manifest_content_hash": HASH_A,
    }

    first = run_tactical_v22_historical_diagnostic(**arguments)
    second = run_tactical_v22_historical_diagnostic(**arguments)

    assert first == second
    assert first.status == DiagnosticStatus.COMPLETE
    assert first.artifact_content_hash == second.artifact_content_hash
    assert {
        (item.schedule, item.horizon_sessions) for item in first.horizons
    } == {
        (schedule, horizon)
        for schedule in DiagnosticSchedule
        for horizon in (5, 20, 60)
    }
    for item in first.horizons:
        assert item.decision_count > 0
        assert item.coverage == Decimal("1.00000000")
        assert sum(item.terminal_population.values()) == (
            item.decision_count * 4
        )
        assert len(item.benchmarks) == 6
        assert all(
            benchmark.availability_status == AvailabilityStatus.AVAILABLE
            and benchmark.average_net_return is not None
            for benchmark in item.benchmarks
        )
        assert item.total_round_trip_cost_rate >= 0
        assert item.risk_metrics.maximum_drawdown is not None
    assert first.evaluation_role == EvaluationRole.DEVELOPMENT_OBSERVED
    assert first.claim_ceiling == ClaimCeiling.DIAGNOSTIC_ONLY
    assert first.untouched_holdout_available is False
    assert first.parameters_tuned is False


def test_freeze_record_hash_mismatch_blocks_execution(tmp_path: Path) -> None:
    binding = _write_freeze(tmp_path / "freeze.json")
    broken = FreezeBinding(
        path=binding.path,
        expected_file_sha256=binding.expected_file_sha256,
        expected_content_hash=binding.expected_content_hash,
        expected_freeze_hash="C" * 64,
    )

    report = run_tactical_v22_historical_diagnostic(
        freeze_binding=broken,
        inputs=_inputs(),
        benchmarks=_benchmarks(),
        event_resolver=_event_resolver,
        benchmark_score_resolver=_score_resolver,
    )

    assert report.status == DiagnosticStatus.BLOCKED
    assert "MODEL_FREEZE_RECORD_HASH_MISMATCH" in report.blockers


def test_invalid_event_evidence_blocks_before_outcomes(tmp_path: Path) -> None:
    def missing_event(
        _security_id: str,
        _decision_date: date,
        _cutoff: datetime,
    ) -> EventEvidenceV22:
        return EventEvidenceV22(
            state=EvidenceState.MISSING,
            risk_level=None,
            source_hash=None,
            available_at=None,
            ingested_at=None,
        )

    report = run_tactical_v22_historical_diagnostic(
        freeze_binding=_write_freeze(tmp_path / "freeze.json"),
        inputs=_inputs(),
        benchmarks=_benchmarks(),
        event_resolver=missing_event,
        benchmark_score_resolver=_score_resolver,
    )

    assert report.status == DiagnosticStatus.BLOCKED
    assert report.horizons == ()
    assert any(
        item.startswith("HISTORICAL_EVENT_EVIDENCE_NOT_VALID[")
        for item in report.blockers
    )


def test_incomplete_value_population_blocks_before_outcomes(
    tmp_path: Path,
) -> None:
    def incomplete_scores(
        kind: BenchmarkKind,
        decision_date: date,
        security_ids: tuple[str, ...],
    ) -> dict[str, Decimal] | None:
        values = _score_resolver(kind, decision_date, security_ids)
        if kind == BenchmarkKind.PURE_VALUE and values is not None:
            values.pop(security_ids[-1])
        return values

    report = run_tactical_v22_historical_diagnostic(
        freeze_binding=_write_freeze(tmp_path / "freeze.json"),
        inputs=_inputs(),
        benchmarks=_benchmarks(),
        event_resolver=_event_resolver,
        benchmark_score_resolver=incomplete_scores,
    )

    assert report.status == DiagnosticStatus.BLOCKED
    assert report.horizons == ()
    assert any(
        item.startswith("BENCHMARK_SCORE_POPULATION_INCOMPLETE[PURE_VALUE:")
        for item in report.blockers
    )


def test_hash_verified_cache_loader_rejects_modified_payload(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    payload_path = storage / "payloads/S1/payload.json"
    payload_path.parent.mkdir(parents=True)
    payload = {
        "symbol": "S1",
        "availableAt": "2026-07-29T22:00:00+00:00",
        "retrievedAt": "2026-07-29T22:00:00+00:00",
        "bars": [
            {
                "tradingDate": "2026-07-28",
                "tactical": {
                    "open": "10",
                    "high": "11",
                    "low": "9",
                    "close": "10.5",
                    "sessionComplete": True,
                },
                "volume": 1000,
                "adjustmentFactor": "1",
            }
        ],
    }
    payload["contentHash"] = canonical_hash(payload)
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    payload_file_sha = hashlib.sha256(payload_path.read_bytes()).hexdigest().upper()
    manifest = {
        "status": "COMPLETE",
        "completedSecurityCount": 1,
        "records": [
            {
                "symbol": "S1",
                "payloadStorageReference": "payloads/S1/payload.json",
                "payloadFileSha256": payload_file_sha,
                "payloadContentHash": payload["contentHash"],
                "barCount": 1,
            }
        ],
    }
    manifest["artifactContentHash"] = canonical_hash(manifest)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    loaded_manifest, series = load_hash_verified_yahoo_cache_v22(
        manifest_path=manifest_path,
        storage_root=storage,
    )
    assert loaded_manifest["status"] == "COMPLETE"
    assert tuple(series) == ("S1",)

    payload["bars"][0]["volume"] = 999
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="FILE_HASH_MISMATCH"):
        load_hash_verified_yahoo_cache_v22(
            manifest_path=manifest_path,
            storage_root=storage,
        )


def test_current_cache_and_accepted_freeze_produce_blocked_missing_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest_path = (
        root
        / "docs/generated/"
        "historical-yahoo-price-cache-20260729T-HISTORICAL-V1-R2-manifest.json"
    )
    freeze_path = root / "docs/generated/tactical-v2-2-model-freeze.json"
    storage_root = (
        root / "storage/historical-validation/yahoo-daily-price-cache-v1"
    )
    require_repository_paths(
        root,
        (
            manifest_path.relative_to(root),
            freeze_path.relative_to(root),
            storage_root.relative_to(root),
        ),
        purpose="Tactical v2.2 current-cache blocked-contract reconstruction",
    )

    manifest, series = load_hash_verified_yahoo_cache_v22(
        manifest_path=manifest_path,
        storage_root=storage_root,
    )
    securities = tuple(sorted(set(series) - {"SPY"}))
    benchmarks = tuple(
        BenchmarkEvidence(
            kind=kind,
            identifier=f"{kind.value}-current-cache-v1",
            availability_status=(
                AvailabilityStatus.AVAILABLE
                if kind
                in {
                    BenchmarkKind.SPY,
                    BenchmarkKind.EQUAL_WEIGHT,
                    BenchmarkKind.PURE_MOMENTUM,
                }
                else AvailabilityStatus.MISSING
            ),
            evidence_hash=(
                manifest["artifactContentHash"]
                if kind
                in {
                    BenchmarkKind.SPY,
                    BenchmarkKind.EQUAL_WEIGHT,
                    BenchmarkKind.PURE_MOMENTUM,
                }
                else None
            ),
            reason=(
                None
                if kind
                in {
                    BenchmarkKind.SPY,
                    BenchmarkKind.EQUAL_WEIGHT,
                    BenchmarkKind.PURE_MOMENTUM,
                }
                else "Current cache has no required historical benchmark evidence"
            ),
        )
        for kind in BenchmarkKind
    )
    inputs = HistoricalDiagnosticInputsV22(
        frozen_security_ids=securities,
        series_by_identifier=series,
        market_benchmark_id="SPY",
        sector_benchmark_by_security={},
        sector_mapping_version="MISSING",
        sector_mapping_hash=HASH_B,
        diagnostic_cutoff=datetime(2026, 7, 30, 1, tzinfo=UTC),
        order_notional=Decimal("10000"),
    )
    report = run_tactical_v22_historical_diagnostic(
        freeze_binding=FreezeBinding(
            path=freeze_path,
            expected_file_sha256=TACTICAL_FREEZE_FILE_SHA,
            expected_content_hash=TACTICAL_FREEZE_CONTENT_HASH,
            expected_freeze_hash=TACTICAL_FREEZE_HASH,
            required_source_file_sha256s=(
                HISTORICAL_CACHE_MANIFEST_FILE_SHA,
            ),
        ),
        inputs=inputs,
        benchmarks=benchmarks,
        event_resolver=None,
        benchmark_score_resolver=None,
        source_manifest_content_hash=manifest["artifactContentHash"],
    )

    assert report.status == DiagnosticStatus.BLOCKED
    assert report.freeze_content_hash == TACTICAL_FREEZE_CONTENT_HASH
    assert report.horizons == ()
    assert "HISTORICAL_EVENT_EVIDENCE_MISSING" in report.blockers
    assert "BENCHMARK_SECTOR_MISSING" in report.blockers
    assert "BENCHMARK_PURE_VALUE_MISSING" in report.blockers
    assert "BENCHMARK_PURE_QUALITY_MISSING" in report.blockers
    assert any(
        blocker.startswith("SECTOR_MAPPING_MISSING[")
        for blocker in report.blockers
    )


def test_current_cache_builds_complete_66_security_terminal_artifact() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest_path = (
        root
        / "docs/generated/"
        "historical-yahoo-price-cache-20260729T-HISTORICAL-V1-R2-manifest.json"
    )
    freeze_path = root / "docs/generated/tactical-v2-2-model-freeze.json"
    universe_path = (
        root
        / "analysis-python/resources/universes/"
        "market-intelligence-closed-test-us-v1.json"
    )
    storage_root = (
        root / "storage/historical-validation/yahoo-daily-price-cache-v1"
    )
    require_repository_paths(
        root,
        (
            manifest_path.relative_to(root),
            freeze_path.relative_to(root),
            universe_path.relative_to(root),
            storage_root.relative_to(root),
        ),
        purpose="Tactical v2.2 terminal artifact reconstruction",
    )

    artifact = build_tactical_v22_blocked_terminal_artifact(
        repo_root=root,
        diagnostic_at=datetime(2026, 7, 30, 2, 30, tzinfo=UTC),
        freeze_binding=FreezeBinding(
            path=freeze_path,
            expected_file_sha256=TACTICAL_FREEZE_FILE_SHA,
            expected_content_hash=TACTICAL_FREEZE_CONTENT_HASH,
            expected_freeze_hash=TACTICAL_FREEZE_HASH,
            required_source_file_sha256s=(
                HISTORICAL_CACHE_MANIFEST_FILE_SHA,
            ),
        ),
        manifest_path=manifest_path,
        storage_root=storage_root,
        universe_path=universe_path,
    )

    assert artifact["terminalStatus"] == "BLOCKED_BY_DATA"
    assert artifact["evaluationRole"] == "DEVELOPMENT_OBSERVED"
    assert artifact["untouchedHoldout"] is False
    assert artifact["claimCeiling"] == "DIAGNOSTIC_ONLY"
    assert artifact["metrics"] == {
        "horizons": [],
        "outcomesIncluded": False,
        "scoresIncluded": False,
        "returnClaimsIncluded": False,
    }
    assert artifact["execution"] == {
        "networkRequests": 0,
        "tuningPerformed": False,
        "historicalOutcomeEvaluationExecuted": False,
    }
    population = artifact["population"]
    assert population["securityCount"] == 66
    assert len(population["records"]) == 66
    assert len(
        {row["publicSecurityId"] for row in population["records"]}
    ) == 66
    assert population["terminalCounts"] == {
        "ASSESSED": 0,
        "MISSING": 55,
        "INVALID": 0,
        "STALE": 0,
        "NOT_APPLICABLE": 2,
        "SPECIALIZED_MODEL_REQUIRED": 0,
        "EXCLUDED": 9,
    }
    assert artifact["missingEvidence"] == {
        "historicalSectorMapping": "MISSING",
        "historicalEventEvidence": "MISSING",
        "pureValueBenchmark": "MISSING",
        "pureQualityBenchmark": "MISSING",
    }
    unhashed = {
        key: value
        for key, value in artifact.items()
        if key != "artifactContentHash"
    }
    assert canonical_hash(unhashed) == artifact["artifactContentHash"]


def test_committed_terminal_artifact_is_hash_bound_and_git_safe() -> None:
    root = Path(__file__).resolve().parents[2]
    artifact_path = (
        root
        / "docs/generated/"
        "tactical-v2-2-historical-diagnostic-terminal-2026-07-29.json"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    unhashed = {
        key: value
        for key, value in artifact.items()
        if key != "artifactContentHash"
    }

    assert file_hash(artifact_path) == TACTICAL_TERMINAL_ARTIFACT_FILE_SHA
    assert (
        artifact["artifactContentHash"]
        == TACTICAL_TERMINAL_ARTIFACT_CONTENT_HASH
    )
    assert canonical_hash(unhashed) == artifact["artifactContentHash"]
    assert artifact["terminalStatus"] == "BLOCKED_BY_DATA"
    assert artifact["population"]["securityCount"] == 66
    serialized = json.dumps(artifact, sort_keys=True)
    assert '"value"' not in serialized
    assert '"score"' not in serialized
    assert '"return"' not in serialized
