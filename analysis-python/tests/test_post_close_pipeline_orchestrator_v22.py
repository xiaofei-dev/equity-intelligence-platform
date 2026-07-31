from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.post_close_pipeline_orchestrator_v22 import (
    CHRONOLOGY_ACCEPTANCE_V19,
    ImmutableStageResumeV22,
    PostClosePipelineCommandsV22,
    PostClosePipelineError,
    PostClosePipelineRequestV22,
    PostCloseStage,
    StageTerminalStatus,
    _enrollment_adapter_readiness_projection,
    build_current_post_close_preflight_v22,
    evaluate_successor_readiness_v221,
    load_completed_immutable_stage_v22,
    run_post_close_pipeline_v22,
    write_immutable_post_close_artifact_v22,
)
from equity_analysis.forward_validation.post_freeze_decision_snapshot_v22 import (
    EXPECTED_BENCHMARK_KINDS,
    POST_FREEZE_AI_BOUNDARY_V22,
    POST_FREEZE_BENCHMARK_EVIDENCE_V22,
    POST_FREEZE_DECISION_INPUT_V22,
    POST_FREEZE_PRICE_EVIDENCE_V22,
    AiNarrativeBoundaryV22,
    ArtifactPurpose,
    BenchmarkEvidenceV22,
    BenchmarkTerminalState,
    CompletedSessionPriceEvidenceV22,
    PostFreezeSecurityDecisionV22,
    assemble_post_freeze_decision_snapshot_v22,
    build_post_freeze_contract_fixture_v22,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> dict[str, Any]:
    return json.loads(
        (
            REPOSITORY_ROOT / "docs/generated" / name
        ).read_text(encoding="utf-8")
    )


def _frozen() -> dict[str, dict[str, Any]]:
    return {
        "parent_preregistration": _load("forward-dqv-preregistration-v2.json"),
        "benchmark_preregistration": _load(
            "forward-benchmark-preregistration-v2-2.json"
        ),
        "preregistration_seal": _load(
            "forward-preregistration-seal-v2-2.json"
        ),
        "external_reference_universe": _load(
            "forward-benchmark-external-reference-universe-v2-2.json"
        ),
        "input_capture": _load("forward-benchmark-input-capture-v2-2.json"),
        "input_coverage": _load("forward-benchmark-input-coverage-v2-2.json"),
        "candidate_construction": _load(
            "forward-benchmark-candidate-construction-v2-2.json"
        ),
    }


def _sealed(body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "artifactContentHash": canonical_hash(body)}


def _future(*, status: str = "READY") -> dict[str, Any]:
    frozen = _frozen()
    body = {
        "artifactType": "FUTURE_COMPLETED_SESSION_PRICE_HISTORY_CAPTURE",
        "schemaVersion": "FUTURE-PRICE-HISTORY-CAPTURE-v2.0.0",
        "status": status,
        "targetSession": "2026-07-30",
        "preregistrationSealHash": frozen["preregistration_seal"][
            "sealContentHash"
        ],
        "externalReferenceUniverseHash": frozen[
            "external_reference_universe"
        ]["artifactContentHash"],
        "calendarEvidenceHash": canonical_hash({"fixture": "calendar"}),
        "controlledManifestContentHash": canonical_hash(
            {"fixture": "controlled-price"}
        ),
        "priceSymbolCount": 67,
        "readySymbolCount": 67,
        "providerRetryLimit": 0,
        "physicalHttpAttempts": 69,
        "symbols": [
            {
                "symbol": f"S{index:02d}",
                "receiptHash": canonical_hash({"receipt": index}),
            }
            for index in range(67)
        ],
        "rawProviderValuesIncluded": False,
        "scoresOrRanksIncluded": False,
    }
    return _sealed(body)


def _benchmark(price_hash: str) -> dict[str, Any]:
    frozen = _frozen()
    body = {
        "artifactType": "FORWARD_BENCHMARK_CONSTRUCTION_MANIFEST",
        "schemaVersion": "FORWARD-BENCHMARK-MANIFEST-v2.2.0",
        "status": "READY",
        "completedSession": "2026-07-30",
        "preregistrationSealHash": frozen["preregistration_seal"][
            "sealContentHash"
        ],
        "futurePriceExecutionHash": price_hash,
        "inputCaptureHash": frozen["input_capture"]["artifactContentHash"],
        "inputCoverageHash": frozen["input_coverage"]["artifactContentHash"],
        "candidateConstructionHash": frozen["candidate_construction"][
            "artifactContentHash"
        ],
        "families": [
            {
                "kind": kind,
                "state": "AVAILABLE",
                "evidenceHash": canonical_hash({"benchmark": kind}),
                "terminalHash": canonical_hash({"terminal": kind}),
            }
            for kind in EXPECTED_BENCHMARK_KINDS
        ],
        "requiredKinds": list(EXPECTED_BENCHMARK_KINDS),
        "allSixAvailable": True,
        "providerNetworkRequestsExecuted": 0,
        "databaseWritesExecuted": 0,
        "rawProviderValuesIncluded": False,
    }
    return _sealed(body)


def _chronology() -> dict[str, Any]:
    return _sealed(
        {
            "artifactType": "FORWARD_DQV_V19_CHRONOLOGY_ACCEPTANCE",
            "schemaVersion": CHRONOLOGY_ACCEPTANCE_V19,
            "status": "READY",
            "migrationVersion": 19,
            "chronologyConstraintValidated": True,
            "legacyEnrollmentAdapterReady": False,
            "prospectiveEnrollmentAdapterV211Ready": True,
            "databaseWritesExecuted": 0,
        }
    )


def _rows_with_price_hash(
    *,
    price_evidence_hash: str,
) -> tuple[PostFreezeSecurityDecisionV22, ...]:
    fixture = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    rows = []
    for row in fixture.decisions:
        payload = row.model_dump(mode="json", by_alias=True)
        payload["priceEvidenceHash"] = price_evidence_hash
        payload.pop("rowHash")
        payload["rowHash"] = canonical_hash(payload)
        rows.append(PostFreezeSecurityDecisionV22.model_validate(payload))
    return tuple(rows)


def _snapshot(
    *,
    benchmark_manifest: dict[str, Any],
    future: dict[str, Any],
    rows: tuple[Any, ...],
) -> Any:
    fixture = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    price_hash = future["artifactContentHash"]
    price_evidence = CompletedSessionPriceEvidenceV22(
        schema_version=POST_FREEZE_PRICE_EVIDENCE_V22,
        completed_session=fixture.completed_session,
        completed_at=datetime(2026, 7, 30, 22, tzinfo=UTC),
        evidence_hash=rows[0].price_evidence_hash,
        action_adjustment_binding_hash=canonical_hash(
            {"fixture": "action-adjustment"}
        ),
        source_hashes=(
            price_hash,
            str(future["calendarEvidenceHash"]),
            str(future["controlledManifestContentHash"]),
        ),
    )
    benchmark_hash = benchmark_manifest["artifactContentHash"]
    benchmarks = tuple(
        BenchmarkEvidenceV22(
            schema_version=POST_FREEZE_BENCHMARK_EVIDENCE_V22,
            benchmark_kind=kind,
            terminal_state=BenchmarkTerminalState.AVAILABLE,
            completed_session=fixture.completed_session,
            contract_hash=canonical_hash({"contract": kind}),
            source_binding_hash=benchmark_hash,
            evidence_hash=canonical_hash({"evidence": kind}),
        )
        for kind in EXPECTED_BENCHMARK_KINDS
    )
    return assemble_post_freeze_decision_snapshot_v22(
        repository_root=REPOSITORY_ROOT,
        purpose=ArtifactPurpose.PROSPECTIVE_DECISION,
        source_input_contract_version=POST_FREEZE_DECISION_INPUT_V22,
        decision_cutoff=fixture.decision_cutoff,
        completed_session_price_evidence=price_evidence,
        model_freezes=fixture.model_freezes,
        benchmark_evidence=benchmarks,
        cost_policy_hash=fixture.cost_policy_hash,
        sector_classification_hash=fixture.sector_classification_hash,
        source_snapshot_hash=fixture.source_snapshot_hash,
        decisions=rows,
        ai_narrative=AiNarrativeBoundaryV22(
            schema_version=POST_FREEZE_AI_BOUNDARY_V22,
            status="NOT_EXECUTED",
            may_affect_deterministic_fields=False,
        ),
    )


@dataclass
class _BenchmarkResult:
    git_safe_manifest: dict[str, Any]


class _FakeV19Adapter:
    def __init__(self) -> None:
        self.persist_calls = 0

    def prepare(self, **kwargs: Any) -> dict[str, Any]:
        snapshot = kwargs["decision_snapshot"]
        return {
            "schemaVersion": "PROSPECTIVE-ENROLLMENT-PREPARATION-v2.1.1",
            "status": "READY_FOR_PERSISTENCE",
            "securityCount": snapshot.population_count,
            "horizons": [5, 20, 60, 126, 252],
            "chronologyAcceptanceHash": kwargs[
                "chronology_acceptance"
            ]["artifactContentHash"],
        }

    def persist(self, preparation: Any, *, repository: Any) -> str:
        self.persist_calls += 1
        return repository.persist(preparation)


def _ready_request(
    *,
    execute_enrollment: bool = False,
    repository: Any | None = None,
    adapter: _FakeV19Adapter | None = None,
) -> PostClosePipelineRequestV22:
    future = _future()
    benchmark = _benchmark(future["artifactContentHash"])
    price_evidence_hash = canonical_hash({"fixture": "price-evidence"})
    rows = _rows_with_price_hash(price_evidence_hash=price_evidence_hash)
    return PostClosePipelineRequestV22(
        repository_root=REPOSITORY_ROOT,
        frozen_artifacts=_frozen(),
        future_price_execution=future,
        v18_acceptance=_load("forward-dqv-v18-acceptance-v1.json"),
        chronology_v19_acceptance=_chronology(),
        commands=PostClosePipelineCommandsV22(
            construct_benchmarks=lambda: _BenchmarkResult(benchmark),
            execute_frozen_models=lambda: rows,
            assemble_decision_snapshot=lambda manifest, values: _snapshot(
                benchmark_manifest=manifest,
                future=future,
                rows=values,
            ),
        ),
        enrollment_adapter=adapter or _FakeV19Adapter(),
        enrollment_repository=repository,
        execute_enrollment=execute_enrollment,
    )


def test_current_preflight_is_blocked_without_side_effects() -> None:
    artifact = build_current_post_close_preflight_v22(
        repository_root=REPOSITORY_ROOT
    )

    assert artifact["status"] == "BLOCKED"
    assert "TARGET_SESSION_NOT_COMPLETED" in artifact["blockedReasons"]
    assert (
        "ENROLLMENT_CHRONOLOGY_V19_ACCEPTANCE_MISSING"
        not in artifact["blockedReasons"]
    )
    assert (
        "PRODUCTION_66_MODEL_INPUT_EVIDENCE_MISSING"
        in artifact["blockedReasons"]
    )
    assert artifact["providerNetworkRequestsExecuted"] == 0
    assert artifact["databaseWritesExecuted"] == 0
    assert artifact["scoresOrRanksComputed"] is False
    assert artifact["enrollmentExecuted"] is False
    assert (
        artifact["futureLiveCaptureCommandMayBeInvokedByOrchestrator"]
        is False
    )


def test_checked_in_preflight_v3_matches_repository_state() -> None:
    expected = build_current_post_close_preflight_v22(
        repository_root=REPOSITORY_ROOT
    )
    checked_in = json.loads(
        (
            REPOSITORY_ROOT
            / "docs/generated/"
            "post-close-pipeline-orchestrator-v2-2-preflight-v3.json"
        ).read_text(encoding="utf-8")
    )

    assert checked_in == expected
    body = dict(checked_in)
    claim = body.pop("artifactContentHash")
    assert canonical_hash(body) == claim

    legacy_v2 = json.loads(
        (
            REPOSITORY_ROOT
            / "docs/generated/"
            "post-close-pipeline-orchestrator-v2-2-preflight-v2.json"
        ).read_text(encoding="utf-8")
    )
    legacy_body = dict(legacy_v2)
    legacy_claim = legacy_body.pop("artifactContentHash")
    assert canonical_hash(legacy_body) == legacy_claim
    assert legacy_v2 != checked_in


def test_fixture_runs_all_stages_ready_without_database_write() -> None:
    result = run_post_close_pipeline_v22(_ready_request())

    assert result.status == "READY"
    assert result.blockers == ()
    assert tuple(item.stage for item in result.stage_receipts) == tuple(
        PostCloseStage
    )
    assert all(
        item.status == StageTerminalStatus.COMPLETED
        for item in result.stage_receipts
    )
    assert result.decision_snapshot is not None
    assert len(result.decision_snapshot.decisions) == 66
    assert result.decision_snapshot.purpose == ArtifactPurpose.PROSPECTIVE_DECISION
    assert result.readiness is not None
    assert result.readiness["status"] == "READY"
    assert (
        result.readiness["postFreezeDecisionManifestHash"]
        == result.decision_snapshot.manifest_content_hash
    )

    adapter_readiness = _enrollment_adapter_readiness_projection(
        result.readiness
    )
    assert (
        adapter_readiness["schemaVersion"]
        == "PROSPECTIVE-READINESS-CONTROLLER-v2.2.0"
    )
    assert (
        adapter_readiness["postFreezeDecisionManifestHash"]
        == result.decision_snapshot.manifest_content_hash
    )
    adapter_body = dict(adapter_readiness)
    adapter_claim = adapter_body.pop("artifactContentHash")
    assert canonical_hash(adapter_body) == adapter_claim
    assert result.artifact["databaseWritesExecuted"] == 0
    assert result.artifact["providerNetworkRequestsExecutedByOrchestrator"] == 0


def test_unknown_price_capture_stops_every_downstream_stage() -> None:
    request = _ready_request()
    request = PostClosePipelineRequestV22(
        **{
            **request.__dict__,
            "future_price_execution": {"status": "UNKNOWN"},
        }
    )
    result = run_post_close_pipeline_v22(request)

    assert result.status == "BLOCKED"
    assert result.stage_receipts[0].status == StageTerminalStatus.UNKNOWN
    assert all(
        item.status == StageTerminalStatus.NOT_EXECUTED
        for item in result.stage_receipts[1:]
    )


def test_explicit_enrollment_requires_repository() -> None:
    result = run_post_close_pipeline_v22(
        _ready_request(execute_enrollment=True)
    )

    assert result.status == "BLOCKED"
    assert "EXPLICIT_ENROLLMENT_REPOSITORY_REQUIRED" in result.blockers
    assert result.enrollment_receipt is None
    assert result.artifact["databaseWritesExecuted"] == 0


def test_explicit_enrollment_calls_only_injected_fake_repository() -> None:
    class Repository:
        calls = 0

        def persist(self, preparation: Any) -> str:
            self.calls += 1
            return "fixture-enrollment-receipt"

    repository = Repository()
    adapter = _FakeV19Adapter()
    result = run_post_close_pipeline_v22(
        _ready_request(
            execute_enrollment=True,
            repository=repository,
            adapter=adapter,
        )
    )

    assert result.status == "READY"
    assert result.enrollment_receipt == "fixture-enrollment-receipt"
    assert repository.calls == 1
    assert adapter.persist_calls == 1
    assert result.artifact["databaseWritesExecuted"] == 1


def test_v221_readiness_rejects_changed_row_hash() -> None:
    request = _ready_request()
    benchmark = request.commands.construct_benchmarks()
    rows = request.commands.execute_frozen_models()
    snapshot = request.commands.assemble_decision_snapshot(
        benchmark.git_safe_manifest,
        rows,
    )
    payload = snapshot.model_dump(mode="json", by_alias=True)
    payload["decisions"][0]["rowHash"] = canonical_hash({"changed": True})

    with pytest.raises(ValueError):
        type(snapshot).model_validate(payload)


def test_v221_controller_binds_controlled_snapshot_not_projection() -> None:
    request = _ready_request()
    benchmark = request.commands.construct_benchmarks()
    rows = request.commands.execute_frozen_models()
    snapshot = request.commands.assemble_decision_snapshot(
        benchmark.git_safe_manifest,
        rows,
    )
    result = evaluate_successor_readiness_v221(
        frozen_artifacts=request.frozen_artifacts,
        future_price_execution=request.future_price_execution,
        benchmark_manifest=benchmark.git_safe_manifest,
        decision_snapshot=snapshot,
        v18_acceptance=request.v18_acceptance,
        chronology_v19_acceptance=request.chronology_v19_acceptance,
    )

    assert result["status"] == "READY"
    assert result["postFreezeDecisionManifestHash"] == (
        snapshot.manifest_content_hash
    )
    assert result["controllerCompatibilityProjectionHash"] != (
        snapshot.manifest_content_hash
    )


def test_immutable_preflight_replay_and_conflict(tmp_path: Path) -> None:
    artifact = build_current_post_close_preflight_v22(
        repository_root=REPOSITORY_ROOT
    )
    path = tmp_path / "preflight.json"

    first = write_immutable_post_close_artifact_v22(path, artifact)
    second = write_immutable_post_close_artifact_v22(path, artifact)
    assert first == second

    path.write_text("{}", encoding="utf-8")
    with pytest.raises(
        PostClosePipelineError,
        match="IMMUTABLE_POST_CLOSE_ARTIFACT_CONFLICT",
    ):
        write_immutable_post_close_artifact_v22(path, artifact)


def test_resume_accepts_only_completed_byte_identical_stage(
    tmp_path: Path,
) -> None:
    body = {
        "artifactType": "FORWARD_BENCHMARK_CONSTRUCTION_MANIFEST",
        "schemaVersion": "FORWARD-BENCHMARK-MANIFEST-v2.2.0",
        "status": "READY",
        "sourceBindingHashes": [canonical_hash({"source": "price"})],
    }
    payload = _sealed(body)
    path = tmp_path / "benchmark.json"
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode()
    path.write_bytes(encoded)
    binding = ImmutableStageResumeV22(
        stage=PostCloseStage.SIX_BENCHMARK_CONSTRUCTION,
        path=path,
        expected_file_sha256="sha256:" + hashlib.sha256(encoded).hexdigest(),
        expected_artifact_content_hash=payload["artifactContentHash"],
    )

    resumed = load_completed_immutable_stage_v22(binding)
    assert resumed.receipt.status == StageTerminalStatus.COMPLETED
    assert resumed.receipt.resumed_from_immutable_artifact is True

    changed = dict(payload)
    changed["status"] = "UNKNOWN"
    changed = _sealed(
        {key: value for key, value in changed.items() if key != "artifactContentHash"}
    )
    unknown_path = tmp_path / "unknown.json"
    unknown_encoded = (
        json.dumps(changed, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode()
    unknown_path.write_bytes(unknown_encoded)
    unknown_binding = ImmutableStageResumeV22(
        stage=PostCloseStage.SIX_BENCHMARK_CONSTRUCTION,
        path=unknown_path,
        expected_file_sha256=(
            "sha256:" + hashlib.sha256(unknown_encoded).hexdigest()
        ),
        expected_artifact_content_hash=changed["artifactContentHash"],
    )
    with pytest.raises(
        PostClosePipelineError,
        match="RESUME_UNKNOWN_STAGE_PROHIBITED",
    ):
        load_completed_immutable_stage_v22(unknown_binding)
