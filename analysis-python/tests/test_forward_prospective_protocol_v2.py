from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import (
    GitSafeDecisionManifest,
    GitSafeDecisionRow,
    ModelTrack,
    PopulationTerminalState,
)
from equity_analysis.forward_validation.decision_snapshot_v2 import (
    load_sealed_model_freeze,
)
from equity_analysis.forward_validation.outcomes_v2 import (
    BenchmarkOutcomeInput,
    BenchmarkOutcomeState,
    ForwardTargetMetricEvidence,
    OperationalCompleteness,
    OutcomeObservationState,
    QualityTarget,
    QualityTerminalStatus,
    SecurityOutcomeInput,
    assess_forward_quality,
    build_outcome_batch,
    build_outcome_v16_audit_event_payload,
    build_quality_v16_audit_event_payload,
    verify_idempotent_outcome_replay,
    write_outcome_bundle,
)
from equity_analysis.forward_validation.prospective_protocol_v2 import (
    EnrollmentStatus,
    HorizonEvaluationRole,
    build_enrollment,
    build_enrollment_v16_audit_event_payload,
    build_preregistration,
    build_preregistration_v16_audit_event_payload,
    verify_idempotent_enrollment_replay,
    verify_preregistration,
    write_enrollment_bundle,
    write_preregistration_artifact,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
PROFILE_ID = UUID("22222222-2222-4222-8222-222222222222")
SNAPSHOT_ID = UUID("33333333-3333-4333-8333-333333333333")
DECISION_AS_OF = datetime(2026, 7, 30, 22, tzinfo=UTC)
REGISTERED_AT = datetime(2026, 7, 30, 1, tzinfo=UTC)


def _freezes():
    paths = {
        ModelTrack.TACTICAL: "docs/generated/tactical-v2-2-model-freeze.json",
        ModelTrack.LONG_HORIZON: "docs/generated/long-horizon-v1-1-model-freeze.json",
    }
    return tuple(
        load_sealed_model_freeze(
            repository_root=REPOSITORY_ROOT,
            artifact_path=REPOSITORY_ROOT / paths[track],
            track=track,
        )
        for track in ModelTrack
    )


def _preregistration():
    return build_preregistration(
        repository_root=REPOSITORY_ROOT,
        registered_at=REGISTERED_AT,
        model_freezes=_freezes(),
    )


def _decision_manifest(*, prospective_ready: bool = True):
    preregistration = _preregistration()
    row = GitSafeDecisionRow(
        public_security_id=SECURITY_ID,
        profile_id=PROFILE_ID,
        symbol="TEST",
        tactical_state=PopulationTerminalState.ASSESSED,
        long_horizon_state=PopulationTerminalState.ASSESSED,
        tactical_input_hash="sha256:" + "1" * 64,
        tactical_result_hash="sha256:" + "2" * 64,
        long_horizon_input_hash="sha256:" + "3" * 64,
        long_horizon_evidence_hash="sha256:" + "4" * 64,
        long_horizon_result_hash="sha256:" + "5" * 64,
    )
    body = {
        "schemaVersion": "FORWARD-DECISION-MANIFEST-v2.0.0",
        "idempotencyKey": "decision:2026-07-30",
        "idempotencyHash": "sha256:" + "6" * 64,
        "dataSnapshotId": str(SNAPSHOT_ID),
        "decisionAsOf": DECISION_AS_OF,
        "universeVersion": "CLOSED-TEST-v1",
        "universeHash": "sha256:" + "7" * 64,
        "profileSetHash": canonical_hash([str(PROFILE_ID)]),
        "frozenPopulationHash": canonical_hash([str(SECURITY_ID)]),
        "modelFreezeHashes": {
            item.track.value: item.model_freeze_binding_hash
            for item in preregistration.model_freezes
        },
        "controlledArtifactHash": "sha256:" + "8" * 64,
        "controlledArtifactReference": (
            "storage/forward-validation/decision-snapshots-v2/"
            + "8" * 64
            + ".json"
        ),
        "prospectiveReady": prospective_ready,
        "blockedReasons": () if prospective_ready else ("TEST_BLOCKER",),
        "securityCount": 1,
        "terminalCounts": {
            "TACTICAL:ASSESSED": 1,
            "LONG_HORIZON:ASSESSED": 1,
        },
        "decisions": (row.model_dump(mode="json", by_alias=True),),
        "rawProviderValuesIncluded": False,
        "deterministicNumericResultsIncluded": False,
        "aiUsedForDeterministicDecisions": False,
    }
    return GitSafeDecisionManifest.model_validate(
        {**body, "manifestContentHash": canonical_hash(body)}
    )


def _maturity_sessions():
    return {
        sessions: DECISION_AS_OF + timedelta(days=sessions + 5)
        for sessions in (5, 20, 60, 126, 252)
    }


def _enrollment(*, manifest=None):
    return build_enrollment(
        preregistration=_preregistration(),
        decision_manifest=manifest or _decision_manifest(),
        idempotency_key="forward-v2:2026-07-30:closed-test-v1",
        enrolled_at=DECISION_AS_OF + timedelta(hours=1),
        effective_at_completed_session_open=DECISION_AS_OF + timedelta(hours=15),
        maturity_sessions=_maturity_sessions(),
    )


def _benchmark_inputs(*, missing: BenchmarkKind | None = None):
    result = []
    for index, kind in enumerate(BenchmarkKind, start=1):
        if kind == missing:
            result.append(
                BenchmarkOutcomeInput(
                    kind=kind,
                    identifier=kind.value,
                    state=BenchmarkOutcomeState.MISSING,
                    reason="TEST_MISSING",
                )
            )
        else:
            result.append(
                BenchmarkOutcomeInput(
                    kind=kind,
                    identifier=kind.value,
                    state=BenchmarkOutcomeState.AVAILABLE,
                    gross_return=Decimal("0.01") + Decimal(index) / Decimal("1000"),
                    order_notional=Decimal("10000"),
                    average_daily_dollar_volume=Decimal("100000000"),
                    price_action_evidence_hash="sha256:" + str(index) * 64,
                )
            )
    return tuple(result)


def _security_inputs(*, state: OutcomeObservationState = OutcomeObservationState.ASSESSED):
    if state == OutcomeObservationState.ASSESSED:
        return (
            SecurityOutcomeInput(
                public_security_id=SECURITY_ID,
                state=state,
                gross_return=Decimal("0.05"),
                order_notional=Decimal("10000"),
                average_daily_dollar_volume=Decimal("100000000"),
                price_action_evidence_hash="sha256:" + "a" * 64,
            ),
        )
    return (
        SecurityOutcomeInput(
            public_security_id=SECURITY_ID,
            state=state,
            reason_codes=("TEST_MISSING",),
        ),
    )


def _outcome_bundle(
    *,
    completed_sessions: int = 5,
    missing_benchmark: BenchmarkKind | None = None,
    state: OutcomeObservationState = OutcomeObservationState.ASSESSED,
):
    enrollment = _enrollment()
    maturity = next(
        item
        for item in enrollment.enrollment.maturity_schedule
        if item.completed_sessions == completed_sessions
    )
    return build_outcome_batch(
        preregistration=_preregistration(),
        enrollment=enrollment.enrollment,
        decision_manifest=_decision_manifest(),
        completed_sessions=completed_sessions,
        observed_at=maturity.matures_at_completed_session,
        benchmark_inputs=_benchmark_inputs(missing=missing_benchmark),
        security_inputs=_security_inputs(state=state),
    )


def _metric(
    target: QualityTarget,
    *,
    outcome_horizon: int = 5,
    eligible: int = 100,
    frozen: int = 100,
    coverage: Decimal = Decimal("1"),
    completed_decision_sessions: int = 20,
    lower: Decimal = Decimal("0.01"),
):
    return ForwardTargetMetricEvidence(
        model_track=(
            ModelTrack.TACTICAL
            if target == QualityTarget.TACTICAL_DECISION_QUALITY
            else ModelTrack.LONG_HORIZON
        ),
        completed_sessions=outcome_horizon,
        target=target,
        eligible_security_decisions=eligible,
        frozen_population_decisions=frozen,
        coverage_ratio=coverage,
        completed_decision_sessions=completed_decision_sessions,
        bootstrap_block_sessions=5,
        benchmark_states={
            item: BenchmarkOutcomeState.AVAILABLE for item in BenchmarkKind
        },
        discrimination_lower_confidence_bound=lower,
        versus_benchmark_lower_confidence_bounds={
            item: Decimal("0.01") for item in BenchmarkKind
        },
        maximum_drawdown=Decimal("-0.10"),
        benchmark_maximum_drawdown=Decimal("-0.20"),
        downside_capture=Decimal("0.80"),
        future_fundamental_observations=100,
        outcome_batch_hashes=("sha256:" + "c" * 64,),
        decision_manifest_hashes=("sha256:" + "d" * 64,),
        matured_through=datetime(2027, 1, 1, tzinfo=UTC),
        metric_evidence_hash="sha256:" + "b" * 64,
    )


def test_preregistration_binds_accepted_freezes_governance_and_protocol() -> None:
    preregistration = _preregistration()
    verify_preregistration(preregistration)

    assert tuple(item.completed_sessions for item in preregistration.horizons) == (
        5,
        20,
        60,
        126,
        252,
    )
    assert preregistration.horizons[3].evaluation_role == (
        HorizonEvaluationRole.LONG_HORIZON_INTERIM_DIAGNOSTIC
    )
    assert preregistration.horizons[3].formal_gate_eligible is False
    assert preregistration.governance.artifact_content_hash == (
        "sha256:27453fce7ef859e0eaadbf4426d0d26c142ee2118edd9cacf9f0462a05031752"
    )
    assert preregistration.ordinary_iid_bootstrap_allowed is False
    assert preregistration.ai_may_affect_deterministic_fields is False


def test_preregistration_hash_tampering_is_rejected() -> None:
    preregistration = _preregistration().model_copy(
        update={"preregistration_content_hash": "sha256:" + "f" * 64}
    )
    with pytest.raises(ValueError, match="canonical hash"):
        verify_preregistration(preregistration)


def test_preregistration_rejects_a_self_consistent_but_unaccepted_freeze() -> None:
    tactical, long_horizon = _freezes()
    forged = tactical.model_copy(
        update={"freeze_record_hash": "sha256:" + "f" * 64}
    )

    with pytest.raises(ValueError, match="not the accepted immutable artifact"):
        build_preregistration(
            repository_root=REPOSITORY_ROOT,
            registered_at=REGISTERED_AT,
            model_freezes=(forged, long_horizon),
        )


def test_complete_prospective_manifest_enrolls_idempotently() -> None:
    first = _enrollment()
    second = _enrollment()

    assert first.enrollment == second.enrollment
    assert (
        verify_idempotent_enrollment_replay(first.enrollment, second.enrollment)
        == EnrollmentStatus.EXACT_REPLAY
    )
    assert first.enrollment.operational_status == "COMPLETE"
    assert first.enrollment.model_quality_status == "NOT_MATURED"
    assert first.enrollment.outcome_observation_executed is False


def test_enrollment_rejects_blocked_snapshot_and_conflicting_replay() -> None:
    with pytest.raises(ValueError, match="prospective-ready"):
        _enrollment(manifest=_decision_manifest(prospective_ready=False))

    existing = _enrollment().enrollment
    candidate = existing.model_copy(
        update={"enrollment_content_hash": "sha256:" + "f" * 64}
    )
    with pytest.raises(ValueError, match="canonical hash"):
        verify_idempotent_enrollment_replay(existing, candidate)


def test_enrollment_requires_natural_future_maturity_sessions() -> None:
    sessions = _maturity_sessions()
    sessions[5] = DECISION_AS_OF
    with pytest.raises(ValidationError, match="follow the sealed decision"):
        build_enrollment(
            preregistration=_preregistration(),
            decision_manifest=_decision_manifest(),
            idempotency_key="bad-maturity",
            enrolled_at=DECISION_AS_OF + timedelta(hours=1),
            effective_at_completed_session_open=DECISION_AS_OF + timedelta(hours=15),
            maturity_sessions=sessions,
        )


def test_outcomes_cannot_run_before_natural_maturity() -> None:
    enrollment = _enrollment().enrollment
    with pytest.raises(ValueError, match="naturally matured"):
        build_outcome_batch(
            preregistration=_preregistration(),
            enrollment=enrollment,
            decision_manifest=_decision_manifest(),
            completed_sessions=5,
            observed_at=DECISION_AS_OF + timedelta(days=1),
            benchmark_inputs=_benchmark_inputs(),
            security_inputs=_security_inputs(),
        )


@pytest.mark.parametrize(
    ("completed_sessions", "role"),
    (
        (5, HorizonEvaluationRole.TACTICAL_FORMAL),
        (20, HorizonEvaluationRole.TACTICAL_FORMAL),
        (60, HorizonEvaluationRole.TACTICAL_FORMAL),
        (126, HorizonEvaluationRole.LONG_HORIZON_INTERIM_DIAGNOSTIC),
        (252, HorizonEvaluationRole.LONG_HORIZON_FORMAL),
    ),
)
def test_all_five_preregistered_horizons_accept_only_their_natural_maturity(
    completed_sessions: int,
    role: HorizonEvaluationRole,
) -> None:
    bundle = _outcome_bundle(completed_sessions=completed_sessions)

    assert bundle.batch.completed_sessions == completed_sessions
    assert bundle.batch.evaluation_role == role


def test_outcome_applies_frozen_costs_and_git_safe_manifest_omits_values() -> None:
    bundle = _outcome_bundle()
    record = bundle.batch.security_outcomes[0]
    payload = json.dumps(
        bundle.manifest.model_dump(mode="json", by_alias=True),
        sort_keys=True,
    )

    assert record.round_trip_cost_rate is not None
    assert record.net_return == record.gross_return - record.round_trip_cost_rate
    assert len(record.net_excess_returns) == 6
    assert bundle.batch.decision_snapshot_mutated is False
    assert bundle.manifest.deterministic_numeric_results_included is False
    for forbidden in ('"grossReturn"', '"netReturn"', '"roundTripCostRate"'):
        assert forbidden not in payload


def test_outcome_requires_complete_population_and_all_benchmark_rows() -> None:
    enrollment = _enrollment().enrollment
    maturity = enrollment.maturity_schedule[0].matures_at_completed_session
    with pytest.raises(ValueError, match="one terminal outcome"):
        build_outcome_batch(
            preregistration=_preregistration(),
            enrollment=enrollment,
            decision_manifest=_decision_manifest(),
            completed_sessions=5,
            observed_at=maturity,
            benchmark_inputs=_benchmark_inputs(),
            security_inputs=(),
        )
    with pytest.raises(ValueError, match="complete frozen benchmark"):
        build_outcome_batch(
            preregistration=_preregistration(),
            enrollment=enrollment,
            decision_manifest=_decision_manifest(),
            completed_sessions=5,
            observed_at=maturity,
            benchmark_inputs=_benchmark_inputs()[:-1],
            security_inputs=_security_inputs(),
        )


def test_missing_evidence_is_explicit_but_operational_completion_is_separate() -> None:
    bundle = _outcome_bundle(
        missing_benchmark=BenchmarkKind.PURE_VALUE,
        state=OutcomeObservationState.MISSING,
    )

    assert bundle.batch.operational_completeness == OperationalCompleteness.COMPLETE
    assert "REQUIRED_BENCHMARK_OUTCOME_UNAVAILABLE" in bundle.batch.evidence_blockers
    assert "SECURITY_OUTCOME_EVIDENCE_INCOMPLETE" in bundle.batch.evidence_blockers
    assert bundle.manifest.terminal_counts == {"MISSING": 1}


def test_outcome_exact_replay_is_accepted_and_conflict_is_rejected() -> None:
    first = _outcome_bundle()
    second = _outcome_bundle()
    verify_idempotent_outcome_replay(first, second)

    changed_batch = second.batch.model_copy(
        update={"outcome_batch_content_hash": "sha256:" + "f" * 64}
    )
    changed = type(second)(
        batch=changed_batch,
        controlled_artifact_hash=second.controlled_artifact_hash,
        controlled_artifact_reference=second.controlled_artifact_reference,
        manifest=second.manifest,
    )
    with pytest.raises(ValueError, match="canonical hash"):
        verify_idempotent_outcome_replay(first, changed)


def test_quality_gate_is_insufficient_until_sample_matures() -> None:
    report = assess_forward_quality(
        preregistration=_preregistration(),
        model_track=ModelTrack.TACTICAL,
        model_version="TACTICAL-SIGNAL-v2.2.0",
        completed_sessions=5,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
        operational_completeness=OperationalCompleteness.COMPLETE,
        target_evidence=(
            _metric(
                QualityTarget.TACTICAL_DECISION_QUALITY,
                eligible=50,
                frozen=100,
                coverage=Decimal("0.5"),
            ),
        ),
    )

    assert report.model_quality_status == QualityTerminalStatus.INSUFFICIENT_EVIDENCE
    assert report.operational_completeness == OperationalCompleteness.COMPLETE


def test_quality_gate_can_honestly_return_not_validated() -> None:
    report = assess_forward_quality(
        preregistration=_preregistration(),
        model_track=ModelTrack.TACTICAL,
        model_version="TACTICAL-SIGNAL-v2.2.0",
        completed_sessions=5,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
        operational_completeness=OperationalCompleteness.COMPLETE,
        target_evidence=(
            _metric(QualityTarget.TACTICAL_DECISION_QUALITY, lower=Decimal("-0.01")),
        ),
    )

    assert report.model_quality_status == QualityTerminalStatus.NOT_VALIDATED
    assert report.target_results[0].status == QualityTerminalStatus.NOT_VALIDATED


def test_quality_gate_validates_only_strict_block_bootstrap_evidence() -> None:
    report = assess_forward_quality(
        preregistration=_preregistration(),
        model_track=ModelTrack.TACTICAL,
        model_version="TACTICAL-SIGNAL-v2.2.0",
        completed_sessions=5,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
        operational_completeness=OperationalCompleteness.COMPLETE,
        target_evidence=(_metric(QualityTarget.TACTICAL_DECISION_QUALITY),),
    )

    assert report.model_quality_status == QualityTerminalStatus.VALIDATED
    assert report.ordinary_iid_bootstrap_used is False
    assert report.ai_influence is False


def test_126_session_long_observation_is_diagnostic_only() -> None:
    targets = tuple(
        _metric(
            target,
            outcome_horizon=126,
            completed_decision_sessions=600,
        ).model_copy(update={"bootstrap_block_sessions": 126})
        for target in (
            QualityTarget.BUSINESS_QUALITY,
            QualityTarget.SECURITY_ATTRACTIVENESS,
            QualityTarget.DOWNSIDE_RISK,
        )
    )
    report = assess_forward_quality(
        preregistration=_preregistration(),
        model_track=ModelTrack.LONG_HORIZON,
        model_version="LONG-HORIZON-RESEARCH-v1.1.0",
        completed_sessions=126,
        assessed_at=datetime(2028, 1, 1, tzinfo=UTC),
        operational_completeness=OperationalCompleteness.COMPLETE,
        target_evidence=targets,
    )

    assert report.model_quality_status == QualityTerminalStatus.DIAGNOSTIC_ONLY
    assert all(
        item.status == QualityTerminalStatus.DIAGNOSTIC_ONLY
        for item in report.target_results
    )


def test_252_session_long_horizon_can_return_mixed_without_aggregate_overclaim() -> None:
    targets = []
    for target in (
        QualityTarget.BUSINESS_QUALITY,
        QualityTarget.SECURITY_ATTRACTIVENESS,
        QualityTarget.DOWNSIDE_RISK,
    ):
        metric = _metric(
            target,
            outcome_horizon=252,
            completed_decision_sessions=600,
            lower=(
                Decimal("-0.01")
                if target == QualityTarget.SECURITY_ATTRACTIVENESS
                else Decimal("0.01")
            ),
        ).model_copy(update={"bootstrap_block_sessions": 252})
        targets.append(metric)
    report = assess_forward_quality(
        preregistration=_preregistration(),
        model_track=ModelTrack.LONG_HORIZON,
        model_version="LONG-HORIZON-RESEARCH-v1.1.0",
        completed_sessions=252,
        assessed_at=datetime(2029, 1, 1, tzinfo=UTC),
        operational_completeness=OperationalCompleteness.COMPLETE,
        target_evidence=tuple(targets),
    )

    assert report.model_quality_status == QualityTerminalStatus.MIXED
    assert {item.status for item in report.target_results} == {
        QualityTerminalStatus.VALIDATED,
        QualityTerminalStatus.NOT_VALIDATED,
    }


def test_operational_failure_blocks_quality_without_calling_it_model_failure() -> None:
    report = assess_forward_quality(
        preregistration=_preregistration(),
        model_track=ModelTrack.TACTICAL,
        model_version="TACTICAL-SIGNAL-v2.2.0",
        completed_sessions=5,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
        operational_completeness=OperationalCompleteness.INCOMPLETE,
        target_evidence=(_metric(QualityTarget.TACTICAL_DECISION_QUALITY),),
    )

    assert report.operational_completeness == OperationalCompleteness.INCOMPLETE
    assert report.model_quality_status == QualityTerminalStatus.BLOCKED_BY_DATA


def test_audit_payloads_are_build_only_and_artifact_writes_are_immutable(
    tmp_path: Path,
) -> None:
    preregistration = _preregistration()
    enrollment = _enrollment()
    outcome = _outcome_bundle()
    quality = assess_forward_quality(
        preregistration=preregistration,
        model_track=ModelTrack.TACTICAL,
        model_version="TACTICAL-SIGNAL-v2.2.0",
        completed_sessions=5,
        assessed_at=datetime(2027, 1, 1, tzinfo=UTC),
        operational_completeness=OperationalCompleteness.COMPLETE,
        target_evidence=(_metric(QualityTarget.TACTICAL_DECISION_QUALITY),),
    )

    for event in (
        build_preregistration_v16_audit_event_payload(preregistration),
        build_enrollment_v16_audit_event_payload(enrollment),
        build_outcome_v16_audit_event_payload(outcome),
        build_quality_v16_audit_event_payload(quality),
    ):
        assert event.detail["databaseWriteExecuted"] is False
        assert event.detail["providerNetworkRequests"] == 0
        assert event.detail["aiStatus"] == "NOT_EXECUTED"

    preregistration_path = tmp_path / "docs/generated/preregistration.json"
    assert (
        write_preregistration_artifact(
            preregistration,
            artifact_path=preregistration_path,
        )
        == preregistration_path
    )
    write_preregistration_artifact(
        preregistration,
        artifact_path=preregistration_path,
    )

    enrollment_manifest = tmp_path / "docs/generated/enrollment.json"
    first = write_enrollment_bundle(
        enrollment,
        repository_root=tmp_path,
        git_safe_manifest_path=enrollment_manifest,
    )
    second = write_enrollment_bundle(
        enrollment,
        repository_root=tmp_path,
        git_safe_manifest_path=enrollment_manifest,
    )
    assert first == second

    outcome_manifest = tmp_path / "docs/generated/outcome.json"
    first_outcome = write_outcome_bundle(
        outcome,
        repository_root=tmp_path,
        git_safe_manifest_path=outcome_manifest,
    )
    second_outcome = write_outcome_bundle(
        outcome,
        repository_root=tmp_path,
        git_safe_manifest_path=outcome_manifest,
    )
    assert first_outcome == second_outcome

    outcome_manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Immutable artifact conflict"):
        write_outcome_bundle(
            outcome,
            repository_root=tmp_path,
            git_safe_manifest_path=outcome_manifest,
        )
