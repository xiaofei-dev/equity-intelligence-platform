import argparse
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from equity_analysis.market_data.eodhd import EodhdProvider
from equity_analysis.market_data.provider import MarketDataProviderError
from equity_analysis.provider_validation.cli import _load_local_environment
from equity_analysis.provider_validation.execution_safety import (
    repository_root_env_path,
)
from equity_analysis.provider_validation.mature_gate import (
    LIVE_ENDPOINTS,
    EodhdCallBudget,
    GateEvidenceLedger,
    MatureGateRunLock,
    MatureGateUniverse,
    attach_sec_availability,
    build_report,
    evaluate_candidate,
    normalized_payload_hash,
    pit_period_diagnostics,
    plan_reproducibility,
    projected_live_cost,
    required_field_diagnostic,
    sec_availability_by_period,
)
from equity_analysis.provider_validation.models import (
    GateStatus,
    MatureGateSecurityResult,
    ProviderGateDiagnosticArtifact,
    ProviderGateSecurityDiagnostic,
    SecFailureDiagnostic,
)
from equity_analysis.provider_validation.sec_edgar import (
    SecEdgarClient,
    SecEdgarError,
    select_point_in_time_facts_with_diagnostics,
)

ANALYSIS_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = ANALYSIS_ROOT.parent
DEFAULT_FIXTURE = (
    ANALYSIS_ROOT / "tests" / "fixtures" / "provider_acceptance_universe_v3.json"
)
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "docs" / "generated"
LIVE_CONFIRMATION = "I_CONFIRM_BOUNDED_LIVE_REQUESTS"
DIAGNOSTIC_SCHEMA_VERSION = "provider-gate-diagnostics-v1.0.0"
FOCUSED_RETEST_SYMBOLS = ("NVDA", "EXPO", "VZ", "LANC", "TXN")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the bounded 100-security mature-company data gate."
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2020, 1, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    selection_group = parser.add_mutually_exclusive_group()
    selection_group.add_argument(
        "--maximum-symbols",
        type=int,
        help="Limit the named universe for a bounded canary. Must be between 1 and 120.",
    )
    selection_group.add_argument(
        "--symbols",
        nargs="+",
        help="Explicit fixture symbols for a bounded canary, in execution order.",
    )
    parser.add_argument(
        "--reproducibility-sample-size",
        type=int,
        default=5,
        help="Second network pass sample size. Must be between 0 and 5.",
    )
    parser.add_argument(
        "--execute-live",
        action="store_true",
        help="Authorize bounded EODHD and SEC requests. Without this flag, validate only.",
    )
    parser.add_argument(
        "--confirm-live",
        choices=(LIVE_CONFIRMATION,),
        help=f"Required with --execute-live. Exact value: {LIVE_CONFIRMATION}",
    )
    parser.add_argument(
        "--dashboard-before",
        type=int,
        help="Exact EODHD dashboard counter recorded before a live run.",
    )
    return parser.parse_args()


def _failed_result(candidate, reason: str) -> MatureGateSecurityResult:
    return MatureGateSecurityResult(
        symbol=candidate.symbol,
        sector=candidate.sector,
        candidate_role=candidate.candidate_role,
        status=GateStatus.FAIL,
        reason_codes=(reason,),
        field_coverage={},
    )


def _sanitized_failure_reason(error: Exception) -> str:
    if isinstance(error, MarketDataProviderError):
        return f"EODHD_{error.code}"
    if isinstance(error, SecEdgarError):
        if error.code == "SEC_REQUEST_FAILED" and "HTTP " in str(error):
            return f"SEC_EDGAR_HTTP_{str(error).rsplit('HTTP ', 1)[1]}"
        return error.code
    if isinstance(error, RuntimeError):
        return str(error) if str(error).isupper() else "GATE_RUNTIME_ERROR"
    return "NORMALIZATION_VALUE_ERROR"


def _run_id(started_at: datetime) -> str:
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid4().hex[:12]}"


def _output_path(output_directory: Path, run_id: str) -> Path:
    return output_directory / f"mature-company-data-gate-{run_id}.json"


def _diagnostic_output_path(output_directory: Path, run_id: str) -> Path:
    return output_directory / f"mature-company-data-gate-{run_id}-diagnostics.json"


def _write_immutable_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.write("\n")


def _provider_payload_hash(financials, prices, actions, market_values) -> str:
    return normalized_payload_hash(
        {
            "financialContent": [item.content_hash for item in financials],
            "prices": prices.content_hash,
            "actions": [
                {
                    "type": item.action_type,
                    "date": item.effective_date,
                    "amount": item.amount,
                    "currency": item.currency,
                    "splitFrom": item.split_from,
                    "splitTo": item.split_to,
                }
                for item in actions.actions
            ],
            "marketValueContent": [item.content_hash for item in market_values],
        }
    )


def _validate_candidate(
    candidate,
    provider,
    sec,
    ledger,
    start_date: date,
    end_date: date,
    normalized_observer=None,
):
    financials = provider.fetch_financial_statements(candidate.symbol)
    prices = provider.fetch_daily_prices(candidate.symbol, start_date, end_date)
    actions = provider.fetch_corporate_actions(candidate.symbol, start_date, end_date)
    market_values = provider.fetch_historical_market_cap(
        candidate.symbol, start_date, end_date
    )
    cik = candidate.cik or sec.lookup_cik(candidate.symbol)[0]
    as_of_time = datetime.combine(end_date, datetime.max.time(), tzinfo=UTC)
    filings = sec.fetch_recent_filings(cik, candidate.symbol, as_of_time)
    facts = sec.fetch_company_facts(cik)
    selection = select_point_in_time_facts_with_diagnostics(
        facts,
        filings,
        tuple(item.trading_date for item in prices.bars),
        as_of_time,
    )
    selected_facts = selection.facts
    availability = sec_availability_by_period(
        facts,
        filings,
        tuple(item.trading_date for item in prices.bars),
        as_of_time,
    )
    financials = attach_sec_availability(financials, availability)
    payload_hash = _provider_payload_hash(financials, prices, actions, market_values)
    ledger.record(f"mature-gate:{candidate.symbol}", payload_hash)
    result = evaluate_candidate(
        candidate,
        financials,
        market_values,
        {
            "identity": prices.security.symbol == candidate.symbol,
            "activeStatus": (end_date - prices.bars[-1].trading_date).days <= 7,
            "dailyPrice": bool(prices.bars),
            "adjustedPrice": all(item.adjusted_close is not None for item in prices.bars),
            "dividends": True,
            "splits": True,
            "idempotentRerun": True,
        },
    )
    sec_failure_items = [
        SecFailureDiagnostic(
            code="SEC_UNSUPPORTED_FORM",
            endpoint_category="submissions",
            detail=form,
        )
        for form in sec.last_unsupported_forms
    ]
    if not filings:
        sec_failure_items.append(
            SecFailureDiagnostic(
                code="SEC_NO_ELIGIBLE_FILING_BEFORE_AS_OF",
                endpoint_category="submissions",
            )
        )
    eligible_accessions = {item.accession_number for item in filings}
    observed_accessions = {
        str(item.get("accn"))
        for fact in facts.get("facts", {}).get("us-gaap", {}).values()
        for unit_values in fact.get("units", {}).values()
        for item in unit_values
        if item.get("accn")
    }
    if not selected_facts and observed_accessions - eligible_accessions:
        sec_failure_items.append(
            SecFailureDiagnostic(
                code="SEC_ACCESSION_MISMATCH",
                endpoint_category="company_facts",
            )
        )
    pit_diagnostic_items = pit_period_diagnostics(financials, selected_facts)
    if any(
        item.match_status == "OUTSIDE_SEVEN_DAYS"
        for item in pit_diagnostic_items
    ):
        sec_failure_items.append(
            SecFailureDiagnostic(
                code="SEC_PERIOD_MISMATCH",
                endpoint_category="company_facts",
            )
        )
    diagnostic = ProviderGateSecurityDiagnostic(
        symbol=candidate.symbol,
        provider_symbol=(
            financials[0].provider_symbol if financials else provider.map_symbol(candidate.symbol)
        ),
        provider_schema_version=(
            financials[0].provider_schema_version
            if financials
            else provider.descriptor.provider_schema_version
        ),
        parser_version=(
            financials[0].parser_version
            if financials
            else provider.descriptor.parser_version
        ),
        source_hashes=tuple(sorted({item.content_hash for item in financials})),
        required_fields=required_field_diagnostic(financials),
        financial_records=provider.financial_diagnostics(candidate.symbol),
        pit_periods=pit_diagnostic_items,
        sec_failures=tuple(sec_failure_items),
        sec_availability_exclusions=selection.availability_exclusions,
    )
    if normalized_observer is not None:
        normalized_observer(financials, diagnostic)
    return result, payload_hash, diagnostic


def _rerun_candidate(candidate, provider, start_date: date, end_date: date) -> str:
    financials = provider.fetch_financial_statements(candidate.symbol)
    prices = provider.fetch_daily_prices(candidate.symbol, start_date, end_date)
    actions = provider.fetch_corporate_actions(candidate.symbol, start_date, end_date)
    market_values = provider.fetch_historical_market_cap(
        candidate.symbol, start_date, end_date
    )
    return _provider_payload_hash(financials, prices, actions, market_values)


def _execute_live(
    arguments,
    universe,
    selected_candidates,
    started_at,
    output_path,
    diagnostic_output_path,
):
    local_environment = _load_local_environment(repository_root_env_path())
    api_key = os.getenv("EODHD_API_KEY") or local_environment.get("EODHD_API_KEY", "")
    user_agent = os.getenv("SEC_USER_AGENT") or local_environment.get("SEC_USER_AGENT", "")
    if not api_key:
        raise SystemExit("EODHD_API_KEY is required for --execute-live")
    if not user_agent:
        raise SystemExit("SEC_USER_AGENT is required for --execute-live")

    rerun_sample_size = min(
        arguments.reproducibility_sample_size,
        len(selected_candidates),
    )
    cost = projected_live_cost(len(selected_candidates), rerun_sample_size)
    budget = EodhdCallBudget(
        weighted_call_ceiling=cost["weightedEodhdCallCeiling"],
        request_ceiling=cost["eodhdAttemptCeiling"],
    )
    provider = EodhdProvider(
        api_key=api_key,
        request_observer=budget.record,
        request_authorizer=budget.reserve,
    )
    sec_metrics = []
    sec = SecEdgarClient(user_agent=user_agent, request_observer=sec_metrics.append)
    ledger = GateEvidenceLedger()
    results: list[MatureGateSecurityResult] = []
    first_run_hashes: dict[str, str] = {}
    diagnostics: list[ProviderGateSecurityDiagnostic] = []

    for candidate in selected_candidates:
        try:
            result, payload_hash, diagnostic = _validate_candidate(
                candidate,
                provider,
                sec,
                ledger,
                arguments.start_date,
                arguments.end_date,
            )
            first_run_hashes[candidate.symbol] = payload_hash
            diagnostics.append(diagnostic)
        except (
            MarketDataProviderError,
            SecEdgarError,
            RuntimeError,
            ValueError,
        ) as error:
            result = _failed_result(candidate, _sanitized_failure_reason(error))
            diagnostics.append(
                ProviderGateSecurityDiagnostic(
                    symbol=candidate.symbol,
                    sec_failures=(
                        SecFailureDiagnostic(
                            code=_sanitized_failure_reason(error),
                            endpoint_category=(
                                error.endpoint_category
                                if isinstance(error, SecEdgarError)
                                else "eodhd"
                            ),
                        ),
                    ),
                )
            )
        results.append(result)

    rerun_provider = EodhdProvider(
        api_key=api_key,
        request_observer=budget.record,
        request_authorizer=budget.reserve,
    )
    reproducibility_plan = plan_reproducibility(
        tuple(
            item.symbol
            for item in results
            if item.status == GateStatus.PASS
        ),
        rerun_sample_size,
    )
    updated_results: list[MatureGateSecurityResult] = []
    for result in results:
        if result.status != GateStatus.PASS:
            updated_results.append(result)
            continue
        candidate = next(item for item in selected_candidates if item.symbol == result.symbol)
        if reproducibility_plan[result.symbol] == "IMMUTABLE_PAYLOAD_REPLAY":
            replay_status, _revision = ledger.record(
                f"mature-gate:{candidate.symbol}",
                first_run_hashes[candidate.symbol],
            )
            if replay_status != "UNCHANGED":
                result = result.model_copy(
                    update={
                        "status": GateStatus.PARTIAL,
                        "reason_codes": (
                            *result.reason_codes,
                            "PERSISTENCE_REPLAY_CHANGED",
                        ),
                    }
                )
            updated_results.append(result)
            continue
        try:
            rerun_hash = _rerun_candidate(
                candidate,
                rerun_provider,
                arguments.start_date,
                arguments.end_date,
            )
            if rerun_hash == first_run_hashes[candidate.symbol]:
                ledger.record(f"mature-gate:{candidate.symbol}", rerun_hash)
                coverage = {**result.field_coverage, "idempotentRerun": True}
                result = result.model_copy(update={"field_coverage": coverage})
            else:
                result = result.model_copy(
                    update={
                        "status": GateStatus.PARTIAL,
                        "reason_codes": (*result.reason_codes, "RERUN_CONTENT_CHANGED"),
                    }
                )
        except (MarketDataProviderError, RuntimeError, ValueError) as error:
            result = result.model_copy(
                update={
                    "status": GateStatus.PARTIAL,
                    "reason_codes": (
                        *result.reason_codes,
                        f"RERUN_{_sanitized_failure_reason(error)}",
                    ),
                }
            )
        updated_results.append(result)

    report = build_report(
        universe,
        tuple(updated_results),
        (*budget.metrics, *sec_metrics),
        started_at=started_at,
        run_id=output_path.stem.removeprefix("mature-company-data-gate-"),
        observed_provider_dashboard_before=arguments.dashboard_before,
    )
    _write_immutable_report(output_path, report.model_dump_json(indent=2))
    approved_budgets = {
        "eodhdHttpAttempts": cost["eodhdAttemptCeiling"],
        "secHttpAttempts": cost["secHttpRequests"],
        "configuredLocalWeight": cost["configuredLocalWeightedCalls"],
        "provisionalProviderBilling": cost["observedProvisionalProviderCalls"],
        "providerBilledSafetyCeiling": cost["billingSafetyBudget"],
    }
    artifact_without_hash = {
        "diagnosticSchemaVersion": DIAGNOSTIC_SCHEMA_VERSION,
        "runId": report.run_id,
        "generatedAt": report.generated_at,
        "gateReportReference": output_path.name,
        "selectedSymbols": tuple(item.symbol for item in selected_candidates),
        "approvedBudgets": approved_budgets,
        "securities": tuple(diagnostics),
        "rawProviderValuesIncluded": False,
        "credentialsIncluded": False,
    }
    diagnostic_artifact = ProviderGateDiagnosticArtifact.model_validate(
        {
            **artifact_without_hash,
            "artifactContentHash": normalized_payload_hash(artifact_without_hash),
        }
    )
    _write_immutable_report(
        diagnostic_output_path,
        diagnostic_artifact.model_dump_json(indent=2),
    )
    print(
        json.dumps(
            {
                "runId": output_path.stem.removeprefix("mature-company-data-gate-"),
                "output": str(output_path),
                "diagnosticOutput": str(diagnostic_output_path),
                "qualifiedCompanyGate": report.qualified_company_gate,
                "scoreableCandidateCount": report.scoreable_candidate_count,
                "requestMetricCount": len(report.request_metrics),
                "physicalHttpAttemptCount": report.physical_http_attempt_count,
                "configuredLocalWeightedCalls": report.configured_local_weighted_calls,
                "observedProviderDashboardDelta": (
                    report.observed_provider_dashboard_delta
                ),
                "observedProviderDashboardBefore": (
                    report.observed_provider_dashboard_before
                ),
                "providerBillingReconciliation": (
                    report.provider_billing_reconciliation
                ),
                "durationSeconds": str(report.duration_seconds),
            },
            indent=2,
            default=str,
        )
    )


def main() -> None:
    started_at = datetime.now(UTC)
    arguments = _arguments()
    universe = MatureGateUniverse.model_validate_json(
        arguments.fixture.read_text(encoding="utf-8")
    )
    universe.validate_composition()
    candidates_by_symbol = {item.symbol.upper(): item for item in universe.candidates}
    if arguments.symbols:
        requested_symbols = tuple(symbol.strip().upper() for symbol in arguments.symbols)
        if len(set(requested_symbols)) != len(requested_symbols):
            raise SystemExit("--symbols must not contain duplicates")
        missing_symbols = [
            symbol for symbol in requested_symbols if symbol not in candidates_by_symbol
        ]
        if missing_symbols:
            raise SystemExit(
                "--symbols contains symbols outside the named universe: "
                + ", ".join(missing_symbols)
            )
        selected_candidates = tuple(candidates_by_symbol[symbol] for symbol in requested_symbols)
    else:
        maximum_symbols = arguments.maximum_symbols or len(universe.candidates)
        if not 1 <= maximum_symbols <= len(universe.candidates):
            raise SystemExit("--maximum-symbols must be between 1 and 120")
        selected_candidates = universe.candidates[:maximum_symbols]
    if not 0 <= arguments.reproducibility_sample_size <= 5:
        raise SystemExit("--reproducibility-sample-size must be between 0 and 5")
    focused_retest = tuple(item.symbol for item in selected_candidates) == FOCUSED_RETEST_SYMBOLS
    rerun_sample_size = min(
        arguments.reproducibility_sample_size,
        len(selected_candidates),
    )
    if focused_retest:
        rerun_sample_size = 0
    run_id = _run_id(started_at)
    output_path = _output_path(arguments.output_directory, run_id)
    diagnostic_output_path = _diagnostic_output_path(arguments.output_directory, run_id)
    projected_cost = projected_live_cost(
        len(selected_candidates),
        rerun_sample_size,
    )
    preflight = {
        "universeVersion": universe.universe_version,
        "symbols": [item.symbol for item in selected_candidates],
        "symbolCount": len(selected_candidates),
        "endpoints": LIVE_ENDPOINTS,
        "locallyProjectedCostUsingConfiguredWeights": projected_cost,
        "runId": run_id,
        "output": str(output_path),
        "diagnosticOutput": str(diagnostic_output_path),
        "immutableOutputs": True,
        "providerBillingReconciled": False,
        "dashboardBefore": arguments.dashboard_before,
        "liveRequestsExecuted": False,
    }
    if not arguments.execute_live:
        print(json.dumps(preflight, indent=2))
        return
    if arguments.confirm_live != LIVE_CONFIRMATION:
        raise SystemExit(
            "--execute-live requires "
            f"--confirm-live {LIVE_CONFIRMATION}"
        )
    if arguments.dashboard_before is not None and arguments.dashboard_before < 0:
        raise SystemExit("--dashboard-before must be non-negative when provided")

    if output_path.exists() or diagnostic_output_path.exists():
        raise SystemExit("Refusing to overwrite an existing mature-gate artifact")
    lock_path = arguments.output_directory / ".mature-gate-live.lock"
    try:
        with MatureGateRunLock(lock_path, run_id):
            print(
                json.dumps(
                    {**preflight, "runId": run_id, "output": str(output_path)},
                    indent=2,
                )
            )
            _execute_live(
                arguments,
                universe,
                selected_candidates,
                started_at,
                output_path,
                diagnostic_output_path,
            )
    except RuntimeError as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
