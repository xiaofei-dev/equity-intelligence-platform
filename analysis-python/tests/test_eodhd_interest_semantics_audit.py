from __future__ import annotations

import json
from pathlib import Path

from equity_analysis.provider_validation.eodhd_interest_semantics_audit import (
    AUDIT_SCHEMA_VERSION,
    TARGET_SYMBOLS,
    build_documentation_claims,
    inspect_controlled_payload,
    inspect_fundamentals_structure,
)


def test_documentation_does_not_promote_field_name_to_ttm_route() -> None:
    claims = build_documentation_claims()

    assert claims["fieldIdentity"]["decision"] == "PROVEN"
    assert claims["completeEconomicScope"]["decision"] == "NOT_DOCUMENTED"
    assert claims["quarterlyDurationSemantic"]["decision"] == "NOT_DOCUMENTED"
    assert claims["yearlyDurationSemantic"]["decision"] == "NOT_DOCUMENTED"
    assert claims["updateAndRevision"]["decision"] == "CONTRADICTED"
    assert claims["currentSnapshotRoute"]["decision"] == "NOT_DOCUMENTED"


def test_cache_structure_distinguishes_present_null_absent_and_ttm() -> None:
    payload = {
        "General": {"UpdatedAt": "2026-01-01"},
        "Highlights": {"InterestExpenseTTM": None},
        "Valuation": {},
        "Technicals": {},
        "Financials": {
            "Income_Statement": {
                "currency_symbol": "USD",
                "quarterly": {
                    "2025-Q1": {
                        "date": "2025-03-31",
                        "filing_date": "2025-05-01",
                        "interestExpense": None,
                    },
                    "2025-Q2": {
                        "date": "2025-06-30",
                        "filing_date": "2025-08-01",
                    },
                },
                "yearly": {
                    "2025": {
                        "date": "2025-12-31",
                        "filing_date": "2026-02-01",
                        "interestExpense": "not-persisted-by-audit",
                    }
                },
            }
        },
    }

    result = inspect_fundamentals_structure(payload)

    assert result["quarterly"]["interestExpensePresentCount"] == 1
    assert result["quarterly"]["interestExpenseNullCount"] == 1
    assert result["quarterly"]["interestExpenseAbsentCount"] == 1
    assert result["quarterly"]["periodStartPresentCount"] == 0
    assert result["yearly"]["interestExpenseNonNullCount"] == 1
    assert result["explicitTtmInterestPaths"] == [
        "Highlights.InterestExpenseTTM"
    ]


def test_controlled_normalization_requires_hash_and_keeps_duration_unproven() -> None:
    record = {
        "symbol": "TEST",
        "providerSymbol": "TEST.US",
        "dataset": "FINANCIAL",
        "normalizedField": "interest_expense",
        "value": "1",
        "unit": "currency",
        "currency": "USD",
        "periodType": "QUARTERLY",
        "fiscalPeriodEnd": "2025-03-31",
        "effectiveAt": "2025-03-31T00:00:00Z",
        "availableAt": "2025-05-01T00:00:00Z",
        "ingestedAt": "2025-05-02T00:00:00Z",
        "sourceReference": "eodhd:fundamentals:TEST.US:quarterly",
        "providerCode": "eodhd",
        "providerSchemaVersion": "test",
        "parserVersion": "test",
        "normalizationVersion": "provider-neutral-scoring-input-v2.0.0",
        "sourceContentHash": "A" * 64,
        "accessionNumber": "0000000001-25-000001",
        "contentHash": "B" * 64,
    }

    result = inspect_controlled_payload({"records": [record]})

    assert result["normalizedEodhdInterestRecordCount"] == 1
    assert result["periodStartPresentCount"] == 0
    assert result["accessionPresentCount"] == 1
    assert result["recordContentHashPresentCount"] == 1
    assert result["recordHashValidationStatus"] == (
        "COVERED_BY_HASH_VERIFIED_CONTROLLED_PAYLOAD"
    )
    assert result["semanticBindingStatus"] == (
        "HASH_PERIOD_END_AND_SEC_ACCESSION_PRESENT_DURATION_SEMANTIC_UNPROVEN"
    )


def test_generated_audit_is_value_free_and_keeps_all_targets_blocked() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    path = (
        repository_root
        / "docs/generated/eodhd-interest-expense-documentation-cache-audit-v1-2.json"
    )
    text = path.read_text(encoding="utf-8")
    artifact = json.loads(text)

    assert artifact["schemaVersion"] == AUDIT_SCHEMA_VERSION
    assert artifact["targetSymbols"] == list(TARGET_SYMBOLS)
    assert artifact["eligibilityDecision"]["targetSecurityCountUnblocked"] == 0
    assert artifact["eligibilityDecision"]["targetSecurityCountBlocked"] == 10
    assert artifact["requests"]["eodhdFinancialDataApiRequests"] == 0
    assert artifact["requests"]["secFinancialDataApiRequests"] == 0
    assert artifact["rawProviderValuesIncluded"] is False
    assert artifact["scoresOrRanksIncluded"] is False
    assert '"value":' not in text
