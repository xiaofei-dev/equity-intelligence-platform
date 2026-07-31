from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.forward_validation import prospective_cohort_controller_v22
from equity_analysis.forward_validation.outcomes_v21 import sealed_model_payload
from equity_analysis.forward_validation.outcomes_v211 import (
    ForwardDqvEnrollmentV211,
)
from equity_analysis.forward_validation.prospective_cohort_controller_v22 import (
    CohortAccumulationRequestV22,
    CohortDecisionDateCandidateV22,
    ProspectiveCohortControllerError,
    build_contract_fixture_request_v22,
    build_prospective_cohort_plan_v22,
    verify_idempotent_cohort_plan_replay_v22,
    verify_prospective_cohort_plan_v22,
    write_immutable_cohort_plan_v22,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _plan(
    request: CohortAccumulationRequestV22 | None = None,
) -> tuple[CohortAccumulationRequestV22, dict]:
    source = request or build_contract_fixture_request_v22()
    with patch.object(
        prospective_cohort_controller_v22,
        "_v19_binding",
        return_value={
            "path": "test-v19-binding",
            "schemaVersion": "FORWARD-DQV-V19-CHRONOLOGY-ACCEPTANCE-v1.0.0",
            "artifactContentHash": "sha256:" + "a" * 64,
            "fileSha256": "sha256:" + "b" * 64,
        },
    ):
        return source, build_prospective_cohort_plan_v22(
            repository_root=REPOSITORY_ROOT,
            request=source,
        )


def _persisted_request(
    source: CohortAccumulationRequestV22 | None = None,
) -> CohortAccumulationRequestV22:
    fixture = source or build_contract_fixture_request_v22()
    body = fixture.model_dump(mode="json", by_alias=True)
    body.pop("requestContentHash")
    body["purpose"] = "PERSISTED_ENROLLMENT_READ"
    for candidate in body["decisionDates"]:
        candidate.pop("candidateContentHash")
        candidate["enrollmentExecuted"] = True
        assessed = candidate["enrollment"]["terminalCounts"]["ASSESSED"]
        for index, row in enumerate(candidate["securityDecisions"]):
            row.pop("recordContentHash")
            for outcome in row["horizonOutcomes"]:
                state = "ASSESSED" if index < assessed else "MISSING"
                outcome["state"] = state
                outcome["observedAt"] = (
                    datetime.fromisoformat(
                        outcome["maturedAtCompletedSession"].replace("Z", "+00:00")
                    )
                    + timedelta(minutes=5)
                )
                outcome["outcomeBatchContentHash"] = canonical_hash(
                    {
                        "fixture": "persisted-outcome-batch",
                        "completedSession": candidate["completedSession"],
                        "completedSessions": outcome["completedSessions"],
                    }
                )
                outcome["securityOutcomeRecordHash"] = canonical_hash(
                    {
                        "fixture": "persisted-security-outcome",
                        "publicSecurityId": row["publicSecurityId"],
                        "completedSession": candidate["completedSession"],
                        "completedSessions": outcome["completedSessions"],
                        "state": state,
                    }
                )
            row["recordContentHash"] = canonical_hash(row)
        candidate["candidateContentHash"] = canonical_hash(candidate)
    request = CohortAccumulationRequestV22.model_validate(
        {**body, "requestContentHash": canonical_hash(body)}
    )
    request._database_read_verified = True
    return request


def _request_with_candidates(
    source: CohortAccumulationRequestV22,
    candidates: list[dict],
) -> CohortAccumulationRequestV22:
    body = source.model_dump(mode="json", by_alias=True)
    body.pop("requestContentHash")
    body["decisionDates"] = candidates
    request = CohortAccumulationRequestV22.model_validate(
        {**body, "requestContentHash": canonical_hash(body)}
    )
    request._database_read_verified = source._database_read_verified
    return request


def _candidate_with_change(
    source: CohortDecisionDateCandidateV22,
    **updates,
) -> dict:
    body = source.model_dump(mode="json", by_alias=True)
    body.pop("candidateContentHash")
    body.update(updates)
    return {**body, "candidateContentHash": canonical_hash(body)}


def _candidate_with_enrollment_change(
    source: CohortDecisionDateCandidateV22,
    update: Callable[[dict[str, Any]], None],
) -> dict:
    body = source.model_dump(mode="json", by_alias=True)
    body.pop("candidateContentHash")
    enrollment_body = dict(body["enrollment"])
    enrollment_body.pop("enrollmentContentHash")
    update(enrollment_body)
    draft = ForwardDqvEnrollmentV211.model_validate(
        {
            **enrollment_body,
            "enrollmentContentHash": "sha256:" + "0" * 64,
        }
    )
    enrollment = ForwardDqvEnrollmentV211.model_validate(
        sealed_model_payload(draft, "enrollmentContentHash")
    )
    body["enrollment"] = enrollment.model_dump(mode="json", by_alias=True)
    return {**body, "candidateContentHash": canonical_hash(body)}


def _verify(
    request: CohortAccumulationRequestV22,
    plan: dict,
) -> None:
    with patch.object(
        prospective_cohort_controller_v22,
        "_v19_binding",
        return_value=plan["v19ChronologyAcceptance"],
    ):
        verify_prospective_cohort_plan_v22(
            repository_root=REPOSITORY_ROOT,
            request=request,
            artifact=plan,
        )


def test_contract_fixture_never_claims_matured_or_formal_evidence() -> None:
    request, plan = _plan()

    _verify(request, plan)
    assert request._database_read_verified is False
    assert plan["distinctDecisionDateCount"] == 2
    assert plan["plannedAssessedSecurityDecisionCount"] == 106
    assert plan["plannedDecisionThresholdReached"] is True
    assert plan["differentDatesDeduplicated"] is False
    assert plan["stablePublicSecurityIdCount"] == 66
    assert all(row["securityCount"] == 66 for row in plan["decisionDates"])
    assert all(
        row["formalIndependentEligibleSecurityDecisions"] == 0
        for row in plan["horizonSchedules"]
    )
    assert all(
        row["formalIndependentCohortThresholdReached"] is False
        for row in plan["horizonSchedules"]
    )
    assert plan["executionBoundary"]["enrollmentExecuted"] is False
    assert all(
        row["enrollmentExecuted"] is False for row in plan["decisionDates"]
    )


def test_db_backed_dates_reach_formal_short_horizon_thresholds() -> None:
    request, plan = _plan(_persisted_request())
    assert all(
        row["formalIndependentEligibleSecurityDecisions"] == 106
        for row in plan["horizonSchedules"]
    )
    by_horizon = {
        row["completedSessions"]: row for row in plan["horizonSchedules"]
    }
    assert by_horizon[5]["formalIndependentCohortThresholdReached"] is True
    assert by_horizon[20]["formalIndependentCohortThresholdReached"] is True
    assert by_horizon[60]["formalIndependentCohortThresholdReached"] is True
    assert by_horizon[126]["formalIndependentCohortThresholdReached"] is False
    assert by_horizon[252]["formalIndependentCohortThresholdReached"] is False
    assert by_horizon[252]["maturedCalendarSpanReached"] is False


def test_same_date_exact_replay_is_counted_once_and_is_idempotent() -> None:
    original = build_contract_fixture_request_v22()
    candidate_rows = [
        item.model_dump(mode="json", by_alias=True)
        for item in original.decision_dates
    ]
    candidate_rows.append(candidate_rows[0])
    request = _request_with_candidates(original, candidate_rows)
    _, plan = _plan(request)
    _, repeated = _plan(request)

    assert plan["sameDateExactReplayCount"] == 1
    assert plan["distinctDecisionDateCount"] == 2
    assert plan["plannedAssessedSecurityDecisionCount"] == 106
    assert verify_idempotent_cohort_plan_replay_v22(plan, repeated) == (
        "EXACT_REPLAY"
    )


def test_same_date_hash_drift_is_rejected_as_a_conflict() -> None:
    original = build_contract_fixture_request_v22()
    first, second = original.decision_dates
    changed = _candidate_with_change(
        second,
        completedSession=first.completed_session.isoformat(),
    )
    request = _request_with_candidates(
        original,
        [
            first.model_dump(mode="json", by_alias=True),
            changed,
        ],
    )

    with pytest.raises(
        ProspectiveCohortControllerError,
        match="SAME_DECISION_DATE_IDEMPOTENCY_CONFLICT",
    ):
        _plan(request)


def test_incomplete_session_is_rejected_before_any_schedule_is_built() -> None:
    original = build_contract_fixture_request_v22()
    first = original.decision_dates[0]
    close = UnitedStatesMarketCalendar().session_close(
        first.completed_session
    )
    changed = _candidate_with_change(
        first,
        calendarVerifiedAt=close,
    )
    request = _request_with_candidates(original, [changed])

    with pytest.raises(
        ProspectiveCohortControllerError,
        match="DECISION_SESSION_NOT_COMPLETED_AND_CALENDAR_VERIFIED",
    ):
        _plan(request)


def test_overlapping_dates_preserve_raw_count_but_fail_independent_schedules() -> None:
    request = _persisted_request(
        build_contract_fixture_request_v22(
            decision_sessions=(date(2025, 1, 15), date(2025, 1, 16))
        )
    )
    _, plan = _plan(request)

    assert plan["plannedAssessedSecurityDecisionCount"] == 106
    assert plan["plannedDecisionThresholdReached"] is True
    for schedule in plan["horizonSchedules"]:
        assert (
            schedule["decisionDates"][1][
                "overlapsPriorAcceptedDecisionWindow"
            ]
            is True
        )
        assert (
            schedule["decisionDates"][1][
                "formalIndependentScheduleSelected"
            ]
            is False
        )
        assert schedule["formalIndependentDistinctDecisionDates"] == 1
        assert schedule["formalIndependentEligibleSecurityDecisions"] == 53
        assert schedule["formalIndependentCohortThresholdReached"] is False


def test_two_dates_below_80_percent_coverage_are_not_threshold_ready() -> None:
    request = build_contract_fixture_request_v22(assessed_per_date=50)
    _, plan = _plan(request)

    assert plan["plannedAssessedSecurityDecisionCount"] == 100
    assert plan["plannedDecisionThresholdReached"] is False
    for schedule in plan["horizonSchedules"]:
        assert schedule["formalIndependentCoverageReached"] is False
        assert schedule["formalIndependentCohortThresholdReached"] is False


def test_horizon_eligibility_uses_per_security_matured_evidence() -> None:
    original = _persisted_request()
    candidates = [
        item.model_dump(mode="json", by_alias=True)
        for item in original.decision_dates
    ]
    for row in candidates[1]["securityDecisions"][:3]:
        row.pop("recordContentHash")
        row["horizonOutcomes"][0]["state"] = "MISSING"
        row["recordContentHash"] = canonical_hash(row)
    candidates[1].pop("candidateContentHash")
    candidates[1]["candidateContentHash"] = canonical_hash(candidates[1])
    request = _request_with_candidates(original, candidates)
    _, plan = _plan(request)
    by_horizon = {
        row["completedSessions"]: row for row in plan["horizonSchedules"]
    }

    assert by_horizon[5]["formalIndependentEligibleSecurityDecisions"] == 103
    assert by_horizon[20]["formalIndependentEligibleSecurityDecisions"] == 106


def test_cross_date_enrollment_identity_reuse_is_rejected() -> None:
    original = build_contract_fixture_request_v22()
    first, second = original.decision_dates
    changed = _candidate_with_enrollment_change(
        second,
        lambda body: body.update(
            {"enrollmentId": str(first.enrollment.enrollment_id)}
        ),
    )
    request = _request_with_candidates(
        original,
        [first.model_dump(mode="json", by_alias=True), changed],
    )

    with pytest.raises(
        ProspectiveCohortControllerError,
        match="CROSS_DATE_ENROLLMENT_OR_DECISION_EVIDENCE_REUSED",
    ):
        _plan(request)


def test_maturity_schedule_must_match_the_candidate_session() -> None:
    original = build_contract_fixture_request_v22()
    first = original.decision_dates[0]

    def change_schedule(body: dict[str, Any]) -> None:
        schedule = body["maturitySchedule"][0]
        schedule.pop("scheduleContentHash")
        original_maturity = datetime.fromisoformat(
            schedule["maturesAtCompletedSession"].replace("Z", "+00:00")
        )
        schedule["maturesAtCompletedSession"] = (
            original_maturity + timedelta(hours=1)
        )
        schedule["scheduleContentHash"] = canonical_hash(schedule)

    changed = _candidate_with_enrollment_change(first, change_schedule)
    request = _request_with_candidates(original, [changed])
    with pytest.raises(
        ProspectiveCohortControllerError,
        match="ENROLLMENT_MATURITY_SCHEDULE_DOES_NOT_MATCH_DECISION_SESSION",
    ):
        _plan(request)


def test_unexecuted_preflight_cannot_claim_matured_outcomes() -> None:
    original = _persisted_request()
    candidate = original.decision_dates[0].model_dump(
        mode="json",
        by_alias=True,
    )
    candidate.pop("candidateContentHash")
    candidate["enrollmentExecuted"] = False
    candidate["candidateContentHash"] = canonical_hash(candidate)

    with pytest.raises(ValidationError, match="unexecuted enrollment"):
        CohortDecisionDateCandidateV22.model_validate(candidate)


def test_legacy_v210_enrollment_cannot_enter_the_controller() -> None:
    original = build_contract_fixture_request_v22()
    candidate = original.decision_dates[0].model_dump(
        mode="json",
        by_alias=True,
    )
    candidate["enrollment"]["schemaVersion"] = "FORWARD-DQV-ENROLLMENT-v2.1.0"
    candidate.pop("candidateContentHash")
    candidate["candidateContentHash"] = canonical_hash(candidate)

    with pytest.raises(ValidationError):
        CohortDecisionDateCandidateV22.model_validate(candidate)


def test_controller_never_executes_provider_db_model_enrollment_or_outcome() -> None:
    _, plan = _plan()

    assert plan["acceptedEnrollmentContract"] == (
        "FORWARD-DQV-ENROLLMENT-v2.1.1"
    )
    assert plan["status"] == "OFFLINE_COHORT_PLAN_READY"
    assert plan["nextAction"] == (
        "WAIT_FOR_AUTHORIZED_REAL_POST_CLOSE_EVIDENCE"
    )
    assert plan["executionBoundary"] == {
        "providerNetworkRequests": 0,
        "databaseReads": 0,
        "databaseWrites": 0,
        "modelReruns": 0,
        "scoresOrRanksComputed": False,
        "enrollmentExecuted": False,
        "outcomesComputed": False,
        "schedulerCreated": False,
        "cloudResourcesCreated": False,
        "automaticTradingAuthorized": False,
    }
    assert all(
        row["enrollmentExecuted"] is False for row in plan["decisionDates"]
    )
    assert all(
        row["outcomesComputed"] is False for row in plan["horizonSchedules"]
    )


def test_serialized_persisted_request_without_db_readback_is_rejected() -> None:
    persisted = _persisted_request()
    serialized = persisted.model_dump(mode="json", by_alias=True)
    request = CohortAccumulationRequestV22.model_validate(serialized)
    with pytest.raises(
        ProspectiveCohortControllerError,
        match="PERSISTED_ENROLLMENT_READ_REQUIRES_DATABASE_READBACK",
    ):
        _plan(request)


def test_offline_request_cannot_claim_executed_enrollment() -> None:
    persisted = _persisted_request()
    body = persisted.model_dump(mode="json", by_alias=True)
    body["purpose"] = "OFFLINE_PREFLIGHT"
    body.pop("requestContentHash")
    with pytest.raises(ValidationError, match="cannot claim executed enrollment"):
        CohortAccumulationRequestV22.model_validate(
            {**body, "requestContentHash": canonical_hash(body)}
        )


def test_coverage_denominator_matches_statistics_terminal_taxonomy() -> None:
    original = _persisted_request()
    candidates = [
        item.model_dump(mode="json", by_alias=True)
        for item in original.decision_dates
    ]
    excluded_states = (
        "NOT_APPLICABLE",
        "SPECIALIZED_MODEL_REQUIRED",
        "EXCLUDED",
    )
    for row, state in zip(
        candidates[0]["securityDecisions"][-3:],
        excluded_states,
        strict=True,
    ):
        row.pop("recordContentHash")
        outcome = row["horizonOutcomes"][0]
        outcome["state"] = state
        outcome["securityOutcomeRecordHash"] = canonical_hash(
            {"state": state, "publicSecurityId": row["publicSecurityId"]}
        )
        row["recordContentHash"] = canonical_hash(row)
    candidates[0].pop("candidateContentHash")
    candidates[0]["candidateContentHash"] = canonical_hash(candidates[0])
    request = _request_with_candidates(original, candidates)
    _, plan = _plan(request)
    horizon = next(
        row for row in plan["horizonSchedules"] if row["completedSessions"] == 5
    )
    first = horizon["decisionDates"][0]
    assert first["maturedCoverageDenominator"] == 63
    assert first["maturedAssessedSecurityDecisions"] == 53
    assert first["minimumCoverageReached"] is True


def test_each_date_must_match_preregistration_and_benchmark_contract() -> None:
    original = build_contract_fixture_request_v22()
    first, second = original.decision_dates
    prereg_drift = _candidate_with_enrollment_change(
        second,
        lambda body: body.update(
            {"preregistrationContentHash": "sha256:" + "c" * 64}
        ),
    )
    request = _request_with_candidates(
        original,
        [first.model_dump(mode="json", by_alias=True), prereg_drift],
    )
    with pytest.raises(
        ProspectiveCohortControllerError,
        match="COHORT_FROZEN_CONTRACT_HASH_DRIFT",
    ):
        _plan(request)

    benchmark_drift = _candidate_with_enrollment_change(
        second,
        lambda body: body.update({"benchmarkContractVersion": "unexpected-v1"}),
    )
    request = _request_with_candidates(
        original,
        [first.model_dump(mode="json", by_alias=True), benchmark_drift],
    )
    with pytest.raises(
        ProspectiveCohortControllerError,
        match="COHORT_FROZEN_CONTRACT_HASH_DRIFT",
    ):
        _plan(request)


def test_immutable_writer_accepts_exact_replay_and_rejects_drift(
    tmp_path: Path,
) -> None:
    _, plan = _plan()
    path = tmp_path / "cohort-plan.json"

    first = write_immutable_cohort_plan_v22(path, plan)
    second = write_immutable_cohort_plan_v22(path, plan)
    assert first == second

    changed = dict(plan)
    changed["eligibleSecurityDecisionCount"] = 99
    changed_body = dict(changed)
    changed_body.pop("artifactContentHash")
    changed["artifactContentHash"] = canonical_hash(changed_body)
    with pytest.raises(
        ProspectiveCohortControllerError,
        match="idempotency conflict",
    ):
        write_immutable_cohort_plan_v22(path, changed)
