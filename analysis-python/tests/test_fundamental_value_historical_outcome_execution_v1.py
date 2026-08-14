import json
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.historical_outcome_execution_v1 import (
    C7ExecutionError,
    Journal,
    build_plan,
    build_reuse_registry,
    plan_artifact,
)
from equity_analysis.fundamental_value.historical_quarterly_semantics_support_v1 import (
    canonical_hash,
)

REPOSITORY = Path(__file__).resolve().parents[2]


def _checkpoint() -> dict:
    return json.loads(
        (
            REPOSITORY
            / "storage/fundamental-value-historical-validation-v1"
            / "stage7c5-provider-native/sealed-predictors.json"
        ).read_text()
    )


def test_plan_is_exact_203_and_aliases_are_collision_free() -> None:
    plan = build_plan(_checkpoint())
    assert len(plan.requests) == 203
    assert len({item.symbol for item in plan.requests}) == 203
    assert sum(item.role == "EQUITY" for item in plan.requests) == 191
    assert sum(item.role == "SECTOR_BENCHMARK" for item in plan.requests) == 11
    assert next(item for item in plan.requests if item.security_id == "EODHD:BF-B").symbol == "BF-B"


def test_plan_artifact_refuses_to_hide_missing_requests() -> None:
    plan = build_plan(_checkpoint())
    registry = {
        "planHash": plan.plan_hash,
        "requestSetHash": plan.request_set_hash,
        "recordCount": 1,
        "records": [{"symbol": "SPY"}],
        "contentHash": "A" * 64,
    }
    artifact = plan_artifact(plan, registry)
    assert artifact["plannedRequestCount"] == 203
    assert artifact["reusedReceiptCount"] == 1
    assert artifact["newRequestCount"] == 202
    assert artifact["retryLimit"] == 0
    assert artifact["unknownRetryAllowed"] is False


def test_reuse_registry_binds_exact_adapter_range_and_request() -> None:
    plan = build_plan(_checkpoint())
    manifest = json.loads(
        (
            REPOSITORY
            / "docs/generated"
            / "historical-yahoo-price-cache-20260729T-HISTORICAL-V1-R2-manifest.json"
        ).read_text()
    )
    spy = next(item for item in manifest["records"] if item["symbol"] == "SPY")
    storage = Path(
        r"C:\Projects\equity-intelligence-platform\storage\historical-validation\yahoo-daily-price-cache-v1"
    )
    registry = build_reuse_registry(plan, {"SPY": spy}, storage)
    assert registry["recordCount"] == 1
    request = next(item for item in plan.requests if item.symbol == "SPY")
    assert registry["records"][0]["requestIdentity"] == request.request_identity
    drift = dict(spy)
    drift["adjustmentPolicyVersion"] = "WRONG"
    with pytest.raises((C7ExecutionError, ValueError)):
        build_reuse_registry(plan, {"SPY": drift}, storage)


def test_journal_binds_plan_request_chain_and_blocks_unknown(tmp_path: Path) -> None:
    plan = build_plan(_checkpoint())
    request = plan.requests[0]
    journal = Journal(tmp_path, plan, "A" * 64)
    intent = journal.append(request, "INTENT", {"retryLimit": 0})
    assert intent["previousEventHash"] is None
    with pytest.raises(C7ExecutionError, match="INVALID_TRANSITION"):
        journal.append(request, "INTENT", {})
    event_path = next(
        (tmp_path / f"{request.ordinal:03d}-{request.request_identity}").glob("*.json")
    )
    event = json.loads(event_path.read_text())
    event["requestIdentity"] = "B" * 64
    event_path.write_text(json.dumps(event))
    with pytest.raises(C7ExecutionError, match="UNKNOWN_EVENT_CHAIN"):
        journal.events(request)


def test_journal_rejects_plan_drift_and_copied_request_event(tmp_path: Path) -> None:
    plan = build_plan(_checkpoint())
    journal = Journal(tmp_path, plan, "A" * 64)
    first, second = plan.requests[:2]
    journal.append(first, "INTENT", {})
    source = next((tmp_path / f"{first.ordinal:03d}-{first.request_identity}").glob("*.json"))
    destination = tmp_path / f"{second.ordinal:03d}-{second.request_identity}"
    destination.mkdir()
    (destination / source.name).write_bytes(source.read_bytes())
    with pytest.raises(C7ExecutionError, match="UNKNOWN_EVENT_CHAIN"):
        journal.events(second)
    with pytest.raises(C7ExecutionError, match="PLAN_DRIFT"):
        Journal(tmp_path, plan, "C" * 64)


def test_checked_preflight_is_canonical_and_network_bounded() -> None:
    artifact = json.loads(
        (
            REPOSITORY
            / "contracts/fundamental-value-historical-validation-v1"
            / "stage7c7-yahoo-outcome-preflight.json"
        ).read_text()
    )
    body = dict(artifact)
    claimed = body.pop("contentHash")
    assert claimed == canonical_hash(body)
    assert artifact["plannedRequestCount"] == 203
    assert artifact["reusedReceiptCount"] == 37
    assert artifact["newRequestCount"] == 166
    assert artifact["hardCeiling"] == 203
    assert artifact["retryLimit"] == 0
    assert artifact["numericOutcomesRead"] is False


def test_checked_acquisition_summary_preserves_outcome_stop() -> None:
    artifact = json.loads(
        (
            REPOSITORY
            / "contracts/fundamental-value-historical-validation-v1"
            / "stage7c7-outcome-acquisition-summary.json"
        ).read_text()
    )
    body = dict(artifact)
    claimed = body.pop("contentHash")
    assert claimed == canonical_hash(body)
    assert artifact["planned"] == artifact["completed"] == 203
    assert artifact["reused"] == 37
    assert artifact["newPhysicalCalls"] == 166
    assert artifact["retryLimit"] == artifact["unknownRequests"] == 0
    assert artifact["outcomesRead"] is False
    assert artifact["state"] == "BLOCKED_OUTCOME_PROTOCOL_UNRESOLVED"


def test_c8_policy_is_canonical_complete_and_pre_outcome() -> None:
    artifact = json.loads(
        (
            REPOSITORY
            / "contracts/fundamental-value-historical-validation-v1"
            / "stage7c8-outcome-policy.json"
        ).read_text()
    )
    body = dict(artifact)
    claimed = body.pop("contentHash")
    assert claimed == canonical_hash(body)
    assert artifact["outcomeAccessed"] is False
    assert artifact["bindings"]["c8ReuseRegistry"] == (
        "2F3B706745B8E99F14037CC52C83FA360580761E462A307E11C6BB28DBEFD711"
    )
    assert artifact["cost"]["net"] == "GROSS_MINUS_ROUND_TRIP_COST_RATE"
    assert artifact["downside"]["minimumMatched"] == 20
    assert artifact["severeLoss"]["condition"] == "NET_TOTAL_RETURN_LTE_MINUS_0_30"
    assert artifact["spearman"]["minimumPairs"] == 100
    assert artifact["eligibility"]["minimumHighCoverage"] == "0.90"
    assert artifact["anchors"]["equalityOverlaps"] is True


def test_c8_results_are_canonical_and_keep_claim_ceiling() -> None:
    result = json.loads((REPOSITORY / "contracts/fundamental-value-historical-validation-v1"
                         / "stage7c8-outcome-result.json").read_text())
    body = dict(result)
    assert body.pop("contentHash") == canonical_hash(body)
    assert len(result["dateHorizonResults"]) == 36
    assert result["providerValuesIncluded"] is False
    assert result["claimCeiling"] == (
        "DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION")
    final = json.loads((REPOSITORY / "contracts/fundamental-value-historical-validation-v1"
                        / "stage7c8-outcome-final.json").read_text())
    body = dict(final)
    assert body.pop("contentHash") == canonical_hash(body)
    assert final["evidenceRuling"] == (
        "DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION")
    assert final["modelLevelUpgrade"] is False
    assert all(final["thresholdResults"].values())
    assert final["nonOverlappingAnchors"]["dates"] == [
        "2015-05-07", "2019-06-21", "2023-05-18"]
    disposition = json.loads((REPOSITORY
        / "contracts/fundamental-value-historical-validation-v1"
        / "stage7c8-audit-disposition.json").read_text())
    body = dict(disposition)
    assert body.pop("contentHash") == canonical_hash(body)
    assert disposition["rankIcInterpretationValid"] is False
    assert disposition["allThresholdsPassedClaimValid"] is False
    assert disposition["evidenceRuling"] == "NOT_VALIDATED"
    assert disposition["stage8State"] == "CLOSED_STAGE7_NOT_ACCEPTED"
