from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from equity_analysis.screening.config import QC_VERSION, QC_WEIGHTS, UQ_VERSION, UQ_WEIGHTS
from equity_analysis.screening.normalization import (
    GENERAL_MINIMUM,
    SECTOR_MINIMUM,
    SECTOR_SIZE_MINIMUM,
)

ALGORITHM_GATE_VERSION = "objective-rating-algorithm-gate-v1.0.0"
EXPECTED_PROVIDER_REPORT_VERSION = "mature-company-data-gate-v1.0.0"
REQUIRED_EVIDENCE_GAPS = (
    "COMPANY_TYPE_CLASSIFICATION",
    "FACTOR_READY_HISTORICAL_SERIES",
    "PER_OBSERVATION_AVAILABLE_AT",
    "RAW_NUMERIC_VALUES",
    "UNITS_AND_CURRENCY",
)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _content_hash(value: Mapping[str, Any]) -> str:
    return sha256(_canonical_bytes(value)).hexdigest().upper()


def _load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return loaded


def _component_path(directory: Path, run_id: str) -> Path:
    matches = tuple(
        path
        for path in directory.glob(f"mature-company-data-gate-{run_id}.json")
        if not path.name.endswith(("-diagnostics.json", "-final-reconciliation.json"))
    )
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one component report for run {run_id}")
    return matches[0]


def build_algorithm_gate(
    merged_path: Path,
    *,
    expected_merged_sha256: str,
) -> dict[str, Any]:
    merged_path = merged_path.resolve()
    actual_merged_hash = _file_sha256(merged_path)
    if actual_merged_hash != expected_merged_sha256.upper():
        raise ValueError("Merged provider acceptance SHA-256 mismatch")

    merged = _load_json(merged_path)
    if merged.get("aggregateGateStatus") != "PASS":
        raise ValueError("Provider acceptance is not PASS")
    if merged.get("uniquePassCount") != 100:
        raise ValueError("Algorithm gate requires exactly 100 unique provider PASS records")

    pass_records = merged.get("passRecords")
    if not isinstance(pass_records, list) or len(pass_records) != 100:
        raise ValueError("Provider acceptance passRecords are incomplete")
    symbols = [record.get("symbol") for record in pass_records]
    if len(set(symbols)) != 100 or any(not symbol for symbol in symbols):
        raise ValueError("Provider acceptance symbols are not 100 unique non-empty identifiers")
    if any(
        record.get("status") != "PASS" or record.get("liveConfirmed") is not True
        for record in pass_records
    ):
        raise ValueError("Algorithm gate accepts only live-confirmed PASS evidence")

    components: dict[str, tuple[Path, dict[str, Any], str]] = {}
    for run_id in merged.get("componentRunIds", ()):
        path = _component_path(merged_path.parent, run_id)
        report_hash = _file_sha256(path)
        report = _load_json(path)
        if report.get("reportVersion") != EXPECTED_PROVIDER_REPORT_VERSION:
            raise ValueError(f"Provider gate version mismatch for {run_id}")
        components[run_id] = (path, report, report_hash)

    for record in pass_records:
        run_id = record["sourceRunId"]
        if run_id not in components:
            raise ValueError(f"Missing component report for {record['symbol']}")
        if components[run_id][2] != record["sourceReportSha256"].upper():
            raise ValueError(f"Component report SHA-256 mismatch for {record['symbol']}")

    raw_values_available = all(
        report.get("rawProviderValuesIncluded") is True
        for _, report, _ in components.values()
    )
    outcomes = [
        {
            "symbol": record["symbol"],
            "sector": record["sector"],
            "providerGateStatus": "PASS",
            "providerEvidenceType": "LIVE_IMMUTABLE_REPORT",
            "algorithmEligibility": "INSUFFICIENT_DATA",
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
            "missingEvidence": list(REQUIRED_EVIDENCE_GAPS),
            "sourceRunId": record["sourceRunId"],
            "sourceReportSha256": record["sourceReportSha256"].upper(),
        }
        for record in sorted(pass_records, key=lambda item: item["symbol"])
    ]

    payload: dict[str, Any] = {
        "artifactType": "OBJECTIVE_RATING_ALGORITHM_GATE",
        "schemaVersion": ALGORITHM_GATE_VERSION,
        "input": {
            "mergedAcceptancePath": merged_path.name,
            "mergedAcceptanceSha256": actual_merged_hash,
            "mergedAcceptanceContentHash": merged.get("artifactContentHash"),
            "providerGateStatus": merged["aggregateGateStatus"],
            "providerPassCount": merged["uniquePassCount"],
            "componentReports": [
                {
                    "runId": run_id,
                    "path": path.name,
                    "sha256": report_hash,
                    "rawProviderValuesIncluded": report.get("rawProviderValuesIncluded"),
                }
                for run_id, (path, report, report_hash) in sorted(components.items())
            ],
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
            "winsorizationPercentiles": ["0.05", "0.95"],
            "cohortMinimums": {
                "sectorSizeCompanyType": SECTOR_SIZE_MINIMUM,
                "sectorCompanyType": SECTOR_MINIMUM,
                "generalCompany": GENERAL_MINIMUM,
            },
            "missingDataRule": "NO_ZERO_NO_NEUTRAL_NO_WEIGHT_REDISTRIBUTION",
            "specializedCompanyRule": "SPECIALIZED_MODEL_REQUIRED",
            "numericType": "DECIMAL",
        },
        "snapshot": {
            "status": "NOT_SEALED",
            "pitStatus": "NOT_VERIFIABLE_FROM_REDISTRIBUTABLE_ARTIFACTS",
            "rawNumericValuesAvailable": raw_values_available,
            "reason": (
                "Hash-verified provider reports intentionally exclude raw provider values. "
                "They do not contain a factor-ready PIT observation snapshot."
            ),
        },
        "result": {
            "algorithmGateStatus": "NOT_ACCEPTED",
            "scoredCount": 0,
            "insufficientDataCount": len(outcomes),
            "notApplicableCount": 0,
            "rankedCount": 0,
            "determinismStatus": "PASS_FOR_GATE_DECISION",
            "statisticalDistributionStatus": "NOT_EVALUABLE",
            "providerPassDoesNotImplyAlgorithmEligibility": True,
        },
        "securities": outcomes,
        "aiParticipation": "NONE",
    }
    return {**payload, "artifactContentHash": _content_hash(payload)}


def write_algorithm_gate(
    merged_path: Path,
    output_path: Path,
    *,
    expected_merged_sha256: str,
) -> dict[str, Any]:
    artifact = build_algorithm_gate(
        merged_path,
        expected_merged_sha256=expected_merged_sha256,
    )
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the offline Objective Rating Algorithm Gate artifact."
    )
    parser.add_argument("merged_acceptance", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    arguments = parser.parse_args()
    write_algorithm_gate(
        arguments.merged_acceptance,
        arguments.output,
        expected_merged_sha256=arguments.expected_sha256,
    )


if __name__ == "__main__":
    main()
