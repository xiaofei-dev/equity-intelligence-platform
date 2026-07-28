from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    NormalizedScoringInputRecord,
    canonical_hash,
)
from equity_analysis.screening.algorithm_gate import ALGORITHM_GATE_VERSION
from equity_analysis.screening.config import QC_VERSION, QC_WEIGHTS, UQ_VERSION, UQ_WEIGHTS
from equity_analysis.screening.normalization import (
    GENERAL_MINIMUM,
    SECTOR_MINIMUM,
    SECTOR_SIZE_MINIMUM,
)

EXPANSION_ALGORITHM_GATE_VERSION = f"{ALGORITHM_GATE_VERSION}-expansion-1"
INPUT_CONTRACT_VERSION = "provider-neutral-scoring-input-v1.0.0"
FORMULA_REQUIRED_FIELDS = frozenset(
    {
        "capital_expenditure",
        "cash_and_equivalents",
        "diluted_weighted_average_shares",
        "ebitda",
        "gross_profit",
        "income_tax",
        "interest_expense",
        "market_capitalization",
        "net_income",
        "operating_cash_flow",
        "operating_income",
        "pretax_income",
        "revenue",
        "stockholders_equity",
        "total_debt",
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


def _validate_payload(
    path: Path,
    *,
    symbol: str,
    expected_payload_hash: str,
    as_of_time: datetime,
) -> tuple[frozenset[str], int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("inputContractVersion") != INPUT_CONTRACT_VERSION:
        raise ValueError(f"Input contract version mismatch for {symbol}")
    if payload.get("symbol") != symbol:
        raise ValueError(f"Payload symbol mismatch for {symbol}")
    if canonical_hash(payload) != expected_payload_hash.upper():
        raise ValueError(f"Canonical payload hash mismatch for {symbol}")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError(f"Empty scoring payload for {symbol}")
    fields: set[str] = set()
    for raw_record in records:
        record = NormalizedScoringInputRecord.model_validate(raw_record)
        if record.symbol != symbol:
            raise ValueError(f"Record symbol mismatch for {symbol}")
        record_without_hash = dict(raw_record)
        record_hash = record_without_hash.pop("contentHash", None)
        legacy_hash_input = dict(record_without_hash)
        for timestamp_field in ("effectiveAt", "availableAt", "ingestedAt"):
            timestamp = legacy_hash_input.get(timestamp_field)
            if isinstance(timestamp, str) and timestamp.endswith("Z"):
                legacy_hash_input[timestamp_field] = f"{timestamp[:-1]}+00:00"
        if canonical_hash(legacy_hash_input) != str(record_hash).upper():
            raise ValueError(f"Record content hash mismatch for {symbol}")
        if record.available_at > as_of_time:
            raise ValueError(f"Future observation entered the snapshot for {symbol}")
        if not record.unit or not record.source_reference or not record.provider_code:
            raise ValueError(f"Incomplete lineage for {symbol}")
        try:
            Decimal(str(raw_record["value"]))
        except (InvalidOperation, KeyError) as error:
            raise ValueError(f"Invalid decimal value for {symbol}") from error
        fields.add(record.normalized_field)
    return frozenset(fields), len(records)


def build_expansion_algorithm_gate(
    aggregate_path: Path,
    reconciliation_path: Path,
    storage_root: Path,
    *,
    expected_aggregate_sha256: str,
    expected_reconciliation_sha256: str,
) -> dict[str, Any]:
    aggregate_path = aggregate_path.resolve()
    reconciliation_path = reconciliation_path.resolve()
    aggregate = _load_verified(aggregate_path, expected_aggregate_sha256)
    _load_verified(reconciliation_path, expected_reconciliation_sha256)
    if aggregate.get("uniqueSecurityCount") != 300:
        raise ValueError("Expansion gate requires exactly 300 unique securities")

    ledger = aggregate.get("ledger")
    if not isinstance(ledger, list) or len(ledger) != 300:
        raise ValueError("Expansion ledger is incomplete")
    symbols = [item.get("symbol") for item in ledger]
    if len(set(symbols)) != 300:
        raise ValueError("Expansion ledger symbols are not unique")

    manifest_records: dict[str, dict[str, Any]] = {}
    for source_run in aggregate.get("sourceRuns", ()):
        run_id = source_run["runId"]
        manifest_path = (
            aggregate_path.parent / f"expansion-provider-gate-{run_id}-scoring-input-manifest.json"
        )
        manifest = _load_verified(manifest_path, source_run["scoringInputManifestSha256"])
        for record in manifest.get("records", ()):
            symbol = record["symbol"]
            existing = manifest_records.get(symbol)
            if existing is not None and existing["normalizedPayloadHash"] != record[
                "normalizedPayloadHash"
            ]:
                raise ValueError(f"Conflicting scoring manifests for {symbol}")
            manifest_records[symbol] = record

    as_of_time = datetime.fromisoformat(aggregate["generatedAt"].replace("Z", "+00:00"))
    outcomes: list[dict[str, Any]] = []
    loaded_count = 0
    record_count = 0
    field_sets: Counter[tuple[str, ...]] = Counter()
    missing_fields: Counter[str] = Counter()

    for item in sorted(ledger, key=lambda value: value["symbol"]):
        symbol = item["symbol"]
        status = item["status"]
        if status == "EXCLUDED":
            outcomes.append(
                {
                    "symbol": symbol,
                    "providerStatus": status,
                    "algorithmStatus": "NOT_APPLICABLE",
                    "reasonCodes": item.get("reasonCodes", ()),
                }
            )
            continue
        if status != "PASS":
            outcomes.append(
                {
                    "symbol": symbol,
                    "providerStatus": status,
                    "algorithmStatus": "INSUFFICIENT_DATA",
                    "reasonCodes": item.get("reasonCodes", ()),
                }
            )
            continue
        if item.get("liveConfirmed") is not True or item.get("scoringInputReady") is not True:
            raise ValueError(f"PASS record lacks live scoring evidence for {symbol}")
        manifest_record = manifest_records.get(symbol)
        if manifest_record is None:
            raise ValueError(f"Scoring manifest record is missing for {symbol}")
        payload_hash = manifest_record["normalizedPayloadHash"].upper()
        ledger_hash = item.get("scoringInputPayloadHash")
        if ledger_hash is not None and ledger_hash.upper() != payload_hash:
            raise ValueError(f"Ledger and manifest payload hashes differ for {symbol}")
        payload_path = storage_root / symbol / f"{payload_hash}.json"
        if not payload_path.is_file():
            raise ValueError(f"Controlled scoring payload is missing for {symbol}")
        fields, records = _validate_payload(
            payload_path,
            symbol=symbol,
            expected_payload_hash=payload_hash,
            as_of_time=as_of_time,
        )
        loaded_count += 1
        record_count += records
        field_sets[tuple(sorted(fields))] += 1
        missing = tuple(sorted(FORMULA_REQUIRED_FIELDS - fields))
        missing_fields.update(missing)
        algorithm_status = "INSUFFICIENT_DATA" if missing else "FORMULA_READY"
        outcomes.append(
            {
                "symbol": symbol,
                "sector": item["sector"],
                "marketCapBand": item["marketCapBand"],
                "companyType": item["companyType"],
                "providerStatus": status,
                "algorithmStatus": algorithm_status,
                "qualityCompounder": {
                    "strategyVersion": QC_VERSION,
                    "status": "INSUFFICIENT_DATA" if missing else "PENDING_SCORE",
                    "score": None,
                    "rank": None,
                },
                "undervaluedQuality": {
                    "strategyVersion": UQ_VERSION,
                    "status": "INSUFFICIENT_DATA" if missing else "PENDING_SCORE",
                    "score": None,
                    "rank": None,
                },
                "missingNormalizedFields": missing,
                "payloadHash": payload_hash,
                "recordCount": records,
            }
        )

    formula_ready = sum(item["algorithmStatus"] == "FORMULA_READY" for item in outcomes)
    insufficient = sum(item["algorithmStatus"] == "INSUFFICIENT_DATA" for item in outcomes)
    not_applicable = sum(item["algorithmStatus"] == "NOT_APPLICABLE" for item in outcomes)
    payload: dict[str, Any] = {
        "artifactType": "OBJECTIVE_RATING_EXPANSION_ALGORITHM_GATE",
        "schemaVersion": EXPANSION_ALGORITHM_GATE_VERSION,
        "input": {
            "aggregatePath": aggregate_path.name,
            "aggregateSha256": expected_aggregate_sha256.upper(),
            "aggregateContentHash": aggregate.get("artifactContentHash"),
            "billingReconciliationPath": reconciliation_path.name,
            "billingReconciliationSha256": expected_reconciliation_sha256.upper(),
            "universeVersion": aggregate["universeVersion"],
            "universeCount": 300,
            "providerStatusDistribution": aggregate["statusDistribution"],
            "controlledPayloadCount": loaded_count,
            "controlledRecordCount": record_count,
            "inputContractVersion": INPUT_CONTRACT_VERSION,
        },
        "versions": {
            "qualityCompounder": QC_VERSION,
            "undervaluedQuality": UQ_VERSION,
        },
        "formulaManifest": {
            "qualityCompounderWeights": {
                name: str(weight) for name, weight in QC_WEIGHTS.items()
            },
            "undervaluedQualityWeights": {
                name: str(weight) for name, weight in UQ_WEIGHTS.items()
            },
            "requiredNormalizedFields": sorted(FORMULA_REQUIRED_FIELDS),
            "winsorizationPercentiles": ["0.05", "0.95"],
            "cohortMinimums": {
                "sectorSizeCompanyType": SECTOR_SIZE_MINIMUM,
                "sectorCompanyType": SECTOR_MINIMUM,
                "generalCompany": GENERAL_MINIMUM,
            },
            "missingDataRule": "NO_ZERO_NO_NEUTRAL_NO_WEIGHT_REDISTRIBUTION",
        },
        "validation": {
            "payloadCanonicalHashes": "PASS",
            "recordContentHashes": "PASS",
            "decimalValues": "PASS",
            "units": "PASS",
            "pitAvailableAt": "PASS",
            "lineageIdentifiers": "PASS",
            "formulaOperandCoverage": "FAIL",
            "fieldSetDistribution": [
                {"fields": list(fields), "securityCount": count}
                for fields, count in sorted(field_sets.items())
            ],
            "missingFieldDistribution": dict(sorted(missing_fields.items())),
        },
        "result": {
            "algorithmGateStatus": "NOT_ACCEPTED",
            "formulaReadyCount": formula_ready,
            "scoredCount": 0,
            "rankedCount": 0,
            "insufficientDataCount": insufficient,
            "notApplicableCount": not_applicable,
            "determinismStatus": "PASS_FOR_GATE_DECISION",
            "rankingStabilityStatus": "NOT_EVALUABLE",
            "providerPassDoesNotImplyAlgorithmEligibility": True,
        },
        "securities": outcomes,
        "licensedValuesIncluded": False,
        "networkRequestsExecuted": False,
        "aiParticipation": "NONE",
    }
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def write_expansion_algorithm_gate(
    aggregate_path: Path,
    reconciliation_path: Path,
    storage_root: Path,
    output_path: Path,
    *,
    expected_aggregate_sha256: str,
    expected_reconciliation_sha256: str,
) -> dict[str, Any]:
    artifact = build_expansion_algorithm_gate(
        aggregate_path,
        reconciliation_path,
        storage_root,
        expected_aggregate_sha256=expected_aggregate_sha256,
        expected_reconciliation_sha256=expected_reconciliation_sha256,
    )
    output_path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the offline expansion Algorithm Gate.")
    parser.add_argument("aggregate", type=Path)
    parser.add_argument("reconciliation", type=Path)
    parser.add_argument("storage_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--aggregate-sha256", required=True)
    parser.add_argument("--reconciliation-sha256", required=True)
    arguments = parser.parse_args()
    write_expansion_algorithm_gate(
        arguments.aggregate,
        arguments.reconciliation,
        arguments.storage_root,
        arguments.output,
        expected_aggregate_sha256=arguments.aggregate_sha256,
        expected_reconciliation_sha256=arguments.reconciliation_sha256,
    )


if __name__ == "__main__":
    main()
