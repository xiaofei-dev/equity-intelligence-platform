import argparse
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

from equity_analysis.market_data.eodhd import EodhdProvider
from equity_analysis.market_data.provider import MarketDataProviderError
from equity_analysis.provider_validation.cli import _load_local_environment
from equity_analysis.provider_validation.expansion_gate import (
    ELIGIBLE_ROLES,
    GitignoredLocalScoringInputStore,
    build_scoring_input_manifest,
    build_slice_preflight,
    canonical_hash,
    file_hash,
    financial_observations_to_scoring_inputs,
    new_run_id,
    validate_expansion_universe,
    write_immutable_json,
)
from equity_analysis.provider_validation.mature_gate import (
    REPORT_VERSION,
    EodhdCallBudget,
    GateEvidenceLedger,
    MatureGateCandidate,
    MatureGateRunLock,
    required_statement_window,
)
from equity_analysis.provider_validation.mature_gate_cli import (
    DIAGNOSTIC_SCHEMA_VERSION,
    _failed_result,
    _sanitized_failure_reason,
    _validate_candidate,
)
from equity_analysis.provider_validation.models import (
    GateStatus,
    MatureGateSecurityResult,
)
from equity_analysis.provider_validation.sec_edgar import SecEdgarClient, SecEdgarError

LIVE_CONFIRMATION = "I_CONFIRM_ONE_EXPANSION_SLICE"
DEFAULT_UNIVERSE = Path(
    "analysis-python/tests/fixtures/provider_expansion_universe_v1.json"
)
DEFAULT_SLICE_MANIFEST = Path("docs/generated/provider-expansion-slice-manifest-v1.json")
DEFAULT_OUTPUT_DIRECTORY = Path("docs/generated")
DEFAULT_STORAGE_ROOT = Path("storage/provider-validation/scoring-inputs")


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute exactly one bounded provider-expansion slice."
    )
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--slice-manifest", type=Path, default=DEFAULT_SLICE_MANIFEST)
    parser.add_argument("--slice-id", required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2020, 1, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE_ROOT)
    parser.add_argument("--dashboard-before", type=int, required=True)
    parser.add_argument(
        "--dashboard-counter-status",
        choices=("CONFIRMED", "PROJECTED_WORST_CASE"),
        default="CONFIRMED",
    )
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--confirm-live", choices=(LIVE_CONFIRMATION,))
    return parser.parse_args()


def _load_and_validate(options: argparse.Namespace) -> tuple[dict, dict, dict]:
    universe = json.loads(options.universe.read_text(encoding="utf-8"))
    validate_expansion_universe(universe)
    stored_universe_hash = universe.get("universeContentHash")
    unhashed_universe = dict(universe)
    unhashed_universe.pop("universeContentHash", None)
    if stored_universe_hash != canonical_hash(unhashed_universe):
        raise SystemExit("Expansion universe content hash mismatch")

    manifest = json.loads(options.slice_manifest.read_text(encoding="utf-8"))
    stored_manifest_hash = manifest.get("manifestContentHash")
    unhashed_manifest = dict(manifest)
    unhashed_manifest.pop("manifestContentHash", None)
    if stored_manifest_hash != canonical_hash(unhashed_manifest):
        raise SystemExit("Expansion slice manifest content hash mismatch")
    if manifest["universeVersion"] != universe["universeVersion"]:
        raise SystemExit("Expansion universe and slice manifest versions differ")
    matching = [item for item in manifest["slices"] if item["sliceId"] == options.slice_id]
    if len(matching) != 1:
        raise SystemExit("Unknown or duplicate expansion slice ID")
    return universe, manifest, matching[0]


def _candidate(item: dict) -> MatureGateCandidate:
    return MatureGateCandidate(
        symbol=item["symbol"],
        sector=item["sector"],
        candidateRole=item["candidateRole"],
        selectionReason=item["selectionReason"],
        expectedCompanyType="MATURE_OPERATING_COMPANY",
        cik=item.get("cik"),
    )


def _reference_result(item: dict) -> MatureGateSecurityResult:
    return MatureGateSecurityResult(
        symbol=item["symbol"],
        sector=item["sector"],
        candidateRole=item["candidateRole"],
        status=GateStatus.EXCLUDED,
        reasonCodes=(item["classificationReason"],),
        fieldCoverage={},
        marketCapBand=item.get("marketCapBand"),
    )


def _persistence_failure_reason(error: Exception) -> str:
    message = str(error)
    reasons = {
        "Scoring input requires PIT availableAt": (
            "SCORING_INPUT_MISSING_PIT_AVAILABLE_AT"
        ),
        "Scoring input requires a matched PIT accession": (
            "SCORING_INPUT_MISSING_PIT_ACCESSION"
        ),
        "Scoring-input persistence requires records": (
            "SCORING_INPUT_REQUIRED_WINDOW_EMPTY"
        ),
        "SCORING_INPUT_REPLAY_CHANGED": "SCORING_INPUT_REPLAY_CHANGED",
        "CONTENT_ADDRESSED_SCORING_INPUT_COLLISION": (
            "CONTENT_ADDRESSED_SCORING_INPUT_COLLISION"
        ),
    }
    return reasons.get(message, "SCORING_INPUT_PERSISTENCE_ERROR")


def _run_live(
    options: argparse.Namespace,
    universe: dict,
    slice_record: dict,
    preflight: dict,
    started_at: datetime,
) -> None:
    local_environment = _load_local_environment(Path(".env"))
    api_key = os.getenv("EODHD_API_KEY") or local_environment.get("EODHD_API_KEY", "")
    user_agent = os.getenv("SEC_USER_AGENT") or local_environment.get("SEC_USER_AGENT", "")
    if not api_key:
        raise SystemExit("EODHD_API_KEY is required for live execution")
    if not user_agent:
        raise SystemExit("SEC_USER_AGENT is required for live execution")

    budget = EodhdCallBudget(
        weighted_call_ceiling=preflight["configuredLocalWeightCeiling"],
        request_ceiling=preflight["eodhdPhysicalAttemptCeiling"],
    )
    provider = EodhdProvider(
        api_key=api_key,
        request_observer=budget.record,
        request_authorizer=budget.reserve,
    )
    sec_metrics = []
    sec = SecEdgarClient(user_agent=user_agent, request_observer=sec_metrics.append)
    evidence_ledger = GateEvidenceLedger()
    storage = GitignoredLocalScoringInputStore(options.storage_root)
    candidate_by_symbol = {item["symbol"]: item for item in universe["candidates"]}
    results = []
    diagnostics = []
    receipts = []
    persistence_errors: dict[str, str] = {}

    for symbol in slice_record["symbols"]:
        item = candidate_by_symbol[symbol]
        if item["candidateRole"] not in ELIGIBLE_ROLES:
            result = _reference_result(item)
            results.append(
                {
                    **result.model_dump(mode="json", by_alias=True),
                    "scoringInputReady": False,
                    "scoringInputReasonCodes": ["REFERENCE_ONLY_NOT_SCORING_ELIGIBLE"],
                }
            )
            continue
        candidate = _candidate(item)
        captured_receipt = None

        def persist_normalized(
            financials,
            diagnostic,
            current_symbol=symbol,
        ) -> None:
            nonlocal captured_receipt
            try:
                accession_by_period = {
                    (
                        pit.statement_type,
                        pit.period_type,
                        pit.provider_fiscal_period_end,
                    ): pit.accession_number
                    for pit in diagnostic.pit_periods
                    if pit.accession_number
                }
                required = required_statement_window(financials)
                records = financial_observations_to_scoring_inputs(
                    required,
                    accession_by_period,
                    provider_code=provider.descriptor.code,
                )
                captured_receipt = storage.persist(
                    records,
                    run_id=preflight["runId"],
                )
                replay = storage.persist(records, run_id=preflight["runId"])
                if (
                    replay.normalized_payload_hash
                    != captured_receipt.normalized_payload_hash
                ):
                    raise RuntimeError("SCORING_INPUT_REPLAY_CHANGED")
            except (RuntimeError, ValueError) as error:
                persistence_errors[current_symbol] = _persistence_failure_reason(error)
                captured_receipt = None

        try:
            result, _payload_hash, diagnostic = _validate_candidate(
                candidate,
                provider,
                sec,
                evidence_ledger,
                options.start_date,
                options.end_date,
                normalized_observer=persist_normalized,
            )
            diagnostics.append(diagnostic.model_dump(mode="json", by_alias=True))
        except (
            MarketDataProviderError,
            SecEdgarError,
            RuntimeError,
            ValueError,
        ) as error:
            result = _failed_result(candidate, _sanitized_failure_reason(error))
            persistence_errors[symbol] = _sanitized_failure_reason(error)
        if captured_receipt is not None:
            receipts.append(captured_receipt)
        scoring_ready = result.status == GateStatus.PASS and captured_receipt is not None
        results.append(
            {
                **result.model_dump(mode="json", by_alias=True),
                "scoringInputReady": scoring_ready,
                "scoringInputReasonCodes": (
                    []
                    if scoring_ready
                    else [
                        persistence_errors.get(
                            symbol,
                            "PROVIDER_GATE_NOT_PASS_OR_SCORING_INPUT_NOT_PERSISTED",
                        )
                    ]
                ),
                "scoringInputPayloadHash": (
                    captured_receipt.normalized_payload_hash
                    if captured_receipt is not None
                    else None
                ),
                "scoringInputStorageReference": (
                    captured_receipt.storage_reference
                    if captured_receipt is not None
                    else None
                ),
            }
        )

    if len(sec_metrics) > preflight["secPhysicalAttemptCeiling"]:
        raise RuntimeError("SEC_REQUEST_BUDGET_EXHAUSTED")
    completed_at = datetime.now(UTC)
    report = {
        "reportVersion": REPORT_VERSION,
        "artifactType": "EXPANSION_PROVIDER_GATE_SLICE",
        "runId": preflight["runId"],
        "sliceId": slice_record["sliceId"],
        "universeVersion": universe["universeVersion"],
        "startedAt": started_at.isoformat(),
        "completedAt": completed_at.isoformat(),
        "dashboardBefore": options.dashboard_before,
        "dashboardAfter": None,
        "providerBillingReconciliation": "NOT_RECONCILED",
        "networkRerunSample": 0,
        "results": results,
        "requestMetrics": [
            item.model_dump(mode="json", by_alias=True)
            for item in (*budget.metrics, *sec_metrics)
        ],
        "physicalHttpAttemptCount": len(budget.metrics) + len(sec_metrics),
        "eodhdPhysicalAttemptCount": len(budget.metrics),
        "secPhysicalAttemptCount": len(sec_metrics),
        "configuredLocalWeightedCalls": budget.weighted_calls,
        "scoringInputReadyCount": sum(
            item["scoringInputReady"] for item in results
        ),
        "objectiveRatingExecuted": False,
        "licensedRawProviderPayloadIncluded": False,
    }
    report_path = Path(preflight["reportPath"])
    write_immutable_json(report_path, report)
    diagnostics_artifact = {
        "diagnosticSchemaVersion": DIAGNOSTIC_SCHEMA_VERSION,
        "runId": preflight["runId"],
        "sliceId": slice_record["sliceId"],
        "gateReportReference": report_path.name,
        "gateReportSha256": file_hash(report_path),
        "securities": diagnostics,
        "rawProviderValuesIncluded": False,
        "credentialsIncluded": False,
    }
    diagnostics_artifact["artifactContentHash"] = canonical_hash(diagnostics_artifact)
    write_immutable_json(Path(preflight["diagnosticPath"]), diagnostics_artifact)

    scoring_manifest = build_scoring_input_manifest(
        tuple(receipts),
        aggregate_artifact_path=str(report_path),
        aggregate_artifact_sha256=file_hash(report_path),
    )
    write_immutable_json(
        Path(preflight["scoringInputManifestPath"]),
        scoring_manifest,
    )
    checkpoint = {
        "artifactType": "EXPANSION_SLICE_CHECKPOINT",
        "runId": preflight["runId"],
        "sliceId": slice_record["sliceId"],
        "completedSymbols": list(slice_record["symbols"]),
        "reportPath": str(report_path),
        "reportSha256": file_hash(report_path),
        "diagnosticPath": preflight["diagnosticPath"],
        "diagnosticSha256": file_hash(Path(preflight["diagnosticPath"])),
        "scoringInputManifestPath": preflight["scoringInputManifestPath"],
        "scoringInputManifestSha256": file_hash(
            Path(preflight["scoringInputManifestPath"])
        ),
        "nextAction": "STOP_AND_RECORD_DASHBOARD_AFTER",
        "automaticContinuationAuthorized": False,
    }
    checkpoint["artifactContentHash"] = canonical_hash(checkpoint)
    write_immutable_json(Path(preflight["checkpointPath"]), checkpoint)
    print(json.dumps(checkpoint, indent=2))


def main() -> None:
    options = arguments()
    started_at = datetime.now(UTC)
    universe, _manifest, slice_record = _load_and_validate(options)
    run_id = new_run_id(started_at)
    preflight = build_slice_preflight(
        slice_record,
        dashboard_before=options.dashboard_before,
        output_directory=options.output_directory,
        run_id=run_id,
        dashboard_counter_status=options.dashboard_counter_status,
    )
    print(json.dumps(preflight, indent=2))
    if not options.execute_live:
        return
    if options.confirm_live != LIVE_CONFIRMATION:
        raise SystemExit(
            f"--execute-live requires --confirm-live {LIVE_CONFIRMATION}"
        )
    if not preflight["safeToExecute"]:
        raise SystemExit("Slice would violate the provider reserve")
    output_paths = (
        preflight["reportPath"],
        preflight["diagnosticPath"],
        preflight["checkpointPath"],
        preflight["scoringInputManifestPath"],
    )
    if any(Path(item).exists() for item in output_paths):
        raise SystemExit("Refusing to overwrite an expansion artifact")
    lock_path = options.output_directory / ".mature-gate-live.lock"
    try:
        with MatureGateRunLock(lock_path, run_id):
            _run_live(
                options,
                universe,
                slice_record,
                preflight,
                started_at,
            )
    except RuntimeError as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
