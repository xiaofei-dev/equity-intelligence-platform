from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

EXPECTED_CONTRACTS_SCHEMA_VERSION = (
    "forward-decision-quality-expected-contracts-v1.0.0"
)
FINAL_ACCEPTANCE_SCHEMA_VERSION = (
    "forward-decision-quality-final-acceptance-v1.0.0"
)
PENDING_FUTURE_OUTCOMES = "PENDING_FUTURE_OUTCOMES"
HORIZONS = (5, 20, 60)
REQUIRED_SHADOW_ARMS = (
    "A_LUMP_SUM",
    "B_FIXED_FOUR_TRANCHE",
    "C_STATE_GATED_FOUR_TRANCHE",
    "D_CASH_ONLY",
    "E_SECTOR_ETF",
    "E_SPY",
)
TACTICAL_RESULT_STATUSES = {"ASSESSED", "INSUFFICIENT_DATA"}
TACTICAL_ENTRY_STAGES = {
    "NONE",
    "EARLY_REVERSAL_CANDIDATE",
    "PROBE_ELIGIBLE",
    "CONFIRMED",
    "INVALIDATED",
    "INSUFFICIENT_DATA",
}
TACTICAL_ACTIONABILITY = {
    "WATCH_ONLY",
    "WAIT_FOR_PULLBACK",
    "LIMITED_ENTRY",
    "ENTRY",
    "RISK_BLOCKED",
    "NO_SETUP",
    "INSUFFICIENT_DATA",
}
TACTICAL_HORIZON_OUTLOOKS = {
    "FAVORABLE",
    "NEUTRAL",
    "UNFAVORABLE",
    "INSUFFICIENT_DATA",
}
SOURCE_HASH_FIELDS = {
    "objectiveRating": "artifactContentHash",
    "tacticalSignal": "contentHash",
    "weeklyPreregistration": "artifactContentHash",
    "dailyProtocol": "artifactContentHash",
    "enrollmentPreflight": "artifactContentHash",
}


def _load(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED[{path.name}]")
    return loaded


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _require_sha256(value: Any, label: str) -> str:
    normalized = str(value).upper()
    if len(normalized) != 64 or any(
        character not in "0123456789ABCDEF" for character in normalized
    ):
        raise ValueError(f"INVALID_SHA256[{label}]")
    return normalized


def _verify_embedded_hash(
    payload: dict[str, Any],
    *,
    hash_field: str,
    label: str,
) -> str:
    expected = _require_sha256(payload.get(hash_field), f"{label}.{hash_field}")
    unhashed = dict(payload)
    del unhashed[hash_field]
    actual = canonical_hash(unhashed)
    if actual != expected:
        raise ValueError(f"EMBEDDED_HASH_MISMATCH[{label}]")
    return expected


def _parse_datetime(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"INVALID_TIMESTAMP[{label}]") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"TIMEZONE_REQUIRED[{label}]")
    return parsed.astimezone(UTC)


def _parse_date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"INVALID_DATE[{label}]") from error


def _relative_path(repository_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repository_root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"SOURCE_OUTSIDE_REPOSITORY[{path}]") from error


def _resolve_source(repository_root: Path, reference: str) -> Path:
    candidate = (repository_root / reference).resolve()
    _relative_path(repository_root, candidate)
    if not candidate.is_file():
        raise ValueError(f"SOURCE_ARTIFACT_NOT_FOUND[{reference}]")
    return candidate


def _write_or_verify(path: Path, artifact: dict[str, Any], conflict: str) -> None:
    if path.exists():
        if _load(path) != artifact:
            raise ValueError(conflict)
        return
    write_immutable_json(path, artifact)


def _tactical_results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = payload.get("results")
    if not isinstance(results, dict):
        raise ValueError("TACTICAL_RESULTS_OBJECT_REQUIRED")
    normalized: dict[str, dict[str, Any]] = {}
    for symbol, result in results.items():
        if not isinstance(result, dict):
            raise ValueError(f"TACTICAL_RESULT_OBJECT_REQUIRED[{symbol}]")
        normalized[str(symbol)] = result
    if not normalized:
        raise ValueError("TACTICAL_RESULTS_REQUIRED")
    return normalized


def _source_descriptor(
    *,
    repository_root: Path,
    path: Path,
    payload: dict[str, Any],
    hash_field: str,
) -> dict[str, Any]:
    embedded_hash = _verify_embedded_hash(
        payload,
        hash_field=hash_field,
        label=path.name,
    )
    return {
        "path": _relative_path(repository_root, path),
        "fileSha256": _file_sha256(path),
        "embeddedHashField": hash_field,
        "embeddedContentHash": embedded_hash,
    }


def _latest_evidence_timestamp(
    objective: dict[str, Any],
    tactical: dict[str, Any],
) -> str:
    objective_time = _parse_datetime(
        objective.get("asOfTime"),
        "objectiveRating.asOfTime",
    )
    tactical_time = _parse_datetime(
        tactical.get("generatedAt"),
        "tacticalSignal.generatedAt",
    )
    return max(objective_time, tactical_time).isoformat().replace("+00:00", "Z")


def build_expected_contract_manifest(
    *,
    repository_root: Path,
    objective_rating_path: Path,
    tactical_signal_path: Path,
    weekly_preregistration_path: Path,
    daily_protocol_path: Path,
    enrollment_preflight_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    sources = {
        "objectiveRating": (objective_rating_path, _load(objective_rating_path)),
        "tacticalSignal": (tactical_signal_path, _load(tactical_signal_path)),
        "weeklyPreregistration": (
            weekly_preregistration_path,
            _load(weekly_preregistration_path),
        ),
        "dailyProtocol": (daily_protocol_path, _load(daily_protocol_path)),
        "enrollmentPreflight": (
            enrollment_preflight_path,
            _load(enrollment_preflight_path),
        ),
    }
    descriptors = {
        role: _source_descriptor(
            repository_root=repository_root,
            path=path,
            payload=payload,
            hash_field=SOURCE_HASH_FIELDS[role],
        )
        for role, (path, payload) in sources.items()
    }
    objective = sources["objectiveRating"][1]
    tactical = sources["tacticalSignal"][1]
    weekly = sources["weeklyPreregistration"][1]
    daily = sources["dailyProtocol"][1]
    tactical_results = _tactical_results(tactical)
    tactical_effective_from = sorted(
        {
            str(result.get("effectiveFrom"))
            for result in tactical_results.values()
            if result.get("status") == "ASSESSED"
        }
    )
    tactical_ttls = sorted(
        {
            int(result["signalTtlCompletedSessions"])
            for result in tactical_results.values()
            if result.get("status") == "ASSESSED"
        }
    )
    costs = weekly.get("costAssumptions")
    if not isinstance(costs, dict):
        raise ValueError("COST_ASSUMPTIONS_REQUIRED")
    round_trip_cost = sum(
        int(costs[field])
        for field in (
            "buyTransactionCostBps",
            "buySlippageBps",
            "hypotheticalSaleTransactionCostBps",
            "hypotheticalSaleSlippageBps",
        )
    )
    artifact = {
        "artifactType": "FORWARD_DECISION_QUALITY_EXPECTED_CONTRACTS",
        "schemaVersion": EXPECTED_CONTRACTS_SCHEMA_VERSION,
        "assembledFromEvidenceAt": _latest_evidence_timestamp(objective, tactical),
        "sourceArtifacts": descriptors,
        "deterministicModelContracts": {
            "objectiveRating": {
                "artifactType": objective.get("artifactType"),
                "schemaVersion": objective.get("schemaVersion"),
                "modelVersion": objective.get("strategyVersion"),
                "scope": objective.get("scope"),
                "status": objective.get("status"),
            },
            "tacticalSignal": {
                "schemaVersion": tactical.get("schemaVersion"),
                "modelVersion": tactical.get("modelVersion"),
                "executionMode": tactical.get("executionMode"),
                "effectiveFromValues": tactical_effective_from,
                "signalTtlCompletedSessions": tactical_ttls,
                "statisticalEdgeProven": tactical.get(
                    "statisticalEdgeProven"
                ),
            },
        },
        "forwardEvaluationContract": {
            "weeklyExperimentVersion": weekly.get("experimentVersion"),
            "dailyExperimentVersion": daily.get("experimentVersion"),
            "observationHorizonsTradingDays": list(HORIZONS),
            "shadowArms": list(REQUIRED_SHADOW_ARMS),
            "decisionCutoffRule": "COMPLETED_SESSION_ONLY",
            "executionRule": "NO_EARLIER_THAN_NEXT_SESSION",
            "sameSessionExecutionPermitted": False,
            "costAssumptions": costs,
            "roundTripCostAndSlippageBps": round_trip_cost,
            "comparisonBaselines": [
                "A_LUMP_SUM",
                "B_FIXED_FOUR_TRANCHE",
                "D_CASH_ONLY",
            ],
            "policyArm": "C_STATE_GATED_FOUR_TRANCHE",
            "benchmarkComparisons": ["SECTOR_ETF", "SPY"],
            "minimumOverallCompletedEpisodes": 20,
            "minimumSectorOrSizeCompletedEpisodes": 10,
            "statisticalEdgeClaim": "NOT_ESTABLISHED",
        },
        "claimBoundary": {
            "historicalWalkForwardIsProspectiveEvidence": False,
            "automaticTradingAuthorized": False,
            "realizedFuturePerformanceClaimAuthorized": False,
        },
        "networkRequestsExecuted": False,
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    _write_or_verify(
        output_path,
        artifact,
        "FORWARD_EXPECTED_CONTRACT_MANIFEST_CONFLICT",
    )
    return artifact


def _verify_manifest_sources(
    repository_root: Path,
    manifest: dict[str, Any],
) -> dict[str, tuple[Path, dict[str, Any]]]:
    descriptors = manifest.get("sourceArtifacts")
    if not isinstance(descriptors, dict):
        raise ValueError("EXPECTED_SOURCE_ARTIFACTS_REQUIRED")
    loaded: dict[str, tuple[Path, dict[str, Any]]] = {}
    for role, hash_field in SOURCE_HASH_FIELDS.items():
        descriptor = descriptors.get(role)
        if not isinstance(descriptor, dict):
            raise ValueError(f"EXPECTED_SOURCE_DESCRIPTOR_REQUIRED[{role}]")
        path = _resolve_source(repository_root, str(descriptor.get("path")))
        payload = _load(path)
        if descriptor.get("embeddedHashField") != hash_field:
            raise ValueError(f"EXPECTED_HASH_FIELD_MISMATCH[{role}]")
        embedded = _verify_embedded_hash(
            payload,
            hash_field=hash_field,
            label=role,
        )
        if embedded != _require_sha256(
            descriptor.get("embeddedContentHash"),
            f"manifest.{role}.embeddedContentHash",
        ):
            raise ValueError(f"EXPECTED_CONTENT_HASH_MISMATCH[{role}]")
        if _file_sha256(path) != _require_sha256(
            descriptor.get("fileSha256"),
            f"manifest.{role}.fileSha256",
        ):
            raise ValueError(f"EXPECTED_FILE_HASH_MISMATCH[{role}]")
        loaded[role] = (path, payload)
    return loaded


def _validate_objective_contract(
    payload: dict[str, Any],
    expected: dict[str, Any],
) -> tuple[set[str], dict[str, Any]]:
    if payload.get("status") != "PASS":
        raise ValueError("OBJECTIVE_RATING_GATE_NOT_PASSED")
    if payload.get("scope") != "CURRENT_DECISION_ONLY":
        raise ValueError("OBJECTIVE_RATING_SCOPE_NOT_CURRENT_DECISION_ONLY")
    if payload.get("strategyVersion") != expected.get("modelVersion"):
        raise ValueError("OBJECTIVE_RATING_MODEL_VERSION_MISMATCH")
    if payload.get("schemaVersion") != expected.get("schemaVersion"):
        raise ValueError("OBJECTIVE_RATING_SCHEMA_VERSION_MISMATCH")
    if payload.get("methodologyBoundaries", {}).get(
        "forwardDecisionQualityValidationExecuted"
    ):
        raise ValueError("OBJECTIVE_GATE_ALREADY_MARKED_FORWARD_EXECUTED")
    securities = payload.get("securities")
    if not isinstance(securities, list) or not securities:
        raise ValueError("OBJECTIVE_RATING_SECURITIES_REQUIRED")
    symbols = [str(item.get("symbol")) for item in securities]
    if len(set(symbols)) != len(symbols):
        raise ValueError("OBJECTIVE_RATING_DUPLICATE_SYMBOL")
    if int(payload.get("scoredSecurityCount", -1)) != len(symbols):
        raise ValueError("OBJECTIVE_RATING_COUNT_MISMATCH")
    if any(item.get("status") != "SCORED" for item in securities):
        raise ValueError("OBJECTIVE_RATING_NON_SCORED_SECURITY")
    for item in securities:
        _require_sha256(
            item.get("inputPayloadHash"),
            f"objectiveRating.{item.get('symbol')}.inputPayloadHash",
        )
    as_of = _parse_datetime(payload.get("asOfTime"), "objectiveRating.asOfTime")
    return set(symbols), {
        "status": "PASS",
        "modelVersion": payload["strategyVersion"],
        "schemaVersion": payload["schemaVersion"],
        "scope": payload["scope"],
        "decisionCutoff": as_of.isoformat().replace("+00:00", "Z"),
        "scoredSecurityCount": len(symbols),
    }


def _validate_tactical_contract(
    payload: dict[str, Any],
    expected: dict[str, Any],
) -> tuple[set[str], dict[str, Any], dict[str, Any]]:
    if payload.get("modelVersion") != expected.get("modelVersion"):
        raise ValueError("TACTICAL_MODEL_VERSION_MISMATCH")
    if payload.get("schemaVersion") != expected.get("schemaVersion"):
        raise ValueError("TACTICAL_SCHEMA_VERSION_MISMATCH")
    if payload.get("rawProviderValuesIncluded") is not False:
        raise ValueError("TACTICAL_GIT_SAFE_BOUNDARY_FAILED")
    if payload.get("statisticalEdgeProven") != "NOT_ESTABLISHED":
        raise ValueError("TACTICAL_EDGE_CLAIM_NOT_ALLOWED")
    generated_at = _parse_datetime(
        payload.get("generatedAt"),
        "tacticalSignal.generatedAt",
    )
    source_window = payload.get("sourceWindow")
    if not isinstance(source_window, dict):
        raise ValueError("TACTICAL_SOURCE_WINDOW_REQUIRED")
    source_end = _parse_date(source_window.get("to"), "tacticalSignal.sourceWindow.to")
    results = _tactical_results(payload)
    actionability = Counter()
    entry_stages = Counter()
    horizon_outlooks: dict[int, Counter[str]] = {
        horizon: Counter() for horizon in HORIZONS
    }
    historical_episode_counts = Counter()
    assessed_dates: set[date] = set()
    assessed_symbols: set[str] = set()
    abstention_count = 0
    insufficient_count = 0
    for symbol, result in sorted(results.items()):
        status = str(result.get("status"))
        if status not in TACTICAL_RESULT_STATUSES:
            raise ValueError(f"TACTICAL_RESULT_STATUS_UNKNOWN[{symbol}]")
        if status != "ASSESSED":
            insufficient_count += 1
            abstention_count += 1
            continue
        assessed_symbols.add(symbol)
        as_of = _parse_date(result.get("asOfDate"), f"tacticalSignal.{symbol}.asOf")
        assessed_dates.add(as_of)
        if as_of > source_end or as_of > generated_at.date():
            raise ValueError(f"TACTICAL_FUTURE_DECISION_DATE[{symbol}]")
        if result.get("dataCadence") != "COMPLETED_DAILY_SESSION":
            raise ValueError(f"TACTICAL_INCOMPLETE_SESSION_CONTRACT[{symbol}]")
        if result.get("effectiveFrom") != "NEXT_SESSION_OPEN":
            raise ValueError(f"TACTICAL_SAME_SESSION_EXECUTION_RISK[{symbol}]")
        if int(result.get("signalTtlCompletedSessions", -1)) != 1:
            raise ValueError(f"TACTICAL_SIGNAL_TTL_MISMATCH[{symbol}]")
        horizon_rows = result.get("horizons")
        if not isinstance(horizon_rows, list):
            raise ValueError(f"TACTICAL_HORIZONS_REQUIRED[{symbol}]")
        observed_horizons = {
            int(item.get("tradingDays")) for item in horizon_rows
        }
        if observed_horizons != set(HORIZONS):
            raise ValueError(f"TACTICAL_HORIZON_SET_MISMATCH[{symbol}]")
        for item in horizon_rows:
            outlook = str(item.get("outlook"))
            if outlook not in TACTICAL_HORIZON_OUTLOOKS:
                raise ValueError(f"TACTICAL_HORIZON_OUTLOOK_UNKNOWN[{symbol}]")
            horizon_outlooks[int(item["tradingDays"])][outlook] += 1
        action = str(result.get("actionability"))
        stage = str(result.get("entryStage"))
        if action not in TACTICAL_ACTIONABILITY:
            raise ValueError(f"TACTICAL_ACTIONABILITY_UNKNOWN[{symbol}]")
        if stage not in TACTICAL_ENTRY_STAGES:
            raise ValueError(f"TACTICAL_ENTRY_STAGE_UNKNOWN[{symbol}]")
        risk_multiplier = result.get("maximumRiskUnitMultiplier")
        if (
            isinstance(risk_multiplier, bool)
            or not isinstance(risk_multiplier, int | float)
            or not 0.0 <= float(risk_multiplier) <= 1.0
        ):
            raise ValueError(f"TACTICAL_RISK_MULTIPLIER_INVALID[{symbol}]")
        if action == "WAIT_FOR_PULLBACK" and (
            stage != "CONFIRMED" or float(risk_multiplier) != 0.0
        ):
            raise ValueError(
                f"TACTICAL_PULLBACK_WAIT_MUST_BE_ZERO_RISK[{symbol}]"
            )
        if action == "ENTRY" and stage != "CONFIRMED":
            raise ValueError(f"TACTICAL_ENTRY_STAGE_MISMATCH[{symbol}]")
        if action == "LIMITED_ENTRY" and stage != "PROBE_ELIGIBLE":
            raise ValueError(f"TACTICAL_LIMITED_ENTRY_STAGE_MISMATCH[{symbol}]")
        actionability[action] += 1
        entry_stages[stage] += 1
        if action not in {"ENTRY", "LIMITED_ENTRY"}:
            abstention_count += 1
        walk_forward = result.get("walkForward", [])
        if not isinstance(walk_forward, list):
            raise ValueError(f"TACTICAL_WALK_FORWARD_ROWS_REQUIRED[{symbol}]")
        for row in walk_forward:
            if row.get("statisticalEdgeProven") != "NOT_ESTABLISHED":
                raise ValueError(f"TACTICAL_WALK_FORWARD_EDGE_CLAIM[{symbol}]")
            horizon = int(row.get("horizonTradingDays"))
            if horizon not in HORIZONS:
                raise ValueError(f"TACTICAL_WALK_FORWARD_HORIZON[{symbol}]")
            historical_episode_counts[horizon] += int(
                row.get("episodeCount", 0)
            )
    if not assessed_dates:
        raise ValueError("TACTICAL_ASSESSED_RESULT_REQUIRED")
    return assessed_symbols, {
        "status": "PASS",
        "modelVersion": payload["modelVersion"],
        "schemaVersion": payload["schemaVersion"],
        "executionMode": payload.get("executionMode"),
        "generatedAt": generated_at.isoformat().replace("+00:00", "Z"),
        "sourceWindow": source_window,
        "assessedSecurityCount": len(results) - insufficient_count,
        "insufficientSecurityCount": insufficient_count,
        "decisionDates": sorted(item.isoformat() for item in assessed_dates),
        "effectiveFrom": "NEXT_SESSION_OPEN",
        "signalTtlCompletedSessions": 1,
        "actionabilityCounts": dict(sorted(actionability.items())),
        "entryStageCounts": dict(sorted(entry_stages.items())),
        "abstentionCount": abstention_count,
        "horizonOutlookCounts": {
            str(horizon): dict(sorted(values.items()))
            for horizon, values in horizon_outlooks.items()
        },
    }, {
        "status": "DESCRIPTIVE_DIAGNOSTIC_ONLY",
        "prospectiveOutcomeEvidence": False,
        "survivorshipBiasControlled": False,
        "survivorshipStatus": "NOT_PROVEN_NAMED_SECURITY_SAMPLE",
        "costAdjusted": True,
        "totalEpisodeRowsByHorizon": {
            str(horizon): historical_episode_counts[horizon]
            for horizon in HORIZONS
        },
        "statisticalEdgeProven": "NOT_ESTABLISHED",
    }


def _validate_operational_sources(
    *,
    objective: dict[str, Any],
    weekly: dict[str, Any],
    daily: dict[str, Any],
    preflight: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    objective_hash = objective["artifactContentHash"]
    if weekly.get("sourceAlgorithmGate", {}).get(
        "artifactContentHash"
    ) != objective_hash:
        raise ValueError("WEEKLY_SOURCE_GATE_HASH_MISMATCH")
    if daily.get("sourceAlgorithmGate", {}).get(
        "artifactContentHash"
    ) != objective_hash:
        raise ValueError("DAILY_SOURCE_GATE_HASH_MISMATCH")
    if daily.get("supersedes", {}).get(
        "artifactContentHash"
    ) != weekly.get("artifactContentHash"):
        raise ValueError("DAILY_SUPERSESSION_HASH_MISMATCH")
    if preflight.get("experimentId") != weekly.get("experimentId"):
        raise ValueError("PREFLIGHT_EXPERIMENT_ID_MISMATCH")
    if set(weekly.get("shadowArms", [])) != set(REQUIRED_SHADOW_ARMS):
        raise ValueError("SHADOW_ARM_CONTRACT_MISMATCH")
    if tuple(weekly.get("observationHorizonsTradingDays", [])) != HORIZONS:
        raise ValueError("WEEKLY_HORIZON_CONTRACT_MISMATCH")
    if tuple(contract.get("observationHorizonsTradingDays", [])) != HORIZONS:
        raise ValueError("EXPECTED_HORIZON_CONTRACT_MISMATCH")
    costs = weekly.get("costAssumptions")
    if costs != contract.get("costAssumptions"):
        raise ValueError("COST_ASSUMPTION_CONTRACT_MISMATCH")
    round_trip_cost = sum(
        int(costs[field])
        for field in (
            "buyTransactionCostBps",
            "buySlippageBps",
            "hypotheticalSaleTransactionCostBps",
            "hypotheticalSaleSlippageBps",
        )
    )
    if round_trip_cost != int(contract.get("roundTripCostAndSlippageBps")):
        raise ValueError("ROUND_TRIP_COST_CONTRACT_MISMATCH")
    if contract.get("sameSessionExecutionPermitted") is not False:
        raise ValueError("SAME_SESSION_EXECUTION_MUST_BE_FALSE")
    if any(
        int(source.get("signalsEnrolled", 0)) != 0
        for source in (weekly, daily, preflight)
    ):
        raise ValueError("UNMODELED_ENROLLED_SIGNALS_PRESENT")
    if weekly.get("futureOutcomesObserved") is not False:
        raise ValueError("UNMODELED_FUTURE_OUTCOME_PRESENT")
    objective_sectors = {
        str(item.get("sector")) for item in objective.get("securities", [])
    }
    benchmark_map = weekly.get("sectorBenchmarks")
    if not isinstance(benchmark_map, dict):
        raise ValueError("SECTOR_BENCHMARK_MAP_REQUIRED")
    missing_sector_mappings = sorted(objective_sectors - set(benchmark_map))
    if missing_sector_mappings:
        raise ValueError(
            "OBJECTIVE_SECTOR_BENCHMARK_MISSING["
            + ",".join(missing_sector_mappings)
            + "]"
        )
    return {
        "frameworkImplementation": "PASS",
        "currentEnrollmentStatus": (
            "PENDING_FRESH_SYNCHRONIZED_DECISION_SNAPSHOT"
        ),
        "legacyWeeklyStatus": weekly.get("status"),
        "dailyProtocolStatus": daily.get("status"),
        "preflightEnrollmentReady": bool(preflight.get("enrollmentReady")),
        "signalsEnrolled": 0,
        "futureOutcomesObserved": False,
        "costAssumptions": costs,
        "roundTripCostAndSlippageBps": round_trip_cost,
        "baselineArms": contract.get("comparisonBaselines"),
        "policyArm": contract.get("policyArm"),
        "benchmarkComparisons": contract.get("benchmarkComparisons"),
        "sectorBenchmarkCoverage": {
            "status": "PASS",
            "coveredObjectiveSectorCount": len(objective_sectors),
            "missingSectors": [],
        },
    }


def build_final_acceptance(
    *,
    repository_root: Path,
    expected_contract_manifest_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    manifest = _load(expected_contract_manifest_path)
    manifest_hash = _verify_embedded_hash(
        manifest,
        hash_field="artifactContentHash",
        label="expectedContractManifest",
    )
    if manifest.get("schemaVersion") != EXPECTED_CONTRACTS_SCHEMA_VERSION:
        raise ValueError("EXPECTED_CONTRACT_SCHEMA_VERSION_MISMATCH")
    loaded = _verify_manifest_sources(repository_root, manifest)
    objective = loaded["objectiveRating"][1]
    tactical = loaded["tacticalSignal"][1]
    weekly = loaded["weeklyPreregistration"][1]
    daily = loaded["dailyProtocol"][1]
    preflight = loaded["enrollmentPreflight"][1]
    expected_models = manifest.get("deterministicModelContracts")
    if not isinstance(expected_models, dict):
        raise ValueError("EXPECTED_MODEL_CONTRACTS_REQUIRED")
    objective_symbols, objective_acceptance = _validate_objective_contract(
        objective,
        expected_models.get("objectiveRating", {}),
    )
    (
        tactical_symbols,
        tactical_acceptance,
        historical_diagnostics,
    ) = _validate_tactical_contract(
        tactical,
        expected_models.get("tacticalSignal", {}),
    )
    contract = manifest.get("forwardEvaluationContract")
    if not isinstance(contract, dict):
        raise ValueError("FORWARD_EVALUATION_CONTRACT_REQUIRED")
    operational = _validate_operational_sources(
        objective=objective,
        weekly=weekly,
        daily=daily,
        preflight=preflight,
        contract=contract,
    )
    objective_date = _parse_datetime(
        objective["asOfTime"],
        "objectiveRating.asOfTime",
    ).date()
    tactical_dates = {
        _parse_date(value, "tacticalSignal.decisionDate")
        for value in tactical_acceptance["decisionDates"]
    }
    synchronized = tactical_dates == {objective_date}
    intersection = sorted(objective_symbols & tactical_symbols)
    full_joint_coverage = objective_symbols <= tactical_symbols
    outcome_rows = [
        {
            "horizonTradingDays": horizon,
            "status": PENDING_FUTURE_OUTCOMES,
            "prospectiveCompletedEpisodeCount": 0,
            "baselineComparisonStatus": PENDING_FUTURE_OUTCOMES,
            "sectorBenchmarkComparisonStatus": PENDING_FUTURE_OUTCOMES,
            "spyComparisonStatus": PENDING_FUTURE_OUTCOMES,
            "calibrationStatus": PENDING_FUTURE_OUTCOMES,
            "reason": (
                "No signal has been enrolled under a fresh synchronized "
                "decision snapshot, so no prospective horizon is mature."
            ),
        }
        for horizon in HORIZONS
    ]
    evidence_descriptors = manifest["sourceArtifacts"]
    source_evidence_hash = canonical_hash(
        [
            {
                "role": role,
                "path": descriptor["path"],
                "fileSha256": descriptor["fileSha256"],
                "embeddedContentHash": descriptor["embeddedContentHash"],
            }
            for role, descriptor in sorted(evidence_descriptors.items())
        ]
    )
    artifact = {
        "artifactType": "FORWARD_DECISION_QUALITY_FINAL_OFFLINE_ACCEPTANCE",
        "schemaVersion": FINAL_ACCEPTANCE_SCHEMA_VERSION,
        "status": PENDING_FUTURE_OUTCOMES,
        "evaluatedFromEvidenceAt": manifest["assembledFromEvidenceAt"],
        "expectedContractManifest": {
            "path": _relative_path(
                repository_root,
                expected_contract_manifest_path,
            ),
            "fileSha256": _file_sha256(expected_contract_manifest_path),
            "artifactContentHash": manifest_hash,
        },
        "frameworkAcceptance": "PASS",
        "deterministicModelAcceptance": {
            "objectiveRating": objective_acceptance,
            "tacticalSignal": tactical_acceptance,
            "jointDecisionSnapshot": {
                "status": (
                    "PASS"
                    if synchronized and full_joint_coverage
                    else "PENDING_FRESH_SYNCHRONIZED_DECISION_SNAPSHOT"
                ),
                "timestampsSynchronized": synchronized,
                "fullObjectiveUniverseTacticalCoverage": full_joint_coverage,
                "objectiveSecurityCount": len(objective_symbols),
                "tacticalSecurityCount": len(tactical_symbols),
                "intersectionCount": len(intersection),
                "intersectionSymbolsHash": canonical_hash(intersection),
            },
        },
        "operationalReadiness": operational,
        "decisionTimingAndExecution": {
            "status": "PASS",
            "objectiveDecisionCutoff": objective_acceptance["decisionCutoff"],
            "tacticalDecisionDates": tactical_acceptance["decisionDates"],
            "decisionCutoffRule": contract["decisionCutoffRule"],
            "executionRule": contract["executionRule"],
            "tacticalEffectiveFrom": tactical_acceptance["effectiveFrom"],
            "sameSessionExecutionPermitted": False,
            "tacticalSignalTtlCompletedSessions": tactical_acceptance[
                "signalTtlCompletedSessions"
            ],
        },
        "prospectiveOutcomeEvidence": {
            "status": PENDING_FUTURE_OUTCOMES,
            "signalsEnrolled": 0,
            "realizedProspectiveEpisodeCount": 0,
            "horizons": outcome_rows,
            "preliminaryConclusion": "INSUFFICIENT_SAMPLE",
            "statisticalEdgeProven": "NOT_ESTABLISHED",
        },
        "calibrationAndCoverageContract": {
            "status": PENDING_FUTURE_OUTCOMES,
            "minimumOverallCompletedEpisodes": contract[
                "minimumOverallCompletedEpisodes"
            ],
            "minimumSectorOrSizeCompletedEpisodes": contract[
                "minimumSectorOrSizeCompletedEpisodes"
            ],
            "requiredCoverageMeasures": [
                "ENROLLED_TO_MATURED_EPISODE_RATE",
                "ABSTENTION_RATE_AND_REASON",
                "MISSING_OR_STALE_INPUT_RATE",
                "TACTICAL_OUTLOOK_CALIBRATION_BY_HORIZON",
                "ENTRY_STAGE_CALIBRATION_BY_HORIZON",
                "OBJECTIVE_TOP_MINUS_BOTTOM_SPREAD",
                "SECTOR_AND_SPY_RELATIVE_RETURN_AFTER_COSTS",
            ],
            "currentTacticalAbstentionCount": tactical_acceptance[
                "abstentionCount"
            ],
            "missingValuesRemainExplicit": True,
            "missingValuesCoercedToNeutralOrZero": False,
        },
        "contaminationControls": {
            "immutableDecisionArtifactsVerified": True,
            "allSourceFileHashesVerified": True,
            "allEmbeddedContentHashesVerified": True,
            "noSameSessionExecution": True,
            "objectiveCurrentSnapshotNotRelabeledHistoricalPit": True,
            "dailyCohortOverlapReported": True,
            "sameSecurityStrategyBucketCooldownTradingDays": 60,
            "identityDelistingAndCorporateActionCoverage": (
                "PENDING_AT_ENROLLMENT"
            ),
            "survivorshipContaminationControl": (
                "PENDING_PROSPECTIVE_IDENTITY_AND_ACTION_GATES"
            ),
            "lookAheadContaminationStatus": (
                "PASS_FOR_FRAMEWORK_PENDING_PROSPECTIVE_OBSERVATIONS"
            ),
        },
        "historicalWalkForwardDiagnostics": historical_diagnostics,
        "evidence": {
            "sourceArtifacts": evidence_descriptors,
            "sourceEvidenceSetHash": source_evidence_hash,
        },
        "claimBoundary": {
            "operationalReadinessIsPerformanceEvidence": False,
            "historicalWalkForwardIsProspectiveEvidence": False,
            "oneMonthOutcomeObserved": False,
            "threeMonthOutcomeObserved": False,
            "realizedReturnClaimAuthorized": False,
            "automaticTradingAuthorized": False,
            "recommendationAuthorized": False,
        },
        "networkRequestsExecuted": False,
        "providerRequestsExecuted": 0,
        "databaseWritesExecuted": False,
        "scoringExecuted": False,
        "commitPushOrDeploymentExecuted": False,
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    _write_or_verify(
        output_path,
        artifact,
        "FORWARD_FINAL_ACCEPTANCE_CONFLICT",
    )
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a hash-bound offline acceptance for the current Forward "
            "Decision-Quality Validation contracts."
        )
    )
    parser.add_argument(
        "--objective-rating",
        type=Path,
        default=Path(
            "docs/generated/"
            "objective-rating-v1-current-snapshot-algorithm-gate-v1.json"
        ),
    )
    parser.add_argument(
        "--tactical-signal",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--weekly-preregistration",
        type=Path,
        default=Path(
            "docs/generated/forward-decision-quality-preregistration-v1.json"
        ),
    )
    parser.add_argument(
        "--daily-protocol",
        type=Path,
        default=Path(
            "docs/generated/forward-daily-incremental-protocol-v1.json"
        ),
    )
    parser.add_argument(
        "--enrollment-preflight",
        type=Path,
        default=Path(
            "docs/generated/forward-enrollment-operational-preflight-v1.json"
        ),
    )
    parser.add_argument(
        "--expected-contracts-output",
        type=Path,
        default=Path(
            "docs/generated/forward-decision-quality-expected-contracts-v1.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/forward-decision-quality-final-acceptance-v1.json"
        ),
    )
    arguments = parser.parse_args()
    root = Path.cwd().resolve()

    def resolved(path: Path) -> Path:
        return (root / path).resolve()

    manifest = build_expected_contract_manifest(
        repository_root=root,
        objective_rating_path=resolved(arguments.objective_rating),
        tactical_signal_path=resolved(arguments.tactical_signal),
        weekly_preregistration_path=resolved(arguments.weekly_preregistration),
        daily_protocol_path=resolved(arguments.daily_protocol),
        enrollment_preflight_path=resolved(arguments.enrollment_preflight),
        output_path=resolved(arguments.expected_contracts_output),
    )
    acceptance = build_final_acceptance(
        repository_root=root,
        expected_contract_manifest_path=resolved(
            arguments.expected_contracts_output
        ),
        output_path=resolved(arguments.output),
    )
    print(
        json.dumps(
            {
                "status": acceptance["status"],
                "frameworkAcceptance": acceptance["frameworkAcceptance"],
                "objectiveModelVersion": manifest[
                    "deterministicModelContracts"
                ]["objectiveRating"]["modelVersion"],
                "tacticalModelVersion": manifest[
                    "deterministicModelContracts"
                ]["tacticalSignal"]["modelVersion"],
                "artifactContentHash": acceptance["artifactContentHash"],
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
