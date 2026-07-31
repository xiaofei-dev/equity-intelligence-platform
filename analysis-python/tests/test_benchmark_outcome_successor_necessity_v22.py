from __future__ import annotations

import json
from pathlib import Path

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_outcome_successor_necessity_v22 import (
    build_benchmark_outcome_successor_necessity_v1,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_successor_necessity_proves_ledger_ready_but_outcome_blocked() -> None:
    artifact = build_benchmark_outcome_successor_necessity_v1(
        REPOSITORY_ROOT
    )

    assert artifact["status"] == "SUCCESSOR_REQUIRED_BEFORE_FORMAL_OUTCOME"
    assert artifact["ledgerReadiness"]["status"] == "READY_CONTRACT_IMPLEMENTED"
    assert artifact["formalOutcomeSchemaReadiness"]["status"] == "BLOCKED"
    assert set(artifact["formalOutcomeSchemaReadiness"]["blockers"]) == {
        "V18_SECTOR_OUTCOME_NOT_SECURITY_SPECIFIC",
        "V18_BENCHMARK_VARIANT_ID_NOT_RETAINED",
        "GATE_H_MULTI_HOLDING_COST_INPUT_NOT_EXPRESSIBLE",
        "STATISTICS_SECTOR_RETURN_REUSED_ACROSS_ALL_SECURITIES",
    }
    assert all(artifact["sourceConstraintChecks"].values())
    assert artifact["requiredSuccessorDesign"]["migrationApplied"] is False
    assert artifact["databaseWrites"] == 0
    assert artifact["formalOutcomesComputed"] is False

    body = dict(artifact)
    claimed = body.pop("artifactContentHash")
    assert canonical_hash(body) == claimed


def test_successor_design_requires_per_security_sector_and_holding_cost() -> None:
    artifact = build_benchmark_outcome_successor_necessity_v1(
        REPOSITORY_ROOT
    )
    design = artifact["requiredSuccessorDesign"]
    table_names = {item["name"] for item in design["minimumTables"]}

    assert "analytics.forward_dqv_benchmark_ledger_v3" in table_names
    assert "analytics.forward_dqv_benchmark_family_v3" in table_names
    assert "analytics.forward_dqv_benchmark_variant_v3" in table_names
    assert "analytics.forward_dqv_benchmark_holding_v3" in table_names
    assert (
        "analytics.forward_dqv_benchmark_variant_outcome_v3" in table_names
    )
    assert (
        "analytics.forward_dqv_security_benchmark_binding_v3" in table_names
    )
    assert (
        "analytics.forward_dqv_benchmark_holding_outcome_v3" in table_names
    )
    assert "never average ADTV" in design["portfolioCostRule"]
    assert "each security" in design["sectorComparisonRule"]
    assert design["exact66BySixBindingCompletenessRequired"] is True
    assert design["existingOutcomeBatchHeaderReused"] is True
    assert set(design["requiredUpgradeTests"]) >= {
        "CLEAN_V1_TO_V20",
        "UPGRADE_V18_TO_V20",
        "UPGRADE_V19_TO_V20",
        "EXACT_66_BY_SIX_SECURITY_BINDINGS",
        "AGGREGATE_ADTV_REJECTED",
    }


def test_checked_in_successor_necessity_matches_current_sources() -> None:
    expected = build_benchmark_outcome_successor_necessity_v1(
        REPOSITORY_ROOT
    )
    observed = json.loads(
        (
            REPOSITORY_ROOT
            / "docs/generated/"
            "forward-dqv-benchmark-outcome-successor-necessity-v1.json"
        ).read_text(encoding="utf-8")
    )

    assert observed == expected
