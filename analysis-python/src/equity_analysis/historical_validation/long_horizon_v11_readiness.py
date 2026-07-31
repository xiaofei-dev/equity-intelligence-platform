from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from equity_analysis.historical_validation.governance_v1 import (
    EvaluationRole,
    ValidationTerminalStatus,
)
from equity_analysis.historical_validation.model_freeze_v1 import (
    canonical_hash,
    file_sha256,
    verify_model_freeze_artifact,
)
from equity_analysis.provider_validation.cli import _load_local_environment
from equity_analysis.provider_validation.execution_safety import (
    repository_root_env_path,
)

LONG_HORIZON_V11_READINESS_VERSION = (
    "LONG-HORIZON-v1.1-HISTORICAL-READINESS-v1.0.0"
)
LONG_HORIZON_V11_MODEL_VERSION = "LONG-HORIZON-RESEARCH-v1.1.0"
UNIVERSE_PATH = (
    "analysis-python/resources/universes/"
    "market-intelligence-closed-test-us-v1.json"
)
PRICE_MANIFEST_PATH = (
    "docs/generated/"
    "historical-yahoo-price-cache-20260729T-HISTORICAL-V1-R2-manifest.json"
)
PRICE_STORAGE_PATH = (
    "storage/historical-validation/yahoo-daily-price-cache-v1"
)
FREEZE_PATH = "docs/generated/long-horizon-v1-1-model-freeze.json"
OBSERVED_V1_PATH = (
    "docs/generated/"
    "long-horizon-historical-stratified-validation-v1-4-2026-07-29.json"
)
RUNNER_PATH = (
    "analysis-python/src/equity_analysis/historical_validation/"
    "long_horizon_v11_readiness.py"
)

V11_HISTORICAL_FIELDS = (
    "return_on_invested_capital",
    "operating_margin",
    "free_cash_flow_margin",
    "earnings_stability",
    "cash_flow_stability",
    "net_debt_to_ebitda",
    "interest_coverage",
    "current_ratio",
    "diluted_share_growth",
    "incremental_return_on_invested_capital",
    "reinvestment_efficiency",
    "shareholder_yield",
    "acquisition_discipline",
    "free_cash_flow_yield",
    "earnings_yield",
    "enterprise_value_to_ebitda",
    "own_history_valuation_attractiveness",
    "conservative_fundamental_growth",
    "annualized_valuation_normalization",
    "cyclicality_risk",
    "concentration_risk",
    "event_risk",
    "peer_quality_percentile",
    "peer_valuation_attractiveness_percentile",
    "evidence_coverage_ratio",
    "point_in_time_verified_ratio",
    "revision_lineage_ratio",
    "semantic_evidence_ratio",
)


@dataclass(frozen=True)
class DatabaseSecurityInventory:
    public_security_id: str
    fundamental_fact_count: int
    distinct_metric_count: int
    earliest_fundamental_period: str | None
    latest_fundamental_period: str | None
    membership_snapshot_count: int
    earliest_membership_as_of: str | None
    latest_membership_as_of: str | None
    classification_observation_count: int


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _verify_artifact_content_hash(payload: Mapping[str, Any], label: str) -> str:
    expected = payload.get("artifactContentHash")
    if not isinstance(expected, str):
        raise ValueError(f"{label} has no artifactContentHash")
    content = dict(payload)
    del content["artifactContentHash"]
    if canonical_hash(content) != expected:
        raise ValueError(f"{label} artifactContentHash mismatch")
    return expected


def _roles(universe: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    roles = universe.get("roles")
    if not isinstance(roles, dict):
        raise ValueError("Universe roles must be an object")
    for role, symbols in roles.items():
        if not isinstance(symbols, list):
            raise ValueError(f"Universe role must be a list: {role}")
        for raw_symbol in symbols:
            symbol = str(raw_symbol).upper()
            if symbol in result:
                raise ValueError(f"Duplicate universe symbol: {symbol}")
            result[symbol] = str(role)
    return result


def _verify_prices(
    repo_root: Path,
    manifest: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    if manifest.get("status") != "COMPLETE":
        raise ValueError("Historical Yahoo manifest is not complete")
    if manifest.get("normalizedAdjustmentMode") == "RAW":
        raise ValueError("Historical manifest unexpectedly declares raw prices")
    storage_root = repo_root / PRICE_STORAGE_PATH
    verified: dict[str, dict[str, Any]] = {}
    records = manifest.get("records")
    if not isinstance(records, list):
        raise ValueError("Historical Yahoo manifest records must be a list")
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Historical Yahoo record must be an object")
        symbol = str(record["symbol"]).upper()
        path = storage_root / str(record["payloadStorageReference"])
        if not path.is_file():
            raise FileNotFoundError(f"Missing historical price payload: {symbol}")
        if file_sha256(path) != record["payloadFileSha256"]:
            raise ValueError(f"Historical price file hash mismatch: {symbol}")
        payload = _load_json(path)
        content_hash = payload.get("contentHash")
        if content_hash != record["payloadContentHash"]:
            raise ValueError(f"Historical price content hash mismatch: {symbol}")
        content = dict(payload)
        del content["contentHash"]
        if canonical_hash(content) != content_hash:
            raise ValueError(f"Historical price canonical hash mismatch: {symbol}")
        if symbol in verified:
            raise ValueError(f"Duplicate historical price symbol: {symbol}")
        verified[symbol] = record
    return verified


def load_database_inventory(
    database_url: str,
    symbols: tuple[str, ...],
    universe_version: str,
) -> dict[str, DatabaseSecurityInventory]:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT
                security.symbol,
                security.public_id::text,
                COALESCE(facts.fact_count, 0),
                COALESCE(facts.metric_count, 0),
                facts.earliest_period,
                facts.latest_period,
                COALESCE(membership.snapshot_count, 0),
                membership.earliest_as_of,
                membership.latest_as_of,
                COALESCE(classification.observation_count, 0)
            FROM analytics.security security
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*) AS fact_count,
                    COUNT(DISTINCT fact.metric_code) AS metric_count,
                    MIN(fact.period_end) AS earliest_period,
                    MAX(fact.period_end) AS latest_period
                FROM analytics.fundamental_fact fact
                WHERE fact.security_id = security.id
            ) facts ON TRUE
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(DISTINCT member.snapshot_id) AS snapshot_count,
                    MIN(snapshot.as_of_time) AS earliest_as_of,
                    MAX(snapshot.as_of_time) AS latest_as_of
                FROM analytics.snapshot_universe_member member
                JOIN analytics.data_snapshot snapshot
                  ON snapshot.id = member.snapshot_id
                WHERE member.security_id = security.id
                  AND member.universe_version = %s
                  AND snapshot.status = 'READY'
            ) membership ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS observation_count
                FROM analytics.company_profile_observation profile
                WHERE profile.security_id = security.id
                  AND profile.taxonomy_code IS NOT NULL
                  AND profile.sector_code IS NOT NULL
            ) classification ON TRUE
            WHERE security.symbol = ANY(%s)
            ORDER BY security.symbol
            """,
            (universe_version, list(symbols)),
        ).fetchall()

    result: dict[str, DatabaseSecurityInventory] = {}
    for row in rows:
        symbol = str(row[0]).upper()
        result[symbol] = DatabaseSecurityInventory(
            public_security_id=str(row[1]),
            fundamental_fact_count=int(row[2]),
            distinct_metric_count=int(row[3]),
            earliest_fundamental_period=(
                row[4].isoformat() if row[4] is not None else None
            ),
            latest_fundamental_period=(
                row[5].isoformat() if row[5] is not None else None
            ),
            membership_snapshot_count=int(row[6]),
            earliest_membership_as_of=(
                row[7].isoformat() if row[7] is not None else None
            ),
            latest_membership_as_of=(
                row[8].isoformat() if row[8] is not None else None
            ),
            classification_observation_count=int(row[9]),
        )
    return result


def _database_evidence(
    inventory: DatabaseSecurityInventory | None,
) -> dict[str, Any]:
    if inventory is None:
        return {
            "stablePublicSecurityId": None,
            "fundamentalFactCount": 0,
            "distinctMetricCount": 0,
            "fundamentalPeriodRange": None,
            "readyMembershipSnapshotCount": 0,
            "membershipAsOfRange": None,
            "classificationObservationCount": 0,
        }
    return {
        "stablePublicSecurityId": inventory.public_security_id,
        "fundamentalFactCount": inventory.fundamental_fact_count,
        "distinctMetricCount": inventory.distinct_metric_count,
        "fundamentalPeriodRange": {
            "earliest": inventory.earliest_fundamental_period,
            "latest": inventory.latest_fundamental_period,
        },
        "readyMembershipSnapshotCount": inventory.membership_snapshot_count,
        "membershipAsOfRange": {
            "earliest": inventory.earliest_membership_as_of,
            "latest": inventory.latest_membership_as_of,
        },
        "classificationObservationCount": (
            inventory.classification_observation_count
        ),
    }


def _candidate_record(
    *,
    symbol: str,
    role: str,
    price: Mapping[str, Any] | None,
    inventory: DatabaseSecurityInventory | None,
) -> dict[str, Any]:
    price_available = price is not None and int(price["barCount"]) >= 253
    database = _database_evidence(inventory)
    missing_fields = list(V11_HISTORICAL_FIELDS)
    gaps = [
        "NO_HASH_VERIFIED_V11_HISTORICAL_DECISION_INPUTS",
        "PIT_AVAILABILITY_NOT_PROVEN_FOR_ALL_V11_INPUTS",
        "HISTORICAL_UNIVERSE_MEMBERSHIP_NOT_AVAILABLE_AT_DECISION_DATES",
        "HISTORICAL_SECTOR_AND_PEER_COHORT_NOT_AVAILABLE_AT_DECISION_DATES",
        "FORMAL_BENCHMARK_SET_INCOMPLETE",
    ]
    if database["stablePublicSecurityId"] is None:
        gaps.insert(0, "STABLE_PUBLIC_SECURITY_ID_MISSING")
    if not price_available:
        gaps.append("HASH_VERIFIED_252_SESSION_OUTCOME_SERIES_MISSING")
    return {
        "symbol": symbol,
        "role": role,
        "publicSecurityId": database["stablePublicSecurityId"],
        "terminalState": "MISSING",
        "readinessStatus": ValidationTerminalStatus.BLOCKED_BY_DATA.value,
        "v11HistoricalDecisionReady": False,
        "v11ScoreComputed": False,
        "missingV11Fields": missing_fields,
        "gapCodes": gaps,
        "priceOutcomeEvidence": {
            "status": "AVAILABLE" if price_available else "MISSING",
            "horizonSessions": 252,
            "barCount": int(price["barCount"]) if price else 0,
            "firstTradingDate": price["firstTradingDate"] if price else None,
            "lastTradingDate": price["lastTradingDate"] if price else None,
            "payloadContentHash": price["payloadContentHash"] if price else None,
            "priceActionEvidence": (
                "EX_POST_TOTAL_RETURN_ADJUSTED" if price_available else "UNPROVEN"
            ),
            "claimBoundary": (
                "Outcome prices are diagnostic evidence only and cannot repair "
                "missing decision-time inputs."
            ),
        },
        "databaseEvidenceInventory": database,
    }


def build_readiness_artifact(
    *,
    repo_root: Path,
    database_inventory: Mapping[str, DatabaseSecurityInventory],
    diagnostic_at: datetime,
) -> dict[str, Any]:
    if diagnostic_at.tzinfo is None or diagnostic_at.utcoffset() is None:
        raise ValueError("diagnostic_at must be timezone-aware")

    freeze_path = repo_root / FREEZE_PATH
    freeze = _load_json(freeze_path)
    verify_model_freeze_artifact(repo_root, freeze)
    if freeze.get("modelVersion") != LONG_HORIZON_V11_MODEL_VERSION:
        raise ValueError("Long Horizon v1.1 freeze model version mismatch")

    universe_path = repo_root / UNIVERSE_PATH
    universe = _load_json(universe_path)
    roles = _roles(universe)
    price_manifest_path = repo_root / PRICE_MANIFEST_PATH
    price_manifest = _load_json(price_manifest_path)
    price_manifest_hash = _verify_artifact_content_hash(
        price_manifest,
        "Historical Yahoo manifest",
    )
    if file_sha256(universe_path) != price_manifest["universeFileSha256"]:
        raise ValueError("Universe file hash does not match Yahoo manifest")
    prices = _verify_prices(repo_root, price_manifest)

    records: list[dict[str, Any]] = []
    excluded_reasons = universe.get("excludedReasons", {})
    for symbol, role in sorted(roles.items()):
        if role in {"PRIMARY", "RESERVE"}:
            records.append(
                _candidate_record(
                    symbol=symbol,
                    role=role,
                    price=prices.get(symbol),
                    inventory=database_inventory.get(symbol),
                )
            )
        elif role == "REFERENCE_ONLY":
            database = _database_evidence(database_inventory.get(symbol))
            price = prices.get(symbol)
            records.append(
                {
                    "symbol": symbol,
                    "role": role,
                    "publicSecurityId": database["stablePublicSecurityId"],
                    "terminalState": "NOT_APPLICABLE",
                    "readinessStatus": "REFERENCE_ONLY",
                    "v11HistoricalDecisionReady": False,
                    "v11ScoreComputed": False,
                    "missingV11Fields": [],
                    "gapCodes": [],
                    "priceOutcomeEvidence": {
                        "status": "AVAILABLE" if price else "MISSING",
                        "horizonSessions": 252,
                        "barCount": int(price["barCount"]) if price else 0,
                        "payloadContentHash": (
                            price["payloadContentHash"] if price else None
                        ),
                    },
                    "databaseEvidenceInventory": database,
                }
            )
        else:
            database = _database_evidence(database_inventory.get(symbol))
            records.append(
                {
                    "symbol": symbol,
                    "role": role,
                    "publicSecurityId": database["stablePublicSecurityId"],
                    "terminalState": "EXCLUDED",
                    "readinessStatus": "EXCLUDED_BY_FROZEN_UNIVERSE",
                    "v11HistoricalDecisionReady": False,
                    "v11ScoreComputed": False,
                    "missingV11Fields": [],
                    "gapCodes": [str(excluded_reasons.get(symbol, "EXCLUDED"))],
                    "priceOutcomeEvidence": {
                        "status": "NOT_EVALUATED",
                        "horizonSessions": 252,
                    },
                    "databaseEvidenceInventory": database,
                }
            )

    candidate_records = [
        record for record in records if record["role"] in {"PRIMARY", "RESERVE"}
    ]
    field_gap_counts = {
        field: sum(
            field in record["missingV11Fields"] for record in candidate_records
        )
        for field in V11_HISTORICAL_FIELDS
    }
    terminal_counts = {
        state: sum(record["terminalState"] == state for record in records)
        for state in ("MISSING", "NOT_APPLICABLE", "EXCLUDED")
    }
    database_lineage = [
        {
            "symbol": symbol,
            **_database_evidence(database_inventory.get(symbol)),
        }
        for symbol in sorted(roles)
    ]
    observed_v1_path = repo_root / OBSERVED_V1_PATH
    artifact: dict[str, Any] = {
        "artifactType": "LONG_HORIZON_V11_HISTORICAL_READINESS",
        "schemaVersion": LONG_HORIZON_V11_READINESS_VERSION,
        "modelVersion": LONG_HORIZON_V11_MODEL_VERSION,
        "diagnosticAt": diagnostic_at.astimezone(UTC).isoformat(),
        "terminalStatus": ValidationTerminalStatus.BLOCKED_BY_DATA.value,
        "freeze": {
            "path": FREEZE_PATH,
            "fileSha256": file_sha256(freeze_path),
            "artifactContentHash": freeze["artifactContentHash"],
            "freezeHash": freeze["freezeHash"],
        },
        "sourceEvidence": {
            "universe": {
                "path": UNIVERSE_PATH,
                "fileSha256": file_sha256(universe_path),
                "version": universe["universeVersion"],
                "securityCount": len(roles),
            },
            "historicalPrices": {
                "path": PRICE_MANIFEST_PATH,
                "fileSha256": file_sha256(price_manifest_path),
                "artifactContentHash": price_manifest_hash,
                "verifiedPayloadCount": len(prices),
                "adjustmentMode": "TOTAL_RETURN_ADJUSTED",
            },
            "databaseInventory": {
                "securityCount": len(database_inventory),
                "lineageHash": canonical_hash(database_lineage),
                "numericValuesIncluded": False,
            },
            "runner": {
                "path": RUNNER_PATH,
                "fileSha256": file_sha256(repo_root / RUNNER_PATH),
            },
        },
        "observedHistoricalEvidence": {
            "path": OBSERVED_V1_PATH,
            "fileSha256": file_sha256(observed_v1_path),
            "modelVersion": "LONG-HORIZON-RESEARCH-v1.0.0",
            "evaluationRole": EvaluationRole.DEVELOPMENT_OBSERVED.value,
            "untouchedHoldout": False,
        },
        "requirements": {
            "requiredV11HistoricalFields": list(V11_HISTORICAL_FIELDS),
            "pointInTimeAvailabilityRequired": True,
            "historicalMembershipRequired": True,
            "historicalSectorAndCohortRequired": True,
            "minimumPeerCohort": 20,
            "requiredFormalBenchmarks": [
                "SPY",
                "SECTOR",
                "EQUAL_WEIGHT",
                "PURE_MOMENTUM",
                "PURE_VALUE",
                "PURE_QUALITY",
            ],
            "outcomeHorizonSessions": 252,
        },
        "benchmarkReadiness": {
            "SPY": "AVAILABLE_DIAGNOSTIC_ONLY",
            "SECTOR": "MISSING",
            "EQUAL_WEIGHT": "BLOCKED_HISTORICAL_MEMBERSHIP",
            "PURE_MOMENTUM": "BLOCKED_HISTORICAL_MEMBERSHIP",
            "PURE_VALUE": "BLOCKED_V11_PIT_INPUTS",
            "PURE_QUALITY": "BLOCKED_V11_PIT_INPUTS",
            "formalSetReady": False,
        },
        "summary": {
            "frozenPopulationCount": len(records),
            "modelCandidateCount": len(candidate_records),
            "v11HistoricalDecisionReadyCount": 0,
            "v11ScoreCount": 0,
            "terminalCounts": terminal_counts,
            "hashVerified252SessionOutcomeSeriesCount": sum(
                record["priceOutcomeEvidence"].get("status") == "AVAILABLE"
                for record in candidate_records
            ),
            "fieldGapCounts": field_gap_counts,
        },
        "records": records,
        "claimBoundary": {
            "historicalScoringExecuted": False,
            "proxyFormulaUsed": False,
            "v10ScoreReused": False,
            "networkRequestsExecuted": False,
            "forwardValidationExecuted": False,
            "databaseWritesExecuted": False,
            "databaseMigrationExecuted": False,
            "statement": (
                "The cached outcome series cannot authorize a Long Horizon "
                "v1.1 historical decision when decision-time v1.1 inputs, "
                "membership, cohorts, and benchmarks are incomplete."
            ),
        },
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    return artifact


def verify_readiness_artifact(
    artifact: Mapping[str, Any],
    repo_root: Path | None = None,
) -> None:
    expected = artifact.get("artifactContentHash")
    if not isinstance(expected, str):
        raise ValueError("Readiness artifact has no artifactContentHash")
    content = dict(artifact)
    del content["artifactContentHash"]
    if canonical_hash(content) != expected:
        raise ValueError("Readiness artifact content hash mismatch")
    records = artifact.get("records")
    if not isinstance(records, list) or len(records) != 66:
        raise ValueError("Readiness artifact must cover the complete 66-security universe")
    symbols = [record["symbol"] for record in records]
    if len(set(symbols)) != len(symbols):
        raise ValueError("Readiness artifact contains duplicate securities")
    if any(record["v11ScoreComputed"] for record in records):
        raise ValueError("Readiness artifact cannot contain computed v1.1 scores")
    if artifact["summary"]["v11HistoricalDecisionReadyCount"] != 0:
        raise ValueError("Readiness artifact unexpectedly claims ready decisions")
    if repo_root is not None:
        source = artifact["sourceEvidence"]
        freeze_path = repo_root / artifact["freeze"]["path"]
        if file_sha256(freeze_path) != artifact["freeze"]["fileSha256"]:
            raise ValueError("Bound freeze file hash mismatch")
        verify_model_freeze_artifact(repo_root, _load_json(freeze_path))
        universe_path = repo_root / source["universe"]["path"]
        if file_sha256(universe_path) != source["universe"]["fileSha256"]:
            raise ValueError("Bound universe file hash mismatch")
        price_path = repo_root / source["historicalPrices"]["path"]
        if file_sha256(price_path) != source["historicalPrices"]["fileSha256"]:
            raise ValueError("Bound historical-price manifest hash mismatch")
        price_manifest = _load_json(price_path)
        _verify_artifact_content_hash(price_manifest, "Historical Yahoo manifest")
        _verify_prices(repo_root, price_manifest)
        runner_path = repo_root / source["runner"]["path"]
        if file_sha256(runner_path) != source["runner"]["fileSha256"]:
            raise ValueError("Readiness runner source hash mismatch")
        observed_path = repo_root / artifact["observedHistoricalEvidence"]["path"]
        if (
            file_sha256(observed_path)
            != artifact["observedHistoricalEvidence"]["fileSha256"]
        ):
            raise ValueError("Observed v1.0 artifact file hash mismatch")


def _database_url() -> str:
    environment = _load_local_environment(repository_root_env_path())
    explicit = os.getenv("ANALYTICS_DATABASE_URL") or environment.get(
        "ANALYTICS_DATABASE_URL",
        "",
    )
    if explicit:
        return explicit
    required = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_PORT", "POSTGRES_DB")
    if any(not environment.get(key) for key in required):
        raise SystemExit("Local PostgreSQL configuration is required")
    return "postgresql://{}:{}@localhost:{}/{}".format(
        environment["POSTGRES_USER"],
        environment["POSTGRES_PASSWORD"],
        environment["POSTGRES_PORT"],
        environment["POSTGRES_DB"],
    )


def _write_immutable(path: Path, payload: Mapping[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(f"Refusing to overwrite readiness artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit Long Horizon v1.1 historical validation readiness."
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--diagnostic-at", required=True)
    arguments = parser.parse_args()

    repo_root = arguments.repo_root.resolve()
    universe = _load_json(repo_root / UNIVERSE_PATH)
    symbols = tuple(sorted(_roles(universe)))
    inventory = load_database_inventory(
        _database_url(),
        symbols,
        str(universe["universeVersion"]),
    )
    artifact = build_readiness_artifact(
        repo_root=repo_root,
        database_inventory=inventory,
        diagnostic_at=datetime.fromisoformat(arguments.diagnostic_at),
    )
    verify_readiness_artifact(artifact, repo_root)
    _write_immutable(arguments.output, artifact)
    print(
        json.dumps(
            {
                "output": str(arguments.output),
                "artifactContentHash": artifact["artifactContentHash"],
                "terminalStatus": artifact["terminalStatus"],
                "ready": artifact["summary"]["v11HistoricalDecisionReadyCount"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
