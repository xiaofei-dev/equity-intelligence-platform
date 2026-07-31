from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_construction_v22 import (
    BenchmarkConstructionResultV22,
)
from equity_analysis.forward_validation.deterministic_decision_output_v22 import (
    DeterministicDecisionOutputSetV22,
)
from equity_analysis.forward_validation.post_freeze_decision_snapshot_v22 import (
    ArtifactPurpose,
    BenchmarkTerminalState,
    PostFreezeDecisionSnapshotV22,
)
from equity_analysis.forward_validation.post_freeze_model_execution_v22 import (
    PostFreezeModelExecutionResultV22,
)
from equity_analysis.forward_validation.prospective_enrollment_adapter_v22 import (
    EnrollmentPersistenceBindingV22,
    ProspectiveEnrollmentPreparationV22,
    persist_prepared_enrollment_v22,
    prepare_prospective_enrollment_v22,
)
from equity_analysis.forward_validation.prospective_readiness_controller_v22 import (
    PROSPECTIVE_READINESS_CONTROLLER_V22,
    evaluate_successor_readiness_v22,
)

POST_CLOSE_PIPELINE_ORCHESTRATOR_V22 = "POST-CLOSE-PIPELINE-ORCHESTRATOR-v2.2.0"
POST_CLOSE_PIPELINE_READINESS_V221 = "PROSPECTIVE-READINESS-CONTROLLER-v2.2.1"
POST_CLOSE_PIPELINE_PREFLIGHT_V22 = "POST-CLOSE-PIPELINE-PREFLIGHT-v2.2.1"
CHRONOLOGY_ACCEPTANCE_V19 = "FORWARD-DQV-V19-CHRONOLOGY-ACCEPTANCE-v1.0.0"
EXPECTED_BENCHMARK_KINDS = frozenset(
    {
        "SPY",
        "SECTOR",
        "EQUAL_WEIGHT",
        "PURE_MOMENTUM",
        "PURE_VALUE",
        "PURE_QUALITY",
    }
)
EXPECTED_ROLE_COUNTS = {
    "PRIMARY": 48,
    "RESERVE": 7,
    "REFERENCE_ONLY": 2,
    "EXCLUDED": 9,
}


class PostClosePipelineError(RuntimeError):
    pass


class PostCloseStage(StrEnum):
    PRICE_CAPTURE_VERIFICATION = "PRICE_CAPTURE_VERIFICATION"
    SIX_BENCHMARK_CONSTRUCTION = "SIX_BENCHMARK_CONSTRUCTION"
    FROZEN_MODEL_EXECUTION = "FROZEN_MODEL_EXECUTION"
    POST_FREEZE_DECISION_SNAPSHOT = "POST_FREEZE_DECISION_SNAPSHOT"
    SUCCESSOR_READINESS = "SUCCESSOR_READINESS"
    PROSPECTIVE_ENROLLMENT = "PROSPECTIVE_ENROLLMENT"


class StageTerminalStatus(StrEnum):
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"
    NOT_EXECUTED = "NOT_EXECUTED"


@dataclass(frozen=True)
class StageReceiptV22:
    stage: PostCloseStage
    status: StageTerminalStatus
    artifact_content_hash: str | None
    source_binding_hashes: tuple[str, ...]
    reason_codes: tuple[str, ...]
    resumed_from_immutable_artifact: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "status": self.status.value,
            "artifactContentHash": self.artifact_content_hash,
            "sourceBindingHashes": list(self.source_binding_hashes),
            "reasonCodes": list(self.reason_codes),
            "resumedFromImmutableArtifact": (self.resumed_from_immutable_artifact),
        }


@dataclass(frozen=True)
class ImmutableStageResumeV22:
    stage: PostCloseStage
    path: Path
    expected_file_sha256: str
    expected_artifact_content_hash: str


@dataclass(frozen=True)
class VerifiedStageResumeV22:
    binding: ImmutableStageResumeV22
    payload: dict[str, Any]
    receipt: StageReceiptV22


class EnrollmentChronologyAdapterV221(Protocol):
    def prepare(
        self,
        *,
        readiness: dict[str, Any],
        decision_snapshot: PostFreezeDecisionSnapshotV22,
        benchmark_manifest: dict[str, Any],
        chronology_acceptance: dict[str, Any],
    ) -> Any:
        """Prepare, but do not persist, a V19 chronology-safe enrollment."""

    def persist(self, preparation: Any, *, repository: Any) -> str:
        """Persist one explicitly authorized prepared enrollment."""


@dataclass(frozen=True)
class ProductionEnrollmentChronologyAdapterV221:
    """Bind the orchestrator to the production V19/v2.1.1 adapter."""

    repository_root: Path
    v18_acceptance: dict[str, Any]
    persistence_binding: EnrollmentPersistenceBindingV22

    def prepare(
        self,
        *,
        readiness: dict[str, Any],
        decision_snapshot: PostFreezeDecisionSnapshotV22,
        benchmark_manifest: dict[str, Any],
        chronology_acceptance: dict[str, Any],
    ) -> ProspectiveEnrollmentPreparationV22:
        adapter_readiness = _enrollment_adapter_readiness_projection(readiness)
        preparation = prepare_prospective_enrollment_v22(
            repository_root=self.repository_root,
            successor_readiness=adapter_readiness,
            decision_snapshot=decision_snapshot,
            benchmark_manifest=benchmark_manifest,
            v18_acceptance=self.v18_acceptance,
            v19_chronology_acceptance=chronology_acceptance,
            persistence_binding=self.persistence_binding,
        )
        if preparation.status != "READY_FOR_PERSISTENCE":
            reason = (
                preparation.blockers[0]
                if preparation.blockers
                else "PROSPECTIVE_ENROLLMENT_PREFLIGHT_BLOCKED"
            )
            raise PostClosePipelineError(reason)
        return preparation

    def persist(
        self,
        preparation: ProspectiveEnrollmentPreparationV22,
        *,
        repository: Any,
    ) -> str:
        enrollment_id = persist_prepared_enrollment_v22(
            preparation,
            repository=repository,
            execute=True,
        )
        return str(enrollment_id)


@dataclass(frozen=True)
class PostClosePipelineCommandsV22:
    construct_benchmarks: Callable[[], BenchmarkConstructionResultV22] | None = None
    execute_frozen_models: (
        Callable[[], tuple[Any, ...] | PostFreezeModelExecutionResultV22] | None
    ) = None
    assemble_decision_snapshot: (
        Callable[
            [dict[str, Any], tuple[Any, ...]],
            PostFreezeDecisionSnapshotV22,
        ]
        | None
    ) = None


@dataclass(frozen=True)
class PostClosePipelineRequestV22:
    repository_root: Path
    frozen_artifacts: Mapping[str, dict[str, Any]]
    future_price_execution: dict[str, Any] | None
    v18_acceptance: dict[str, Any] | None
    chronology_v19_acceptance: dict[str, Any] | None
    commands: PostClosePipelineCommandsV22
    enrollment_adapter: EnrollmentChronologyAdapterV221 | None = None
    enrollment_repository: Any | None = None
    execute_enrollment: bool = False


@dataclass(frozen=True)
class PostClosePipelineResultV22:
    status: str
    blockers: tuple[str, ...]
    stage_receipts: tuple[StageReceiptV22, ...]
    artifact: dict[str, Any]
    benchmark_manifest: dict[str, Any] | None
    decision_snapshot: PostFreezeDecisionSnapshotV22 | None
    decision_outputs: DeterministicDecisionOutputSetV22 | None
    readiness: dict[str, Any] | None
    enrollment_receipt: str | None


def run_post_close_pipeline_v22(
    request: PostClosePipelineRequestV22,
) -> PostClosePipelineResultV22:
    """Run post-close stages only; this function has no provider transport."""

    receipts: list[StageReceiptV22] = []
    blockers: set[str] = set()
    benchmark_manifest: dict[str, Any] | None = None
    decision_snapshot: PostFreezeDecisionSnapshotV22 | None = None
    decision_outputs: DeterministicDecisionOutputSetV22 | None = None
    readiness: dict[str, Any] | None = None
    enrollment_receipt: str | None = None

    chronology_hash = _verify_chronology_acceptance(
        request.chronology_v19_acceptance,
        blockers,
    )
    price_hash, price_receipt = _verify_price_stage(request.future_price_execution)
    receipts.append(price_receipt)
    if price_receipt.status != StageTerminalStatus.COMPLETED:
        blockers.update(price_receipt.reason_codes)
        receipts.extend(_not_executed_after(PostCloseStage.PRICE_CAPTURE_VERIFICATION))
        return _result(
            request=request,
            blockers=blockers,
            receipts=receipts,
            chronology_hash=chronology_hash,
            benchmark_manifest=None,
            decision_snapshot=None,
            readiness=None,
            enrollment_receipt=None,
        )

    if request.commands.construct_benchmarks is None:
        blockers.add("SIX_BENCHMARK_CONSTRUCTION_COMMAND_MISSING")
        receipts.append(
            _blocked(
                PostCloseStage.SIX_BENCHMARK_CONSTRUCTION,
                "SIX_BENCHMARK_CONSTRUCTION_COMMAND_MISSING",
                price_hash,
            )
        )
        receipts.extend(_not_executed_after(PostCloseStage.SIX_BENCHMARK_CONSTRUCTION))
        return _result(
            request=request,
            blockers=blockers,
            receipts=receipts,
            chronology_hash=chronology_hash,
            benchmark_manifest=None,
            decision_snapshot=None,
            readiness=None,
            enrollment_receipt=None,
        )
    try:
        benchmark_result = request.commands.construct_benchmarks()
        benchmark_manifest = benchmark_result.git_safe_manifest
        benchmark_hash = _verify_benchmark_manifest(
            benchmark_manifest,
            price_hash=price_hash,
        )
    except Exception as error:
        code = _stage_error_code(error)
        blockers.add(code)
        receipts.append(
            _failed_receipt(
                PostCloseStage.SIX_BENCHMARK_CONSTRUCTION,
                code,
                price_hash,
            )
        )
        receipts.extend(_not_executed_after(PostCloseStage.SIX_BENCHMARK_CONSTRUCTION))
        return _result(
            request=request,
            blockers=blockers,
            receipts=receipts,
            chronology_hash=chronology_hash,
            benchmark_manifest=None,
            decision_snapshot=None,
            readiness=None,
            enrollment_receipt=None,
        )
    receipts.append(
        StageReceiptV22(
            stage=PostCloseStage.SIX_BENCHMARK_CONSTRUCTION,
            status=StageTerminalStatus.COMPLETED,
            artifact_content_hash=benchmark_hash,
            source_binding_hashes=(price_hash,),
            reason_codes=(),
        )
    )

    if request.commands.execute_frozen_models is None:
        blockers.add("FROZEN_MODEL_EXECUTION_COMMAND_MISSING")
        receipts.append(
            _blocked(
                PostCloseStage.FROZEN_MODEL_EXECUTION,
                "FROZEN_MODEL_EXECUTION_COMMAND_MISSING",
                benchmark_hash,
            )
        )
        receipts.extend(_not_executed_after(PostCloseStage.FROZEN_MODEL_EXECUTION))
        return _result(
            request=request,
            blockers=blockers,
            receipts=receipts,
            chronology_hash=chronology_hash,
            benchmark_manifest=benchmark_manifest,
            decision_snapshot=None,
            readiness=None,
            enrollment_receipt=None,
        )
    try:
        model_execution = request.commands.execute_frozen_models()
        if isinstance(model_execution, PostFreezeModelExecutionResultV22):
            model_rows = model_execution.rows
            decision_outputs = model_execution.decision_outputs
            model_hash = _verify_model_execution_result(model_execution)
        else:
            model_rows = model_execution
            model_hash = _verify_model_rows(model_rows)
    except Exception as error:
        code = _stage_error_code(error)
        blockers.add(code)
        receipts.append(
            _failed_receipt(
                PostCloseStage.FROZEN_MODEL_EXECUTION,
                code,
                benchmark_hash,
            )
        )
        receipts.extend(_not_executed_after(PostCloseStage.FROZEN_MODEL_EXECUTION))
        return _result(
            request=request,
            blockers=blockers,
            receipts=receipts,
            chronology_hash=chronology_hash,
            benchmark_manifest=benchmark_manifest,
            decision_snapshot=None,
            readiness=None,
            enrollment_receipt=None,
        )
    receipts.append(
        StageReceiptV22(
            stage=PostCloseStage.FROZEN_MODEL_EXECUTION,
            status=StageTerminalStatus.COMPLETED,
            artifact_content_hash=model_hash,
            source_binding_hashes=(price_hash, benchmark_hash),
            reason_codes=(),
        )
    )

    if request.commands.assemble_decision_snapshot is None:
        blockers.add("POST_FREEZE_DECISION_ASSEMBLER_MISSING")
        receipts.append(
            _blocked(
                PostCloseStage.POST_FREEZE_DECISION_SNAPSHOT,
                "POST_FREEZE_DECISION_ASSEMBLER_MISSING",
                model_hash,
            )
        )
        receipts.extend(_not_executed_after(PostCloseStage.POST_FREEZE_DECISION_SNAPSHOT))
        return _result(
            request=request,
            blockers=blockers,
            receipts=receipts,
            chronology_hash=chronology_hash,
            benchmark_manifest=benchmark_manifest,
            decision_snapshot=None,
            readiness=None,
            enrollment_receipt=None,
        )
    try:
        decision_snapshot = request.commands.assemble_decision_snapshot(
            benchmark_manifest,
            model_rows,
        )
        decision_hash = _verify_controlled_snapshot(
            decision_snapshot,
            parent=request.frozen_artifacts["parent_preregistration"],
            benchmark_hash=benchmark_hash,
            future_price_hash=price_hash,
        )
        if decision_outputs is not None:
            _verify_decision_output_snapshot_binding(
                decision_outputs,
                decision_snapshot,
            )
    except Exception as error:
        code = _stage_error_code(error)
        blockers.add(code)
        receipts.append(
            _failed_receipt(
                PostCloseStage.POST_FREEZE_DECISION_SNAPSHOT,
                code,
                model_hash,
            )
        )
        receipts.extend(_not_executed_after(PostCloseStage.POST_FREEZE_DECISION_SNAPSHOT))
        return _result(
            request=request,
            blockers=blockers,
            receipts=receipts,
            chronology_hash=chronology_hash,
            benchmark_manifest=benchmark_manifest,
            decision_snapshot=None,
            readiness=None,
            enrollment_receipt=None,
        )
    receipts.append(
        StageReceiptV22(
            stage=PostCloseStage.POST_FREEZE_DECISION_SNAPSHOT,
            status=StageTerminalStatus.COMPLETED,
            artifact_content_hash=decision_hash,
            source_binding_hashes=(price_hash, benchmark_hash, model_hash),
            reason_codes=(),
        )
    )

    try:
        readiness = evaluate_successor_readiness_v221(
            frozen_artifacts=request.frozen_artifacts,
            future_price_execution=request.future_price_execution,
            benchmark_manifest=benchmark_manifest,
            decision_snapshot=decision_snapshot,
            v18_acceptance=request.v18_acceptance,
            chronology_v19_acceptance=request.chronology_v19_acceptance,
        )
        readiness_hash = _verified_artifact_hash(readiness)
    except Exception as error:
        code = _stage_error_code(error)
        blockers.add(code)
        receipts.append(
            _failed_receipt(
                PostCloseStage.SUCCESSOR_READINESS,
                code,
                decision_hash,
            )
        )
        receipts.append(
            _not_executed(
                PostCloseStage.PROSPECTIVE_ENROLLMENT,
                "UPSTREAM_STAGE_NOT_COMPLETED",
            )
        )
        return _result(
            request=request,
            blockers=blockers,
            receipts=receipts,
            chronology_hash=chronology_hash,
            benchmark_manifest=benchmark_manifest,
            decision_snapshot=decision_snapshot,
            decision_outputs=decision_outputs,
            readiness=None,
            enrollment_receipt=None,
        )
    if readiness["status"] != "READY":
        blockers.update(readiness["blockedReasons"])
        receipts.append(
            StageReceiptV22(
                stage=PostCloseStage.SUCCESSOR_READINESS,
                status=StageTerminalStatus.BLOCKED,
                artifact_content_hash=readiness_hash,
                source_binding_hashes=(
                    price_hash,
                    benchmark_hash,
                    decision_hash,
                ),
                reason_codes=tuple(readiness["blockedReasons"]),
            )
        )
        receipts.append(
            _not_executed(
                PostCloseStage.PROSPECTIVE_ENROLLMENT,
                "SUCCESSOR_READINESS_NOT_READY",
            )
        )
        return _result(
            request=request,
            blockers=blockers,
            receipts=receipts,
            chronology_hash=chronology_hash,
            benchmark_manifest=benchmark_manifest,
            decision_snapshot=decision_snapshot,
            decision_outputs=decision_outputs,
            readiness=readiness,
            enrollment_receipt=None,
        )
    receipts.append(
        StageReceiptV22(
            stage=PostCloseStage.SUCCESSOR_READINESS,
            status=StageTerminalStatus.COMPLETED,
            artifact_content_hash=readiness_hash,
            source_binding_hashes=(price_hash, benchmark_hash, decision_hash),
            reason_codes=(),
        )
    )

    if request.enrollment_adapter is None:
        blockers.add("CHRONOLOGY_SAFE_ENROLLMENT_ADAPTER_MISSING")
        receipts.append(
            _blocked(
                PostCloseStage.PROSPECTIVE_ENROLLMENT,
                "CHRONOLOGY_SAFE_ENROLLMENT_ADAPTER_MISSING",
                readiness_hash,
            )
        )
    else:
        try:
            preparation = request.enrollment_adapter.prepare(
                readiness=readiness,
                decision_snapshot=decision_snapshot,
                benchmark_manifest=benchmark_manifest,
                chronology_acceptance=request.chronology_v19_acceptance or {},
            )
            preparation_artifact = (
                preparation.preflight_artifact
                if isinstance(
                    preparation,
                    ProspectiveEnrollmentPreparationV22,
                )
                else preparation
            )
            preparation_hash = (
                _verified_artifact_hash(preparation_artifact)
                if isinstance(preparation_artifact, dict)
                and "artifactContentHash" in preparation_artifact
                else canonical_hash(preparation_artifact)
            )
            if request.execute_enrollment:
                if request.enrollment_repository is None:
                    raise PostClosePipelineError("EXPLICIT_ENROLLMENT_REPOSITORY_REQUIRED")
                enrollment_receipt = request.enrollment_adapter.persist(
                    preparation,
                    repository=request.enrollment_repository,
                )
            receipts.append(
                StageReceiptV22(
                    stage=PostCloseStage.PROSPECTIVE_ENROLLMENT,
                    status=StageTerminalStatus.COMPLETED,
                    artifact_content_hash=preparation_hash,
                    source_binding_hashes=(
                        readiness_hash,
                        chronology_hash or "",
                    ),
                    reason_codes=(),
                )
            )
        except Exception as error:
            code = _stage_error_code(error)
            blockers.add(code)
            receipts.append(
                _failed_receipt(
                    PostCloseStage.PROSPECTIVE_ENROLLMENT,
                    code,
                    readiness_hash,
                )
            )

    return _result(
        request=request,
        blockers=blockers,
        receipts=receipts,
        chronology_hash=chronology_hash,
        benchmark_manifest=benchmark_manifest,
        decision_snapshot=decision_snapshot,
        decision_outputs=decision_outputs,
        readiness=readiness,
        enrollment_receipt=enrollment_receipt,
    )


def evaluate_successor_readiness_v221(
    *,
    frozen_artifacts: Mapping[str, dict[str, Any]],
    future_price_execution: dict[str, Any],
    benchmark_manifest: dict[str, Any],
    decision_snapshot: PostFreezeDecisionSnapshotV22,
    v18_acceptance: dict[str, Any] | None,
    chronology_v19_acceptance: dict[str, Any] | None,
) -> dict[str, Any]:
    """Versioned bridge from the controlled snapshot to legacy controller v2.2."""

    snapshot_hash = _verify_controlled_snapshot(
        decision_snapshot,
        parent=frozen_artifacts["parent_preregistration"],
        benchmark_hash=_verified_artifact_hash(benchmark_manifest),
        future_price_hash=_verified_artifact_hash(future_price_execution),
    )
    compatibility_manifest = _controller_compatibility_projection(
        decision_snapshot,
        benchmark_manifest_hash=_verified_artifact_hash(benchmark_manifest),
        future_price_execution_hash=_verified_artifact_hash(future_price_execution),
    )
    legacy = evaluate_successor_readiness_v22(
        parent_preregistration=frozen_artifacts["parent_preregistration"],
        benchmark_preregistration=frozen_artifacts["benchmark_preregistration"],
        preregistration_seal=frozen_artifacts["preregistration_seal"],
        external_reference_universe=frozen_artifacts["external_reference_universe"],
        input_capture=frozen_artifacts["input_capture"],
        input_coverage=frozen_artifacts["input_coverage"],
        candidate_construction=frozen_artifacts["candidate_construction"],
        future_price_execution=future_price_execution,
        benchmark_manifest=benchmark_manifest,
        post_freeze_decision_manifest=compatibility_manifest,
        v18_acceptance=v18_acceptance,
    )
    blockers = set(legacy["blockedReasons"])
    chronology_hash = _verify_chronology_acceptance(
        chronology_v19_acceptance,
        blockers,
    )
    body = {
        **{
            key: value
            for key, value in legacy.items()
            if key
            not in {
                "artifactContentHash",
                "schemaVersion",
                "status",
                "blockedReasons",
                "postFreezeDecisionManifestHash",
            }
        },
        "schemaVersion": POST_CLOSE_PIPELINE_READINESS_V221,
        "status": "READY" if not blockers else "BLOCKED",
        "blockedReasons": sorted(blockers),
        "legacyControllerArtifactContentHash": legacy["artifactContentHash"],
        "controlledPostFreezeDecisionSnapshotHash": snapshot_hash,
        "postFreezeDecisionManifestHash": snapshot_hash,
        "chronologyV19AcceptanceHash": chronology_hash,
        "controllerCompatibilityProjectionHash": (compatibility_manifest["artifactContentHash"]),
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def _enrollment_adapter_readiness_projection(
    readiness: dict[str, Any],
) -> dict[str, Any]:
    """Project v2.2.1 to the adapter's frozen v2.2 readiness contract."""

    if (
        readiness.get("schemaVersion") != POST_CLOSE_PIPELINE_READINESS_V221
        or readiness.get("status") != "READY"
        or readiness.get("blockedReasons") not in ([], ())
    ):
        raise PostClosePipelineError("SUCCESSOR_READINESS_V2_2_1_NOT_READY")
    _verified_artifact_hash(readiness)
    controlled_hash = readiness.get("controlledPostFreezeDecisionSnapshotHash")
    if (
        controlled_hash is None
        or readiness.get("postFreezeDecisionManifestHash") != controlled_hash
    ):
        raise PostClosePipelineError("SUCCESSOR_CONTROLLED_SNAPSHOT_BINDING_INVALID")
    body = {
        key: value
        for key, value in readiness.items()
        if key
        not in {
            "artifactContentHash",
            "schemaVersion",
            "legacyControllerArtifactContentHash",
            "controlledPostFreezeDecisionSnapshotHash",
            "chronologyV19AcceptanceHash",
            "controllerCompatibilityProjectionHash",
        }
    }
    body.update(
        {
            "schemaVersion": PROSPECTIVE_READINESS_CONTROLLER_V22,
            "postFreezeDecisionManifestHash": controlled_hash,
            "sourceReadinessV221Hash": readiness["artifactContentHash"],
        }
    )
    return {**body, "artifactContentHash": canonical_hash(body)}


def build_current_post_close_preflight_v22(
    *,
    repository_root: Path,
) -> dict[str, Any]:
    final_price_preflight = _load_verified(
        repository_root
        / "docs/generated/future-price-history-final-preexecution-preflight-v2-1.json"
    )
    final_readiness = _load_verified(
        repository_root / "docs/generated/forward-v2-2-final-successor-readiness-closeout-v2.json"
    )
    chronology_path = (
        repository_root / "docs/generated/forward-dqv-v19-chronology-acceptance-v1.json"
    )
    chronology_acceptance = _load_verified(chronology_path) if chronology_path.exists() else None
    blockers = set(final_price_preflight.get("blockedReasons") or ())
    chronology_hash = _verify_chronology_acceptance(
        chronology_acceptance,
        blockers,
    )
    blockers.add("PRODUCTION_66_MODEL_INPUT_EVIDENCE_MISSING")
    blockers.add("CONTROLLED_BENCHMARK_CONSTITUENT_LEDGER_NOT_IMPLEMENTED")
    stages = [
        StageReceiptV22(
            stage=PostCloseStage.PRICE_CAPTURE_VERIFICATION,
            status=StageTerminalStatus.BLOCKED,
            artifact_content_hash=None,
            source_binding_hashes=(final_price_preflight["artifactContentHash"],),
            reason_codes=tuple(sorted(final_price_preflight.get("blockedReasons") or ())),
        ),
        *_not_executed_after(PostCloseStage.PRICE_CAPTURE_VERIFICATION),
    ]
    body = {
        "artifactType": "POST_CLOSE_PIPELINE_PREFLIGHT",
        "schemaVersion": POST_CLOSE_PIPELINE_PREFLIGHT_V22,
        "orchestratorVersion": POST_CLOSE_PIPELINE_ORCHESTRATOR_V22,
        "readinessControllerVersion": POST_CLOSE_PIPELINE_READINESS_V221,
        "status": "BLOCKED",
        "blockedReasons": sorted(blockers),
        "targetSession": final_price_preflight.get("targetSession"),
        "latestCompletedSession": final_price_preflight.get("latestCompletedSession"),
        "stages": [item.as_dict() for item in stages],
        "sourceBindings": {
            "finalPricePreexecutionPreflight": {
                "path": (
                    "docs/generated/future-price-history-final-preexecution-preflight-v2-1.json"
                ),
                "artifactContentHash": final_price_preflight["artifactContentHash"],
            },
            "finalSuccessorReadinessCloseout": {
                "path": ("docs/generated/forward-v2-2-final-successor-readiness-closeout-v2.json"),
                "artifactContentHash": final_readiness["artifactContentHash"],
            },
            "v19ChronologyAcceptance": (
                {
                    "path": ("docs/generated/forward-dqv-v19-chronology-acceptance-v1.json"),
                    "artifactContentHash": chronology_hash,
                }
                if chronology_hash is not None
                else None
            ),
        },
        "productionStageBindings": {
            "priceCapture": {
                "state": "BLOCKED_TARGET_SESSION_NOT_COMPLETED",
                "networkEntryPoint": (
                    "equity_analysis.future_price_evidence.history_capture_cli_v2"
                ),
                "orchestratorMayInvoke": False,
            },
            "benchmarkConstruction": {
                "state": "IMPLEMENTED_AWAITING_COMPLETED_PRICE_CAPTURE",
                "callable": ("benchmark_construction_v22.build_benchmark_evidence_bundle_v22"),
            },
            "modelInputAssembly": {
                "state": "IMPLEMENTED_AWAITING_REAL_66_MEMBER_EVIDENCE",
                "callable": (
                    "post_close_model_input_assembly_v22.assemble_post_close_model_inputs_v22"
                ),
                "currentEvidenceArtifact": None,
            },
            "frozenModelExecution": {
                "state": "IMPLEMENTED_AWAITING_MODEL_INPUT_ASSEMBLY",
                "callable": ("post_freeze_model_execution_v22.execute_post_freeze_models_v22"),
            },
            "deterministicDecisionOutput": {
                "state": "IMPLEMENTED_AWAITING_REAL_FROZEN_MODEL_EXECUTION",
                "contract": ("deterministic_decision_output_v22.DeterministicDecisionOutputSetV22"),
                "controlledBenchmarkConstituentLedgerSetHash": "REQUIRED",
            },
            "decisionSnapshot": {
                "state": "IMPLEMENTED_AWAITING_UPSTREAM_STAGES",
                "callable": (
                    "post_freeze_decision_snapshot_v22.assemble_post_freeze_decision_snapshot_v22"
                ),
            },
            "successorReadiness": {
                "state": "IMPLEMENTED_V2_2_1_BRIDGE_AWAITING_UPSTREAM",
                "callable": "evaluate_successor_readiness_v221",
            },
            "prospectiveEnrollment": {
                "state": (
                    "IMPLEMENTED_V2_1_1_AWAITING_UPSTREAM_AND_EXPLICIT_EXECUTION"
                    if chronology_hash is not None
                    else "BLOCKED_V19_ACCEPTANCE_MISSING"
                ),
                "legacyV18OrV2_1_0ReadyAccepted": False,
                "v19ChronologyAcceptanceHash": chronology_hash,
                "explicitExecuteEnrollmentRequired": True,
            },
        },
        "futureLiveCaptureCommandMayBeInvokedByOrchestrator": False,
        "futureLiveCaptureRequiresExistingDedicatedCli": True,
        "providerNetworkRequestsExecuted": 0,
        "databaseReadsExecuted": 0,
        "databaseWritesExecuted": 0,
        "scoresOrRanksComputed": False,
        "enrollmentExecuted": False,
        "aiUsedForDeterministicFields": False,
        "automaticTradingAuthorized": False,
        "rawProviderValuesIncluded": False,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_immutable_post_close_artifact_v22(
    path: Path,
    artifact: dict[str, Any],
) -> str:
    _verified_artifact_hash(artifact)
    encoded = (json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise PostClosePipelineError("IMMUTABLE_POST_CLOSE_ARTIFACT_CONFLICT")
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def load_completed_immutable_stage_v22(
    binding: ImmutableStageResumeV22,
) -> VerifiedStageResumeV22:
    """Load only a canonical, byte-identical, terminal native stage artifact."""

    encoded = binding.path.read_bytes()
    file_hash = "sha256:" + hashlib.sha256(encoded).hexdigest()
    if file_hash != binding.expected_file_sha256:
        raise PostClosePipelineError("RESUME_FILE_SHA256_CONFLICT")
    payload = json.loads(encoded)
    artifact_hash = _verified_artifact_hash(payload)
    if artifact_hash != binding.expected_artifact_content_hash:
        raise PostClosePipelineError("RESUME_ARTIFACT_HASH_CONFLICT")
    status = str(payload.get("status") or "")
    if status == "UNKNOWN":
        raise PostClosePipelineError("RESUME_UNKNOWN_STAGE_PROHIBITED")
    accepted_types = {
        PostCloseStage.PRICE_CAPTURE_VERIFICATION: (
            "FUTURE_COMPLETED_SESSION_PRICE_HISTORY_CAPTURE",
            {"READY"},
        ),
        PostCloseStage.SIX_BENCHMARK_CONSTRUCTION: (
            "FORWARD_BENCHMARK_CONSTRUCTION_MANIFEST",
            {"READY"},
        ),
        PostCloseStage.FROZEN_MODEL_EXECUTION: (
            "POST_CLOSE_FROZEN_MODEL_EXECUTION",
            {"COMPLETED"},
        ),
        PostCloseStage.POST_FREEZE_DECISION_SNAPSHOT: (
            "POST_FREEZE_DECISION_SNAPSHOT_CONTROLLED",
            {"READY"},
        ),
        PostCloseStage.SUCCESSOR_READINESS: (
            "FORWARD_V2_2_SUCCESSOR_PROSPECTIVE_READINESS",
            {"READY"},
        ),
        PostCloseStage.PROSPECTIVE_ENROLLMENT: (
            "PROSPECTIVE_ENROLLMENT_PREPARATION",
            {"READY_FOR_PERSISTENCE"},
        ),
    }
    expected_type, accepted_status = accepted_types[binding.stage]
    if payload.get("artifactType") != expected_type or status not in accepted_status:
        raise PostClosePipelineError("RESUME_STAGE_NOT_COMPLETED")
    receipt = StageReceiptV22(
        stage=binding.stage,
        status=StageTerminalStatus.COMPLETED,
        artifact_content_hash=artifact_hash,
        source_binding_hashes=tuple(
            sorted(str(value) for value in payload.get("sourceBindingHashes") or ())
        ),
        reason_codes=(),
        resumed_from_immutable_artifact=True,
    )
    return VerifiedStageResumeV22(
        binding=binding,
        payload=payload,
        receipt=receipt,
    )


def _verify_price_stage(
    artifact: dict[str, Any] | None,
) -> tuple[str, StageReceiptV22]:
    if artifact is None:
        reason = "TARGET_SESSION_NOT_COMPLETED"
        return "", _blocked(
            PostCloseStage.PRICE_CAPTURE_VERIFICATION,
            reason,
        )
    state = str(artifact.get("status") or "")
    if state == "UNKNOWN":
        return "", StageReceiptV22(
            stage=PostCloseStage.PRICE_CAPTURE_VERIFICATION,
            status=StageTerminalStatus.UNKNOWN,
            artifact_content_hash=None,
            source_binding_hashes=(),
            reason_codes=("PRICE_CAPTURE_PHYSICAL_REQUEST_UNKNOWN",),
        )
    try:
        artifact_hash = _verified_artifact_hash(artifact)
    except Exception:
        return "", StageReceiptV22(
            stage=PostCloseStage.PRICE_CAPTURE_VERIFICATION,
            status=StageTerminalStatus.CONFLICT,
            artifact_content_hash=None,
            source_binding_hashes=(),
            reason_codes=("PRICE_CAPTURE_IMMUTABLE_ARTIFACT_CONFLICT",),
        )
    symbols = artifact.get("symbols") or []
    if (
        artifact.get("artifactType") != "FUTURE_COMPLETED_SESSION_PRICE_HISTORY_CAPTURE"
        or artifact.get("schemaVersion") != "FUTURE-PRICE-HISTORY-CAPTURE-v2.0.0"
        or state != "READY"
        or artifact.get("providerRetryLimit") != 0
        or artifact.get("priceSymbolCount") != 67
        or artifact.get("readySymbolCount") != 67
        or len(symbols) != 67
        or len({str(item.get("symbol")) for item in symbols}) != 67
        or artifact.get("physicalHttpAttempts", 70) > 69
    ):
        return artifact_hash, _blocked(
            PostCloseStage.PRICE_CAPTURE_VERIFICATION,
            "COMPLETED_SESSION_PRICE_EVIDENCE_INCOMPLETE",
            artifact_hash,
        )
    return artifact_hash, StageReceiptV22(
        stage=PostCloseStage.PRICE_CAPTURE_VERIFICATION,
        status=StageTerminalStatus.COMPLETED,
        artifact_content_hash=artifact_hash,
        source_binding_hashes=tuple(
            sorted(
                {
                    str(artifact.get("calendarEvidenceHash")),
                    str(artifact.get("controlledManifestContentHash")),
                }
            )
        ),
        reason_codes=(),
    )


def _verify_benchmark_manifest(
    artifact: dict[str, Any],
    *,
    price_hash: str,
) -> str:
    artifact_hash = _verified_artifact_hash(artifact)
    families = artifact.get("families") or []
    observed = {str(item.get("kind")) for item in families}
    available = {str(item.get("kind")) for item in families if item.get("state") == "AVAILABLE"}
    if (
        artifact.get("schemaVersion") != "FORWARD-BENCHMARK-MANIFEST-v2.2.0"
        or artifact.get("status") != "READY"
        or artifact.get("allSixAvailable") is not True
        or observed != EXPECTED_BENCHMARK_KINDS
        or available != EXPECTED_BENCHMARK_KINDS
        or artifact.get("futurePriceExecutionHash") != price_hash
    ):
        raise PostClosePipelineError("SIX_BENCHMARK_CONSTRUCTION_INCOMPLETE")
    return artifact_hash


def _verify_model_rows(rows: tuple[Any, ...]) -> str:
    if len(rows) != 66:
        raise PostClosePipelineError("MODEL_EXECUTION_MUST_RETURN_66_ROWS")
    payload = [
        (item.model_dump(mode="json", by_alias=True) if hasattr(item, "model_dump") else item)
        for item in rows
    ]
    ids = {str(item["publicSecurityId"]) for item in payload}
    if len(ids) != 66:
        raise PostClosePipelineError("MODEL_EXECUTION_STABLE_ID_COVERAGE_INVALID")
    for item in payload:
        body = dict(item)
        claim = body.pop("rowHash", None)
        if canonical_hash(body) != claim:
            raise PostClosePipelineError("MODEL_EXECUTION_ROW_HASH_INVALID")
    return canonical_hash(
        {
            "schemaVersion": "POST-CLOSE-MODEL-STAGE-v2.2.0",
            "rowHashes": sorted(str(item["rowHash"]) for item in payload),
        }
    )


def _verify_model_execution_result(
    result: PostFreezeModelExecutionResultV22,
) -> str:
    _verify_model_rows(result.rows)
    output_set = DeterministicDecisionOutputSetV22.model_validate(
        result.decision_outputs.model_dump(mode="json", by_alias=True)
    )
    row_hashes = [item.row_hash for item in result.rows]
    output_row_hashes = [item.post_freeze_row_hash for item in output_set.rows]
    if row_hashes != output_row_hashes:
        raise PostClosePipelineError("MODEL_EXECUTION_DECISION_OUTPUT_ROW_BINDING_MISMATCH")
    body = {
        "schemaVersion": "POST-FREEZE-MODEL-EXECUTION-v2.2.0",
        "decisionCutoff": output_set.decision_cutoff,
        "completedSession": output_set.completed_session,
        "rowHashes": row_hashes,
        "decisionOutputSetHash": output_set.output_set_content_hash,
        "scoresComputed": any(
            item.long_terminal_state.value == "ASSESSED"
            or any(state.value == "ASSESSED" for state in item.tactical_terminal_states.values())
            for item in output_set.rows
        ),
        "ranksComputed": False,
        "aiMayAffectDeterministicResult": False,
        "humanMayAffectDeterministicResult": False,
    }
    if canonical_hash(body) != result.execution_content_hash:
        raise PostClosePipelineError("MODEL_EXECUTION_CONTENT_HASH_INVALID")
    return result.execution_content_hash


def _verify_controlled_snapshot(
    snapshot: PostFreezeDecisionSnapshotV22,
    *,
    parent: dict[str, Any],
    benchmark_hash: str,
    future_price_hash: str,
) -> str:
    payload = snapshot.model_dump(mode="json", by_alias=True)
    body = dict(payload)
    claim = body.pop("manifestContentHash", None)
    if canonical_hash(body) != claim:
        raise PostClosePipelineError("CONTROLLED_SNAPSHOT_HASH_INVALID")
    reparsed = PostFreezeDecisionSnapshotV22.model_validate(payload)
    if reparsed.purpose != ArtifactPurpose.PROSPECTIVE_DECISION:
        raise PostClosePipelineError("CONTROLLED_SNAPSHOT_NOT_PROSPECTIVE")
    expected_ids = {
        str(item["publicSecurityId"]) for item in parent["prospectiveUniverse"]["securities"]
    }
    observed_ids = {str(item.public_security_id) for item in reparsed.decisions}
    if (
        len(observed_ids) != 66
        or observed_ids != expected_ids
        or reparsed.role_counts != EXPECTED_ROLE_COUNTS
    ):
        raise PostClosePipelineError("CONTROLLED_SNAPSHOT_66_POPULATION_INVALID")
    if any(
        item.source_binding_hash != benchmark_hash
        or item.terminal_state != BenchmarkTerminalState.AVAILABLE
        for item in reparsed.benchmark_evidence
    ):
        raise PostClosePipelineError("CONTROLLED_SNAPSHOT_BENCHMARK_BINDING_INVALID")
    if future_price_hash not in set(reparsed.completed_session_price_evidence.source_hashes):
        raise PostClosePipelineError("CONTROLLED_SNAPSHOT_PRICE_BINDING_INVALID")
    if reparsed.terminal_counts != _terminal_counts(reparsed):
        raise PostClosePipelineError("CONTROLLED_SNAPSHOT_TERMINAL_COUNTS_INVALID")
    return str(claim)


def _verify_decision_output_snapshot_binding(
    outputs: DeterministicDecisionOutputSetV22,
    snapshot: PostFreezeDecisionSnapshotV22,
) -> None:
    expected_model_freezes = {
        item.track: item.artifact_content_hash for item in snapshot.model_freezes
    }
    if (
        outputs.decision_cutoff != snapshot.decision_cutoff
        or outputs.completed_session != snapshot.completed_session
        or outputs.source_snapshot_hash != snapshot.source_snapshot_hash
        or outputs.population_identity_binding_hash != snapshot.population_identity_binding_hash
        or outputs.model_freeze_hashes != expected_model_freezes
    ):
        raise PostClosePipelineError("DECISION_OUTPUT_SNAPSHOT_ROOT_BINDING_MISMATCH")
    snapshot_rows = {item.public_security_id: item.row_hash for item in snapshot.decisions}
    output_rows = {item.public_security_id: item.post_freeze_row_hash for item in outputs.rows}
    if snapshot_rows != output_rows or len(snapshot_rows) != 66:
        raise PostClosePipelineError("DECISION_OUTPUT_SNAPSHOT_EXACT_66_BINDING_MISMATCH")
    assessed = any(
        item.long_terminal_state.value == "ASSESSED"
        or any(state.value == "ASSESSED" for state in item.tactical_terminal_states.values())
        for item in outputs.rows
    )
    if snapshot.scores_or_ranks_computed != assessed:
        raise PostClosePipelineError("DECISION_OUTPUT_SCORE_EXECUTION_STATE_MISMATCH")


def _controller_compatibility_projection(
    snapshot: PostFreezeDecisionSnapshotV22,
    *,
    benchmark_manifest_hash: str,
    future_price_execution_hash: str,
) -> dict[str, Any]:
    body = {
        "artifactType": "FORWARD_DECISION_SNAPSHOT",
        "schemaVersion": "FORWARD-DECISION-SNAPSHOT-v2.2.0",
        "dataSnapshotId": str(snapshot.source_snapshot_hash),
        "decisionAsOf": snapshot.decision_cutoff.isoformat(),
        "completedSession": snapshot.completed_session.isoformat(),
        "prospectiveReady": True,
        "futurePriceExecutionHash": future_price_execution_hash,
        "benchmarkManifestHash": benchmark_manifest_hash,
        "decisions": [
            {
                "publicSecurityId": str(item.public_security_id),
                "symbol": item.symbol,
                "rowHash": item.row_hash,
            }
            for item in snapshot.decisions
        ],
        "controlledSnapshotContentHash": snapshot.manifest_content_hash,
        "aiUsedForDeterministicFields": False,
        "aiUsedForDeterministicDecisions": False,
        "rawProviderValuesIncluded": False,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def _verify_chronology_acceptance(
    artifact: dict[str, Any] | None,
    blockers: set[str],
) -> str | None:
    if artifact is None:
        blockers.add("ENROLLMENT_CHRONOLOGY_V19_ACCEPTANCE_MISSING")
        return None
    try:
        artifact_hash = _verified_artifact_hash(artifact)
    except Exception:
        blockers.add("ENROLLMENT_CHRONOLOGY_V19_ACCEPTANCE_INVALID")
        return None
    if (
        artifact.get("schemaVersion") != CHRONOLOGY_ACCEPTANCE_V19
        or artifact.get("status") != "READY"
        or artifact.get("migrationVersion") != 19
        or artifact.get("chronologyConstraintValidated") is not True
        or artifact.get("legacyEnrollmentAdapterReady") is not False
        or artifact.get("prospectiveEnrollmentAdapterV211Ready") is not True
    ):
        blockers.add("ENROLLMENT_CHRONOLOGY_V19_ACCEPTANCE_INVALID")
        return None
    return artifact_hash


def _result(
    *,
    request: PostClosePipelineRequestV22,
    blockers: set[str],
    receipts: list[StageReceiptV22],
    chronology_hash: str | None,
    benchmark_manifest: dict[str, Any] | None,
    decision_snapshot: PostFreezeDecisionSnapshotV22 | None,
    readiness: dict[str, Any] | None,
    enrollment_receipt: str | None,
    decision_outputs: DeterministicDecisionOutputSetV22 | None = None,
) -> PostClosePipelineResultV22:
    status = "READY" if not blockers else "BLOCKED"
    body = {
        "artifactType": "POST_CLOSE_PIPELINE_RESULT",
        "schemaVersion": POST_CLOSE_PIPELINE_ORCHESTRATOR_V22,
        "status": status,
        "blockedReasons": sorted(blockers),
        "stages": [item.as_dict() for item in receipts],
        "chronologyV19AcceptanceHash": chronology_hash,
        "benchmarkManifestHash": (
            _verified_artifact_hash(benchmark_manifest) if benchmark_manifest is not None else None
        ),
        "controlledDecisionSnapshotHash": (
            decision_snapshot.manifest_content_hash if decision_snapshot is not None else None
        ),
        "deterministicDecisionOutputSetHash": (
            decision_outputs.output_set_content_hash if decision_outputs is not None else None
        ),
        "successorReadinessHash": (
            _verified_artifact_hash(readiness) if readiness is not None else None
        ),
        "enrollmentReceipt": enrollment_receipt,
        "executeEnrollmentRequested": request.execute_enrollment,
        "providerNetworkRequestsExecutedByOrchestrator": 0,
        "databaseWritesExecuted": 1 if enrollment_receipt is not None else 0,
        "scoresOrRanksComputedByOrchestrator": (
            decision_snapshot.scores_or_ranks_computed if decision_snapshot is not None else False
        ),
        "futureLiveCaptureCommandMayBeInvokedByOrchestrator": False,
        "aiUsedForDeterministicFields": False,
        "automaticTradingAuthorized": False,
        "rawProviderValuesIncluded": False,
    }
    artifact = {**body, "artifactContentHash": canonical_hash(body)}
    return PostClosePipelineResultV22(
        status=status,
        blockers=tuple(sorted(blockers)),
        stage_receipts=tuple(receipts),
        artifact=artifact,
        benchmark_manifest=benchmark_manifest,
        decision_snapshot=decision_snapshot,
        decision_outputs=decision_outputs,
        readiness=readiness,
        enrollment_receipt=enrollment_receipt,
    )


def _verified_artifact_hash(artifact: dict[str, Any]) -> str:
    for field in (
        "artifactContentHash",
        "manifestContentHash",
        "sealContentHash",
        "preregistrationContentHash",
    ):
        claim = artifact.get(field)
        if claim is None:
            continue
        body = {key: value for key, value in artifact.items() if key != field}
        if canonical_hash(body) != claim:
            raise PostClosePipelineError("CANONICAL_HASH_MISMATCH")
        return str(claim)
    raise PostClosePipelineError("CANONICAL_HASH_MISSING")


def _load_verified(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _verified_artifact_hash(payload)
    return payload


def _terminal_counts(
    snapshot: PostFreezeDecisionSnapshotV22,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in snapshot.decisions:
        for item in row.tactical_horizons:
            key = f"TACTICAL:{item.horizon.value}:{item.terminal_state.value}"
            counts[key] = counts.get(key, 0) + 1
        key = f"LONG_HORIZON:TWELVE_MONTHS_PLUS:{row.long_horizon.terminal_state.value}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _blocked(
    stage: PostCloseStage,
    reason: str,
    *source_hashes: str,
) -> StageReceiptV22:
    return StageReceiptV22(
        stage=stage,
        status=StageTerminalStatus.BLOCKED,
        artifact_content_hash=None,
        source_binding_hashes=tuple(item for item in source_hashes if item),
        reason_codes=(reason,),
    )


def _failed_receipt(
    stage: PostCloseStage,
    reason: str,
    *source_hashes: str,
) -> StageReceiptV22:
    status = (
        StageTerminalStatus.UNKNOWN
        if "UNKNOWN" in reason
        else StageTerminalStatus.CONFLICT
        if "CONFLICT" in reason or "HASH" in reason
        else StageTerminalStatus.BLOCKED
    )
    return StageReceiptV22(
        stage=stage,
        status=status,
        artifact_content_hash=None,
        source_binding_hashes=tuple(item for item in source_hashes if item),
        reason_codes=(reason,),
    )


def _not_executed(stage: PostCloseStage, reason: str) -> StageReceiptV22:
    return StageReceiptV22(
        stage=stage,
        status=StageTerminalStatus.NOT_EXECUTED,
        artifact_content_hash=None,
        source_binding_hashes=(),
        reason_codes=(reason,),
    )


def _not_executed_after(stage: PostCloseStage) -> list[StageReceiptV22]:
    ordered = list(PostCloseStage)
    return [
        _not_executed(item, "UPSTREAM_STAGE_NOT_COMPLETED")
        for item in ordered[ordered.index(stage) + 1 :]
    ]


def _stage_error_code(error: Exception) -> str:
    text = str(error).strip().upper().replace(" ", "_")
    if not text:
        text = type(error).__name__.upper()
    return text[:160]
