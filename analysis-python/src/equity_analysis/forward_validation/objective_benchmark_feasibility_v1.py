from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.daily_refresh.universe import SECURITY_NAMESPACE
from equity_analysis.forward_validation.preregistration_seal_v21 import (
    load_preregistration_seal_bundle,
)

OBJECTIVE_BENCHMARK_FEASIBILITY_V1 = (
    "OBJECTIVE-BENCHMARK-COVERAGE-LINEAGE-FEASIBILITY-v1.0.0"
)
QUALITY_MODEL_VERSION = "QC-v1.0.0"
VALUE_MODEL_VERSION = "UQ-v1.0.0"
MINIMUM_SCORE_COUNT = 20
MINIMUM_INCLUDED_COVERAGE = Decimal("0.80")
UNIVERSE_RELATIVE_PATH = Path(
    "analysis-python/resources/universes/market-intelligence-closed-test-us-v1.json"
)
INPUT_MANIFEST_RELATIVE_PATH = Path(
    "docs/generated/objective-rating-v1-current-decision-input-manifest-v1.json"
)
ALGORITHM_GATE_RELATIVE_PATH = Path(
    "docs/generated/objective-rating-v1-current-snapshot-algorithm-gate-v1.json"
)
_HASH_PATTERN = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")


class FeasibilityState(StrEnum):
    READY = "READY"
    MISSING = "MISSING"


@dataclass(frozen=True)
class ObjectiveDatabaseInventory:
    data_snapshot_id: UUID
    snapshot_state: str
    snapshot_as_of: datetime
    ingestion_cutoff: datetime
    universe_version: str
    included_count: int
    reference_only_count: int
    excluded_count: int
    succeeded_screening_run_count: int
    quant_eligible_count: int
    coverage_quality_score_count: int
    coverage_valuation_score_count: int
    scored_quality_strategy_count: int
    scored_value_strategy_count: int
    factor_result_count: int
    factor_result_with_lineage_count: int
    scored_profile_count: int
    profile_quality_score_count: int
    profile_valuation_score_count: int
    source_record_content_hashes: frozenset[str]


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _normalized_hash(value: str) -> str:
    match = _HASH_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("Expected a SHA-256 value")
    return f"sha256:{match.group(1).lower()}"


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _aware(value, "Artifact timestamp").isoformat().replace("+00:00", "Z")


def _verify_git_safe_artifact(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    expected = str(payload.get("artifactContentHash", ""))
    body = dict(payload)
    body.pop("artifactContentHash", None)
    actual = canonical_hash(body)
    if _normalized_hash(expected) != actual:
        raise ValueError(f"Artifact canonical hash is invalid: {path}")
    return payload, _file_sha256(path)


def _verify_controlled_input(
    repository_root: Path,
    row: dict[str, Any],
) -> dict[str, Any]:
    relative_path = Path(str(row["storageReference"]))
    if relative_path.is_absolute():
        raise ValueError("Controlled input reference must be repository-relative")
    path = repository_root / relative_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = _normalized_hash(str(row["payloadContentHash"]))
    content_hash = _normalized_hash(str(payload.get("contentHash", "")))
    body = dict(payload)
    body.pop("contentHash", None)
    if content_hash != expected or canonical_hash(body) != expected:
        raise ValueError(f"Controlled Objective input hash is invalid: {relative_path}")
    if payload.get("scoresOrRanksIncluded") is not False:
        raise ValueError("Controlled Objective input unexpectedly contains scores")
    return payload


def _maximum_available_at(operands: dict[str, Any]) -> datetime | None:
    values: list[datetime] = []
    for operand in operands.values():
        raw = operand.get("availableAt")
        if raw:
            values.append(
                _aware(
                    datetime.fromisoformat(str(raw).replace("Z", "+00:00")),
                    "Operand availableAt",
                )
            )
    return max(values) if values else None


def _lineage_summary(payload: dict[str, Any]) -> tuple[bool, str, tuple[str, ...]]:
    operands = payload.get("operands")
    if not isinstance(operands, dict) or not operands:
        return False, "NO_OPERAND_LINEAGE", ()
    source_hashes: set[str] = set()
    for operand in operands.values():
        required = (
            "availableAt",
            "orderedEvidenceIds",
            "periodIds",
            "sourceAccessions",
            "sourceContentHashes",
            "status",
        )
        if any(field not in operand for field in required):
            return False, "OPERAND_LINEAGE_INCOMPLETE", ()
        for value in operand["sourceContentHashes"]:
            source_hashes.add(_normalized_hash(str(value)))
    return True, "OPERAND_LINEAGE_PRESENT", tuple(sorted(source_hashes))


def inspect_objective_database(
    connection: Any,
    *,
    data_snapshot_id: UUID,
) -> ObjectiveDatabaseInventory:
    snapshot = connection.execute(
        """
        SELECT status, as_of_time, ingestion_cutoff
        FROM analytics.data_snapshot
        WHERE id = %s
        """,
        (data_snapshot_id,),
    ).fetchone()
    if snapshot is None:
        raise ValueError("Objective feasibility snapshot does not exist")
    member_rows = connection.execute(
        """
        SELECT universe_version, membership_status, COUNT(*)
        FROM analytics.snapshot_universe_member
        WHERE snapshot_id = %s
        GROUP BY universe_version, membership_status
        """,
        (data_snapshot_id,),
    ).fetchall()
    if not member_rows:
        raise ValueError("Objective feasibility snapshot has no universe members")
    universe_versions = {str(row[0]) for row in member_rows}
    if len(universe_versions) != 1:
        raise ValueError("Objective feasibility snapshot has multiple universes")
    member_counts = {str(row[1]): int(row[2]) for row in member_rows}
    run_row = connection.execute(
        """
        SELECT COUNT(*) FILTER (WHERE status = 'SUCCEEDED')
        FROM analytics.screening_run
        WHERE snapshot_id = %s
        """,
        (data_snapshot_id,),
    ).fetchone()
    coverage = connection.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE coverage.coverage_state = 'QUANT_ELIGIBLE'),
            COUNT(coverage.quality_score),
            COUNT(coverage.valuation_score)
        FROM analytics.coverage_result coverage
        JOIN analytics.screening_run run ON run.id = coverage.run_id
        WHERE run.snapshot_id = %s
          AND run.status = 'SUCCEEDED'
        """,
        (data_snapshot_id,),
    ).fetchone()
    strategies = connection.execute(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE rating.strategy_version = %s AND rating.status = 'SCORED'
            ),
            COUNT(*) FILTER (
                WHERE rating.strategy_version = %s AND rating.status = 'SCORED'
            )
        FROM analytics.strategy_rating rating
        JOIN analytics.screening_run run ON run.id = rating.run_id
        WHERE run.snapshot_id = %s
          AND run.status = 'SUCCEEDED'
        """,
        (QUALITY_MODEL_VERSION, VALUE_MODEL_VERSION, data_snapshot_id),
    ).fetchone()
    factors = connection.execute(
        """
        SELECT
            COUNT(DISTINCT factor.id),
            COUNT(DISTINCT factor.id) FILTER (
                WHERE lineage.source_record_id IS NOT NULL
            )
        FROM analytics.factor_result factor
        JOIN analytics.screening_run run ON run.id = factor.run_id
        LEFT JOIN analytics.factor_result_lineage lineage
          ON lineage.factor_result_id = factor.id
        WHERE run.snapshot_id = %s
          AND run.status = 'SUCCEEDED'
        """,
        (data_snapshot_id,),
    ).fetchone()
    profiles = connection.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE objective_rating_status = 'SCORED'),
            COUNT(objective_quality_score),
            COUNT(objective_valuation_score)
        FROM analytics.security_profile_snapshot
        WHERE data_snapshot_id = %s
        """,
        (data_snapshot_id,),
    ).fetchone()
    source_record_rows = connection.execute(
        """
        SELECT DISTINCT content_hash
        FROM analytics.source_record
        """
    ).fetchall()
    return ObjectiveDatabaseInventory(
        data_snapshot_id=data_snapshot_id,
        snapshot_state=str(snapshot[0]),
        snapshot_as_of=_aware(snapshot[1], "Snapshot as-of"),
        ingestion_cutoff=_aware(snapshot[2], "Snapshot ingestion cutoff"),
        universe_version=next(iter(universe_versions)),
        included_count=member_counts.get("INCLUDED", 0),
        reference_only_count=member_counts.get("REFERENCE_ONLY", 0),
        excluded_count=member_counts.get("EXCLUDED", 0),
        succeeded_screening_run_count=int(run_row[0]),
        quant_eligible_count=int(coverage[0]),
        coverage_quality_score_count=int(coverage[1]),
        coverage_valuation_score_count=int(coverage[2]),
        scored_quality_strategy_count=int(strategies[0]),
        scored_value_strategy_count=int(strategies[1]),
        factor_result_count=int(factors[0]),
        factor_result_with_lineage_count=int(factors[1]),
        scored_profile_count=int(profiles[0]),
        profile_quality_score_count=int(profiles[1]),
        profile_valuation_score_count=int(profiles[2]),
        source_record_content_hashes=frozenset(
            _normalized_hash(str(row[0])) for row in source_record_rows
        ),
    )


def _source_binding(path: Path, payload: dict[str, Any], file_hash: str) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "fileSha256": file_hash,
        "artifactContentHash": _normalized_hash(
            str(payload["artifactContentHash"])
        ),
    }


def build_objective_benchmark_feasibility_artifact(
    *,
    repository_root: Path,
    database: ObjectiveDatabaseInventory,
    evaluated_at: datetime,
) -> dict[str, Any]:
    preregistration = load_preregistration_seal_bundle(
        repository_root=repository_root
    )
    universe_path = repository_root / UNIVERSE_RELATIVE_PATH
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    if universe["universeVersion"] != database.universe_version:
        raise ValueError("Database and frozen universe versions differ")
    included_symbols = tuple(
        str(symbol)
        for role in ("PRIMARY", "RESERVE")
        for symbol in universe["roles"][role]
    )
    if len(included_symbols) != 55 or database.included_count != 55:
        raise ValueError("Objective benchmark denominator must be 55 included members")
    input_path = repository_root / INPUT_MANIFEST_RELATIVE_PATH
    gate_path = repository_root / ALGORITHM_GATE_RELATIVE_PATH
    input_manifest, input_file_hash = _verify_git_safe_artifact(input_path)
    gate, gate_file_hash = _verify_git_safe_artifact(gate_path)
    if (
        input_manifest.get("scoresOrRanksIncluded") is not False
        or input_manifest.get("networkRequestsExecuted") is not False
        or gate.get("strategyVersion") != QUALITY_MODEL_VERSION
        or gate.get("networkRequestsExecuted") is not False
    ):
        raise ValueError("Objective evidence does not match the accepted offline contract")
    gate_as_of = _aware(
        datetime.fromisoformat(str(gate["asOfTime"]).replace("Z", "+00:00")),
        "Objective gate as-of",
    )
    input_rows = {
        str(row["symbol"]): row for row in input_manifest["securities"]
    }
    gate_rows = {
        str(row["symbol"]): row
        for row in gate["securities"]
        if row.get("status") == "SCORED"
    }
    security_rows: list[dict[str, Any]] = []
    diagnostic_quality_count = 0
    diagnostic_uq_ready_count = 0
    verified_controlled_input_count = 0
    operand_lineage_count = 0
    controlled_source_hashes: set[str] = set()
    quality_diagnostic_source_hashes: set[str] = set()
    for symbol in included_symbols:
        input_row = input_rows.get(symbol)
        gate_row = gate_rows.get(symbol)
        input_hash: str | None = None
        diagnostic_available_at: datetime | None = None
        lineage_hash: str | None = None
        lineage_status = "MISSING"
        current_uq_ready = False
        source_hashes: tuple[str, ...] = ()
        if input_row is not None:
            controlled = _verify_controlled_input(repository_root, input_row)
            verified_controlled_input_count += 1
            input_hash = _normalized_hash(str(input_row["payloadContentHash"]))
            current_uq_ready = bool(controlled.get("currentUqInputReady"))
            diagnostic_uq_ready_count += int(current_uq_ready)
            complete, lineage_status, source_hashes = _lineage_summary(controlled)
            diagnostic_available_at = _maximum_available_at(
                controlled.get("operands", {})
            )
            if complete:
                operand_lineage_count += 1
                controlled_source_hashes.update(source_hashes)
                lineage_hash = canonical_hash(
                    {
                        "inputPayloadHash": input_hash,
                        "sourceContentHashes": source_hashes,
                        "availableAt": diagnostic_available_at,
                    }
                )
        quality_diagnostic_present = (
            gate_row is not None
            and input_hash is not None
            and _normalized_hash(str(gate_row["inputPayloadHash"])) == input_hash
            and gate_row["strategyVersion"] == QUALITY_MODEL_VERSION
        )
        if quality_diagnostic_present:
            diagnostic_quality_count += 1
            quality_diagnostic_source_hashes.update(source_hashes)
        public_security_id = uuid5(SECURITY_NAMESPACE, f"US:{symbol}")
        security_rows.append(
            {
                "symbol": symbol,
                "publicSecurityId": str(public_security_id),
                "membershipStatus": "INCLUDED",
                "pureQuality": {
                    "formalState": FeasibilityState.MISSING,
                    "diagnosticEvidenceStatus": (
                        "PRESENT_PRE_PREREGISTRATION"
                        if quality_diagnostic_present
                        else "MISSING"
                    ),
                    "modelVersion": (
                        QUALITY_MODEL_VERSION if quality_diagnostic_present else None
                    ),
                    "effectiveAt": (
                        _iso(gate_as_of) if quality_diagnostic_present else None
                    ),
                    "availableAt": (
                        _iso(diagnostic_available_at)
                        if quality_diagnostic_present
                        else None
                    ),
                    "ingestedAt": None,
                    "inputPayloadHash": (
                        input_hash if quality_diagnostic_present else None
                    ),
                    "lineageEvidenceHash": (
                        lineage_hash if quality_diagnostic_present else None
                    ),
                    "lineageStatus": (
                        lineage_status
                        if quality_diagnostic_present
                        else "MISSING"
                    ),
                    "reasonCodes": (
                        [
                            "PRE_REGISTRATION_DEVELOPMENT_EVIDENCE",
                            "SCORE_LEVEL_INGESTED_AT_NOT_RETAINED",
                        ]
                        if quality_diagnostic_present
                        else ["NO_ACCEPTED_OBJECTIVE_QUALITY_SCORE"]
                    ),
                },
                "pureValue": {
                    "formalState": FeasibilityState.MISSING,
                    "diagnosticInputReady": current_uq_ready,
                    "modelVersion": VALUE_MODEL_VERSION,
                    "effectiveAt": None,
                    "availableAt": None,
                    "ingestedAt": None,
                    "inputPayloadHash": input_hash,
                    "lineageEvidenceHash": lineage_hash,
                    "lineageStatus": lineage_status,
                    "reasonCodes": ["NO_ACCEPTED_OBJECTIVE_VALUE_SCORE"],
                },
            }
        )
    required_count = max(
        MINIMUM_SCORE_COUNT,
        math.ceil(database.included_count * MINIMUM_INCLUDED_COVERAGE),
    )
    quality_coverage = Decimal(diagnostic_quality_count) / Decimal(
        database.included_count
    )
    formal_quality_count = min(
        database.scored_quality_strategy_count,
        database.coverage_quality_score_count,
        database.scored_profile_count,
        database.profile_quality_score_count,
    )
    formal_value_count = min(
        database.scored_value_strategy_count,
        database.coverage_valuation_score_count,
        database.scored_profile_count,
        database.profile_valuation_score_count,
    )
    body: dict[str, Any] = {
        "artifactType": "OBJECTIVE_BENCHMARK_COVERAGE_LINEAGE_FEASIBILITY",
        "schemaVersion": OBJECTIVE_BENCHMARK_FEASIBILITY_V1,
        "evaluatedAt": _iso(evaluated_at),
        "preregistrationSealContentHash": preregistration.seal.seal_content_hash,
        "futureDecisionMustBeStrictlyAfter": _iso(
            preregistration.seal.future_decision_must_be_strictly_after
        ),
        "dataSnapshotId": str(database.data_snapshot_id),
        "snapshotState": database.snapshot_state,
        "snapshotAsOf": _iso(database.snapshot_as_of),
        "ingestionCutoff": _iso(database.ingestion_cutoff),
        "universeVersion": database.universe_version,
        "universeFileSha256": _file_sha256(universe_path),
        "includedPopulationCount": database.included_count,
        "referenceOnlyCount": database.reference_only_count,
        "excludedCount": database.excluded_count,
        "requirements": {
            "minimumScoreCount": MINIMUM_SCORE_COUNT,
            "minimumIncludedCoverage": str(MINIMUM_INCLUDED_COVERAGE),
            "minimumRequiredOf55": required_count,
            "stablePublicSecurityIdsRequired": True,
            "postPreregistrationDecisionRequired": True,
            "completeScoreLineageRequired": True,
            "providerPassImpliesEligibility": False,
        },
        "pureQuality": {
            "state": FeasibilityState.MISSING,
            "modelVersion": QUALITY_MODEL_VERSION,
            "formalCandidateCount": formal_quality_count,
            "diagnosticPreRegistrationCandidateCount": diagnostic_quality_count,
            "diagnosticCoverageRatio": str(quality_coverage.quantize(Decimal("0.0001"))),
            "minimumRequiredCount": required_count,
            "additionalDiagnosticCandidatesRequiredForCoverage": max(
                0,
                required_count - diagnostic_quality_count,
            ),
            "additionalFormalCandidatesRequired": max(
                0,
                required_count - formal_quality_count,
            ),
            "reasonCodes": [
                "NO_POST_PREREGISTRATION_OBJECTIVE_QUALITY_RUN",
                "DIAGNOSTIC_INCLUDED_COVERAGE_BELOW_80_PERCENT",
                "SCORE_LEVEL_LINEAGE_INCOMPLETE",
            ],
        },
        "pureValue": {
            "state": FeasibilityState.MISSING,
            "modelVersion": VALUE_MODEL_VERSION,
            "formalCandidateCount": formal_value_count,
            "diagnosticInputReadyCount": diagnostic_uq_ready_count,
            "diagnosticAcceptedScoreCount": 0,
            "minimumRequiredCount": required_count,
            "additionalFormalCandidatesRequired": max(
                0,
                required_count - formal_value_count,
            ),
            "reasonCodes": [
                "NO_ACCEPTED_OBJECTIVE_VALUE_SCORE",
                "NO_POST_PREREGISTRATION_OBJECTIVE_VALUE_RUN",
                "HISTORICAL_FCF_YIELD_PIT_INPUT_REMAINS_MISSING",
            ],
        },
        "databaseInventory": {
            "succeededScreeningRunCount": database.succeeded_screening_run_count,
            "quantEligibleCount": database.quant_eligible_count,
            "coverageQualityScoreCount": database.coverage_quality_score_count,
            "coverageValuationScoreCount": database.coverage_valuation_score_count,
            "scoredQualityStrategyCount": database.scored_quality_strategy_count,
            "scoredValueStrategyCount": database.scored_value_strategy_count,
            "factorResultCount": database.factor_result_count,
            "factorResultWithLineageCount": (
                database.factor_result_with_lineage_count
            ),
            "scoredProfileCount": database.scored_profile_count,
            "profileQualityScoreCount": database.profile_quality_score_count,
            "profileValuationScoreCount": database.profile_valuation_score_count,
        },
        "controlledCacheInventory": {
            "includedManifestRowCount": sum(
                1 for symbol in included_symbols if symbol in input_rows
            ),
            "verifiedControlledInputCount": verified_controlled_input_count,
            "operandLineagePresentCount": operand_lineage_count,
            "uniqueOperandSourceContentHashCount": len(controlled_source_hashes),
            "qualityDiagnosticSourceContentHashCount": len(
                quality_diagnostic_source_hashes
            ),
            "databaseSourceRecordHashMatchCount": len(
                quality_diagnostic_source_hashes.intersection(
                    database.source_record_content_hashes
                )
            ),
            "scoreLevelIngestedAtPresentCount": 0,
            "rawProviderValuesIncluded": False,
        },
        "schemaReuse": [
            {
                "migration": "V14",
                "state": "REUSABLE",
                "responsibility": (
                    "Stable security identity, classification, and reference lineage."
                ),
            },
            {
                "migration": "V15",
                "state": "REUSABLE",
                "responsibility": (
                    "PIT metric observations and source-record timestamps/hashes."
                ),
            },
            {
                "migration": "V16",
                "state": "REUSABLE_FRESHNESS_ONLY",
                "responsibility": (
                    "Independent dataset freshness and refresh audit evidence."
                ),
            },
            {
                "migration": "V17",
                "state": "REUSABLE_PROJECTION_ONLY",
                "responsibility": (
                    "Immutable profile projection after a lineage-complete Objective run; "
                    "it is not an authoritative scoring substitute."
                ),
            },
            {
                "migration": "V8",
                "state": "REQUIRED_AUTHORITATIVE_SCORE_LEDGER",
                "responsibility": (
                    "Screening coverage, strategy scores, factor results, and "
                    "factor-to-source lineage."
                ),
            },
        ],
        "sourceBindings": {
            "inputManifest": _source_binding(
                INPUT_MANIFEST_RELATIVE_PATH,
                input_manifest,
                input_file_hash,
            ),
            "algorithmGate": _source_binding(
                ALGORITHM_GATE_RELATIVE_PATH,
                gate,
                gate_file_hash,
            ),
        },
        "independentProspectiveBlockers": [
            {
                "code": "SECTOR_REFERENCE_BENCHMARK_COVERAGE_INCOMPLETE",
                "state": "BLOCKED",
                "requiredContract": (
                    "Every included sector benchmark assignment must resolve to "
                    "a REFERENCE_ONLY security in the same frozen universe."
                ),
                "observedReferenceOnlySymbols": list(
                    universe["roles"]["REFERENCE_ONLY"]
                ),
                "impact": (
                    "Completing PURE_QUALITY or PURE_VALUE coverage alone cannot "
                    "authorize prospective enrollment."
                ),
            }
        ],
        "securities": security_rows,
        "conclusion": {
            "status": "NOT_READY_FOR_POST_PREREGISTRATION_CONSTRUCTION",
            "pureQualityReady": False,
            "pureValueReady": False,
            "newScoringExecuted": False,
            "formulaOrThresholdChanges": False,
            "pitPolicyChanges": False,
        },
        "scoresOrRanksIncluded": False,
        "licensedProviderValuesIncluded": False,
        "providerNetworkRequests": 0,
        "databaseWrites": 0,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}
