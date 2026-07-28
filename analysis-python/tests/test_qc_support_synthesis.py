import json
from pathlib import Path

from equity_analysis.provider_validation.expansion_gate import canonical_hash
from equity_analysis.provider_validation.qc_support_synthesis import (
    build_decision,
    primitive_requirements_by_symbol,
    residual_operand_counts,
)


def test_residual_counts_deduplicate_factor_reuse_within_security() -> None:
    plan = {
        "residualMatrix": [
            {
                "symbol": "A",
                "residualFactors": [
                    {"blockers": [{"operand": "ebit_ttm"}]},
                    {"blockers": [{"operand": "ebit_ttm"}]},
                ],
            },
            {
                "symbol": "B",
                "residualFactors": [
                    {"blockers": [{"operand": "interest_expense_ttm"}]}
                ],
            },
        ]
    }
    assert residual_operand_counts(plan) == {
        "ebit_ttm": 1,
        "interest_expense_ttm": 1,
    }
    assert primitive_requirements_by_symbol(plan) == [
        {
            "symbol": "A",
            "residualOperands": ["ebit_ttm"],
            "minimumSourceRequirements": ["current_ttm:operatingIncome"],
        },
        {
            "symbol": "B",
            "residualOperands": ["interest_expense_ttm"],
            "minimumSourceRequirements": ["current_ttm:interestExpense"],
        },
    ]


def test_decision_keeps_gate_closed_when_yahoo_best_case_is_seven() -> None:
    manifest = {"currentQcInputReadyCount": 6}
    residual = {
        "targetCount": 14,
        "targetSymbols": [f"S{index}" for index in range(14)],
        "residualMatrix": [
            {
                "symbol": f"S{index}",
                "residualFactors": [
                    {"blockers": [{"operand": "interest_expense_ttm"}]}
                ],
            }
            for index in range(14)
        ],
        "boundedYahooPreflight": {
            "networkRequestsExecuted": 0,
            "predictedBestCaseCurrentQcInputReadyCount": 7,
        },
    }
    decision = build_decision(
        manifest,
        residual,
        manifest_reference={},
        residual_reference={},
    )
    assert decision["reassemblyDecision"]["algorithmGateAuthorized"] is False
    assert decision["networkRequestsExecuted"] is False
    assert decision["formulaWeightCohortOrMissingRuleChanges"] is False


def test_generated_decision_is_hash_stable_and_contains_five_examples() -> None:
    root = Path(__file__).resolve().parents[2]
    path = (
        root
        / "docs/generated/objective-rating-v1-qc-data-source-decision-v1.json"
    )
    artifact = json.loads(path.read_text(encoding="utf-8"))
    assert artifact["artifactContentHash"] == canonical_hash(
        {
            key: value
            for key, value in artifact.items()
            if key != "artifactContentHash"
        }
    )
    assert artifact["reassemblyDecision"]["currentQcInputReadyCount"] == 6
    assert artifact["reassemblyDecision"][
        "additionalConflictFreeSecuritiesRequired"
    ] == 14
    assert len(artifact["reproducibleExamples"]) == 5
    assert artifact["scoresOrRanksGenerated"] is False
