from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient

from equity_analysis.forward_validation.models import (
    EnrollmentAccepted,
    ExperimentMode,
    ExperimentStatus,
    ForwardExperimentAccepted,
    ForwardExperimentStatus,
)
from equity_analysis.forward_validation.routes import get_repository
from equity_analysis.main import app

EXPERIMENT_ID = UUID("00000000-0000-0000-0000-000000000011")
RUN_ID = UUID("00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 7, 31, 21, tzinfo=UTC)


class FakeForwardRepository:
    def create_experiment(self, request, _key):
        assert request.mode == ExperimentMode.DRY_RUN
        return ForwardExperimentAccepted(
            experiment_id=str(EXPERIMENT_ID),
            status=ExperimentStatus.PENDING,
            mode=request.mode,
            submitted_at=NOW,
        )

    def status(self, _experiment_id):
        return ForwardExperimentStatus(
            experiment_id=str(EXPERIMENT_ID),
            status=ExperimentStatus.ACTIVE,
            mode=ExperimentMode.DRY_RUN,
            submitted_at=NOW,
            screening_run_id=str(RUN_ID),
            experiment_version="FORWARD-VALIDATION-v1.0.0",
            entry_policy_version="ENTRY-POLICY-v1.0.0",
            notional_usd=Decimal("10000.00"),
        )

    def enroll(self, _experiment_id, _request, _key):
        return EnrollmentAccepted(
            enrollment_id="enrollment-1",
            signal_count=8,
            sealed_at=NOW,
            input_hash="sha256:enrollment",
        )

    def rows(self, _experiment_id, _table):
        return []

    def report(self, _experiment_id, _report_type):
        return None


def test_forward_routes_default_to_dry_run_and_freeze_enrollment() -> None:
    app.dependency_overrides[get_repository] = FakeForwardRepository
    try:
        with TestClient(app) as client:
            created = client.post(
                "/internal/v1/forward-validation/experiments",
                headers={"Idempotency-Key": "forward-1"},
                json={"screeningRunId": str(RUN_ID)},
            )
            assert created.status_code == 202
            assert created.json()["mode"] == "DRY_RUN"

            enrollment = client.post(
                f"/internal/v1/forward-validation/experiments/{EXPERIMENT_ID}/enrollments",
                headers={"Idempotency-Key": "enrollment-1"},
                json={"screeningRunId": str(RUN_ID), "enrollmentTime": NOW.isoformat()},
            )
            assert enrollment.status_code == 201
            assert enrollment.json()["signalCount"] == 8
    finally:
        app.dependency_overrides.clear()


def test_forward_create_requires_idempotency_key() -> None:
    app.dependency_overrides[get_repository] = FakeForwardRepository
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/v1/forward-validation/experiments",
                json={"screeningRunId": str(RUN_ID)},
            )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    finally:
        app.dependency_overrides.clear()
