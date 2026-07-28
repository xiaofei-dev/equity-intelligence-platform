from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

AUDIT_SCHEMA_VERSION = "eodhd-documentation-semantic-audit-v2.0.0"
PROVIDER_SEMANTIC_CONTRACT_VERSION = "eodhd-fundamentals-semantics-v2.0.0"
ALLOWED_DECISIONS = frozenset({"PROVEN", "NOT_DOCUMENTED", "CONTRADICTED"})

SOURCES = (
    {
        "sourceId": "EODHD_FUNDAMENTALS_GLOSSARY_COMMON_STOCK",
        "url": (
            "https://eodhd.com/financial-academy/financial-faq/"
            "fundamentals-glossary-common-stock"
        ),
        "accessedAt": "2026-07-28T04:12:26.490969Z",
        "sha256": "7F8A55C99D2A694D1A39BE6A07530936988F2D5E85F69E832383E7AC5DF5AC0F",
    },
    {
        "sourceId": "EODHD_DEBT_FIELDS_EXPLAINED",
        "url": (
            "https://eodhd.com/financial-academy/financial-faq/"
            "debt-fields-explained"
        ),
        "accessedAt": "2026-07-28T04:12:26.750806Z",
        "sha256": "C3A1B40CF40F71B424F4F58622421CA10B3512F7A0A2E5CE507489B577BD351A",
    },
    {
        "sourceId": "EODHD_FUNDAMENTALS_API_DOCUMENTATION",
        "url": "https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds",
        "accessedAt": "2026-07-28T04:12:27.160383Z",
        "sha256": "D66343528610E6571F9D9A7BC4A33E3FADEBBAE5953E2C0F47FFD2130A4451DB",
    },
    {
        "sourceId": "EODHD_OFFICIAL_OPENAPI_FUNDAMENTALS_PATH",
        "url": (
            "https://raw.githubusercontent.com/EodHistoricalData/"
            "EODHD-openapi/main/paths/fundamentals_ticker.yaml"
        ),
        "accessedAt": "2026-07-28T04:12:27.369827Z",
        "sha256": "0D1D1D5EF6C99CC75E240489F2D091F39E2BA87D01A8D4EC05C97C4FAE6729FA",
    },
    {
        "sourceId": "EODHD_US_FUNDAMENTALS_RECALCULATION_NOTICE",
        "url": (
            "https://eodhd.com/financial-apis-blog/"
            "big-update-for-usa-fundamentals-new-fields"
        ),
        "accessedAt": "2026-07-28T04:12:27.670904Z",
        "sha256": "FCC8691CCD658432680FC1402608D57614B940A2F15335B7923DA0C4B031B899",
    },
)


def _claim(
    decision: str,
    reason_code: str,
    source_ids: tuple[str, ...],
    evidence_summary: str,
) -> dict[str, Any]:
    if decision not in ALLOWED_DECISIONS:
        raise ValueError("Unsupported documentation decision")
    return {
        "decision": decision,
        "reasonCode": reason_code,
        "sourceIds": list(source_ids),
        "evidenceSummary": evidence_summary,
    }


def build_documentation_audit() -> dict[str, Any]:
    glossary = "EODHD_FUNDAMENTALS_GLOSSARY_COMMON_STOCK"
    debt = "EODHD_DEBT_FIELDS_EXPLAINED"
    api = "EODHD_FUNDAMENTALS_API_DOCUMENTATION"
    openapi = "EODHD_OFFICIAL_OPENAPI_FUNDAMENTALS_PATH"
    recalculation = "EODHD_US_FUNDAMENTALS_RECALCULATION_NOTICE"
    debt_claims = {
        "fieldIdentity": _claim(
            "PROVEN",
            "OFFICIAL_GLOSSARY_NAMES_FIELD_TOTAL_DEBT",
            (glossary, debt),
            (
                "Official EODHD documentation calls shortLongTermDebtTotal total "
                "debt and locates it in Financials.Balance_Sheet."
            ),
        ),
        "inclusionsAndExclusions": _claim(
            "NOT_DOCUMENTED",
            "COMPONENTS_VARY_BY_COMPANY_AND_EXCLUSIONS_UNSPECIFIED",
            (glossary, debt),
            (
                "The glossary says composition may differ by company and does "
                "not exhaustively define leases, notes, overdrafts, convertible "
                "debt, or other interest-bearing obligations."
            ),
        ),
        "unitAndCurrency": _claim(
            "PROVEN",
            "FINANCIAL_STATEMENT_CURRENCY_SYMBOL_DOCUMENTED",
            (glossary, api),
            (
                "The Financials balance-sheet section carries currency_symbol "
                "for report figures."
            ),
        ),
        "consolidationScope": _claim(
            "NOT_DOCUMENTED",
            "CONSOLIDATED_ENTITY_SCOPE_NOT_SPECIFIED",
            (glossary, api, openapi),
            (
                "No reviewed public field definition establishes consolidated, "
                "parent-only, or segment scope for shortLongTermDebtTotal."
            ),
        ),
        "instantPeriodSemantics": _claim(
            "NOT_DOCUMENTED",
            "BALANCE_SHEET_DATE_NOT_EXPLICITLY_DEFINED_AS_INSTANT",
            (glossary, api, openapi),
            (
                "The field is under Balance_Sheet and records have date and "
                "filing_date, but the documentation does not explicitly define "
                "the value as an instant at period end."
            ),
        ),
        "revisionAndUpdatePolicy": _claim(
            "CONTRADICTED",
            "HISTORICAL_VALUES_CAN_BE_RECALCULATED_WITHOUT_REVISION_IDENTITY",
            (glossary, recalculation, api),
            (
                "UpdatedAt describes file refreshes, while EODHD has announced "
                "historical field recalculation and full redownload guidance; "
                "no immutable revision stream is documented."
            ),
        ),
        "frozenV1TotalDebtEquivalence": _claim(
            "PROVEN",
            "FROZEN_V1_ACCEPTS_PROVIDER_NORMALIZED_TOTAL_DEBT",
            (glossary, debt, api, openapi),
            (
                "The frozen v1 formula accepts normalized total debt where supplied, "
                "and the official provider documentation names "
                "shortLongTermDebtTotal total debt. Issuer composition variation is "
                "retained as a provider-normalization limitation."
            ),
        ),
    }
    ebitda_claims = {
        "highlightsTtmIdentity": _claim(
            "PROVEN",
            "OFFICIAL_HIGHLIGHTS_EBITDA_IS_TTM",
            (glossary, api),
            (
                "Official documentation defines Highlights.EBITDA as earnings "
                "before interest, taxes, depreciation, and amortization (TTM)."
            ),
        ),
        "fieldIdentity": _claim(
            "PROVEN",
            "OFFICIAL_GLOSSARY_DEFINES_EBITDA",
            (glossary, api),
            (
                "Official documentation lists ebitda in Income_Statement and "
                "defines it as EBIT plus depreciationAndAmortization."
            ),
        ),
        "reportedOrProviderDerived": _claim(
            "PROVEN",
            "DOCUMENTED_PROVIDER_FORMULA",
            (glossary,),
            (
                "The published formula shows this field is a provider-calculated "
                "financial-statement value rather than proof of issuer-reported "
                "EBITDA."
            ),
        ),
        "formulaAndComponents": _claim(
            "PROVEN",
            "EBIT_PLUS_DEPRECIATION_AND_AMORTIZATION",
            (glossary,),
            "The glossary documents ebit + depreciationAndAmortization.",
        ),
        "quarterlyDurationSemantics": _claim(
            "NOT_DOCUMENTED",
            "QUARTERLY_DISCRETE_YTD_TTM_SEMANTIC_UNSPECIFIED",
            (glossary, api, openapi),
            (
                "The sources label records quarterly but do not state whether "
                "each EBITDA value is a discrete quarter, YTD duration, or TTM."
            ),
        ),
        "annualDurationSemantics": _claim(
            "NOT_DOCUMENTED",
            "YEARLY_FULL_FISCAL_DURATION_NOT_EXPLICIT",
            (glossary, api, openapi),
            (
                "The sources label records yearly and provide an end date, but "
                "do not explicitly define the duration start or full-fiscal-year "
                "semantics."
            ),
        ),
        "unitAndCurrency": _claim(
            "PROVEN",
            "FINANCIAL_STATEMENT_CURRENCY_SYMBOL_DOCUMENTED",
            (glossary, api),
            (
                "The Income_Statement section carries currency_symbol for report "
                "figures."
            ),
        ),
        "filingAvailability": _claim(
            "PROVEN",
            "FINANCIAL_RECORD_FILING_DATE_DOCUMENTED",
            (glossary, api),
            (
                "Each yearly and quarterly Financials record is documented with "
                "date and filing_date."
            ),
        ),
        "acceptanceTimestamp": _claim(
            "NOT_DOCUMENTED",
            "FILING_ACCEPTANCE_TIMESTAMP_NOT_SUPPLIED",
            (glossary, api, openapi),
            (
                "The reviewed schema documents filing_date, not an acceptance "
                "timestamp or intraday public-availability time."
            ),
        ),
        "revisionAndUpdatePolicy": _claim(
            "CONTRADICTED",
            "HISTORICAL_VALUES_CAN_BE_RECALCULATED_WITHOUT_REVISION_IDENTITY",
            (glossary, recalculation, api),
            (
                "Historical fundamentals can be recalculated and redownloaded, "
                "while no field-level revision identity or restatement lineage "
                "is documented."
            ),
        ),
        "frozenV1TtmConstruction": _claim(
            "NOT_DOCUMENTED",
            "TTM_EBITDA_CANNOT_BE_CONSTRUCTED_WITHOUT_QUARTER_DURATION_SEMANTICS",
            (glossary, api, openapi),
            (
                "The provider formula is known, but frozen TTM construction is "
                "not authorized because quarterly duration semantics are absent."
            ),
        ),
        "frozenV1CurrentSnapshotEquivalence": _claim(
            "PROVEN",
            "FROZEN_V1_ACCEPTS_NORMALIZED_TTM_EBITDA",
            (glossary, api),
            (
                "The frozen net-debt-to-EBITDA factor accepts a normalized EBITDA "
                "input. Highlights.EBITDA supplies the documented TTM value without "
                "requiring quarterly reconstruction."
            ),
        ),
    }
    data_dictionary = {
        "decision": "PROVEN",
        "reasonCode": "OFFICIAL_GLOSSARY_AND_OPENAPI_EXIST",
        "sourceIds": [glossary, api, openapi],
        "scope": (
            "The glossary defines many field names and the OpenAPI defines the "
            "endpoint and broad response structure."
        ),
        "limitation": (
            "The OpenAPI models Financials yearly and quarterly collections "
            "without field-level schemas, so it does not close the disputed "
            "period, scope, or revision semantics."
        ),
    }
    current_contract_update_allowed = (
        debt_claims["fieldIdentity"]["decision"] == "PROVEN"
        and debt_claims["frozenV1TotalDebtEquivalence"]["decision"] == "PROVEN"
        and ebitda_claims["highlightsTtmIdentity"]["decision"] == "PROVEN"
        and ebitda_claims["frozenV1CurrentSnapshotEquivalence"]["decision"]
        == "PROVEN"
    )
    audit = {
        "artifactType": "EODHD_FUNDAMENTALS_DOCUMENTATION_SEMANTIC_AUDIT",
        "schemaVersion": AUDIT_SCHEMA_VERSION,
        "providerSemanticContractVersion": PROVIDER_SEMANTIC_CONTRACT_VERSION,
        "scope": "DOCUMENTATION_ONLY",
        "sources": list(SOURCES),
        "shortLongTermDebtTotal": debt_claims,
        "ebitda": ebitda_claims,
        "officialDataDictionary": data_dictionary,
        "providerSemanticContractUpdateAllowed": current_contract_update_allowed,
        "providerSemanticContractScope": "CURRENT_SNAPSHOT_ONLY",
        "eligibilityDecision": {
            "currentQc": "SOURCE_ROUTE_ACCEPTED_ALGORITHM_WINDOW_ASSEMBLY_PENDING",
            "currentQcBlockingReasons": [
                "CURRENT_FACTOR_WINDOW_ASSEMBLY_NOT_EXECUTED",
            ],
            "currentUq": "BLOCKED",
            "currentUqAdditionalBlockingReasons": [
                "MONTHLY_PIT_FCF_YIELD_HISTORY_NOT_AVAILABLE",
            ],
            "historicalPit": "BLOCKED",
            "supportConfirmationRequired": False,
        },
        "requests": {
            "documentationHttpRequests": len(SOURCES),
            "eodhdFinancialDataApiRequests": 0,
            "secFinancialDataApiRequests": 0,
        },
        "repositoryEvidence": {
            "normalizedCoverage": {
                "shortLongTermDebtTotalAsTotalDebt": "223_OF_223",
                "ebitda": "223_OF_223",
            },
            "interpretation": (
                "The documented fields may be used only in a sealed current snapshot. "
                "They do not prove historical publication or revision lineage."
            ),
        },
        "algorithmScoringExecuted": False,
        "forwardValidationExecuted": False,
    }
    audit["artifactContentHash"] = canonical_hash(audit)
    return audit


def semantic_contract_is_acceptable(audit: dict[str, Any]) -> bool:
    return bool(audit["providerSemanticContractUpdateAllowed"])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the documentation-only EODHD semantic audit."
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    write_immutable_json(arguments.output.resolve(), build_documentation_audit())


if __name__ == "__main__":
    main()
