from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.forward_validation.models import EnrollmentAccepted
from equity_analysis.forward_validation.prospective_enrollment_v1 import (
    ProspectiveDecisionState,
    ProspectiveEnrollmentRepository,
    ProspectiveEnrollmentRequest,
    ProspectiveEnrollmentStatus,
    ProspectiveMaturityStatus,
    ProspectiveSecurityDecision,
)

AS_OF = datetime(2026, 7, 28, 22, tzinfo=UTC)
DATA_SNAPSHOT_ID = UUID("f58a7566-26fb-49c0-b724-1d049e2cecf2")
PROFILE_ID = UUID("5853521d-d021-43c0-8169-2cc5fefcf281")
SECURITY_ID = UUID("7a793a85-b294-4b5e-ada0-83777bbf5cc3")
RUN_ID = UUID("4bcd5efb-11d5-456a-a137-b10d121690e3")
EXPERIMENT_ID = UUID("2b66e5bd-e231-4743-b89b-374db6b68738")
ATTEMPT_ID = UUID("a4fbd69e-f89c-48c9-a2b2-f890fd560b11")
ENROLLMENT_ID = UUID("84c59402-ec19-46db-9058-f5395707719d")
EVENT_HASH = "sha256:" + "a" * 64


class _FakeForwardRepository:
    def __init__(self, signal_count: int = 1) -> None:
        self.signal_count = signal_count
        self.calls: list[tuple[Any, ...]] = []

    def enroll(self, *args: Any) -> EnrollmentAccepted:
        self.calls.append(args)
        return EnrollmentAccepted(
            enrollment_id=str(ENROLLMENT_ID),
            signal_count=self.signal_count,
            sealed_at=AS_OF,
            input_hash="sha256:" + "b" * 64,
        )


class _InMemoryProspectiveRepository(ProspectiveEnrollmentRepository):
    def __init__(
        self,
        snapshot: dict[str, Any],
        forward_repository: _FakeForwardRepository,
    ) -> None:
        self.snapshot = snapshot
        self._forward_repository = forward_repository
        self._calendar = UnitedStatesMarketCalendar()
        self.observation_calls: list[tuple[UUID, datetime]] = []
        self.persisted_detail: dict[str, Any] | None = None

    def _existing(self, idempotency_key: str, request_hash: str) -> None:
        return None

    def _load_and_verify_snapshot(
        self,
        request: ProspectiveEnrollmentRequest,
    ) -> dict[str, Any]:
        return self.snapshot

    def _persist_not_matured_observations(
        self,
        *,
        enrollment_id: UUID,
        decision_as_of: datetime,
    ) -> None:
        self.observation_calls.append((enrollment_id, decision_as_of))

    def _persist_attempt(self, **kwargs: Any) -> UUID:
        self.persisted_detail = kwargs["detail"]
        return ATTEMPT_ID


def _request(*, with_experiment: bool = False) -> ProspectiveEnrollmentRequest:
    return ProspectiveEnrollmentRequest(
        decision_snapshot_event_hash=EVENT_HASH,
        market_intelligence_screening_run_ids=(RUN_ID,),
        idempotency_key="prospective-enrollment-v1-fixture",
        experiment_id=EXPERIMENT_ID if with_experiment else None,
    )


def _decision(state: ProspectiveDecisionState) -> ProspectiveSecurityDecision:
    return ProspectiveSecurityDecision(
        profile_id=PROFILE_ID,
        security_id=SECURITY_ID,
        symbol="AAPL",
        state=state,
        exclusion_reasons=(
            ("NO_ELIGIBLE_RESULT",)
            if state == ProspectiveDecisionState.EXCLUDED
            else ()
        ),
        long_horizon_context_hash="sha256:" + "c" * 64,
    )


def _snapshot(
    *,
    eligible_count: int,
    blocked_reasons: tuple[str, ...] = (),
) -> dict[str, Any]:
    is_eligible = eligible_count > 0
    return {
        "dataSnapshotId": DATA_SNAPSHOT_ID,
        "decisionAsOf": AS_OF,
        "objectiveScreeningRunId": str(RUN_ID) if is_eligible else None,
        "profileCount": 1,
        "eligibleCount": eligible_count,
        "excludedCount": 0 if is_eligible else 1,
        "decisions": (
            _decision(
                ProspectiveDecisionState.ELIGIBLE
                if is_eligible
                else ProspectiveDecisionState.EXCLUDED
            ),
        ),
        "blockedReasons": blocked_reasons,
    }


def test_no_eligible_snapshot_is_sealed_without_creating_forward_signals() -> None:
    forward = _FakeForwardRepository()
    repository = _InMemoryProspectiveRepository(
        _snapshot(eligible_count=0),
        forward,
    )

    accepted = repository.enroll(_request())

    assert accepted.status == ProspectiveEnrollmentStatus.NO_ELIGIBLE_SIGNALS
    assert accepted.signal_count == 0
    assert accepted.forward_enrollment_id is None
    assert forward.calls == []
    assert repository.observation_calls == []
    assert [item.trading_days for item in accepted.maturity_schedule] == [5, 20, 60]
    assert [item.matures_on.isoformat() for item in accepted.maturity_schedule] == [
        "2026-08-04T20:00:00+00:00",
        "2026-08-25T20:00:00+00:00",
        "2026-10-21T20:00:00+00:00",
    ]
    assert all(
        item.status == ProspectiveMaturityStatus.NOT_APPLICABLE
        for item in accepted.maturity_schedule
    )
    assert accepted.long_horizon_is_context_only is True
    assert repository.persisted_detail is not None
    assert repository.persisted_detail["providerNetworkRequests"] == 0
    assert repository.persisted_detail["aiUsedForEnrollment"] is False


def test_eligible_snapshot_stays_blocked_without_legacy_compatibility() -> None:
    forward = _FakeForwardRepository()
    repository = _InMemoryProspectiveRepository(
        _snapshot(
            eligible_count=1,
            blocked_reasons=("COMPATIBLE_OBJECTIVE_SCREENING_RUN_REQUIRED",),
        ),
        forward,
    )

    accepted = repository.enroll(_request())

    assert accepted.status == ProspectiveEnrollmentStatus.BLOCKED
    assert accepted.blocked_reasons == (
        "COMPATIBLE_OBJECTIVE_SCREENING_RUN_REQUIRED",
    )
    assert forward.calls == []
    assert repository.observation_calls == []
    assert all(
        item.status == ProspectiveMaturityStatus.NOT_APPLICABLE
        for item in accepted.maturity_schedule
    )


def test_compatible_legacy_run_delegates_and_schedules_only_frozen_horizons() -> None:
    forward = _FakeForwardRepository(signal_count=2)
    repository = _InMemoryProspectiveRepository(
        _snapshot(eligible_count=1),
        forward,
    )

    accepted = repository.enroll(_request(with_experiment=True))

    assert accepted.status == ProspectiveEnrollmentStatus.ENROLLED
    assert accepted.forward_enrollment_id == ENROLLMENT_ID
    assert accepted.signal_count == 2
    assert len(forward.calls) == 1
    experiment_id, enrollment_request, idempotency_key = forward.calls[0]
    assert experiment_id == EXPERIMENT_ID
    assert enrollment_request.screening_run_id == str(RUN_ID)
    assert enrollment_request.enrollment_time == AS_OF
    assert idempotency_key.endswith(":prospective-enrollment-v1-fixture")
    assert repository.observation_calls == [(ENROLLMENT_ID, AS_OF)]
    assert [(item.horizon, item.trading_days) for item in accepted.maturity_schedule] == [
        ("ONE_WEEK", 5),
        ("ONE_MONTH", 20),
        ("THREE_MONTHS", 60),
    ]
    assert all(
        item.status == ProspectiveMaturityStatus.NOT_MATURED
        for item in accepted.maturity_schedule
    )
    assert all("12" not in item.horizon for item in accepted.maturity_schedule)


def test_request_rejects_duplicate_market_intelligence_runs() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        ProspectiveEnrollmentRequest(
            decision_snapshot_event_hash=EVENT_HASH,
            market_intelligence_screening_run_ids=(RUN_ID, RUN_ID),
            idempotency_key="duplicate-run-fixture",
        )
