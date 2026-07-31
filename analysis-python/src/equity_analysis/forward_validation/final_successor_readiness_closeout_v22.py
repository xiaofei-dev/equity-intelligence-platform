from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.prospective_readiness_controller_v22 import (
    evaluate_successor_readiness_v22,
)
from equity_analysis.forward_validation.v18_acceptance_v1 import (
    load_and_verify_forward_dqv_v18_acceptance,
)

FINAL_SUCCESSOR_READINESS_CLOSEOUT_V2 = (
    "FORWARD-V2.2-FINAL-SUCCESSOR-READINESS-CLOSEOUT-v1.1.0"
)
FINAL_V18_ACCEPTANCE_HASH = (
    "sha256:e5ce27f66981d8341ed0d88f33fc72d380999b3d68360d53ce83f908f51a5f1e"
)
EXPECTED_BLOCKERS = (
    "COMPLETED_SESSION_PRICE_EVIDENCE_MISSING",
    "POST_FREEZE_DECISION_MANIFEST_MISSING",
    "SIX_BENCHMARK_CONSTRUCTION_MISSING",
)

_PARENT_PREREGISTRATION = "forward-dqv-preregistration-v2.json"
_BENCHMARK_PREREGISTRATION = "forward-benchmark-preregistration-v2-2.json"
_PREREGISTRATION_SEAL = "forward-preregistration-seal-v2-2.json"
_EXTERNAL_REFERENCE_UNIVERSE = (
    "forward-benchmark-external-reference-universe-v2-2.json"
)
_INPUT_CAPTURE = "forward-benchmark-input-capture-v2-2.json"
_INPUT_COVERAGE = "forward-benchmark-input-coverage-v2-2.json"
_CANDIDATE_CONSTRUCTION = (
    "forward-benchmark-candidate-construction-v2-2.json"
)
_POST_FREEZE_CONTRACT_FIXTURE = (
    "post-freeze-decision-snapshot-v2-2-contract-fixture.json"
)
_MODEL_EXECUTION_PREFLIGHT = (
    "post-freeze-model-execution-v2-2-preflight-v2.json"
)
_ENROLLMENT_ADAPTER_PREFLIGHT = (
    "prospective-enrollment-adapter-v2-2-preflight.json"
)
_V18_ACCEPTANCE = "forward-dqv-v18-acceptance-v1.json"


class FinalSuccessorReadinessCloseoutError(RuntimeError):
    pass


def build_final_successor_readiness_closeout_v1(
    repository_root: Path,
) -> dict[str, Any]:
    generated_root = repository_root / "docs" / "generated"

    def load(name: str) -> dict[str, Any]:
        return _load_json(generated_root / name)

    v18_acceptance, v18_hash = load_and_verify_forward_dqv_v18_acceptance(
        generated_root / _V18_ACCEPTANCE,
        repository_root,
    )
    if v18_hash != FINAL_V18_ACCEPTANCE_HASH:
        raise FinalSuccessorReadinessCloseoutError(
            "FINAL_V18_ACCEPTANCE_HASH_MISMATCH"
        )

    candidate_construction = load(_CANDIDATE_CONSTRUCTION)
    post_freeze_fixture = load(_POST_FREEZE_CONTRACT_FIXTURE)
    model_execution_preflight = load(_MODEL_EXECUTION_PREFLIGHT)
    enrollment_adapter_preflight = load(_ENROLLMENT_ADAPTER_PREFLIGHT)

    successor_readiness = evaluate_successor_readiness_v22(
        parent_preregistration=load(_PARENT_PREREGISTRATION),
        benchmark_preregistration=load(_BENCHMARK_PREREGISTRATION),
        preregistration_seal=load(_PREREGISTRATION_SEAL),
        external_reference_universe=load(_EXTERNAL_REFERENCE_UNIVERSE),
        input_capture=load(_INPUT_CAPTURE),
        input_coverage=load(_INPUT_COVERAGE),
        candidate_construction=candidate_construction,
        future_price_execution=None,
        benchmark_manifest=None,
        post_freeze_decision_manifest=None,
        v18_acceptance=v18_acceptance,
    )
    if (
        successor_readiness.get("status") != "BLOCKED"
        or tuple(successor_readiness.get("blockedReasons") or ())
        != EXPECTED_BLOCKERS
        or successor_readiness.get("v18AcceptanceHash") != v18_hash
    ):
        raise FinalSuccessorReadinessCloseoutError(
            "FINAL_SUCCESSOR_READINESS_STATE_UNEXPECTED"
        )

    bindings = {
        "v18Acceptance": _verified_binding(
            generated_root / _V18_ACCEPTANCE,
            v18_acceptance,
        ),
        "benchmarkContract": _verified_binding(
            generated_root / _CANDIDATE_CONSTRUCTION,
            candidate_construction,
        ),
        "postFreezeDecisionContract": _verified_binding(
            generated_root / _POST_FREEZE_CONTRACT_FIXTURE,
            post_freeze_fixture,
        ),
        "modelExecutionPreflight": _verified_binding(
            generated_root / _MODEL_EXECUTION_PREFLIGHT,
            model_execution_preflight,
        ),
        "prospectiveEnrollmentAdapterPreflight": _verified_binding(
            generated_root / _ENROLLMENT_ADAPTER_PREFLIGHT,
            enrollment_adapter_preflight,
        ),
    }
    _verify_contract_states(
        v18_acceptance=v18_acceptance,
        post_freeze_fixture=post_freeze_fixture,
        candidate_construction=candidate_construction,
        model_execution_preflight=model_execution_preflight,
        enrollment_adapter_preflight=enrollment_adapter_preflight,
    )

    body: dict[str, Any] = {
        "artifactType": "FORWARD_V2_2_FINAL_SUCCESSOR_READINESS_CLOSEOUT",
        "schemaVersion": FINAL_SUCCESSOR_READINESS_CLOSEOUT_V2,
        "effectiveDate": "2026-07-29",
        "status": "BLOCKED",
        "blockedReasons": list(EXPECTED_BLOCKERS),
        "successorReadiness": successor_readiness,
        "sourceBindings": bindings,
        "requiredNextEvidence": {
            "completedSessionPriceEvidence": {
                "state": "MISSING",
                "requiredArtifactType": (
                    "FUTURE_COMPLETED_SESSION_PRICE_HISTORY_CAPTURE"
                ),
                "requiredSchemaVersion": (
                    "FUTURE-PRICE-HISTORY-CAPTURE-v2.0.0"
                ),
            },
            "sixBenchmarkManifest": {
                "state": "MISSING",
                "requiredSchemaVersion": (
                    "FORWARD-BENCHMARK-MANIFEST-v2.2.0"
                ),
                "requiredAvailableKinds": [
                    "SPY",
                    "SECTOR",
                    "EQUAL_WEIGHT",
                    "PURE_MOMENTUM",
                    "PURE_VALUE",
                    "PURE_QUALITY",
                ],
            },
            "prospectivePostFreezeDecision": {
                "state": "MISSING",
                "requiredPurpose": "PROSPECTIVE_DECISION",
                "requiredSchemaVersion": (
                    "FORWARD-DECISION-SNAPSHOT-v2.2.0"
                ),
                "requiredPopulationCount": 66,
            },
        },
        "contractState": {
            "v18Implementation": "READY_NOT_ENROLLED",
            "benchmarkCandidateConstruction": (
                "READY_PRICE_LIQUIDITY_COST_AND_REFERENCE_EVIDENCE_PENDING"
            ),
            "postFreezeDecisionContractFixture": (
                "BLOCKED_CONTRACT_FIXTURE_NOT_PROSPECTIVE"
            ),
            "modelExecutionPreflight": "BLOCKED_NO_EXECUTION",
            "prospectiveEnrollmentAdapter": "BLOCKED_NO_EXECUTION",
        },
        "supersession": {
            "newArtifactOnly": True,
            "intermediateArtifactsOverwritten": False,
            "preservedIntermediatePaths": [
                (
                    "docs/generated/"
                    "forward-v2-2-successor-readiness-closeout.json"
                ),
                (
                    "docs/generated/"
                    "forward-v2-2-successor-readiness-v18-closeout.json"
                ),
                (
                    "docs/generated/"
                    "forward-v2-2-final-successor-readiness-closeout-v1.json"
                ),
            ],
            "supersededModelPreflightPath": (
                "docs/generated/"
                "post-freeze-model-execution-v2-2-preflight.json"
            ),
            "portableModelPreflightPath": (
                "docs/generated/"
                "post-freeze-model-execution-v2-2-preflight-v2.json"
            ),
        },
        "executionBoundary": {
            "providerNetworkRequests": 0,
            "databaseReads": 0,
            "databaseWrites": 0,
            "scoresOrRanksComputed": False,
            "enrollmentExecuted": False,
            "outcomesComputed": False,
            "commitCreated": False,
            "pushExecuted": False,
            "deploymentExecuted": False,
            "aiUsedForDeterministicFields": False,
            "automaticTradingAuthorized": False,
            "rawProviderValuesIncluded": False,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_immutable_final_successor_readiness_closeout(
    path: Path,
    artifact: dict[str, Any],
) -> str:
    claim = artifact.get("artifactContentHash")
    body = dict(artifact)
    body.pop("artifactContentHash", None)
    if canonical_hash(body) != claim:
        raise FinalSuccessorReadinessCloseoutError(
            "FINAL_CLOSEOUT_CANONICAL_HASH_MISMATCH"
        )
    encoded = (
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise FinalSuccessorReadinessCloseoutError(
                "IMMUTABLE_FINAL_CLOSEOUT_CONFLICT"
            )
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _verify_contract_states(
    *,
    v18_acceptance: dict[str, Any],
    post_freeze_fixture: dict[str, Any],
    candidate_construction: dict[str, Any],
    model_execution_preflight: dict[str, Any],
    enrollment_adapter_preflight: dict[str, Any],
) -> None:
    if (
        v18_acceptance.get("status") != "READY"
        or v18_acceptance.get("enrollmentStatus") != "NOT_EXECUTED"
        or v18_acceptance.get("executionBoundary", {}).get(
            "enrollmentExecuted"
        )
        is not False
    ):
        raise FinalSuccessorReadinessCloseoutError(
            "FINAL_V18_ACCEPTANCE_STATE_INVALID"
        )
    if (
        post_freeze_fixture.get("purpose") != "CONTRACT_FIXTURE"
        or post_freeze_fixture.get("status") != "BLOCKED_CONTRACT_FIXTURE"
        or post_freeze_fixture.get("populationCount") != 66
        or post_freeze_fixture.get("enrollmentAuthorized") is not False
        or post_freeze_fixture.get("scoresOrRanksComputed") is not False
    ):
        raise FinalSuccessorReadinessCloseoutError(
            "POST_FREEZE_CONTRACT_FIXTURE_STATE_INVALID"
        )
    if (
        candidate_construction.get("fullBenchmarkConstructionStatus")
        != "PRICE_LIQUIDITY_COST_AND_EXTERNAL_REFERENCE_EVIDENCE_PENDING"
        or candidate_construction.get("enrollmentExecuted") is not False
    ):
        raise FinalSuccessorReadinessCloseoutError(
            "BENCHMARK_CONTRACT_STATE_INVALID"
        )
    if (
        model_execution_preflight.get("status") != "BLOCKED"
        or model_execution_preflight.get("realManifestGenerated") is not False
        or model_execution_preflight.get("decisionRowsGenerated") != 0
        or model_execution_preflight.get("scoresOrRanksComputed") is not False
        or model_execution_preflight.get("providerNetworkRequests") != 0
        or model_execution_preflight.get("databaseWrites") != 0
    ):
        raise FinalSuccessorReadinessCloseoutError(
            "MODEL_EXECUTION_PREFLIGHT_STATE_INVALID"
        )
    if (
        enrollment_adapter_preflight.get("status") != "BLOCKED"
        or enrollment_adapter_preflight.get("enrollmentExecuted") is not False
        or enrollment_adapter_preflight.get("providerNetworkRequestsExecuted")
        != 0
        or enrollment_adapter_preflight.get("databaseWritesExecuted") != 0
        or enrollment_adapter_preflight.get("v18AcceptanceHash")
        != FINAL_V18_ACCEPTANCE_HASH
    ):
        raise FinalSuccessorReadinessCloseoutError(
            "ENROLLMENT_ADAPTER_PREFLIGHT_STATE_INVALID"
        )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _verified_binding(
    path: Path,
    artifact: dict[str, Any],
) -> dict[str, str]:
    claim = artifact.get("artifactContentHash")
    if not isinstance(claim, str):
        raise FinalSuccessorReadinessCloseoutError(
            "SOURCE_ARTIFACT_CANONICAL_HASH_MISSING"
        )
    body = dict(artifact)
    body.pop("artifactContentHash", None)
    if canonical_hash(body) != claim:
        raise FinalSuccessorReadinessCloseoutError(
            "SOURCE_ARTIFACT_CANONICAL_HASH_MISMATCH"
        )
    return {
        "path": path.relative_to(path.parents[2]).as_posix(),
        "fileSha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        "artifactContentHash": claim,
    }
