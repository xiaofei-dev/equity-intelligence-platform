from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_contracts_v21 import (
    BenchmarkFamilyEvidenceV21,
    ForwardV21ContractError,
    ForwardV21ErrorCode,
    GitSafeDecisionManifestV21,
    build_benchmark_preregistration_v21,
    build_decision_manifest_v21,
    build_enrollment_v21,
    build_git_safe_benchmark_manifest_v21,
    seal_controlled_benchmark_bundle_v21,
    seal_controlled_benchmark_construction_artifact_v21,
    verify_controlled_benchmark_bundle_v21,
    verify_controlled_benchmark_construction_artifact_v21,
    verify_decision_manifest_v21,
    verify_git_safe_benchmark_manifest_v21,
    verify_idempotent_enrollment_replay_v21,
)
from equity_analysis.forward_validation.contracts_v2 import (
    BenchmarkAvailability,
    GitSafeDecisionManifest,
    GitSafeDecisionRow,
    ModelTrack,
    PopulationTerminalState,
)
from equity_analysis.forward_validation.decision_snapshot_v2 import (
    load_sealed_model_freeze,
)
from equity_analysis.forward_validation.prospective_protocol_v2 import (
    build_preregistration,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
PROFILE_ID = UUID("22222222-2222-4222-8222-222222222222")
SNAPSHOT_ID = UUID("33333333-3333-4333-8333-333333333333")
DECISION_AS_OF = datetime(2026, 7, 30, 22, tzinfo=UTC)
REGISTERED_AT = datetime(2026, 7, 30, 1, tzinfo=UTC)
POLICY_HASH = "sha256:" + "c" * 64


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


def _parent_preregistration():
    return build_preregistration(
        repository_root=REPOSITORY_ROOT,
        registered_at=REGISTERED_AT,
        model_freezes=_freezes(),
    )


def _source_manifest(
    *,
    prospective_ready: bool = False,
    blocked_reasons: tuple[str, ...] = ("REQUIRED_BENCHMARK_EVIDENCE_UNAVAILABLE",),
    terminal_counts: dict[str, int] | None = None,
):
    preregistration = _parent_preregistration()
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
            "storage/forward-validation/decision-snapshots-v2/" + "8" * 64 + ".json"
        ),
        "prospectiveReady": prospective_ready,
        "blockedReasons": blocked_reasons,
        "securityCount": 1,
        "terminalCounts": terminal_counts or {"TACTICAL:ASSESSED": 1, "LONG_HORIZON:ASSESSED": 1},
        "decisions": (row.model_dump(mode="json", by_alias=True),),
        "rawProviderValuesIncluded": False,
        "deterministicNumericResultsIncluded": False,
        "aiUsedForDeterministicDecisions": False,
    }
    return GitSafeDecisionManifest.model_validate(
        {**body, "manifestContentHash": canonical_hash(body)}
    )


def _families(
    *,
    unavailable: BenchmarkKind | None = None,
    unavailable_status: BenchmarkAvailability = BenchmarkAvailability.MISSING,
) -> tuple[BenchmarkFamilyEvidenceV21, ...]:
    return tuple(
        BenchmarkFamilyEvidenceV21(
            kind=kind,
            benchmark_id=f"{kind.value}-v1",
            construction_method=(
                "DIRECT_TOTAL_RETURN"
                if kind in {BenchmarkKind.SPY, BenchmarkKind.SECTOR}
                else "FROZEN_SYNTHETIC_PORTFOLIO"
            ),
            availability=(
                unavailable_status if kind == unavailable else BenchmarkAvailability.AVAILABLE
            ),
            evidence_hash=(None if kind == unavailable else "sha256:" + format(index, "x") * 64),
            source_evidence_hash=(None if kind == unavailable else "sha256:" + "a" * 64),
            constituent_set_hash=(None if kind == unavailable else "sha256:" + "b" * 64),
            weight_hash=(None if kind == unavailable else "sha256:" + "c" * 64),
            selection_hash=(None if kind == unavailable else "sha256:" + "d" * 64),
            cost_evidence_hash=(None if kind == unavailable else "sha256:" + "e" * 64),
            sector_assignment_hash=(
                "sha256:" + "f" * 64
                if kind == BenchmarkKind.SECTOR and kind != unavailable
                else None
            ),
            reason="TEST_MISSING" if kind == unavailable else None,
        )
        for index, kind in enumerate(BenchmarkKind, start=1)
    )


def _chain(
    *,
    unavailable: BenchmarkKind | None = None,
    unavailable_status: BenchmarkAvailability = BenchmarkAvailability.MISSING,
):
    parent = _parent_preregistration()
    source = _source_manifest()
    families = _families(
        unavailable=unavailable,
        unavailable_status=unavailable_status,
    )
    benchmark_preregistration = build_benchmark_preregistration_v21(
        parent=parent,
        registered_at=REGISTERED_AT + timedelta(minutes=1),
        construction_policy_version="FORWARD-BENCHMARK-CONSTRUCTION-v2.1.0",
        construction_policy_hash=POLICY_HASH,
    )
    construction = seal_controlled_benchmark_construction_artifact_v21(
        data_snapshot_id=SNAPSHOT_ID,
        decision_as_of=DECISION_AS_OF,
        ingestion_cutoff=DECISION_AS_OF - timedelta(minutes=1),
        universe_version=source.universe_version,
        universe_hash=source.universe_hash,
        frozen_population_hash=source.frozen_population_hash,
        construction_policy_version="FORWARD-BENCHMARK-CONSTRUCTION-v2.1.0",
        construction_policy_hash=POLICY_HASH,
        cost_policy_version=parent.cost_policy_version,
        cost_policy_hash=parent.cost_policy_hash,
        parent_liquidity_cost_policy_version=parent.cost_policy_version,
        parent_liquidity_cost_policy_hash=parent.cost_policy_hash,
        families=families,
    )
    bundle = seal_controlled_benchmark_bundle_v21(
        construction_artifact=construction,
        construction_artifact_reference=(
            "storage/forward-validation/benchmark-construction-v2-1/"
            + construction.artifact_content_hash.removeprefix("sha256:")
            + ".json"
        ),
    )
    benchmark_manifest = build_git_safe_benchmark_manifest_v21(
        bundle=bundle,
        construction_artifact=construction,
        controlled_bundle_reference=(
            "storage/forward-validation/benchmark-evidence-v2-1/"
            + bundle.bundle_content_hash.removeprefix("sha256:")
            + ".json"
        ),
    )
    decision = build_decision_manifest_v21(
        parent_preregistration=parent,
        benchmark_preregistration=benchmark_preregistration,
        source=source,
        benchmark_manifest=benchmark_manifest,
        bundle=bundle,
        construction_artifact=construction,
    )
    return (
        parent,
        benchmark_preregistration,
        source,
        construction,
        bundle,
        benchmark_manifest,
        decision,
    )


def _maturities():
    return {
        sessions: DECISION_AS_OF + timedelta(days=sessions + 5)
        for sessions in (5, 20, 60, 126, 252)
    }


def _enroll(chain):
    parent, benchmark_preregistration, source, construction, bundle, manifest, decision = chain
    return build_enrollment_v21(
        parent_preregistration=parent,
        benchmark_preregistration=benchmark_preregistration,
        source_decision_manifest=source,
        decision_manifest=decision,
        benchmark_manifest=manifest,
        controlled_bundle=bundle,
        controlled_construction_artifact=construction,
        idempotency_key="forward-v2.1:2026-07-30:closed-test-v1",
        enrolled_at=DECISION_AS_OF + timedelta(hours=1),
        effective_at_completed_session_open=DECISION_AS_OF + timedelta(hours=15),
        maturity_sessions=_maturities(),
    )


def _rehash_decision(value: GitSafeDecisionManifestV21, **updates):
    body = value.model_dump(mode="json", by_alias=True)
    body.pop("manifestContentHash")
    body.update(updates)
    return GitSafeDecisionManifestV21.model_validate(
        {**body, "manifestContentHash": canonical_hash(body)}
    )


def test_complete_six_family_chain_enrolls_and_replays_exactly():
    chain = _chain()
    enrollment = _enroll(chain)

    assert chain[-1].prospective_ready is True
    assert enrollment.prospective_ready is True
    assert verify_idempotent_enrollment_replay_v21(enrollment, enrollment) == ("EXACT_REPLAY")


def test_v20_manifest_cannot_enter_v21_enrollment():
    chain = _chain()
    parent, prereg, source, construction, bundle, manifest, _ = chain

    with pytest.raises(ForwardV21ContractError) as error:
        build_enrollment_v21(
            parent_preregistration=parent,
            benchmark_preregistration=prereg,
            source_decision_manifest=source,
            decision_manifest=source,
            benchmark_manifest=manifest,
            controlled_bundle=bundle,
            controlled_construction_artifact=construction,
            idempotency_key="reject-v2",
            enrolled_at=DECISION_AS_OF + timedelta(hours=1),
            effective_at_completed_session_open=DECISION_AS_OF + timedelta(hours=15),
            maturity_sessions=_maturities(),
        )

    assert error.value.code == ForwardV21ErrorCode.V21_MANIFEST_REQUIRED


@pytest.mark.parametrize(
    "availability",
    [
        BenchmarkAvailability.MISSING,
        BenchmarkAvailability.STALE,
        BenchmarkAvailability.INVALID,
    ],
)
def test_unavailable_family_blocks_readiness_and_enrollment(availability):
    chain = _chain(
        unavailable=BenchmarkKind.PURE_VALUE,
        unavailable_status=availability,
    )
    family = chain[3].families[-2]
    assert family.kind == BenchmarkKind.PURE_VALUE
    assert family.availability == availability

    assert chain[-1].prospective_ready is False
    with pytest.raises(ForwardV21ContractError) as error:
        _enroll(chain)
    assert error.value.code == ForwardV21ErrorCode.BENCHMARK_UNAVAILABLE


def test_duplicate_and_missing_benchmark_kinds_have_stable_codes():
    families = _families()
    duplicate = families[:-1] + (families[0],)

    with pytest.raises(ForwardV21ContractError) as duplicate_error:
        seal_controlled_benchmark_construction_artifact_v21(
            data_snapshot_id=SNAPSHOT_ID,
            decision_as_of=DECISION_AS_OF,
            ingestion_cutoff=DECISION_AS_OF,
            universe_version="CLOSED-TEST-v1",
            universe_hash="sha256:" + "1" * 64,
            frozen_population_hash="sha256:" + "2" * 64,
            construction_policy_version="POLICY-v1",
            construction_policy_hash=POLICY_HASH,
            cost_policy_version="COST-v1",
            cost_policy_hash="sha256:" + "3" * 64,
            parent_liquidity_cost_policy_version="PARENT-COST-v1",
            parent_liquidity_cost_policy_hash="sha256:" + "4" * 64,
            families=duplicate,
        )
    assert duplicate_error.value.code == ForwardV21ErrorCode.BENCHMARK_KIND_DUPLICATE

    with pytest.raises(ForwardV21ContractError) as missing_error:
        seal_controlled_benchmark_construction_artifact_v21(
            data_snapshot_id=SNAPSHOT_ID,
            decision_as_of=DECISION_AS_OF,
            ingestion_cutoff=DECISION_AS_OF,
            universe_version="CLOSED-TEST-v1",
            universe_hash="sha256:" + "1" * 64,
            frozen_population_hash="sha256:" + "2" * 64,
            construction_policy_version="POLICY-v1",
            construction_policy_hash=POLICY_HASH,
            cost_policy_version="COST-v1",
            cost_policy_hash="sha256:" + "3" * 64,
            parent_liquidity_cost_policy_version="PARENT-COST-v1",
            parent_liquidity_cost_policy_hash="sha256:" + "4" * 64,
            families=families[:-1],
        )
    assert missing_error.value.code == ForwardV21ErrorCode.BENCHMARK_SET_INCOMPLETE


def test_forged_ready_flag_is_rejected_after_rehash():
    chain = _chain(unavailable=BenchmarkKind.PURE_VALUE)
    forged = _rehash_decision(
        chain[-1],
        prospectiveReady=True,
        blockedReasons=(),
    )

    with pytest.raises(ForwardV21ContractError) as error:
        verify_decision_manifest_v21(
            forged,
            parent_preregistration=chain[0],
            benchmark_preregistration=chain[1],
            source=chain[2],
            benchmark_manifest=chain[5],
            bundle=chain[4],
            construction_artifact=chain[3],
        )

    assert error.value.code == ForwardV21ErrorCode.READY_FORGED


def test_bundle_hash_drift_and_manifest_relink_are_rejected():
    chain = _chain()
    drifted_bundle = chain[4].model_copy(update={"bundle_content_hash": "sha256:" + "0" * 64})
    with pytest.raises(ForwardV21ContractError) as hash_error:
        verify_controlled_benchmark_bundle_v21(
            drifted_bundle,
            construction_artifact=chain[3],
            require_available=True,
        )
    assert hash_error.value.code == ForwardV21ErrorCode.HASH_INVALID

    relinked = chain[5].model_copy(
        update={"controlled_bundle_reference": "storage/elsewhere/bundle.json"}
    )
    body = relinked.model_dump(mode="json", by_alias=True)
    body.pop("manifestContentHash")
    relinked = relinked.model_copy(update={"manifest_content_hash": canonical_hash(body)})
    with pytest.raises(ForwardV21ContractError) as link_error:
        verify_git_safe_benchmark_manifest_v21(
            relinked,
            bundle=chain[4],
            construction_artifact=chain[3],
            require_available=True,
        )
    assert link_error.value.code == ForwardV21ErrorCode.EVIDENCE_LINK_MISMATCH


def test_incomplete_population_cannot_build_v21_manifest():
    source = _source_manifest(terminal_counts={"TACTICAL:ASSESSED": 1, "LONG_HORIZON:ASSESSED": 0})
    chain = _chain()

    with pytest.raises(ForwardV21ContractError) as error:
        build_decision_manifest_v21(
            parent_preregistration=chain[0],
            benchmark_preregistration=chain[1],
            source=source,
            benchmark_manifest=chain[5],
            bundle=chain[4],
            construction_artifact=chain[3],
        )

    assert error.value.code == ForwardV21ErrorCode.POPULATION_INCOMPLETE


def test_opaque_family_hash_cannot_replace_construction_ledger():
    with pytest.raises(ValidationError):
        BenchmarkFamilyEvidenceV21(
            kind=BenchmarkKind.SPY,
            benchmark_id="SPY-v1",
            construction_method="DIRECT_TOTAL_RETURN",
            availability=BenchmarkAvailability.AVAILABLE,
            evidence_hash="sha256:" + "1" * 64,
        )


def test_component_ledger_hash_drift_breaks_construction_link():
    chain = _chain()
    construction = chain[3]
    first = construction.families[0].model_copy(update={"weight_hash": "sha256:" + "0" * 64})
    families = (first, *construction.families[1:])
    body = construction.model_dump(mode="json", by_alias=True)
    body.pop("artifactContentHash")
    body["families"] = tuple(item.model_dump(mode="json", by_alias=True) for item in families)
    drifted = construction.model_copy(
        update={
            "families": families,
            "artifact_content_hash": canonical_hash(body),
        }
    )
    verify_controlled_benchmark_construction_artifact_v21(
        drifted,
        require_available=True,
    )

    with pytest.raises(ForwardV21ContractError) as error:
        verify_controlled_benchmark_bundle_v21(
            chain[4],
            construction_artifact=drifted,
            require_available=True,
        )

    assert error.value.code == ForwardV21ErrorCode.EVIDENCE_LINK_MISMATCH


def test_late_benchmark_preregistration_cannot_promote_old_snapshot():
    chain = _chain()
    late = build_benchmark_preregistration_v21(
        parent=chain[0],
        registered_at=DECISION_AS_OF + timedelta(minutes=1),
        construction_policy_version=chain[3].construction_policy_version,
        construction_policy_hash=chain[3].construction_policy_hash,
    )

    with pytest.raises(ForwardV21ContractError) as error:
        build_decision_manifest_v21(
            parent_preregistration=chain[0],
            benchmark_preregistration=late,
            source=chain[2],
            benchmark_manifest=chain[5],
            bundle=chain[4],
            construction_artifact=chain[3],
        )

    assert error.value.code == ForwardV21ErrorCode.PREREGISTRATION_MISMATCH
