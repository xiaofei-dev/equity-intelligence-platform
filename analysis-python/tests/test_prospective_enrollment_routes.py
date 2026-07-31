from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from equity_analysis.forward_validation.prospective_enrollment_v1 import (
    ProspectiveDecisionState,
    ProspectiveEnrollmentAccepted,
    ProspectiveEnrollmentConflictError,
    ProspectiveEnrollmentSnapshotError,
    ProspectiveEnrollmentStatus,
    ProspectiveMaturitySchedule,
    ProspectiveMaturityStatus,
    ProspectiveSecurityDecision,
)
from equity_analysis.forward_validation.routes import get_prospective_repository
from equity_analysis.main import app

ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000031")
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000032")
RUN_ID = UUID("00000000-0000-0000-0000-000000000033")
PROFILE_ID = UUID("00000000-0000-0000-0000-000000000034")
SECURITY_ID = UUID("00000000-0000-0000-0000-000000000035")
DECISION_HASH = "sha256:" + "a" * 64
ATTEMPT_HASH = "sha256:" + "b" * 64
CONTEXT_HASH = "sha256:" + "c" * 64
DECISION_AS_OF = datetime(2026, 7, 29, 2, tzinfo=UTC)


def _accepted(
    status: ProspectiveEnrollmentStatus = ProspectiveEnrollmentStatus.BLOCKED,
) -> ProspectiveEnrollmentAccepted:
    return ProspectiveEnrollmentAccepted(
        attempt_id=ATTEMPT_ID,
        attempt_hash=ATTEMPT_HASH,
        decision_snapshot_event_hash=DECISION_HASH,
        status=status,
        data_snapshot_id=SNAPSHOT_ID,
        decision_as_of=DECISION_AS_OF,
        profile_count=1,
        eligible_count=1 if status == ProspectiveEnrollmentStatus.BLOCKED else 0,
        excluded_count=0 if status == ProspectiveEnrollmentStatus.BLOCKED else 1,
        signal_count=0,
        maturity_schedule=tuple(
            ProspectiveMaturitySchedule(
                horizon=label,
                trading_days=days,
                matures_on=DECISION_AS_OF,
                status=ProspectiveMaturityStatus.NOT_APPLICABLE,
            )
            for label, days in (
                ("ONE_WEEK", 5),
                ("ONE_MONTH", 20),
                ("THREE_MONTHS", 60),
            )
        ),
        decisions=(
            ProspectiveSecurityDecision(
                profile_id=PROFILE_ID,
                security_id=SECURITY_ID,
                symbol="AAPL",
                state=(
                    ProspectiveDecisionState.ELIGIBLE
                    if status == ProspectiveEnrollmentStatus.BLOCKED
                    else ProspectiveDecisionState.EXCLUDED
                ),
                exclusion_reasons=(
                    ()
                    if status == ProspectiveEnrollmentStatus.BLOCKED
                    else ("OBJECTIVE_RATING_NOT_SCORE_ELIGIBLE",)
                ),
                long_horizon_context_hash=CONTEXT_HASH,
            ),
        ),
        blocked_reasons=(
            ("COMPATIBLE_OBJECTIVE_SCREENING_RUN_REQUIRED",)
            if status == ProspectiveEnrollmentStatus.BLOCKED
            else ()
        ),
        long_horizon_is_context_only=True,
    )


class FakeProspectiveRepository:
    result = _accepted()
    create_error: Exception | None = None

    def enroll(self, request):
        assert request.idempotency_key == "attempt-key-1"
        assert request.market_intelligence_screening_run_ids == (RUN_ID,)
        if self.create_error is not None:
            raise self.create_error
        return self.result

    def get(self, attempt_id):
        assert attempt_id == ATTEMPT_ID
        return self.result

    def latest(self):
        return self.result


def _payload() -> dict[str, object]:
    return {
        "decisionSnapshotEventHash": DECISION_HASH,
        "marketIntelligenceScreeningRunIds": [str(RUN_ID)],
    }


def test_legacy_post_route_is_hard_blocked_before_repository_access() -> None:
    repository = FakeProspectiveRepository()
    app.dependency_overrides[get_prospective_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/v1/forward-validation/prospective-enrollments",
                headers={"Idempotency-Key": "attempt-key-1"},
                json=_payload(),
            )
        assert response.status_code == 410
        assert (
            response.json()["detail"]["code"]
            == "LEGACY_PROSPECTIVE_ENROLLMENT_DISABLED"
        )
    finally:
        app.dependency_overrides.clear()


def test_legacy_post_route_remains_blocked_for_any_old_repository_state() -> None:
    repository = FakeProspectiveRepository()
    repository.result = _accepted(ProspectiveEnrollmentStatus.NO_ELIGIBLE_SIGNALS)
    app.dependency_overrides[get_prospective_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/v1/forward-validation/prospective-enrollments",
                headers={"Idempotency-Key": "attempt-key-1"},
                json=_payload(),
            )
        assert response.status_code == 410
        assert (
            response.json()["detail"]["code"]
            == "LEGACY_PROSPECTIVE_ENROLLMENT_DISABLED"
        )
    finally:
        app.dependency_overrides.clear()


def test_legacy_post_error_state_cannot_bypass_hard_block() -> None:
    repository = FakeProspectiveRepository()
    app.dependency_overrides[get_prospective_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            repository.create_error = ProspectiveEnrollmentConflictError("conflict")
            conflict = client.post(
                "/internal/v1/forward-validation/prospective-enrollments",
                headers={"Idempotency-Key": "attempt-key-1"},
                json=_payload(),
            )
            repository.create_error = ProspectiveEnrollmentSnapshotError("snapshot")
            invalid = client.post(
                "/internal/v1/forward-validation/prospective-enrollments",
                headers={"Idempotency-Key": "attempt-key-1"},
                json=_payload(),
            )
            repository.result = None
            missing = client.get(
                f"/internal/v1/forward-validation/prospective-enrollments/{ATTEMPT_ID}"
            )
        assert conflict.status_code == 410
        assert (
            conflict.json()["detail"]["code"]
            == "LEGACY_PROSPECTIVE_ENROLLMENT_DISABLED"
        )
        assert invalid.status_code == 410
        assert (
            invalid.json()["detail"]["code"]
            == "LEGACY_PROSPECTIVE_ENROLLMENT_DISABLED"
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "PROSPECTIVE_ENROLLMENT_NOT_FOUND"
    finally:
        app.dependency_overrides.clear()


def test_latest_route_precedes_uuid_route_and_returns_explicit_not_found() -> None:
    repository = FakeProspectiveRepository()
    app.dependency_overrides[get_prospective_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            latest = client.get(
                "/internal/v1/forward-validation/prospective-enrollments/latest"
            )
            repository.result = None
            missing = client.get(
                "/internal/v1/forward-validation/prospective-enrollments/latest"
            )
        assert latest.status_code == 200
        assert latest.json()["attemptId"] == str(ATTEMPT_ID)
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "PROSPECTIVE_ENROLLMENT_NOT_FOUND"
    finally:
        app.dependency_overrides.clear()
