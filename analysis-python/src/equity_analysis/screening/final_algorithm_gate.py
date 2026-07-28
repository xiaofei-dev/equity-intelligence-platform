from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import canonical_hash
from equity_analysis.screening.config import QC_VERSION, QC_WEIGHTS, UQ_VERSION, UQ_WEIGHTS
from equity_analysis.screening.normalization import (
    GENERAL_MINIMUM,
    SECTOR_MINIMUM,
    SECTOR_SIZE_MINIMUM,
)

FINAL_GATE_VERSION = "objective-rating-final-algorithm-gate-v1.0.0"
INPUT_CONTRACT_VERSION = "provider-neutral-scoring-input-v2.0.0"
REQUIRED_RECORD_KEYS = frozenset(
    {
        "symbol",
        "dataset",
        "normalizedField",
        "value",
        "unit",
        "currency",
        "periodType",
        "fiscalPeriodEnd",
        "effectiveAt",
        "availableAt",
        "ingestedAt",
        "sourceReference",
        "providerCode",
        "providerSchemaVersion",
        "parserVersion",
        "normalizationVersion",
        "sourceContentHash",
        "contentHash",
    }
)


def _file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def _load_verified(path: Path, expected_hash: str) -> dict[str, Any]:
    if _file_hash(path) != expected_hash.upper():
        raise ValueError(f"SHA-256 mismatch: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _verify_content_hash(value: dict[str, Any], field: str) -> None:
    expected = value.get(field)
    payload = {key: item for key, item in value.items() if key != field}
    if expected != canonical_hash(payload):
        raise ValueError(f"Canonical content hash mismatch: {field}")


def _validate_payload(path: Path, symbol: str, expected_hash: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if canonical_hash(payload) != expected_hash.upper():
        raise ValueError(f"Canonical payload hash mismatch for {symbol}")
    if payload.get("inputContractVersion") != INPUT_CONTRACT_VERSION:
        raise ValueError(f"Input contract mismatch for {symbol}")
    if payload.get("symbol") != symbol or payload.get("missingNormalizedFields"):
        raise ValueError(f"Formula-ready payload identity or coverage mismatch for {symbol}")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError(f"Formula-ready payload is empty for {symbol}")

    datasets: Counter[str] = Counter()
    parsers: set[str] = set()
    normalizers: set[str] = set()
    future_historical_valuation_count = 0
    for record in records:
        missing = REQUIRED_RECORD_KEYS - record.keys()
        if missing:
            raise ValueError(f"Record contract fields are missing for {symbol}: {sorted(missing)}")
        if record["symbol"] != symbol:
            raise ValueError(f"Record symbol mismatch for {symbol}")
        effective = datetime.fromisoformat(record["effectiveAt"].replace("Z", "+00:00"))
        available = datetime.fromisoformat(record["availableAt"].replace("Z", "+00:00"))
        ingested = datetime.fromisoformat(record["ingestedAt"].replace("Z", "+00:00"))
        if effective > available or available > ingested:
            raise ValueError(f"Invalid PIT ordering for {symbol}")
        if record["dataset"] == "FINANCIAL" and not record.get("accessionNumber"):
            raise ValueError(f"Financial accession is missing for {symbol}")
        if (
            record["dataset"] in {"DAILY_PRICE", "HISTORICAL_MARKET_CAP"}
            and available.date() > effective.date()
        ):
            future_historical_valuation_count += 1
        datasets[record["dataset"]] += 1
        parsers.add(record["parserVersion"])
        normalizers.add(record["normalizationVersion"])
    return {
        "recordCount": len(records),
        "datasets": dict(sorted(datasets.items())),
        "parserVersions": sorted(parsers),
        "normalizationVersions": sorted(normalizers),
        "historicalValuationsUnavailableAtEffectiveTime": future_historical_valuation_count,
        "hasPeriodStart": all(
            "periodStart" in record
            for record in records
            if record["dataset"] == "FINANCIAL"
        ),
        "hasDurationSemantics": all(
            "durationSemantics" in record
            for record in records
            if record["dataset"] == "FINANCIAL"
        ),
    }


def build_final_algorithm_gate(
    aggregate_path: Path,
    billing_path: Path,
    repository_root: Path,
    *,
    expected_aggregate_sha256: str,
    expected_aggregate_content_hash: str,
    expected_billing_sha256: str,
) -> dict[str, Any]:
    aggregate = _load_verified(aggregate_path, expected_aggregate_sha256)
    _load_verified(billing_path, expected_billing_sha256)
    _verify_content_hash(aggregate, "artifactContentHash")
    if aggregate["artifactContentHash"] != expected_aggregate_content_hash.upper():
        raise ValueError("Authoritative aggregate canonical hash mismatch")
    if aggregate.get("statusCounts") != {
        "FORMULA_READY": 223,
        "SECURITY_INSUFFICIENT_DATA": 20,
    }:
        raise ValueError("Unexpected terminal status distribution")

    source_manifest = repository_root / aggregate["sourceManifestPath"]
    terminal_evidence = repository_root / aggregate["terminalEvidencePath"]
    _load_verified(source_manifest, aggregate["sourceManifestSha256"])
    _load_verified(terminal_evidence, aggregate["terminalEvidenceSha256"])
    for component in aggregate["componentReports"]:
        report = _load_verified(repository_root / component["path"], component["sha256"])
        if report.get("artifactContentHash") != component["artifactContentHash"]:
            raise ValueError(f"Component content hash mismatch: {component['runId']}")

    ready_results: list[dict[str, Any]] = []
    insufficient_results: list[dict[str, Any]] = []
    parser_versions: set[str] = set()
    normalization_versions: set[str] = set()
    total_records = 0
    historical_pit_failures = 0
    period_start_complete = True
    duration_semantics_complete = True
    checkpoint_verified = 0

    for security in sorted(aggregate["securities"], key=lambda item: item["symbol"]):
        source_report = repository_root / security["sourceReportPath"]
        _load_verified(source_report, security["sourceReportSha256"])
        if security["status"] != "FORMULA_READY":
            insufficient_results.append(
                {
                    "symbol": security["symbol"],
                    "status": "INSUFFICIENT_DATA",
                    "reasonCodes": security["reasonCodes"],
                }
            )
            continue
        storage_reference = security.get("storageReference")
        if not storage_reference:
            storage_reference = (
                f"storage/provider-validation/scoring-inputs-v2/{security['symbol']}/"
                f"{security['contentHash']}.json"
            )
        details = _validate_payload(
            repository_root / storage_reference,
            security["symbol"],
            security["contentHash"],
        )
        checkpoint_hash = security.get("checkpointSha256")
        if checkpoint_hash:
            matches = tuple(
                (
                    repository_root
                    / "storage/provider-validation/scoring-inputs-v2/checkpoints"
                    / security["sourceRunId"]
                ).glob(f"*-{security['symbol']}.json")
            )
            if len(matches) != 1 or _file_hash(matches[0]) != checkpoint_hash:
                raise ValueError(f"Checkpoint hash mismatch for {security['symbol']}")
            checkpoint_verified += 1
        total_records += details["recordCount"]
        historical_pit_failures += details["historicalValuationsUnavailableAtEffectiveTime"]
        period_start_complete &= details["hasPeriodStart"]
        duration_semantics_complete &= details["hasDurationSemantics"]
        parser_versions.update(details["parserVersions"])
        normalization_versions.update(details["normalizationVersions"])
        ready_results.append(
            {
                "symbol": security["symbol"],
                "inputStatus": "FORMULA_READY",
                "algorithmStatus": "INSUFFICIENT_DATA",
                "qualityCompounder": {
                    "strategyVersion": QC_VERSION,
                    "status": "INSUFFICIENT_DATA",
                    "score": None,
                    "rank": None,
                },
                "undervaluedQuality": {
                    "strategyVersion": UQ_VERSION,
                    "status": "INSUFFICIENT_DATA",
                    "score": None,
                    "rank": None,
                },
                "reasonCodes": [
                    "COMPANY_CLASSIFICATION_SNAPSHOT_MISSING",
                    "FINANCIAL_DURATION_SEMANTICS_MISSING",
                    "HISTORICAL_VALUATION_PIT_UNAVAILABLE",
                ],
                "payloadHash": security["contentHash"],
            }
        )

    payload: dict[str, Any] = {
        "artifactType": "OBJECTIVE_RATING_FINAL_ALGORITHM_GATE",
        "schemaVersion": FINAL_GATE_VERSION,
        "input": {
            "aggregatePath": aggregate_path.name,
            "aggregateSha256": expected_aggregate_sha256.upper(),
            "aggregateContentHash": expected_aggregate_content_hash.upper(),
            "billingPath": billing_path.name,
            "billingSha256": expected_billing_sha256.upper(),
            "inputContractVersion": INPUT_CONTRACT_VERSION,
            "formulaReadyPayloadCount": len(ready_results),
            "insufficientInputCount": len(insufficient_results),
            "controlledRecordCount": total_records,
            "checkpointHashesVerified": checkpoint_verified,
        },
        "snapshot": {
            "status": "NOT_SEALED",
            "asOfTime": None,
            "cutoff": None,
            "universeVersion": None,
            "companyTypeVersion": None,
            "parserVersions": sorted(parser_versions),
            "normalizationVersions": sorted(normalization_versions),
            "reason": "The input contract cannot reproduce Objective Rating v1 PIT factors.",
        },
        "formulaManifest": {
            "qualityCompounderWeights": {
                name: str(weight) for name, weight in QC_WEIGHTS.items()
            },
            "undervaluedQualityWeights": {
                name: str(weight) for name, weight in UQ_WEIGHTS.items()
            },
            "winsorizationPercentiles": ["0.05", "0.95"],
            "cohortMinimums": {
                "sectorSizeCompanyType": SECTOR_SIZE_MINIMUM,
                "sectorCompanyType": SECTOR_MINIMUM,
                "generalCompany": GENERAL_MINIMUM,
            },
            "missingDataRule": "NO_ZERO_NO_NEUTRAL_NO_WEIGHT_REDISTRIBUTION",
        },
        "validation": {
            "aggregateHashChain": "PASS",
            "billingHash": "PASS",
            "sourceReportHashChain": "PASS",
            "payloadCanonicalHashes": "PASS",
            "checkpointHashes": "PASS",
            "recordContractShape": "PASS",
            "periodStartCoverage": "PASS" if period_start_complete else "FAIL",
            "durationSemanticsCoverage": "PASS" if duration_semantics_complete else "FAIL",
            "historicalValuationPitStatus": "FAIL",
            "historicalRecordsUnavailableAtEffectiveTime": historical_pit_failures,
            "classificationSnapshotStatus": "FAIL",
        },
        "result": {
            "algorithmGateStatus": "NOT_ACCEPTED",
            "inputFormulaReadyCount": 223,
            "algorithmEligibleCount": 0,
            "qcEligibleCount": 0,
            "uqEligibleCount": 0,
            "scoredCount": 0,
            "rankedCount": 0,
            "insufficientDataCount": 243,
            "notApplicableCount": 0,
            "determinismStatus": "PASS_FOR_GATE_DECISION",
            "cohortStatus": "NOT_EVALUABLE",
        },
        "securities": ready_results + insufficient_results,
        "licensedValuesIncluded": False,
        "networkRequestsExecuted": False,
        "forwardValidationExecuted": False,
        "aiParticipation": "NONE",
    }
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the final offline Algorithm Gate.")
    parser.add_argument("aggregate", type=Path)
    parser.add_argument("billing", type=Path)
    parser.add_argument("repository_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--aggregate-sha256", required=True)
    parser.add_argument("--aggregate-content-hash", required=True)
    parser.add_argument("--billing-sha256", required=True)
    arguments = parser.parse_args()
    artifact = build_final_algorithm_gate(
        arguments.aggregate,
        arguments.billing,
        arguments.repository_root,
        expected_aggregate_sha256=arguments.aggregate_sha256,
        expected_aggregate_content_hash=arguments.aggregate_content_hash,
        expected_billing_sha256=arguments.billing_sha256,
    )
    arguments.output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
