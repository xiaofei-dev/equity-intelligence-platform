from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from equity_analysis.forward_validation.human_decision_governance_v1 import (
    HUMAN_DECISION_RECORD_V1,
    PORTFOLIO_SUITABILITY_BOUNDARY_V1,
    HumanDecisionGovernanceError,
    HumanDecisionRecordV1,
    append_human_decision_record_v1,
    build_human_decision_governance_policy_artifact_v1,
    seal_human_decision_record_v1,
    seal_portfolio_suitability_boundary_v1,
    seal_prospective_governance_sidecar_v1,
    validate_human_decision_chain,
    write_or_verify_immutable_human_record_v1,
)
from equity_analysis.forward_validation.outcomes_v21 import (
    HorizonEvaluationRole,
    MaturityScheduleV21,
    sealed_model_payload,
)
from equity_analysis.forward_validation.outcomes_v211 import (
    FORWARD_DQV_ENROLLMENT_V211,
    ForwardDqvEnrollmentV211,
)

_HASH_A = "sha256:" + "a" * 64
_HASH_B = "sha256:" + "b" * 64
_HASH_C = "sha256:" + "c" * 64
_HASH_D = "sha256:" + "d" * 64
_SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
_SEALED_AT = datetime(2026, 7, 30, 20, 0, tzinfo=UTC)
_ENROLLMENT_ID = UUID("55555555-5555-4555-8555-555555555555")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _record_payload(**overrides):
    values = {
        "schemaVersion": HUMAN_DECISION_RECORD_V1,
        "recordId": "22222222-2222-4222-8222-222222222222",
        "enrollmentId": None,
        "publicSecurityId": str(_SECURITY_ID),
        "deterministicOutputSetHash": _HASH_A,
        "deterministicSecurityOutputHash": _HASH_B,
        "deterministicOutputSealEvidenceHash": _HASH_C,
        "deterministicOutputSealedAt": _SEALED_AT.isoformat(),
        "actorIdentity": "closed-test-user-01",
        "testIdentity": "forward-dqv-cohort-v1",
        "recordedAt": (_SEALED_AT + timedelta(minutes=5)).isoformat(),
        "citedEvidence": [
            {
                "evidenceKind": "REGULATORY_FILING",
                "reference": "sec://filing/example",
                "contentHash": _HASH_D,
                "availableAt": (_SEALED_AT - timedelta(hours=1)).isoformat(),
                "citedAt": (_SEALED_AT + timedelta(minutes=4)).isoformat(),
            }
        ],
        "rationale": "The evidence supports retaining this security for research review.",
        "confidence": "0.70",
        "disposition": "WATCH_ONLY",
        "predecessorRecordHash": None,
        "supersedesRecordHash": None,
        "modelScoreOrRankCopiedIntoRecord": False,
        "mayMutateModelOutput": False,
        "mayMutateModelEvidenceLabel": False,
        "portfolioWeightsIncluded": False,
        "tradeDecisionIncluded": False,
        "automaticExecutionAuthorized": False,
    }
    values.update(overrides)
    return values


def _boundary_payload(**overrides):
    values = {
        "schemaVersion": PORTFOLIO_SUITABILITY_BOUNDARY_V1,
        "deterministicOutputSetHash": _HASH_A,
        "enrollmentId": None,
        "modelAssessmentState": "NOT_ASSESSED_BY_MODEL",
        "userOwnedWorkflowState": "NOT_SUPPLIED",
        "userOwnedWorkflowReference": None,
        "userOwnedWorkflowHash": None,
        "userOwnedWorkflowIdentity": None,
        "modelMayDeterminePortfolioSuitability": False,
        "portfolioWeightsIncluded": False,
        "tradeDecisionIncluded": False,
        "automaticExecutionAuthorized": False,
    }
    values.update(overrides)
    return values


def _enrollment() -> ForwardDqvEnrollmentV211:
    entry = _SEALED_AT + timedelta(minutes=30)
    roles = {
        5: HorizonEvaluationRole.TACTICAL_FORMAL,
        20: HorizonEvaluationRole.TACTICAL_FORMAL,
        60: HorizonEvaluationRole.TACTICAL_FORMAL,
        126: HorizonEvaluationRole.LONG_HORIZON_INTERIM_DIAGNOSTIC,
        252: HorizonEvaluationRole.LONG_HORIZON_FORMAL,
    }
    schedules = []
    for index, sessions in enumerate((5, 20, 60, 126, 252), start=1):
        draft = MaturityScheduleV21(
            completed_sessions=sessions,
            evaluation_role=roles[sessions],
            formal_gate_eligible=sessions != 126,
            matures_at_completed_session=entry + timedelta(days=index),
            schedule_content_hash="sha256:" + "0" * 64,
        )
        schedules.append(
            MaturityScheduleV21.model_validate(
                sealed_model_payload(draft, "scheduleContentHash")
            )
        )
    draft = ForwardDqvEnrollmentV211(
        schema_version=FORWARD_DQV_ENROLLMENT_V211,
        enrollment_id=_ENROLLMENT_ID,
        idempotency_key="human-governance-v1-test",
        canonical_request_hash=_HASH_D,
        preregistration_content_hash=_HASH_A,
        decision_manifest_content_hash=_HASH_B,
        decision_controlled_artifact_hash=_HASH_C,
        decision_controlled_artifact_reference="controlled://decision/composite",
        decision_data_snapshot_id=UUID(
            "66666666-6666-4666-8666-666666666666"
        ),
        decision_as_of=_SEALED_AT - timedelta(minutes=5),
        effective_at_completed_session_open=entry,
        universe_version="CLOSED-TEST-66-v1",
        frozen_population_hash=_HASH_D,
        model_freeze_hashes={"TACTICAL": _HASH_A, "LONG_HORIZON": _HASH_B},
        benchmark_contract_version="FORWARD-BENCHMARK-v2.2.0",
        benchmark_contract_hash=_HASH_C,
        cost_policy_version="FORWARD-COST-v2.2.0",
        cost_policy_hash=_HASH_D,
        security_count=66,
        terminal_counts={"ASSESSED": 66},
        maturity_schedule=tuple(schedules),
        sealed_at=_SEALED_AT,
        enrollment_content_hash="sha256:" + "0" * 64,
    )
    return ForwardDqvEnrollmentV211.model_validate(
        sealed_model_payload(draft, "enrollmentContentHash")
    )


def test_human_record_is_sealed_after_model_output_and_has_no_model_values() -> None:
    record = seal_human_decision_record_v1(_record_payload())
    assert record.confidence == Decimal("0.70")
    assert record.may_mutate_model_output is False
    assert record.model_score_or_rank_copied_into_record is False
    payload = record.model_dump(mode="json", by_alias=True)
    assert "opportunityScore" not in payload
    assert "deterministicScore" not in payload
    assert "rank" not in payload
    assert HumanDecisionRecordV1.model_validate(payload) == record


def test_human_record_rejects_pre_model_judgment_and_future_citation() -> None:
    with pytest.raises(ValueError, match="after immutable model output"):
        seal_human_decision_record_v1(
            _record_payload(recordedAt=(_SEALED_AT - timedelta(seconds=1)).isoformat())
        )
    with pytest.raises(ValueError, match="no later than record time"):
        seal_human_decision_record_v1(
            _record_payload(
                citedEvidence=[
                    {
                        "evidenceKind": "PRIMARY_SOURCE",
                        "reference": "source://future",
                        "contentHash": _HASH_D,
                        "availableAt": _SEALED_AT.isoformat(),
                        "citedAt": (_SEALED_AT + timedelta(minutes=6)).isoformat(),
                    }
                ]
            )
        )


def test_append_chain_preserves_predecessor_and_single_supersession() -> None:
    root = seal_human_decision_record_v1(_record_payload())
    records = append_human_decision_record_v1(
        (root,),
        _record_payload(
            recordId="33333333-3333-4333-8333-333333333333",
            recordedAt=(_SEALED_AT + timedelta(minutes=10)).isoformat(),
            supersedesRecordHash=root.record_content_hash,
            rationale="New cited evidence supersedes the earlier research disposition.",
            disposition="ABSTAIN",
        ),
    )
    assert records[-1].predecessor_record_hash == root.record_content_hash
    validate_human_decision_chain(records)
    with pytest.raises(HumanDecisionGovernanceError, match="SUPERSESSION_INVALID"):
        append_human_decision_record_v1(
            records,
            _record_payload(
                recordId="44444444-4444-4444-8444-444444444444",
                recordedAt=(_SEALED_AT + timedelta(minutes=15)).isoformat(),
                supersedesRecordHash=root.record_content_hash,
            ),
        )


def test_portfolio_boundary_defaults_to_not_assessed_and_has_no_weights() -> None:
    boundary = seal_portfolio_suitability_boundary_v1(_boundary_payload())
    assert boundary.model_assessment_state == "NOT_ASSESSED_BY_MODEL"
    assert boundary.portfolio_weights_included is False
    assert boundary.trade_decision_included is False
    with pytest.raises(ValueError, match="cannot carry"):
        seal_portfolio_suitability_boundary_v1(
            _boundary_payload(userOwnedWorkflowReference="app://portfolio/one")
        )
    supplied = seal_portfolio_suitability_boundary_v1(
        _boundary_payload(
            userOwnedWorkflowState="SUPPLIED_SEPARATELY",
            userOwnedWorkflowReference="app://portfolio/one",
            userOwnedWorkflowHash=_HASH_D,
            userOwnedWorkflowIdentity="closed-test-user-01",
        )
    )
    assert supplied.model_assessment_state == "NOT_ASSESSED_BY_MODEL"


def test_sidecar_binds_human_chain_and_fails_closed_for_persistence() -> None:
    record = seal_human_decision_record_v1(_record_payload())
    boundary = seal_portfolio_suitability_boundary_v1(_boundary_payload())
    sidecar = seal_prospective_governance_sidecar_v1(
        decision_manifest_hash=_HASH_B,
        deterministic_output_set_hash=_HASH_A,
        decision_controlled_composite_hash=_HASH_C,
        deterministic_output_sealed_at=_SEALED_AT,
        portfolio_suitability_boundary=boundary,
        human_records=(record,),
    )
    assert sidecar.formal_persistence_state == "BLOCKED_SUCCESSOR_SCHEMA_REQUIRED"
    assert sidecar.human_record_head_hash == record.record_content_hash
    assert sidecar.human_judgment_included_in_model_output is False
    assert sidecar.human_judgment_included_in_enrollment_hash is False


def test_sidecar_rejects_root_mismatch_and_post_entry_human_decision() -> None:
    record = seal_human_decision_record_v1(_record_payload())
    wrong_boundary = seal_portfolio_suitability_boundary_v1(
        _boundary_payload(deterministicOutputSetHash=_HASH_D)
    )
    with pytest.raises(ValueError, match="Portfolio boundary root binding mismatch"):
        seal_prospective_governance_sidecar_v1(
            decision_manifest_hash=_HASH_B,
            deterministic_output_set_hash=_HASH_A,
            decision_controlled_composite_hash=_HASH_C,
            deterministic_output_sealed_at=_SEALED_AT,
            portfolio_suitability_boundary=wrong_boundary,
            human_records=(record,),
        )


def test_sidecar_verifies_enrollment_and_prospective_human_chronology() -> None:
    enrollment = _enrollment()
    record = seal_human_decision_record_v1(
        _record_payload(enrollmentId=str(enrollment.enrollment_id))
    )
    boundary = seal_portfolio_suitability_boundary_v1(
        _boundary_payload(enrollmentId=str(enrollment.enrollment_id))
    )
    sidecar = seal_prospective_governance_sidecar_v1(
        decision_manifest_hash=_HASH_B,
        deterministic_output_set_hash=_HASH_A,
        decision_controlled_composite_hash=_HASH_C,
        deterministic_output_sealed_at=_SEALED_AT,
        portfolio_suitability_boundary=boundary,
        human_records=(record,),
        enrollment=enrollment,
    )
    assert sidecar.enrollment_content_hash == enrollment.enrollment_content_hash
    late_record = seal_human_decision_record_v1(
        _record_payload(
            enrollmentId=str(enrollment.enrollment_id),
            recordedAt=(
                enrollment.effective_at_completed_session_open
                + timedelta(seconds=1)
            ).isoformat(),
            citedEvidence=[
                {
                    "evidenceKind": "PRIMARY_SOURCE",
                    "reference": "source://late",
                    "contentHash": _HASH_D,
                    "availableAt": _SEALED_AT.isoformat(),
                    "citedAt": (
                        enrollment.effective_at_completed_session_open
                        + timedelta(seconds=1)
                    ).isoformat(),
                }
            ],
        )
    )
    with pytest.raises(ValueError, match="no later than the effective entry open"):
        seal_prospective_governance_sidecar_v1(
            decision_manifest_hash=_HASH_B,
            deterministic_output_set_hash=_HASH_A,
            decision_controlled_composite_hash=_HASH_C,
            deterministic_output_sealed_at=_SEALED_AT,
            portfolio_suitability_boundary=boundary,
            human_records=(late_record,),
            enrollment=enrollment,
        )


def test_immutable_writer_is_idempotent_and_rejects_drift(tmp_path: Path) -> None:
    record = seal_human_decision_record_v1(_record_payload())
    path = write_or_verify_immutable_human_record_v1(
        record=record,
        storage_root=tmp_path,
    )
    assert (
        write_or_verify_immutable_human_record_v1(
            record=record,
            storage_root=tmp_path,
        )
        == path
    )
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        write_or_verify_immutable_human_record_v1(
            record=record,
            storage_root=tmp_path,
        )


def test_policy_artifact_is_machine_readable_and_fail_closed() -> None:
    artifact = build_human_decision_governance_policy_artifact_v1()
    assert artifact["status"] == "CONTRACT_READY_PERSISTENCE_BLOCKED"
    assert artifact["humanDecision"]["mayMutateScoreOrRank"] is False
    assert (
        artifact["portfolioSuitability"]["defaultModelState"]
        == "NOT_ASSESSED_BY_MODEL"
    )
    assert (
        artifact["formalPersistence"]["state"]
        == "BLOCKED_SUCCESSOR_SCHEMA_REQUIRED"
    )
    checked_in = json.loads(
        (
            REPOSITORY_ROOT
            / "docs"
            / "generated"
            / "forward-human-decision-governance-policy-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert checked_in == artifact
