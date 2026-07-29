import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from equity_analysis.market_intelligence.models import (
    CurrentMarketData,
    EvidenceLineage,
    FactState,
    MarketIntelligenceProfileEnvelope,
    ScreeningRunMetadata,
    SnapshotScreeningRequest,
)
from equity_analysis.market_intelligence.persistence import (
    MarketIntelligenceCursorError,
    _decode_cursor,
    _decode_search_cursor,
    _encode_cursor,
    _encode_search_cursor,
)
from equity_analysis.market_intelligence.pipeline import (
    METRIC_VERSION,
    MarketIntelligenceAssembler,
    PostgresTacticalInputAdapter,
    _unique_lineage,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts" / "market-intelligence-v1"
PIPELINE = (
    ROOT / "analysis-python/src/equity_analysis/market_intelligence/pipeline.py"
).read_text(encoding="utf-8")
PERSISTENCE = (
    ROOT / "analysis-python/src/equity_analysis/market_intelligence/persistence.py"
).read_text(encoding="utf-8")


def _contract(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def test_shared_contract_examples_validate_against_python_models() -> None:
    request = SnapshotScreeningRequest.model_validate(
        _contract("screening-run-request.example.json")
    )
    envelope = MarketIntelligenceProfileEnvelope.model_validate(
        _contract("profile-envelope.example.json")
    )
    run = ScreeningRunMetadata.model_validate(
        _contract("screening-run-metadata.example.json")
    )

    assert request.data_snapshot_id == UUID("11111111-1111-4111-8111-111111111111")
    assert envelope.current_market_data.state == FactState.MISSING
    assert envelope.profile.ai_narrative.status == "NOT_EXECUTED"
    assert run.state == "SEALED"


def test_current_market_data_keeps_missing_distinct_from_zero() -> None:
    with pytest.raises(ValueError, match="cannot carry a price"):
        CurrentMarketData(
            state=FactState.MISSING,
            price=0,
            currency="USD",
            reason="NO_OBSERVATION",
        )


def test_cursors_are_resource_bound_and_opaque() -> None:
    run_id = UUID("44444444-4444-4444-8444-444444444444")
    other_run_id = UUID("55555555-5555-4555-8555-555555555555")
    cursor = _encode_cursor(run_id, 20)
    search_cursor = _encode_search_cursor(run_id, 81)

    assert _decode_cursor(cursor, run_id) == 20
    assert _decode_search_cursor(search_cursor, run_id) == 81
    assert "44444444" not in cursor
    with pytest.raises(MarketIntelligenceCursorError):
        _decode_cursor(cursor, other_run_id)
    with pytest.raises(MarketIntelligenceCursorError):
        _decode_search_cursor(search_cursor, other_run_id)


def test_pipeline_has_no_provider_factory_or_network_boundary() -> None:
    assert "create_market_data_provider" not in PIPELINE
    assert "requests." not in PIPELINE
    assert "httpx." not in PIPELINE
    assert "data_snapshot_source" in PIPELINE
    assert "snapshot.status" in PIPELINE
    assert "member.universe_version" in PIPELINE
    assert METRIC_VERSION == "MARKET-INTELLIGENCE-INPUT-v1.0.0"


def test_snapshot_run_contract_does_not_accept_profile_ids() -> None:
    payload = _contract("screening-run-request.example.json")
    payload["profileIds"] = ["22222222-2222-4222-8222-222222222222"]

    with pytest.raises(ValidationError, match="profileIds"):
        SnapshotScreeningRequest.model_validate(payload)


def test_repository_enforces_ready_snapshot_and_exact_profile_set() -> None:
    assert "Data snapshot must exist and be READY" in PERSISTENCE
    assert "profile_ids != expected" in PERSISTENCE
    assert "exactly match the snapshot universe profile set" in PERSISTENCE
    assert "MARKET_INTELLIGENCE_DECISION_SNAPSHOT_SEALED" in PERSISTENCE


def test_pipeline_components_require_database_configuration() -> None:
    with pytest.raises(ValueError, match="Analytics database URL"):
        MarketIntelligenceAssembler("")

    assert PostgresTacticalInputAdapter is not None


def test_valid_current_market_data_requires_full_provenance() -> None:
    with pytest.raises(ValueError, match="complete provenance"):
        CurrentMarketData(
            state=FactState.VALID,
            price=100,
            currency="USD",
            trading_date=datetime(2026, 7, 28, tzinfo=UTC).date(),
        )


def test_unique_lineage_keeps_latest_effective_observation_for_one_source() -> None:
    common = {
        "provider_code": "yfinance",
        "provider_schema_version": "v1",
        "parser_version": "v1",
        "source_reference": "yfinance://AAPL/history",
        "content_hash": "sha256:" + ("a" * 64),
        "available_at": datetime(2026, 7, 29, tzinfo=UTC),
        "retrieved_at": datetime(2026, 7, 29, tzinfo=UTC),
    }
    older = EvidenceLineage(
        **common,
        effective_at=datetime(2026, 6, 29, tzinfo=UTC),
    )
    latest = EvidenceLineage(
        **common,
        effective_at=datetime(2026, 7, 28, tzinfo=UTC),
    )

    selected = _unique_lineage((latest, older))

    assert selected == (latest,)
