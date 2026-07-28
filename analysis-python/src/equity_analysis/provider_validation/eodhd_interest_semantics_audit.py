from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)
from equity_analysis.provider_validation.objective_rating_semantics_audit import (
    _load_response,
    _verify_event,
)

AUDIT_SCHEMA_VERSION = "eodhd-interest-expense-semantic-audit-v1.1.0"
PROVIDER_SEMANTIC_CONTRACT_VERSION = (
    "eodhd-interest-expense-semantics-v1.0.0"
)
TARGET_SYMBOLS = (
    "AMAT",
    "CIEN",
    "COO",
    "CSCO",
    "DHR",
    "FAST",
    "FIX",
    "PLAB",
    "TSN",
    "WDFC",
)
ALLOWED_DECISIONS = frozenset({"PROVEN", "NOT_DOCUMENTED", "CONTRADICTED"})
DOCUMENTATION_SOURCES = (
    {
        "sourceId": "EODHD_FUNDAMENTALS_GLOSSARY_COMMON_STOCK",
        "url": (
            "https://eodhd.com/financial-academy/financial-faq/"
            "fundamentals-glossary-common-stock"
        ),
        "accessedAt": "2026-07-28T05:41:38.9141463Z",
        "sha256": (
            "FC218EF3269F0877D2081211ABB078AE1395ACF246DD8AE41CEDD7748C4BC817"
        ),
        "httpStatus": 200,
    },
    {
        "sourceId": "EODHD_FUNDAMENTALS_API_DOCUMENTATION",
        "url": "https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds",
        "accessedAt": "2026-07-28T05:41:39.3281829Z",
        "sha256": (
            "F3262397CF89E442FF2BA41C1199529365BC19161BE7CA9CB2702245F482203C"
        ),
        "httpStatus": 200,
    },
    {
        "sourceId": "EODHD_OFFICIAL_OPENAPI_FUNDAMENTALS_PATH",
        "url": (
            "https://raw.githubusercontent.com/EodHistoricalData/"
            "EODHD-openapi/main/paths/fundamentals_ticker.yaml"
        ),
        "accessedAt": "2026-07-28T05:41:39.4308897Z",
        "sha256": (
            "0D1D1D5EF6C99CC75E240489F2D091F39E2BA87D01A8D4EC05C97C4FAE6729FA"
        ),
        "httpStatus": 200,
    },
    {
        "sourceId": "EODHD_US_FUNDAMENTALS_RECALCULATION_NOTICE",
        "url": (
            "https://eodhd.com/financial-apis-blog/"
            "big-update-for-usa-fundamentals-new-fields"
        ),
        "accessedAt": "2026-07-28T05:41:39.7296100Z",
        "sha256": (
            "97E51CB444F868FFEB3584790FE1B8ADE20FA008B98C32DE8DA6F8DB78367116"
        ),
        "httpStatus": 200,
    },
    {
        "sourceId": "EODHD_HISTORICAL_RATIO_ACADEMY",
        "url": (
            "https://eodhd.com/financial-academy/financial-faq/"
            "historical-financial-ratios-how-to-calculate"
        ),
        "accessedAt": "2026-07-28T05:41:40.0444381Z",
        "sha256": (
            "6CEAEC2F48BBD61F9F76585A004C79290162F4A976ABE79562B6BC2684EE1DA4"
        ),
        "httpStatus": 200,
    },
)


def _claim(
    decision: str,
    reason_code: str,
    source_ids: tuple[str, ...],
    evidence_summary: str,
) -> dict[str, Any]:
    if decision not in ALLOWED_DECISIONS:
        raise ValueError("EODHD_INTEREST_DOCUMENTATION_DECISION_INVALID")
    return {
        "decision": decision,
        "reasonCode": reason_code,
        "sourceIds": list(source_ids),
        "evidenceSummary": evidence_summary,
    }


def build_documentation_claims() -> dict[str, dict[str, Any]]:
    glossary = "EODHD_FUNDAMENTALS_GLOSSARY_COMMON_STOCK"
    api = "EODHD_FUNDAMENTALS_API_DOCUMENTATION"
    openapi = "EODHD_OFFICIAL_OPENAPI_FUNDAMENTALS_PATH"
    recalculation = "EODHD_US_FUNDAMENTALS_RECALCULATION_NOTICE"
    ratios = "EODHD_HISTORICAL_RATIO_ACADEMY"
    return {
        "fieldIdentity": _claim(
            "PROVEN",
            "OFFICIAL_GLOSSARY_DEFINES_BORROWED_FUNDS_COST",
            (glossary, ratios),
            (
                "Official EODHD documentation defines interestExpense as the "
                "cost incurred for borrowed funds and uses it as the interest "
                "coverage denominator."
            ),
        ),
        "completeEconomicScope": _claim(
            "NOT_DOCUMENTED",
            "CAPITALIZED_INTEREST_FEES_NETTING_AND_COMPLETENESS_UNSPECIFIED",
            (glossary, ratios),
            (
                "The public definition does not establish treatment of "
                "capitalized interest, financing fees, operating-interest "
                "components, netting, or complete consolidated scope."
            ),
        ),
        "quarterlyDurationSemantic": _claim(
            "NOT_DOCUMENTED",
            "QUARTERLY_DISCRETE_YTD_TTM_SEMANTIC_UNSPECIFIED",
            (glossary, api, openapi, ratios),
            (
                "The sources label the collection quarterly and show an example, "
                "but never define each record as discrete quarter, YTD, or TTM."
            ),
        ),
        "yearlyDurationSemantic": _claim(
            "NOT_DOCUMENTED",
            "YEARLY_FULL_FISCAL_DURATION_NOT_EXPLICIT",
            (glossary, api, openapi),
            (
                "The sources label the collection yearly and define its date as "
                "period end, but do not provide period start or an explicit "
                "full-fiscal-year duration contract."
            ),
        ),
        "unitAndCurrency": _claim(
            "PROVEN",
            "INCOME_STATEMENT_CURRENCY_SYMBOL_DOCUMENTED",
            (glossary,),
            (
                "The Income_Statement section documents currency_symbol as the "
                "currency of report figures."
            ),
        ),
        "filingDate": _claim(
            "PROVEN",
            "FINANCIAL_REPORT_FILING_DATE_DOCUMENTED",
            (glossary,),
            (
                "The glossary defines filing_date as the date the financial "
                "report was filed."
            ),
        ),
        "intradayAvailability": _claim(
            "NOT_DOCUMENTED",
            "FILING_ACCEPTANCE_TIME_NOT_SUPPLIED",
            (glossary, api, openapi),
            (
                "No acceptance timestamp or intraday public-availability "
                "contract is documented for Financials records."
            ),
        ),
        "updateAndRevision": _claim(
            "CONTRADICTED",
            "HISTORICAL_RECALCULATION_WITHOUT_IMMUTABLE_REVISION_STREAM",
            (glossary, recalculation, api),
            (
                "UpdatedAt describes file refresh while official notices allow "
                "historical recalculation; no immutable field revision identity "
                "or original publication timeline is documented."
            ),
        ),
        "directTtmField": _claim(
            "NOT_DOCUMENTED",
            "NO_OFFICIAL_TTM_INTERESTEXPENSE_FIELD_DOCUMENTED",
            (glossary, api, openapi),
            (
                "The reviewed official schemas document TTM for several "
                "Highlights fields, but not for interest expense."
            ),
        ),
        "currentSnapshotRoute": _claim(
            "NOT_DOCUMENTED",
            "NO_PROVEN_TTM_OR_DISCRETE_QUARTER_INTEREST_ROUTE",
            (glossary, api, openapi, ratios),
            (
                "Frozen v1 may accept provider-normalized interest expense, but "
                "the public contract does not prove a TTM field or four "
                "discrete-quarter inputs."
            ),
        ),
    }


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _field_paths(value: Any, prefix: str = "") -> set[str]:
    paths = set()
    if not isinstance(value, dict):
        return paths
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        paths.add(path)
        if isinstance(child, dict):
            paths.update(_field_paths(child, path))
    return paths


def _period_structure(rows: list[dict[str, Any]]) -> dict[str, Any]:
    field_names = sorted({str(key) for row in rows for key in row})
    present = [row for row in rows if "interestExpense" in row]
    return {
        "recordCount": len(rows),
        "recordFieldNames": field_names,
        "interestExpensePresentCount": len(present),
        "interestExpenseNonNullCount": sum(
            row.get("interestExpense") is not None for row in present
        ),
        "interestExpenseNullCount": sum(
            row.get("interestExpense") is None for row in present
        ),
        "interestExpenseAbsentCount": len(rows) - len(present),
        "datePresentCount": sum(bool(row.get("date")) for row in rows),
        "filingDatePresentCount": sum(
            bool(row.get("filing_date")) for row in rows
        ),
        "periodStartPresentCount": sum(
            bool(row.get("period_start") or row.get("periodStart"))
            for row in rows
        ),
        "accessionPresentCount": sum(
            bool(row.get("accession") or row.get("accessionNumber"))
            for row in rows
        ),
    }


def inspect_fundamentals_structure(payload: dict[str, Any]) -> dict[str, Any]:
    financials = payload.get("Financials", {})
    income = (
        financials.get("Income_Statement", {})
        if isinstance(financials, dict)
        else {}
    )
    quarterly = _records(
        income.get("quarterly", {}) if isinstance(income, dict) else {}
    )
    yearly = _records(
        income.get("yearly", {}) if isinstance(income, dict) else {}
    )
    candidate_paths = sorted(
        path
        for section in ("Highlights", "Valuation", "Technicals")
        for path in _field_paths(payload.get(section, {}), section)
        if "interest" in path.lower()
    )
    ttm_interest_paths = [
        path
        for path in candidate_paths
        if "ttm" in path.lower() and "interest" in path.lower()
    ]
    return {
        "topLevelFieldNames": sorted(str(key) for key in payload),
        "incomeStatementFieldNames": (
            sorted(str(key) for key in income)
            if isinstance(income, dict)
            else []
        ),
        "incomeStatementCurrencySymbolPresent": bool(
            isinstance(income, dict) and income.get("currency_symbol")
        ),
        "quarterly": _period_structure(quarterly),
        "yearly": _period_structure(yearly),
        "interestNamedPathsOutsideFinancials": candidate_paths,
        "explicitTtmInterestPaths": ttm_interest_paths,
        "generalUpdatedAtPresent": bool(
            isinstance(payload.get("General"), dict)
            and payload["General"].get("UpdatedAt")
        ),
    }


def inspect_controlled_payload(payload: dict[str, Any]) -> dict[str, Any]:
    records = [
        record
        for record in payload.get("records", ())
        if record.get("providerCode") == "eodhd"
        and record.get("normalizedField") == "interest_expense"
    ]
    content_hash_count = sum(bool(record.get("contentHash")) for record in records)
    return {
        "normalizedEodhdInterestRecordCount": len(records),
        "quarterlyRecordCount": sum(
            record.get("periodType") == "QUARTERLY" for record in records
        ),
        "annualRecordCount": sum(
            record.get("periodType") == "ANNUAL" for record in records
        ),
        "periodStartPresentCount": sum(
            bool(record.get("periodStart")) for record in records
        ),
        "fiscalPeriodEndPresentCount": sum(
            bool(record.get("fiscalPeriodEnd")) for record in records
        ),
        "accessionPresentCount": sum(
            bool(record.get("accessionNumber")) for record in records
        ),
        "availableAtPresentCount": sum(
            bool(record.get("availableAt")) for record in records
        ),
        "sourceHashPresentCount": sum(
            bool(record.get("sourceContentHash")) for record in records
        ),
        "recordContentHashPresentCount": content_hash_count,
        "recordHashValidationStatus": (
            "COVERED_BY_HASH_VERIFIED_CONTROLLED_PAYLOAD"
        ),
        "semanticBindingStatus": (
            "HASH_PERIOD_END_AND_SEC_ACCESSION_PRESENT_DURATION_SEMANTIC_UNPROVEN"
            if records
            and content_hash_count == len(records)
            and all(record.get("accessionNumber") for record in records)
            else "NO_VERIFIED_NORMALIZED_EODHD_INTEREST_RECORDS"
        ),
    }


def _fundamentals_events(repository_root: Path) -> dict[str, dict[str, Any]]:
    root = (
        repository_root
        / "storage/provider-validation/scoring-inputs-v2/"
        "physical-request-journals"
    )
    result = {}
    for path in sorted(root.rglob("*-COMPLETED.json")):
        event = _verify_event(path)
        if event["detail"].get("endpointCategory") != "fundamentals":
            continue
        symbol = event["symbol"]
        if symbol in result:
            raise ValueError(f"EODHD_FUNDAMENTALS_CACHE_DUPLICATE[{symbol}]")
        _load_response(event, repository_root)
        result[symbol] = event
    return result


def _controlled_payload(
    repository_root: Path,
    security: dict[str, Any],
) -> dict[str, Any]:
    reference = security.get("storageReference")
    if not reference:
        return {}
    path = repository_root / reference
    payload = json.loads(path.read_text(encoding="utf-8"))
    if canonical_hash(payload) == security["contentHash"]:
        return payload
    if canonical_hash(
        {key: value for key, value in payload.items() if key != "contentHash"}
    ) != security["contentHash"]:
        raise ValueError(
            f"CONTROLLED_SCORING_INPUT_HASH_MISMATCH[{security['symbol']}]"
        )
    return payload


def build_interest_semantics_audit(
    *,
    repository_root: Path,
    output_path: Path,
) -> dict[str, Any]:
    aggregate_path = (
        repository_root
        / "docs/generated/formula-ready-243-final-aggregate-v1.json"
    )
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    ready = [
        item
        for item in aggregate["securities"]
        if item["status"] == "FORMULA_READY"
    ]
    if len(ready) != 223:
        raise ValueError("FORMULA_READY_SOURCE_COUNT_NOT_223")
    events = _fundamentals_events(repository_root)
    cache_counts = Counter()
    records = []
    target_records = []
    for security in sorted(ready, key=lambda item: item["symbol"]):
        symbol = security["symbol"]
        event = events.get(symbol)
        structure = (
            inspect_fundamentals_structure(_load_response(event, repository_root))
            if event
            else None
        )
        controlled = inspect_controlled_payload(
            _controlled_payload(repository_root, security)
        )
        if event:
            cache_counts["HASH_VERIFIED_RAW_FUNDAMENTALS_CACHE"] += 1
        else:
            cache_counts["RAW_FUNDAMENTALS_CACHE_MISSING"] += 1
        record = {
            "symbol": symbol,
            "rawFundamentalsCacheStatus": (
                "HASH_VERIFIED" if event else "MISSING"
            ),
            "rawFundamentalsRunId": event["runId"] if event else None,
            "rawFundamentalsResponseHash": (
                event["detail"]["responseContentHash"] if event else None
            ),
            "structure": structure,
            "controlledNormalization": controlled,
            "currentSnapshotRoute": "BLOCKED",
            "routeReasonCodes": [
                "NO_DOCUMENTED_TTM_INTERESTEXPENSE_FIELD",
                "QUARTERLY_DURATION_SEMANTIC_NOT_PROVEN",
                "COMPLETE_GROSS_INTEREST_SCOPE_NOT_PROVEN",
                *(
                    []
                    if event
                    else ["RAW_EODHD_FUNDAMENTALS_CACHE_MISSING"]
                ),
            ],
        }
        records.append(record)
        if symbol in TARGET_SYMBOLS:
            target_records.append(record)
    if tuple(item["symbol"] for item in target_records) != TARGET_SYMBOLS:
        by_symbol = {item["symbol"]: item for item in target_records}
        target_records = [by_symbol[symbol] for symbol in TARGET_SYMBOLS]

    quarterly_non_null = sum(
        item["structure"]["quarterly"]["interestExpenseNonNullCount"]
        for item in records
        if item["structure"]
    )
    yearly_non_null = sum(
        item["structure"]["yearly"]["interestExpenseNonNullCount"]
        for item in records
        if item["structure"]
    )
    explicit_ttm_count = sum(
        bool(item["structure"]["explicitTtmInterestPaths"])
        for item in records
        if item["structure"]
    )
    artifact = {
        "artifactType": "EODHD_INTEREST_EXPENSE_DOCUMENTATION_CACHE_AUDIT",
        "schemaVersion": AUDIT_SCHEMA_VERSION,
        "providerSemanticContractVersion": (
            PROVIDER_SEMANTIC_CONTRACT_VERSION
        ),
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "scope": "DOCUMENTATION_AND_OFFLINE_CACHE_STRUCTURE_ONLY",
        "documentationSources": list(DOCUMENTATION_SOURCES),
        "documentationClaims": build_documentation_claims(),
        "sourceAggregatePath": aggregate_path.relative_to(
            repository_root
        ).as_posix(),
        "sourceAggregateContentHash": aggregate["artifactContentHash"],
        "formulaReadySourceSecurityCount": len(ready),
        "cacheStatusCounts": dict(sorted(cache_counts.items())),
        "cacheCoverage": {
            "rawFundamentalsCacheCount": cache_counts[
                "HASH_VERIFIED_RAW_FUNDAMENTALS_CACHE"
            ],
            "rawFundamentalsCacheMissingCount": cache_counts[
                "RAW_FUNDAMENTALS_CACHE_MISSING"
            ],
            "quarterlyInterestExpenseNonNullRecordCount": quarterly_non_null,
            "yearlyInterestExpenseNonNullRecordCount": yearly_non_null,
            "securityCountWithExplicitTtmInterestPath": explicit_ttm_count,
        },
        "targetSymbols": list(TARGET_SYMBOLS),
        "targetResults": target_records,
        "allSecurityStructureRecords": records,
        "eligibilityDecision": {
            "currentSnapshotOnly": "BLOCKED",
            "targetSecurityCountUnblocked": 0,
            "targetSecurityCountBlocked": len(TARGET_SYMBOLS),
            "supportConfirmationRequired": True,
            "reasonCodes": [
                "PROVIDER_FIELD_IDENTITY_ONLY_PARTIALLY_DOCUMENTED",
                "NO_PROVEN_TTM_INTERESTEXPENSE_FIELD",
                "QUARTERLY_DURATION_SEMANTIC_NOT_PROVEN",
                "COMPLETE_GROSS_INTEREST_SCOPE_NOT_PROVEN",
            ],
        },
        "requests": {
            "documentationHttpRequests": len(DOCUMENTATION_SOURCES),
            "eodhdFinancialDataApiRequests": 0,
            "secFinancialDataApiRequests": 0,
        },
        "rawProviderValuesIncluded": False,
        "scoresOrRanksIncluded": False,
        "forwardValidationExecuted": False,
        "formulaOrThresholdChanges": False,
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    write_immutable_json(output_path, artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the documentation and offline cache-structure audit for "
            "EODHD interestExpense."
        )
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd().parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.repository_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    artifact = build_interest_semantics_audit(
        repository_root=root,
        output_path=output,
    )
    print(
        json.dumps(
            {
                "artifactPath": output.relative_to(root).as_posix(),
                "artifactContentHash": artifact["artifactContentHash"],
                "cacheStatusCounts": artifact["cacheStatusCounts"],
                "targetSecurityCountUnblocked": artifact[
                    "eligibilityDecision"
                ]["targetSecurityCountUnblocked"],
                "supportConfirmationRequired": artifact[
                    "eligibilityDecision"
                ]["supportConfirmationRequired"],
                "financialDataApiRequests": 0,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
