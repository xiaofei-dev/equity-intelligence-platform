from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

DECISION_VERSION = "objective-rating-v1-qc-data-source-decision-v1.0.0"

EXISTING_EODHD_VALUE_PATHS = {
    "incomeStatement": [
        "Financials.Income_Statement.quarterly.*.totalRevenue",
        "Financials.Income_Statement.quarterly.*.grossProfit",
        "Financials.Income_Statement.quarterly.*.operatingIncome",
        "Financials.Income_Statement.quarterly.*.ebit",
        "Financials.Income_Statement.quarterly.*.netIncome",
        "Financials.Income_Statement.quarterly.*.incomeTaxExpense",
        "Financials.Income_Statement.quarterly.*.incomeBeforeTax",
        "Financials.Income_Statement.quarterly.*.interestExpense",
        "Financials.Income_Statement.yearly.*",
    ],
    "cashFlow": [
        "Financials.Cash_Flow.quarterly.*.totalCashFromOperatingActivities",
        "Financials.Cash_Flow.quarterly.*.capitalExpenditures",
        "Financials.Cash_Flow.yearly.*",
    ],
    "dilutedSharesAliases": [
        "weightedAverageShsOutDil",
        "dilutedWeightedAverageShares",
        "weightedAverageSharesDiluted",
    ],
}

MISSING_OR_UNPROVEN_CAPABILITIES = [
    {
        "requirementId": "EXPLICIT_DURATION_CONTRACT",
        "minimumRequirement": (
            "For each quarterly and yearly duration value: periodStart, periodEnd, "
            "explicit 3M/YTD/12M/TTM classification, unit, currency, and fiscal "
            "period identity."
        ),
        "providerState": "VALUE_FIELDS_EXIST_METADATA_NOT_OBSERVED_OR_DOCUMENTED",
        "issueType": "PUBLIC_DOCUMENTATION_AMBIGUITY_AND_MODEL_EVIDENCE_REQUIREMENT",
    },
    {
        "requirementId": "CURRENT_INTEREST_TTM",
        "minimumRequirement": (
            "A current TTM interestExpense value or four explicitly discrete 3M "
            "gross-interest values ending at the current fiscal period."
        ),
        "providerState": "INTEREST_FIELD_EXISTS_EXPLICIT_TTM_PATH_NOT_OBSERVED",
        "issueType": "PROVIDER_COVERAGE_AND_PUBLIC_DOCUMENTATION_AMBIGUITY",
    },
    {
        "requirementId": "HISTORICAL_TTM_ENDPOINTS",
        "minimumRequirement": (
            "Comparable TTM endpoints 1,000 through 1,200 days apart for diluted "
            "EPS, gross profit, revenue, operating income, CFO, capex, and diluted "
            "weighted-average shares when required by a security."
        ),
        "providerState": "CURRENT_HIGHLIGHTS_EXIST_HISTORICAL_TTM_SERIES_NOT_OBSERVED",
        "issueType": "PROVIDER_COVERAGE_AND_MODEL_EVIDENCE_REQUIREMENT",
    },
    {
        "requirementId": "EIGHT_DISCRETE_QUARTERS",
        "minimumRequirement": (
            "Eight consecutive explicit 3M records for operating income, revenue, "
            "CFO, and capex, with non-overlapping periods and consistent units."
        ),
        "providerState": "HISTORICAL_VALUES_EXIST_DURATION_CLASS_UNPROVEN",
        "issueType": "PUBLIC_DOCUMENTATION_AMBIGUITY_AND_MODEL_EVIDENCE_REQUIREMENT",
    },
    {
        "requirementId": "AVAILABILITY_AND_REVISIONS",
        "minimumRequirement": (
            "Per-record publication or availability time, meaning of filing_date, "
            "revision/update behavior, and a stable revision or vintage identity."
        ),
        "providerState": "FILING_DATE_EXISTS_PUBLICATION_AND_REVISION_SEMANTICS_UNPROVEN",
        "issueType": "PUBLIC_DOCUMENTATION_AMBIGUITY_OR_MISSING_PROVIDER_CAPABILITY",
    },
]

EXAMPLE_EXPECTATIONS = [
    {
        "symbol": "TTC",
        "currentPeriodEnd": "2026-05-01",
        "historicalTtmEndRange": ["2023-01-17", "2023-08-05"],
        "needed": ["historical diluted EPS TTM", "current interest expense TTM"],
    },
    {
        "symbol": "AVGO",
        "currentPeriodEnd": "2026-05-03",
        "historicalTtmEndRange": ["2023-01-19", "2023-08-07"],
        "needed": [
            "current net income TTM",
            "historical diluted EPS TTM",
            "current interest expense TTM",
        ],
    },
    {
        "symbol": "HRL",
        "currentPeriodEnd": "2026-04-30",
        "historicalTtmEndRange": ["2023-01-16", "2023-08-04"],
        "needed": [
            "eight explicit 3M operating-income/revenue/CFO/capex records",
            "historical gross and operating margin TTM inputs",
            "current interest expense TTM",
        ],
    },
    {
        "symbol": "GPC",
        "currentPeriodEnd": "2026-06-30",
        "historicalTtmEndRange": ["2023-03-18", "2023-10-04"],
        "needed": [
            "current operating income or EBIT TTM",
            "eight explicit 3M operating-income/revenue/CFO/capex records",
            "historical operating-margin TTM inputs",
            "current interest expense TTM",
        ],
    },
    {
        "symbol": "ADSK",
        "currentPeriodEnd": "2026-04-30",
        "historicalTtmEndRange": ["2023-01-16", "2023-08-04"],
        "needed": [
            "current operating income, pretax income, income tax, and net income TTM",
            "current CFO, capex, and diluted weighted-average shares",
            "historical gross and operating margin TTM inputs",
            "current interest expense TTM",
        ],
    },
]

OPERAND_TO_SOURCE_REQUIREMENTS = {
    "interest_expense_ttm": ["current_ttm:interestExpense"],
    "diluted_eps_three_year_prior": ["historical_ttm:dilutedEps"],
    "net_income_ttm": ["current_ttm:netIncome"],
    "operating_income_ttm": ["current_ttm:operatingIncome"],
    "ebit_ttm": ["current_ttm:operatingIncome"],
    "pretax_income_ttm": ["current_ttm:incomeBeforeTax"],
    "income_tax_ttm": ["current_ttm:incomeTaxExpense"],
    "operating_cash_flow_ttm": [
        "current_ttm:totalCashFromOperatingActivities"
    ],
    "capital_expenditure_ttm": ["current_ttm:capitalExpenditures"],
    "diluted_weighted_average_shares_current": [
        "current_ttm:dilutedWeightedAverageShares"
    ],
    "fcf_ttm": [
        "current_ttm:totalCashFromOperatingActivities",
        "current_ttm:capitalExpenditures",
    ],
    "fcf_per_diluted_share_current": [
        "current_ttm:totalCashFromOperatingActivities",
        "current_ttm:capitalExpenditures",
        "current_ttm:dilutedWeightedAverageShares",
    ],
    "fcf_per_diluted_share_three_year_prior": [
        "historical_ttm:totalCashFromOperatingActivities",
        "historical_ttm:capitalExpenditures",
        "historical_ttm:dilutedWeightedAverageShares",
    ],
    "operating_margin_ttm": [
        "current_ttm:operatingIncome",
        "current_ttm:totalRevenue",
    ],
    "gross_margin_three_year_change": [
        "historical_ttm:grossProfit",
        "historical_ttm:totalRevenue",
    ],
    "operating_margin_three_year_change": [
        "historical_ttm:operatingIncome",
        "historical_ttm:totalRevenue",
    ],
    "eight_aligned_discrete_operating_margins": [
        "eight_explicit_3m:operatingIncome",
        "eight_explicit_3m:totalRevenue",
    ],
    "eight_aligned_discrete_fcf_margins": [
        "eight_explicit_3m:totalCashFromOperatingActivities",
        "eight_explicit_3m:capitalExpenditures",
        "eight_explicit_3m:totalRevenue",
    ],
}


def _without_hash(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in artifact.items()
        if key != "artifactContentHash"
    }


def load_verified(
    path: Path,
    *,
    expected_file_sha: str,
    expected_content_hash: str,
) -> dict[str, Any]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest().upper() != expected_file_sha:
        raise ValueError("SOURCE_FILE_HASH_MISMATCH")
    artifact = json.loads(raw)
    if artifact.get("artifactContentHash") != expected_content_hash:
        raise ValueError("SOURCE_EMBEDDED_CONTENT_HASH_MISMATCH")
    if canonical_hash(_without_hash(artifact)) != expected_content_hash:
        raise ValueError("SOURCE_CANONICAL_CONTENT_HASH_MISMATCH")
    return artifact


def residual_operand_counts(plan: dict[str, Any]) -> dict[str, int]:
    by_symbol: dict[str, set[str]] = {}
    for security in plan["residualMatrix"]:
        operands = {
            blocker["operand"]
            for factor in security["residualFactors"]
            for blocker in factor["blockers"]
        }
        by_symbol[security["symbol"]] = operands
    counts = Counter(
        operand
        for operands in by_symbol.values()
        for operand in operands
    )
    return dict(sorted(counts.items()))


def primitive_requirements_by_symbol(
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    result = []
    for security in plan["residualMatrix"]:
        blockers = {
            blocker["operand"]
            for factor in security["residualFactors"]
            for blocker in factor["blockers"]
        }
        primitives = sorted(
            {
                requirement
                for blocker in blockers
                for requirement in OPERAND_TO_SOURCE_REQUIREMENTS[blocker]
            }
        )
        result.append(
            {
                "symbol": security["symbol"],
                "residualOperands": sorted(blockers),
                "minimumSourceRequirements": primitives,
            }
        )
    return result


def build_decision(
    manifest: dict[str, Any],
    residual: dict[str, Any],
    *,
    manifest_reference: dict[str, str],
    residual_reference: dict[str, str],
) -> dict[str, Any]:
    if manifest["currentQcInputReadyCount"] != 6:
        raise ValueError("UNEXPECTED_CURRENT_QC_READY_COUNT")
    if residual["targetCount"] != 14 or len(residual["targetSymbols"]) != 14:
        raise ValueError("RESIDUAL_TARGET_SCOPE_INVALID")
    if residual["boundedYahooPreflight"]["networkRequestsExecuted"] != 0:
        raise ValueError("RESIDUAL_PLAN_NETWORK_EXECUTION_NOT_ZERO")
    if residual["boundedYahooPreflight"][
        "predictedBestCaseCurrentQcInputReadyCount"
    ] != 7:
        raise ValueError("UNEXPECTED_YAHOO_BEST_CASE_COUNT")

    decision = {
        "artifactType": "OBJECTIVE_RATING_V1_QC_DATA_SOURCE_DECISION",
        "schemaVersion": "objective-rating-v1-qc-data-source-decision-v1",
        "decisionVersion": DECISION_VERSION,
        "sourceArtifacts": {
            "currentFactorManifest": manifest_reference,
            "residualEvidencePlan": residual_reference,
        },
        "reassemblyDecision": {
            "status": "ACCEPTED_METHOD_CONFORMANT_COHORT_INSUFFICIENT",
            "currentQcInputReadyCount": 6,
            "minimumRequired": 20,
            "additionalConflictFreeSecuritiesRequired": 14,
            "boundedYahooTtcBestCaseReadyCount": 7,
            "algorithmGateAuthorized": False,
        },
        "residualTargetSymbols": residual["targetSymbols"],
        "uniqueResidualOperandSecurityCounts": residual_operand_counts(residual),
        "primitiveRequirementsBySymbol": primitive_requirements_by_symbol(
            residual
        ),
        "smallestDataSourceRequirements": MISSING_OR_UNPROVEN_CAPABILITIES,
        "existingEodhdAllInOneValuePaths": EXISTING_EODHD_VALUE_PATHS,
        "notObservedInCurrentPayloadContract": [
            "periodStart",
            "explicit duration type per record",
            "historical TTM diluted EPS series",
            "per-record provider publication or availability timestamp",
            "immutable revision or vintage identifier",
        ],
        "resolvedQuestionsNotToRepeat": [
            "provider-normalized current total debt",
            "Highlights.EBITDA current TTM",
            "Highlights.RevenueTTM current TTM",
            "Highlights.GrossProfitTTM current TTM",
            "Highlights.DilutedEpsTTM current TTM",
        ],
        "reproducibleExamples": EXAMPLE_EXPECTATIONS,
        "supportAnswerAcceptance": {
            "requiredForm": [
                "exact endpoint URL template without an API token",
                "exact JSON path and data type",
                "explicit period semantics",
                "historical coverage statement",
                "revision and update behavior",
                "plan entitlement or required add-on",
                "documentation version or effective date",
            ],
            "verbalAssuranceWithoutPathsOrSemanticsAccepted": False,
        },
        "fallbackCapabilityEvaluation": [
            "standardized US fundamentals with explicit periodStart and periodEnd",
            "explicit 3M, YTD, 12M, and TTM duration classification",
            "at least eight quarters of raw income-statement and cash-flow history",
            "comparable historical TTM diluted EPS and weighted diluted shares",
            "currency, unit, and split-adjustment metadata",
            "per-record publication availability and revision or vintage lineage",
            "stable security identifiers and licensed local snapshot retention",
        ],
        "networkRequestsExecuted": False,
        "scoresOrRanksGenerated": False,
        "forwardValidationExecuted": False,
        "formulaWeightCohortOrMissingRuleChanges": False,
    }
    decision["artifactContentHash"] = canonical_hash(decision)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--manifest-file-sha", required=True)
    parser.add_argument("--manifest-content-hash", required=True)
    parser.add_argument("--residual-plan", required=True, type=Path)
    parser.add_argument("--residual-file-sha", required=True)
    parser.add_argument("--residual-content-hash", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = load_verified(
        args.manifest,
        expected_file_sha=args.manifest_file_sha,
        expected_content_hash=args.manifest_content_hash,
    )
    residual = load_verified(
        args.residual_plan,
        expected_file_sha=args.residual_file_sha,
        expected_content_hash=args.residual_content_hash,
    )
    decision = build_decision(
        manifest,
        residual,
        manifest_reference={
            "path": args.manifest.as_posix(),
            "fileSha256": args.manifest_file_sha,
            "artifactContentHash": args.manifest_content_hash,
        },
        residual_reference={
            "path": args.residual_plan.as_posix(),
            "fileSha256": args.residual_file_sha,
            "artifactContentHash": args.residual_content_hash,
        },
    )
    write_immutable_json(args.output, decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
