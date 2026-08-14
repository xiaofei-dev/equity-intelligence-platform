from pathlib import Path

import pytest

from equity_analysis.fundamental_value.historical_execution_v1 import (
    AcquisitionPhase,
    BatchPlan,
    EndpointExecutionJournal,
    PlannedRequest,
    batch_plan_hash,
    canonical_hash,
    registry_preflight_from_provider_artifact,
    verify_canary_checkpoint_reuse,
)
from equity_analysis.fundamental_value.historical_provider_v1 import (
    build_eodhd_preflight,
)


def request(identity: str = "SEC-1:eod") -> PlannedRequest:
    return PlannedRequest(identity, "SEC-1", "ABC", "eod", "/api/eod/ABC.US", 1)


def plan() -> BatchPlan:
    return BatchPlan("BATCH-001", "A" * 64, "B" * 64, "C" * 64, "D" * 64,
                     "BASELINE", 20000, 1, 1, 0, (request(),))


def test_plan_hash_binds_budget_and_all_contract_hashes() -> None:
    assert len(batch_plan_hash(plan())) == 64
    invalid = BatchPlan(**{**plan().__dict__, "configured_weight_ceiling": 2})
    with pytest.raises(ValueError, match="WEIGHT_BUDGET_MISMATCH"):
        batch_plan_hash(invalid)


def test_unmatched_intent_blocks_resume_as_unknown(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="BLOCKED_EXECUTION_CONTRACT_INCOMPLETE"):
        EndpointExecutionJournal(tmp_path, "run-1", plan())


def test_completed_checkpoint_is_reused_without_physical_replay(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="BLOCKED_EXECUTION_CONTRACT_INCOMPLETE"):
        EndpointExecutionJournal(tmp_path, "run-1", plan())


def test_journal_rejects_plan_hash_drift(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="BLOCKED_EXECUTION_CONTRACT_INCOMPLETE"):
        EndpointExecutionJournal(tmp_path, "run-1", plan())


def test_canaries_must_be_bound_to_later_membership_requests() -> None:
    with pytest.raises(RuntimeError, match="CANARY_REUSE_BLOCKED"):
        verify_canary_checkpoint_reuse(["a", "b"], ["c"])


def test_registry_preflight_is_derived_from_canonical_provider_artifact() -> None:
    artifact = build_eodhd_preflight()
    result = registry_preflight_from_provider_artifact(
        artifact, phase=AcquisitionPhase.BASELINE, universe_hash="A" * 64,
        decision_dates_hash="B" * 64, protocol_hash="C" * 64)
    assert result.physical_request_total == 930
    assert {item[0] for item in result.permitted_endpoints} == {
        "fundamentals", "div", "splits"}
    forged = dict(artifact)
    forged["minimumUnusedReserve"] = 1
    with pytest.raises(ValueError, match="NOT_MASTER_FROZEN"):
        registry_preflight_from_provider_artifact(
            forged, phase=AcquisitionPhase.BASELINE, universe_hash="A" * 64,
            decision_dates_hash="B" * 64, protocol_hash="C" * 64)
    resealed = dict(forged)
    body = dict(resealed)
    body.pop("contentHash")
    resealed["contentHash"] = canonical_hash(body)
    with pytest.raises(ValueError, match="NOT_MASTER_FROZEN"):
        registry_preflight_from_provider_artifact(
            resealed, phase=AcquisitionPhase.BASELINE, universe_hash="A" * 64,
            decision_dates_hash="B" * 64, protocol_hash="C" * 64)


def test_cross_request_event_copy_fails_identity_replay(tmp_path: Path) -> None:
    requests = (request("SEC-1:eod"), request("SEC-2:eod"))
    requests = (requests[0], PlannedRequest(
        "SEC-2:eod", "SEC-2", "DEF", "eod", "/api/eod/DEF.US", 1))
    two = BatchPlan("BATCH-002", "A" * 64, "B" * 64, "C" * 64, "D" * 64,
                    "BASELINE", 20000, 2, 2, 0, requests)
    with pytest.raises(RuntimeError, match="BLOCKED_EXECUTION_CONTRACT_INCOMPLETE"):
        EndpointExecutionJournal(tmp_path, "run-1", two)
