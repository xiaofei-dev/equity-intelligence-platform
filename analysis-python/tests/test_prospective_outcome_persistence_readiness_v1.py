from __future__ import annotations

from pathlib import Path

import pytest

from equity_analysis.schema_audit.prospective_outcome_persistence_readiness_v1 import (
    ProspectiveOutcomePersistenceAuditError,
    _require_tokens,
    build_prospective_outcome_persistence_readiness_audit,
    write_immutable_audit,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_current_schema_has_bounded_v18_successor_for_forward_v2_outcomes() -> None:
    artifact = build_prospective_outcome_persistence_readiness_audit(
        REPOSITORY_ROOT
    )

    assert artifact["status"] == "V18_SUCCESSOR_IMPLEMENTED_PENDING_ACCEPTANCE"
    assert artifact["decision"]["v18Required"] is True
    assert artifact["decision"]["migrationCreated"] is True
    assert artifact["execution"]["databaseReads"] == 0
    assert artifact["execution"]["databaseWrites"] == 0
    assert artifact["execution"]["networkRequests"] == 0
    assert {
        item["name"] for item in artifact["v18Responsibility"]["tables"]
    } == {
        "analytics.forward_dqv_enrollment_v2",
        "analytics.forward_dqv_maturity_schedule_v2",
        "analytics.forward_dqv_outcome_batch_v2",
        "analytics.forward_dqv_security_outcome_v2",
        "analytics.forward_dqv_benchmark_outcome_v2",
        "analytics.forward_dqv_path_metric_v2",
        "analytics.forward_dqv_quality_report_v2",
    }
    assert {
        item["path"] for item in artifact["evidence"]["implementedSuccessor"]
    } == {
        "database/migrations/V18__create_forward_dqv_v2_outcome_ledger.sql",
        "analysis-python/src/equity_analysis/forward_validation/outcomes_v21.py",
        (
            "analysis-python/src/equity_analysis/forward_validation/"
            "outcome_persistence_v21.py"
        ),
    }


def test_audit_distinguishes_legacy_horizon_and_benchmark_blocks() -> None:
    artifact = build_prospective_outcome_persistence_readiness_audit(
        REPOSITORY_ROOT
    )
    matrix = {
        item["requirement"]: item for item in artifact["capabilityMatrix"]
    }

    assert matrix["FIVE_MATURITY_HORIZONS"]["currentDisposition"] == (
        "HARD_SCHEMA_BLOCK"
    )
    assert matrix["SIX_FORMAL_BENCHMARK_ARMS"]["currentDisposition"] == (
        "SEMANTIC_SCHEMA_BLOCK"
    )
    assert matrix["APPEND_ONLY_CORRECTIONS"]["currentDisposition"] == (
        "PARTIAL_RESULT_CHAIN"
    )


def test_contract_token_drift_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "V11.sql"
    source.write_text(
        "CREATE TABLE analytics.forward_observation_result ();",
        encoding="utf-8",
    )

    with pytest.raises(
        ProspectiveOutcomePersistenceAuditError,
        match="contract drift",
    ):
        _require_tokens(
            source,
            (
                "CREATE TABLE analytics.forward_observation_result",
                "CHECK (horizon_trading_days IN (5, 20, 60))",
            ),
        )


def test_audit_writer_is_immutable(tmp_path: Path) -> None:
    artifact = build_prospective_outcome_persistence_readiness_audit(
        REPOSITORY_ROOT
    )
    output = tmp_path / "audit.json"
    first = write_immutable_audit(output, artifact)
    assert write_immutable_audit(output, artifact) == first

    with pytest.raises(
        ProspectiveOutcomePersistenceAuditError,
        match="IMMUTABLE_CONFLICT",
    ):
        write_immutable_audit(
            output,
            {**artifact, "status": "CHANGED"},
        )
