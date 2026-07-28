import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from equity_analysis.market_intelligence.models import AiNarrative, ScreeningRequest
from equity_analysis.market_intelligence.persistence import (
    METHODOLOGY_REFERENCE,
    MarketIntelligenceRepository,
    canonical_hash,
)

ROOT = Path(__file__).resolve().parents[2]
PERSISTENCE = (
    ROOT / "analysis-python/src/equity_analysis/market_intelligence/persistence.py"
).read_text(encoding="utf-8")
MIGRATIONS = "\n".join(
    path.read_text(encoding="utf-8")
    for path in sorted((ROOT / "database/migrations").glob("V*.sql"))
)
V17 = (
    ROOT / "database/migrations/V17__persist_market_intelligence_screening_contract.sql"
).read_text(encoding="utf-8")


def test_every_repository_table_exists_in_v1_to_v17_schema() -> None:
    referenced = set(re.findall(r"analytics\.([a-z][a-z0-9_]*)", PERSISTENCE))
    created = set(re.findall(r"CREATE TABLE analytics\.([a-z][a-z0-9_]*)", MIGRATIONS))
    views = set(re.findall(r"CREATE (?:OR REPLACE )?VIEW analytics\.([a-z][a-z0-9_]*)", MIGRATIONS))

    assert referenced <= created | views


@pytest.mark.parametrize(
    ("table", "columns"),
    (
        (
            "security_profile_snapshot",
            (
                "contract_version",
                "security_id",
                "data_snapshot_id",
                "snapshot_as_of",
                "input_payload_hash",
            ),
        ),
        (
            "security_profile_fact",
            ("profile_id", "fact_name", "metric_observation_id", "display_order"),
        ),
        (
            "market_intelligence_horizon_view",
            (
                "profile_id",
                "horizon",
                "model_id",
                "model_version",
                "input_hash",
                "evidence_hash",
            ),
        ),
        (
            "market_intelligence_screening_run",
            (
                "idempotency_key",
                "canonical_request_hash",
                "methodology_reference",
                "input_snapshot_hash",
                "result_hash",
                "sealed_at",
            ),
        ),
        (
            "market_intelligence_ai_narrative",
            (
                "prompt_version",
                "model_version",
                "narrative_hash",
                "may_affect_deterministic_fields",
            ),
        ),
    ),
)
def test_repository_columns_exist_in_v17(table: str, columns: tuple[str, ...]) -> None:
    match = re.search(
        rf"CREATE TABLE analytics\.{table} \((.*?)\n\);",
        V17,
        flags=re.DOTALL,
    )
    assert match is not None
    declared = set(re.findall(r"^\s{4}([a-z][a-z0-9_]*)\s", match.group(1), re.MULTILINE))

    assert set(columns) <= declared


def test_hashes_are_canonical_and_methodology_is_versioned() -> None:
    first = canonical_hash({"b": 2, "a": ["x", 1]})
    second = canonical_hash({"a": ["x", 1], "b": 2})

    assert first == second
    assert first.startswith("sha256:")
    assert METHODOLOGY_REFERENCE == "docs/market-intelligence-screening-v1.md"


def test_repository_requires_database_configuration() -> None:
    with pytest.raises(ValueError, match="Analytics database URL"):
        MarketIntelligenceRepository("")


def test_available_ai_narrative_requires_prompt_and_model_versions() -> None:
    with pytest.raises(ValueError, match="generation and version metadata"):
        AiNarrative(
            status="AVAILABLE",
            narrative="Cited observation.",
            source_references=("source://one",),
            generated_at=datetime.now(UTC),
        )


def test_screening_request_hash_includes_filter_and_versioned_metric() -> None:
    request = ScreeningRequest(
        as_of=datetime(2026, 7, 28, 21, tzinfo=UTC),
        rank_by="LONG_HORIZON",
    )

    assert canonical_hash(request) == canonical_hash(request.model_dump(mode="json", by_alias=True))
