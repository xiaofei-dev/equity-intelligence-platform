from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import (
    Actionability,
    BenchmarkAvailability,
    BenchmarkEvidenceBinding,
    CostPolicyBinding,
    EventRiskLevel,
    EvidenceState,
    FreezeStatus,
    HorizonOutlook,
    ModelFreezeBinding,
    ModelTrack,
    OutcomeDependence,
    ReadyDataSnapshotBinding,
    SetupThesis,
    TacticalComponentRecord,
    TacticalHorizon,
    ValidationEvidenceEnvelope,
)
from equity_analysis.forward_validation.decision_snapshot_v2 import (
    build_decision_snapshot,
    build_security_decision,
    build_v16_audit_event_payload,
    load_sealed_model_freeze,
    verify_idempotent_replay,
    write_snapshot_bundle,
)
from equity_analysis.research_rating.long_horizon_v11 import (
    CompanyModelV11,
    LongHorizonV11Inputs,
    evaluate_long_horizon_v11,
)
from equity_analysis.tactical.contracts_v22 import (
    ComponentScoreV22,
    HorizonAssessmentV22,
    TacticalAssessmentV22,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
PROFILE_ID = UUID("22222222-2222-4222-8222-222222222222")
DATA_SNAPSHOT_ID = UUID("33333333-3333-4333-8333-333333333333")
DECISION_AS_OF = datetime(2026, 7, 29, 22, tzinfo=UTC)


def _component(score: float = 50.0) -> ComponentScoreV22:
    return ComponentScoreV22(
        state=EvidenceState.VALID,
        score=score,
        reasons=("fixture",),
    )


def _horizon(horizon: TacticalHorizon) -> HorizonAssessmentV22:
    return HorizonAssessmentV22(
        horizon=horizon,
        trading_days=horizon.trading_days,
        selected_thesis=SetupThesis.CONTINUATION,
        continuation_eligible=True,
        mean_reversion_eligible=False,
        continuation_score=70.0,
        mean_reversion_score=40.0,
        opportunity_score=68.0,
        entry_value_score=64.0,
        risk_score=30.0,
        outlook=HorizonOutlook.FAVORABLE,
        actionability=Actionability.ENTRY,
        confidence="HIGH",
        maximum_risk_unit_multiplier=1.0,
        missing_inputs=(),
        reasons=("fixture",),
    )


def _tactical_assessment(
    *,
    ttl: int = 1,
    security_id: UUID = SECURITY_ID,
) -> TacticalAssessmentV22:
    return TacticalAssessmentV22(
        version="TACTICAL-SIGNAL-v2.2.0",
        input_schema_version="TACTICAL-INPUT-v2.2.0",
        feature_version="TACTICAL-FEATURES-v2.2.0",
        input_hash="A" * 64,
        decision_domain="SHORT_TERM_SPECULATION",
        data_cadence="COMPLETED_DAILY_SESSION",
        as_of_date=date(2026, 7, 29),
        decision_cutoff=DECISION_AS_OF,
        effective_from="NEXT_COMPLETED_SESSION_OPEN",
        signal_ttl_completed_sessions=ttl,
        security_id=str(security_id),
        market_benchmark_id="SPY",
        sector_benchmark_id="XLK",
        continuation_quality=_component(72),
        mean_reversion_potential=_component(45),
        rebound_readiness=_component(61),
        falling_knife_risk=_component(20),
        chase_risk=_component(30),
        volatility_risk=_component(35),
        liquidity=_component(90),
        market_regime=_component(65),
        sector_regime=_component(62),
        market_relative_strength=_component(67),
        sector_relative_strength=_component(66),
        event_risk_state=EvidenceState.VALID,
        event_risk_level=EventRiskLevel.LOW,
        horizons=tuple(_horizon(item) for item in TacticalHorizon),
        warnings=(),
    )


def _security_decision():
    long_assessment = evaluate_long_horizon_v11(
        LongHorizonV11Inputs(
            symbol="TEST",
            company_model=CompanyModelV11.GENERAL,
        )
    )
    return build_security_decision(
        public_security_id=SECURITY_ID,
        profile_id=PROFILE_ID,
        symbol="TEST",
        tactical_assessment=_tactical_assessment(),
        long_horizon_assessment=long_assessment,
        long_horizon_input_hash="B" * 64,
        long_horizon_evidence_hash="C" * 64,
    )


def _freezes() -> tuple[ModelFreezeBinding, ...]:
    return (
        load_sealed_model_freeze(
            repository_root=REPOSITORY_ROOT,
            artifact_path=(REPOSITORY_ROOT / "docs/generated/tactical-v2-2-model-freeze.json"),
            track=ModelTrack.TACTICAL,
        ),
        load_sealed_model_freeze(
            repository_root=REPOSITORY_ROOT,
            artifact_path=(REPOSITORY_ROOT / "docs/generated/long-horizon-v1-1-model-freeze.json"),
            track=ModelTrack.LONG_HORIZON,
        ),
    )


def _data_snapshot() -> ReadyDataSnapshotBinding:
    return ReadyDataSnapshotBinding(
        data_snapshot_id=DATA_SNAPSHOT_ID,
        state="READY",
        as_of=DECISION_AS_OF,
        universe_version="CLOSED-TEST-v1",
        universe_hash="sha256:" + "d" * 64,
        profile_set_hash=canonical_hash([str(PROFILE_ID)]),
        source_snapshot_hash="sha256:" + "e" * 64,
    )


def _benchmarks() -> tuple[BenchmarkEvidenceBinding, ...]:
    return (
        BenchmarkEvidenceBinding(
            benchmark_kind="MARKET",
            benchmark_id="SPY",
            version="BENCHMARK-EVIDENCE-v1",
            availability=BenchmarkAvailability.AVAILABLE,
            evidence_hash="sha256:" + "1" * 64,
        ),
        BenchmarkEvidenceBinding(
            benchmark_kind="SECTOR",
            benchmark_id="XLK",
            version="BENCHMARK-EVIDENCE-v1",
            availability=BenchmarkAvailability.AVAILABLE,
            evidence_hash="sha256:" + "2" * 64,
        ),
    )


def _bundle(*, freezes: tuple[ModelFreezeBinding, ...] | None = None):
    cost_hash = _freezes()[0].cost_model_hash
    return build_decision_snapshot(
        idempotency_key="forward-v2:2026-07-29:closed-test-v1",
        sealed_at=datetime(2026, 7, 30, 1, tzinfo=UTC),
        data_snapshot=_data_snapshot(),
        model_freezes=freezes or _freezes(),
        benchmark_evidence=_benchmarks(),
        cost_policy=CostPolicyBinding(
            policy_version="LIQUIDITY-SENSITIVE-COST-v1.0.0",
            contract_hash=cost_hash,
        ),
        evidence_envelope=ValidationEvidenceEnvelope(
            outcome_dependence=OutcomeDependence.NON_OVERLAPPING
        ),
        frozen_security_ids=(SECURITY_ID,),
        decisions=(_security_decision(),),
    )


def test_accepted_model_freezes_are_bound_by_all_three_hashes() -> None:
    tactical, long_horizon = _freezes()

    assert tactical.freeze_artifact_content_hash == (
        "sha256:a596080cd7936a6881a38e759c597934dae1125ec83026df6db0434f6fe31910"
    )
    assert tactical.freeze_record_hash == (
        "sha256:d6e3edb1160856ade700c37d42a4c9e2cdda3b88a4080dbc8ed73354b4c5bf99"
    )
    assert tactical.freeze_file_sha256 == (
        "sha256:5d541315f62990bc5f44a4e421f404d737f6ffcf039e586b18ba362a113dc49f"
    )
    assert long_horizon.freeze_artifact_content_hash == (
        "sha256:233271457387a5d7212379ae2c77d69c743dc69f7345fe2d834ff7dc98d4fa59"
    )
    assert long_horizon.freeze_record_hash == (
        "sha256:8f8e7fb671a8c35e771fdad6b9e3ed5d90950135acc9297bbff571f27780e6c3"
    )
    assert long_horizon.freeze_file_sha256 == (
        "sha256:e208c280355077009c4af102383881d89d3139242086e859b5eec4beb6873024"
    )


def test_snapshot_is_complete_deterministic_and_prospective_ready() -> None:
    first = _bundle()
    second = _bundle()

    assert first.controlled_artifact_hash == second.controlled_artifact_hash
    assert first.manifest == second.manifest
    assert first.snapshot.prospective_ready is True
    assert first.snapshot.blocked_reasons == ()
    assert first.snapshot.frozen_security_ids == (SECURITY_ID,)
    assert first.manifest.security_count == 1
    assert first.manifest.deterministic_numeric_results_included is False
    assert first.snapshot.decisions[0].long_horizon.default_ranking_score is None
    assert first.snapshot.decisions[0].long_horizon.deterministic_ranking_authorized is False


def test_git_safe_manifest_omits_deterministic_numeric_results() -> None:
    bundle = _bundle()
    manifest = bundle.manifest.model_dump(mode="json", by_alias=True)
    encoded = json.dumps(manifest, sort_keys=True)

    for forbidden in (
        '"opportunityScore"',
        '"entryValueScore"',
        '"riskScore"',
        '"businessQuality"',
        '"expectedReturn"',
        '"low"',
        '"base"',
        '"high"',
    ):
        assert forbidden not in encoded
    assert '"tacticalResultHash"' in encoded
    assert '"longHorizonResultHash"' in encoded


def test_tactical_ttl_cannot_be_relaxed() -> None:
    assessment = _tactical_assessment(ttl=2)
    long_assessment = evaluate_long_horizon_v11(
        LongHorizonV11Inputs(
            symbol="TEST",
            company_model=CompanyModelV11.GENERAL,
        )
    )

    with pytest.raises(ValidationError, match="expire after one session"):
        build_security_decision(
            public_security_id=SECURITY_ID,
            profile_id=PROFILE_ID,
            symbol="TEST",
            tactical_assessment=assessment,
            long_horizon_assessment=long_assessment,
            long_horizon_input_hash="B" * 64,
            long_horizon_evidence_hash="C" * 64,
        )


def test_long_horizon_record_cannot_authorize_a_default_rank() -> None:
    record = _security_decision().long_horizon
    payload = record.model_dump(mode="json", by_alias=True)
    payload["defaultRankingScore"] = "50"
    payload["deterministicRankingAuthorized"] = True

    with pytest.raises(ValidationError):
        record.__class__.model_validate(payload)


def test_complete_population_and_ready_profile_hash_are_required() -> None:
    decision = _security_decision()
    other_id = UUID("44444444-4444-4444-8444-444444444444")

    with pytest.raises(ValidationError, match="Every frozen security"):
        build_decision_snapshot(
            idempotency_key="incomplete",
            sealed_at=datetime(2026, 7, 30, 1, tzinfo=UTC),
            data_snapshot=_data_snapshot(),
            model_freezes=_freezes(),
            benchmark_evidence=_benchmarks(),
            cost_policy=CostPolicyBinding(
                policy_version="LIQUIDITY-SENSITIVE-COST-v1.0.0",
                contract_hash=_freezes()[0].cost_model_hash,
            ),
            evidence_envelope=ValidationEvidenceEnvelope(
                outcome_dependence=OutcomeDependence.NON_OVERLAPPING
            ),
            frozen_security_ids=(SECURITY_ID, other_id),
            decisions=(decision,),
        )

    bad_snapshot = _data_snapshot().model_copy(update={"profile_set_hash": "sha256:" + "0" * 64})
    with pytest.raises(ValueError, match="profile-set hash"):
        build_decision_snapshot(
            idempotency_key="wrong-profile-set",
            sealed_at=datetime(2026, 7, 30, 1, tzinfo=UTC),
            data_snapshot=bad_snapshot,
            model_freezes=_freezes(),
            benchmark_evidence=_benchmarks(),
            cost_policy=CostPolicyBinding(
                policy_version="LIQUIDITY-SENSITIVE-COST-v1.0.0",
                contract_hash=_freezes()[0].cost_model_hash,
            ),
            evidence_envelope=ValidationEvidenceEnvelope(
                outcome_dependence=OutcomeDependence.NON_OVERLAPPING
            ),
            frozen_security_ids=(SECURITY_ID,),
            decisions=(decision,),
        )


def test_input_contract_only_freeze_blocks_prospective_readiness() -> None:
    tactical, long_horizon = _freezes()
    draft_payload = tactical.model_dump(mode="json", by_alias=True)
    draft_payload.update(
        {
            "status": FreezeStatus.INPUT_CONTRACT_ONLY,
            "frozenAt": None,
            "observedEvidenceCutoff": None,
            "freezeRecordHash": None,
            "freezeArtifactContentHash": None,
            "freezeFileSha256": None,
        }
    )
    draft = ModelFreezeBinding.model_validate(draft_payload)

    bundle = _bundle(freezes=(draft, long_horizon))

    assert bundle.snapshot.prospective_ready is False
    assert bundle.snapshot.blocked_reasons == ("MODEL_FREEZE_ARTIFACT_PENDING",)


def test_unaccepted_sealed_freeze_is_rejected() -> None:
    tactical, long_horizon = _freezes()
    forged = tactical.model_copy(update={"freeze_record_hash": "sha256:" + "f" * 64})

    with pytest.raises(ValueError, match="not an accepted immutable artifact"):
        _bundle(freezes=(forged, long_horizon))


def test_idempotency_key_cannot_bind_different_evidence() -> None:
    first = _bundle()
    second = _bundle()
    verify_idempotent_replay(first.manifest, second.manifest)

    changed = second.manifest.model_copy(update={"controlled_artifact_hash": "sha256:" + "f" * 64})
    with pytest.raises(ValueError, match="different evidence"):
        verify_idempotent_replay(first.manifest, changed)


def test_audit_payload_is_build_only_and_artifacts_are_immutable(
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    event = build_v16_audit_event_payload(bundle)

    assert event.event_type == "FORWARD_V2_DAILY_DECISION_SNAPSHOT_SEALED"
    assert event.detail["databaseWriteExecuted"] is False
    assert event.detail["providerNetworkRequests"] == 0
    assert event.detail["aiStatus"] == "NOT_EXECUTED"

    manifest_path = tmp_path / "docs/generated/forward-v2-test.json"
    first_paths = write_snapshot_bundle(
        bundle,
        repository_root=tmp_path,
        manifest_path=manifest_path,
    )
    second_paths = write_snapshot_bundle(
        bundle,
        repository_root=tmp_path,
        manifest_path=manifest_path,
    )
    assert first_paths == second_paths

    changed = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed["securityCount"] = 2
    manifest_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="Immutable artifact conflict"):
        write_snapshot_bundle(
            bundle,
            repository_root=tmp_path,
            manifest_path=manifest_path,
        )


def test_component_state_never_turns_missing_into_a_neutral_score() -> None:
    with pytest.raises(ValidationError):
        TacticalComponentRecord(
            state=EvidenceState.MISSING,
            score=50,
        )

    missing = replace(_component(), state=EvidenceState.MISSING, score=None)
    assert missing.state == EvidenceState.MISSING
