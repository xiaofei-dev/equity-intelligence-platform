import argparse
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

RECONCILIATION_SCHEMA_VERSION = "formula-ready-billing-reconciliation-v1.0.0"
PROVISIONAL_BILLING_PER_EODHD_SYMBOL = 25


def calculate_budget(
    configured_local_weights: list[int],
    eodhd_symbol_count: int,
) -> dict[str, int]:
    configured = sum(configured_local_weights)
    provisional = eodhd_symbol_count * PROVISIONAL_BILLING_PER_EODHD_SYMBOL
    return {
        "configuredLocalWeights": configured,
        "provisionalProviderBilling": provisional,
        "hardProviderBilledSafetyCeiling": (provisional * 3 + 1) // 2,
    }


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def _verify_event(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = payload.get("eventHash")
    without_hash = {key: value for key, value in payload.items() if key != "eventHash"}
    if expected != canonical_hash(without_hash):
        raise ValueError(f"RUN_JOURNAL_EVENT_HASH_MISMATCH[{path}]")
    return payload


def build_billing_reconciliation(
    *,
    aggregate_path: Path,
    expected_aggregate_sha256: str,
    repository_root: Path,
    dashboard_before: int,
    dashboard_after: int,
) -> dict[str, Any]:
    actual_aggregate_sha = _sha256(aggregate_path)
    if actual_aggregate_sha != expected_aggregate_sha256.upper():
        raise ValueError("FINAL_AGGREGATE_SHA256_MISMATCH")
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    expected_content_hash = aggregate.get("artifactContentHash")
    if expected_content_hash != canonical_hash(
        {
            key: value
            for key, value in aggregate.items()
            if key != "artifactContentHash"
        }
    ):
        raise ValueError("FINAL_AGGREGATE_CONTENT_HASH_MISMATCH")
    if (
        aggregate["uniqueSecurityCount"] != 243
        or aggregate["statusCounts"]
        != {"FORMULA_READY": 223, "SECURITY_INSUFFICIENT_DATA": 20}
        or aggregate["systemExecutionFailures"] != 0
        or aggregate["networkRetries"] != 0
    ):
        raise ValueError("FINAL_AGGREGATE_CLOSEOUT_COUNTS_MISMATCH")

    run_evidence = []
    configured_local_weight = 0
    checkpoints_by_run: dict[str, list[dict[str, Any]]] = {}
    payloads_by_run: dict[str, list[dict[str, Any]]] = {}
    for security in aggregate["securities"]:
        run_id = security["sourceRunId"]
        if security["sourceSliceId"] is not None:
            checkpoint_directory = (
                repository_root
                / "storage/provider-validation/scoring-inputs-v2/checkpoints"
                / run_id
            )
            checkpoint_matches = sorted(
                checkpoint_directory.glob(f"*-{security['symbol']}.json")
            )
            if (
                len(checkpoint_matches) != 1
                or _sha256(checkpoint_matches[0]) != security["checkpointSha256"]
            ):
                raise ValueError(
                    f"CHECKPOINT_SHA256_MISMATCH[{security['symbol']}]"
                )
            checkpoints_by_run.setdefault(run_id, []).append(
                {
                    "symbol": security["symbol"],
                    "path": checkpoint_matches[0].as_posix(),
                    "sha256": security["checkpointSha256"],
                }
            )
        storage_reference = security.get("storageReference")
        if storage_reference:
            storage_path = repository_root / storage_reference
            storage_payload = json.loads(storage_path.read_text(encoding="utf-8"))
            if (
                storage_path.stem.upper() != security["contentHash"]
                or canonical_hash(storage_payload) != security["contentHash"]
            ):
                raise ValueError(
                    f"TERMINAL_PAYLOAD_HASH_MISMATCH[{security['symbol']}]"
                )
        payloads_by_run.setdefault(run_id, []).append(
            {
                "symbol": security["symbol"],
                "status": security["status"],
                "contentHash": security["contentHash"],
                "storageReference": storage_reference,
            }
        )
    journal_root = (
        repository_root
        / "storage/provider-validation/scoring-inputs-v2/physical-request-journals"
    )
    for component in aggregate["componentReports"]:
        run_id = component["runId"]
        report_path = (
            repository_root / component["path"]
            if not Path(component["path"]).is_absolute()
            else Path(component["path"])
        )
        if _sha256(report_path) != component["sha256"]:
            raise ValueError(f"COMPONENT_REPORT_SHA256_MISMATCH[{run_id}]")
        run_directory = journal_root / run_id / "run"
        preflight_paths = sorted(run_directory.glob("*-PREFLIGHT.json"))
        complete_paths = sorted(run_directory.glob("*-COMPLETE.json"))
        if len(preflight_paths) != 1 or len(complete_paths) != 1:
            raise ValueError(f"RUN_JOURNAL_TERMINAL_EVENTS_MISSING[{run_id}]")
        preflight = _verify_event(preflight_paths[0])
        complete = _verify_event(complete_paths[0])
        if (
            preflight["runId"] != run_id
            or complete["runId"] != run_id
            or complete["detail"]["status"] == "SYSTEM_EXECUTION_FAIL"
        ):
            raise ValueError(f"RUN_JOURNAL_STATUS_MISMATCH[{run_id}]")
        configured_local_weight += int(
            preflight["detail"]["configuredLocalWeightCeiling"]
        )
        run_evidence.append(
            {
                "runId": run_id,
                "sliceId": component["sliceId"],
                "reportPath": component["path"],
                "reportSha256": component["sha256"],
                "reportContentHash": component["artifactContentHash"],
                "preflightJournalPath": preflight_paths[0].as_posix(),
                "preflightJournalSha256": _sha256(preflight_paths[0]),
                "preflightEventHash": preflight["eventHash"],
                "completeJournalPath": complete_paths[0].as_posix(),
                "completeJournalSha256": _sha256(complete_paths[0]),
                "completeEventHash": complete["eventHash"],
                "configuredLocalWeightCeiling": preflight["detail"][
                    "configuredLocalWeightCeiling"
                ],
                "checkpoints": sorted(
                    checkpoints_by_run[run_id], key=lambda item: item["symbol"]
                ),
                "terminalPayloads": sorted(
                    payloads_by_run[run_id], key=lambda item: item["symbol"]
                ),
            }
        )

    telemetry = aggregate["telemetry"]["newPhysicalAttempts"]
    eodhd_total = int(telemetry["eodhdTotal"])
    sec_total = int(telemetry["secTotal"])
    total = int(telemetry["total"])
    if eodhd_total != 705 or sec_total != 476 or total != 1181:
        raise ValueError("PHYSICAL_ATTEMPT_CLOSEOUT_MISMATCH")
    eodhd_symbols = int(
        aggregate["telemetry"]["logicalEndpointEvaluations"]["fundamentals"]
    )
    budget = calculate_budget(
        [
            int(item["configuredLocalWeightCeiling"])
            for item in run_evidence
        ],
        eodhd_symbols,
    )
    provisional = budget["provisionalProviderBilling"]
    hard_ceiling = budget["hardProviderBilledSafetyCeiling"]
    if (
        configured_local_weight != 2820
        or provisional != 5875
        or hard_ceiling != 8813
    ):
        raise ValueError("INDEPENDENT_BUDGET_RECALCULATION_MISMATCH")
    observed_delta = dashboard_after - dashboard_before
    if observed_delta < 0 or observed_delta > hard_ceiling:
        raise ValueError("OBSERVED_DASHBOARD_DELTA_OUTSIDE_CLOSEOUT_BOUND")

    payload = {
        "artifactType": "FORMULA_READY_FINAL_BILLING_RECONCILIATION",
        "schemaVersion": RECONCILIATION_SCHEMA_VERSION,
        "finalAggregatePath": aggregate_path.as_posix(),
        "finalAggregateSha256": actual_aggregate_sha,
        "finalAggregateContentHash": expected_content_hash,
        "dashboard": {
            "before": dashboard_before,
            "after": dashboard_after,
            "observedProviderBilledDelta": observed_delta,
        },
        "budget": {
            **budget,
            "provisionalBillingPerEodhdSymbol": (
                PROVISIONAL_BILLING_PER_EODHD_SYMBOL
            ),
        },
        "physicalAttempts": {
            "eodhd": eodhd_total,
            "sec": sec_total,
            "total": total,
            "retries": aggregate["networkRetries"],
            "byEndpoint": {
                "eodhd": telemetry["eodhd"],
                "sec": telemetry["sec"],
            },
        },
        "securityCounts": {
            "unique": aggregate["uniqueSecurityCount"],
            "formulaReady": aggregate["statusCounts"]["FORMULA_READY"],
            "insufficientData": aggregate["statusCounts"][
                "SECURITY_INSUFFICIENT_DATA"
            ],
            "systemExecutionFailures": aggregate["systemExecutionFailures"],
        },
        "runLevelBillingStatus": "PROVISIONALLY_RECONCILED",
        "endpointLevelBillingStatus": "NOT_RECONCILED",
        "componentEvidence": run_evidence,
        "terminalEvidenceOutsideSlices": sorted(
            (
                item
                for run_id, items in payloads_by_run.items()
                if run_id not in checkpoints_by_run
                for item in items
            ),
            key=lambda item: item["symbol"],
        ),
        "rawProviderValuesIncluded": False,
        "licensedPayloadsIncluded": False,
        "credentialsIncluded": False,
        "objectiveRatingExecuted": False,
        "networkRequestsExecutedDuringReconciliation": False,
    }
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--aggregate-sha256", required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--dashboard-before", type=int, required=True)
    parser.add_argument("--dashboard-after", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reconciliation = build_billing_reconciliation(
        aggregate_path=args.aggregate,
        expected_aggregate_sha256=args.aggregate_sha256,
        repository_root=args.repository_root,
        dashboard_before=args.dashboard_before,
        dashboard_after=args.dashboard_after,
    )
    write_immutable_json(args.output, reconciliation)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "dashboardDelta": reconciliation["dashboard"][
                    "observedProviderBilledDelta"
                ],
                "runLevelBillingStatus": reconciliation[
                    "runLevelBillingStatus"
                ],
                "endpointLevelBillingStatus": reconciliation[
                    "endpointLevelBillingStatus"
                ],
                "artifactContentHash": reconciliation["artifactContentHash"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
