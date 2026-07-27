from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

import psycopg
from pydantic import BaseModel, ConfigDict, Field, model_validator

from equity_analysis.provider_validation.models import SecFactObservation


class NormalizedFundamentalFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric_code: str
    numeric_value: Decimal
    unit: str
    currency: str | None = None
    period_start: date | None = None
    period_end: date
    fiscal_year: int | None = None
    fiscal_period: str
    form_type: str
    mapping_version: str


class FundamentalFactBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    security_public_id: UUID
    provider_code: str = "sec_edgar"
    provider_name: str = "SEC EDGAR"
    provider_schema_version: str
    request_key: str
    parser_version: str
    normalization_version: str
    source_reference: str
    source_uri: str | None = None
    source_content_hash: str
    acceptance_datetime: datetime
    available_at: datetime
    ingested_at: datetime
    revision_status: Literal["AS_REPORTED", "AS_FILED", "RESTATED", "CORRECTED"]
    quality_status: Literal["VALIDATED", "PROVISIONAL", "REJECTED", "NOT_VERIFIED"]
    facts: tuple[NormalizedFundamentalFact, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_times_and_source(self) -> "FundamentalFactBatch":
        timestamps = (
            self.acceptance_datetime,
            self.available_at,
            self.ingested_at,
        )
        if any(item.tzinfo is None or item.utcoffset() is None for item in timestamps):
            raise ValueError("Fundamental lineage timestamps must include timezones")
        if not self.acceptance_datetime <= self.available_at <= self.ingested_at:
            raise ValueError(
                "Fundamental timestamps must satisfy acceptance <= available <= ingested"
            )
        if any(fact.form_type == "" or fact.fiscal_period == "" for fact in self.facts):
            raise ValueError("Fundamental form and fiscal period are required")
        if self.source_content_hash not in self.request_key:
            raise ValueError("Fundamental request key must include the source content hash")
        return self


class FundamentalFactRepository:
    def __init__(
        self,
        database_url: str,
        connect: Callable[[str], Any] | None = None,
    ) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self._database_url = database_url
        self._connect = connect or psycopg.connect

    def insert_batch(self, batch: FundamentalFactBatch) -> int:
        with self._connect(self._database_url) as connection:
            provider_id = self._provider_id(connection, batch)
            ingestion_batch_id = self._ingestion_batch_id(
                connection,
                provider_id,
                batch,
            )
            source_record_id = self._source_record_id(
                connection,
                provider_id,
                ingestion_batch_id,
                batch,
            )
            security_row = connection.execute(
                """
                SELECT id
                FROM analytics.security
                WHERE public_id = %s
                """,
                (batch.security_public_id,),
            ).fetchone()
            if security_row is None:
                raise ValueError(f"Unknown security public ID {batch.security_public_id}")
            security_id = security_row[0]

            inserted = 0
            for fact in batch.facts:
                row = connection.execute(
                    """
                    INSERT INTO analytics.fundamental_fact (
                        security_id,
                        metric_code,
                        numeric_value,
                        unit,
                        currency,
                        period_start,
                        period_end,
                        fiscal_year,
                        fiscal_period,
                        form_type,
                        accession_number,
                        filed_at,
                        available_at,
                        ingested_at,
                        mapping_version,
                        normalization_version,
                        revision_status,
                        quality_status,
                        source_record_id
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT ON CONSTRAINT uq_fundamental_fact_source
                    DO NOTHING
                    RETURNING id
                    """,
                    (
                        security_id,
                        fact.metric_code,
                        fact.numeric_value,
                        fact.unit,
                        fact.currency,
                        fact.period_start,
                        fact.period_end,
                        fact.fiscal_year,
                        fact.fiscal_period,
                        fact.form_type,
                        batch.source_reference,
                        batch.acceptance_datetime,
                        batch.available_at,
                        batch.ingested_at,
                        fact.mapping_version,
                        batch.normalization_version,
                        batch.revision_status,
                        batch.quality_status,
                        source_record_id,
                    ),
                ).fetchone()
                if row is not None:
                    inserted += 1
        return inserted

    @staticmethod
    def _provider_id(connection: Any, batch: FundamentalFactBatch) -> int:
        row = connection.execute(
            """
            INSERT INTO analytics.data_provider (
                code,
                name,
                provider_schema_version
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                name = EXCLUDED.name,
                provider_schema_version = EXCLUDED.provider_schema_version
            RETURNING id
            """,
            (
                batch.provider_code,
                batch.provider_name,
                batch.provider_schema_version,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("Provider upsert did not return an identifier")
        return int(row[0])

    @staticmethod
    def _ingestion_batch_id(
        connection: Any,
        provider_id: int,
        batch: FundamentalFactBatch,
    ) -> UUID:
        row = connection.execute(
            """
            INSERT INTO analytics.ingestion_batch (
                provider_id,
                request_key,
                status,
                parser_version,
                normalization_version,
                started_at,
                completed_at
            )
            VALUES (%s, %s, 'SUCCEEDED', %s, %s, %s, %s)
            ON CONFLICT (provider_id, request_key) DO NOTHING
            RETURNING id
            """,
            (
                provider_id,
                batch.request_key,
                batch.parser_version,
                batch.normalization_version,
                batch.ingested_at,
                batch.ingested_at,
            ),
        ).fetchone()
        if row is None:
            row = connection.execute(
                """
                SELECT id
                FROM analytics.ingestion_batch
                WHERE provider_id = %s AND request_key = %s
                """,
                (provider_id, batch.request_key),
            ).fetchone()
        if row is None:
            raise RuntimeError("Ingestion batch insert did not return an identifier")
        return row[0]

    @staticmethod
    def _source_record_id(
        connection: Any,
        provider_id: int,
        ingestion_batch_id: UUID,
        batch: FundamentalFactBatch,
    ) -> UUID:
        row = connection.execute(
            """
            INSERT INTO analytics.source_record (
                ingestion_batch_id,
                provider_id,
                provider_record_id,
                source_reference,
                source_uri,
                original_at,
                available_at,
                ingested_at,
                schema_version,
                revision_status,
                quality_status,
                content_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider_id, source_reference, content_hash)
            DO NOTHING
            RETURNING id
            """,
            (
                ingestion_batch_id,
                provider_id,
                batch.source_reference,
                batch.source_reference,
                batch.source_uri,
                batch.acceptance_datetime,
                batch.available_at,
                batch.ingested_at,
                batch.provider_schema_version,
                batch.revision_status,
                batch.quality_status,
                batch.source_content_hash,
            ),
        ).fetchone()
        if row is None:
            row = connection.execute(
                """
                SELECT id
                FROM analytics.source_record
                WHERE provider_id = %s
                  AND source_reference = %s
                  AND content_hash = %s
                """,
                (
                    provider_id,
                    batch.source_reference,
                    batch.source_content_hash,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("Source record insert did not return an identifier")
        return row[0]


def normalize_sec_fact(
    observation: SecFactObservation,
    mapping_version: str,
) -> NormalizedFundamentalFact:
    if observation.fiscal_period is None:
        raise ValueError("SEC fact requires a fiscal period before persistence")
    return NormalizedFundamentalFact(
        metric_code=observation.metric_code,
        numeric_value=observation.value,
        unit=observation.unit,
        currency=observation.unit if len(observation.unit) == 3 else None,
        period_start=observation.period_start,
        period_end=observation.period_end,
        fiscal_year=observation.fiscal_year,
        fiscal_period=observation.fiscal_period,
        form_type=observation.form,
        mapping_version=mapping_version,
    )
