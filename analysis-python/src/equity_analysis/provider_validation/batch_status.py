import argparse
import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

BATCH_STATUS_SCHEMA_VERSION = "formula-ready-batch-status-v1.0.0"
REMAINING_MANIFEST_SCHEMA_VERSION = "formula-ready-remaining-manifest-v1.0.0"
COMBINED_REPORT_V1_1 = "formula-ready-combined-backfill-v1.1.0"
TERMINAL_STATUSES = frozenset(
    {"FORMULA_READY", "SKIPPED_EXISTING_COMPLETE", "SECURITY_INSUFFICIENT_DATA"}
)


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def read_combined_report(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    actual_hash = file_sha256(path)
    if expected_sha256 is not None and actual_hash != expected_sha256.upper():
        raise ValueError("SOURCE_REPORT_SHA256_MISMATCH")
    report = json.loads(path.read_text(encoding="utf-8"))
    version = report.get("reportVersion")
    if version not in {None, COMBINED_REPORT_V1_1}:
        raise ValueError(f"UNSUPPORTED_COMBINED_REPORT_VERSION[{version}]")
    if version is None:
        logical = report.pop("endpointPhysicalAttempts", {})
        report["reportVersion"] = "formula-ready-combined-backfill-v1.0.0"
        report["logicalEndpointEvaluations"] = logical
        report["replayedCompletedEndpoints"] = {}
        report["newPhysicalAttempts"] = None
        report["telemetryCompatibility"] = (
            "LEGACY_COUNTS_ARE_LOGICAL_EVALUATIONS_NOT_VERIFIED_PHYSICAL_ATTEMPTS"
        )
    else:
        report.setdefault("logicalEndpointEvaluations", {})
        report.setdefault("replayedCompletedEndpoints", {})
        report.setdefault("newPhysicalAttempts", {})
        report["telemetryCompatibility"] = "V1_1_SEPARATED"
    report["sourceReportSha256"] = actual_hash
    return report


def build_remaining_manifest(
    source_manifest: dict[str, Any],
    terminal_evidence: dict[str, dict[str, Any]],
    *,
    slice_size: int = 20,
) -> dict[str, Any]:
    if not 1 <= slice_size <= 20:
        raise ValueError("SLICE_SIZE_MUST_BE_BETWEEN_1_AND_20")
    records = source_manifest["records"]
    source_symbols = [item["symbol"] for item in records]
    if len(source_symbols) != len(set(source_symbols)):
        raise ValueError("SOURCE_MANIFEST_DUPLICATE_SYMBOL")
    for symbol, evidence in terminal_evidence.items():
        if symbol not in source_symbols:
            raise ValueError(f"TERMINAL_SYMBOL_NOT_IN_SOURCE[{symbol}]")
        if evidence.get("status") not in TERMINAL_STATUSES:
            raise ValueError(f"NON_TERMINAL_EVIDENCE[{symbol}]")
        if not evidence.get("sourceReportSha256"):
            raise ValueError(f"MISSING_TERMINAL_SOURCE_HASH[{symbol}]")
    remaining = [item for item in records if item["symbol"] not in terminal_evidence]
    slices = [
        {
            "sliceId": f"formula-ready-remaining-{index + 1:03d}",
            "sequence": index + 1,
            "symbols": [item["symbol"] for item in remaining[offset : offset + slice_size]],
            "records": remaining[offset : offset + slice_size],
        }
        for index, offset in enumerate(range(0, len(remaining), slice_size))
    ]
    payload = {
        "artifactType": "FORMULA_READY_REMAINING_MANIFEST",
        "schemaVersion": REMAINING_MANIFEST_SCHEMA_VERSION,
        "sourceManifestContentHash": source_manifest.get("manifestContentHash"),
        "sourceEligibleSymbolCount": len(records),
        "completedTerminalSymbols": [
            {
                "symbol": symbol,
                "status": terminal_evidence[symbol]["status"],
                "sourceRunId": terminal_evidence[symbol].get("sourceRunId"),
                "sourceReportSha256": terminal_evidence[symbol]["sourceReportSha256"],
            }
            for symbol in source_symbols
            if symbol in terminal_evidence
        ],
        "remainingSymbolCount": len(remaining),
        "sliceSize": slice_size,
        "sliceCount": len(slices),
        "slices": slices,
        "selectionApplied": False,
        "replacementApplied": False,
        "networkRequestsExecuted": False,
    }
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def build_batch_aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    symbols = [item["symbol"] for item in results]
    if len(symbols) != len(set(symbols)):
        raise ValueError("DUPLICATE_BATCH_RESULT_SYMBOL")
    statuses = Counter(item["status"] for item in results)
    reasons = Counter(
        reason for item in results for reason in item.get("reasonCodes", [])
    )
    evaluated = len(results)
    dominant = [
        (reason, count)
        for reason, count in reasons.items()
        if evaluated and count * 2 > evaluated
    ]
    dominant.sort(key=lambda item: (-item[1], item[0]))
    system_failure = statuses["SYSTEM_EXECUTION_FAIL"] > 0
    if system_failure:
        stop_signal = "STOP_FOR_SYSTEM_EXECUTION_FAILURE"
    elif dominant:
        stop_signal = "STOP_FOR_SYSTEMATIC_DATA_GAP"
    else:
        stop_signal = "CONTINUE"
    payload = {
        "artifactType": "FORMULA_READY_BATCH_AGGREGATE",
        "schemaVersion": BATCH_STATUS_SCHEMA_VERSION,
        "uniqueSymbolCount": evaluated,
        "statusCounts": dict(sorted(statuses.items())),
        "reasonCounts": dict(sorted(reasons.items())),
        "stopSignal": stop_signal,
        "dominantGap": (
            {
                "reasonCode": dominant[0][0],
                "count": dominant[0][1],
                "evaluatedCount": evaluated,
                "fraction": dominant[0][1] / evaluated,
            }
            if dominant
            else None
        ),
        "missingValuesCoerced": False,
        "objectiveRatingExecuted": False,
    }
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def _load_terminal_evidence(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records", payload)
    return {item["symbol"]: item for item in records}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--terminal-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slice-size", type=int, default=20)
    args = parser.parse_args()
    source = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    payload = build_remaining_manifest(
        source,
        _load_terminal_evidence(args.terminal_evidence),
        slice_size=args.slice_size,
    )
    write_immutable_json(args.output, payload)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
