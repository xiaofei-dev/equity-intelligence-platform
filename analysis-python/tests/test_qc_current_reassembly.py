import json
from pathlib import Path

from equity_analysis.provider_validation.expansion_gate import canonical_hash
from equity_analysis.provider_validation.qc_current_reassembly import (
    FRESHNESS_DAYS,
)
from equity_analysis.provider_validation.qc_residual_evidence_plan import (
    _route,
)


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_reassembled_manifest_applies_policy_and_removes_csco() -> None:
    path = (
        _root()
        / "docs/generated/objective-rating-v1-current-factor-input-manifest-v1-7.json"
    )
    artifact = json.loads(path.read_text(encoding="utf-8"))
    assert artifact["artifactContentHash"] == canonical_hash(
        {
            key: value
            for key, value in artifact.items()
            if key != "artifactContentHash"
        }
    )
    assert FRESHNESS_DAYS == 150
    assert artifact["currentQcInputReadyCount"] == 6
    assert artifact["currentQcInputReadySymbols"] == [
        "AMAT",
        "CIEN",
        "COO",
        "DHR",
        "FAST",
        "TSN",
    ]
    assert "CSCO" not in artifact["currentQcInputReadySymbols"]


def test_operating_margin_provider_ratio_remains_rejected() -> None:
    manifest = json.loads(
        (
            _root()
            / "docs/generated/objective-rating-v1-current-factor-input-manifest-v1-7.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["windowRules"]["rejectedFormulaSubstitutes"] == [
        "Highlights.OperatingMarginTTM"
    ]


def test_yahoo_routes_are_narrow_and_do_not_accept_annual_eps() -> None:
    interest = _route("interest_expense_ttm")
    assert interest["bestCaseResolvable"] is True
    assert interest["authorizedTypes"] == [
        "quarterlyInterestExpense",
        "trailingInterestExpense",
    ]
    eps = _route("diluted_eps_three_year_prior")
    assert eps["bestCaseResolvable"] is True
    assert "annualDilutedEps" not in eps["authorizedTypes"]
    assert _route("operating_income_ttm")["bestCaseResolvable"] is False


def test_residual_preflight_fails_before_spending_calls() -> None:
    artifact = json.loads(
        (
            _root()
            / "docs/generated/objective-rating-v1-qc-residual-evidence-plan-v1.json"
        ).read_text(encoding="utf-8")
    )
    preflight = artifact["boundedYahooPreflight"]
    assert preflight["status"] == "DO_NOT_EXECUTE_COHORT_COMPLETION_PRECHECK_FAIL"
    assert preflight["symbols"] == ["TTC"]
    assert preflight["physicalHttpAttemptCeiling"] == 1
    assert preflight["maxRetries"] == 0
    assert preflight["networkRequestsExecuted"] == 0
    assert preflight["predictedBestCaseCurrentQcInputReadyCount"] == 7
    assert artifact["networkRequestsExecuted"] is False
