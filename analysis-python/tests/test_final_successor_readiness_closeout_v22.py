from __future__ import annotations

import json
from pathlib import Path

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.final_successor_readiness_closeout_v22 import (
    EXPECTED_BLOCKERS,
    FINAL_V18_ACCEPTANCE_HASH,
    FinalSuccessorReadinessCloseoutError,
    build_final_successor_readiness_closeout_v1,
    write_immutable_final_successor_readiness_closeout,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_repository_current_final_closeout_is_honestly_blocked() -> None:
    artifact = build_final_successor_readiness_closeout_v1(REPOSITORY_ROOT)

    assert artifact["status"] == "BLOCKED"
    assert tuple(artifact["blockedReasons"]) == EXPECTED_BLOCKERS
    assert (
        artifact["sourceBindings"]["v18Acceptance"]["artifactContentHash"]
        == FINAL_V18_ACCEPTANCE_HASH
    )
    assert artifact["successorReadiness"]["v18AcceptanceHash"] == (
        FINAL_V18_ACCEPTANCE_HASH
    )
    assert artifact["executionBoundary"] == {
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
    }


def test_closeout_binds_all_offline_contract_stages() -> None:
    artifact = build_final_successor_readiness_closeout_v1(REPOSITORY_ROOT)

    assert set(artifact["sourceBindings"]) == {
        "v18Acceptance",
        "benchmarkContract",
        "postFreezeDecisionContract",
        "modelExecutionPreflight",
        "prospectiveEnrollmentAdapterPreflight",
    }
    assert (
        artifact["contractState"]["v18Implementation"]
        == "READY_NOT_ENROLLED"
    )
    assert (
        artifact["contractState"]["postFreezeDecisionContractFixture"]
        == "BLOCKED_CONTRACT_FIXTURE_NOT_PROSPECTIVE"
    )
    assert artifact["supersession"]["intermediateArtifactsOverwritten"] is False
    for relative in artifact["supersession"]["preservedIntermediatePaths"]:
        assert (REPOSITORY_ROOT / relative).exists()
    portable = json.loads(
        (
            REPOSITORY_ROOT
            / artifact["supersession"]["portableModelPreflightPath"]
        ).read_text(encoding="utf-8")
    )
    portable_body = dict(portable)
    portable_claim = portable_body.pop("artifactContentHash")
    assert canonical_hash(portable_body) == portable_claim
    assert artifact["sourceBindings"]["modelExecutionPreflight"][
        "artifactContentHash"
    ] == portable_claim


def test_final_closeout_writer_is_immutable(tmp_path: Path) -> None:
    artifact = build_final_successor_readiness_closeout_v1(REPOSITORY_ROOT)
    path = tmp_path / "closeout.json"

    first = write_immutable_final_successor_readiness_closeout(path, artifact)
    assert (
        write_immutable_final_successor_readiness_closeout(path, artifact)
        == first
    )
    changed = json.loads(json.dumps(artifact))
    changed["status"] = "READY"
    changed["artifactContentHash"] = artifact["artifactContentHash"]

    with pytest.raises(
        FinalSuccessorReadinessCloseoutError,
        match="CANONICAL_HASH_MISMATCH",
    ):
        write_immutable_final_successor_readiness_closeout(path, changed)
