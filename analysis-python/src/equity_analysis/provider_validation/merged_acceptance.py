import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from equity_analysis.provider_validation.mature_gate import (
    REPORT_VERSION,
    REQUIRED_NORMALIZED_FIELDS,
)

SCHEMA_VERSION = "mature-gate-merged-acceptance-v1.0.0"
DIAGNOSTIC_SCHEMA_VERSION = "provider-gate-diagnostics-v1.0.0"


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def _load_verified(path_value: str, expected_hash: str) -> dict[str, Any]:
    path = Path(path_value)
    if not path.is_file():
        raise ValueError(f"Required source artifact is missing: {path}")
    actual_hash = _sha256(path)
    if actual_hash != expected_hash.upper():
        raise ValueError(f"Source artifact hash mismatch: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _validated_live_source(
    metadata: dict[str, Any],
    *,
    require_diagnostics: bool,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    if metadata.get("evidenceType") != "LIVE_IMMUTABLE_REPORT":
        raise ValueError("Only immutable live reports may override the ledger")
    report = _load_verified(metadata["reportPath"], metadata["reportSha256"])
    if report.get("runId") != metadata["runId"]:
        raise ValueError("Live report run ID does not match its manifest entry")
    if report.get("reportVersion") != REPORT_VERSION:
        raise ValueError("Live report uses an incompatible gate standard version")
    parser_versions: tuple[str, ...] = ()
    if require_diagnostics:
        if not metadata.get("diagnosticPath") or not metadata.get("diagnosticSha256"):
            raise ValueError("Live override is missing diagnostic source evidence")
        diagnostics = _load_verified(
            metadata["diagnosticPath"],
            metadata["diagnosticSha256"],
        )
        if diagnostics.get("runId") != metadata["runId"]:
            raise ValueError("Diagnostic run ID does not match its live report")
        if diagnostics.get("diagnosticSchemaVersion") != DIAGNOSTIC_SCHEMA_VERSION:
            raise ValueError("Diagnostic source uses an incompatible schema version")
        parser_versions = tuple(
            sorted(
                {
                    item["parserVersion"]
                    for item in diagnostics["securities"]
                    if item.get("parserVersion")
                }
            )
        )
    return report, parser_versions


def _billing_evidence(metadata: dict[str, Any]) -> dict[str, Any]:
    observed_delta = metadata["dashboardAfter"] - metadata["dashboardBefore"]
    return {
        "runId": metadata["runId"],
        "dashboardBefore": metadata["dashboardBefore"],
        "dashboardAfter": metadata["dashboardAfter"],
        "observedDelta": observed_delta,
        "provisionalBilling": metadata["provisionalBilling"],
        "billingSafetyCeiling": metadata["billingSafetyCeiling"],
        "runLevelBillingStatus": (
            "PROVISIONALLY_RECONCILED"
            if observed_delta <= metadata["provisionalBilling"]
            and observed_delta <= metadata["billingSafetyCeiling"]
            else "NOT_RECONCILED"
        ),
        "endpointLevelBillingStatus": "NOT_RECONCILED",
    }


def merge_live_results(
    base_report: dict[str, Any],
    overrides: tuple[tuple[dict[str, Any], dict[str, Any]], ...],
    *,
    target_pass_count: int,
    base_metadata: dict[str, Any],
) -> dict[str, Any]:
    base_symbols = [item["symbol"] for item in base_report["results"]]
    if len(base_symbols) != len(set(base_symbols)):
        raise ValueError("Base report contains duplicate symbols")
    ledger = {
        item["symbol"]: {
            "symbol": item["symbol"],
            "sector": item["sector"],
            "candidateRole": item["candidateRole"],
            "sourceRunId": base_metadata["runId"],
            "sourceReportSha256": base_metadata["reportSha256"],
            "status": item["status"],
            "reasonCodes": item["reasonCodes"],
            "liveConfirmed": True,
        }
        for item in base_report["results"]
    }
    for metadata, report in overrides:
        if metadata.get("evidenceType") != "LIVE_IMMUTABLE_REPORT":
            raise ValueError("Only immutable live reports may override the ledger")
        symbols = [item["symbol"] for item in report["results"]]
        if len(symbols) != len(set(symbols)):
            raise ValueError("Live override contains duplicate symbols")
        for item in report["results"]:
            if item["symbol"] not in ledger:
                raise ValueError("Live override contains a symbol outside the base universe")
            previous = ledger[item["symbol"]]
            ledger[item["symbol"]] = {
                **previous,
                "sourceRunId": metadata["runId"],
                "sourceReportSha256": metadata["reportSha256"],
                "status": item["status"],
                "reasonCodes": item["reasonCodes"],
                "liveConfirmed": True,
            }
    records = tuple(sorted(ledger.values(), key=lambda item: item["symbol"]))
    pass_records = tuple(item for item in records if item["status"] == "PASS")
    if len({item["symbol"] for item in pass_records}) != len(pass_records):
        raise ValueError("Merged PASS ledger contains duplicate symbols")
    if any(not item["liveConfirmed"] for item in pass_records):
        raise ValueError("Merged PASS ledger contains a non-live result")
    return {
        "ledger": records,
        "passRecords": pass_records,
        "unresolvedRecords": tuple(
            item for item in records if item["status"] != "PASS"
        ),
        "uniquePassCount": len(pass_records),
        "aggregateGateStatus": (
            "PASS" if len(pass_records) >= target_pass_count else "FAIL"
        ),
        "passShortfall": max(target_pass_count - len(pass_records), 0),
    }


def build_merged_acceptance(manifest: dict[str, Any]) -> dict[str, Any]:
    base_metadata = manifest["baseRun"]
    base_report, _ = _validated_live_source(
        base_metadata,
        require_diagnostics=False,
    )
    validated_overrides = []
    parser_versions: set[str] = set()
    component_runs = [base_metadata["runId"]]
    billing = [_billing_evidence(base_metadata)]
    for metadata in sorted(
        manifest["liveOverrides"],
        key=lambda item: item["sequence"],
    ):
        report, versions = _validated_live_source(
            metadata,
            require_diagnostics=True,
        )
        parser_versions.update(versions)
        validated_overrides.append((metadata, report))
        component_runs.append(metadata["runId"])
        billing.append(_billing_evidence(metadata))
    for evidence in manifest.get("offlineEvidence", ()):
        _load_verified(evidence["artifactPath"], evidence["artifactSha256"])
        if evidence.get("eligibleForStatusOverride"):
            raise ValueError("Offline evidence cannot be eligible for status override")
    merged = merge_live_results(
        base_report,
        tuple(validated_overrides),
        target_pass_count=manifest["targetPassCount"],
        base_metadata=base_metadata,
    )
    payload = {
        "artifactType": "CROSS_RUN_PROVIDER_GATE_AGGREGATE_ACCEPTANCE",
        "schemaVersion": SCHEMA_VERSION,
        "isSingleLiveGateRun": False,
        "networkRequestsExecuted": False,
        "generatedAt": datetime.now(UTC).isoformat(),
        "targetPassCount": manifest["targetPassCount"],
        "standards": {
            "gateReportVersion": REPORT_VERSION,
            "diagnosticSchemaVersion": DIAGNOSTIC_SCHEMA_VERSION,
            "parserVersions": sorted(parser_versions),
            "pitPeriodToleranceDays": 7,
            "requiredNormalizedFields": sorted(REQUIRED_NORMALIZED_FIELDS),
        },
        "coverageRule": (
            "Each base-universe symbol appears once. A later status replaces an "
            "earlier status only when it comes from a hash-verified immutable live "
            "report using the same gate standard. Offline evidence never upgrades status."
        ),
        "componentRunIds": component_runs,
        "billingEvidence": billing,
        "runLevelBillingStatus": (
            "PROVISIONALLY_RECONCILED"
            if all(
                item["runLevelBillingStatus"] == "PROVISIONALLY_RECONCILED"
                for item in billing
            )
            else "NOT_RECONCILED"
        ),
        "endpointLevelBillingStatus": "NOT_RECONCILED",
        **merged,
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


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge immutable mature-gate live evidence without network access."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    generated_at = datetime.now(UTC)
    run_id = f"{generated_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:12]}"
    built = build_merged_acceptance(manifest)
    artifact_without_hash = {
        "runId": run_id,
        **{
            key: value
            for key, value in built.items()
            if key != "artifactContentHash"
        },
    }
    canonical = json.dumps(
        artifact_without_hash,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    artifact = {
        **artifact_without_hash,
        "artifactContentHash": sha256(canonical).hexdigest().upper(),
    }
    output = (
        arguments.output_directory
        / f"mature-company-data-gate-{run_id}-merged-acceptance.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(artifact, handle, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                "runId": run_id,
                "output": str(output),
                "uniquePassCount": artifact["uniquePassCount"],
                "aggregateGateStatus": artifact["aggregateGateStatus"],
                "networkRequestsExecuted": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
