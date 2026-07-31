from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from controlled_data import require_artifact_controlled_references

from equity_analysis.market_intelligence.objective_gate_replay_postgres_v1 import (
    _normalized_inputs,
)
from equity_analysis.market_intelligence.objective_gate_replay_v1 import (
    CURRENT_SCOPE,
    EXPECTED_MANIFEST_HASH,
    EXPECTED_PAYLOAD_SCHEMA,
    EXPECTED_SOURCE_POLICY,
    EXPECTED_WINDOW_POLICY,
    ObjectiveGateReplayError,
    _verify_payload,
    build_objective_gate_replay_plan,
)
from equity_analysis.provider_validation.expansion_gate import canonical_hash

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = (
    REPOSITORY_ROOT
    / "docs/generated/objective-rating-v1-current-decision-input-manifest-v1.json"
)
GATE = (
    REPOSITORY_ROOT
    / "docs/generated/objective-rating-v1-current-snapshot-algorithm-gate-v1.json"
)
AUDIT = (
    REPOSITORY_ROOT
    / "docs/generated/market-intelligence-eligibility-root-cause-audit-v1.json"
)


def _require_objective_controlled_inputs() -> None:
    require_artifact_controlled_references(
        REPOSITORY_ROOT,
        (MANIFEST.relative_to(REPOSITORY_ROOT),),
        purpose="Objective Rating gate replay",
    )


def _plan():
    _require_objective_controlled_inputs()
    return build_objective_gate_replay_plan(
        repository_root=REPOSITORY_ROOT,
        input_manifest_path=MANIFEST,
        algorithm_gate_path=GATE,
        closed_pool_audit_path=AUDIT,
    )


def _write_resealed(path: Path, payload: dict) -> None:
    candidate = dict(payload)
    candidate.pop("artifactContentHash", None)
    candidate["artifactContentHash"] = canonical_hash(candidate)
    path.write_text(
        json.dumps(candidate, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def test_replay_plan_verifies_controlled_evidence_and_reaches_objective_minimum():
    plan = _plan()

    assert plan.source_profile_count == 66
    assert plan.included_count == 55
    assert plan.objective_scored_count == 32
    assert plan.insufficient_data_count == 23
    assert plan.non_applicable_count == 11
    assert plan.frozen_minimum == 20
    assert plan.threshold_reached is True
    assert plan.network_requests_required is False
    assert plan.full_market_intelligence_eligibility_claimed is False
    assert plan.manifest_content_hash == EXPECTED_MANIFEST_HASH
    assert plan.source_snapshot_id == "beaa9952-9852-4088-9dc3-92047824414b"
    assert plan.universe_version == "market-intelligence-closed-test-us-v1.0.0"
    assert sum(
        item.objective_state == "OBJECTIVE_QC_SCORED"
        for item in plan.securities
    ) == 32


def test_replay_plan_rejects_unsealed_gate_change(tmp_path: Path):
    payload = json.loads(GATE.read_text(encoding="utf-8"))
    payload["scoredSecurityCount"] = 135
    changed = tmp_path / "gate.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ObjectiveGateReplayError,
        match="ARTIFACT_CONTENT_HASH_MISMATCH",
    ):
        build_objective_gate_replay_plan(
            repository_root=REPOSITORY_ROOT,
            input_manifest_path=MANIFEST,
            algorithm_gate_path=changed,
            closed_pool_audit_path=AUDIT,
        )


def test_replay_plan_rejects_historical_pit_promotion(tmp_path: Path):
    payload = json.loads(GATE.read_text(encoding="utf-8"))
    payload["methodologyBoundaries"]["historicalPitClaim"] = True
    changed = tmp_path / "gate.json"
    _write_resealed(changed, payload)

    with pytest.raises(
        ObjectiveGateReplayError,
        match="OBJECTIVE_GATE_NOT_ACCEPTED",
    ):
        build_objective_gate_replay_plan(
            repository_root=REPOSITORY_ROOT,
            input_manifest_path=MANIFEST,
            algorithm_gate_path=changed,
            closed_pool_audit_path=AUDIT,
        )


def test_replay_plan_rejects_gate_input_hash_drift(tmp_path: Path):
    payload = json.loads(GATE.read_text(encoding="utf-8"))
    payload["securities"][0]["inputPayloadHash"] = "0" * 64
    changed = tmp_path / "gate.json"
    _write_resealed(changed, payload)

    with pytest.raises(
        ObjectiveGateReplayError,
        match="OBJECTIVE_GATE_NOT_ACCEPTED",
    ):
        build_objective_gate_replay_plan(
            repository_root=REPOSITORY_ROOT,
            input_manifest_path=MANIFEST,
            algorithm_gate_path=changed,
            closed_pool_audit_path=AUDIT,
        )


def test_controlled_payload_rejects_resealed_symbol_mismatch(tmp_path: Path):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source_item = next(
        item for item in manifest["securities"] if item["storageReference"]
    )
    payload = {"symbol": "WRONG"}
    payload["contentHash"] = canonical_hash(payload)
    item = {
        **source_item,
        "payloadContentHash": payload["contentHash"],
    }

    # The controlled payload resolver intentionally rejects paths outside the
    # repository, so place the fixture below a temporary repository root.
    fixture_root = tmp_path / "repo"
    fixture_root.mkdir()
    fixture_path = fixture_root / "payload.json"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
    item["storageReference"] = "payload.json"
    with pytest.raises(
        ObjectiveGateReplayError,
        match="CONTROLLED_PAYLOAD_SYMBOL_MISMATCH",
    ):
        _verify_payload(
            fixture_root,
            item,
            cutoff=manifest["cutoff"],
        )


def test_controlled_payload_requires_frozen_semantic_versions(tmp_path: Path):
    payload = {
        "schemaVersion": EXPECTED_PAYLOAD_SCHEMA,
        "windowPolicyVersion": EXPECTED_WINDOW_POLICY,
        "sourcePolicyVersion": EXPECTED_SOURCE_POLICY,
        "symbol": "TEST",
        "cutoff": "2026-07-28T23:59:59Z",
        "scope": CURRENT_SCOPE,
        "formulaOrWeightChanges": False,
        "scoresOrRanksIncluded": False,
        "historicalPitEligible": False,
        "forwardObservationEligible": True,
        "backtestEligible": False,
        "currentQcInputReady": True,
        "algorithmQcEligible": True,
        "qcRawFactors": {},
    }
    payload["contentHash"] = canonical_hash(payload)
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    item = {
        "symbol": "TEST",
        "status": "CURRENT_QC_INPUT_READY",
        "storageReference": "payload.json",
        "payloadContentHash": payload["contentHash"],
    }
    payload["windowPolicyVersion"] = "unapproved-window-policy"
    payload.pop("contentHash")
    payload["contentHash"] = canonical_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    item["payloadContentHash"] = payload["contentHash"]

    with pytest.raises(
        ObjectiveGateReplayError,
        match="CONTROLLED_PAYLOAD_WINDOW_POLICY_MISMATCH",
    ):
        _verify_payload(
            tmp_path,
            item,
            cutoff="2026-07-28T23:59:59Z",
        )


def test_gate_recomputation_rejects_score_and_rank_tampering():
    _require_objective_controlled_inputs()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    gate = json.loads(GATE.read_text(encoding="utf-8"))
    gate["securities"][0]["score"] = "0.0000"
    with pytest.raises(ValueError, match="OBJECTIVE_GATE_SCORE_MISMATCH"):
        _normalized_inputs(
            repository_root=REPOSITORY_ROOT,
            manifest=manifest,
            gate=gate,
        )

    gate = json.loads(GATE.read_text(encoding="utf-8"))
    gate["securities"][0]["rank"], gate["securities"][1]["rank"] = (
        gate["securities"][1]["rank"],
        gate["securities"][0]["rank"],
    )
    with pytest.raises(ValueError, match="OBJECTIVE_GATE_RANK_ORDER_MISMATCH"):
        _normalized_inputs(
            repository_root=REPOSITORY_ROOT,
            manifest=manifest,
            gate=gate,
        )


def test_postgres_writer_rejects_unsealed_universe_before_connecting():
    _require_objective_controlled_inputs()
    from equity_analysis.market_intelligence.objective_gate_replay_postgres_v1 import (
        ObjectiveGateReplayPostgresWriter,
    )

    writer = ObjectiveGateReplayPostgresWriter(
        "postgresql://unused.invalid/objective_replay_test",
        REPOSITORY_ROOT,
    )
    with pytest.raises(ValueError, match="Universe version does not match"):
        writer.replay(
            source_snapshot_id=UUID("beaa9952-9852-4088-9dc3-92047824414b"),
            universe_version="unapproved-universe-v2",
            input_manifest_path=MANIFEST,
            algorithm_gate_path=GATE,
            closed_pool_audit_path=AUDIT,
        )
