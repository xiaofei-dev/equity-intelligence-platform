from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from equity_analysis.historical_validation.governance_v1 import (
    EvaluationRole,
    ModelFreezeRecord,
    freeze_hash,
    freeze_payload,
)
from equity_analysis.historical_validation.protocol_v2 import (
    HISTORICAL_VALIDATION_PROTOCOL_V2,
)

MODEL_FREEZE_ARTIFACT_VERSION = "MODEL-FREEZE-ARTIFACT-v1.0.0"
MODEL_FREEZE_GENERATOR_VERSION = "MODEL-FREEZE-GENERATOR-v1.0.0"
LICENSED_ARTIFACT_RECEIPT_VERSION = (
    "LICENSED-HISTORICAL-ARTIFACT-RECEIPTS-v1.0.0"
)
LICENSED_ARTIFACT_RECEIPT_PATH = Path(
    "docs/generated/licensed-historical-artifact-receipts-v1.json"
)
FIXED_RANDOM_SEED = 20260729
OBSERVED_EVIDENCE_CUTOFF = datetime(2026, 7, 29, 23, 59, 59, tzinfo=UTC)
SOURCE_FINALIZATION_OBSERVED_AT = datetime(
    2026,
    7,
    30,
    0,
    40,
    54,
    609680,
    tzinfo=UTC,
)
FROZEN_AT = datetime(2026, 7, 30, 0, 45, 0, tzinfo=UTC)

TACTICAL_TRACK = "TACTICAL"
LONG_HORIZON_TRACK = "LONG_HORIZON"

_LEGACY_TRAILING_LF_SOURCE_HASHES = {
    "analysis-python/src/equity_analysis/historical_validation/walk_forward_v2.py": {
        "current": "9F842C5F379BCE3CFE88318342549061316822AC908F581B7378F07F3577FA7E",
        "sealed": "45D4DBDD0E7A643658B160AE5B044C15A4A07113DC33382A3DE87DDFF3D72F0F",
    },
}

_TRACKS: dict[str, dict[str, Any]] = {
    TACTICAL_TRACK: {
        "modelVersion": "TACTICAL-SIGNAL-v2.2.0",
        "maximumHorizonSessions": 60,
        "sourceFiles": (
            "analysis-python/src/equity_analysis/tactical/contracts_v22.py",
            "analysis-python/src/equity_analysis/tactical/features_v22.py",
            "analysis-python/src/equity_analysis/tactical/signal_v22.py",
            "docs/tactical-signal-v2-2-methodology-2026-07-29.md",
        ),
        "formulaFiles": (
            "analysis-python/src/equity_analysis/tactical/features_v22.py",
            "analysis-python/src/equity_analysis/tactical/signal_v22.py",
        ),
        "weightFiles": (
            "analysis-python/src/equity_analysis/tactical/features_v22.py",
            "analysis-python/src/equity_analysis/tactical/signal_v22.py",
        ),
        "inputSchemaFiles": (
            "analysis-python/src/equity_analysis/tactical/contracts_v22.py",
        ),
        "historicalEvidence": (
            {
                "path": (
                    "docs/generated/"
                    "tactical-historical-stratified-validation-v1-1-2026-07-29.json"
                ),
                "role": EvaluationRole.DEVELOPMENT_OBSERVED.value,
                "modelVersion": "TACTICAL-SIGNAL-v2.1.0",
            },
        ),
        "applicability": {
            "decisionDomain": "SHORT_TERM_SPECULATION",
            "cadence": "COMPLETED_DAILY_SESSION",
            "horizonsCompletedSessions": [5, 20, 60],
            "effectiveFrom": "NEXT_COMPLETED_SESSION_OPEN",
            "signalTtlCompletedSessions": 1,
            "requiredEvidence": [
                "securityAdjustedOHLCV",
                "marketBenchmarkAdjustedOHLCV",
                "sectorBenchmarkAdjustedOHLCV",
                "deterministicEventRisk",
            ],
            "automaticTradingAuthorized": False,
        },
        "missingPolicy": {
            "states": [
                "VALID",
                "MISSING",
                "STALE",
                "INVALID",
                "NOT_APPLICABLE",
            ],
            "neutralSubstitutionAllowed": False,
            "requiredInvalidEvidenceOutcome": "INSUFFICIENT_DATA",
            "eventUncertaintyActionabilityCeiling": "WATCH_ONLY",
        },
        "acceptance": {
            "target": "TACTICAL_DECISION_QUALITY",
            "aggregateModelScoreIsReturnForecast": False,
            "minimumEligibleDecisions": 100,
            "minimumCoverageRatio": "0.80",
            "requiredNetComparisons": [
                "SPY",
                "SECTOR",
                "EQUAL_WEIGHT",
                "PURE_MOMENTUM",
            ],
            "requiredPositiveLowerConfidenceBounds": [
                "TOP_MINUS_BOTTOM",
                "TOP_VERSUS_BENCHMARK",
            ],
            "maximumDownsideCapture": "1.00",
            "drawdownMustNotBeWorseThanBenchmark": True,
            "regimeAndSectorBreakdownsRequired": True,
        },
    },
    LONG_HORIZON_TRACK: {
        "modelVersion": "LONG-HORIZON-RESEARCH-v1.1.0",
        "maximumHorizonSessions": 252,
        "sourceFiles": (
            "analysis-python/src/equity_analysis/research_rating/long_horizon_v11.py",
            "docs/long-horizon-research-rating-v1-1.md",
        ),
        "formulaFiles": (
            "analysis-python/src/equity_analysis/research_rating/long_horizon_v11.py",
        ),
        "weightFiles": (
            "analysis-python/src/equity_analysis/research_rating/long_horizon_v11.py",
        ),
        "inputSchemaFiles": (
            "analysis-python/src/equity_analysis/research_rating/long_horizon_v11.py",
        ),
        "historicalEvidence": (
            {
                "path": (
                    "docs/generated/"
                    "long-horizon-historical-stratified-validation-v1-4-2026-07-29.json"
                ),
                "role": EvaluationRole.DEVELOPMENT_OBSERVED.value,
                "modelVersion": "LONG-HORIZON-RESEARCH-v1.0.0",
            },
        ),
        "applicability": {
            "decisionDomain": "LONG_HORIZON_RESEARCH",
            "minimumHorizon": "12_MONTHS",
            "supportedCompanyModel": "GENERAL",
            "specializedModels": [
                "BANK",
                "INSURANCE",
                "REIT",
                "RESOURCE",
                "BIOTECH",
            ],
            "recentIpoOutcome": "INSUFFICIENT_PUBLIC_HISTORY",
            "defaultRankingAuthorized": False,
            "automaticTradingAuthorized": False,
        },
        "missingPolicy": {
            "states": ["VALID", "MISSING", "INVALID", "NOT_APPLICABLE"],
            "neutralSubstitutionAllowed": False,
            "completeDimensionEvidenceRequired": True,
            "insufficientCohortOutcome": "COHORT_INSUFFICIENT",
            "minimumPeerCohort": 20,
            "specializedCompanyOutcome": "SPECIALIZED_MODEL_REQUIRED",
        },
        "acceptance": {
            "target": "SEPARATE_LONG_HORIZON_DECISION_TARGETS",
            "defaultRankingAuthorized": False,
            "minimumCoverageRatio": "0.80",
            "minimumEligibleDecisionsPerTarget": 100,
            "targets": {
                "BUSINESS_QUALITY": [
                    "FUTURE_FUNDAMENTAL_DURABILITY",
                    "IMPAIRMENT_RATE",
                ],
                "SECURITY_ATTRACTIVENESS": [
                    "BENCHMARK_RELATIVE_RETURN",
                    "TOP_MINUS_BOTTOM",
                ],
                "DOWNSIDE_RISK": [
                    "MAXIMUM_DRAWDOWN",
                    "DOWNSIDE_CAPTURE",
                ],
            },
            "singleAggregateValidationClaimAllowed": False,
            "requiredPositiveLowerConfidenceBounds": [
                "TARGET_DISCRIMINATION",
                "TARGET_VERSUS_BENCHMARK",
            ],
            "maximumDownsideCapture": "1.00",
        },
    },
}

_SHARED_SOURCE_FILES = (
    "analysis-python/src/equity_analysis/historical_validation/governance_v1.py",
    "analysis-python/src/equity_analysis/historical_validation/protocol_v2.py",
    "analysis-python/src/equity_analysis/historical_validation/walk_forward_v2.py",
    "docs/model-validation-governance-v1.md",
    "docs/historical-walk-forward-validation-v2.md",
    "docs/generated/model-validation-governance-v1.json",
)

_OBSERVED_SOURCE_FILES = (
    "docs/generated/historical-yahoo-price-cache-20260729T-HISTORICAL-V1-R2-manifest.json",
)

_BENCHMARK_CONTRACT = {
    "version": "FORMAL-BENCHMARK-CONTRACT-v1.0.0",
    "required": [
        "SPY",
        "SECTOR",
        "EQUAL_WEIGHT",
        "PURE_MOMENTUM",
        "PURE_VALUE",
        "PURE_QUALITY",
    ],
    "datedEvidenceHashRequired": True,
    "sameExecutionAndCostPolicyRequired": True,
    "formalGateStopsOnUnavailableBenchmark": True,
}

_COST_CONTRACT = {
    "version": "LIQUIDITY-SENSITIVE-COST-v1.0.0",
    "fixedRoundTripBps": "2",
    "baseSlippageOneWayBps": "1",
    "impactBpsAtFullParticipation": "25",
    "maximumImpactOneWayBps": "50",
    "averageDailyDollarVolumeRequired": True,
    "costsAppliedBeforeAcceptance": True,
}

_UNIVERSE_CONTRACT = {
    "version": "COMPLETE-FROZEN-POPULATION-v1.0.0",
    "identity": "STABLE_PUBLIC_SECURITY_ID",
    "completePopulationRequiredAtEveryDecision": True,
    "historicalMembershipRequiredForHistoricalValidation": True,
    "prospectiveFrozenUniverseAllowed": True,
    "currentUniverseRetrospectiveRole": EvaluationRole.DEVELOPMENT_OBSERVED.value,
    "terminalStatesRequired": [
        "ASSESSED",
        "MISSING",
        "INVALID",
        "STALE",
        "NOT_APPLICABLE",
        "SPECIALIZED_MODEL_REQUIRED",
        "EXCLUDED",
    ],
    "survivorshipSubstitutionAllowed": False,
}

_SAMPLING_BASE = {
    "version": "PURGED-NESTED-WALK-FORWARD-v1.0.0",
    "roles": [
        EvaluationRole.DEVELOPMENT_OBSERVED.value,
        EvaluationRole.SEALED_VALIDATION.value,
        EvaluationRole.WALK_FORWARD_OUTER_FOLD.value,
        EvaluationRole.PROSPECTIVE_FORWARD.value,
    ],
    "chronologicalOuterFolds": True,
    "nestedDevelopmentSelection": True,
    "ordinaryIidBootstrapFormalGateAllowed": False,
    "formalResampling": "BLOCK_BOOTSTRAP",
    "overlappingOutcomesRole": "OVERLAPPING_DIAGNOSTIC",
}


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest().upper()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def matches_bound_file_sha256(
    path: Path,
    expected_sha256: str,
    *,
    relative_path: str | None = None,
) -> bool:
    expected = expected_sha256.removeprefix("sha256:").upper()
    actual = file_sha256(path)
    if actual == expected:
        return True
    if relative_path is None:
        return False
    compatibility = _LEGACY_TRAILING_LF_SOURCE_HASHES.get(relative_path)
    if (
        compatibility is None
        or actual != compatibility["current"]
        or expected != compatibility["sealed"]
    ):
        return False
    source = path.read_bytes()
    return hashlib.sha256(source + b"\n").hexdigest().upper() == expected


def _load_licensed_artifact_receipts(repo_root: Path) -> dict[str, str]:
    receipt_path = repo_root / LICENSED_ARTIFACT_RECEIPT_PATH
    if not receipt_path.is_file():
        return {}
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("artifactType") != "LICENSED_HISTORICAL_ARTIFACT_RECEIPTS"
        or payload.get("schemaVersion") != LICENSED_ARTIFACT_RECEIPT_VERSION
        or payload.get("rawProviderValuesIncluded") is not False
        or payload.get("derivedLicensedMetricsIncluded") is not False
    ):
        raise ValueError("Licensed historical artifact receipt contract is invalid")
    expected_hash = payload.get("artifactContentHash")
    body = dict(payload)
    body.pop("artifactContentHash", None)
    if not isinstance(expected_hash, str) or canonical_hash(body) != expected_hash:
        raise ValueError("Licensed historical artifact receipt hash does not match")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Licensed historical artifact receipt entries are invalid")
    receipts: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "path",
            "fileSha256",
            "artifactContentHash",
        }:
            raise ValueError("Licensed historical artifact receipt entry is invalid")
        relative_path = entry.get("path")
        file_hash = entry.get("fileSha256")
        content_hash = entry.get("artifactContentHash")
        if (
            not isinstance(relative_path, str)
            or not isinstance(file_hash, str)
            or not isinstance(content_hash, str)
            or len(file_hash) != 64
            or len(content_hash) != 64
            or any(character not in "0123456789ABCDEF" for character in file_hash)
            or any(character not in "0123456789ABCDEF" for character in content_hash)
            or relative_path in receipts
        ):
            raise ValueError("Licensed historical artifact receipt entry is invalid")
        receipts[relative_path] = file_hash
    return receipts


def _receipt_bound_sha256(repo_root: Path, relative_path: str) -> str | None:
    return _load_licensed_artifact_receipts(repo_root).get(relative_path)


def _source_entry(repo_root: Path, relative_path: str) -> dict[str, str]:
    path = repo_root / relative_path
    if path.is_file():
        source_hash = file_sha256(path)
    else:
        source_hash = _receipt_bound_sha256(repo_root, relative_path)
        if source_hash is None:
            raise FileNotFoundError(
                f"Required freeze source does not exist: {relative_path}"
            )
    return {"path": relative_path, "fileSha256": source_hash}


def _entries(repo_root: Path, paths: tuple[str, ...]) -> list[dict[str, str]]:
    return [_source_entry(repo_root, path) for path in paths]


def _hash_source_subset(
    repo_root: Path,
    *,
    contract: str,
    paths: tuple[str, ...],
) -> str:
    return canonical_hash({"contract": contract, "sources": _entries(repo_root, paths)})


def validate_generation_chronology(
    repo_root: Path,
    paths: tuple[str, ...],
) -> datetime:
    modified_times = [
        datetime.fromtimestamp((repo_root / path).stat().st_mtime, tz=UTC)
        for path in paths
    ]
    latest = max(modified_times)
    if latest > SOURCE_FINALIZATION_OBSERVED_AT:
        raise ValueError(
            "A bound source was modified after sourceFinalizationObservedAt: "
            f"latest={latest.isoformat()}, "
            f"recorded={SOURCE_FINALIZATION_OBSERVED_AT.isoformat()}"
        )
    if SOURCE_FINALIZATION_OBSERVED_AT >= FROZEN_AT:
        raise ValueError("frozenAt must follow sourceFinalizationObservedAt")
    if OBSERVED_EVIDENCE_CUTOFF >= FROZEN_AT:
        raise ValueError("frozenAt must follow observedEvidenceCutoff")
    return latest


def build_model_freeze_artifact(
    repo_root: Path,
    track: str,
    *,
    enforce_generation_chronology: bool = False,
) -> dict[str, Any]:
    try:
        configuration = _TRACKS[track]
    except KeyError as exc:
        raise ValueError(f"Unsupported model track: {track}") from exc

    maximum_horizon = int(configuration["maximumHorizonSessions"])
    sampling_contract = {
        **_SAMPLING_BASE,
        "randomSeed": FIXED_RANDOM_SEED,
        "maximumHorizonSessions": maximum_horizon,
        "purgeSessions": maximum_horizon,
        "embargoSessions": maximum_horizon,
    }

    track_sources = tuple(configuration["sourceFiles"])
    all_paths = tuple(
        dict.fromkeys(
            (
                *track_sources,
                *_SHARED_SOURCE_FILES,
                *_OBSERVED_SOURCE_FILES,
                *(
                    item["path"]
                    for item in configuration["historicalEvidence"]
                ),
            )
        )
    )
    source_files = _entries(repo_root, all_paths)
    if enforce_generation_chronology:
        validate_generation_chronology(repo_root, all_paths)
    historical_evidence = [
        {
            **item,
            "fileSha256": _source_entry(repo_root, item["path"])["fileSha256"],
            "untouchedHoldout": False,
        }
        for item in configuration["historicalEvidence"]
    ]

    formulas_hash = _hash_source_subset(
        repo_root,
        contract="FORMULAS",
        paths=tuple(configuration["formulaFiles"]),
    )
    weights_hash = _hash_source_subset(
        repo_root,
        contract="WEIGHTS_AND_THRESHOLDS",
        paths=tuple(configuration["weightFiles"]),
    )
    input_schema_hash = _hash_source_subset(
        repo_root,
        contract="INPUT_SCHEMA",
        paths=tuple(configuration["inputSchemaFiles"]),
    )
    applicability_hash = canonical_hash(configuration["applicability"])
    missing_policy_hash = canonical_hash(configuration["missingPolicy"])
    benchmark_hash = canonical_hash(_BENCHMARK_CONTRACT)
    cost_hash = canonical_hash(_COST_CONTRACT)
    universe_hash = canonical_hash(_UNIVERSE_CONTRACT)
    sampling_hash = canonical_hash(sampling_contract)
    acceptance_hash = canonical_hash(configuration["acceptance"])

    record = ModelFreezeRecord(
        model_version=configuration["modelVersion"],
        validation_protocol_version=HISTORICAL_VALIDATION_PROTOCOL_V2,
        frozen_at=FROZEN_AT,
        observed_evidence_cutoff=OBSERVED_EVIDENCE_CUTOFF,
        formulas_hash=formulas_hash,
        weights_hash=weights_hash,
        input_schema_hash=input_schema_hash,
        applicability_hash=applicability_hash,
        missing_data_policy_hash=missing_policy_hash,
        benchmark_contract_hash=benchmark_hash,
        cost_model_hash=cost_hash,
        universe_hash=universe_hash,
        sampling_hash=sampling_hash,
        acceptance_threshold_hash=acceptance_hash,
        source_artifact_hashes=tuple(
            item["fileSha256"] for item in source_files
        ),
        random_seed=FIXED_RANDOM_SEED,
        maximum_horizon_sessions=maximum_horizon,
        purge_sessions=maximum_horizon,
        embargo_sessions=maximum_horizon,
    )
    artifact: dict[str, Any] = {
        "artifactType": "MODEL_FREEZE",
        "schemaVersion": MODEL_FREEZE_ARTIFACT_VERSION,
        "generatorVersion": MODEL_FREEZE_GENERATOR_VERSION,
        "modelTrack": track,
        "modelVersion": configuration["modelVersion"],
        "freezeRecord": freeze_payload(record),
        "freezeHash": freeze_hash(record),
        "contracts": {
            "applicability": configuration["applicability"],
            "missingDataPolicy": configuration["missingPolicy"],
            "benchmark": _BENCHMARK_CONTRACT,
            "cost": _COST_CONTRACT,
            "universe": _UNIVERSE_CONTRACT,
            "sampling": sampling_contract,
            "acceptance": configuration["acceptance"],
        },
        "sourceFiles": source_files,
        "freezeChronology": {
            "observedEvidenceCutoff": OBSERVED_EVIDENCE_CUTOFF.isoformat(),
            "sourceFinalizationObservedAt": (
                SOURCE_FINALIZATION_OBSERVED_AT.isoformat()
            ),
            "frozenAt": FROZEN_AT.isoformat(),
            "derivation": (
                "The fixed UTC freeze time is the next five-minute boundary "
                "after the maximum bound-source mtime observed during initial "
                "generation."
            ),
            "generationChronologyChecked": True,
            "stableVerificationUsesContentHashesNotCheckoutMtime": True,
        },
        "observedHistoricalEvidence": {
            "evaluationRole": EvaluationRole.DEVELOPMENT_OBSERVED.value,
            "observedEvidenceCutoff": OBSERVED_EVIDENCE_CUTOFF.isoformat(),
            "untouchedHoldoutAvailable": False,
            "artifacts": historical_evidence,
            "claimBoundary": (
                "Observed retrospective evidence is diagnostic development "
                "evidence and cannot become an untouched holdout."
            ),
        },
        "execution": {
            "networkRequestsExecuted": False,
            "historicalScoringExecuted": False,
            "forwardValidationExecuted": False,
            "databaseMigrationExecuted": False,
        },
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    return artifact


def verify_model_freeze_artifact(repo_root: Path, artifact: dict[str, Any]) -> None:
    expected_content_hash = artifact.get("artifactContentHash")
    if not isinstance(expected_content_hash, str):
        raise ValueError("Freeze artifact is missing artifactContentHash")
    content = dict(artifact)
    del content["artifactContentHash"]
    if canonical_hash(content) != expected_content_hash:
        raise ValueError("Freeze artifact content hash does not match")

    track = artifact.get("modelTrack")
    expected = build_model_freeze_artifact(repo_root, str(track))
    if expected == artifact:
        return

    adjusted = copy.deepcopy(expected)
    sealed_sources = artifact.get("sourceFiles")
    if not isinstance(sealed_sources, list) or len(sealed_sources) != len(
        adjusted["sourceFiles"]
    ):
        raise ValueError("Freeze artifact no longer matches its source contracts")
    adjusted_hashes: list[str] = []
    for current_source, sealed_source in zip(
        adjusted["sourceFiles"],
        sealed_sources,
        strict=True,
    ):
        if (
            not isinstance(sealed_source, dict)
            or current_source["path"] != sealed_source.get("path")
        ):
            raise ValueError(
                "Freeze artifact no longer matches its source contracts"
            )
        sealed_hash = sealed_source.get("fileSha256")
        source_path = repo_root / current_source["path"]
        source_matches = (
            isinstance(sealed_hash, str)
            and (
                (
                    source_path.is_file()
                    and matches_bound_file_sha256(
                        source_path,
                        sealed_hash,
                        relative_path=current_source["path"],
                    )
                )
                or (
                    not source_path.is_file()
                    and _receipt_bound_sha256(
                        repo_root,
                        current_source["path"],
                    )
                    == sealed_hash
                )
            )
        )
        if not source_matches:
            raise ValueError(
                "Freeze artifact no longer matches its source contracts"
            )
        current_source["fileSha256"] = sealed_hash
        adjusted_hashes.append(sealed_hash)

    adjusted["freezeRecord"]["source_artifact_hashes"] = adjusted_hashes
    parsed_record = dict(adjusted["freezeRecord"])
    parsed_record["frozen_at"] = datetime.fromisoformat(
        parsed_record["frozen_at"]
    )
    parsed_record["observed_evidence_cutoff"] = datetime.fromisoformat(
        parsed_record["observed_evidence_cutoff"]
    )
    parsed_record["source_artifact_hashes"] = tuple(
        parsed_record["source_artifact_hashes"]
    )
    adjusted["freezeHash"] = freeze_hash(ModelFreezeRecord(**parsed_record))
    adjusted.pop("artifactContentHash")
    adjusted["artifactContentHash"] = canonical_hash(adjusted)
    if adjusted != artifact:
        raise ValueError("Freeze artifact no longer matches its source contracts")


def write_immutable_artifact(path: Path, artifact: dict[str, Any]) -> None:
    rendered = json.dumps(artifact, ensure_ascii=True, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(f"Refusing to overwrite changed freeze artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate immutable model freezes.")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument(
        "--track",
        choices=(TACTICAL_TRACK, LONG_HORIZON_TRACK),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    repo_root = arguments.repo_root.resolve()
    artifact = build_model_freeze_artifact(
        repo_root,
        arguments.track,
        enforce_generation_chronology=True,
    )
    write_immutable_artifact(arguments.output, artifact)
    verify_model_freeze_artifact(repo_root, artifact)
    print(
        json.dumps(
            {
                "output": str(arguments.output),
                "artifactContentHash": artifact["artifactContentHash"],
                "freezeHash": artifact["freezeHash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
