from __future__ import annotations

from datetime import timedelta

import pytest
from test_forward_outcomes_v21 import enrollment as legacy_enrollment

from equity_analysis.forward_validation.outcomes_v21 import sealed_model_payload
from equity_analysis.forward_validation.outcomes_v211 import (
    FORWARD_DQV_ENROLLMENT_V211,
    ForwardDqvEnrollmentV211,
    verify_enrollment_v211,
)


def _v211(*, seal_offset_minutes: int) -> ForwardDqvEnrollmentV211:
    legacy = legacy_enrollment()
    body = legacy.model_dump(mode="python", by_alias=True)
    body["schemaVersion"] = FORWARD_DQV_ENROLLMENT_V211
    body["sealedAt"] = (
        legacy.effective_at_completed_session_open
        + timedelta(minutes=seal_offset_minutes)
    )
    body["enrollmentContentHash"] = "sha256:" + "0" * 64
    draft = ForwardDqvEnrollmentV211.model_validate(body)
    return ForwardDqvEnrollmentV211.model_validate(
        sealed_model_payload(draft, "enrollmentContentHash")
    )


def test_v211_accepts_seal_before_entry_and_verifies_hash() -> None:
    enrollment = _v211(seal_offset_minutes=-1)

    verify_enrollment_v211(enrollment)
    assert enrollment.schema_version == FORWARD_DQV_ENROLLMENT_V211
    assert enrollment.decision_as_of <= enrollment.sealed_at
    assert enrollment.sealed_at <= enrollment.effective_at_completed_session_open


def test_v211_rejects_seal_after_entry_open() -> None:
    with pytest.raises(
        ValueError,
        match="sealed no later than the completed-session entry open",
    ):
        _v211(seal_offset_minutes=1)


def test_v211_rejects_legacy_schema_version() -> None:
    legacy = legacy_enrollment().model_dump(mode="python", by_alias=True)

    with pytest.raises(ValueError):
        ForwardDqvEnrollmentV211.model_validate(legacy)
