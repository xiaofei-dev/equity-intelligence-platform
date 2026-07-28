import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from equity_analysis.provider_validation.current_interest_integration import (
    ACCEPTED_CLASSIFICATIONS,
    apply_interest_decision,
    build_interest_supplement,
)
from equity_analysis.provider_validation.expansion_gate import canonical_hash


def _base_snapshot() -> dict:
    factor = {
        "status": "MISSING",
        "reasonCode": "MISSING_REQUIRED_OPERANDS",
        "requiredOperands": ["ebit_ttm", "interest_expense_ttm"],
        "blockingOperands": ["interest_expense_ttm"],
    }
    return {
        "schemaVersion": "old",
        "cutoff": "2026-07-27T23:59:59Z",
        "symbol": "AMAT",
        "operands": {
            "ebit_ttm": {"status": "VALID", "value": "100"},
            "interest_expense_ttm": {
                "status": "MISSING",
                "reasonCode": "STALE",
            },
        },
        "qcFactors": {"interest_coverage": deepcopy(factor)},
        "uqFactors": {
            "interest_coverage": deepcopy(factor),
            "historical_fcf_yield_percentile": {
                "status": "MISSING",
                "reasonCode": "MISSING_REQUIRED_OPERANDS",
                "requiredOperands": ["minimum_12_monthly_pit_fcf_yields"],
                "blockingOperands": ["minimum_12_monthly_pit_fcf_yields"],
            },
        },
        "currentQcInputReady": False,
        "currentUqInputReady": False,
        "contentHash": "A" * 64,
    }


def _provider_result(classification: str) -> dict:
    return {
        "symbol": "AMAT",
        "classification": classification,
        "latestFourQuarterPeriodEnds": [
            "2025-07-31",
            "2025-10-31",
            "2026-01-31",
            "2026-04-30",
        ],
        "controlledComparisonHash": "B" * 64,
        "rawYahooResponseHash": "C" * 64,
        "controlledComparisonStorageReference": "storage/controlled.json",
        "rawYahooStorageReference": "storage/raw.json",
    }


def _controlled() -> dict:
    return {
        "eodhdFourQuarterSum": "100",
        "yahooTtmValue": "100",
        "currency": "USD",
        "yahooTtmPeriodEnd": "2026-04-30",
        "quarterPeriodEnds": [
            "2025-07-31",
            "2025-10-31",
            "2026-01-31",
            "2026-04-30",
        ],
        "eodhdNormalizedContentHash": "D" * 64,
        "yahooNormalizedContentHash": "E" * 64,
    }


def _provider_artifact() -> dict:
    return {
        "generatedAt": "2026-07-28T07:55:16Z",
        "artifactContentHash": "F" * 64,
    }


def test_accepted_interest_updates_only_current_operand_and_factors() -> None:
    result = _provider_result("CROSS_PROVIDER_TTM_CONFIRMED")
    supplement = build_interest_supplement(
        provider_result=result,
        controlled=_controlled(),
        provider_artifact=_provider_artifact(),
    )
    payload = apply_interest_decision(
        base_snapshot=_base_snapshot(),
        provider_result=result,
        supplement=supplement,
        cutoff=_provider_artifact()["generatedAt"],
    )
    assert payload["operands"]["interest_expense_ttm"]["status"] == "VALID"
    assert payload["qcFactors"]["interest_coverage"]["status"] == "VALID"
    assert payload["currentQcInputReady"] is True
    assert payload["currentUqInputReady"] is False
    assert supplement["historicalPitAuthorized"] is False
    assert supplement["quarterHistoryAuthorized"] is False
    assert supplement["grossEconomicScopeProven"] is False
    assert payload["contentHash"] == canonical_hash(
        {key: value for key, value in payload.items() if key != "contentHash"}
    )


def test_cien_risk_flag_is_retained_without_authorizing_quarters() -> None:
    result = _provider_result("YAHOO_INTERNAL_REVISION_INCONSISTENCY")
    assert result["classification"] in ACCEPTED_CLASSIFICATIONS
    supplement = build_interest_supplement(
        provider_result=result,
        controlled=_controlled(),
        provider_artifact=_provider_artifact(),
    )
    assert supplement["riskFlags"] == ["YAHOO_QUARTER_SERIES_CONFLICT"]
    assert supplement["quarterHistoryAuthorized"] is False


def test_provider_conflict_remains_missing() -> None:
    result = _provider_result("PROVIDER_VALUE_CONFLICT")
    payload = apply_interest_decision(
        base_snapshot=_base_snapshot(),
        provider_result=result,
        supplement=None,
        cutoff=_provider_artifact()["generatedAt"],
    )
    assert payload["operands"]["interest_expense_ttm"]["status"] == "MISSING"
    assert (
        payload["operands"]["interest_expense_ttm"]["reasonCode"]
        == "PROVIDER_CONFLICT"
    )
    assert payload["currentQcInputReady"] is False


def test_formal_acceptance_and_integration_gate_hash_chain() -> None:
    root = Path(__file__).resolve().parents[2]
    acceptance_path = (
        root
        / "docs/generated/"
        "objective-rating-v1-cross-provider-current-interest-acceptance-v1.json"
    )
    gate_path = (
        root
        / "docs/generated/"
        "objective-rating-v1-current-interest-integration-gate-v1.json"
    )
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    for artifact in (acceptance, gate):
        assert artifact["artifactContentHash"] == canonical_hash(
            {
                key: value
                for key, value in artifact.items()
                if key != "artifactContentHash"
            }
        )
    for source_key in (
        "sourcePolicy",
        "sourceAcceptance",
        "factorInputManifest",
    ):
        source = gate[source_key]
        path = root / source["path"]
        assert sha256(path.read_bytes()).hexdigest().upper() == source[
            "fileSha256"
        ]
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["artifactContentHash"] == source["contentHash"]
    assert gate["currentInputReadiness"]["qcCount"] == 7
    assert gate["currentInputReadiness"]["uqCount"] == 0
    assert gate["cohortGate"]["status"] == "COHORT_TOO_SMALL"
    assert (
        gate["algorithmGateStatus"]
        == "NOT_EXECUTED_COHORT_TOO_SMALL"
    )
