"""Bounded SEC-only scoring-input supplement for the frozen three-symbol canary."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

from equity_analysis.provider_validation.cli import _load_local_environment
from equity_analysis.provider_validation.execution_safety import ExecutionLease
from equity_analysis.provider_validation.expansion_gate import (
    FORMULA_INPUT_FIELDS,
    canonical_hash,
    file_hash,
    new_run_id,
    write_immutable_json,
)
from equity_analysis.provider_validation.models import (
    ProviderRequestMetric,
    SecFactObservation,
    SecFilingSummary,
)
from equity_analysis.provider_validation.scoring_backfill_cli import (
    GitignoredV2Store,
    ScoringInputV2Record,
)
from equity_analysis.provider_validation.sec_edgar import (
    SEC_CONCEPT_MAPPING_VERSION,
    SecEdgarClient,
    select_point_in_time_facts,
)

CANARY_SYMBOLS = ("AAPL", "CAT", "JNJ")
LIVE_CONFIRMATION = "I_CONFIRM_SEC_ONLY_SCORING_SUPPLEMENT_CANARY"
REPORT_VERSION = "sec-scoring-supplement-canary-v1.0.0"
DIAGNOSTIC_VERSION = "sec-scoring-supplement-diagnostics-v1.0.0"
MAX_SEC_ATTEMPTS = 9
ALLOWED_ENDPOINTS = ("ticker_mapping", "submissions", "company_facts")
SUPPLEMENT_FIELDS = frozenset(
    {"diluted_weighted_average_shares", "interest_expense"}
)
METRIC_TO_FIELD = {
    "diluted_shares": "diluted_weighted_average_shares",
    "interest_expense": "interest_expense",
}


class SecSupplementProvider(Protocol):
    def lookup_cik(self, symbol: str) -> tuple[str, str]: ...

    def fetch_recent_filings(
        self,
        cik: str,
        symbol: str,
        as_of_time: datetime,
    ) -> tuple[SecFilingSummary, ...]: ...

    def fetch_company_facts(self, cik: str) -> dict[str, Any]: ...


def build_preflight(
    *,
    run_id: str,
    output_directory: Path,
    storage_root: Path,
) -> dict[str, Any]:
    stem = f"sec-scoring-supplement-{run_id}"
    return {
        "reportVersion": REPORT_VERSION,
        "runId": run_id,
        "symbols": list(CANARY_SYMBOLS),
        "endpoints": list(ALLOWED_ENDPOINTS),
        "maximumSecPhysicalAttempts": MAX_SEC_ATTEMPTS,
        "maximumEodhdPhysicalAttempts": 0,
        "retryCeiling": 0,
        "explicitConfirmationRequired": True,
        "singleRunLockRequired": True,
        "immutableOutputs": True,
        "networkRequestsExecuted": False,
        "reportPath": str(output_directory / f"{stem}.json"),
        "manifestPath": str(output_directory / f"{stem}-manifest.json"),
        "diagnosticPath": str(output_directory / f"{stem}-diagnostics.json"),
        "checkpointDirectory": str(storage_root / "checkpoints" / run_id),
    }


def _load_v2_payload(path: Path, symbol: str) -> tuple[dict[str, Any], tuple[
    ScoringInputV2Record, ...
]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("symbol") != symbol:
        raise ValueError(f"Controlled payload symbol mismatch for {symbol}")
    expected = path.stem.upper()
    if len(expected) == 64 and canonical_hash(payload) != expected:
        raise ValueError(f"Controlled payload content hash mismatch for {symbol}")
    records = tuple(
        ScoringInputV2Record.model_validate(item) for item in payload.get("records", ())
    )
    if not records:
        raise ValueError(f"Controlled payload contains no records for {symbol}")
    return payload, records


def _trading_dates(records: tuple[ScoringInputV2Record, ...]) -> tuple[date, ...]:
    return tuple(
        sorted(
            {
                item.fiscal_period_end
                for item in records
                if item.dataset == "DAILY_PRICE"
            }
        )
    )


def _is_discrete_quarter(fact: SecFactObservation) -> bool:
    if (
        fact.form not in {"10-Q", "10-Q/A"}
        or fact.period_start is None
        or fact.fiscal_period not in {"Q1", "Q2", "Q3"}
    ):
        return False
    duration_days = (fact.period_end - fact.period_start).days + 1
    return 70 <= duration_days <= 110


def _sec_record(
    symbol: str,
    cik: str,
    fact: SecFactObservation,
    ingested_at: datetime,
) -> ScoringInputV2Record:
    normalized_field = METRIC_TO_FIELD[fact.metric_code]
    raw = {
        "symbol": symbol,
        "providerSymbol": cik,
        "dataset": "FINANCIAL",
        "normalizedField": normalized_field,
        "value": str(fact.value),
        "unit": "SHARES" if fact.unit == "shares" else "USD",
        "currency": None if fact.unit == "shares" else "USD",
        "periodType": "QUARTERLY",
        "fiscalPeriodEnd": fact.period_end.isoformat(),
        "effectiveAt": datetime.combine(
            fact.period_end,
            datetime.min.time(),
            tzinfo=UTC,
        ).isoformat(),
        "availableAt": fact.available_at.isoformat(),
        "ingestedAt": ingested_at.isoformat(),
        "sourceReference": f"sec-edgar:companyfacts:CIK{cik}",
        "providerCode": "sec_edgar",
        "providerSchemaVersion": "sec-companyfacts-v1",
        "parserVersion": fact.concept_mapping_version
        or SEC_CONCEPT_MAPPING_VERSION,
        "sourceContentHash": fact.source_content_hash,
        "accessionNumber": fact.accession_number,
    }
    return ScoringInputV2Record.model_validate(
        {**raw, "contentHash": canonical_hash(raw)}
    )


def supplement_symbol(
    *,
    symbol: str,
    payload_path: Path,
    provider: SecSupplementProvider,
    as_of_time: datetime,
    ingested_at: datetime,
    store: GitignoredV2Store,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _payload, existing = _load_v2_payload(payload_path, symbol)
    trading_dates = _trading_dates(existing)
    if not trading_dates:
        raise ValueError(f"No controlled trading calendar for {symbol}")
    cik, entity_name = provider.lookup_cik(symbol)
    filings = provider.fetch_recent_filings(cik, symbol, as_of_time)
    company_facts = provider.fetch_company_facts(cik)
    selected = select_point_in_time_facts(
        company_facts,
        filings,
        trading_dates,
        as_of_time,
    )
    approved = tuple(
        item
        for item in selected
        if item.metric_code in METRIC_TO_FIELD and _is_discrete_quarter(item)
    )
    additions = tuple(
        _sec_record(symbol, cik, item, ingested_at) for item in approved
    )
    replacement_keys = {
        (item.normalized_field, item.period_type, item.fiscal_period_end)
        for item in additions
    }
    retained = tuple(
        item
        for item in existing
        if (
            item.normalized_field,
            item.period_type,
            item.fiscal_period_end,
        )
        not in replacement_keys
    )
    merged = tuple(
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
    receipt = store.persist(symbol, merged)
    coverage = sorted({item.normalized_field for item in merged} & FORMULA_INPUT_FIELDS)
    diagnostic = {
        "symbol": symbol,
        "cik": cik,
        "entityName": entity_name,
        "sourceHashes": sorted(
            {item.source_content_hash for item in additions}
        ),
        "selectedConcepts": [
            {
                "normalizedField": METRIC_TO_FIELD[item.metric_code],
                "taxonomyTag": item.taxonomy_tag,
                "unit": item.unit,
                "periodStart": item.period_start.isoformat()
                if item.period_start
                else None,
                "periodEnd": item.period_end.isoformat(),
                "form": item.form,
                "accessionNumber": item.accession_number,
                "acceptanceDatetime": item.acceptance_datetime.isoformat(),
                "availableAt": item.available_at.isoformat(),
                "conceptPriority": item.concept_priority,
                "semanticClassification": item.semantic_classification,
                "conceptMappingVersion": item.concept_mapping_version,
                "sourceContentHash": item.source_content_hash,
            }
            for item in approved
        ],
        "rejectedNonDiscreteFactCount": sum(
            item.metric_code in METRIC_TO_FIELD and not _is_discrete_quarter(item)
            for item in selected
        ),
        "formulaCoverage": coverage,
        "missingFormulaFields": sorted(FORMULA_INPUT_FIELDS - set(coverage)),
        "rawValuesIncluded": False,
    }
    return receipt, diagnostic


def execute_canary(
    *,
    payload_paths: dict[str, Path],
    provider: SecSupplementProvider,
    as_of_time: datetime,
    ingested_at: datetime,
    store: GitignoredV2Store,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if tuple(payload_paths) != CANARY_SYMBOLS:
        raise ValueError("SEC supplement canary requires exact AAPL, CAT, JNJ order")
    receipts = []
    diagnostics = []
    for symbol in CANARY_SYMBOLS:
        receipt, diagnostic = supplement_symbol(
            symbol=symbol,
            payload_path=payload_paths[symbol],
            provider=provider,
            as_of_time=as_of_time,
            ingested_at=ingested_at,
            store=store,
        )
        receipts.append(receipt)
        diagnostics.append(diagnostic)
    return receipts, diagnostics


def _parse_payloads(values: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        symbol, separator, raw_path = value.partition("=")
        if not separator or symbol in parsed:
            raise ValueError("--v2-payload requires unique SYMBOL=PATH values")
        parsed[symbol] = Path(raw_path)
    if tuple(parsed) != CANARY_SYMBOLS:
        raise ValueError("--v2-payload order must be AAPL, CAT, JNJ")
    return parsed


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v2-payload", action="append", default=[], required=True)
    parser.add_argument("--as-of-time", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output-directory", type=Path, default=Path("docs/generated"))
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path("storage/provider-validation/scoring-inputs-v2"),
    )
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--confirm-live", choices=(LIVE_CONFIRMATION,))
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    payload_paths = _parse_payloads(arguments.v2_payload)
    run_id = new_run_id()
    preflight = build_preflight(
        run_id=run_id,
        output_directory=arguments.output_directory,
        storage_root=arguments.storage_root,
    )
    print(json.dumps(preflight, indent=2))
    if not arguments.execute_live:
        return
    if arguments.confirm_live != LIVE_CONFIRMATION:
        raise SystemExit(
            f"--execute-live requires --confirm-live {LIVE_CONFIRMATION}"
        )
    if any(Path(preflight[key]).exists() for key in (
        "reportPath",
        "manifestPath",
        "diagnosticPath",
    )):
        raise SystemExit("Refusing to overwrite a SEC supplement artifact")
    environment = _load_local_environment(Path(".env"))
    user_agent = os.environ.get("SEC_USER_AGENT") or environment.get(
        "SEC_USER_AGENT",
        "",
    )
    if not user_agent:
        raise SystemExit("SEC_EDGAR_USER_AGENT is required")
    metrics: list[ProviderRequestMetric] = []
    provider = SecEdgarClient(
        user_agent=user_agent,
        request_observer=metrics.append,
    )
    store = GitignoredV2Store(arguments.storage_root)
    lock_path = arguments.storage_root / ".scoring-input-v2.lock"
    with ExecutionLease(lock_path, run_id):
        receipts, diagnostics = execute_canary(
            payload_paths=payload_paths,
            provider=provider,
            as_of_time=arguments.as_of_time,
            ingested_at=datetime.now(UTC),
            store=store,
        )
        if len(metrics) > MAX_SEC_ATTEMPTS:
            raise RuntimeError("SEC supplement exceeded its physical attempt ceiling")
        report = {
            **preflight,
            "networkRequestsExecuted": True,
            "secPhysicalAttempts": len(metrics),
            "eodhdPhysicalAttempts": 0,
            "retryCount": 0,
            "endpointAttempts": dict(
                sorted(Counter(item.endpoint_category for item in metrics).items())
            ),
            "completedSymbols": len(receipts),
            "receipts": receipts,
        }
        write_immutable_json(Path(preflight["reportPath"]), report)
        diagnostic_artifact = {
            "diagnosticVersion": DIAGNOSTIC_VERSION,
            "runId": run_id,
            "rawValuesIncluded": False,
            "securities": diagnostics,
        }
        write_immutable_json(
            Path(preflight["diagnosticPath"]),
            diagnostic_artifact,
        )
        manifest = {
            "artifactType": "SEC_SCORING_SUPPLEMENT_GIT_SAFE_MANIFEST",
            "runId": run_id,
            "reportSha256": file_hash(Path(preflight["reportPath"])),
            "diagnosticSha256": file_hash(Path(preflight["diagnosticPath"])),
            "licensedValuesIncluded": False,
            "receipts": receipts,
        }
        write_immutable_json(Path(preflight["manifestPath"]), manifest)


if __name__ == "__main__":
    main()
