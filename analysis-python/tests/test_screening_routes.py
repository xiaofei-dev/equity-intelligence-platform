from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from equity_analysis.main import app
from equity_analysis.screening.models import (
    CoverageSummary,
    RatingPage,
    RunStatus,
    ScreeningRunAccepted,
    ScreeningRunStatus,
)
from equity_analysis.screening.routes import get_repository

RUN_ID = UUID("00000000-0000-0000-0000-000000000001")
AS_OF = datetime(2026, 7, 25, 20, 0, tzinfo=UTC)


class FakeRepository:
    def __init__(self) -> None:
        self.idempotency_key = None

    def create_run(self, _request, idempotency_key):
        self.idempotency_key = idempotency_key
        return ScreeningRunAccepted(
            run_id=str(RUN_ID),
            status=RunStatus.PENDING,
            submitted_at=AS_OF,
        )

    def execute(self, _run_id):
        return None

    def get_status(self, run_id):
        return ScreeningRunStatus(
            run_id=str(run_id),
            status=RunStatus.SUCCEEDED,
            as_of_time=AS_OF,
            data_snapshot_id="snapshot-2026-07-25",
            universe_version="universe-us-general-company-v1.0.0",
            strategy_versions=("QC-v1.0.0", "UQ-v1.0.0"),
            coverage=CoverageSummary(
                universe_count=20,
                scored_count=5,
                ineligible_count=1,
                insufficient_data_count=4,
                specialized_model_count=10,
            ),
        )

    def ratings(self, run_id, _cursor, _limit):
        return RatingPage(run_id=str(run_id), items=())


def test_create_status_and_rating_routes_share_the_versioned_contract() -> None:
    repository = FakeRepository()
    app.dependency_overrides[get_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/v1/screening/runs",
                headers={"Idempotency-Key": "screening-acceptance-1"},
                json={
                    "asOfTime": AS_OF.isoformat(),
                    "dataSnapshotId": "snapshot-2026-07-25",
                    "universeVersion": "universe-us-general-company-v1.0.0",
                    "strategyVersions": ["QC-v1.0.0", "UQ-v1.0.0"],
                    "includeNearTermMarketCondition": True,
                },
            )
            assert response.status_code == 202
            assert response.json()["runId"] == str(RUN_ID)
            assert repository.idempotency_key == "screening-acceptance-1"

            status = client.get(f"/internal/v1/screening/runs/{RUN_ID}")
            assert status.status_code == 200
            assert status.json()["coverage"]["universeCount"] == 20

            ratings = client.get(f"/internal/v1/screening/runs/{RUN_ID}/ratings")
            assert ratings.status_code == 200
            assert ratings.json()["items"] == []
    finally:
        app.dependency_overrides.clear()


def test_create_requires_idempotency_key() -> None:
    app.dependency_overrides[get_repository] = FakeRepository
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/v1/screening/runs",
                json={
                    "asOfTime": AS_OF.isoformat(),
                    "dataSnapshotId": "snapshot-2026-07-25",
                    "universeVersion": "universe-us-general-company-v1.0.0",
                    "strategyVersions": ["QC-v1.0.0"],
                },
            )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    finally:
        app.dependency_overrides.clear()
