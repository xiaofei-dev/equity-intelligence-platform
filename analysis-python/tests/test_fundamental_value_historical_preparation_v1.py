import json
from dataclasses import replace
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.historical_preparation_v1 import (
    PreparationState,
    build_coverage_feasibility,
    build_daily_path_contract,
    build_diagnostic_inputs,
    build_execution_preparation,
    build_operand_feasibility,
    build_predictor_registry,
    build_preparation_manifest,
    build_raw_source_feasibility,
    build_universe_source_manifest,
    canonical_hash,
    evaluate_target_component_diagnostic,
    extract_target_component,
)
from equity_analysis.fundamental_value.historical_validation_v1 import (
    HistoricalValidationError,
    PredictorContract,
    PredictorTarget,
    validate_predictor_contract,
)


def test_universe_manifest_is_honestly_blocked_and_preflight_denies_network() -> None:
    value = build_universe_source_manifest()
    assert value["state"] == PreparationState.FROZEN_UNIVERSE_SOURCE_BLOCKED
    assert value["realSecurityCount"] == 0
    assert value["old300FixtureAccepted"] is False
    assert value["singleRequestPreflight"]["networkAuthorized"] is False
    body = dict(value)
    claimed = body.pop("contentHash")
    assert claimed == canonical_hash(body)


def test_predictors_freeze_four_distinct_stage2_paths_without_risk_cap() -> None:
    values = build_predictor_registry()
    assert [item.target for item in values] == [
        "COMPANY_QUALITY", "SECURITY_ATTRACTIVENESS_MARGIN_OF_SAFETY",
        "EXPECTED_RETURN", "DOWNSIDE_RISK"]
    assert [item.higher_is_better for item in values] == [True, True, True, False]
    assert all("risk_cap" not in item.source_field_path for item in values)
    assert len({item.mapping_content_hash for item in values}) == 4
    assert values[1].source_field_path == "margin_of_safety.low"
    assert all(item.projection_years == 3 for item in values)


def test_predictor_hash_aligns_with_validation_contract_and_exact_path() -> None:
    mapping = build_predictor_registry()[0]
    contract = PredictorContract(
        "stage7-company-quality", mapping.model_version, PredictorTarget.COMPANY_QUALITY,
        mapping.mapping_version, mapping.mapping_content_hash,
        "FundamentalValueAssessmentV1 target component", mapping.eligibility_definition,
        mapping.higher_is_better, mapping.source_field_path, mapping.formula_version,
        mapping.assumption_version, mapping.projection_years, mapping.aggregation_version,
        mapping.binary_condition_paths, accepted_by_master=True)
    validate_predictor_contract(contract)
    with pytest.raises(ValueError, match="UNKNOWN_TYPED_TARGET_SOURCE_PATH"):
        assessment, _ = evaluate_target_component_diagnostic({})
        extract_target_component(assessment, replace(mapping, source_field_path="bad.path"))
    with pytest.raises(ValueError, match="TARGET_MODEL_VERSION_BINDING_MISMATCH"):
        extract_target_component(replace(assessment, formula_version="changed"), mapping)
    with pytest.raises(HistoricalValidationError, match="MAPPING_CONTENT_HASH_MISMATCH"):
        validate_predictor_contract(replace(contract, source_field_path="changed.path"))
    with pytest.raises(HistoricalValidationError, match="MAPPING_CONTENT_HASH_MISMATCH"):
        validate_predictor_contract(replace(contract, aggregation_version="changed"))
    with pytest.raises(HistoricalValidationError, match="MAPPING_CONTENT_HASH_MISMATCH"):
        validate_predictor_contract(replace(contract, binary_condition_paths=("changed:code",)))


def test_diagnostic_adapter_builds_all_missing_and_admits_only_valid_component() -> None:
    inputs = build_diagnostic_inputs({})
    assert inputs.projection_years == 3
    assessment, targets = evaluate_target_component_diagnostic({})
    assert assessment.projection_years == 3
    assert all(item["admitted"] is False for item in targets)
    assert all(item["claimLabel"] == "DEVELOPMENT_OBSERVED" for item in targets)


def test_operand_feasibility_preserves_all_34_missing_states_and_stops_canary() -> None:
    value = build_operand_feasibility({"controlled": "A" * 64})
    assert value["operandCount"] == 34
    assert value["usableRequiredOperandCount"] == 0
    assert value["canaryEndpointSet"] == []
    assert value["state"] == PreparationState.BLOCKED_BY_OPERAND_EVIDENCE
    assert all(item["terminalState"] in {"MISSING", "NOT_APPLICABLE"}
               for item in value["operands"])


def test_daily_path_and_execution_remain_blocked_without_calculation_or_network() -> None:
    path = build_daily_path_contract()
    execution = build_execution_preparation()
    assert path["calculationAuthorized"] is False
    assert path["state"] == PreparationState.BLOCKED_DAILY_PATH_REQUIRED
    assert execution["networkAuthorized"] is False
    assert execution["matrixState"] == "ABSENT_UNTIL_EXACT_310_IDS_ARE_FROZEN"


def test_complete_preparation_manifest_is_deterministic_and_outcome_blind() -> None:
    root = Path(__file__).resolve().parents[2]
    first = build_preparation_manifest(root)
    second = build_preparation_manifest(root)
    assert first == second
    assert first["outcomesInspected"] is False
    body = dict(first)
    claimed = body.pop("contentHash")
    assert claimed == canonical_hash(body)
    fixture = json.loads((root / "contracts/fundamental-value-historical-validation-v1"
        / "stage7c-preparation-manifest.json").read_text(encoding="utf-8"))
    summary = dict(fixture)
    summary_hash = summary.pop("summaryContentHash")
    assert summary_hash == canonical_hash(summary)
    assert fixture["preparationContentHash"] == first["contentHash"]
    assert fixture["universeContentHash"] == first["universe"]["contentHash"]
    assert fixture["predictors"] == json.loads(json.dumps(first["predictors"]))
    assert fixture["operandFeasibilityContentHash"] == first["operandFeasibility"]["contentHash"]
    assert fixture["coverageFeasibilityContentHash"] == first["coverageFeasibility"]["contentHash"]
    assert fixture["rawSourceFeasibilityContentHash"] == (
        first["rawSourceFeasibility"]["contentHash"])
    assert fixture["dailyPathContentHash"] == first["dailyPath"]["contentHash"]
    assert fixture["executionContentHash"] == first["execution"]["contentHash"]


def test_coverage_feasibility_verifies_artifact_and_reports_36_zero_coverage_cells() -> None:
    root = Path(__file__).resolve().parents[2]
    value = build_coverage_feasibility(root)
    assert len(value["acceptedTargetCoverage"]) == 36
    assert all(item["securityCount"] == 100 and item["usableCount"] == 0
               for item in value["acceptedTargetCoverage"])
    assert value["performanceOutcomesRead"] is False
    assert value["goNoGo"] == "NO_GO_FOR_310_OR_ACQUISITION"
    distribution = next(item for item in value["candidateDerivedProducers"]
                        if item["operand"] == "shareholder_distribution_coverage")
    assert distribution["parents"][-2:] == ["cash_dividends_paid", "share_repurchases"]
    assert distribution["coverageDenominator"] == "free_cash_flow"


def test_raw_source_feasibility_is_hash_verified_and_separate_from_q2_coverage() -> None:
    root = Path(__file__).resolve().parents[2]
    value = build_raw_source_feasibility(root)
    assert value["outcomesRead"] is False
    assert value["stage7FrozenQ2DateCoverage"].startswith("NOT_MEASURED")
    assert value["secV4SecurityCount"] == 223
    assert len(value["anchors"]) == 4
    assert all(item["candidateCount"] == 55 for item in value["anchors"])
