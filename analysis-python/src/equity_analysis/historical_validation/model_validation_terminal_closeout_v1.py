from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from equity_analysis.historical_validation.governance_v1 import (
    AvailabilityEvidence,
    EvaluationRole,
    OutcomeDependence,
    PriceActionEvidence,
    UniverseEvidence,
    ValidationEvidenceEnvelope,
)
from equity_analysis.historical_validation.governance_v11 import (
    EvidenceComponentState,
    EvidenceTarget,
    ModelEvidenceLabel,
    ModelTrack,
    OperationalRunStatus,
    TargetHorizonEvidenceRecord,
    validate_target_horizon_evidence,
)

MODEL_VALIDATION_TERMINAL_CLOSEOUT_V1 = (
    "MODEL-VALIDATION-TERMINAL-CLOSEOUT-v1.0.0"
)
TACTICAL_MODEL_VERSION = "TACTICAL-SIGNAL-v2.2.0"
LONG_HORIZON_MODEL_VERSION = "LONG-HORIZON-RESEARCH-v1.1.0"


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _read_artifact(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    claimed = payload.get("artifactContentHash")
    if not isinstance(claimed, str):
        raise ValueError(f"{path} does not contain artifactContentHash")
    unhashed = dict(payload)
    del unhashed["artifactContentHash"]
    if _canonical_hash(unhashed) != claimed.removeprefix("sha256:").upper():
        raise ValueError(f"{path} canonical hash is invalid")
    return payload


def _stable_reference(path: Path) -> str:
    parts = path.parts
    if "docs" in parts:
        return Path(*parts[parts.index("docs") :]).as_posix()
    return path.as_posix()


def _tactical_envelope() -> ValidationEvidenceEnvelope:
    return ValidationEvidenceEnvelope(
        availability=AvailabilityEvidence.CURRENT_REVISION_RETROSPECTIVE,
        universe=UniverseEvidence.CURRENT_UNIVERSE_RETROSPECTIVE,
        outcome_dependence=OutcomeDependence.OVERLAPPING_DIAGNOSTIC,
        evaluation_role=EvaluationRole.DEVELOPMENT_OBSERVED,
        price_action=PriceActionEvidence.EX_POST_TOTAL_RETURN_ADJUSTED,
    )


def _long_horizon_envelope() -> ValidationEvidenceEnvelope:
    return ValidationEvidenceEnvelope(
        availability=AvailabilityEvidence.PIT_VERIFIED,
        universe=UniverseEvidence.CURRENT_UNIVERSE_RETROSPECTIVE,
        outcome_dependence=OutcomeDependence.OVERLAPPING_DIAGNOSTIC,
        evaluation_role=EvaluationRole.DEVELOPMENT_OBSERVED,
        price_action=PriceActionEvidence.EX_POST_TOTAL_RETURN_ADJUSTED,
    )


def _serialize_record(
    record: TargetHorizonEvidenceRecord,
    *,
    diagnostic_label: str,
) -> dict[str, object]:
    ceiling = validate_target_horizon_evidence(record)
    return {
        "modelVersion": record.model_version,
        "modelTrack": record.model_track.value,
        "target": record.target.value,
        "horizonCompletedSessions": record.horizon_completed_sessions,
        "runStatus": record.run_status.value,
        "modelEvidenceLabel": record.model_evidence_label.value,
        "diagnosticLabel": diagnostic_label,
        "claimCeiling": ceiling.value,
        "targetEvidence": record.target_evidence.value,
        "rankingEvidence": record.ranking_evidence.value,
        "entryDecisionEvidence": record.entry_decision_evidence.value,
        "limitations": list(record.limitations),
        "aiMayAffectDeterministicFields": False,
        "humanJudgmentMayMutateModelSnapshot": False,
    }


def _tactical_records() -> list[dict[str, object]]:
    ranking_labels = {
        5: (
            ModelEvidenceLabel.NOT_VALIDATED,
            "UNSUPPORTED_DIAGNOSTIC",
        ),
        20: (
            ModelEvidenceLabel.PARTIALLY_SUPPORTED,
            "WEAK_MIXED_DIAGNOSTIC",
        ),
        60: (
            ModelEvidenceLabel.PARTIALLY_SUPPORTED,
            "MODEST_INCONCLUSIVE_DIAGNOSTIC",
        ),
    }
    records: list[dict[str, object]] = []
    for horizon, (evidence_label, diagnostic_label) in ranking_labels.items():
        records.append(
            _serialize_record(
                TargetHorizonEvidenceRecord(
                    model_version=TACTICAL_MODEL_VERSION,
                    model_track=ModelTrack.TACTICAL_V22,
                    target=EvidenceTarget.TACTICAL_RANKING,
                    horizon_completed_sessions=horizon,
                    run_status=OperationalRunStatus.COMPLETED,
                    model_evidence_label=evidence_label,
                    evidence_envelope=_tactical_envelope(),
                    target_evidence=EvidenceComponentState.PRESENT,
                    ranking_evidence=EvidenceComponentState.PRESENT,
                    entry_decision_evidence=EvidenceComponentState.MISSING,
                    limitations=(
                        "CURRENT_UNIVERSE_RETROSPECTIVE",
                        "CURRENT_CLASSIFICATION_SECTOR_NOT_PIT",
                        "CORE_90_PERCENT_INTERVALS_CROSS_ZERO",
                        "VALUE_QUALITY_AND_SIZE_STABILITY_MISSING",
                    ),
                ),
                diagnostic_label=diagnostic_label,
            )
        )
        records.append(
            _serialize_record(
                TargetHorizonEvidenceRecord(
                    model_version=TACTICAL_MODEL_VERSION,
                    model_track=ModelTrack.TACTICAL_V22,
                    target=EvidenceTarget.TACTICAL_ENTRY_DECISION,
                    horizon_completed_sessions=horizon,
                    run_status=OperationalRunStatus.INSUFFICIENT_EVIDENCE,
                    model_evidence_label=ModelEvidenceLabel.NOT_VALIDATED,
                    evidence_envelope=_tactical_envelope(),
                    target_evidence=EvidenceComponentState.MISSING,
                    ranking_evidence=EvidenceComponentState.PRESENT,
                    entry_decision_evidence=EvidenceComponentState.MISSING,
                    limitations=(
                        "NO_EXECUTABLE_ENTRY_OR_LIMITED_ENTRY_EPISODES",
                        "HISTORICAL_EVENT_EVIDENCE_MISSING",
                        "WATCH_ONLY_ACTIONABILITY_CEILING",
                    ),
                ),
                diagnostic_label="NOT_VALIDATED_NO_EXECUTABLE_EPISODES",
            )
        )
    return records


def _long_horizon_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    limitations = (
        "NO_COMPLETE_HISTORICAL_MODEL_INPUT_SET",
        "NO_HISTORICAL_MODEL_EXECUTION_OR_RANK",
        "CURRENT_UNIVERSE_SURVIVORSHIP_NOT_CONTROLLED",
        "HISTORICAL_VALUATION_AND_RISK_EVIDENCE_INCOMPLETE",
    )
    for horizon in (252, 504, 756, 1260):
        for target in (
            EvidenceTarget.COMPANY_QUALITY,
            EvidenceTarget.SECURITY_ATTRACTIVENESS,
            EvidenceTarget.EXPECTED_RETURN,
            EvidenceTarget.DOWNSIDE_RISK,
        ):
            records.append(
                _serialize_record(
                    TargetHorizonEvidenceRecord(
                        model_version=LONG_HORIZON_MODEL_VERSION,
                        model_track=ModelTrack.LONG_HORIZON_V11,
                        target=target,
                        horizon_completed_sessions=horizon,
                        run_status=OperationalRunStatus.INSUFFICIENT_EVIDENCE,
                        model_evidence_label=ModelEvidenceLabel.NOT_VALIDATED,
                        evidence_envelope=_long_horizon_envelope(),
                        target_evidence=EvidenceComponentState.MISSING,
                        ranking_evidence=EvidenceComponentState.NOT_EVALUATED,
                        entry_decision_evidence=EvidenceComponentState.NOT_APPLICABLE,
                        limitations=limitations,
                    ),
                    diagnostic_label="NOT_VALIDATED_INCOMPLETE_PIT_MODEL_INPUTS",
                )
            )
    return records


def build_terminal_closeout(
    tactical_closeout_path: Path,
    long_horizon_tier1_path: Path,
    long_horizon_tier2_path: Path,
) -> dict[str, object]:
    source_paths = (
        tactical_closeout_path,
        long_horizon_tier1_path,
        long_horizon_tier2_path,
    )
    source_artifacts = [_read_artifact(path) for path in source_paths]
    records = [*_tactical_records(), *_long_horizon_records()]
    payload: dict[str, object] = {
        "artifactType": "MODEL_VALIDATION_TERMINAL_CLOSEOUT",
        "schemaVersion": MODEL_VALIDATION_TERMINAL_CLOSEOUT_V1,
        "generatedAt": "2026-07-30T00:00:00Z",
        "sourceArtifacts": [
            {
                "reference": _stable_reference(path),
                "fileSha256": _file_sha256(path),
                "artifactContentHash": artifact["artifactContentHash"],
            }
            for path, artifact in zip(source_paths, source_artifacts, strict=True)
        ],
        "recordCount": len(records),
        "records": records,
        "tacticalCalibrationState": (
            "NOT_APPLICABLE_UNCALIBRATED_ORDINAL_MODEL"
        ),
        "practicalValueThresholdApplicability": (
            "OBSERVED_TIER1_NOT_APPLICABLE"
        ),
        "portfolioSuitability": "NOT_ASSESSED_BY_MODEL",
        "aiParticipationInDeterministicEvidence": False,
        "modelFormulaOrThresholdChanged": False,
        "historicalModelRerun": False,
        "terminalConclusion": (
            "TACTICAL_RANKING_PARTIAL_DIAGNOSTIC_ONLY;"
            "TACTICAL_ENTRY_NOT_VALIDATED;"
            "LONG_HORIZON_NOT_VALIDATED"
        ),
    }
    payload["artifactContentHash"] = _canonical_hash(payload)
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tactical-closeout", type=Path, required=True)
    parser.add_argument("--long-horizon-tier1", type=Path, required=True)
    parser.add_argument("--long-horizon-tier2", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    artifact = build_terminal_closeout(
        args.tactical_closeout,
        args.long_horizon_tier1,
        args.long_horizon_tier2,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
