from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.future_price_evidence.final_preexecution_preflight_v2 import (
    FINAL_V18_ACCEPTANCE_HASH,
    FinalPreexecutionPreflightError,
    build_final_preexecution_preflight_v2,
    write_immutable_final_preexecution_preflight,
)
from equity_analysis.future_price_evidence.history_capture_runner_v2 import (
    LIVE_CONFIRMATION,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BEFORE_TARGET_COMPLETION = datetime(2026, 7, 30, 19, 0, tzinfo=UTC)
AFTER_TARGET_COMPLETION = datetime(2026, 7, 30, 22, 0, tzinfo=UTC)


def _artifact(*, as_of: datetime = BEFORE_TARGET_COMPLETION) -> dict:
    return build_final_preexecution_preflight_v2(
        repository_root=REPOSITORY_ROOT,
        as_of=as_of,
    )


def test_repository_final_preexecution_state_is_honestly_blocked() -> None:
    artifact = _artifact()

    assert artifact["status"] == "BLOCKED_AWAITING_TARGET_SESSION_COMPLETION"
    assert artifact["blockedReasons"] == ["TARGET_SESSION_NOT_COMPLETED"]
    assert artifact["targetSession"] == "2026-07-30"
    assert artifact["latestCompletedSession"] == "2026-07-29"
    assert artifact["targetSessionCompleted"] is False
    assert artifact["executionBoundary"] == {
        "networkRequestsExecuted": 0,
        "providerRequestsExecuted": 0,
        "databaseReadsExecuted": 0,
        "databaseWritesExecuted": 0,
        "scoresOrRanksComputed": False,
        "enrollmentExecuted": False,
        "outcomesComputed": False,
        "aiUsedForDeterministicFields": False,
        "automaticTradingAuthorized": False,
        "commitCreated": False,
        "pushExecuted": False,
        "deploymentExecuted": False,
        "rawProviderValuesIncluded": False,
    }


def test_exact_67_plus_two_plan_and_evidence_contract_are_frozen() -> None:
    artifact = _artifact()
    plan = artifact["plan"]

    assert plan["priceSymbolCount"] == 67
    assert plan["yahooChartRequestCount"] == 67
    assert plan["officialCalendarRequestCount"] == 2
    assert plan["physicalHttpAttemptHardCeiling"] == 69
    assert plan["configuredWeightHardCeiling"] == 69
    assert plan["providerRetryLimit"] == 0
    assert plan["historyWindowCalendarDays"] == 420
    assert plan["minimumParsedCompletedSessionsPerSymbol"] == 253
    evidence = artifact["evidenceContract"]
    assert evidence["rawTransportHashSemantics"] == (
        "EXACT_HTTP_RESPONSE_BODY_BYTES"
    )
    assert evidence["adjustmentMode"] == "TOTAL_RETURN_ADJUSTED"
    assert evidence["rawAndAdjustedBarsRequired"] is True
    assert evidence["corporateActionsRequired"] is True
    assert evidence["actionAdjustmentBindingRequired"] is True
    assert evidence["adtvPolicyVersion"] == (
        "ADTV-20-RAW-CLOSE-X-RAW-VOLUME-v1.0.0"
    )
    assert evidence["adtvCompletedSessions"] == 20


def test_final_readiness_v18_universe_and_source_hashes_are_bound() -> None:
    artifact = _artifact()
    bindings = artifact["sourceBindings"]

    assert bindings["finalSuccessorReadinessCloseoutV2"]["path"].endswith(
        "forward-v2-2-final-successor-readiness-closeout-v2.json"
    )
    assert bindings["v18Acceptance"]["artifactContentHash"] == (
        FINAL_V18_ACCEPTANCE_HASH
    )
    assert bindings["closedTestUniverse"]["fileSha256"].upper().endswith(
        artifact["plan"]["universeFileSha256"]
    )
    assert (
        bindings["v22PreregistrationSeal"]["sealContentHash"]
        == artifact["plan"]["preregistrationSealHash"]
    )
    assert (
        bindings["externalReferenceUniverse"]["artifactContentHash"]
        == artifact["plan"]["externalReferenceUniverseHash"]
    )
    for binding in bindings.values():
        assert Path(REPOSITORY_ROOT / binding["path"]).is_file()
        assert len(binding["fileSha256"].removeprefix("sha256:")) == 64


def test_execution_safety_and_only_post_close_command_are_exact() -> None:
    artifact = _artifact()
    safety = artifact["executionSafety"]
    command = artifact["onlyApprovedPostCloseCommand"]

    assert safety["leaseRequired"] is True
    assert safety["physicalRequestJournalRequired"] is True
    assert safety["checkpointRequiredForCompletedReplay"] is True
    assert safety["unknownStatePolicy"] == "STOP_NO_AUTOMATIC_RETRY"
    assert safety["providerRetryLimit"] == 0
    controlled_state = artifact["currentControlledStateAudit"]
    assert controlled_state["leaseExists"] is False
    assert controlled_state["unknownPhysicalRequestCount"] == 0
    assert controlled_state["auditPerformedWithoutNetworkOrDatabase"] is True
    expected_token_hash = "sha256:" + hashlib.sha256(
        LIVE_CONFIRMATION.encode("utf-8")
    ).hexdigest()
    assert artifact["liveConfirmation"]["tokenSha256"] == expected_token_hash
    assert command["argv"].count("--execute-live") == 1
    assert command["argv"].count("--confirm-live") == 1
    assert command["argv"].count("--confirm-nyse-session") == 1
    assert command["argv"].count("--confirm-nyse-close") == 1
    assert command["argv"].count("--confirm-nasdaq-session") == 1
    assert command["argv"].count("--confirm-nasdaq-close") == 1
    assert "--write-database" not in command["argv"]
    assert "--resume" not in command["argv"]


def test_after_close_only_advances_to_named_calendar_review() -> None:
    artifact = _artifact(as_of=AFTER_TARGET_COMPLETION)

    assert artifact["targetSessionCompleted"] is True
    assert artifact["latestCompletedSession"] == "2026-07-30"
    assert (
        artifact["status"]
        == "READY_FOR_NAMED_DUAL_CALENDAR_REVIEW_AND_SINGLE_EXECUTION"
    )
    assert artifact["executionBoundary"]["networkRequestsExecuted"] == 0
    assert artifact["executionBoundary"]["databaseWritesExecuted"] == 0


def test_json_round_trip_directly_verifies_canonical_hash(tmp_path: Path) -> None:
    artifact = _artifact()
    path = tmp_path / "preexecution.json"

    file_sha = write_immutable_final_preexecution_preflight(path, artifact)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    body = dict(loaded)
    claim = body.pop("artifactContentHash")

    assert canonical_hash(body) == claim
    assert (
        file_sha
        == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert write_immutable_final_preexecution_preflight(path, loaded) == file_sha


def test_immutable_writer_rejects_tampering(tmp_path: Path) -> None:
    artifact = _artifact()
    path = tmp_path / "preexecution.json"
    write_immutable_final_preexecution_preflight(path, artifact)
    tampered = json.loads(json.dumps(artifact))
    tampered["plan"]["physicalHttpAttemptHardCeiling"] = 70

    with pytest.raises(
        FinalPreexecutionPreflightError,
        match="CANONICAL_HASH_MISMATCH",
    ):
        write_immutable_final_preexecution_preflight(path, tampered)
