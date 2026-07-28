import argparse
import json
import os
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field, model_validator

from equity_analysis.market_data.eodhd import EodhdProvider
from equity_analysis.provider_validation.cli import _load_local_environment
from equity_analysis.provider_validation.expansion_gate import (
    FORMULA_HISTORY_REQUIREMENTS,
    FORMULA_INPUT_FIELDS,
    MINIMUM_PROVIDER_RESERVE,
    PROVIDER_DAILY_LIMIT,
    canonical_hash,
    file_hash,
    new_run_id,
    write_immutable_json,
)
from equity_analysis.provider_validation.mature_gate import (
    EodhdCallBudget,
    MatureGateRunLock,
)
from equity_analysis.provider_validation.models import (
    HistoricalMarketValueObservation,
    NormalizedFinancialObservation,
    ValidationModel,
)

V2_CONTRACT_VERSION = "provider-neutral-scoring-input-v2.0.0"
V1_CONTRACT_VERSION = "provider-neutral-scoring-input-v1.0.0"
V2_REPORT_VERSION = "formula-scoring-backfill-v1.0.0"
LIVE_CONFIRMATION = "I_CONFIRM_BOUNDED_SCORING_INPUT_BACKFILL"
ALLOWED_ENDPOINTS = ("fundamentals", "eod", "historical-market-cap")
WEIGHT_PER_SYMBOL = 12
PHYSICAL_ATTEMPTS_PER_SYMBOL = 3
PROVISIONAL_BILLING_PER_SYMBOL = 25
SAFETY_MULTIPLIER = Decimal("1.5")
DEFAULT_STORAGE = Path("storage/provider-validation/scoring-inputs-v2")
DEFAULT_OUTPUT = Path("docs/generated")


class ScoringInputV2Record(ValidationModel):
    symbol: str
    provider_symbol: str
    dataset: str
    normalized_field: str
    value: Decimal
    unit: str
    currency: str | None = None
    period_type: str
    fiscal_period_end: date
    effective_at: datetime
    available_at: datetime
    ingested_at: datetime
    source_reference: str
    provider_code: str
    provider_schema_version: str
    parser_version: str
    normalization_version: str = V2_CONTRACT_VERSION
    source_content_hash: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    accession_number: str | None = None
    content_hash: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_lineage(self) -> "ScoringInputV2Record":
        if self.available_at > self.ingested_at:
            raise ValueError("availableAt cannot be later than ingestedAt")
        if self.effective_at > self.available_at:
            raise ValueError("Future observation cannot precede its availability")
        if self.effective_at.date() != self.fiscal_period_end:
            raise ValueError("Fiscal period end must match effectiveAt")
        if self.dataset == "FINANCIAL" and not self.accession_number:
            raise ValueError("Financial v2 records require a PIT accession")
        if "api_token=" in self.source_reference.lower():
            raise ValueError("Source reference contains credentials")
        return self


class BackfillProvider(Protocol):
    def fetch_financial_statements(
        self, symbol: str
    ) -> tuple[NormalizedFinancialObservation, ...]: ...

    def fetch_daily_prices(self, symbol: str, start_date: date, end_date: date): ...

    def fetch_historical_market_cap(
        self, symbol: str, start_date: date, end_date: date
    ) -> tuple[HistoricalMarketValueObservation, ...]: ...


def _cost(symbol_count: int) -> dict[str, int | str]:
    if symbol_count < 1:
        raise ValueError("Backfill slice must contain at least one symbol")
    provisional = symbol_count * PROVISIONAL_BILLING_PER_SYMBOL
    safety = (Decimal(provisional) * SAFETY_MULTIPLIER).to_integral_value(rounding="ROUND_CEILING")
    return {
        "physicalHttpAttemptCeiling": symbol_count * PHYSICAL_ATTEMPTS_PER_SYMBOL,
        "configuredLocalWeightCeiling": symbol_count * WEIGHT_PER_SYMBOL,
        "provisionalProviderBilling": provisional,
        "providerBilledSafetyCeiling": int(safety),
        "retryCeiling": 0,
    }


def _slice_from_manifest(path: Path, slice_id: str) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    expected = manifest.get("manifestContentHash")
    without_hash = {key: value for key, value in manifest.items() if key != "manifestContentHash"}
    if expected != canonical_hash(without_hash):
        raise ValueError("Slice manifest content hash mismatch")
    matches = [item for item in manifest["slices"] if item["sliceId"] == slice_id]
    if len(matches) != 1:
        raise ValueError("Immutable preflight slice ID was not found exactly once")
    return matches[0]


def build_preflight(
    manifest_path: Path,
    slice_id: str,
    *,
    dashboard_before: int,
    output_directory: Path,
    storage_root: Path,
    run_id: str,
) -> dict[str, Any]:
    if not 0 <= dashboard_before <= PROVIDER_DAILY_LIMIT:
        raise ValueError("Dashboard counter is outside the provider daily limit")
    selected = _slice_from_manifest(manifest_path, slice_id)
    symbols = selected["symbols"]
    if len(symbols) != len(set(symbols)):
        raise ValueError("Backfill slice contains duplicate symbols")
    report = output_directory / f"scoring-input-backfill-{run_id}.json"
    git_manifest = output_directory / f"scoring-input-backfill-{run_id}-manifest.json"
    checkpoint = storage_root / "checkpoints" / run_id
    cost = _cost(len(symbols))
    maximum_safe_delta = (
        PROVIDER_DAILY_LIMIT - MINIMUM_PROVIDER_RESERVE - dashboard_before
    )
    return {
        "reportVersion": V2_REPORT_VERSION,
        "inputContractVersion": V2_CONTRACT_VERSION,
        "priorInputContractVersion": V1_CONTRACT_VERSION,
        "runId": run_id,
        "sliceId": slice_id,
        "sliceManifestPath": str(manifest_path),
        "symbols": symbols,
        "symbolCount": len(symbols),
        "endpoints": ALLOWED_ENDPOINTS,
        **cost,
        "dashboardBefore": dashboard_before,
        "minimumProviderReserve": MINIMUM_PROVIDER_RESERVE,
        "maximumSafeObservedDelta": maximum_safe_delta,
        "safeToExecute": cost["providerBilledSafetyCeiling"] <= maximum_safe_delta,
        "reportPath": str(report),
        "manifestPath": str(git_manifest),
        "checkpointDirectory": str(checkpoint),
        "storageRoot": str(storage_root),
        "immutableOutputs": True,
        "singleRunLockRequired": True,
        "explicitConfirmationRequired": True,
        "networkRequestsExecuted": False,
    }


def load_v1_pit_index(
    storage_references: tuple[Path, ...],
) -> dict[tuple[str, str, date], tuple[datetime, str]]:
    index = {}
    for path in storage_references:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload["records"]:
            accession = item.get("accessionNumber")
            if not accession:
                continue
            key = (
                item["symbol"],
                item["periodType"],
                date.fromisoformat(item["fiscalPeriodEnd"]),
            )
            value = (datetime.fromisoformat(item["availableAt"]), accession)
            previous = index.get(key)
            if previous is not None and previous != value:
                raise ValueError("Conflicting controlled v1 PIT evidence")
            index[key] = value
    return index


def _record(payload: dict[str, Any]) -> ScoringInputV2Record:
    return ScoringInputV2Record.model_validate({**payload, "contentHash": canonical_hash(payload)})


def normalize_symbol_v2(
    symbol: str,
    financials: tuple[NormalizedFinancialObservation, ...],
    prices,
    market_values: tuple[HistoricalMarketValueObservation, ...],
    pit_index: dict[tuple[str, str, date], tuple[datetime, str]],
) -> tuple[ScoringInputV2Record, ...]:
    records = []
    required_pit_keys = {
        key for key in pit_index if key[0] == symbol
    }
    matched_pit_keys = set()
    for observation in financials:
        pit_key = (
            symbol,
            observation.period_type,
            observation.fiscal_period_end,
        )
        pit = pit_index.get(pit_key)
        if pit is None:
            continue
        matched_pit_keys.add(pit_key)
        available_at, accession = pit
        for field, value in sorted(observation.values.items()):
            if value is None:
                continue
            records.append(
                _record(
                    {
                        "symbol": symbol,
                        "providerSymbol": observation.provider_symbol,
                        "dataset": "FINANCIAL",
                        "normalizedField": field,
                        "value": str(value),
                        "unit": (
                            "SHARES"
                            if field in {
                                "shares_outstanding",
                                "diluted_weighted_average_shares",
                            }
                            else observation.currency
                        ),
                        "currency": (
                            None
                            if field in {
                                "shares_outstanding",
                                "diluted_weighted_average_shares",
                            }
                            else observation.currency
                        ),
                        "periodType": observation.period_type,
                        "fiscalPeriodEnd": observation.fiscal_period_end.isoformat(),
                        "effectiveAt": observation.effective_at.isoformat(),
                        "availableAt": available_at.isoformat(),
                        "ingestedAt": observation.ingested_at.isoformat(),
                        "sourceReference": observation.source_reference,
                        "providerCode": "eodhd",
                        "providerSchemaVersion": observation.provider_schema_version,
                        "parserVersion": observation.parser_version,
                        "sourceContentHash": observation.content_hash,
                        "accessionNumber": accession,
                    }
                )
            )
    if not required_pit_keys:
        raise ValueError("V2 backfill has no controlled v1 PIT evidence")
    if matched_pit_keys != required_pit_keys:
        raise ValueError("V2 backfill is missing a required controlled PIT period")
    for bar in prices.bars:
        for field, value, unit in (
            ("open", bar.open_price, f"{prices.security.currency}/SHARE"),
            ("high", bar.high_price, f"{prices.security.currency}/SHARE"),
            ("low", bar.low_price, f"{prices.security.currency}/SHARE"),
            ("close", bar.close_price, f"{prices.security.currency}/SHARE"),
            ("adjusted_close", bar.adjusted_close, f"{prices.security.currency}/SHARE"),
            ("volume", bar.volume, "SHARES"),
        ):
            if value is None:
                continue
            effective = datetime.combine(bar.trading_date, datetime.min.time(), tzinfo=UTC)
            records.append(
                _record(
                    {
                        "symbol": symbol,
                        "providerSymbol": prices.provider_symbol,
                        "dataset": "DAILY_PRICE",
                        "normalizedField": field,
                        "value": str(value),
                        "unit": unit,
                        "currency": (
                            None if field == "volume" else prices.security.currency
                        ),
                        "periodType": "DAILY",
                        "fiscalPeriodEnd": bar.trading_date.isoformat(),
                        "effectiveAt": effective.isoformat(),
                        "availableAt": prices.available_at.isoformat(),
                        "ingestedAt": prices.retrieved_at.isoformat(),
                        "sourceReference": prices.source_reference,
                        "providerCode": prices.provider_descriptor.code,
                        "providerSchemaVersion": (
                            prices.provider_descriptor.provider_schema_version
                        ),
                        "parserVersion": prices.provider_descriptor.parser_version,
                        "sourceContentHash": prices.content_hash.removeprefix(
                            "sha256:"
                        ).upper(),
                    }
                )
            )
    for observation in market_values:
        effective = datetime.combine(observation.effective_at, datetime.min.time(), tzinfo=UTC)
        records.append(
            _record(
                {
                    "symbol": symbol,
                    "providerSymbol": observation.provider_symbol,
                    "dataset": "HISTORICAL_MARKET_CAP",
                    "normalizedField": "market_capitalization",
                    "value": str(observation.market_capitalization),
                    "unit": "USD",
                    "currency": "USD",
                    "periodType": "DAILY",
                    "fiscalPeriodEnd": observation.effective_at.isoformat(),
                    "effectiveAt": effective.isoformat(),
                    "availableAt": observation.ingested_at.isoformat(),
                    "ingestedAt": observation.ingested_at.isoformat(),
                    "sourceReference": observation.source_reference,
                    "providerCode": "eodhd",
                    "providerSchemaVersion": observation.provider_schema_version,
                    "parserVersion": observation.parser_version,
                    "sourceContentHash": observation.content_hash,
                }
            )
        )
    return tuple(
        sorted(
            records,
            key=lambda item: (
                item.dataset,
                item.normalized_field,
                item.effective_at,
                item.content_hash,
            ),
        )
    )


class GitignoredV2Store:
    def __init__(self, root: Path) -> None:
        self._root = root

    def persist(self, symbol: str, records: tuple[ScoringInputV2Record, ...]) -> dict[str, Any]:
        payload = {
            "inputContractVersion": V2_CONTRACT_VERSION,
            "symbol": symbol,
            "formulaHistoryRequirements": FORMULA_HISTORY_REQUIREMENTS,
            "missingNormalizedFields": sorted(
                FORMULA_INPUT_FIELDS - {item.normalized_field for item in records}
            ),
            "records": [item.model_dump(mode="json", by_alias=True) for item in records],
        }
        content_hash = canonical_hash(payload)
        path = self._root / symbol / f"{content_hash}.json"
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != payload:
                raise RuntimeError("SCORING_INPUT_V2_CONTENT_HASH_COLLISION")
        else:
            write_immutable_json(path, payload)
        return {
            "symbol": symbol,
            "contentHash": content_hash,
            "storageReference": path.as_posix(),
            "recordCount": len(records),
            "datasetCoverage": dict(sorted(Counter(item.dataset for item in records).items())),
        }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded scoring-input v2 backfill.")
    parser.add_argument("--slice-manifest", type=Path, required=True)
    parser.add_argument("--slice-id", required=True)
    parser.add_argument("--v1-payload", type=Path, action="append", default=[])
    parser.add_argument("--dashboard-before", type=int, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE)
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--confirm-live", choices=(LIVE_CONFIRMATION,))
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    run_id = new_run_id()
    preflight = build_preflight(
        arguments.slice_manifest,
        arguments.slice_id,
        dashboard_before=arguments.dashboard_before,
        output_directory=arguments.output_directory,
        storage_root=arguments.storage_root,
        run_id=run_id,
    )
    print(json.dumps(preflight, indent=2))
    if not arguments.execute_live:
        return
    if arguments.confirm_live != LIVE_CONFIRMATION:
        raise SystemExit(f"--execute-live requires --confirm-live {LIVE_CONFIRMATION}")
    if not preflight["safeToExecute"]:
        raise SystemExit("Backfill slice would consume the provider safety reserve")
    for key in ("reportPath", "manifestPath"):
        if Path(preflight[key]).exists():
            raise SystemExit("Refusing to overwrite a backfill artifact")
    local_environment = _load_local_environment(Path(".env"))
    api_key = os.environ.get("EODHD_API_KEY") or local_environment.get(
        "EODHD_API_KEY", ""
    )
    if not api_key:
        raise SystemExit("EODHD_API_KEY is required")
    pit_index = load_v1_pit_index(tuple(arguments.v1_payload))
    budget = EodhdCallBudget(
        weighted_call_ceiling=preflight["configuredLocalWeightCeiling"],
        request_ceiling=preflight["physicalHttpAttemptCeiling"],
    )
    provider = EodhdProvider(
        api_key=api_key,
        max_retries=0,
        request_observer=budget.record,
        request_authorizer=budget.reserve,
    )
    store = GitignoredV2Store(arguments.storage_root)
    receipts = []
    lock = arguments.storage_root / ".scoring-input-v2.lock"
    with MatureGateRunLock(lock, run_id):
        for index, symbol in enumerate(preflight["symbols"], start=1):
            financials = provider.fetch_financial_statements(symbol)
            prices = provider.fetch_daily_prices(symbol, arguments.start_date, arguments.end_date)
            market_values = provider.fetch_historical_market_cap(
                symbol, arguments.start_date, arguments.end_date
            )
            records = normalize_symbol_v2(symbol, financials, prices, market_values, pit_index)
            receipt = store.persist(symbol, records)
            receipts.append(receipt)
            write_immutable_json(
                Path(preflight["checkpointDirectory"])
                / f"{index:04d}-{symbol}-{receipt['contentHash']}.json",
                receipt,
            )
        report = {
            **preflight,
            "networkRequestsExecuted": True,
            "completedSymbols": len(receipts),
            "physicalHttpAttempts": budget.requests,
            "configuredLocalWeights": budget.weighted_calls,
            "receipts": receipts,
        }
        write_immutable_json(Path(preflight["reportPath"]), report)
        manifest = {
            "artifactType": "SCORING_INPUT_V2_GIT_SAFE_MANIFEST",
            "runId": run_id,
            "reportSha256": file_hash(Path(preflight["reportPath"])),
            "licensedValuesIncluded": False,
            "receipts": receipts,
        }
        write_immutable_json(Path(preflight["manifestPath"]), manifest)


if __name__ == "__main__":
    main()
