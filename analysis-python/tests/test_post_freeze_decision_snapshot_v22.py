from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.post_freeze_decision_snapshot_v22 import (
    EXPECTED_BENCHMARK_KINDS,
    EXPECTED_COST_POLICY_HASH,
    EXPECTED_ROLE_COUNTS,
    FORWARD_DQV_PREREGISTRATION_PATH,
    POST_FREEZE_DECISION_INPUT_V22,
    AiNarrativeBoundaryV22,
    ArtifactPurpose,
    PostFreezeDecisionError,
    PostFreezeDecisionSnapshotV22,
    assemble_post_freeze_decision_snapshot_v22,
    build_git_safe_post_freeze_manifest_v22,
    build_post_freeze_contract_fixture_v22,
    write_immutable_post_freeze_manifest_v22,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _rehash(payload: dict) -> dict:
    body = dict(payload)
    body.pop("manifestContentHash", None)
    return {**body, "manifestContentHash": canonical_hash(body)}


def test_contract_fixture_binds_seal_66_members_models_and_six_benchmarks() -> None:
    manifest = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    parent = json.loads(
        (REPOSITORY_ROOT / FORWARD_DQV_PREREGISTRATION_PATH).read_text(
            encoding="utf-8"
        )
    )

    assert manifest.population_count == 66
    assert manifest.role_counts == EXPECTED_ROLE_COUNTS
    assert len(manifest.decisions) == 66
    assert len({item.public_security_id for item in manifest.decisions}) == 66
    assert {
        (item.symbol, str(item.public_security_id), item.role)
        for item in manifest.decisions
    } == {
        (item["symbol"], item["publicSecurityId"], item["role"])
        for item in parent["prospectiveUniverse"]["securities"]
    }
    assert {item.benchmark_kind for item in manifest.benchmark_evidence} == set(
        EXPECTED_BENCHMARK_KINDS
    )
    assert {item.track for item in manifest.model_freezes} == {
        "TACTICAL",
        "LONG_HORIZON",
    }
    assert manifest.cost_policy_hash == EXPECTED_COST_POLICY_HASH
    assert all(len(item.tactical_horizons) == 3 for item in manifest.decisions)
    assert manifest.ai_narrative.may_affect_deterministic_fields is False
    assert manifest.enrollment_authorized is False
    assert manifest.scores_or_ranks_computed is False


def test_fixture_decision_is_strictly_after_v22_seal_and_one_completed_session() -> None:
    manifest = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )

    assert manifest.decision_cutoff > manifest.seal.cutoff
    assert (
        manifest.completed_session_price_evidence.completed_at
        > manifest.seal.cutoff
    )
    assert all(
        item.decision_cutoff == manifest.decision_cutoff
        and item.completed_session == manifest.completed_session
        and item.price_evidence_hash
        == manifest.completed_session_price_evidence.evidence_hash
        for item in manifest.decisions
    )


def test_preseal_decision_is_rejected_even_with_a_recomputed_manifest_hash() -> None:
    manifest = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    payload = manifest.model_dump(mode="json", by_alias=True)
    payload["decisionCutoff"] = "2026-07-30T03:55:37.171621Z"

    with pytest.raises(
        ValidationError,
        match="strictly after the v2.2 seal",
    ):
        PostFreezeDecisionSnapshotV22.model_validate(_rehash(payload))


def test_mixed_completed_session_rows_are_rejected() -> None:
    manifest = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    payload = manifest.model_dump(mode="json", by_alias=True)
    row = dict(payload["decisions"][0])
    row["completedSession"] = "2026-07-31"
    row_body = dict(row)
    row_body.pop("rowHash")
    row["rowHash"] = canonical_hash(row_body)
    payload["decisions"][0] = row

    with pytest.raises(ValidationError, match="one cutoff and one completed session"):
        PostFreezeDecisionSnapshotV22.model_validate(_rehash(payload))


def test_legacy_snapshot_cannot_be_upgraded() -> None:
    manifest = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )

    with pytest.raises(
        PostFreezeDecisionError,
        match="LEGACY_DECISION_SNAPSHOT_UPGRADE_PROHIBITED",
    ):
        assemble_post_freeze_decision_snapshot_v22(
            repository_root=REPOSITORY_ROOT,
            purpose=ArtifactPurpose.PROSPECTIVE_DECISION,
            source_input_contract_version="FORWARD-DECISION-SNAPSHOT-v2.0.0",
            decision_cutoff=manifest.decision_cutoff,
            completed_session_price_evidence=(
                manifest.completed_session_price_evidence
            ),
            model_freezes=manifest.model_freezes,
            benchmark_evidence=manifest.benchmark_evidence,
            cost_policy_hash=manifest.cost_policy_hash,
            sector_classification_hash=manifest.sector_classification_hash,
            source_snapshot_hash=manifest.source_snapshot_hash,
            decisions=manifest.decisions,
            ai_narrative=manifest.ai_narrative,
        )


def test_all_six_benchmarks_are_required() -> None:
    manifest = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    payload = manifest.model_dump(mode="json", by_alias=True)
    payload["benchmarkEvidence"] = payload["benchmarkEvidence"][:-1]

    with pytest.raises(ValidationError, match="exact six benchmark families"):
        PostFreezeDecisionSnapshotV22.model_validate(_rehash(payload))


def test_non_assessed_terminal_state_requires_explicit_reason() -> None:
    manifest = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    row = manifest.decisions[0].model_dump(mode="json", by_alias=True)
    horizon = dict(row["tacticalHorizons"][0])
    horizon["reasonCodes"] = []
    row["tacticalHorizons"][0] = horizon
    row_body = dict(row)
    row_body.pop("rowHash")
    row["rowHash"] = canonical_hash(row_body)

    with pytest.raises(ValidationError, match="requires reasons and no result"):
        type(manifest.decisions[0]).model_validate(row)


def test_excluded_member_cannot_be_reclassified_as_missing() -> None:
    manifest = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    excluded = next(item for item in manifest.decisions if item.role == "EXCLUDED")
    row = excluded.model_dump(mode="json", by_alias=True)
    row["tacticalHorizons"][0]["terminalState"] = "MISSING"
    row["tacticalHorizons"][0]["reasonCodes"] = ["MISSING_TEST"]
    row_body = dict(row)
    row_body.pop("rowHash")
    row["rowHash"] = canonical_hash(row_body)

    with pytest.raises(ValidationError, match="EXCLUDED terminal states"):
        type(excluded).model_validate(row)


def test_ai_narrative_cannot_affect_deterministic_fields() -> None:
    with pytest.raises(ValidationError, match="Input should be False"):
        AiNarrativeBoundaryV22.model_validate(
            {
                "schemaVersion": "POST-FREEZE-AI-BOUNDARY-v2.2.0",
                "status": "NOT_EXECUTED",
                "mayAffectDeterministicFields": True,
            }
        )


def test_immutable_manifest_replay_and_conflict(tmp_path) -> None:
    manifest = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    path = tmp_path / "post-freeze-v22.json"

    first_hash = write_immutable_post_freeze_manifest_v22(path, manifest)
    second_hash = write_immutable_post_freeze_manifest_v22(path, manifest)

    assert first_hash == second_hash
    changed = path.read_text(encoding="utf-8").replace(
        '"databaseWrites": 0',
        '"databaseWrites": 1',
    )
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(
        PostFreezeDecisionError,
        match="IMMUTABLE_POST_FREEZE_MANIFEST_CONFLICT",
    ):
        write_immutable_post_freeze_manifest_v22(path, manifest)


def test_fixture_source_contract_is_post_freeze_v22() -> None:
    manifest = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )

    assert manifest.source_input_contract_version == POST_FREEZE_DECISION_INPUT_V22
    assert manifest.decision_cutoff == datetime(
        2026,
        7,
        30,
        22,
        30,
        tzinfo=UTC,
    )


def test_checked_in_git_safe_fixture_matches_contract_builder() -> None:
    manifest = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    expected = build_git_safe_post_freeze_manifest_v22(manifest)
    checked_in = json.loads(
        (
                REPOSITORY_ROOT
                / "docs/generated/"
                "post-freeze-decision-snapshot-v2-2-contract-fixture-v2.json"
            ).read_text(encoding="utf-8")
        )

    assert checked_in == expected
    assert checked_in["populationCount"] == 66
    assert checked_in["purpose"] == "CONTRACT_FIXTURE"
    assert checked_in["status"] == "BLOCKED_CONTRACT_FIXTURE"
    assert checked_in["enrollmentAuthorized"] is False
    assert checked_in["scoresOrRanksComputed"] is False
