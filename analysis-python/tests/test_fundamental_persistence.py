from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from equity_analysis.provider_validation.models import SecFactObservation
from equity_analysis.provider_validation.persistence import (
    FundamentalFactBatch,
    FundamentalFactRepository,
    NormalizedFundamentalFact,
    normalize_sec_fact,
)

INGESTION_ID = UUID("00000000-0000-0000-0000-000000000101")
SOURCE_ID = UUID("00000000-0000-0000-0000-000000000102")
SECURITY_ID = UUID("00000000-0000-0000-0000-000000000103")


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self, security_exists: bool = True) -> None:
        self.security_exists = security_exists
        self.fact_keys: set[tuple] = set()
        self.executions: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql: str, parameters: tuple):
        normalized = " ".join(sql.split())
        self.executions.append((normalized, parameters))
        if "INSERT INTO analytics.data_provider" in normalized:
            return FakeResult((11,))
        if "INSERT INTO analytics.ingestion_batch" in normalized:
            return FakeResult((INGESTION_ID,))
        if "INSERT INTO analytics.source_record" in normalized:
            return FakeResult((SOURCE_ID,))
        if "FROM analytics.security" in normalized:
            return FakeResult((7,) if self.security_exists else None)
        if "INSERT INTO analytics.fundamental_fact" in normalized:
            key = parameters[1:]
            if key in self.fact_keys:
                return FakeResult(None)
            self.fact_keys.add(key)
            return FakeResult((len(self.fact_keys),))
        raise AssertionError(f"Unexpected SQL: {normalized}")


def _fact(metric_code: str) -> NormalizedFundamentalFact:
    return NormalizedFundamentalFact(
        metric_code=metric_code,
        numeric_value=Decimal("123.45"),
        unit="USD",
        currency="USD",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 3, 31),
        fiscal_year=2025,
        fiscal_period="Q1",
        form_type="10-Q",
        mapping_version="sec-us-gaap-v1.0.0",
    )


def _batch() -> FundamentalFactBatch:
    return FundamentalFactBatch(
        security_public_id=SECURITY_ID,
        provider_schema_version="companyfacts-v1",
        request_key="sec:0000000001-25-000001:sha256:test",
        parser_version="sec-companyfacts-v1.0.0",
        normalization_version="fundamental-normalization-v1.0.0",
        source_reference="0000000001-25-000001",
        source_content_hash="sha256:test",
        acceptance_datetime=datetime(2025, 5, 1, 21, 0, tzinfo=UTC),
        available_at=datetime(2025, 5, 2, 20, 0, tzinfo=UTC),
        ingested_at=datetime(2026, 7, 26, 20, 0, tzinfo=UTC),
        revision_status="AS_FILED",
        quality_status="VALIDATED",
        facts=(_fact("revenue"), _fact("operating_income")),
    )


def test_repository_inserts_facts_once_for_the_same_source() -> None:
    connection = FakeConnection()
    repository = FundamentalFactRepository(
        "postgresql://test",
        connect=lambda _url: connection,
    )

    assert repository.insert_batch(_batch()) == 2
    assert repository.insert_batch(_batch()) == 0
    fact_inserts = [
        sql
        for sql, _parameters in connection.executions
        if "INSERT INTO analytics.fundamental_fact" in sql
    ]
    assert len(fact_inserts) == 4
    assert all(
        "ON CONFLICT ON CONSTRAINT uq_fundamental_fact_source" in sql for sql in fact_inserts
    )


def test_repository_rejects_unknown_security_and_invalid_lineage_time() -> None:
    repository = FundamentalFactRepository(
        "postgresql://test",
        connect=lambda _url: FakeConnection(security_exists=False),
    )

    with pytest.raises(ValueError, match="Unknown security"):
        repository.insert_batch(_batch())

    with pytest.raises(ValueError, match="acceptance <= available <= ingested"):
        FundamentalFactBatch.model_validate(
            {
                **_batch().model_dump(),
                "available_at": datetime(2025, 4, 30, tzinfo=UTC),
            }
        )

    with pytest.raises(ValueError, match="request key"):
        FundamentalFactBatch.model_validate(
            {
                **_batch().model_dump(),
                "request_key": "sec:request-without-content-identity",
            }
        )


def test_sec_fact_normalization_preserves_missing_values_as_absence() -> None:
    observation = SecFactObservation(
        metric_code="revenue",
        taxonomy_tag="Revenues",
        unit="USD",
        value=Decimal("100"),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 3, 31),
        fiscal_year=2025,
        fiscal_period="Q1",
        form="10-Q",
        filed_at=date(2025, 5, 1),
        accession_number="0000000001-25-000001",
        acceptance_datetime=datetime(2025, 5, 1, 21, 0, tzinfo=UTC),
        available_at=datetime(2025, 5, 2, 20, 0, tzinfo=UTC),
    )

    normalized = normalize_sec_fact(observation, "sec-us-gaap-v1.0.0")

    assert normalized.numeric_value == Decimal("100")
    assert normalized.currency == "USD"
    with pytest.raises(ValueError, match="fiscal period"):
        normalize_sec_fact(
            observation.model_copy(update={"fiscal_period": None}),
            "sec-us-gaap-v1.0.0",
        )
