from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from equity_analysis.market_intelligence.objective_gate_replay_postgres_v1 import (
    ObjectiveGateReplayPostgresWriter,
)

DATABASE_URL = os.getenv("OBJECTIVE_GATE_REPLAY_V17_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="OBJECTIVE_GATE_REPLAY_V17_TEST_DATABASE_URL is not configured",
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = (
    REPOSITORY_ROOT
    / "docs/generated/market-intelligence-eligibility-root-cause-audit-v1.json"
)
MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "docs/generated/objective-rating-v1-current-decision-input-manifest-v1.json"
)
GATE_PATH = (
    REPOSITORY_ROOT
    / "docs/generated/objective-rating-v1-current-snapshot-algorithm-gate-v1.json"
)
SOURCE_SNAPSHOT_ID = UUID("beaa9952-9852-4088-9dc3-92047824414b")
UNIVERSE_VERSION = "market-intelligence-closed-test-us-v1.0.0"
MARKET_BATCH_ID = UUID("15f7bc50-ea19-5d22-9465-f2573e369e39")
MARKET_SOURCE_ID = UUID("dd5a7567-513a-53a8-838f-47be4c0a7d57")
SUPPLEMENT_STORAGE_ROOT = (
    REPOSITORY_ROOT
    / "storage/provider-validation/objective-replay-supplement-tests"
)


def _require_isolated_database() -> None:
    assert DATABASE_URL is not None
    database_name = conninfo_to_dict(DATABASE_URL).get("dbname", "").lower()
    if not database_name.endswith("_test"):
        raise RuntimeError(
            "OBJECTIVE_GATE_REPLAY_V17_TEST_DATABASE_URL must name an isolated "
            "database ending in _test"
        )


def _seed_source_snapshot(*, missing_market_cap_symbol: str | None = None) -> None:
    _require_isolated_database()
    assert DATABASE_URL is not None
    profiles = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))["profiles"]
    with psycopg.connect(DATABASE_URL) as connection:
        existing = connection.execute(
            "SELECT status FROM analytics.data_snapshot WHERE id = %s",
            (SOURCE_SNAPSHOT_ID,),
        ).fetchone()
        connection.execute(
            """
            ALTER TABLE analytics.security
            DISABLE TRIGGER tr_security_public_id_immutable
            """
        )
        for profile in profiles:
            connection.execute(
                """
                INSERT INTO analytics.security (
                    symbol, exchange, name, instrument_type, currency, public_id
                ) VALUES (%s, 'NASDAQ', %s, 'COMMON_STOCK', 'USD', %s)
                ON CONFLICT (symbol) DO UPDATE
                SET public_id = EXCLUDED.public_id
                """,
                (
                    profile["symbol"],
                    f"{profile['symbol']} Test Issuer",
                    profile["securityId"],
                ),
            )
            public_id = connection.execute(
                "SELECT public_id FROM analytics.security WHERE symbol = %s",
                (profile["symbol"],),
            ).fetchone()[0]
            assert str(public_id) == profile["securityId"]
        connection.execute(
            """
            ALTER TABLE analytics.security
            ENABLE TRIGGER tr_security_public_id_immutable
            """
        )
        connection.execute(
            """
            INSERT INTO analytics.data_provider (
                code, name, provider_schema_version
            ) VALUES (
                'objective-replay-test-market',
                'Objective Replay Test Market Data',
                'test-market-v1'
            ) ON CONFLICT (code) DO NOTHING
            """
        )
        provider_id = connection.execute(
            """
            SELECT id FROM analytics.data_provider
            WHERE code = 'objective-replay-test-market'
            """
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO analytics.ingestion_batch (
                id, provider_id, request_key, status, parser_version,
                normalization_version, started_at, completed_at
            ) VALUES (
                %s, %s, 'objective-replay-test-market-v1', 'SUCCEEDED',
                'test-parser-v1', 'test-market-v1',
                TIMESTAMPTZ '2026-07-28 23:00:00Z',
                TIMESTAMPTZ '2026-07-28 23:00:00Z'
            ) ON CONFLICT (provider_id, request_key) DO NOTHING
            """,
            (MARKET_BATCH_ID, provider_id),
        )
        connection.execute(
            """
            INSERT INTO analytics.source_record (
                id, ingestion_batch_id, provider_id, provider_record_id,
                source_reference, original_at, available_at, ingested_at,
                schema_version, revision_status, quality_status, content_hash
            ) VALUES (
                %s, %s, %s, 'market-cap-fixture',
                'test://objective-replay/market-cap',
                TIMESTAMPTZ '2026-07-28 22:00:00Z',
                TIMESTAMPTZ '2026-07-28 23:00:00Z',
                TIMESTAMPTZ '2026-07-28 23:00:00Z',
                'test-market-v1', 'AS_REPORTED', 'VALIDATED',
                'sha256:objective-replay-market-cap-fixture'
            ) ON CONFLICT (provider_id, source_reference, content_hash)
              DO NOTHING
            """,
            (MARKET_SOURCE_ID, MARKET_BATCH_ID, provider_id),
        )
        for profile in profiles:
            if profile["symbol"] == missing_market_cap_symbol:
                continue
            connection.execute(
                """
                INSERT INTO analytics.market_value_observation (
                    security_id, metric_code, observation_date, numeric_value,
                    unit, currency, provider_id, revision_number,
                    source_record_id, available_at, ingested_at,
                    normalization_version
                )
                SELECT security.id, 'MARKET_CAP', DATE '2026-07-28',
                       50000000000, 'USD', 'USD', %s, 1, %s,
                       TIMESTAMPTZ '2026-07-28 23:00:00Z',
                       TIMESTAMPTZ '2026-07-28 23:00:00Z',
                       'test-market-v1'
                FROM analytics.security security
                WHERE security.symbol = %s
                ON CONFLICT (
                    security_id, metric_code, observation_date,
                    provider_id, revision_number
                ) DO NOTHING
                """,
                (provider_id, MARKET_SOURCE_ID, profile["symbol"]),
            )
        if existing is not None:
            assert existing[0] == "READY"
            return
        connection.execute(
            """
            INSERT INTO analytics.universe_definition (
                version, effective_at, configuration, configuration_hash
            ) VALUES (
                %s, TIMESTAMPTZ '2026-07-28 00:00:00Z',
                '{"kind":"objective-replay-test"}'::jsonb,
                'sha256:objective-replay-test-universe-v1'
            ) ON CONFLICT (version) DO NOTHING
            """,
            (UNIVERSE_VERSION,),
        )
        connection.execute(
            """
            INSERT INTO analytics.data_snapshot (
                id, snapshot_key, status, as_of_time, ingestion_cutoff,
                market_normalization_version,
                fundamental_normalization_version,
                action_normalization_version, manifest_hash,
                market_data_provider, market_adjustment_mode
            ) VALUES (
                %s, 'objective-replay-source-v1', 'BUILDING',
                TIMESTAMPTZ '2026-07-29 02:57:08.988871Z',
                TIMESTAMPTZ '2026-07-29 02:57:08.988871Z',
                'market-v1', 'fundamental-v1', 'action-v1',
                'sha256:objective-replay-source-v1',
                'yfinance', 'SPLIT_ADJUSTED'
            )
            """,
            (SOURCE_SNAPSHOT_ID,),
        )
        connection.execute(
            """
            INSERT INTO analytics.data_snapshot_source (
                snapshot_id, ingestion_batch_id
            ) VALUES (%s, %s)
            """,
            (SOURCE_SNAPSHOT_ID, MARKET_BATCH_ID),
        )
        for profile in profiles:
            connection.execute(
                """
                INSERT INTO analytics.snapshot_universe_member (
                    snapshot_id, universe_version, security_id,
                    membership_status, membership_reason, symbol_at_snapshot,
                    company_type_at_snapshot, normalized_sector_at_snapshot
                )
                SELECT %s, %s, security.id, %s, %s, %s, %s, 'TEST_SECTOR'
                FROM analytics.security security
                WHERE security.symbol = %s
                ORDER BY security.id
                LIMIT 1
                """,
                (
                    SOURCE_SNAPSHOT_ID,
                    UNIVERSE_VERSION,
                    profile["membershipStatus"],
                    f"TEST_{profile['membershipStatus']}",
                    profile["symbol"],
                    profile["companyType"],
                    profile["symbol"],
                ),
            )
        connection.execute(
            """
            UPDATE analytics.data_snapshot
            SET status = 'READY', source_count = 1, security_count = 66,
                sealed_at = ingestion_cutoff
            WHERE id = %s
            """,
            (SOURCE_SNAPSHOT_ID,),
        )


def _append_market_cap(symbol: str) -> None:
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL) as connection:
        provider_id = connection.execute(
            """
            SELECT id FROM analytics.data_provider
            WHERE code = 'objective-replay-test-market'
            """
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO analytics.market_value_observation (
                security_id, metric_code, observation_date, numeric_value,
                unit, currency, provider_id, revision_number,
                source_record_id, available_at, ingested_at,
                normalization_version
            )
            SELECT security.id, 'MARKET_CAP', DATE '2026-07-28',
                   50000000000, 'USD', 'USD', %s, 1, %s,
                   TIMESTAMPTZ '2026-07-28 23:00:00Z',
                   TIMESTAMPTZ '2026-07-28 23:00:00Z',
                   'test-market-v1'
            FROM analytics.security security
            WHERE security.symbol = %s
            """,
            (provider_id, MARKET_SOURCE_ID, symbol),
        )


def _seed_supplement(
    *,
    case: str,
    symbol: str,
    provider_code: str = "eodhd",
    source_marker: str = "cached-profile-replay-v1",
    include_audit: bool = True,
    hash_matches_storage: bool = True,
) -> tuple[UUID, Path]:
    assert DATABASE_URL is not None
    batch_id = uuid5(NAMESPACE_URL, f"objective-replay-supplement-batch:{case}")
    source_id = uuid5(NAMESPACE_URL, f"objective-replay-supplement-source:{case}")
    payload = f"objective-replay-supplement:{case}".encode()
    SUPPLEMENT_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    storage_path = SUPPLEMENT_STORAGE_ROOT / f"{case}.bin"
    storage_path.write_bytes(payload)
    storage_reference = storage_path.relative_to(REPOSITORY_ROOT).as_posix()
    actual_hash = sha256(payload).hexdigest()
    content_hash = (
        f"sha256:{actual_hash}"
        if hash_matches_storage
        else f"sha256:{'0' * 64}"
    )
    source_reference = (
        f"eodhd:fundamentals:{symbol}.US:{source_marker}:{actual_hash.upper()}"
    )
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO analytics.data_provider (
                code, name, provider_schema_version
            ) VALUES (%s, %s, 'objective-replay-supplement-test-v1')
            ON CONFLICT (code) DO NOTHING
            """,
            (provider_code, f"{provider_code} supplement test"),
        )
        provider_id = connection.execute(
            "SELECT id FROM analytics.data_provider WHERE code = %s",
            (provider_code,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO analytics.ingestion_batch (
                id, provider_id, request_key, status, parser_version,
                normalization_version, started_at, completed_at
            ) VALUES (
                %s, %s, %s, 'SUCCEEDED', 'supplement-test-parser-v1',
                'supplement-test-normalization-v1',
                TIMESTAMPTZ '2026-07-29 03:30:00Z',
                TIMESTAMPTZ '2026-07-29 04:00:00Z'
            ) ON CONFLICT (provider_id, request_key) DO NOTHING
            """,
            (batch_id, provider_id, f"supplement-test:{case}"),
        )
        connection.execute(
            """
            INSERT INTO analytics.source_record (
                id, ingestion_batch_id, provider_id, source_reference,
                available_at, ingested_at, schema_version, revision_status,
                quality_status, content_hash, storage_reference
            ) VALUES (
                %s, %s, %s, %s,
                TIMESTAMPTZ '2026-07-29 03:30:00Z',
                TIMESTAMPTZ '2026-07-29 04:00:00Z',
                'supplement-test-v1', 'AS_REPORTED', 'PROVISIONAL', %s, %s
            ) ON CONFLICT (provider_id, source_reference, content_hash)
              DO NOTHING
            """,
            (
                source_id,
                batch_id,
                provider_id,
                source_reference,
                content_hash,
                storage_reference,
            ),
        )
        security_id, public_id = connection.execute(
            "SELECT id, public_id FROM analytics.security WHERE symbol = %s",
            (symbol,),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO analytics.company_profile_observation (
                security_id, legal_name, effective_from, revision_number,
                source_record_id, available_at, ingested_at, quality_status
            ) VALUES (
                %s, %s, DATE '2026-07-29', 1, %s,
                TIMESTAMPTZ '2026-07-29 03:30:00Z',
                TIMESTAMPTZ '2026-07-29 04:00:00Z', 'PROVISIONAL'
            ) ON CONFLICT ON CONSTRAINT uq_company_profile_revision DO NOTHING
            """,
            (security_id, f"{symbol} Supplemental", source_id),
        )
        connection.execute(
            """
            INSERT INTO analytics.market_value_observation (
                security_id, metric_code, observation_date, numeric_value,
                unit, currency, provider_id, revision_number,
                source_record_id, available_at, ingested_at,
                normalization_version
            ) VALUES (
                %s, 'MARKET_CAP', DATE '2026-07-29', 3500000000000,
                'USD', 'USD', %s, %s, %s,
                TIMESTAMPTZ '2026-07-29 03:30:00Z',
                TIMESTAMPTZ '2026-07-29 04:00:00Z',
                'supplement-test-normalization-v1'
            ) ON CONFLICT (
                security_id, metric_code, observation_date,
                provider_id, revision_number
            ) DO NOTHING
            """,
            (
                security_id,
                provider_id,
                int(str(batch_id.int)[-6:]) + 100,
                source_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO analytics.security_classification (
                security_id, classification_version, raw_sector, raw_industry,
                normalized_sector, normalized_industry, company_type,
                effective_from, source_record_id
            ) VALUES (
                %s, 'provider-current-replay-v1.0.0',
                'Technology Supplemental', 'Consumer Electronics Supplemental',
                'Technology Supplemental', 'Consumer Electronics Supplemental',
                'MATURE_OPERATING_COMPANY', DATE '2026-07-29', %s
            ) ON CONFLICT ON CONSTRAINT uq_security_classification_version
              DO UPDATE SET
                raw_sector = EXCLUDED.raw_sector,
                raw_industry = EXCLUDED.raw_industry,
                normalized_sector = EXCLUDED.normalized_sector,
                normalized_industry = EXCLUDED.normalized_industry,
                company_type = EXCLUDED.company_type,
                source_record_id = EXCLUDED.source_record_id
            """,
            (security_id, source_id),
        )
        if include_audit:
            detail = {
                "schemaVersion": "provider-cache-replay-v1.0.0",
                "securityPublicId": str(public_id),
                "sourceRecordId": str(source_id),
                "sourceContentHash": content_hash,
                "storageReference": storage_reference,
                "physicalRequests": 0,
                "weightedCalls": 0,
                "networkRequestsExecuted": False,
            }
            connection.execute(
                """
                INSERT INTO analytics.analytics_audit_event (
                    event_type, entity_type, entity_id, actor_service,
                    occurred_at, event_hash, detail
                ) VALUES (
                    'PROVIDER_CACHE_REPLAY', 'SECURITY', %s,
                    'PYTHON_ANALYTICS',
                    TIMESTAMPTZ '2026-07-29 04:00:00Z', %s, %s::jsonb
                ) ON CONFLICT (event_hash) DO NOTHING
                """,
                (
                    str(public_id),
                    sha256(
                        json.dumps(detail, sort_keys=True).encode()
                    ).hexdigest(),
                    json.dumps(detail, sort_keys=True, separators=(",", ":")),
                ),
            )
    return batch_id, storage_path


def test_replay_is_append_only_idempotent_and_preserves_current_only_states():
    _seed_source_snapshot(missing_market_cap_symbol="AAPL")
    assert DATABASE_URL is not None
    writer = ObjectiveGateReplayPostgresWriter(DATABASE_URL, REPOSITORY_ROOT)

    with pytest.raises(ValueError, match=r"MISSING_MARKET_CAP_FOR_COHORT\[AAPL\]"):
        writer.replay(
            source_snapshot_id=SOURCE_SNAPSHOT_ID,
            universe_version=UNIVERSE_VERSION,
            input_manifest_path=MANIFEST_PATH,
            algorithm_gate_path=GATE_PATH,
            closed_pool_audit_path=AUDIT_PATH,
        )
    _append_market_cap("AAPL")

    first = writer.replay(
        source_snapshot_id=SOURCE_SNAPSHOT_ID,
        universe_version=UNIVERSE_VERSION,
        input_manifest_path=MANIFEST_PATH,
        algorithm_gate_path=GATE_PATH,
        closed_pool_audit_path=AUDIT_PATH,
    )
    second = writer.replay(
        source_snapshot_id=SOURCE_SNAPSHOT_ID,
        universe_version=UNIVERSE_VERSION,
        input_manifest_path=MANIFEST_PATH,
        algorithm_gate_path=GATE_PATH,
        closed_pool_audit_path=AUDIT_PATH,
    )

    assert first == second
    assert first.objective_scored_count == 32
    assert first.insufficient_data_count == 23
    assert first.non_applicable_count == 11
    assert first.source_record_count == 138
    assert first.network_requests_executed is False
    assert first.full_market_intelligence_eligibility_claimed is False
    with psycopg.connect(DATABASE_URL) as connection:
        snapshot = connection.execute(
            """
            SELECT status, security_count,
                   (SELECT COUNT(*) FROM analytics.snapshot_universe_member
                    WHERE snapshot_id = analytics.data_snapshot.id),
                   (SELECT COUNT(*) FROM analytics.data_snapshot_source
                    WHERE snapshot_id = analytics.data_snapshot.id)
            FROM analytics.data_snapshot WHERE id = %s
            """,
            (first.snapshot_id,),
        ).fetchone()
        assert snapshot == ("READY", 66, 66, 2)
        coverage = dict(
            connection.execute(
                """
                SELECT coverage_state, COUNT(*)
                FROM analytics.coverage_result
                WHERE run_id = %s GROUP BY coverage_state
                """,
                (first.screening_run_id,),
            ).fetchall()
        )
        assert coverage == {
            "QUANT_ELIGIBLE": 32,
            "INSUFFICIENT_DATA": 23,
        }
        non_applicable_coverage = connection.execute(
            """
            SELECT COUNT(*)
            FROM analytics.coverage_result coverage
            JOIN analytics.snapshot_universe_member member
              ON member.snapshot_id = %s
             AND member.security_id = coverage.security_id
            WHERE coverage.run_id = %s
              AND member.membership_status <> 'INCLUDED'
            """,
            (first.snapshot_id, first.screening_run_id),
        ).fetchone()[0]
        assert non_applicable_coverage == 0
        counts = connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM analytics.factor_result WHERE run_id = %s),
              (SELECT COUNT(*) FROM analytics.strategy_rating WHERE run_id = %s),
              (SELECT COUNT(*) FROM analytics.factor_contribution contribution
               JOIN analytics.strategy_rating rating
                 ON rating.id = contribution.strategy_rating_id
               WHERE rating.run_id = %s),
              (SELECT COUNT(*) FROM analytics.horizon_assessment WHERE run_id = %s),
              (SELECT COUNT(*) FROM analytics.source_record source
               JOIN analytics.ingestion_batch batch
                 ON batch.id = source.ingestion_batch_id
               JOIN analytics.data_provider provider
                 ON provider.id = batch.provider_id
               WHERE provider.code = 'objective_current_gate')
            """,
            (
                first.screening_run_id,
                first.screening_run_id,
                first.screening_run_id,
                first.screening_run_id,
            ),
        ).fetchone()
        assert counts == (416, 32, 352, 32, 138)
        lineage_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM analytics.factor_result_lineage lineage
            JOIN analytics.factor_result factor ON factor.id = lineage.factor_result_id
            WHERE factor.run_id = %s
            """,
            (first.screening_run_id,),
        ).fetchone()[0]
        assert lineage_count == 1248
        source_status = connection.execute(
            """
            SELECT status, security_count
            FROM analytics.data_snapshot WHERE id = %s
            """,
            (SOURCE_SNAPSHOT_ID,),
        ).fetchone()
        assert source_status == ("READY", 66)


def test_supplement_validation_rejects_unapproved_provider():
    _seed_source_snapshot()
    batch_id, storage_path = _seed_supplement(
        case="invalid-provider",
        symbol="AAPL",
        provider_code="not-eodhd",
    )
    try:
        writer = ObjectiveGateReplayPostgresWriter(
            DATABASE_URL or "",
            REPOSITORY_ROOT,
        )
        with pytest.raises(ValueError, match="SUPPLEMENTAL_PROVIDER_NOT_EODHD"):
            writer.replay(
                source_snapshot_id=SOURCE_SNAPSHOT_ID,
                universe_version=UNIVERSE_VERSION,
                input_manifest_path=MANIFEST_PATH,
                algorithm_gate_path=GATE_PATH,
                closed_pool_audit_path=AUDIT_PATH,
                supplemental_ingestion_batch_ids=(batch_id,),
            )
    finally:
        storage_path.unlink(missing_ok=True)


def test_supplement_validation_requires_zero_network_audit():
    _seed_source_snapshot()
    batch_id, storage_path = _seed_supplement(
        case="missing-audit",
        symbol="MSFT",
        include_audit=False,
    )
    try:
        writer = ObjectiveGateReplayPostgresWriter(
            DATABASE_URL or "",
            REPOSITORY_ROOT,
        )
        with pytest.raises(ValueError, match="SUPPLEMENTAL_AUDIT_MISSING"):
            writer.replay(
                source_snapshot_id=SOURCE_SNAPSHOT_ID,
                universe_version=UNIVERSE_VERSION,
                input_manifest_path=MANIFEST_PATH,
                algorithm_gate_path=GATE_PATH,
                closed_pool_audit_path=AUDIT_PATH,
                supplemental_ingestion_batch_ids=(batch_id,),
            )
    finally:
        storage_path.unlink(missing_ok=True)


def test_supplement_validation_rejects_storage_hash_mismatch():
    _seed_source_snapshot()
    batch_id, storage_path = _seed_supplement(
        case="hash-mismatch",
        symbol="AMZN",
        hash_matches_storage=False,
    )
    try:
        writer = ObjectiveGateReplayPostgresWriter(
            DATABASE_URL or "",
            REPOSITORY_ROOT,
        )
        with pytest.raises(ValueError, match="SUPPLEMENTAL_STORAGE_HASH_MISMATCH"):
            writer.replay(
                source_snapshot_id=SOURCE_SNAPSHOT_ID,
                universe_version=UNIVERSE_VERSION,
                input_manifest_path=MANIFEST_PATH,
                algorithm_gate_path=GATE_PATH,
                closed_pool_audit_path=AUDIT_PATH,
                supplemental_ingestion_batch_ids=(batch_id,),
            )
    finally:
        storage_path.unlink(missing_ok=True)


def test_valid_supplement_enriches_derived_snapshot_and_is_idempotent():
    _seed_source_snapshot()
    batch_id, storage_path = _seed_supplement(case="valid", symbol="NVDA")
    try:
        writer = ObjectiveGateReplayPostgresWriter(
            DATABASE_URL or "",
            REPOSITORY_ROOT,
        )
        first = writer.replay(
            source_snapshot_id=SOURCE_SNAPSHOT_ID,
            universe_version=UNIVERSE_VERSION,
            input_manifest_path=MANIFEST_PATH,
            algorithm_gate_path=GATE_PATH,
            closed_pool_audit_path=AUDIT_PATH,
            supplemental_ingestion_batch_ids=(batch_id,),
        )
        second = writer.replay(
            source_snapshot_id=SOURCE_SNAPSHOT_ID,
            universe_version=UNIVERSE_VERSION,
            input_manifest_path=MANIFEST_PATH,
            algorithm_gate_path=GATE_PATH,
            closed_pool_audit_path=AUDIT_PATH,
            supplemental_ingestion_batch_ids=(batch_id,),
        )

        assert first == second
        assert first.supplemental_batch_count == 1
        assert first.supplemental_source_count == 1
        assert first.supplemental_aggregate_hash is not None
        assert first.effective_as_of_time.isoformat() == (
            "2026-07-29T03:30:00+00:00"
        )
        assert first.effective_ingestion_cutoff.isoformat() == (
            "2026-07-29T04:00:00+00:00"
        )
        with psycopg.connect(DATABASE_URL) as connection:
            source_sector = connection.execute(
                """
                SELECT normalized_sector_at_snapshot
                FROM analytics.snapshot_universe_member
                WHERE snapshot_id = %s AND symbol_at_snapshot = 'NVDA'
                """,
                (SOURCE_SNAPSHOT_ID,),
            ).fetchone()[0]
            enriched = connection.execute(
                """
                SELECT member.normalized_sector_at_snapshot,
                       member.membership_status,
                       member.company_type_at_snapshot,
                       security.public_id
                FROM analytics.snapshot_universe_member member
                JOIN analytics.security security
                  ON security.id = member.security_id
                WHERE member.snapshot_id = %s
                  AND member.symbol_at_snapshot = 'NVDA'
                """,
                (first.snapshot_id,),
            ).fetchone()
            snapshot_batches = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT ingestion_batch_id
                    FROM analytics.data_snapshot_source
                    WHERE snapshot_id = %s
                    """,
                    (first.snapshot_id,),
                ).fetchall()
            }
            supplemental_lineage = connection.execute(
                """
                SELECT COUNT(*)
                FROM analytics.factor_result_lineage lineage
                JOIN analytics.factor_result factor
                  ON factor.id = lineage.factor_result_id
                JOIN analytics.security security
                  ON security.id = factor.security_id
                WHERE factor.run_id = %s
                  AND security.symbol = 'NVDA'
                  AND lineage.lineage_role = 'SUPPLEMENTAL_CURRENT_PROFILE'
                """,
                (first.screening_run_id,),
            ).fetchone()[0]
        assert source_sector == "TEST_SECTOR"
        expected_public_id = UUID(
            next(
                profile["securityId"]
                for profile in json.loads(
                    AUDIT_PATH.read_text(encoding="utf-8")
                )["profiles"]
                if profile["symbol"] == "NVDA"
            )
        )
        assert enriched == (
            "Technology Supplemental",
            "INCLUDED",
            "MATURE_OPERATING_COMPANY",
            expected_public_id,
        )
        assert batch_id in snapshot_batches
        assert len(snapshot_batches) == 3
        assert supplemental_lineage == 13
    finally:
        storage_path.unlink(missing_ok=True)
