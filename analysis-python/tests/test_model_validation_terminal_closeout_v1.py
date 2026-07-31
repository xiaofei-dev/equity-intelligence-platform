from __future__ import annotations

import json
from pathlib import Path

from controlled_data import require_repository_paths

from equity_analysis.historical_validation.model_validation_terminal_closeout_v1 import (
    build_terminal_closeout,
)

ROOT = Path(__file__).resolve().parents[2]
TACTICAL = (
    ROOT
    / "docs"
    / "generated"
    / "tactical-v2-2-tier1-statistical-closeout-2026-07-30.json"
)
LONG_TIER1 = (
    ROOT
    / "docs"
    / "generated"
    / "long-horizon-v1-1-tier1-retrospective-2026-07-30.json"
)
LONG_TIER2 = (
    ROOT
    / "docs"
    / "generated"
    / "long-horizon-v1-1-tier2-pit-reconstruction-2026-07-30.json"
)


def _build() -> dict[str, object]:
    require_repository_paths(
        ROOT,
        (
            TACTICAL.relative_to(ROOT),
            LONG_TIER1.relative_to(ROOT),
            LONG_TIER2.relative_to(ROOT),
        ),
        purpose="Model validation terminal closeout reconstruction",
    )
    return build_terminal_closeout(TACTICAL, LONG_TIER1, LONG_TIER2)


def test_closeout_is_deterministic_and_binds_sources() -> None:
    first = _build()
    second = _build()
    assert first == second
    assert len(first["sourceArtifacts"]) == 3
    assert first["artifactContentHash"] == second["artifactContentHash"]


def test_tactical_labels_keep_ranking_separate_from_entry() -> None:
    records = _build()["records"]
    tactical = [
        record for record in records if record["modelTrack"] == "TACTICAL_V22"
    ]
    assert len(tactical) == 6
    ranking = {
        record["horizonCompletedSessions"]: record
        for record in tactical
        if record["target"] == "TACTICAL_RANKING"
    }
    assert ranking[5]["modelEvidenceLabel"] == "NOT_VALIDATED"
    assert ranking[20]["modelEvidenceLabel"] == "PARTIALLY_SUPPORTED"
    assert ranking[60]["modelEvidenceLabel"] == "PARTIALLY_SUPPORTED"
    entries = [
        record
        for record in tactical
        if record["target"] == "TACTICAL_ENTRY_DECISION"
    ]
    assert all(record["modelEvidenceLabel"] == "NOT_VALIDATED" for record in entries)
    assert all(record["entryDecisionEvidence"] == "MISSING" for record in entries)


def test_long_horizon_remains_not_validated_per_target_and_horizon() -> None:
    records = _build()["records"]
    long_records = [
        record
        for record in records
        if record["modelTrack"] == "LONG_HORIZON_V11"
    ]
    assert len(long_records) == 16
    assert {record["horizonCompletedSessions"] for record in long_records} == {
        252,
        504,
        756,
        1260,
    }
    assert all(
        record["modelEvidenceLabel"] == "NOT_VALIDATED"
        for record in long_records
    )
    assert all(record["targetEvidence"] == "MISSING" for record in long_records)


def test_closeout_does_not_claim_calibration_or_portfolio_suitability() -> None:
    artifact = _build()
    assert (
        artifact["tacticalCalibrationState"]
        == "NOT_APPLICABLE_UNCALIBRATED_ORDINAL_MODEL"
    )
    assert artifact["portfolioSuitability"] == "NOT_ASSESSED_BY_MODEL"
    assert artifact["aiParticipationInDeterministicEvidence"] is False
    assert artifact["modelFormulaOrThresholdChanged"] is False
    assert artifact["historicalModelRerun"] is False


def test_checked_in_artifact_matches_builder() -> None:
    checked_in = (
        ROOT
        / "docs"
        / "generated"
        / "model-validation-terminal-closeout-v1.json"
    )
    assert json.loads(checked_in.read_text(encoding="utf-8")) == _build()
