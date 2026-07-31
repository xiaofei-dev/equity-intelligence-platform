from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from equity_analysis.forward_validation.maturity_outcome_engine_v22 import (
    CompletedSessionBar,
    EvidenceState,
    MaturityPathInput,
    build_evidence_root_hashes,
    build_preflight,
    evaluate_maturity,
)
from equity_analysis.forward_validation.outcomes_v21 import (
    MaturityScheduleV21,
)
from equity_analysis.forward_validation.outcomes_v211 import (
    ForwardDqvEnrollmentV211,
)
from equity_analysis.forward_validation.prospective_protocol_v2 import (
    HorizonEvaluationRole,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

HASH = "sha256:" + "a" * 64


def _enrollment(*, security_count: int = 1) -> ForwardDqvEnrollmentV211:
    entry = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
    roles = (
        HorizonEvaluationRole.TACTICAL_FORMAL,
        HorizonEvaluationRole.TACTICAL_FORMAL,
        HorizonEvaluationRole.TACTICAL_FORMAL,
        HorizonEvaluationRole.LONG_HORIZON_INTERIM_DIAGNOSTIC,
        HorizonEvaluationRole.LONG_HORIZON_FORMAL,
    )
    schedules = []
    for horizon, role in zip((5, 20, 60, 126, 252), roles, strict=True):
        payload = {
            "completedSessions": horizon,
            "evaluationRole": role.value,
            "formalGateEligible": horizon != 126,
            "maturesAtCompletedSession": entry + timedelta(days=horizon, hours=6, minutes=30),
        }
        schedules.append(
            MaturityScheduleV21.model_validate({**payload, "scheduleContentHash": _hash(payload)})
        )
    payload = {
        "schemaVersion": "FORWARD-DQV-ENROLLMENT-v2.1.1",
        "enrollmentId": "00000000-0000-0000-0000-000000000001",
        "idempotencyKey": "fixture",
        "canonicalRequestHash": HASH,
        "preregistrationContentHash": HASH,
        "decisionManifestContentHash": HASH,
        "decisionControlledArtifactHash": HASH,
        "decisionControlledArtifactReference": "storage/fixture",
        "decisionDataSnapshotId": "00000000-0000-0000-0000-000000000002",
        "decisionAsOf": datetime(2026, 1, 1, 22, tzinfo=UTC),
        "effectiveAtCompletedSessionOpen": entry,
        "universeVersion": "fixture",
        "frozenPopulationHash": HASH,
        "modelFreezeHashes": {"tactical": HASH},
        "benchmarkContractVersion": "fixture",
        "benchmarkContractHash": HASH,
        "costPolicyVersion": "fixture",
        "costPolicyHash": HASH,
        "securityCount": security_count,
        "terminalCounts": {"READY": security_count},
        "maturitySchedule": [item.model_dump(mode="json", by_alias=True) for item in schedules],
        "sealedAt": datetime(2026, 1, 2, 13, tzinfo=UTC),
    }
    return ForwardDqvEnrollmentV211.model_validate(
        {**payload, "enrollmentContentHash": _hash(payload)}
    )


def _hash(payload: object) -> str:
    from equity_analysis.analytics_interface.contracts import canonical_hash

    return canonical_hash(payload)


def _path(
    *,
    security: bool,
    kind: BenchmarkKind | None = None,
) -> MaturityPathInput:
    start = datetime(2026, 1, 2, 21, tzinfo=UTC)
    bars = tuple(
        CompletedSessionBar(
            session_close=start + timedelta(days=index + 1),
            adjusted_open=Decimal(100 + index),
            adjusted_high=Decimal(102 + index),
            adjusted_low=Decimal(99 + index),
            adjusted_close=Decimal(101 + index),
            available_at=start + timedelta(days=index + 1, minutes=1),
            source_hash=_hash({"bar": index, "kind": str(kind)}),
            action_adjustment_hash=HASH,
        )
        for index in range(5)
    )
    return MaturityPathInput(
        subject_id="security" if security else kind.value,
        public_security_id=(UUID("00000000-0000-0000-0000-000000000003") if security else None),
        benchmark_kind=None if security else kind,
        state=EvidenceState.READY,
        entry_open=Decimal(100),
        bars=bars,
        order_notional=Decimal(10000),
        average_daily_dollar_volume=Decimal(10000000),
        calendar_evidence_hash=HASH,
        source_manifest_hash=_hash({"subject": "security" if security else kind.value}),
    )


def _inputs() -> tuple[
    tuple[MaturityPathInput, ...],
    tuple[MaturityPathInput, ...],
    dict[str, str],
]:
    securities = (_path(security=True),)
    benchmarks = tuple(_path(security=False, kind=kind) for kind in BenchmarkKind)
    spy = next(item for item in benchmarks if item.benchmark_kind == BenchmarkKind.SPY)
    down_bar = spy.bars[1].model_copy(update={"adjusted_close": Decimal(100)})
    down_spy = spy.model_copy(update={"bars": (spy.bars[0], down_bar, *spy.bars[2:])})
    benchmarks = tuple(
        down_spy if item.benchmark_kind == BenchmarkKind.SPY else item for item in benchmarks
    )
    return (
        securities,
        benchmarks,
        build_evidence_root_hashes((*securities, *benchmarks)),
    )


def test_preflight_is_honestly_blocked_without_enrollment_or_maturity() -> None:
    preflight = build_preflight(enrollment_count=0, matured_count=0)
    assert preflight.status == "BLOCKED"
    assert preflight.blockers == (
        "BLOCKED_NO_ENROLLMENT",
        "NO_MATURED_OUTCOMES",
    )
    assert preflight.artifact["networkRequestsExecuted"] == 0


def test_five_session_fixture_builds_returns_metrics_and_six_benchmarks() -> None:
    enrollment = _enrollment()
    securities, benchmarks, roots = _inputs()
    bundle = evaluate_maturity(
        enrollment=enrollment,
        completed_sessions=5,
        observed_at=datetime(2026, 1, 8, tzinfo=UTC),
        security_paths=securities,
        benchmark_paths=benchmarks,
        **roots,
    )
    assert bundle.outcome_batch.security_outcomes[0].gross_return == Decimal("0.05")
    assert len(bundle.outcome_batch.benchmark_outcomes) == 6
    assert len(bundle.supplemental_path_analytics) == 7
    security_analytics = next(
        item
        for item in bundle.supplemental_path_analytics
        if item.stable_identity.startswith("SECURITY:")
    )
    assert security_analytics.order_notional == Decimal("10000")
    assert security_analytics.average_daily_dollar_volume == Decimal("10000000")
    assert security_analytics.liquidity_participation_rate == Decimal("0.001")
    assert security_analytics.downside_capture == Decimal(0)
    assert security_analytics.downside_capture_state == "VALID"
    assert security_analytics.portfolio_turnover is None
    assert (
        security_analytics.portfolio_turnover_state
        == "NOT_COMPUTABLE_MISSING_PORTFOLIO_DENOMINATOR"
    )


def test_future_maturity_and_wrong_path_length_are_rejected() -> None:
    enrollment = _enrollment()
    securities, benchmarks, roots = _inputs()
    with pytest.raises(ValueError, match="FUTURE_MATURITY_NOT_AVAILABLE"):
        evaluate_maturity(
            enrollment=enrollment,
            completed_sessions=5,
            observed_at=datetime(2026, 1, 3, tzinfo=UTC),
            security_paths=securities,
            benchmark_paths=benchmarks,
            **roots,
        )


def test_path_must_bind_exact_maturity_and_observation_cutoff() -> None:
    enrollment = _enrollment()
    path = _path(security=True)
    bad_bar = path.bars[-1].model_copy(
        update={"session_close": path.bars[-1].session_close + timedelta(days=1)}
    )
    bad_path = path.model_copy(update={"bars": (*path.bars[:-1], bad_bar)})
    benchmarks = tuple(_path(security=False, kind=kind) for kind in BenchmarkKind)
    roots = build_evidence_root_hashes((bad_path, *benchmarks))
    with pytest.raises(ValueError, match="PATH_MATURITY_SESSION_MISMATCH"):
        evaluate_maturity(
            enrollment=enrollment,
            completed_sessions=5,
            observed_at=datetime(2026, 1, 8, tzinfo=UTC),
            security_paths=(bad_path,),
            benchmark_paths=benchmarks,
            **roots,
        )


def test_tactical_and_long_payloads_cannot_cross_tracks() -> None:
    enrollment = _enrollment()
    securities, benchmarks, roots = _inputs()
    with pytest.raises(ValueError, match="Tactical outcomes cannot carry"):
        evaluate_maturity(
            enrollment=enrollment,
            completed_sessions=5,
            observed_at=datetime(2026, 1, 8, tzinfo=UTC),
            security_paths=securities,
            benchmark_paths=benchmarks,
            **roots,
            long_expected_return_range=(Decimal("0.1"), Decimal("0.2")),
        )


def test_naive_observed_at_and_unbound_evidence_roots_are_rejected() -> None:
    enrollment = _enrollment()
    securities, benchmarks, roots = _inputs()
    with pytest.raises(ValueError, match="OBSERVED_AT_TIMEZONE_REQUIRED"):
        evaluate_maturity(
            enrollment=enrollment,
            completed_sessions=5,
            observed_at=datetime(2026, 1, 8),
            security_paths=securities,
            benchmark_paths=benchmarks,
            **roots,
        )

    roots["price_evidence_hash"] = HASH
    with pytest.raises(ValueError, match="BATCH_EVIDENCE_ROOT_BINDING_MISMATCH"):
        evaluate_maturity(
            enrollment=enrollment,
            completed_sessions=5,
            observed_at=datetime(2026, 1, 8, tzinfo=UTC),
            security_paths=securities,
            benchmark_paths=benchmarks,
            **roots,
        )


def test_security_population_requires_exact_unique_security_identities() -> None:
    security = _path(security=True)
    benchmarks = tuple(_path(security=False, kind=kind) for kind in BenchmarkKind)

    roots = build_evidence_root_hashes((security, *benchmarks))
    with pytest.raises(ValueError, match="FROZEN_SECURITY_POPULATION_COUNT_MISMATCH"):
        evaluate_maturity(
            enrollment=_enrollment(security_count=2),
            completed_sessions=5,
            observed_at=datetime(2026, 1, 8, tzinfo=UTC),
            security_paths=(security,),
            benchmark_paths=benchmarks,
            **roots,
        )

    benchmark_identity = benchmarks[0]
    with pytest.raises(ValueError, match="SECURITY_PATH_IDENTITY_REQUIRED"):
        evaluate_maturity(
            enrollment=_enrollment(),
            completed_sessions=5,
            observed_at=datetime(2026, 1, 8, tzinfo=UTC),
            security_paths=(benchmark_identity,),
            benchmark_paths=benchmarks,
            source_manifest_hash=HASH,
            calendar_evidence_hash=HASH,
            action_evidence_hash=HASH,
            price_evidence_hash=HASH,
        )

    duplicate = security.model_copy(update={"subject_id": "renamed-duplicate"})
    with pytest.raises(ValueError, match="DUPLICATE_PUBLIC_SECURITY_ID"):
        evaluate_maturity(
            enrollment=_enrollment(security_count=2),
            completed_sessions=5,
            observed_at=datetime(2026, 1, 8, tzinfo=UTC),
            security_paths=(security, duplicate),
            benchmark_paths=benchmarks,
            source_manifest_hash=HASH,
            calendar_evidence_hash=HASH,
            action_evidence_hash=HASH,
            price_evidence_hash=HASH,
        )


def test_evidence_roots_use_typed_stable_identity_and_ignore_order_and_display_name() -> None:
    security = _path(security=True)
    benchmarks = tuple(_path(security=False, kind=kind) for kind in BenchmarkKind)
    paths = (security, *benchmarks)
    expected = build_evidence_root_hashes(paths)

    renamed_with_subject_collision = tuple(
        item.model_copy(update={"subject_id": "shared-display-name"}) for item in paths
    )
    assert build_evidence_root_hashes(tuple(reversed(paths))) == expected
    assert build_evidence_root_hashes(renamed_with_subject_collision) == expected
    with pytest.raises(ValueError, match="DUPLICATE_TYPED_PATH_IDENTITY"):
        build_evidence_root_hashes(
            (security, security.model_copy(update={"subject_id": "another-display-name"}))
        )


def test_downside_capture_is_not_applicable_without_spy_down_sessions() -> None:
    enrollment = _enrollment()
    security = _path(security=True)
    benchmarks = tuple(_path(security=False, kind=kind) for kind in BenchmarkKind)
    roots = build_evidence_root_hashes((security, *benchmarks))
    bundle = evaluate_maturity(
        enrollment=enrollment,
        completed_sessions=5,
        observed_at=datetime(2026, 1, 8, tzinfo=UTC),
        security_paths=(security,),
        benchmark_paths=benchmarks,
        **roots,
    )

    aggregate = next(
        item
        for item in bundle.outcome_batch.path_metrics
        if item.metric_code.value == "DOWNSIDE_CAPTURE"
    )
    security_analytics = next(
        item
        for item in bundle.supplemental_path_analytics
        if item.stable_identity.startswith("SECURITY:")
    )
    assert aggregate.state.value == "NOT_APPLICABLE"
    assert aggregate.metric_value is None
    assert aggregate.reason_codes == ("DOWNSIDE_CAPTURE_NO_SPY_NEGATIVE_SESSIONS",)
    assert security_analytics.downside_capture is None
    assert security_analytics.downside_capture_state == "NOT_APPLICABLE_NO_SPY_NEGATIVE_SESSIONS"
