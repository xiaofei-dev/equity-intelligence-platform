from __future__ import annotations

import copy
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from equity_analysis.historical_validation.model_freeze_v1 import (
    FIXED_RANDOM_SEED,
    FROZEN_AT,
    LONG_HORIZON_TRACK,
    OBSERVED_EVIDENCE_CUTOFF,
    SOURCE_FINALIZATION_OBSERVED_AT,
    TACTICAL_TRACK,
    _load_licensed_artifact_receipts,
    build_model_freeze_artifact,
    canonical_hash,
    matches_bound_file_sha256,
    validate_generation_chronology,
    verify_model_freeze_artifact,
    write_immutable_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("track", "model_version", "horizon"),
    (
        (TACTICAL_TRACK, "TACTICAL-SIGNAL-v2.2.0", 60),
        (LONG_HORIZON_TRACK, "LONG-HORIZON-RESEARCH-v1.1.0", 252),
    ),
)
def test_freeze_binds_model_and_validation_boundaries(
    track: str,
    model_version: str,
    horizon: int,
) -> None:
    artifact = build_model_freeze_artifact(REPO_ROOT, track)

    assert artifact["modelVersion"] == model_version
    assert artifact["freezeRecord"]["model_version"] == model_version
    assert artifact["freezeRecord"]["random_seed"] == FIXED_RANDOM_SEED
    assert artifact["freezeRecord"]["maximum_horizon_sessions"] == horizon
    assert artifact["freezeRecord"]["purge_sessions"] == horizon
    assert artifact["freezeRecord"]["embargo_sessions"] == horizon
    assert artifact["contracts"]["sampling"]["maximumHorizonSessions"] == horizon
    assert artifact["contracts"]["sampling"]["purgeSessions"] == horizon
    assert artifact["contracts"]["sampling"]["embargoSessions"] == horizon
    assert artifact["contracts"]["benchmark"]["formalGateStopsOnUnavailableBenchmark"]
    assert artifact["contracts"]["universe"]["completePopulationRequiredAtEveryDecision"]
    chronology = artifact["freezeChronology"]
    assert datetime.fromisoformat(chronology["observedEvidenceCutoff"]) == (
        OBSERVED_EVIDENCE_CUTOFF
    )
    assert datetime.fromisoformat(chronology["sourceFinalizationObservedAt"]) == (
        SOURCE_FINALIZATION_OBSERVED_AT
    )
    assert datetime.fromisoformat(chronology["frozenAt"]) == FROZEN_AT
    assert OBSERVED_EVIDENCE_CUTOFF < SOURCE_FINALIZATION_OBSERVED_AT < FROZEN_AT
    assert chronology["stableVerificationUsesContentHashesNotCheckoutMtime"] is True


@pytest.mark.parametrize("track", (TACTICAL_TRACK, LONG_HORIZON_TRACK))
def test_observed_history_is_never_an_untouched_holdout(track: str) -> None:
    artifact = build_model_freeze_artifact(REPO_ROOT, track)
    evidence = artifact["observedHistoricalEvidence"]

    assert evidence["evaluationRole"] == "DEVELOPMENT_OBSERVED"
    assert evidence["untouchedHoldoutAvailable"] is False
    assert evidence["artifacts"]
    assert all(item["untouchedHoldout"] is False for item in evidence["artifacts"])
    assert artifact["execution"] == {
        "networkRequestsExecuted": False,
        "historicalScoringExecuted": False,
        "forwardValidationExecuted": False,
        "databaseMigrationExecuted": False,
    }


@pytest.mark.parametrize("track", (TACTICAL_TRACK, LONG_HORIZON_TRACK))
def test_all_source_hashes_and_canonical_hashes_recompute(track: str) -> None:
    artifact = build_model_freeze_artifact(REPO_ROOT, track)

    verify_model_freeze_artifact(REPO_ROOT, artifact)
    content = copy.deepcopy(artifact)
    content_hash = content.pop("artifactContentHash")
    assert canonical_hash(content) == content_hash


def test_contract_change_invalidates_artifact_hash() -> None:
    artifact = build_model_freeze_artifact(REPO_ROOT, TACTICAL_TRACK)
    changed = copy.deepcopy(artifact)
    changed["contracts"]["acceptance"]["minimumCoverageRatio"] = "0.79"
    changed.pop("artifactContentHash")

    assert canonical_hash(changed) != artifact["artifactContentHash"]


def test_initial_generation_chronology_uses_source_time_not_checkout_time(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    observed_time = SOURCE_FINALIZATION_OBSERVED_AT - timedelta(seconds=1)
    os.utime(source, (observed_time.timestamp(), observed_time.timestamp()))

    latest = validate_generation_chronology(tmp_path, ("source.py",))

    assert latest <= SOURCE_FINALIZATION_OBSERVED_AT < FROZEN_AT

    changed_time = SOURCE_FINALIZATION_OBSERVED_AT + timedelta(seconds=1)
    os.utime(source, (changed_time.timestamp(), changed_time.timestamp()))
    with pytest.raises(
        ValueError,
        match="modified after sourceFinalizationObservedAt",
    ):
        validate_generation_chronology(tmp_path, ("source.py",))


def test_stable_verification_does_not_depend_on_checkout_mtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = build_model_freeze_artifact(REPO_ROOT, LONG_HORIZON_TRACK)

    def fail_if_called(*_args: object, **_kwargs: object) -> datetime:
        raise AssertionError("stable verification must not inspect checkout mtimes")

    monkeypatch.setattr(
        "equity_analysis.historical_validation.model_freeze_v1."
        "validate_generation_chronology",
        fail_if_called,
    )
    verify_model_freeze_artifact(REPO_ROOT, artifact)


def test_legacy_trailing_lf_source_binding_is_narrowly_compatible() -> None:
    relative_path = (
        "analysis-python/src/equity_analysis/historical_validation/"
        "walk_forward_v2.py"
    )

    assert matches_bound_file_sha256(
        REPO_ROOT / relative_path,
        "45D4DBDD0E7A643658B160AE5B044C15A4A07113DC33382A3DE87DDFF3D72F0F",
        relative_path=relative_path,
    )
    assert not matches_bound_file_sha256(
        REPO_ROOT / relative_path,
        "F" * 64,
        relative_path=relative_path,
    )


def test_license_safe_receipts_preserve_only_historical_bindings() -> None:
    receipts = _load_licensed_artifact_receipts(REPO_ROOT)

    assert receipts == {
        (
            "docs/generated/"
            "long-horizon-historical-stratified-validation-v1-4-2026-07-29.json"
        ): "B88253CF9F04FF33C25EFD2DE79BE6A516AF03DC3A44271A26B1236E7941F058",
        (
            "docs/generated/"
            "tactical-historical-stratified-validation-v1-1-2026-07-29.json"
        ): "90A93563A9B4B087FF71FF33074D4D16C160476450E423E02A20976AAB298880",
    }
    for track in (TACTICAL_TRACK, LONG_HORIZON_TRACK):
        artifact = build_model_freeze_artifact(REPO_ROOT, track)
        verify_model_freeze_artifact(REPO_ROOT, artifact)


def test_license_safe_receipt_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    target = (
        tmp_path
        / "docs/generated/licensed-historical-artifact-receipts-v1.json"
    )
    target.parent.mkdir(parents=True)
    target.write_text(
        (
            REPO_ROOT
            / "docs/generated/licensed-historical-artifact-receipts-v1.json"
        )
        .read_text(encoding="utf-8")
        .replace(
            "B88253CF9F04FF33C25EFD2DE79BE6A516AF03DC3A44271A26B1236E7941F058",
            "F" * 64,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="receipt hash does not match",
    ):
        _load_licensed_artifact_receipts(tmp_path)


def test_immutable_writer_refuses_a_changed_existing_artifact(tmp_path: Path) -> None:
    path = tmp_path / "freeze.json"
    artifact = build_model_freeze_artifact(REPO_ROOT, TACTICAL_TRACK)
    write_immutable_artifact(path, artifact)
    write_immutable_artifact(path, artifact)

    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        write_immutable_artifact(path, artifact)


@pytest.mark.parametrize("track", (TACTICAL_TRACK, LONG_HORIZON_TRACK))
def test_git_safe_freeze_contains_no_result_or_provider_value_payload(track: str) -> None:
    artifact = build_model_freeze_artifact(REPO_ROOT, track)
    serialized = str(artifact).lower()

    assert '"value"' not in serialized
    assert "rawprovidervalues" not in serialized
    assert "historicalscoringexecuted': true" not in serialized
    assert "forwardvalidationexecuted': true" not in serialized
