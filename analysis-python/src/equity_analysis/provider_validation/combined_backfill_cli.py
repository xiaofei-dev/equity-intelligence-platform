import argparse
import json
import os
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlparse
from urllib.request import urlopen

from equity_analysis.market_data.eodhd import EodhdProvider
from equity_analysis.provider_validation.cli import _load_local_environment
from equity_analysis.provider_validation.execution_safety import (
    ExecutionLease,
    JournaledOpener,
    PhysicalRequestJournal,
    SymbolExecutionJournal,
    repository_root_env_path,
)
from equity_analysis.provider_validation.expansion_gate import (
    FORMULA_HISTORY_REQUIREMENTS,
    FORMULA_INPUT_FIELDS,
    MINIMUM_PROVIDER_RESERVE,
    PROVIDER_DAILY_LIMIT,
    canonical_hash,
    new_run_id,
    write_immutable_json,
)
from equity_analysis.provider_validation.scoring_backfill_cli import (
    LIVE_CONFIRMATION,
    GitignoredV2Store,
    ScoringInputV2Record,
    load_v1_pit_index,
    normalize_symbol_v2,
)
from equity_analysis.provider_validation.sec_edgar import (
    SecEdgarClient,
    select_point_in_time_facts,
)
from equity_analysis.provider_validation.sec_scoring_supplement_cli import (
    METRIC_TO_FIELD,
    SecSupplementProvider,
    _is_discrete_quarter,
    _load_v2_payload,
    _sec_record,
    _trading_dates,
)

COMBINED_REPORT_VERSION = "formula-ready-combined-backfill-v1.1.0"
MAXIMUM_SLICE_SIZE = 20
FORMULA_PRICE_FIELDS = frozenset({"open", "high", "low", "close", "adjusted_close", "volume"})
FORMULA_MARKET_CAP_FIELDS = frozenset({"market_capitalization"})
EODHD_ENDPOINTS = ("fundamentals", "eod", "historical-market-cap")
SEC_ENDPOINTS = ("ticker-mapping", "submissions", "company-facts")
MINIMUM_PRICE_OBSERVATION_DATES = 1
EODHD_WEIGHTS = {"fundamentals": 10, "eod": 1, "historical-market-cap": 1}


class EodhdSupplement(Protocol):
    def fetch_financial_statements(self, symbol: str): ...

    def fetch_daily_prices(self, symbol: str, start_date: date, end_date: date): ...

    def fetch_historical_market_cap(self, symbol: str, start_date: date, end_date: date): ...


class SecSupplement(Protocol):
    def supplement_records(self, symbol: str, records): ...


def classify_physical_request(request) -> tuple[str, str, str, int]:
    parsed = urlparse(request.full_url)
    parts = tuple(part for part in parsed.path.split("/") if part)
    if "eodhd.com" in parsed.netloc:
        api_index = parts.index("api")
        endpoint = parts[api_index + 1]
        symbol = parts[api_index + 2].split(".")[0].upper()
        sanitized_query = sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query)
            if key.lower() not in {"api_token", "api_key", "token"}
        )
        identity = canonical_hash(
            {
                "provider": "eodhd",
                "endpoint": endpoint,
                "symbol": symbol,
                "query": sanitized_query,
            }
        )
        return symbol, endpoint, identity, EODHD_WEIGHTS[endpoint]
    if parts[-1] == "company_tickers.json":
        endpoint = "ticker-mapping"
        symbol = "SEC_GLOBAL"
    elif "submissions" in parts:
        endpoint = "submissions"
        symbol = parts[-1].removeprefix("CIK").removesuffix(".json")
    else:
        endpoint = "company-facts"
        symbol = parts[-1].removeprefix("CIK").removesuffix(".json")
    identity = canonical_hash({"provider": "sec_edgar", "endpoint": endpoint, "identity": symbol})
    return symbol, endpoint, identity, 1


class SecRecordsSupplement:
    def __init__(
        self,
        provider: SecSupplementProvider,
        *,
        as_of_time: datetime,
        ingested_at: datetime,
    ) -> None:
        self._provider = provider
        self._as_of_time = as_of_time
        self._ingested_at = ingested_at

    def supplement_records(self, symbol: str, records):
        trading_dates = _trading_dates(records)
        if not trading_dates:
            raise ValueError(f"No controlled trading calendar for {symbol}")
        cik, _entity_name = self._provider.lookup_cik(symbol)
        filings = self._provider.fetch_recent_filings(cik, symbol, self._as_of_time)
        company_facts = self._provider.fetch_company_facts(cik)
        selected = select_point_in_time_facts(
            company_facts,
            filings,
            trading_dates,
            self._as_of_time,
        )
        approved = tuple(
            item
            for item in selected
            if item.metric_code in METRIC_TO_FIELD and _is_discrete_quarter(item)
        )
        additions = tuple(_sec_record(symbol, cik, item, self._ingested_at) for item in approved)
        replacement_keys = {
            (item.normalized_field, item.period_type, item.fiscal_period_end) for item in additions
        }
        retained = tuple(
            item
            for item in records
            if (
                item.normalized_field,
                item.period_type,
                item.fiscal_period_end,
            )
            not in replacement_keys
        )
        return tuple(
            sorted(
                (*retained, *additions),
                key=lambda item: (
                    item.dataset,
                    item.normalized_field,
                    item.fiscal_period_end,
                    item.available_at,
                    item.content_hash,
                ),
            )
        )


def formula_coverage(records) -> dict[str, Any]:
    financial = {item.normalized_field for item in records if item.dataset == "FINANCIAL"}
    price = {item.normalized_field for item in records if item.dataset == "DAILY_PRICE"}
    market_cap = {
        item.normalized_field for item in records if item.dataset == "HISTORICAL_MARKET_CAP"
    }
    diluted_periods = {
        item.fiscal_period_end
        for item in records
        if item.dataset == "FINANCIAL"
        and item.period_type == "QUARTERLY"
        and item.normalized_field == "diluted_weighted_average_shares"
    }
    interest_periods = {
        item.fiscal_period_end
        for item in records
        if item.dataset == "FINANCIAL"
        and item.period_type == "QUARTERLY"
        and item.normalized_field == "interest_expense"
    }
    market_cap_periods = {
        item.fiscal_period_end for item in records if item.dataset == "HISTORICAL_MARKET_CAP"
    }
    price_periods = {
        item.fiscal_period_end
        for item in records
        if item.dataset == "DAILY_PRICE" and item.normalized_field == "close"
    }
    missing = sorted(
        (FORMULA_INPUT_FIELDS - (financial | market_cap))
        | (FORMULA_PRICE_FIELDS - price)
        | (FORMULA_MARKET_CAP_FIELDS - market_cap)
    )
    required_quarters = FORMULA_HISTORY_REQUIREMENTS["quarterlyFinancialPeriods"]
    required_market_caps = FORMULA_HISTORY_REQUIREMENTS["historicalValuationObservations"]
    history_complete = (
        len(diluted_periods) >= required_quarters
        and len(interest_periods) >= required_quarters
        and len(market_cap_periods) >= required_market_caps
        and len(price_periods) >= MINIMUM_PRICE_OBSERVATION_DATES
    )
    return {
        "requiredFormulaFields": sorted(FORMULA_INPUT_FIELDS),
        "presentFinancialFields": sorted(financial),
        "presentPriceFields": sorted(price),
        "presentMarketCapFields": sorted(market_cap),
        "missingFormulaFields": missing,
        "dilutedShareQuarterlyPeriods": len(diluted_periods),
        "interestExpenseQuarterlyPeriods": len(interest_periods),
        "historicalMarketCapObservations": len(market_cap_periods),
        "dailyPriceObservationDates": len(price_periods),
        "minimumDailyPriceObservationDates": MINIMUM_PRICE_OBSERVATION_DATES,
        "historyRequirements": FORMULA_HISTORY_REQUIREMENTS,
        "historyComplete": history_complete,
        "complete": not missing and history_complete,
    }


def insufficient_reason_codes(coverage: dict[str, Any]) -> list[str]:
    reasons = [
        f"MISSING_FORMULA_FIELD_{field.upper()}"
        for field in coverage["missingFormulaFields"]
    ]
    required_quarters = coverage["historyRequirements"]["quarterlyFinancialPeriods"]
    required_market_caps = coverage["historyRequirements"][
        "historicalValuationObservations"
    ]
    if coverage["dilutedShareQuarterlyPeriods"] < required_quarters:
        reasons.append(
            "DILUTED_SHARES_QUARTERS_"
            f"{coverage['dilutedShareQuarterlyPeriods']}_OF_{required_quarters}"
        )
    if coverage["interestExpenseQuarterlyPeriods"] < required_quarters:
        reasons.append(
            "INTEREST_EXPENSE_QUARTERS_"
            f"{coverage['interestExpenseQuarterlyPeriods']}_OF_{required_quarters}"
        )
    if coverage["historicalMarketCapObservations"] < required_market_caps:
        reasons.append(
            "HISTORICAL_MARKET_CAP_"
            f"{coverage['historicalMarketCapObservations']}_OF_{required_market_caps}"
        )
    if coverage["dailyPriceObservationDates"] < coverage[
        "minimumDailyPriceObservationDates"
    ]:
        reasons.append(
            "DAILY_PRICE_DATES_"
            f"{coverage['dailyPriceObservationDates']}_OF_"
            f"{coverage['minimumDailyPriceObservationDates']}"
        )
    return sorted(reasons)


def classify_symbols(
    symbols: tuple[str, ...],
    local_evidence: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    if not 1 <= len(symbols) <= MAXIMUM_SLICE_SIZE:
        raise ValueError("Combined backfill slice must contain between 1 and 20 symbols")
    if len(symbols) != len(set(symbols)):
        raise ValueError("Combined backfill symbols must be unique")
    classifications = []
    for symbol in symbols:
        evidence = local_evidence.get(symbol, {})
        value_hash = evidence.get("v2ContentHash")
        storage_exists = evidence.get("v2StorageExists") is True
        formula_complete = evidence.get("formulaCoverageComplete") is True
        sec_complete = evidence.get("secSupplementCoverageComplete") is True
        eodhd_complete = evidence.get(
            "eodhdCoverageComplete",
            bool(value_hash and storage_exists and formula_complete),
        )
        if value_hash and storage_exists and formula_complete and sec_complete:
            actions = ("SKIP",)
        else:
            actions = tuple(
                action
                for action, needed in (
                    ("NEEDS_EODHD", not eodhd_complete),
                    ("NEEDS_SEC", not sec_complete),
                )
                if needed
            )
            if not actions:
                actions = ("NEEDS_EODHD",)
        classifications.append(
            {
                "symbol": symbol,
                "actions": actions,
                "existingContentHash": value_hash,
                "formulaCoverageComplete": formula_complete,
                "secSupplementCoverageComplete": sec_complete,
            }
        )
    return tuple(classifications)


def combined_budget(classifications: tuple[dict[str, Any], ...]) -> dict[str, int]:
    eodhd = sum("NEEDS_EODHD" in item["actions"] for item in classifications)
    sec = sum("NEEDS_SEC" in item["actions"] for item in classifications)
    provisional = eodhd * 25
    return {
        "eodhdSymbolCount": eodhd,
        "secSymbolCount": sec,
        "eodhdPhysicalAttemptCeiling": eodhd * 3,
        "secPhysicalAttemptCeiling": sec * 3,
        "totalPhysicalAttemptCeiling": eodhd * 3 + sec * 3,
        "configuredLocalWeightCeiling": eodhd * 12,
        "provisionalProviderBilling": provisional,
        "providerBilledSafetyCeiling": (provisional * 3 + 1) // 2,
        "retryCeiling": 0,
    }


def apply_resume_budget(
    preflight: dict[str, Any],
    completed: dict[str, int],
) -> None:
    symbol_count = len(preflight["symbols"])
    missing_fundamentals = max(symbol_count - completed.get("fundamentals", 0), 0)
    missing_eod = max(symbol_count - completed.get("eod", 0), 0)
    missing_market_cap = max(symbol_count - completed.get("historical-market-cap", 0), 0)
    missing_sec = sum(
        max(symbol_count - completed.get(endpoint, 0), 0) for endpoint in SEC_ENDPOINTS
    )
    preflight["eodhdPhysicalAttemptCeiling"] = (
        missing_fundamentals + missing_eod + missing_market_cap
    )
    preflight["secPhysicalAttemptCeiling"] = missing_sec
    preflight["totalPhysicalAttemptCeiling"] = (
        preflight["eodhdPhysicalAttemptCeiling"] + missing_sec
    )
    preflight["configuredLocalWeightCeiling"] = (
        missing_fundamentals * 10 + missing_eod + missing_market_cap
    )
    preflight["provisionalProviderBilling"] = preflight["configuredLocalWeightCeiling"]
    preflight["providerBilledSafetyCeiling"] = (
        preflight["configuredLocalWeightCeiling"] * 3 + 1
    ) // 2
    preflight["replayedCompletedEndpoints"] = completed


def build_combined_preflight(
    *,
    slice_id: str,
    symbols: tuple[str, ...],
    local_evidence: dict[str, dict[str, Any]],
    dashboard_before: int,
    run_id: str,
    output_directory: Path,
    storage_root: Path,
) -> dict[str, Any]:
    if not 0 <= dashboard_before <= PROVIDER_DAILY_LIMIT:
        raise ValueError("Dashboard counter is outside the provider daily limit")
    classifications = classify_symbols(symbols, local_evidence)
    budget = combined_budget(classifications)
    safe_delta = PROVIDER_DAILY_LIMIT - MINIMUM_PROVIDER_RESERVE - dashboard_before
    stem = f"formula-ready-backfill-{run_id}"
    return {
        "reportVersion": COMBINED_REPORT_VERSION,
        "runId": run_id,
        "sliceId": slice_id,
        "symbols": symbols,
        "classifications": classifications,
        "eodhdEndpoints": EODHD_ENDPOINTS,
        "secEndpoints": SEC_ENDPOINTS,
        **budget,
        "dashboardBefore": dashboard_before,
        "minimumProviderReserve": MINIMUM_PROVIDER_RESERVE,
        "safeToExecute": budget["providerBilledSafetyCeiling"] <= safe_delta,
        "reportPath": str(output_directory / f"{stem}.json"),
        "manifestPath": str(output_directory / f"{stem}-manifest.json"),
        "diagnosticPath": str(output_directory / f"{stem}-diagnostics.json"),
        "checkpointDirectory": str(storage_root / "checkpoints" / run_id),
        "immutableOutputs": True,
        "singleSharedLock": True,
        "networkRequestsExecuted": False,
    }


def execute_combined(
    preflight: dict[str, Any],
    *,
    eodhd: EodhdSupplement,
    sec: SecSupplement,
    existing_pit: dict[str, dict[tuple[str, str, date], tuple[datetime, str]]],
    existing_records: dict[str, tuple[ScoringInputV2Record, ...]],
    existing_receipts: dict[str, dict[str, Any]],
    start_date: date,
    end_date: date,
    store: GitignoredV2Store,
    journal: SymbolExecutionJournal | None = None,
    explicit_verified_resume: bool = False,
) -> dict[str, Any]:
    results = []
    endpoint_calls = Counter()
    for classification in preflight["classifications"]:
        symbol = classification["symbol"]
        actions = classification["actions"]
        if journal is not None:
            resume_state, checkpoint_result = journal.resume(symbol)
            if resume_state == "UNKNOWN":
                if not explicit_verified_resume:
                    raise RuntimeError(f"UNKNOWN_SYMBOL_EXECUTION_STATE[{symbol}]")
                journal.append(
                    symbol,
                    "FAILED",
                    {"reason": "EXPLICIT_VERIFIED_ENDPOINT_RESUME"},
                )
                resume_state = "RUN"
            if resume_state == "SKIP":
                results.append(checkpoint_result)
                continue
            journal.append(
                symbol,
                "INTENT",
                {
                    "actions": actions,
                    "endpointPlanHash": canonical_hash({"symbol": symbol, "actions": actions}),
                },
            )
        if actions == ("SKIP",):
            result = {
                "symbol": symbol,
                "status": "SKIPPED_EXISTING_COMPLETE",
                "receipt": existing_receipts[symbol],
                "formulaCoverageComplete": True,
            }
            results.append(result)
            if journal is not None:
                checkpoint, content_hash = journal.checkpoint(symbol, result)
                journal.append(
                    symbol,
                    "COMPLETED",
                    {
                        "checkpointPath": str(checkpoint),
                        "checkpointHash": content_hash,
                    },
                )
            continue
        pit = existing_pit.get(symbol, {})
        if "NEEDS_EODHD" in actions:
            financials = eodhd.fetch_financial_statements(symbol)
            endpoint_calls["fundamentals"] += 1
            prices = eodhd.fetch_daily_prices(symbol, start_date, end_date)
            endpoint_calls["eod"] += 1
            market_values = eodhd.fetch_historical_market_cap(symbol, start_date, end_date)
            endpoint_calls["historical-market-cap"] += 1
            records = normalize_symbol_v2(symbol, financials, prices, market_values, pit)
        else:
            records = existing_records.get(symbol, ())
            if not records:
                raise ValueError("SEC-only supplement requires controlled v2 records")
        if "NEEDS_SEC" in actions:
            records = sec.supplement_records(symbol, records)
            endpoint_calls.update(SEC_ENDPOINTS)
        coverage = formula_coverage(records)
        if not coverage["complete"]:
            result = {
                "symbol": symbol,
                "status": "SECURITY_INSUFFICIENT_DATA",
                "reasonCodes": insufficient_reason_codes(coverage),
                "formulaCoverage": coverage,
            }
            results.append(result)
            if journal is not None:
                checkpoint, content_hash = journal.checkpoint(symbol, result)
                journal.append(
                    symbol,
                    "COMPLETED",
                    {
                        "checkpointPath": str(checkpoint),
                        "checkpointHash": content_hash,
                        "terminalStatus": "SECURITY_INSUFFICIENT_DATA",
                    },
                )
            continue
        receipt = store.persist(symbol, records)
        result = {
            "symbol": symbol,
            "status": "FORMULA_READY",
            "receipt": receipt,
            "formulaCoverage": coverage,
        }
        results.append(result)
        if journal is not None:
            checkpoint, content_hash = journal.checkpoint(symbol, result)
            journal.append(
                symbol,
                "COMPLETED",
                {
                    "checkpointPath": str(checkpoint),
                    "checkpointHash": content_hash,
                },
            )
    system_success = all(
        item["status"]
        in {
            "SKIPPED_EXISTING_COMPLETE",
            "FORMULA_READY",
            "SECURITY_INSUFFICIENT_DATA",
        }
        for item in results
    )
    has_insufficient = any(
        item["status"] == "SECURITY_INSUFFICIENT_DATA" for item in results
    )
    payload = {
        "reportVersion": COMBINED_REPORT_VERSION,
        "runId": preflight["runId"],
        "sliceId": preflight["sliceId"],
        "status": (
            "COMPLETE_WITH_INSUFFICIENT_DATA"
            if system_success and has_insufficient
            else ("PASS" if system_success else "SYSTEM_EXECUTION_FAIL")
        ),
        "results": results,
        "logicalEndpointEvaluations": dict(sorted(endpoint_calls.items())),
        "replayedCompletedEndpoints": dict(
            sorted(preflight.get("replayedCompletedEndpoints", {}).items())
        ),
        "formulaExecuted": False,
        "networkRetries": 0,
    }
    return {**payload, "artifactContentHash": canonical_hash(payload)}


def write_combined_artifacts(
    preflight: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, str]:
    checkpoints = Path(preflight["checkpointDirectory"])
    for index, result in enumerate(report["results"], start=1):
        checkpoint = {
            "runId": report["runId"],
            "sliceId": report["sliceId"],
            "sequence": index,
            "symbol": result["symbol"],
            "status": result["status"],
            "resultHash": canonical_hash(result),
        }
        write_immutable_json(
            checkpoints / f"{index:04d}-{result['symbol']}.json",
            checkpoint,
        )
    write_immutable_json(Path(preflight["reportPath"]), report)
    manifest = {
        "artifactType": "FORMULA_READY_BACKFILL_GIT_SAFE_MANIFEST",
        "runId": report["runId"],
        "sliceId": report["sliceId"],
        "reportContentHash": report["artifactContentHash"],
        "licensedValuesIncluded": False,
        "results": [
            {
                "symbol": item["symbol"],
                "status": item["status"],
                "receipt": item.get("receipt"),
                "formulaCoverageComplete": (
                    item.get("formulaCoverageComplete")
                    or item.get("formulaCoverage", {}).get("complete", False)
                ),
            }
            for item in report["results"]
        ],
    }
    manifest["artifactContentHash"] = canonical_hash(manifest)
    write_immutable_json(Path(preflight["manifestPath"]), manifest)
    diagnostics = {
        "artifactType": "FORMULA_READY_BACKFILL_DIAGNOSTICS",
        "runId": report["runId"],
        "failures": [
            {
                "symbol": item["symbol"],
                "status": item["status"],
                "reasonCodes": item.get("reasonCodes", []),
                "missingFormulaFields": item.get("formulaCoverage", {}).get(
                    "missingFormulaFields", []
                ),
            }
            for item in report["results"]
            if item["status"]
            in {"SECURITY_INSUFFICIENT_DATA", "SYSTEM_EXECUTION_FAIL"}
        ],
        "rawProviderPayloadsIncluded": False,
        "credentialsIncluded": False,
    }
    diagnostics["artifactContentHash"] = canonical_hash(diagnostics)
    write_immutable_json(Path(preflight["diagnosticPath"]), diagnostics)
    return {
        "reportPath": preflight["reportPath"],
        "manifestPath": preflight["manifestPath"],
        "diagnosticPath": preflight["diagnosticPath"],
    }


def write_preflight_failure(
    preflight: dict[str, Any],
    *,
    error_code: str,
) -> Path:
    payload = {
        "artifactType": "FORMULA_READY_BACKFILL_PREFLIGHT_FAILURE",
        "schemaVersion": "formula-ready-preflight-failure-v1.0.0",
        "runId": preflight["runId"],
        "sliceId": preflight["sliceId"],
        "symbols": preflight["symbols"],
        "errorCode": error_code,
        "networkRequestsExecuted": False,
        "credentialsIncluded": False,
        "licensedValuesIncluded": False,
    }
    payload["artifactContentHash"] = canonical_hash(payload)
    output = Path(preflight["reportPath"]).with_name(
        f"formula-ready-backfill-{preflight['runId']}-preflight-failure.json"
    )
    write_immutable_json(output, payload)
    return output


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan a bounded combined formula-ready backfill slice."
    )
    parser.add_argument("--frozen-slice", type=Path, required=True)
    parser.add_argument("--local-evidence", type=Path, required=True)
    parser.add_argument(
        "--v1-payload-directory",
        type=Path,
        help=(
            "Controlled gitignored v1 root containing <symbol>/*.json payloads. "
            "Discovered paths are merged with local-evidence v1PayloadPaths."
        ),
    )
    parser.add_argument("--dashboard-before", type=int, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--as-of-time", type=datetime.fromisoformat, required=True)
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--confirm-live", choices=(LIVE_CONFIRMATION,))
    parser.add_argument(
        "--resume-run-id",
        help="Explicitly resume one verified existing run journal without creating a new run ID.",
    )
    return parser.parse_args()


def load_controlled_evidence(
    symbols: tuple[str, ...],
    evidence: dict[str, dict[str, Any]],
) -> tuple[
    dict[str, dict[tuple[str, str, date], tuple[datetime, str]]],
    dict[str, tuple[ScoringInputV2Record, ...]],
    dict[str, dict[str, Any]],
]:
    pit = {}
    records = {}
    receipts = {}
    for symbol in symbols:
        item = evidence.get(symbol, {})
        v1_paths = tuple(Path(value) for value in item.get("v1PayloadPaths", ()))
        pit[symbol] = {
            key: value for key, value in load_v1_pit_index(v1_paths).items() if key[0] == symbol
        }
        v2_path = item.get("v2PayloadPath")
        if v2_path:
            _payload, loaded = _load_v2_payload(Path(v2_path), symbol)
            records[symbol] = loaded
        if item.get("v2Receipt"):
            receipts[symbol] = item["v2Receipt"]
    return pit, records, receipts


def run_live_wired(
    *,
    preflight: dict[str, Any],
    local_evidence: dict[str, dict[str, Any]],
    eodhd: EodhdSupplement,
    sec: SecSupplement,
    start_date: date,
    end_date: date,
    storage_root: Path,
    acquire_lock: bool = True,
    explicit_verified_resume: bool = False,
    physical_telemetry: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pit, records, receipts = load_controlled_evidence(tuple(preflight["symbols"]), local_evidence)
    store = GitignoredV2Store(storage_root)

    def execute() -> dict[str, Any]:
        journal = SymbolExecutionJournal(storage_root / "journals", preflight["runId"])
        report = execute_combined(
            preflight,
            eodhd=eodhd,
            sec=sec,
            existing_pit=pit,
            existing_records=records,
            existing_receipts=receipts,
            start_date=start_date,
            end_date=end_date,
            store=store,
            journal=journal,
            explicit_verified_resume=explicit_verified_resume,
        )
        report_without_hash = {
            key: value for key, value in report.items() if key != "artifactContentHash"
        }
        report_without_hash["newPhysicalAttempts"] = (
            physical_telemetry() if physical_telemetry is not None else {"status": "NOT_RECORDED"}
        )
        report = {
            **report_without_hash,
            "artifactContentHash": canonical_hash(report_without_hash),
        }
        write_combined_artifacts(preflight, report)
        return report

    if acquire_lock:
        lock_path = storage_root / ".formula-ready-backfill.lock"
        with ExecutionLease(lock_path, preflight["runId"]):
            return execute()
    return execute()


def main() -> None:
    arguments = _arguments()
    frozen = json.loads(arguments.frozen_slice.read_text(encoding="utf-8"))
    if frozen["contentHash"] != canonical_hash(
        {key: value for key, value in frozen.items() if key != "contentHash"}
    ):
        raise SystemExit("Frozen slice hash mismatch")
    local_evidence_artifact = json.loads(
        arguments.local_evidence.read_text(encoding="utf-8")
    )
    artifact_hash = local_evidence_artifact.get("artifactContentHash")
    if artifact_hash is not None and artifact_hash != canonical_hash(
        {
            key: value
            for key, value in local_evidence_artifact.items()
            if key != "artifactContentHash"
        }
    ):
        raise SystemExit("Local evidence artifact hash mismatch")
    local_evidence = local_evidence_artifact.get(
        "records",
        local_evidence_artifact,
    )
    if arguments.v1_payload_directory:
        for symbol in frozen["symbols"]:
            discovered = sorted(arguments.v1_payload_directory.glob(f"{symbol}/*.json"))
            entry = local_evidence.setdefault(symbol, {})
            entry["v1PayloadPaths"] = sorted(
                {
                    *entry.get("v1PayloadPaths", ()),
                    *(str(path) for path in discovered),
                }
            )
    run_id = arguments.resume_run_id or new_run_id()
    preflight = build_combined_preflight(
        slice_id=frozen["sliceId"],
        symbols=tuple(frozen["symbols"]),
        local_evidence=local_evidence,
        dashboard_before=arguments.dashboard_before,
        run_id=run_id,
        output_directory=arguments.output_directory,
        storage_root=arguments.storage_root,
    )
    if arguments.resume_run_id:
        dry_resume_journal = PhysicalRequestJournal(
            arguments.storage_root / "physical-request-journals",
            run_id,
        )
        dry_completed = dry_resume_journal.resume_preflight(
            {"sliceId": preflight["sliceId"], "symbols": preflight["symbols"]},
            append_event=False,
        )
        apply_resume_budget(preflight, dry_completed)
        preflight["resumeRunId"] = run_id
        preflight["resumeCompatibilityModes"] = list(dry_resume_journal.last_resume_compatibility)
    if not arguments.execute_live:
        print(json.dumps(preflight, indent=2))
        return
    if arguments.confirm_live != LIVE_CONFIRMATION:
        raise SystemExit(f"--execute-live requires --confirm-live {LIVE_CONFIRMATION}")
    if not preflight["safeToExecute"]:
        raise SystemExit("Combined slice would consume the provider safety reserve")
    environment = _load_local_environment(repository_root_env_path())
    api_key = os.environ.get("EODHD_API_KEY") or environment.get("EODHD_API_KEY", "")
    user_agent = os.environ.get("SEC_USER_AGENT") or environment.get("SEC_USER_AGENT", "")
    if not api_key or not user_agent:
        failure_path = write_preflight_failure(
            preflight,
            error_code="MISSING_EODHD_API_KEY_OR_SEC_USER_AGENT",
        )
        raise SystemExit(
            f"EODHD_API_KEY and SEC_USER_AGENT are required; failure artifact: {failure_path}"
        )
    physical_journal = PhysicalRequestJournal(
        arguments.storage_root / "physical-request-journals",
        run_id,
    )
    lease_owner = f"{run_id}:resume:{new_run_id()}" if arguments.resume_run_id else run_id
    lease = ExecutionLease(
        arguments.storage_root / ".formula-ready-backfill.lock",
        lease_owner,
    )
    lease.acquire()
    try:
        completed = (
            physical_journal.resume_preflight(
                {"sliceId": preflight["sliceId"], "symbols": preflight["symbols"]}
            )
            if arguments.resume_run_id
            else None
        )
    except BaseException:
        lease.release()
        raise
    if completed is not None:
        apply_resume_budget(preflight, completed)
        preflight["resumeRunId"] = run_id
        preflight["resumeCompatibilityModes"] = list(physical_journal.last_resume_compatibility)
    print(json.dumps(preflight, indent=2))
    eodhd_opener = JournaledOpener(
        urlopen,
        physical_journal,
        request_classifier=classify_physical_request,
        physical_attempt_ceiling=preflight["eodhdPhysicalAttemptCeiling"],
        configured_weight_ceiling=preflight["configuredLocalWeightCeiling"],
    )
    sec_opener = JournaledOpener(
        urlopen,
        physical_journal,
        request_classifier=classify_physical_request,
        physical_attempt_ceiling=preflight["secPhysicalAttemptCeiling"],
        configured_weight_ceiling=preflight["secPhysicalAttemptCeiling"],
    )
    eodhd = EodhdProvider(
        api_key=api_key,
        max_retries=0,
        opener=eodhd_opener,
    )
    sec_client = SecEdgarClient(
        user_agent=user_agent,
        opener=sec_opener,
    )
    sec = SecRecordsSupplement(
        sec_client,
        as_of_time=arguments.as_of_time,
        ingested_at=datetime.now(arguments.as_of_time.tzinfo),
    )
    preflight_journaled = False
    try:
        if not arguments.resume_run_id:
            physical_journal.preflight(
                {
                    "sliceId": preflight["sliceId"],
                    "symbols": preflight["symbols"],
                    "eodhdAttemptCeiling": preflight["eodhdPhysicalAttemptCeiling"],
                    "secAttemptCeiling": preflight["secPhysicalAttemptCeiling"],
                    "configuredLocalWeightCeiling": preflight["configuredLocalWeightCeiling"],
                }
            )
        preflight_journaled = True
        report = run_live_wired(
            preflight=preflight,
            local_evidence=local_evidence,
            eodhd=eodhd,
            sec=sec,
            start_date=arguments.start_date,
            end_date=arguments.end_date,
            storage_root=arguments.storage_root,
            acquire_lock=False,
            explicit_verified_resume=bool(arguments.resume_run_id),
            physical_telemetry=lambda: {
                "eodhd": eodhd_opener.physical_attempts_by_endpoint,
                "sec": sec_opener.physical_attempts_by_endpoint,
                "eodhdTotal": eodhd_opener.physical_attempts,
                "secTotal": sec_opener.physical_attempts,
                "total": (eodhd_opener.physical_attempts + sec_opener.physical_attempts),
            },
        )
        physical_journal.finalize(
            "COMPLETE",
            {
                "status": report["status"],
                "eodhdPhysicalAttempts": eodhd_opener.physical_attempts,
                "secPhysicalAttempts": sec_opener.physical_attempts,
            },
        )
    except BaseException as error:
        if preflight_journaled:
            physical_journal.finalize("ABORTED", {"sanitizedReason": type(error).__name__.upper()})
        raise
    finally:
        lease.release()
    if report["status"] == "SYSTEM_EXECUTION_FAIL":
        raise SystemExit("Combined formula-ready backfill system execution failed")


if __name__ == "__main__":
    main()
