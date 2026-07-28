from __future__ import annotations

import pytest

from equity_analysis.provider_validation.qc_cohort_feasibility import (
    _rank_key,
    _safe_operand_evidence,
    classify_resolution_route,
)


def test_interest_routes_distinguish_accepted_conflict_and_unchecked() -> None:
    accepted = classify_resolution_route(
        operand="interest_expense_ttm",
        reason_code="LATEST_DISCRETE_TTM_WINDOW_IS_STALE",
        eodhd_current_field_present=False,
        provider_interest_classification="CROSS_PROVIDER_TTM_CONFIRMED",
    )
    assert accepted["category"] == "FIXABLE_FROM_EXISTING_APPROVED_EVIDENCE"

    conflict = classify_resolution_route(
        operand="interest_expense_ttm",
        reason_code="PROVIDER_CONFLICT",
        eodhd_current_field_present=False,
        provider_interest_classification="PROVIDER_VALUE_CONFLICT",
    )
    assert conflict["category"] == "BLOCKED_SEMANTICS_HISTORY_OR_SUPPORT"

    unchecked = classify_resolution_route(
        operand="interest_expense_ttm",
        reason_code="LATEST_DISCRETE_TTM_WINDOW_IS_STALE",
        eodhd_current_field_present=False,
        provider_interest_classification=None,
    )
    assert unchecked["category"] == (
        "POTENTIAL_DOCUMENTED_CURRENT_FIELD_OR_BOUNDED_CONFIRMATION"
    )


def test_explicit_current_field_requires_methodology_ruling() -> None:
    route = classify_resolution_route(
        operand="diluted_eps_current",
        reason_code="CURRENT_DILUTED_EPS_INPUT_WINDOW_MISSING",
        eodhd_current_field_present=True,
        provider_interest_classification=None,
    )
    assert route == {
        "category": (
            "POTENTIAL_DOCUMENTED_CURRENT_FIELD_OR_BOUNDED_CONFIRMATION"
        ),
        "reasonCode": "EXPLICIT_EODHD_CURRENT_FIELD_PRESENT_NOT_AUTHORIZED",
        "methodologyRulingRequired": True,
    }


def test_history_gap_is_not_reclassified_as_parser_fix() -> None:
    route = classify_resolution_route(
        operand="diluted_eps_three_year_prior",
        reason_code="THREE_YEAR_PRIOR_DILUTED_EPS_INPUT_WINDOW_MISSING",
        eodhd_current_field_present=False,
        provider_interest_classification=None,
    )
    assert route["category"] == "BLOCKED_SEMANTICS_HISTORY_OR_SUPPORT"
    assert route["methodologyRulingRequired"] is True


def test_git_safe_operand_evidence_excludes_values() -> None:
    safe = _safe_operand_evidence(
        {
            "status": "MISSING",
            "reasonCode": "NOT_AVAILABLE",
            "periodIds": ["2025-01-01:2025-03-31"],
            "availableAt": None,
            "sourceAccessions": ["0000000000-25-000001"],
            "sourceContentHashes": ["A" * 64],
            "orderedEvidenceIds": ["evidence-1"],
            "derivationLineage": None,
            "value": "123456789",
            "unit": "USD",
        }
    )
    assert safe["status"] == "MISSING"
    assert "value" not in safe
    assert "123456789" not in str(safe)


def test_invalid_artifact_decision_is_never_silently_fixable() -> None:
    route = classify_resolution_route(
        operand="gross_profit_ttm",
        reason_code="UNRECOGNIZED_EVIDENCE_STATE",
        eodhd_current_field_present=False,
        provider_interest_classification=None,
    )
    assert route["category"] == "BLOCKED_SEMANTICS_HISTORY_OR_SUPPORT"
    assert route["reasonCode"] == "NO_APPROVED_OFFLINE_COMPLETION_ROUTE"


def test_minimum_path_penalizes_confirmed_provider_conflict() -> None:
    def record(symbol: str, reason: str) -> dict:
        return {
            "symbol": symbol,
            "qcFactorBlockers": [
                {
                    "factor": "interest_coverage",
                    "blockers": [
                        {
                            "operand": "interest_expense_ttm",
                            "resolutionRoute": {
                                "category": (
                                    "BLOCKED_SEMANTICS_HISTORY_OR_SUPPORT"
                                ),
                                "reasonCode": reason,
                            },
                        }
                    ],
                }
            ],
        }

    history = record(
        "HISTORY",
        "REQUIRED_CURRENT_OR_HISTORICAL_WINDOW_NOT_PROVEN",
    )
    conflict = record("CONFLICT", "EXISTING_CROSS_PROVIDER_VALUE_CONFLICT")
    assert _rank_key(history) < _rank_key(conflict)


@pytest.mark.parametrize(
    "operand",
    [
        "minimum_12_monthly_pit_fcf_yields",
        "earnings_yield_cohort_percentile",
    ],
)
def test_uq_only_operands_are_not_promoted_to_qc_routes(operand: str) -> None:
    route = classify_resolution_route(
        operand=operand,
        reason_code="HISTORICAL_ONLY",
        eodhd_current_field_present=False,
        provider_interest_classification=None,
    )
    assert route["category"] == "BLOCKED_SEMANTICS_HISTORY_OR_SUPPORT"
