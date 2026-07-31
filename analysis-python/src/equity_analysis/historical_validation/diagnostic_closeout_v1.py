from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.historical_validation.governance_v1 import (
    ModelFreezeRecord,
    freeze_hash,
)
from equity_analysis.historical_validation.model_freeze_v1 import (
    matches_bound_file_sha256,
)

HISTORICAL_DIAGNOSTIC_CLOSEOUT_V1 = (
    "HISTORICAL-DIAGNOSTIC-EVIDENCE-CLOSEOUT-v1.0.0"
)


class HistoricalDiagnosticCloseoutError(ValueError):
    pass


@dataclass(frozen=True)
class CloseoutPaths:
    feasibility: Path = Path(
        "docs/generated/historical-pit-slice-feasibility-audit-v1.json"
    )
    tactical_terminal: Path = Path(
        "docs/generated/"
        "tactical-v2-2-historical-diagnostic-terminal-2026-07-29.json"
    )
    tactical_local_diagnostic: Path = Path(
        "docs/generated/tactical-walk-forward-local-diagnostic-2026-07-29.json"
    )
    tactical_freeze: Path = Path(
        "docs/generated/tactical-v2-2-model-freeze.json"
    )
    long_readiness: Path = Path(
        "docs/generated/long-horizon-v1-1-historical-readiness-2026-07-29.json"
    )
    long_retrospective: Path = Path(
        "docs/generated/"
        "long-horizon-historical-stratified-validation-v1-4-2026-07-29.json"
    )
    long_freeze: Path = Path(
        "docs/generated/long-horizon-v1-1-model-freeze.json"
    )


def _normalized_hash(value: str) -> str:
    return value.removeprefix("sha256:").upper()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _safe_path(repository_root: Path, relative_path: str | Path) -> Path:
    root = repository_root.resolve()
    requested = Path(relative_path)
    candidate = (
        requested.resolve()
        if requested.is_absolute()
        else (root / requested).resolve()
    )
    if not requested.is_absolute() and candidate != root and root not in candidate.parents:
        raise HistoricalDiagnosticCloseoutError(
            f"Evidence path escapes the repository: {relative_path}"
        )
    if not candidate.is_file():
        raise HistoricalDiagnosticCloseoutError(
            f"Evidence file is missing: {relative_path}"
        )
    return candidate


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HistoricalDiagnosticCloseoutError(
            f"Evidence is not readable JSON: {path}"
        ) from error
    if not isinstance(payload, dict):
        raise HistoricalDiagnosticCloseoutError(
            f"Evidence must be a JSON object: {path}"
        )
    return payload


def _verify_canonical_hash(path: Path, payload: dict[str, Any]) -> str:
    claim = payload.get("artifactContentHash")
    if not isinstance(claim, str):
        raise HistoricalDiagnosticCloseoutError(
            f"Evidence has no artifactContentHash: {path}"
        )
    body = dict(payload)
    body.pop("artifactContentHash")
    actual = canonical_hash(body)
    if _normalized_hash(actual) != _normalized_hash(claim):
        raise HistoricalDiagnosticCloseoutError(
            f"Evidence canonical hash mismatch: {path}"
        )
    return claim


def _binding(
    repository_root: Path,
    relative_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _safe_path(repository_root, relative_path)
    payload = _load_json(path)
    content_hash = _verify_canonical_hash(path, payload)
    try:
        display_path = path.relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        display_path = path.as_posix()
    return payload, {
        "path": display_path,
        "fileSha256": _file_sha256(path),
        "artifactContentHash": content_hash,
        "artifactType": payload.get("artifactType"),
        "schemaVersion": payload.get("schemaVersion"),
    }


def _verify_file_reference(
    repository_root: Path,
    reference: dict[str, Any],
) -> dict[str, Any]:
    relative_path = reference.get("path")
    expected_file_hash = reference.get("fileSha256")
    if not isinstance(relative_path, str) or not isinstance(
        expected_file_hash, str
    ):
        raise HistoricalDiagnosticCloseoutError(
            "Evidence reference requires path and fileSha256"
    )
    path = _safe_path(repository_root, relative_path)
    normalized_expected = _normalized_hash(expected_file_hash)
    if not matches_bound_file_sha256(
        path,
        normalized_expected,
        relative_path=relative_path,
    ):
        raise HistoricalDiagnosticCloseoutError(
            f"Referenced file SHA-256 mismatch: {relative_path}"
        )
    result: dict[str, Any] = {
        "path": relative_path,
        "fileSha256": normalized_expected,
    }
    expected_content_hash = reference.get("artifactContentHash")
    if expected_content_hash is not None:
        payload = _load_json(path)
        actual_content_hash = (
            _verify_canonical_hash(path, payload)
            if "artifactContentHash" in payload
            else canonical_hash(payload)
        )
        if _normalized_hash(actual_content_hash) != _normalized_hash(
            str(expected_content_hash)
        ):
            raise HistoricalDiagnosticCloseoutError(
                f"Referenced artifact content hash mismatch: {relative_path}"
            )
        result["artifactContentHash"] = actual_content_hash
    return result


def _verify_model_freeze(
    repository_root: Path,
    relative_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    payload, binding = _binding(repository_root, relative_path)
    record_data = payload.get("freezeRecord")
    if not isinstance(record_data, dict):
        raise HistoricalDiagnosticCloseoutError(
            f"Model freeze has no freezeRecord: {relative_path}"
        )
    parsed = dict(record_data)
    try:
        parsed["frozen_at"] = datetime.fromisoformat(parsed["frozen_at"])
        parsed["observed_evidence_cutoff"] = datetime.fromisoformat(
            parsed["observed_evidence_cutoff"]
        )
        parsed["source_artifact_hashes"] = tuple(
            parsed["source_artifact_hashes"]
        )
        actual_freeze_hash = freeze_hash(ModelFreezeRecord(**parsed))
    except (KeyError, TypeError, ValueError) as error:
        raise HistoricalDiagnosticCloseoutError(
            f"Model freeze record is invalid: {relative_path}"
        ) from error
    expected_freeze_hash = payload.get("freezeHash")
    if actual_freeze_hash != _normalized_hash(str(expected_freeze_hash)):
        raise HistoricalDiagnosticCloseoutError(
            f"Model freeze hash mismatch: {relative_path}"
        )
    source_files = payload.get("sourceFiles")
    if not isinstance(source_files, list) or not source_files:
        raise HistoricalDiagnosticCloseoutError(
            f"Model freeze source files are missing: {relative_path}"
        )
    verified_sources = [
        _verify_file_reference(repository_root, item) for item in source_files
    ]
    if [item["fileSha256"] for item in verified_sources] != list(
        record_data["source_artifact_hashes"]
    ):
        raise HistoricalDiagnosticCloseoutError(
            f"Model freeze source hash order mismatch: {relative_path}"
        )
    binding["freezeHash"] = actual_freeze_hash
    binding["modelVersion"] = payload.get("modelVersion")
    return payload, binding, verified_sources


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HistoricalDiagnosticCloseoutError(message)


def _verify_reference_matches(
    reference: dict[str, Any],
    binding: dict[str, Any],
    label: str,
) -> None:
    _require(
        reference.get("path") == binding["path"],
        f"{label} path binding mismatch",
    )
    _require(
        _normalized_hash(str(reference.get("fileSha256")))
        == binding["fileSha256"],
        f"{label} file hash binding mismatch",
    )
    expected_content_hash = reference.get("artifactContentHash")
    if expected_content_hash is not None:
        _require(
            _normalized_hash(str(expected_content_hash))
            == _normalized_hash(str(binding["artifactContentHash"])),
            f"{label} content hash binding mismatch",
        )


def build_historical_diagnostic_closeout(
    repository_root: Path,
    *,
    paths: CloseoutPaths | None = None,
) -> dict[str, Any]:
    root = repository_root.resolve()
    paths = paths or CloseoutPaths()
    feasibility, feasibility_binding = _binding(root, paths.feasibility)
    tactical_terminal, tactical_terminal_binding = _binding(
        root, paths.tactical_terminal
    )
    tactical_local, tactical_local_binding = _binding(
        root, paths.tactical_local_diagnostic
    )
    tactical_freeze, tactical_freeze_binding, tactical_frozen_sources = (
        _verify_model_freeze(root, paths.tactical_freeze)
    )
    long_readiness, long_readiness_binding = _binding(
        root, paths.long_readiness
    )
    long_retrospective, long_retrospective_binding = _binding(
        root, paths.long_retrospective
    )
    long_freeze, long_freeze_binding, long_frozen_sources = (
        _verify_model_freeze(root, paths.long_freeze)
    )

    _verify_reference_matches(
        tactical_terminal["freeze"],
        tactical_freeze_binding,
        "Tactical terminal to freeze",
    )
    _verify_reference_matches(
        long_readiness["freeze"],
        long_freeze_binding,
        "Long readiness to freeze",
    )
    _verify_reference_matches(
        long_readiness["observedHistoricalEvidence"],
        long_retrospective_binding,
        "Long readiness to retrospective evidence",
    )
    _verify_reference_matches(
        feasibility["evidenceSources"]["longHorizonV11Readiness"],
        long_readiness_binding,
        "PIT feasibility to long readiness",
    )

    verified_transitive: dict[str, dict[str, Any]] = {}
    for source in feasibility["evidenceSources"].values():
        verified = _verify_file_reference(root, source)
        verified_transitive[verified["path"]] = verified
    for source in (
        tactical_terminal["sourceEvidence"]["historicalPriceManifest"],
        tactical_terminal["sourceEvidence"]["frozenUniverse"],
        long_readiness["sourceEvidence"]["universe"],
        long_readiness["sourceEvidence"]["historicalPrices"],
        long_readiness["sourceEvidence"]["runner"],
        {
            "path": long_retrospective["sourceManifestPath"],
            "fileSha256": long_retrospective["sourceManifestFileSha256"],
            "artifactContentHash": long_retrospective[
                "sourceManifestContentHash"
            ],
        },
    ):
        verified = _verify_file_reference(root, source)
        verified_transitive[verified["path"]] = verified

    summary = feasibility.get("summary", {})
    status_counts = summary.get("statusCounts", {})
    track_counts = summary.get("trackStatusCounts", {})
    _require(
        status_counts
        == {
            "FORMAL_PIT_ELIGIBLE": 0,
            "DIAGNOSTIC_ONLY": 54,
            "BLOCKED": 18,
        },
        "Historical PIT feasibility terminal counts changed",
    )
    _require(
        track_counts.get("TACTICAL")
        == {
            "FORMAL_PIT_ELIGIBLE": 0,
            "DIAGNOSTIC_ONLY": 54,
            "BLOCKED": 0,
        },
        "Tactical PIT feasibility counts changed",
    )
    _require(
        track_counts.get("LONG")
        == {
            "FORMAL_PIT_ELIGIBLE": 0,
            "DIAGNOSTIC_ONLY": 0,
            "BLOCKED": 18,
        },
        "Long PIT feasibility counts changed",
    )
    _require(
        tactical_terminal.get("modelVersion") == "TACTICAL-SIGNAL-v2.2.0"
        and tactical_terminal.get("claimCeiling") == "DIAGNOSTIC_ONLY"
        and tactical_terminal.get("evaluationRole")
        == "DEVELOPMENT_OBSERVED"
        and tactical_terminal.get("untouchedHoldout") is False
        and tactical_terminal.get("terminalStatus") == "BLOCKED_BY_DATA",
        "Tactical v2.2 evidence exceeds or contradicts its diagnostic ceiling",
    )
    _require(
        tactical_local.get("statisticalEdgeProven") == "NOT_ESTABLISHED",
        "Local tactical diagnostic unexpectedly claims a proven edge",
    )
    _require(
        tactical_freeze.get("modelVersion") == "TACTICAL-SIGNAL-v2.2.0",
        "Unexpected tactical freeze model version",
    )
    _require(
        long_freeze.get("modelVersion") == "LONG-HORIZON-RESEARCH-v1.1.0",
        "Unexpected Long Horizon freeze model version",
    )
    _require(
        long_readiness.get("modelVersion")
        == "LONG-HORIZON-RESEARCH-v1.1.0"
        and long_readiness.get("terminalStatus") == "BLOCKED_BY_DATA",
        "Long Horizon v1.1 readiness is not blocked as expected",
    )
    long_summary = long_readiness.get("summary", {})
    _require(
        long_summary.get("v11HistoricalDecisionReadyCount") == 0
        and long_summary.get("v11ScoreCount") == 0,
        "Long Horizon v1.1 unexpectedly contains a ready historical decision",
    )
    _require(
        long_retrospective.get("modelVersion")
        == "LONG-HORIZON-RESEARCH-v1.0.0"
        and long_retrospective.get("statisticalEdgeProven")
        == "NOT_ESTABLISHED",
        "Long retrospective evidence cannot be promoted to v1.1 validation",
    )
    _require(
        feasibility["closedPool"]["survivorshipBiasPresent"] is True
        and not any(
            feasibility["pitCapability"][key]
            for key in (
                "historicalObservationAvailabilityProvenAtCutoff",
                "historicalMembershipPit",
                "historicalClassificationPit",
                "historicalIdentityAndStatusPit",
                "historicalCorporateActionsPit",
                "historicalObjectiveAndFundamentalsPit",
            )
        ),
        "Historical evidence no longer matches the closed-pool PIT boundary",
    )

    source_bindings = [
        feasibility_binding,
        tactical_terminal_binding,
        tactical_local_binding,
        tactical_freeze_binding,
        long_readiness_binding,
        long_retrospective_binding,
        long_freeze_binding,
    ]
    source_bindings.extend(
        verified_transitive[path] for path in sorted(verified_transitive)
    )
    evidence_graph = {
        "directArtifacts": source_bindings,
        "tacticalFrozenSourceFiles": tactical_frozen_sources,
        "longHorizonFrozenSourceFiles": long_frozen_sources,
    }
    evidence_graph["verifiedFileCount"] = len(
        {
            item["path"]
            for group in (
                source_bindings,
                tactical_frozen_sources,
                long_frozen_sources,
            )
            for item in group
        }
    )
    evidence_graph["evidenceGraphHash"] = canonical_hash(evidence_graph)

    body: dict[str, Any] = {
        "artifactType": "HISTORICAL_DIAGNOSTIC_EVIDENCE_CLOSEOUT",
        "schemaVersion": HISTORICAL_DIAGNOSTIC_CLOSEOUT_V1,
        "effectiveDate": "2026-07-29",
        "mode": "STRICTLY_OFFLINE_READ_ONLY",
        "terminalStatus": "CLOSED_WITHOUT_FORMAL_VALIDATION",
        "tracks": {
            "TACTICAL_1W": {
                "modelVersion": "TACTICAL-SIGNAL-v2.2.0",
                "horizonCompletedSessions": 5,
                "evidenceRole": "DIAGNOSTIC_ONLY",
                "formalValidationStatus": "NOT_ESTABLISHED",
            },
            "TACTICAL_1M": {
                "modelVersion": "TACTICAL-SIGNAL-v2.2.0",
                "horizonCompletedSessions": 20,
                "evidenceRole": "DIAGNOSTIC_ONLY",
                "formalValidationStatus": "NOT_ESTABLISHED",
            },
            "TACTICAL_3M": {
                "modelVersion": "TACTICAL-SIGNAL-v2.2.0",
                "horizonCompletedSessions": 60,
                "evidenceRole": "DIAGNOSTIC_ONLY",
                "formalValidationStatus": "NOT_ESTABLISHED",
            },
            "LONG_12M_PLUS": {
                "modelVersion": "LONG-HORIZON-RESEARCH-v1.1.0",
                "horizonCompletedSessions": 252,
                "evidenceRole": "BLOCKED",
                "formalValidationStatus": "NOT_EXECUTED",
                "historicalDecisionReadyCount": 0,
                "scoreCount": 0,
            },
        },
        "sliceDisposition": {
            "formalPitEligible": 0,
            "diagnosticOnly": 54,
            "blocked": 18,
            "favorableSlicePromotionAllowed": False,
            "fragmentAggregationIntoValidationPassAllowed": False,
        },
        "evidenceLimitations": {
            "closedCurrentPool": True,
            "survivorshipBiasPresent": True,
            "historicalMembershipPit": False,
            "historicalClassificationPit": False,
            "historicalIdentityAndStatusPit": False,
            "historicalCorporateActionsPit": False,
            "historicalFundamentalsAndObjectivePit": False,
            "historicalObservationAvailabilityProvenAtCutoff": False,
            "untouchedHoldout": False,
            "futureReturnProof": False,
            "statisticalEdgeProven": False,
        },
        "claimBoundary": {
            "historicalEvidenceMaySupportEngineeringDiagnostics": True,
            "historicalEvidenceMayProveInvestmentReturns": False,
            "historicalEvidenceMayAuthorizeRetuningFromFavorableSlices": False,
            "historicalEvidenceMaySatisfyForwardValidation": False,
            "onlyFormalPath": (
                "PROSPECTIVE_FORWARD_DECISION_QUALITY_VALIDATION"
            ),
            "statement": (
                "Historical closed-pool evidence is useful for detecting "
                "implementation errors and adverse behavior, but it is not an "
                "untouched holdout, point-in-time historical proof, or future-"
                "return proof. Favorable slices cannot be selected or combined "
                "to create a validation pass."
            ),
        },
        "verifiedEvidenceGraph": evidence_graph,
        "execution": {
            "networkRequests": 0,
            "databaseReads": 0,
            "databaseWrites": 0,
            "modelsExecuted": False,
            "scoresOrRanksComputed": False,
            "weightsOrThresholdsChanged": False,
            "samplingChanged": False,
            "rawProviderValuesIncluded": False,
            "automaticTradingAuthorized": False,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_immutable_closeout(
    output_path: Path,
    artifact: dict[str, Any],
) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n"
    ).encode()
    if output_path.exists():
        if output_path.read_bytes() != encoded:
            raise HistoricalDiagnosticCloseoutError(
                "HISTORICAL_DIAGNOSTIC_CLOSEOUT_IMMUTABLE_CONFLICT"
            )
    else:
        with output_path.open("xb") as handle:
            handle.write(encoded)
    return hashlib.sha256(encoded).hexdigest().upper()
