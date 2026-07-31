from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.v19_acceptance_v2 import (
    FORWARD_DQV_V19_ACCEPTANCE_VERSION,
    verify_forward_dqv_v19_acceptance_v2,
)

FORWARD_DQV_V20_ACTIVATION_ACCEPTANCE = (
    "FORWARD-DQV-V20-ACTIVATION-ACCEPTANCE-v1.0.0"
)
PROSPECTIVE_ENROLLMENT_PREFLIGHT_V20 = (
    "PROSPECTIVE-ENROLLMENT-PREFLIGHT-v2.2.1"
)
POST_CLOSE_PIPELINE_PREFLIGHT_V20 = (
    "POST-CLOSE-PIPELINE-PREFLIGHT-v2.2.1"
)
DETERMINISTIC_OUTPUT_PREFLIGHT_V20 = (
    "POST-FREEZE-DETERMINISTIC-DECISION-OUTPUT-PREFLIGHT-v2.2.1"
)

V20_ACCEPTANCE_PATH = Path(
    "docs/generated/forward-dqv-v20-activation-acceptance-v1.json"
)
V19_ACCEPTANCE_V2_PATH = Path(
    "docs/generated/forward-dqv-v19-chronology-acceptance-v2.json"
)
LEGACY_ENROLLMENT_PREFLIGHT_PATH = Path(
    "docs/generated/prospective-enrollment-adapter-v2-2-v19-preflight-v2.json"
)
PRICE_PREFLIGHT_PATH = Path(
    "docs/generated/future-price-history-final-preexecution-preflight-v2-1.json"
)
TERMINAL_MODEL_LABELS_PATH = Path(
    "docs/generated/model-validation-terminal-closeout-v1.json"
)
HUMAN_POLICY_PATH = Path(
    "docs/generated/forward-human-decision-governance-policy-v1.json"
)

_SOURCE_PATHS = {
    "v20Migration": Path(
        "database/migrations/V20__create_forward_dqv_benchmark_outcome_v3.sql"
    ),
    "v20DatabaseAcceptance": Path(
        "database/tests/forward_dqv_v20_acceptance.sql"
    ),
    "benchmarkLedgerContract": Path(
        "analysis-python/src/equity_analysis/forward_validation/"
        "benchmark_controlled_ledger_v22.py"
    ),
    "decisionControlledComposite": Path(
        "analysis-python/src/equity_analysis/forward_validation/"
        "decision_controlled_composite_v22.py"
    ),
    "benchmarkPersistence": Path(
        "analysis-python/src/equity_analysis/forward_validation/"
        "benchmark_outcome_persistence_v3.py"
    ),
    "humanDecisionGovernance": Path(
        "analysis-python/src/equity_analysis/forward_validation/"
        "human_decision_governance_v1.py"
    ),
    "governancePersistence": Path(
        "analysis-python/src/equity_analysis/forward_validation/"
        "governance_persistence_v3.py"
    ),
    "controlledCompositeTests": Path(
        "analysis-python/tests/test_decision_controlled_composite_v22.py"
    ),
    "typedBenchmarkPersistenceTests": Path(
        "analysis-python/tests/test_benchmark_outcome_persistence_v3.py"
    ),
    "postgresql17TypedRoundTripTests": Path(
        "analysis-python/tests/test_benchmark_outcome_postgres_v20.py"
    ),
}


class ProspectiveActivationV20Error(ValueError):
    pass


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_canonical_artifact(path: Path) -> dict[str, Any]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    claim = artifact.get("artifactContentHash")
    body = {
        key: value
        for key, value in artifact.items()
        if key != "artifactContentHash"
    }
    if not isinstance(claim, str) or canonical_hash(body) != claim:
        raise ProspectiveActivationV20Error(
            f"Canonical artifact verification failed: {path}"
        )
    return artifact


def _source_bindings(repository_root: Path) -> dict[str, dict[str, str]]:
    return {
        name: {
            "path": relative.as_posix(),
            "fileSha256": file_sha256(repository_root / relative),
        }
        for name, relative in _SOURCE_PATHS.items()
    }


def build_v20_activation_acceptance(
    repository_root: Path,
    *,
    focused_python_tests_passed: int,
    postgresql17_acceptance_passed: int,
) -> dict[str, Any]:
    if focused_python_tests_passed < 1 or postgresql17_acceptance_passed < 1:
        raise ValueError("Acceptance test counts must be positive")
    _validate_source_contracts(repository_root)
    v19 = load_canonical_artifact(repository_root / V19_ACCEPTANCE_V2_PATH)
    verify_forward_dqv_v19_acceptance_v2(v19, repository_root)
    human_policy = load_canonical_artifact(repository_root / HUMAN_POLICY_PATH)
    sources = _source_bindings(repository_root)
    body: dict[str, Any] = {
        "artifactType": "FORWARD_DQV_V20_ACTIVATION_ACCEPTANCE",
        "schemaVersion": FORWARD_DQV_V20_ACTIVATION_ACCEPTANCE,
        "effectiveDate": "2026-07-30",
        "status": "INFRASTRUCTURE_READY",
        "migrationVersion": 20,
        "acceptedEnrollmentContract": "FORWARD-DQV-ENROLLMENT-v2.1.1",
        "chronologyAcceptance": {
            "path": V19_ACCEPTANCE_V2_PATH.as_posix(),
            "schemaVersion": FORWARD_DQV_V19_ACCEPTANCE_VERSION,
            "artifactContentHash": v19["artifactContentHash"],
            "fileSha256": file_sha256(
                repository_root / V19_ACCEPTANCE_V2_PATH
            ),
        },
        "sourceFiles": sources,
        "sourceContractHash": canonical_hash(sources),
        "infrastructure": {
            "postgresql17AppendOnlySuccessorSchema": "READY",
            "typedBenchmarkPersistence": "READY",
            "sixFamilyControlledLedgerContract": "READY",
            "decisionControlledCompositeHashChain": "READY",
            "perSecurityDatedSectorBinding": "READY",
            "holdingLevelNonlinearCostEvidence": "READY",
            "humanDecisionAppendOnlySidecar": "READY",
            "portfolioSuitabilityBoundary": "READY",
        },
        "humanAndPortfolioGovernance": {
            "policyPath": HUMAN_POLICY_PATH.as_posix(),
            "policyArtifactContentHash": human_policy["artifactContentHash"],
            "policyFileSha256": file_sha256(
                repository_root / HUMAN_POLICY_PATH
            ),
            "humanDecisionMayMutateModelOutput": False,
            "humanDecisionMayMutateEvidenceLabel": False,
            "portfolioSuitabilityState": "NOT_ASSESSED_BY_MODEL",
            "portfolioWeightsIncluded": False,
            "tradeDecisionIncluded": False,
            "automaticTradingAuthorized": False,
        },
        "postgresql17Acceptance": {
            "status": "PASS",
            "cleanAndUpgradePaths": [
                "V1_TO_V20",
                "V18_TO_V20",
                "V19_TO_V20",
            ],
            "legacyV19RefusalPreserved": True,
            "passed": postgresql17_acceptance_passed,
        },
        "testAcceptance": {
            "focusedPython": {
                "status": "PASS",
                "passed": focused_python_tests_passed,
            },
            "fullRepositorySuite": "PENDING_FINAL_CLOSEOUT",
        },
        "realExecutionState": {
            "controlledBenchmarkLedger": "NOT_EXECUTED",
            "decisionControlledComposite": "NOT_EXECUTED",
            "modelScoring": "NOT_EXECUTED",
            "prospectiveEnrollment": "NOT_EXECUTED",
            "maturityOutcomes": "NOT_AVAILABLE",
            "naturallyMaturedOutcomes": "NOT_AVAILABLE",
        },
        "executionBoundary": _execution_boundary(),
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def verify_v20_activation_acceptance(
    repository_root: Path,
    artifact: dict[str, Any],
) -> str:
    _validate_source_contracts(repository_root)
    claim = artifact.get("artifactContentHash")
    body = {
        key: value
        for key, value in artifact.items()
        if key != "artifactContentHash"
    }
    if not isinstance(claim, str) or canonical_hash(body) != claim:
        raise ProspectiveActivationV20Error("V20_ACTIVATION_HASH_MISMATCH")
    if (
        artifact.get("schemaVersion")
        != FORWARD_DQV_V20_ACTIVATION_ACCEPTANCE
        or artifact.get("status") != "INFRASTRUCTURE_READY"
        or artifact.get("migrationVersion") != 20
        or artifact.get("sourceFiles") != _source_bindings(repository_root)
    ):
        raise ProspectiveActivationV20Error("V20_ACTIVATION_STATE_INVALID")
    if artifact.get("sourceContractHash") != canonical_hash(
        artifact["sourceFiles"]
    ):
        raise ProspectiveActivationV20Error(
            "V20_ACTIVATION_SOURCE_HASH_MISMATCH"
        )
    if set(artifact["infrastructure"].values()) != {"READY"}:
        raise ProspectiveActivationV20Error(
            "V20_ACTIVATION_INFRASTRUCTURE_INCOMPLETE"
        )
    if artifact["realExecutionState"] != {
        "controlledBenchmarkLedger": "NOT_EXECUTED",
        "decisionControlledComposite": "NOT_EXECUTED",
        "modelScoring": "NOT_EXECUTED",
        "prospectiveEnrollment": "NOT_EXECUTED",
        "maturityOutcomes": "NOT_AVAILABLE",
        "naturallyMaturedOutcomes": "NOT_AVAILABLE",
    }:
        raise ProspectiveActivationV20Error(
            "V20_ACTIVATION_EXECUTION_CLAIM_INVALID"
        )
    return claim


def build_prospective_enrollment_preflight_v20(
    repository_root: Path,
    *,
    activation: dict[str, Any],
) -> dict[str, Any]:
    activation_hash = verify_v20_activation_acceptance(
        repository_root,
        activation,
    )
    legacy = load_canonical_artifact(
        repository_root / LEGACY_ENROLLMENT_PREFLIGHT_PATH
    )
    labels = _terminal_label_binding(repository_root)
    blockers = [
        "EXPLICIT_ENROLLMENT_NOT_AUTHORIZED",
        "PRODUCTION_66_MODEL_INPUT_EVIDENCE_MISSING",
        "REAL_CONTROLLED_BENCHMARK_LEDGER_MISSING",
        "REAL_PROSPECTIVE_DECISION_SNAPSHOT_MISSING",
        "SUCCESSOR_READINESS_MISSING",
    ]
    body: dict[str, Any] = {
        "artifactType": "PROSPECTIVE_ENROLLMENT_ADAPTER_PREFLIGHT",
        "schemaVersion": PROSPECTIVE_ENROLLMENT_PREFLIGHT_V20,
        "status": "BLOCKED_BY_TIME_OR_EVIDENCE",
        "blockedReasons": blockers,
        "securityCount": 66,
        "requiredBenchmarkFamilies": [
            "SPY",
            "SECTOR",
            "EQUAL_WEIGHT",
            "PURE_MOMENTUM",
            "PURE_VALUE",
            "PURE_QUALITY",
        ],
        "v20ActivationAcceptanceHash": activation_hash,
        "legacyPreflightSuperseded": {
            "path": LEGACY_ENROLLMENT_PREFLIGHT_PATH.as_posix(),
            "artifactContentHash": legacy["artifactContentHash"],
            "fileSha256": file_sha256(
                repository_root / LEGACY_ENROLLMENT_PREFLIGHT_PATH
            ),
            "reason": "V20_SUCCESSOR_SCHEMA_AND_CURRENT_SOURCE_BINDINGS",
        },
        "infrastructureState": "READY",
        "realControlledBenchmarkLedgerState": "NOT_EXECUTED",
        "realDecisionControlledCompositeState": "NOT_EXECUTED",
        "realEnrollmentState": "NOT_EXECUTED",
        "modelEvidenceLabels": labels,
        "executionBoundary": _execution_boundary(),
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def build_post_close_preflight_v20(
    repository_root: Path,
    *,
    activation: dict[str, Any],
) -> dict[str, Any]:
    activation_hash = verify_v20_activation_acceptance(
        repository_root,
        activation,
    )
    price = load_canonical_artifact(repository_root / PRICE_PREFLIGHT_PATH)
    body: dict[str, Any] = {
        "artifactType": "POST_CLOSE_PIPELINE_PREFLIGHT",
        "schemaVersion": POST_CLOSE_PIPELINE_PREFLIGHT_V20,
        "status": "BLOCKED",
        "blockedReasons": [
            "PRODUCTION_66_MODEL_INPUT_EVIDENCE_MISSING",
            "REAL_CONTROLLED_BENCHMARK_LEDGER_MISSING",
            "TARGET_SESSION_NOT_COMPLETED",
        ],
        "targetSession": price.get("targetSession"),
        "latestCompletedSession": price.get("latestCompletedSession"),
        "v20ActivationAcceptanceHash": activation_hash,
        "infrastructure": {
            "completedSessionCapture": "READY_AWAITING_TIME",
            "sixBenchmarkControlledLedger": "READY_AWAITING_REAL_EVIDENCE",
            "decisionControlledComposite": "READY_AWAITING_REAL_EVIDENCE",
            "modelInputAssembly": "READY_AWAITING_REAL_EVIDENCE",
            "frozenModelExecution": "READY_NOT_EXECUTED",
            "prospectiveEnrollment": "READY_REQUIRES_EXPLICIT_AUTHORIZATION",
            "humanDecisionSidecar": "READY_NOT_EXECUTED",
            "portfolioSuitabilityBoundary": "READY_NOT_EXECUTED",
        },
        "supersededImplementationBlocker": {
            "code": (
                "CONTROLLED_BENCHMARK_CONSTITUENT_LEDGER_NOT_IMPLEMENTED"
            ),
            "state": "RESOLVED_BY_V20_CONTRACT_AND_TYPED_PERSISTENCE",
            "mayProveRealLedgerExists": False,
        },
        "sourceBindings": {
            "pricePreflight": {
                "path": PRICE_PREFLIGHT_PATH.as_posix(),
                "artifactContentHash": price["artifactContentHash"],
                "fileSha256": file_sha256(
                    repository_root / PRICE_PREFLIGHT_PATH
                ),
            },
            "v20ActivationAcceptance": {
                "path": V20_ACCEPTANCE_PATH.as_posix(),
                "artifactContentHash": activation_hash,
                "fileSha256": file_sha256(
                    repository_root / V20_ACCEPTANCE_PATH
                ),
            },
        },
        "modelEvidenceLabels": _terminal_label_binding(repository_root),
        "executionBoundary": _execution_boundary(),
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def build_deterministic_output_preflight_v20(
    repository_root: Path,
    *,
    activation: dict[str, Any],
) -> dict[str, Any]:
    activation_hash = verify_v20_activation_acceptance(
        repository_root,
        activation,
    )
    body: dict[str, Any] = {
        "artifactType": "POST_FREEZE_DETERMINISTIC_DECISION_OUTPUT_PREFLIGHT",
        "schemaVersion": DETERMINISTIC_OUTPUT_PREFLIGHT_V20,
        "status": "BLOCKED",
        "blockers": [
            "REAL_66_CLASSIFICATION_BINDINGS_NOT_AVAILABLE",
            "REAL_CONTROLLED_BENCHMARK_LEDGER_MISSING",
            "REAL_POST_FREEZE_MODEL_EXECUTION_NOT_AVAILABLE",
        ],
        "controlledLedgerInfrastructureState": "READY",
        "decisionControlledCompositeInfrastructureState": "READY",
        "v20ActivationAcceptanceHash": activation_hash,
        "realScoresComputed": False,
        "executionBoundary": _execution_boundary(),
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_immutable_artifact(path: Path, artifact: dict[str, Any]) -> str:
    claim = artifact.get("artifactContentHash")
    body = {
        key: value
        for key, value in artifact.items()
        if key != "artifactContentHash"
    }
    if not isinstance(claim, str) or canonical_hash(body) != claim:
        raise ProspectiveActivationV20Error("ARTIFACT_HASH_MISMATCH")
    encoded = (
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=True)
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise ProspectiveActivationV20Error(
                f"IMMUTABLE_ARTIFACT_CONFLICT:{path}"
            )
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _terminal_label_binding(repository_root: Path) -> dict[str, Any]:
    path = repository_root / TERMINAL_MODEL_LABELS_PATH
    artifact = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": TERMINAL_MODEL_LABELS_PATH.as_posix(),
        "fileSha256": file_sha256(path),
        "declaredArtifactContentHash": artifact["artifactContentHash"],
        "terminalConclusion": artifact["terminalConclusion"],
        "unchangedByActivation": True,
    }


def _execution_boundary() -> dict[str, Any]:
    return {
        "providerNetworkRequests": 0,
        "databaseReads": 0,
        "businessDatabaseWrites": 0,
        "scoresOrRanksComputed": False,
        "enrollmentExecuted": False,
        "outcomesComputed": False,
        "maturityExecuted": False,
        "commitCreated": False,
        "pushExecuted": False,
        "deploymentExecuted": False,
    }


def _validate_source_contracts(repository_root: Path) -> None:
    required_markers = {
        _SOURCE_PATHS["v20Migration"]: (
            "analytics.forward_dqv_benchmark_ledger_v3",
            "analytics.forward_dqv_benchmark_variant_v3",
            "analytics.forward_dqv_benchmark_holding_v3",
            "analytics.forward_dqv_security_benchmark_binding_v3",
            "analytics.forward_dqv_benchmark_holding_outcome_v3",
            "analytics.forward_dqv_human_decision_record_v3",
            "analytics.forward_dqv_portfolio_suitability_boundary_v3",
            "reject_forward_append_only_change",
        ),
        _SOURCE_PATHS["benchmarkLedgerContract"]: (
            "class ControlledBenchmarkLedgerSetV22",
            "class ControlledBenchmarkVariantV22",
            "class ControlledBenchmarkHoldingV22",
            "build_controlled_benchmark_ledger_set_v22",
        ),
        _SOURCE_PATHS["decisionControlledComposite"]: (
            "class DecisionControlledCompositeV22",
            "build_decision_controlled_composite_v22",
            "load_decision_controlled_composite_v22",
        ),
        _SOURCE_PATHS["benchmarkPersistence"]: (
            "class ForwardDqvBenchmarkOutcomeRepositoryV3",
            "class SecurityBenchmarkBindingV3",
            "class HoldingOutcomeV3",
            "class VariantOutcomeV3",
        ),
        _SOURCE_PATHS["governancePersistence"]: (
            "class ForwardDqvGovernanceRepositoryV3",
            "persist_human_record",
            "persist_portfolio_boundary",
        ),
        _SOURCE_PATHS["controlledCompositeTests"]: (
            "test_controlled_ledger_retains_sector_variants_and_selection_chronology",
            "test_composite_loader_rejects_nested_payload_tampering",
        ),
        _SOURCE_PATHS["typedBenchmarkPersistenceTests"]: (
            "test_v20_migration_preserves_v18_v19_and_declares_rich_successor",
            "test_family_aggregation_contract_separates_sector",
        ),
        _SOURCE_PATHS["postgresql17TypedRoundTripTests"]: (
            "test_v20_typed_repository_round_trip",
        ),
    }
    for relative, markers in required_markers.items():
        text = (repository_root / relative).read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in text]
        if missing:
            raise ProspectiveActivationV20Error(
                f"V20_SOURCE_CONTRACT_MARKER_MISSING:{relative}:{missing}"
            )
