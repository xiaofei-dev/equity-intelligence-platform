import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg


class SnapshotConflictError(ValueError):
    pass


@dataclass(frozen=True)
class SnapshotRequest:
    snapshot_key: str
    as_of_time: datetime
    ingestion_cutoff: datetime
    universe_version: str
    market_normalization_version: str
    fundamental_normalization_version: str
    action_normalization_version: str
    market_data_provider: str = "twelve_data"
    market_adjustment_mode: str = "SPLIT_ADJUSTED"


class DataSnapshotRepository:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self._database_url = database_url

    @staticmethod
    def _identity(request: SnapshotRequest, batches: list[dict[str, Any]]) -> str:
        payload = {
            "snapshotKey": request.snapshot_key,
            "asOfTime": request.as_of_time.isoformat(),
            "ingestionCutoff": request.ingestion_cutoff.isoformat(),
            "universeVersion": request.universe_version,
            "normalizationVersions": {
                "market": request.market_normalization_version,
                "fundamental": request.fundamental_normalization_version,
                "action": request.action_normalization_version,
            },
            "marketDataProvider": request.market_data_provider,
            "marketAdjustmentMode": request.market_adjustment_mode,
            "sources": sorted(
                (
                    str(item["batch_id"]),
                    item["content_hash"],
                    item["source_reference"],
                    item.get("provider_code", "legacy"),
                    item.get("provider_schema_version", "legacy"),
                    item.get("parser_version", "legacy"),
                )
                for item in batches
            ),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    def create_and_seal(self, request: SnapshotRequest) -> UUID:
        if request.ingestion_cutoff < request.as_of_time:
            raise ValueError("ingestionCutoff must be on or after asOfTime")
        with psycopg.connect(self._database_url) as connection:
            batches = connection.execute(
                """
                SELECT DISTINCT batch.id AS batch_id, source.content_hash,
                       source.source_reference, provider.code,
                       source.schema_version, batch.parser_version
                FROM analytics.ingestion_batch batch
                JOIN analytics.data_provider provider ON provider.id = batch.provider_id
                JOIN analytics.source_record source
                  ON source.ingestion_batch_id = batch.id
                WHERE batch.status = 'SUCCEEDED'
                  AND source.available_at <= %s
                  AND source.ingested_at <= %s
                  AND (
                    provider.code NOT IN ('twelve_data', 'yfinance', 'eodhd')
                    OR provider.code = %s
                  )
                ORDER BY batch.id, source.content_hash, source.source_reference
                """,
                (
                    request.as_of_time,
                    request.ingestion_cutoff,
                    request.market_data_provider,
                ),
            ).fetchall()
            batch_items = [
                {
                    "batch_id": row[0],
                    "content_hash": row[1],
                    "source_reference": row[2],
                    "provider_code": row[3],
                    "provider_schema_version": row[4],
                    "parser_version": row[5],
                }
                for row in batches
            ]
            manifest_hash = self._identity(request, batch_items)
            existing = connection.execute(
                """
                SELECT id, status, manifest_hash, as_of_time, ingestion_cutoff,
                       market_data_provider, market_adjustment_mode
                FROM analytics.data_snapshot WHERE snapshot_key = %s
                """,
                (request.snapshot_key,),
            ).fetchone()
            if existing:
                if (
                    existing[2] != manifest_hash
                    or existing[3] != request.as_of_time
                    or existing[4] != request.ingestion_cutoff
                    or existing[5] != request.market_data_provider
                    or existing[6] != request.market_adjustment_mode
                ):
                    raise SnapshotConflictError(
                        "Snapshot key is already associated with different inputs"
                    )
                if existing[1] == "READY":
                    return existing[0]
                snapshot_id = existing[0]
                connection.execute(
                    "DELETE FROM analytics.data_snapshot_source WHERE snapshot_id = %s",
                    (snapshot_id,),
                )
                connection.execute(
                    "DELETE FROM analytics.snapshot_universe_member WHERE snapshot_id = %s",
                    (snapshot_id,),
                )
            else:
                row = connection.execute(
                    """
                    INSERT INTO analytics.data_snapshot (
                        snapshot_key, status, as_of_time, ingestion_cutoff,
                        market_normalization_version,
                        fundamental_normalization_version,
                        action_normalization_version, manifest_hash,
                        market_data_provider, market_adjustment_mode
                    ) VALUES (%s, 'BUILDING', %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        request.snapshot_key,
                        request.as_of_time,
                        request.ingestion_cutoff,
                        request.market_normalization_version,
                        request.fundamental_normalization_version,
                        request.action_normalization_version,
                        manifest_hash,
                        request.market_data_provider,
                        request.market_adjustment_mode,
                    ),
                ).fetchone()
                assert row is not None
                snapshot_id = row[0]
            for batch in {item["batch_id"] for item in batch_items}:
                connection.execute(
                    """
                    INSERT INTO analytics.data_snapshot_source
                        (snapshot_id, ingestion_batch_id)
                    VALUES (%s, %s)
                    """,
                    (snapshot_id, batch),
                )
            connection.execute(
                """
                INSERT INTO analytics.snapshot_universe_member (
                    snapshot_id, universe_version, security_id,
                    membership_status, membership_reason, symbol_at_snapshot,
                    company_type_at_snapshot, normalized_sector_at_snapshot
                )
                SELECT %s, %s, security.id,
                    CASE
                      WHEN classification.company_type = 'MATURE_OPERATING_COMPANY'
                        THEN 'INCLUDED'
                      WHEN classification.company_type = 'BENCHMARK'
                        THEN 'REFERENCE_ONLY'
                      ELSE 'EXCLUDED'
                    END,
                    CASE
                      WHEN classification.company_type = 'MATURE_OPERATING_COMPANY'
                        THEN 'GENERAL_COMPANY_CANDIDATE'
                      WHEN classification.company_type = 'BENCHMARK'
                        THEN 'REFERENCE_SECURITY'
                      ELSE 'SPECIALIZED_MODEL_REQUIRED'
                    END,
                    listing.symbol, classification.company_type,
                    classification.normalized_sector
                FROM analytics.security security
                JOIN LATERAL (
                    SELECT symbol FROM analytics.security_listing
                    WHERE security_id = security.id
                      AND valid_from <= %s::date
                    ORDER BY
                      (valid_to IS NULL OR valid_to > %s::date) DESC,
                      valid_from DESC LIMIT 1
                ) listing ON TRUE
                JOIN LATERAL (
                    SELECT company_type, normalized_sector
                    FROM analytics.security_classification
                    WHERE security_id = security.id
                      AND effective_from <= %s::date
                      AND (effective_to IS NULL OR effective_to > %s::date)
                    ORDER BY effective_from DESC LIMIT 1
                ) classification ON TRUE
                """,
                (
                    snapshot_id,
                    request.universe_version,
                    request.as_of_time,
                    request.as_of_time,
                    request.as_of_time,
                    request.as_of_time,
                ),
            )
            counts = connection.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM analytics.data_snapshot_source
                   WHERE snapshot_id = %s),
                  (SELECT COUNT(*) FROM analytics.snapshot_universe_member
                   WHERE snapshot_id = %s)
                """,
                (snapshot_id, snapshot_id),
            ).fetchone()
            assert counts is not None
            connection.execute(
                """
                UPDATE analytics.data_snapshot
                SET status = 'READY', source_count = %s, security_count = %s,
                    sealed_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (counts[0], counts[1], snapshot_id),
            )
            return snapshot_id
