import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.combined_backfill_cli import (
    formula_coverage,
    insufficient_reason_codes,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)
from equity_analysis.provider_validation.scoring_backfill_cli import (
    ScoringInputV2Record,
)

AGGREGATE_SCHEMA_VERSION = "formula-ready-243-aggregate-v1.0.0"
FORMULA_READY_STATUSES = frozenset(
    {"FORMULA_READY", "SKIPPED_EXISTING_COMPLETE"}
)
ALLOWED_SECURITY_STATUSES = FORMULA_READY_STATUSES | {
    "SECURITY_INSUFFICIENT_DATA"
}


def _file_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _verify_canonical_artifact(payload: dict[str, Any], hash_field: str) -> None:
    expected = payload.get(hash_field)
    without_hash = {key: value for key, value in payload.items() if key != hash_field}
    if expected != canonical_hash(without_hash):
        raise ValueError(f"CANONICAL_ARTIFACT_HASH_MISMATCH[{hash_field}]")


def _resolve_storage_path(reference: str, repository_root: Path) -> Path:
    path = Path(reference)
    resolved = (path if path.is_absolute() else repository_root / path).resolve()
    expected_root = (
        repository_root / "storage/provider-validation/scoring-inputs-v2"
    ).resolve()
    if resolved != expected_root and expected_root not in resolved.parents:
        raise ValueError("STORAGE_REFERENCE_OUTSIDE_CONTROLLED_ROOT")
    return resolved


def _verify_formula_ready_result(
    result: dict[str, Any],
    repository_root: Path,
) -> dict[str, Any]:
    receipt = result.get("receipt")
    if not receipt:
        raise ValueError(f"MISSING_FORMULA_READY_RECEIPT[{result['symbol']}]")
    path = _resolve_storage_path(receipt["storageReference"], repository_root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    content_hash = canonical_hash(payload)
    if (
        path.stem.upper() != content_hash
        or receipt["contentHash"] != content_hash
        or payload.get("symbol") != result["symbol"]
    ):
        raise ValueError(f"FORMULA_READY_STORAGE_HASH_MISMATCH[{result['symbol']}]")
    records = tuple(
        ScoringInputV2Record.model_validate(item) for item in payload["records"]
    )
    coverage = formula_coverage(records)
    if not coverage["complete"]:
        raise ValueError(f"FORMULA_READY_COVERAGE_INCOMPLETE[{result['symbol']}]")
    dataset_counts = dict(sorted(Counter(item.dataset for item in records).items()))
    if (
        receipt["recordCount"] != len(records)
        or receipt["datasetCoverage"] != dataset_counts
    ):
        raise ValueError(f"FORMULA_READY_RECEIPT_MISMATCH[{result['symbol']}]")
    return {
        "symbol": result["symbol"],
        "status": "FORMULA_READY",
        "sourceResultStatus": result["status"],
        "storageReference": receipt["storageReference"],
        "contentHash": content_hash,
        "recordCount": len(records),
        "datasetCoverage": dataset_counts,
        "formulaCoverageComplete": True,
        "reasonCodes": [],
    }


def _verify_insufficient_result(result: dict[str, Any]) -> dict[str, Any]:
    coverage = result.get("formulaCoverage")
    if not coverage or coverage.get("complete") is not False:
        raise ValueError(f"INVALID_INSUFFICIENT_COVERAGE[{result['symbol']}]")
    expected_reasons = insufficient_reason_codes(coverage)
    if result.get("reasonCodes") != expected_reasons:
        raise ValueError(f"INSUFFICIENT_REASON_MISMATCH[{result['symbol']}]")
    return {
        "symbol": result["symbol"],
        "status": "SECURITY_INSUFFICIENT_DATA",
        "sourceResultStatus": result["status"],
        "contentHash": canonical_hash(result),
        "formulaCoverageComplete": False,
        "reasonCodes": expected_reasons,
    }


def _verify_checkpoint(
    checkpoint_root: Path,
    report: dict[str, Any],
    sequence: int,
    result: dict[str, Any],
) -> str:
    expected_path = (
        checkpoint_root
        / report["runId"]
        / f"{sequence:04d}-{result['symbol']}.json"
    )
    payload = json.loads(expected_path.read_text(encoding="utf-8"))
    if (
        payload.get("runId") != report["runId"]
        or payload.get("sliceId") != report["sliceId"]
        or payload.get("sequence") != sequence
        or payload.get("symbol") != result["symbol"]
        or payload.get("status") != result["status"]
        or payload.get("resultHash") != canonical_hash(result)
    ):
        raise ValueError(f"RESULT_CHECKPOINT_MISMATCH[{result['symbol']}]")
    return _file_sha256(expected_path)


def _merge_counts(target: Counter, values: dict[str, int]) -> None:
    target.update({key: int(value) for key, value in values.items()})


def _verify_report(
    path: Path,
    repository_root: Path,
    checkpoint_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    _verify_canonical_artifact(report, "artifactContentHash")
    if report.get("status") == "SYSTEM_EXECUTION_FAIL":
        raise ValueError(f"SYSTEM_EXECUTION_FAIL[{report.get('runId')}]")
    if report.get("networkRetries") != 0:
        raise ValueError(f"NETWORK_RETRIES_PRESENT[{report.get('runId')}]")
    entries = []
    for sequence, result in enumerate(report["results"], start=1):
        if result["status"] not in ALLOWED_SECURITY_STATUSES:
            raise ValueError(
                f"UNSUPPORTED_SECURITY_STATUS[{result['symbol']}:{result['status']}]"
            )
        entry = (
            _verify_formula_ready_result(result, repository_root)
            if result["status"] in FORMULA_READY_STATUSES
            else _verify_insufficient_result(result)
        )
        entry["sourceRunId"] = report["runId"]
        entry["sourceSliceId"] = report["sliceId"]
        entry["sourceReportPath"] = path.as_posix()
        entry["sourceReportSha256"] = _file_sha256(path)
        entry["checkpointSha256"] = _verify_checkpoint(
            checkpoint_root, report, sequence, result
        )
        entries.append(entry)
    return entries, report


def _find_source_by_hash(
    directory: Path,
    expected_hash: str,
) -> tuple[Path, dict[str, Any]]:
    for path in sorted(directory.glob("*.json")):
        if _file_sha256(path) == expected_hash:
            return path, json.loads(path.read_text(encoding="utf-8"))
    raise ValueError(f"TERMINAL_SOURCE_HASH_NOT_FOUND[{expected_hash}]")


def _terminal_entries(
    evidence: dict[str, Any],
    generated_directory: Path,
) -> list[dict[str, Any]]:
    entries = []
    for item in evidence["records"]:
        source_path, source = _find_source_by_hash(
            generated_directory, item["sourceReportSha256"]
        )
        symbol = item["symbol"]
        source_items = source.get("securities", source.get("results", ()))
        matches = [record for record in source_items if record.get("symbol") == symbol]
        if len(matches) != 1:
            raise ValueError(f"TERMINAL_SOURCE_SYMBOL_MISMATCH[{symbol}]")
        if item["status"] == "FORMULA_READY":
            if matches[0].get("status") != "FORMULA_READY":
                raise ValueError(f"TERMINAL_FORMULA_READY_NOT_PROVEN[{symbol}]")
            status = "FORMULA_READY"
            reasons: list[str] = []
            content_hash = matches[0]["payloadHash"]
        elif item["status"] == "SECURITY_INSUFFICIENT_DATA":
            reasons = item.get("reasonCodes", ())
            if not reasons:
                raise ValueError(f"TERMINAL_INSUFFICIENT_REASON_MISSING[{symbol}]")
            status = item["status"]
            content_hash = canonical_hash(item)
        else:
            raise ValueError(f"UNSUPPORTED_TERMINAL_STATUS[{symbol}]")
        entries.append(
            {
                "symbol": symbol,
                "status": status,
                "sourceResultStatus": matches[0].get("status"),
                "sourceRunId": item["sourceRunId"],
                "sourceSliceId": None,
                "sourceReportPath": source_path.as_posix(),
                "sourceReportSha256": item["sourceReportSha256"],
                "checkpointSha256": None,
                "contentHash": content_hash,
                "formulaCoverageComplete": status == "FORMULA_READY",
                "reasonCodes": list(reasons),
            }
        )
    return entries


def _validate_scope(
    entries: list[dict[str, Any]],
    source_symbols: list[str],
) -> list[dict[str, Any]]:
    symbols = [item["symbol"] for item in entries]
    if len(symbols) != len(set(symbols)):
        raise ValueError("FINAL_AGGREGATE_DUPLICATE_SYMBOL")
    if set(symbols) != set(source_symbols) or len(symbols) != 243:
        raise ValueError("FINAL_AGGREGATE_SOURCE_SCOPE_MISMATCH")
    by_symbol = {item["symbol"]: item for item in entries}
    return [by_symbol[symbol] for symbol in source_symbols]


def build_final_aggregate(
    *,
    source_manifest_path: Path,
    terminal_evidence_path: Path,
    report_paths: list[Path],
    repository_root: Path,
    checkpoint_root: Path,
    generated_directory: Path,
) -> dict[str, Any]:
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    _verify_canonical_artifact(source_manifest, "manifestContentHash")
    terminal = json.loads(terminal_evidence_path.read_text(encoding="utf-8"))
    entries = _terminal_entries(terminal, generated_directory)
    reports = []
    for path in report_paths:
        report_entries, report = _verify_report(
            path, repository_root, checkpoint_root
        )
        entries.extend(report_entries)
        reports.append((path, report))
    source_symbols = [item["symbol"] for item in source_manifest["records"]]
    ordered = _validate_scope(entries, source_symbols)
    statuses = Counter(item["status"] for item in ordered)
    reasons = Counter(
        reason for item in ordered for reason in item.get("reasonCodes", ())
    )
    logical = Counter()
    replayed = Counter()
    new_eodhd = Counter()
    new_sec = Counter()
    new_totals = Counter()
    component_reports = []
    for path, report in reports:
        _merge_counts(logical, report.get("logicalEndpointEvaluations", {}))
        _merge_counts(replayed, report.get("replayedCompletedEndpoints", {}))
        physical = report.get("newPhysicalAttempts", {})
        _merge_counts(new_eodhd, physical.get("eodhd", {}))
        _merge_counts(new_sec, physical.get("sec", {}))
        for key in ("eodhdTotal", "secTotal", "total"):
            new_totals[key] += int(physical.get(key, 0))
        component_reports.append(
            {
                "runId": report["runId"],
                "sliceId": report["sliceId"],
                "path": path.as_posix(),
                "sha256": _file_sha256(path),
                "artifactContentHash": report["artifactContentHash"],
            }
        )
    payload = {
        "artifactType": "FORMULA_READY_243_FINAL_AGGREGATE",
        "schemaVersion": AGGREGATE_SCHEMA_VERSION,
        "sourceManifestPath": source_manifest_path.as_posix(),
        "sourceManifestSha256": _file_sha256(source_manifest_path),
        "sourceManifestContentHash": source_manifest["manifestContentHash"],
        "terminalEvidencePath": terminal_evidence_path.as_posix(),
        "terminalEvidenceSha256": _file_sha256(terminal_evidence_path),
        "componentReports": component_reports,
        "uniqueSecurityCount": len(ordered),
        "statusCounts": dict(sorted(statuses.items())),
        "reasonCounts": dict(sorted(reasons.items())),
        "systemExecutionFailures": 0,
        "networkRetries": 0,
        "telemetry": {
            "logicalEndpointEvaluations": dict(sorted(logical.items())),
            "replayedCompletedEndpoints": dict(sorted(replayed.items())),
            "newPhysicalAttempts": {
                "eodhd": dict(sorted(new_eodhd.items())),
                "sec": dict(sorted(new_sec.items())),
                **dict(sorted(new_totals.items())),
            },
        },
        "securities": ordered,
        "aggregateStatus": (
            "COMPLETE_WITH_INSUFFICIENT_DATA"
            if statuses["SECURITY_INSUFFICIENT_DATA"]
            else "FORMULA_READY"
        ),
        "scoringReadyMeaning": "INPUT_CONTRACT_READY_ONLY",
        "objectiveRatingExecuted": False,
        "rawProviderValuesIncluded": False,
        "credentialsIncluded": False,
    }
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--terminal-evidence", type=Path, required=True)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--generated-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    aggregate = build_final_aggregate(
        source_manifest_path=args.source_manifest,
        terminal_evidence_path=args.terminal_evidence,
        report_paths=args.report,
        repository_root=args.repository_root,
        checkpoint_root=args.checkpoint_root,
        generated_directory=args.generated_directory,
    )
    write_immutable_json(args.output, aggregate)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "uniqueSecurityCount": aggregate["uniqueSecurityCount"],
                "statusCounts": aggregate["statusCounts"],
                "aggregateStatus": aggregate["aggregateStatus"],
                "artifactContentHash": aggregate["artifactContentHash"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
