from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

import equity_analysis.forward_validation.prospective_enrollment_adapter_v22 as enrollment_adapter
from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.outcome_persistence_v21 import (
    ForwardDqvPersistenceConflict,
)
from equity_analysis.forward_validation.outcomes_v211 import (
    ForwardDqvEnrollmentV211,
)
from equity_analysis.forward_validation.post_freeze_decision_snapshot_v22 import (
    EXPECTED_BENCHMARK_KINDS,
    POST_FREEZE_AI_BOUNDARY_V22,
    POST_FREEZE_BENCHMARK_EVIDENCE_V22,
    POST_FREEZE_DECISION_INPUT_V22,
    AiNarrativeBoundaryV22,
    ArtifactPurpose,
    BenchmarkEvidenceV22,
    BenchmarkTerminalState,
    assemble_post_freeze_decision_snapshot_v22,
    build_post_freeze_contract_fixture_v22,
)
from equity_analysis.forward_validation.prospective_enrollment_adapter_v22 import (
    EnrollmentPersistenceBindingV22,
    ProspectiveEnrollmentAdapterError,
    persist_prepared_enrollment_v22,
    prepare_prospective_enrollment_v22,
    write_immutable_enrollment_preflight,
)
from equity_analysis.forward_validation.v19_acceptance_v1 import (
    verify_forward_dqv_v19_acceptance,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HASH = "sha256:" + "a" * 64
DECISION_COMPOSITE_HASH = canonical_hash({"fixture": "decision-composite"})
DECISION_COMPOSITE_FILE_HASH = canonical_hash(
    {"fixture": "decision-composite-file"}
)


class FakeAtomicEnrollmentRepository:
    def __init__(self) -> None:
        self.rows: dict[str, ForwardDqvEnrollmentV211] = {}
        self.calls = 0

    def persist_enrollment(self, enrollment: ForwardDqvEnrollmentV211) -> UUID:
        self.calls += 1
        existing = self.rows.get(enrollment.idempotency_key)
        if existing is not None:
            if (
                existing.canonical_request_hash
                != enrollment.canonical_request_hash
                or existing.enrollment_content_hash
                != enrollment.enrollment_content_hash
            ):
                raise ForwardDqvPersistenceConflict(
                    "Fake repository detected an idempotency conflict"
                )
            return existing.enrollment_id
        self.rows[enrollment.idempotency_key] = enrollment
        return enrollment.enrollment_id


def _hash(label: str) -> str:
    return canonical_hash({"fixture": label})


def _benchmark_manifest() -> dict[str, Any]:
    body = {
        "artifactType": "FORWARD_BENCHMARK_MANIFEST",
        "schemaVersion": "FORWARD-BENCHMARK-MANIFEST-v2.2.0",
        "status": "READY",
        "allSixAvailable": True,
        "completedSession": "2026-07-30",
        "families": [
            {"kind": kind, "state": "AVAILABLE"}
            for kind in EXPECTED_BENCHMARK_KINDS
        ],
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def _prospective_snapshot(benchmark_hash: str):
    fixture = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    benchmark_evidence = tuple(
        BenchmarkEvidenceV22(
            schema_version=POST_FREEZE_BENCHMARK_EVIDENCE_V22,
            benchmark_kind=kind,
            terminal_state=BenchmarkTerminalState.AVAILABLE,
            completed_session=fixture.completed_session,
            contract_hash=_hash(f"contract:{kind}"),
            source_binding_hash=benchmark_hash,
            evidence_hash=_hash(f"evidence:{kind}"),
        )
        for kind in EXPECTED_BENCHMARK_KINDS
    )
    return assemble_post_freeze_decision_snapshot_v22(
        repository_root=REPOSITORY_ROOT,
        purpose=ArtifactPurpose.PROSPECTIVE_DECISION,
        source_input_contract_version=POST_FREEZE_DECISION_INPUT_V22,
        decision_cutoff=fixture.decision_cutoff,
        completed_session_price_evidence=(
            fixture.completed_session_price_evidence
        ),
        model_freezes=fixture.model_freezes,
        benchmark_evidence=benchmark_evidence,
        cost_policy_hash=fixture.cost_policy_hash,
        sector_classification_hash=fixture.sector_classification_hash,
        source_snapshot_hash=fixture.source_snapshot_hash,
        decisions=fixture.decisions,
        ai_narrative=AiNarrativeBoundaryV22(
            schema_version=POST_FREEZE_AI_BOUNDARY_V22,
            status="NOT_EXECUTED",
            may_affect_deterministic_fields=False,
        ),
    )


@pytest.fixture(autouse=True)
def _stub_verified_composite_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    benchmark = _benchmark_manifest()
    snapshot = _prospective_snapshot(benchmark["artifactContentHash"])
    composite = SimpleNamespace(
        schema_version=(
            "FORWARD-DQV-DECISION-CONTROLLED-COMPOSITE-v2.2.0"
        ),
        decision_cutoff=snapshot.decision_cutoff,
        completed_session=snapshot.completed_session,
        source_snapshot_hash=snapshot.source_snapshot_hash,
        population_identity_binding_hash=(
            snapshot.population_identity_binding_hash
        ),
        post_freeze_decision_manifest_hash=snapshot.manifest_content_hash,
        benchmark_manifest_hash=benchmark["artifactContentHash"],
        cost_policy_hash=snapshot.cost_policy_hash,
    )
    monkeypatch.setattr(
        enrollment_adapter,
        "load_decision_controlled_composite_v22",
        lambda **_kwargs: composite,
    )
    monkeypatch.setattr(
        enrollment_adapter,
        "verify_forward_dqv_v19_acceptance",
        lambda artifact, _root: artifact["artifactContentHash"],
    )


def _v18_acceptance() -> dict[str, Any]:
    return json.loads(
        (
            REPOSITORY_ROOT
            / "docs/generated/forward-dqv-v18-acceptance-v1.json"
        ).read_text(encoding="utf-8")
    )


def _v19_acceptance() -> dict[str, Any]:
    return json.loads(
        (
            REPOSITORY_ROOT
            / "docs/generated/forward-dqv-v19-chronology-acceptance-v1.json"
        ).read_text(encoding="utf-8")
    )


def _successor_controller(
    *,
    snapshot_hash: str,
    benchmark_hash: str,
    v18_hash: str,
    seal_hash: str,
) -> dict[str, Any]:
    body = {
        "artifactType": "FORWARD_V2_2_SUCCESSOR_PROSPECTIVE_READINESS",
        "schemaVersion": "PROSPECTIVE-READINESS-CONTROLLER-v2.2.0",
        "status": "READY",
        "blockedReasons": [],
        "preregistrationSealHash": seal_hash,
        "postFreezeDecisionManifestHash": snapshot_hash,
        "benchmarkManifestHash": benchmark_hash,
        "v18AcceptanceHash": v18_hash,
        "commonCompletedSession": "2026-07-30",
        "benchmarkKindsObserved": list(EXPECTED_BENCHMARK_KINDS),
        "providerNetworkRequestsExecuted": 0,
        "databaseReadsExecuted": 0,
        "databaseWritesExecuted": 0,
        "enrollmentExecuted": False,
        "scoresOrRanksComputed": False,
        "outcomesComputed": False,
        "aiUsedForDeterministicFields": False,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def _binding(
    snapshot_hash: str,
    *,
    idempotency_key: str = "forward-v22-fixture-enrollment",
    sealed_at: datetime = datetime(2026, 7, 31, 13, tzinfo=UTC),
) -> EnrollmentPersistenceBindingV22:
    return EnrollmentPersistenceBindingV22(
        decision_data_snapshot_id=UUID(
            "b51a0367-973c-593f-a626-96b83c58f8f9"
        ),
        source_snapshot_hash=snapshot_hash,
        universe_version="forward-dqv-v2-frozen-66",
        decision_controlled_artifact_reference=(
            "storage/forward-validation/post-freeze/"
            "2026-07-30/decision-snapshot-v2-2.json"
        ),
        decision_controlled_artifact_hash=DECISION_COMPOSITE_HASH,
        decision_controlled_artifact_file_sha256=(
            DECISION_COMPOSITE_FILE_HASH
        ),
        idempotency_key=idempotency_key,
        sealed_at=sealed_at,
    )


def _ready_preparation(
    *,
    binding: EnrollmentPersistenceBindingV22 | None = None,
    sealed_at: datetime = datetime(2026, 7, 31, 13, tzinfo=UTC),
):
    benchmark = _benchmark_manifest()
    snapshot = _prospective_snapshot(benchmark["artifactContentHash"])
    v18 = _v18_acceptance()
    controller = _successor_controller(
        snapshot_hash=snapshot.manifest_content_hash,
        benchmark_hash=benchmark["artifactContentHash"],
        v18_hash=v18["artifactContentHash"],
        seal_hash=snapshot.seal.content_hash,
    )
    return prepare_prospective_enrollment_v22(
        repository_root=REPOSITORY_ROOT,
        successor_readiness=controller,
        decision_snapshot=snapshot,
        benchmark_manifest=benchmark,
        v18_acceptance=v18,
        v19_chronology_acceptance=_v19_acceptance(),
        persistence_binding=binding
        or _binding(snapshot.source_snapshot_hash, sealed_at=sealed_at),
    )


def test_current_contract_fixture_produces_only_blocked_preflight() -> None:
    fixture = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    result = prepare_prospective_enrollment_v22(
        repository_root=REPOSITORY_ROOT,
        successor_readiness=None,
        decision_snapshot=fixture,
        benchmark_manifest=None,
        v18_acceptance=_v18_acceptance(),
        v19_chronology_acceptance=_v19_acceptance(),
        persistence_binding=None,
    )

    assert result.status == "BLOCKED"
    assert result.enrollment is None
    assert {
        "SUCCESSOR_READINESS_CONTROLLER_MISSING",
        "POST_FREEZE_DECISION_NOT_PROSPECTIVE",
        "POST_FREEZE_DECISION_SIX_BENCHMARKS_NOT_AVAILABLE",
        "BENCHMARK_MANIFEST_MISSING",
        "V18_PERSISTENCE_BINDING_MISSING",
    }.issubset(result.blockers)
    assert result.preflight_artifact["databaseWritesExecuted"] == 0
    assert result.preflight_artifact["enrollmentExecuted"] is False


def test_ready_contract_builds_66_population_and_five_horizons() -> None:
    result = _ready_preparation()

    assert result.status == "READY_FOR_PERSISTENCE"
    assert result.blockers == ()
    assert result.enrollment is not None
    enrollment = result.enrollment
    assert enrollment.security_count == 66
    assert enrollment.terminal_counts == {
        "ASSESSED": 0,
        "MISSING": 55,
        "STALE": 0,
        "INVALID": 0,
        "EXCLUDED": 9,
        "ABSTAINED": 2,
    }
    assert tuple(
        item.completed_sessions for item in enrollment.maturity_schedule
    ) == (5, 20, 60, 126, 252)
    assert enrollment.maturity_schedule[3].formal_gate_eligible is False
    assert (
        enrollment.maturity_schedule[3].evaluation_role.value
        == "LONG_HORIZON_INTERIM_DIAGNOSTIC"
    )
    assert enrollment.maturity_schedule[4].formal_gate_eligible is True
    assert (
        enrollment.maturity_schedule[4].evaluation_role.value
        == "LONG_HORIZON_FORMAL"
    )


def test_missing_decision_composite_receipt_blocks_enrollment() -> None:
    benchmark = _benchmark_manifest()
    snapshot = _prospective_snapshot(benchmark["artifactContentHash"])
    binding = _binding(snapshot.source_snapshot_hash).model_copy(
        update={
            "decision_controlled_artifact_hash": None,
            "decision_controlled_artifact_file_sha256": None,
        }
    )

    result = _ready_preparation(binding=binding)

    assert result.status == "BLOCKED"
    assert result.enrollment is None
    assert (
        "DECISION_CONTROLLED_COMPOSITE_RECEIPT_MISSING" in result.blockers
    )


def test_persistence_requires_explicit_execute_flag() -> None:
    result = _ready_preparation()
    repository = FakeAtomicEnrollmentRepository()

    with pytest.raises(
        ProspectiveEnrollmentAdapterError,
        match="EXPLICIT_DATABASE_WRITE_AUTHORIZATION_REQUIRED",
    ):
        persist_prepared_enrollment_v22(
            result,
            repository=repository,
        )

    assert repository.calls == 0
    assert repository.rows == {}


def test_fake_repository_atomic_exact_replay() -> None:
    result = _ready_preparation()
    repository = FakeAtomicEnrollmentRepository()

    first = persist_prepared_enrollment_v22(
        result,
        repository=repository,
        execute=True,
    )
    second = persist_prepared_enrollment_v22(
        result,
        repository=repository,
        execute=True,
    )

    assert first == second
    assert len(repository.rows) == 1
    assert repository.calls == 2
    stored = next(iter(repository.rows.values()))
    assert len(stored.maturity_schedule) == 5


def test_fake_repository_rejects_same_key_with_changed_contract() -> None:
    first = _ready_preparation()
    assert first.enrollment is not None
    changed = _ready_preparation(
        sealed_at=datetime(2026, 7, 31, 13, 15, tzinfo=UTC),
    )
    repository = FakeAtomicEnrollmentRepository()
    persist_prepared_enrollment_v22(
        first,
        repository=repository,
        execute=True,
    )

    with pytest.raises(ForwardDqvPersistenceConflict):
        persist_prepared_enrollment_v22(
            changed,
            repository=repository,
            execute=True,
        )

    assert len(repository.rows) == 1


def test_seal_after_entry_open_is_blocked_before_repository_access() -> None:
    result = _ready_preparation(
        sealed_at=datetime(2026, 7, 31, 13, 31, tzinfo=UTC),
    )
    repository = FakeAtomicEnrollmentRepository()

    assert result.status == "BLOCKED"
    assert result.enrollment is None
    assert "ENROLLMENT_SEALED_AFTER_PROSPECTIVE_ENTRY_OPEN" in result.blockers
    with pytest.raises(
        ProspectiveEnrollmentAdapterError,
        match="PROSPECTIVE_ENROLLMENT_PREFLIGHT_BLOCKED",
    ):
        persist_prepared_enrollment_v22(
            result,
            repository=repository,
            execute=True,
        )
    assert repository.calls == 0


def test_controller_hash_chain_mismatch_blocks_enrollment() -> None:
    benchmark = _benchmark_manifest()
    snapshot = _prospective_snapshot(benchmark["artifactContentHash"])
    v18 = _v18_acceptance()
    controller = _successor_controller(
        snapshot_hash=HASH,
        benchmark_hash=benchmark["artifactContentHash"],
        v18_hash=v18["artifactContentHash"],
        seal_hash=snapshot.seal.content_hash,
    )

    result = prepare_prospective_enrollment_v22(
        repository_root=REPOSITORY_ROOT,
        successor_readiness=controller,
        decision_snapshot=snapshot,
        benchmark_manifest=benchmark,
        v18_acceptance=v18,
        v19_chronology_acceptance=_v19_acceptance(),
        persistence_binding=_binding(snapshot.source_snapshot_hash),
    )

    assert result.status == "BLOCKED"
    assert "SUCCESSOR_DECISION_HASH_CHAIN_MISMATCH" in result.blockers


def test_invalid_v18_acceptance_blocks_enrollment() -> None:
    benchmark = _benchmark_manifest()
    snapshot = _prospective_snapshot(benchmark["artifactContentHash"])
    v18 = _v18_acceptance()
    v18["migrationApplied"] = False
    controller = _successor_controller(
        snapshot_hash=snapshot.manifest_content_hash,
        benchmark_hash=benchmark["artifactContentHash"],
        v18_hash=v18["artifactContentHash"],
        seal_hash=snapshot.seal.content_hash,
    )

    result = prepare_prospective_enrollment_v22(
        repository_root=REPOSITORY_ROOT,
        successor_readiness=controller,
        decision_snapshot=snapshot,
        benchmark_manifest=benchmark,
        v18_acceptance=v18,
        v19_chronology_acceptance=_v19_acceptance(),
        persistence_binding=_binding(snapshot.source_snapshot_hash),
    )

    assert result.status == "BLOCKED"
    assert "V18_ACCEPTANCE_INVALID" in result.blockers


def test_preflight_immutable_replay_and_conflict(tmp_path: Path) -> None:
    result = _ready_preparation()
    path = tmp_path / "preflight.json"

    first = write_immutable_enrollment_preflight(
        path,
        result.preflight_artifact,
    )
    second = write_immutable_enrollment_preflight(
        path,
        result.preflight_artifact,
    )
    assert first == second

    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["databaseWritesExecuted"] = 1
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(
        ProspectiveEnrollmentAdapterError,
        match="IMMUTABLE_PROSPECTIVE_ENROLLMENT_PREFLIGHT_CONFLICT",
    ):
        write_immutable_enrollment_preflight(
            path,
            result.preflight_artifact,
        )


def test_checked_in_preflight_matches_repository_current_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        enrollment_adapter,
        "verify_forward_dqv_v19_acceptance",
        verify_forward_dqv_v19_acceptance,
    )
    fixture = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    expected = prepare_prospective_enrollment_v22(
        repository_root=REPOSITORY_ROOT,
        successor_readiness=None,
        decision_snapshot=fixture,
        benchmark_manifest=None,
        v18_acceptance=_v18_acceptance(),
        v19_chronology_acceptance=_v19_acceptance(),
        persistence_binding=None,
    )
    checked_in = json.loads(
        (
            REPOSITORY_ROOT
            / "docs/generated/"
            "prospective-enrollment-adapter-v2-2-v19-preflight-v2.json"
        ).read_text(encoding="utf-8")
    )

    assert checked_in == expected.preflight_artifact
    assert checked_in["status"] == "BLOCKED"
    assert checked_in["securityCount"] == 66
    assert checked_in["populationTerminalCounts"] == {
        "ASSESSED": 0,
        "MISSING": 55,
        "STALE": 0,
        "INVALID": 0,
        "EXCLUDED": 9,
        "ABSTAINED": 2,
    }
    assert checked_in["databaseWritesExecuted"] == 0
    assert checked_in["enrollmentExecuted"] is False
