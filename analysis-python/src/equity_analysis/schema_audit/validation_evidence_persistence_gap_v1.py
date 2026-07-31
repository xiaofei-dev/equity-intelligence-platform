from __future__ import annotations

import argparse
import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from equity_analysis.daily_refresh.evidence_validation_v1 import canonical_content_hash

AUDIT_VERSION = "VALIDATION-EVIDENCE-PERSISTENCE-GAP-AUDIT-v1.0.0"
PRICE_PREFLIGHT_PATH = (
    "docs/generated/price-promotion-preflight-20260729-beaa9952.json"
)
BENCHMARK_READINESS_PATH = (
    "docs/generated/forward-benchmark-db-readiness-v2-1-beaa9952.json"
)
MIGRATION_PATHS = (
    "database/migrations/V14__create_market_intelligence_reference_data.sql",
    "database/migrations/V15__create_market_intelligence_observations_and_screening.sql",
    "database/migrations/V16__create_market_intelligence_refresh_operations.sql",
    "database/migrations/V17__persist_market_intelligence_screening_contract.sql",
)
EXPECTED_SNAPSHOT_ID = "beaa9952-9852-4088-9dc3-92047824414b"


class GapDisposition(StrEnum):
    REUSE_V14_V17 = "REUSE_V14_V17"
    CODE_ONLY = "CODE_ONLY"
    REQUIRES_APPEND_ONLY_MIGRATION = "REQUIRES_APPEND_ONLY_MIGRATION"


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _require_tokens(path: Path, tokens: tuple[str, ...]) -> None:
    content = path.read_text(encoding="utf-8")
    missing = [token for token in tokens if token not in content]
    if missing:
        raise ValueError(f"{path.name} no longer provides expected schema tokens: {missing}")


def _schema_evidence(repository_root: Path) -> tuple[dict[str, Any], ...]:
    paths = {
        path.name: path
        for relative in MIGRATION_PATHS
        for path in (repository_root / relative,)
    }
    _require_tokens(
        paths["V14__create_market_intelligence_reference_data.sql"],
        (
            "CREATE TABLE analytics.company_profile_observation",
            "source_record_id UUID NOT NULL REFERENCES analytics.source_record",
            "CREATE TABLE analytics.dataset_release",
        ),
    )
    _require_tokens(
        paths["V15__create_market_intelligence_observations_and_screening.sql"],
        (
            "CREATE TABLE analytics.metric_definition",
            "CREATE TABLE analytics.metric_observation",
            "available_at TIMESTAMPTZ NOT NULL",
            "ingested_at TIMESTAMPTZ NOT NULL",
        ),
    )
    _require_tokens(
        paths["V16__create_market_intelligence_refresh_operations.sql"],
        (
            "CREATE TABLE analytics.refresh_checkpoint",
            "CREATE TABLE analytics.analytics_audit_event",
            "event_hash VARCHAR(128) NOT NULL",
            "detail JSONB NOT NULL",
        ),
    )
    _require_tokens(
        paths["V17__persist_market_intelligence_screening_contract.sql"],
        (
            "CREATE TABLE analytics.security_profile_snapshot",
            "input_payload_hash VARCHAR(128) NOT NULL",
            "CREATE TABLE analytics.security_profile_classification_lineage",
            "CREATE TABLE analytics.security_profile_fact_lineage",
        ),
    )
    return tuple(
        {
            "migration": path.name.split("__", maxsplit=1)[0],
            "path": path.relative_to(repository_root).as_posix(),
            "fileSha256": _file_sha256(path),
        }
        for path in paths.values()
    )


def _requirements() -> tuple[dict[str, Any], ...]:
    return (
        {
            "requirement": "COMPLETED_SESSION_CALENDAR_EVIDENCE",
            "disposition": GapDisposition.CODE_ONLY,
            "currentState": "MISSING_RUNTIME_EVIDENCE",
            "existingStructures": (
                "analytics.data_provider",
                "analytics.ingestion_batch",
                "analytics.source_record",
                "analytics.analytics_audit_event",
            ),
            "losslessExpression": (
                "Persist one source_record per hash-verified NYSE/Nasdaq official "
                "calendar body using source_uri, storage_reference, content_hash, "
                "available_at and ingested_at. Seal a versioned audit event that "
                "binds both source IDs/hashes, target session, each authority's "
                "session state, agreement state, reviewer, reviewedAt and evidence hash."
            ),
            "currentBlocker": (
                "The official bodies have not been captured and reviewed; this is "
                "not a missing relational capability."
            ),
            "migrationRequired": False,
        },
        {
            "requirement": "RAW_TRANSPORT_BODY_HASH_AND_REFERENCE",
            "disposition": GapDisposition.CODE_ONLY,
            "currentState": "MISSING_RUNTIME_EVIDENCE",
            "existingStructures": (
                "analytics.source_record.source_uri",
                "analytics.source_record.storage_reference",
                "analytics.source_record.content_hash",
                "analytics.analytics_audit_event.detail",
            ),
            "losslessExpression": (
                "Create a separate raw-transport source_record whose content_hash "
                "is explicitly the raw body hash and whose storage_reference points "
                "to durable external storage. Bind it to the normalized source_record "
                "and request journal in a versioned immutable audit event. Never "
                "reinterpret an existing normalized content_hash as a raw hash."
            ),
            "currentBlocker": (
                "Current yfinance rows retained normalized source hashes only. "
                "A separately typed code contract and durable body capture are absent."
            ),
            "migrationRequired": False,
        },
        {
            "requirement": "ACTION_TO_ADJUSTED_PRICE_BINDING",
            "disposition": GapDisposition.CODE_ONLY,
            "currentState": "MISSING_RUNTIME_EVIDENCE",
            "existingStructures": (
                "analytics.corporate_action",
                "analytics.daily_price_observation",
                "analytics.refresh_checkpoint",
                "analytics.analytics_audit_event",
            ),
            "losslessExpression": (
                "Seal a versioned reconciliation audit event containing the security, "
                "target session, action checkpoint/source manifest hash, selected "
                "action revision hash, both price-mode revision manifest hashes, "
                "adjustment policy/version, reconciliation state and evidence hash."
            ),
            "currentBlocker": (
                "The dual stored modes and action checkpoints reconcile structurally, "
                "but no action-to-adjustment evidence contract has been executed."
            ),
            "migrationRequired": False,
        },
        {
            "requirement": "PRICE_VALIDATION_AND_PROMOTION_HASHES",
            "disposition": GapDisposition.CODE_ONLY,
            "currentState": "MISSING_RUNTIME_EVIDENCE",
            "existingStructures": (
                "analytics.daily_price_observation",
                "analytics.source_record",
                "analytics.analytics_audit_event",
            ),
            "losslessExpression": (
                "Persist immutable validation and promotion decision audit events "
                "that bind security/date/mode, selected prior row IDs and revisions, "
                "source hashes, decision hash, promotion evidence hash, policy hash, "
                "reviewed cutoff and any new VALIDATED revision. Existing rows remain "
                "unchanged."
            ),
            "currentBlocker": (
                "The policy exists in code but no runtime decisions or row bindings "
                "have been sealed."
            ),
            "migrationRequired": False,
        },
        {
            "requirement": "DECISION_TIME_ADTV",
            "disposition": GapDisposition.REUSE_V14_V17,
            "currentState": "MISSING_OBSERVATIONS",
            "existingStructures": (
                "analytics.metric_definition",
                "analytics.metric_observation",
                "analytics.source_record",
                "analytics.dataset_release",
            ),
            "losslessExpression": (
                "Register a versioned ADTV metric definition and persist one append-only "
                "metric_observation per security/decision session with numeric value, "
                "unit, status, source, effective/available/ingested times and revision."
            ),
            "currentBlocker": (
                "The READY snapshot has no qualifying decision-session ADTV observations."
            ),
            "migrationRequired": False,
        },
        {
            "requirement": "OBJECTIVE_SCORE_LINEAGE_AND_TIMING",
            "disposition": GapDisposition.REUSE_V14_V17,
            "currentState": "MISSING_SCORE_FACT_BINDING",
            "existingStructures": (
                "analytics.security_profile_snapshot",
                "analytics.metric_definition",
                "analytics.metric_observation",
                "analytics.security_profile_fact",
                "analytics.security_profile_fact_lineage",
                "analytics.source_record",
            ),
            "losslessExpression": (
                "Persist versioned Objective quality and valuation scores as metric "
                "observations, link them to the exact profile as facts, and retain "
                "ordered input source lineage. metric_observation carries "
                "effective/available/ingested times and revision; the profile already "
                "carries rating version and input_payload_hash."
            ),
            "currentBlocker": (
                "V17 score columns were populated without the existing score-fact and "
                "lineage structures required by Forward v2.1."
            ),
            "migrationRequired": False,
        },
        {
            "requirement": "REAL_SECTOR_LINEAGE",
            "disposition": GapDisposition.REUSE_V14_V17,
            "currentState": "DATA_QUALITY_BLOCKED",
            "existingStructures": (
                "analytics.classification_node",
                "analytics.company_profile_observation",
                "analytics.security_profile_snapshot.classification_source_record_id",
                "analytics.security_profile_classification_lineage",
                "analytics.source_record",
            ),
            "losslessExpression": (
                "Use source-backed V14 company profile classification and copy the exact "
                "taxonomy/node/source lineage into the immutable V17 profile lineage. "
                "Do not accept placeholder sector labels."
            ),
            "currentBlocker": (
                "The current snapshot contains placeholder sector data; the schema "
                "already supports real versioned classification lineage."
            ),
            "migrationRequired": False,
        },
    )


def build_validation_evidence_persistence_gap_audit(
    repository_root: Path,
) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    price_path = repository_root / PRICE_PREFLIGHT_PATH
    benchmark_path = repository_root / BENCHMARK_READINESS_PATH
    price = _json(price_path)
    benchmark = _json(benchmark_path)
    if price.get("state") != "BLOCKED" or benchmark.get("status") != "BLOCKED":
        raise ValueError("Both authoritative diagnostics must remain BLOCKED")
    if (
        price.get("snapshot", {}).get("id") != EXPECTED_SNAPSHOT_ID
        or benchmark.get("dataSnapshotId") != EXPECTED_SNAPSHOT_ID
    ):
        raise ValueError("Diagnostics do not bind the same frozen READY snapshot")

    requirements = _requirements()
    migration_requirements = tuple(
        item["requirement"]
        for item in requirements
        if item["disposition"] == GapDisposition.REQUIRES_APPEND_ONLY_MIGRATION
    )
    payload = {
        "auditVersion": AUDIT_VERSION,
        "state": "COMPLETE",
        "auditMode": "OFFLINE_READ_ONLY",
        "dataSnapshotId": EXPECTED_SNAPSHOT_ID,
        "inputs": (
            {
                "kind": "PRICE_PROMOTION_PREFLIGHT",
                "path": PRICE_PREFLIGHT_PATH,
                "fileSha256": _file_sha256(price_path),
                "artifactContentHash": price["artifactContentHash"],
                "state": price["state"],
            },
            {
                "kind": "FORWARD_BENCHMARK_DB_READINESS",
                "path": BENCHMARK_READINESS_PATH,
                "fileSha256": _file_sha256(benchmark_path),
                "artifactContentHash": benchmark["artifactContentHash"],
                "diagnosticContentHash": benchmark["diagnosticContentHash"],
                "state": benchmark["status"],
            },
        ),
        "schemaEvidence": _schema_evidence(repository_root),
        "requirements": requirements,
        "summary": {
            "reuseV14V17Count": sum(
                item["disposition"] == GapDisposition.REUSE_V14_V17
                for item in requirements
            ),
            "codeOnlyCount": sum(
                item["disposition"] == GapDisposition.CODE_ONLY
                for item in requirements
            ),
            "appendOnlyMigrationCount": len(migration_requirements),
            "appendOnlyMigrationRequirements": migration_requirements,
            "v18Required": bool(migration_requirements),
            "conclusion": "V18_NOT_REQUIRED_FOR_ACCEPTED_V1_EVIDENCE_CONTRACTS",
        },
        "implementationBoundary": {
            "databaseOwnership": "analytics.* remains Python Analytics owned",
            "appSchemaChangeRequired": False,
            "analyticsSchemaChangeRequired": False,
            "migrationCreated": False,
            "databaseWrites": 0,
            "networkRequests": 0,
            "scoringRuns": 0,
        },
        "verificationPlan": {
            "existingMigrationTests": (
                "PostgreSQL 17 clean V1-to-V17",
                "V16-to-V17 upgrade",
                "V17 current schema acceptance",
            ),
            "codeOnlyPersistenceTests": (
                "calendar source/body hash and dual-authority binding replay/conflict",
                "raw versus normalized source hash semantic separation",
                "action/adjustment reconciliation replay/conflict",
                "price validation and promotion row-binding replay/conflict",
                "ADTV PIT selection at decision cutoff",
                "Objective score fact/lineage/timing reconstruction",
                "placeholder-sector rejection and real lineage reconstruction",
            ),
            "futureMigrationTests": (),
        },
    }
    return {
        **payload,
        "artifactContentHash": canonical_content_hash(payload),
    }


def write_audit(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the offline V18 necessity audit.",
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = build_validation_evidence_persistence_gap_audit(
        arguments.repository_root,
    )
    write_audit(arguments.output, result)
    print(result["artifactContentHash"])
    print(result["summary"]["conclusion"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
