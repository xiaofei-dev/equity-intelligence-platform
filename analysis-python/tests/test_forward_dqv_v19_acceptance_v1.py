from __future__ import annotations

from pathlib import Path

import pytest

from equity_analysis.forward_validation.v19_acceptance_v1 import (
    ForwardDqvV19AcceptanceError,
    build_forward_dqv_v19_acceptance,
    verify_forward_dqv_v19_acceptance,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _artifact() -> dict:
    return build_forward_dqv_v19_acceptance(
        REPOSITORY_ROOT,
        focused_python_passed=19,
        postgres_tests_passed=2,
    )


def test_v19_acceptance_binds_sources_and_fixed_chronology() -> None:
    artifact = _artifact()

    assert (
        verify_forward_dqv_v19_acceptance(artifact, REPOSITORY_ROOT)
        == artifact["artifactContentHash"]
    )
    assert artifact["chronologyConstraintValidated"] is True
    assert artifact["legacyEnrollmentAdapterReady"] is False
    assert artifact["prospectiveEnrollmentAdapterV211Ready"] is True


def test_v19_acceptance_rejects_source_or_chronology_drift() -> None:
    artifact = _artifact()
    artifact["chronology"]["sealNoLaterThanEntryOpen"] = False

    with pytest.raises(
        ForwardDqvV19AcceptanceError,
        match="V19_ACCEPTANCE_HASH_MISMATCH",
    ):
        verify_forward_dqv_v19_acceptance(artifact, REPOSITORY_ROOT)
