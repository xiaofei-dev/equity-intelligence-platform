from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.outcomes_v21 import (
    ContractModel,
    MaturityScheduleV21,
)

FORWARD_DQV_ENROLLMENT_V211 = "FORWARD-DQV-ENROLLMENT-v2.1.1"

_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_HORIZONS = (5, 20, 60, 126, 252)


class ForwardDqvEnrollmentV211(ContractModel):
    """Prospective enrollment that must be sealed before the entry open."""

    schema_version: Literal["FORWARD-DQV-ENROLLMENT-v2.1.1"]
    enrollment_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=255)
    canonical_request_hash: str = Field(pattern=_SHA256_PATTERN)
    preregistration_content_hash: str = Field(pattern=_SHA256_PATTERN)
    decision_manifest_content_hash: str = Field(pattern=_SHA256_PATTERN)
    decision_controlled_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    decision_controlled_artifact_reference: str = Field(min_length=1)
    decision_data_snapshot_id: UUID
    decision_as_of: datetime
    effective_at_completed_session_open: datetime
    universe_version: str = Field(min_length=1)
    frozen_population_hash: str = Field(pattern=_SHA256_PATTERN)
    model_freeze_hashes: dict[str, str]
    benchmark_contract_version: str = Field(min_length=1)
    benchmark_contract_hash: str = Field(pattern=_SHA256_PATTERN)
    cost_policy_version: str = Field(min_length=1)
    cost_policy_hash: str = Field(pattern=_SHA256_PATTERN)
    security_count: int = Field(ge=1)
    terminal_counts: dict[str, int]
    maturity_schedule: tuple[MaturityScheduleV21, ...]
    sealed_at: datetime
    enrollment_content_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def enforce_prospective_enrollment(self) -> ForwardDqvEnrollmentV211:
        decision = _aware(self.decision_as_of, "Decision timestamp")
        entry = _aware(
            self.effective_at_completed_session_open,
            "Prospective entry timestamp",
        )
        sealed = _aware(self.sealed_at, "Seal timestamp")
        if not decision <= sealed <= entry:
            raise ValueError(
                "Prospective enrollment must be decided and sealed no later "
                "than the completed-session entry open"
            )
        sessions = tuple(item.completed_sessions for item in self.maturity_schedule)
        if sessions != _HORIZONS:
            raise ValueError("Enrollment requires ordered 5/20/60/126/252 maturities")
        maturity_times = tuple(
            item.matures_at_completed_session for item in self.maturity_schedule
        )
        if (
            len(set(maturity_times)) != len(_HORIZONS)
            or tuple(sorted(maturity_times)) != maturity_times
            or any(value <= entry for value in maturity_times)
        ):
            raise ValueError(
                "Maturity timestamps must be unique, chronological, and post-entry"
            )
        if (
            not self.model_freeze_hashes
            or any(
                not value.startswith("sha256:")
                for value in self.model_freeze_hashes.values()
            )
        ):
            raise ValueError("Model freeze hashes are required")
        if (
            not self.terminal_counts
            or any(value < 0 for value in self.terminal_counts.values())
            or sum(self.terminal_counts.values()) != self.security_count
        ):
            raise ValueError("Terminal counts must equal the frozen population")
        return self


def verify_enrollment_v211(enrollment: ForwardDqvEnrollmentV211) -> None:
    payload = enrollment.model_dump(mode="json", by_alias=True)
    claimed = payload.pop("enrollmentContentHash")
    if canonical_hash(payload) != claimed:
        raise ValueError("Forward DQV v2.1.1 enrollment canonical hash is invalid")
    for item in enrollment.maturity_schedule:
        schedule = item.model_dump(mode="json", by_alias=True)
        schedule_claimed = schedule.pop("scheduleContentHash")
        if canonical_hash(schedule) != schedule_claimed:
            raise ValueError("Forward DQV maturity canonical hash is invalid")


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)
