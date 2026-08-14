from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.contracts_v1 import (
    FundamentalValueContractViolation,
    FundamentalValueDecisionContractV1,
)
from equity_analysis.fundamental_value.core_v1 import (
    ASSUMPTION_POLICY_VERSION,
    FORMULA_VERSION,
)

FIXTURE = (
    Path(__file__).parents[2]
    / "contracts"
    / "fundamental-value-v1"
    / "decision-contract.example.json"
)


def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def reseal(candidate: dict) -> dict:
    hash_payload = {key: value for key, value in candidate.items() if key != "contractContentHash"}
    canonical = json.dumps(
        hash_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    candidate["contractContentHash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    return candidate


def test_canonical_contract_fixture_is_accepted() -> None:
    contract = FundamentalValueDecisionContractV1.parse(payload())
    assert contract.payload["sleeve"] == "LONG_TERM_CORE"
    assert contract.payload["validationGovernance"]["initialModelEvidenceLabel"] == "NOT_VALIDATED"


def test_normative_fixture_versions_match_pure_core_constants() -> None:
    version_set = payload()["versionSet"]
    assert version_set["formulaVersion"] == FORMULA_VERSION
    assert version_set["assumptionPolicyVersion"] == ASSUMPTION_POLICY_VERSION


@pytest.mark.parametrize(
    ("company_type", "applicability"),
    (
        ("BANK", "SPECIALIZED_MODEL_REQUIRED"),
        ("INSURER", "SPECIALIZED_MODEL_REQUIRED"),
        ("REIT", "SPECIALIZED_MODEL_REQUIRED"),
        ("RESOURCE", "SPECIALIZED_MODEL_REQUIRED"),
        ("BIOTECHNOLOGY", "SPECIALIZED_MODEL_REQUIRED"),
        ("FINANCIAL", "SPECIALIZED_MODEL_REQUIRED"),
        ("INCOMPATIBLE_CONGLOMERATE", "SPECIALIZED_MODEL_REQUIRED"),
        ("BENCHMARK", "NOT_APPLICABLE"),
        ("INSUFFICIENT_PUBLIC_HISTORY", "INSUFFICIENT_EVIDENCE"),
    ),
)
def test_unsupported_company_types_fail_closed_without_generic_fallback(
    company_type: str, applicability: str
) -> None:
    candidate = payload()
    candidate["companyType"] = company_type
    candidate["applicability"] = applicability
    FundamentalValueDecisionContractV1.parse(reseal(candidate))
    candidate["applicability"] = "APPLICABLE"
    with pytest.raises(FundamentalValueContractViolation, match="fall back"):
        FundamentalValueDecisionContractV1.parse(candidate)


def test_nbn_bank_case_cannot_receive_generic_applicability() -> None:
    candidate = payload()
    candidate["companyType"] = "BANK"
    candidate["applicability"] = "APPLICABLE"
    candidate["exampleTicker"] = "NBN"
    with pytest.raises(FundamentalValueContractViolation, match="fall back"):
        FundamentalValueDecisionContractV1.parse(candidate)


def test_comparable_method_cannot_control_the_conclusion() -> None:
    candidate = payload()
    comparable = candidate["valuationMethods"][3]
    comparable["role"] = "PRIMARY"
    with pytest.raises(FundamentalValueContractViolation, match="cross-check"):
        FundamentalValueDecisionContractV1.parse(candidate)
    candidate = payload()
    candidate["valuationMethods"][3]["maximumAggregationWeight"] = "0.20"
    with pytest.raises(FundamentalValueContractViolation, match="cross-check"):
        FundamentalValueDecisionContractV1.parse(candidate)


def test_no_method_can_dominate_weighted_aggregation() -> None:
    candidate = payload()
    candidate["valuationMethods"][0]["maximumAggregationWeight"] = "0.51"
    with pytest.raises(FundamentalValueContractViolation, match="dominate"):
        FundamentalValueDecisionContractV1.parse(candidate)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("centralEstimator", "AVERAGE"),
        ("rangeEstimator", "MIN_MAX"),
        ("unrestrictedMinMaxAllowed", True),
    ),
)
def test_aggregation_policy_is_frozen(field: str, value: object) -> None:
    candidate = payload()
    candidate["aggregationPolicy"][field] = value
    with pytest.raises(FundamentalValueContractViolation):
        FundamentalValueDecisionContractV1.parse(candidate)


def test_missing_advanced_evidence_never_becomes_zero_or_silently_usable() -> None:
    candidate = payload()
    candidate["missingAdvancedEvidencePolicy"]["missingNeverBecomesZero"] = False
    with pytest.raises(FundamentalValueContractViolation, match="never become zero"):
        FundamentalValueDecisionContractV1.parse(candidate)
    candidate = payload()
    candidate["missingAdvancedEvidencePolicy"]["materialLeverageEffect"] = "LOWER_CONFIDENCE"
    with pytest.raises(FundamentalValueContractViolation, match="block valuation"):
        FundamentalValueDecisionContractV1.parse(candidate)


@pytest.mark.parametrize(
    "bad_tiers", (["0", "0.01", "0.03", "0.05"], ["0", "0.01", "0.02", "0.03", "0.05", "0.08"])
)
def test_risk_cap_tiers_are_exact_and_never_final_weights(bad_tiers: list[str]) -> None:
    candidate = payload()
    candidate["riskCapPolicy"]["allowedCeilings"] = bad_tiers
    with pytest.raises(FundamentalValueContractViolation, match="tiers"):
        FundamentalValueDecisionContractV1.parse(candidate)
    candidate = payload()
    candidate["riskCapPolicy"]["finalPortfolioWeightAllowed"] = True
    with pytest.raises(FundamentalValueContractViolation, match="final portfolio weight"):
        FundamentalValueDecisionContractV1.parse(candidate)


def test_ai_and_quantitative_trading_cannot_affect_deterministic_output() -> None:
    candidate = payload()
    candidate["quantitativeTradingInputAllowed"] = True
    with pytest.raises(FundamentalValueContractViolation, match="Quantitative Trading"):
        FundamentalValueDecisionContractV1.parse(candidate)
    for field in candidate["aiNarrativeBoundary"]:
        mutated = copy.deepcopy(payload())
        mutated["aiNarrativeBoundary"][field] = True
        with pytest.raises(FundamentalValueContractViolation, match="narrative-only"):
            FundamentalValueDecisionContractV1.parse(mutated)


def test_v23_is_narrow_append_only_and_future_raw_governance_moves_forward() -> None:
    for field in ("rawRetentionGovernanceIncluded", "deletionIncluded", "legalHoldIncluded"):
        candidate = payload()
        candidate["persistenceBoundary"][field] = True
        with pytest.raises(FundamentalValueContractViolation, match="excluded"):
            FundamentalValueDecisionContractV1.parse(candidate)
    candidate = payload()
    candidate["persistenceBoundary"]["reinterpretPriorMigrations"] = True
    with pytest.raises(FundamentalValueContractViolation, match="preserve"):
        FundamentalValueDecisionContractV1.parse(candidate)


@pytest.mark.parametrize("bad_value", ("NaN", "Infinity", "1e-2", 0.25, True))
def test_declared_decimals_fail_closed_without_json_coercion(bad_value: object) -> None:
    candidate = payload()
    candidate["aggregationPolicy"]["lowQuantile"] = bad_value
    with pytest.raises(FundamentalValueContractViolation):
        FundamentalValueDecisionContractV1.parse(candidate)


def test_historical_gate_can_fail_and_forward_requires_prior_acceptance() -> None:
    candidate = payload()
    candidate["validationGovernance"]["historicalGateMayConcludeNotValidated"] = False
    with pytest.raises(FundamentalValueContractViolation, match="NOT_VALIDATED"):
        FundamentalValueDecisionContractV1.parse(candidate)
    candidate = payload()
    candidate["validationGovernance"]["prospectiveAfterHistoricalAcceptanceOnly"] = False
    with pytest.raises(FundamentalValueContractViolation, match="sequencing"):
        FundamentalValueDecisionContractV1.parse(candidate)


def test_contract_content_hash_detects_semantic_drift() -> None:
    candidate = payload()
    candidate["versionSet"]["formulaVersion"] = "changed-without-resealing"
    with pytest.raises(FundamentalValueContractViolation, match="content hash"):
        FundamentalValueDecisionContractV1.parse(candidate)
