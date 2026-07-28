import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = "mature-gate-offline-reclassification-v1.0.0"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a derived mature-gate reclassification without network access."
    )
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--focused-report", type=Path, action="append", default=[])
    parser.add_argument("--focused-diagnostics", type=Path, action="append", default=[])
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def _classification(
    symbol: str,
    status: str,
    reasons: tuple[str, ...],
) -> str:
    if symbol == "NVDA" and status == "PASS":
        return "CONFIRMED_ALIAS_RECOVERY"
    if symbol == "EXPO":
        return "CONFIRMED_ALIAS_RECOVERY_WITH_TRUE_PIT_MISMATCH"
    if symbol == "VZ":
        return "CONFIRMED_PIT_NOT_YET_AVAILABLE"
    if symbol == "TXN":
        return "LOCAL_PIT_FIX_PENDING_LIVE_CONFIRMATION"
    if symbol == "LANC":
        return "AUTHORITATIVE_CIK_MAPPING_MISSING"
    reason_set = set(reasons)
    if reason_set == {"MISSING_REQUIREDRATINGFIELDS"}:
        return "REQUIRES_REPARSE_FIELD_DIAGNOSTICS"
    if reason_set == {"MISSING_PITAVAILABILITY"}:
        return "UNRESOLVED_PIT_WITHOUT_PERIOD_DIAGNOSTICS"
    if reason_set == {
        "MISSING_REQUIREDRATINGFIELDS",
        "MISSING_PITAVAILABILITY",
    }:
        return "REQUIRES_REPARSE_AND_PIT_DIAGNOSTICS"
    if status == "PASS":
        return "CONFIRMED_PASS"
    return "UNRESOLVED"


def build_derived_report(
    source: dict[str, Any],
    focused_reports: tuple[dict[str, Any], ...],
    *,
    run_id: str,
    generated_at: datetime,
    source_references: tuple[dict[str, str], ...],
) -> dict[str, Any]:
    focused_by_symbol: dict[str, dict[str, Any]] = {}
    for report in focused_reports:
        for item in report["results"]:
            focused_by_symbol[item["symbol"]] = item

    records = []
    for original in source["results"]:
        overlay = focused_by_symbol.get(original["symbol"])
        derived_status = overlay["status"] if overlay else original["status"]
        derived_reasons = tuple(
            overlay["reasonCodes"] if overlay else original["reasonCodes"]
        )
        records.append(
            {
                "symbol": original["symbol"],
                "candidateRole": original["candidateRole"],
                "sector": original["sector"],
                "originalStatus": original["status"],
                "originalReasonCodes": original["reasonCodes"],
                "derivedStatus": derived_status,
                "derivedReasonCodes": derived_reasons,
                "classification": _classification(
                    original["symbol"],
                    derived_status,
                    derived_reasons,
                ),
            }
        )

    original_counts = {
        status: sum(item["originalStatus"] == status for item in records)
        for status in ("PASS", "PARTIAL", "FAIL")
    }
    derived_counts = {
        status: sum(item["derivedStatus"] == status for item in records)
        for status in ("PASS", "PARTIAL", "FAIL")
    }
    payload = {
        "artifactType": "OFFLINE_DERIVED_RECLASSIFICATION",
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "generatedAt": generated_at.isoformat(),
        "isLiveGate": False,
        "networkRequestsExecuted": False,
        "sourceReferences": source_references,
        "originalCounts": original_counts,
        "derivedCounts": derived_counts,
        "confirmedPassCount": derived_counts["PASS"],
        "additionalConfirmedPassesNeeded": max(100 - derived_counts["PASS"], 0),
        "records": records,
        "limitations": [
            "The 120-security report does not retain normalized financial "
            "payloads or per-field provider diagnostics.",
            "Only symbols with later focused evidence can be conclusively reclassified.",
            "The TXN local PIT fix requires a later bounded live confirmation "
            "because its licensed payload was not retained.",
            "No Objective Rating, PIT, required-field, or PASS rule was changed.",
        ],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return {
        **payload,
        "artifactContentHash": sha256(canonical).hexdigest().upper(),
    }


def main() -> None:
    arguments = _arguments()
    generated_at = datetime.now(UTC)
    run_id = f"{generated_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:12]}"
    source_paths = (
        arguments.source_report,
        *arguments.focused_report,
        *arguments.focused_diagnostics,
    )
    source_references = tuple(
        {"path": str(path), "sha256": _sha256(path)} for path in source_paths
    )
    report = build_derived_report(
        _read_json(arguments.source_report),
        tuple(_read_json(path) for path in arguments.focused_report),
        run_id=run_id,
        generated_at=generated_at,
        source_references=source_references,
    )
    output = (
        arguments.output_directory
        / f"mature-company-data-gate-{run_id}-offline-reclassification.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                "runId": run_id,
                "output": str(output),
                "confirmedPassCount": report["confirmedPassCount"],
                "additionalConfirmedPassesNeeded": report[
                    "additionalConfirmedPassesNeeded"
                ],
                "networkRequestsExecuted": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
