from collections.abc import Sequence
from datetime import UTC, datetime

import psycopg

from equity_analysis.market_data.models import DailyPriceSeries


class DailyPriceRepository:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self._database_url = database_url

    def upsert(self, series: DailyPriceSeries) -> int:
        with psycopg.connect(self._database_url) as connection:
            security_row = connection.execute(
                """
                INSERT INTO analytics.security (
                    symbol,
                    exchange,
                    name,
                    instrument_type,
                    currency
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (symbol) DO UPDATE SET
                    exchange = EXCLUDED.exchange,
                    name = CASE
                        WHEN EXCLUDED.name = EXCLUDED.symbol
                            THEN analytics.security.name
                        ELSE EXCLUDED.name
                    END,
                    instrument_type = EXCLUDED.instrument_type,
                    currency = EXCLUDED.currency,
                    active = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                (
                    series.security.symbol,
                    series.security.exchange,
                    series.security.name,
                    series.security.instrument_type,
                    series.security.currency,
                ),
            ).fetchone()
            if security_row is None:
                raise RuntimeError("Security upsert did not return an identifier")
            security_id = security_row[0]
            mic = {
                "NASDAQ": "XNAS",
                "NYSE": "XNYS",
                "NYSE AMERICAN": "XASE",
                "NYSE ARCA": "ARCX",
            }.get(series.security.exchange.upper())
            if mic is not None:
                connection.execute(
                    """
                    INSERT INTO analytics.security_listing (
                        security_id, symbol, exchange, mic, currency, valid_from
                    ) VALUES (%s, %s, %s, %s, %s, DATE '1970-01-01')
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        security_id,
                        series.security.symbol,
                        series.security.exchange,
                        mic,
                        series.security.currency,
                    ),
                )
            provider_row = connection.execute(
                """
                INSERT INTO analytics.data_provider (
                    code, name, provider_schema_version
                ) VALUES (%s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    provider_schema_version = EXCLUDED.provider_schema_version
                RETURNING id
                """,
                (
                    series.provider_descriptor.code,
                    series.provider_descriptor.name,
                    series.provider_descriptor.provider_schema_version,
                ),
            ).fetchone()
            if provider_row is None:
                raise RuntimeError("Provider upsert did not return an identifier")
            provider_id = provider_row[0]
            content_hash = series.content_hash
            request_key = (
                f"daily-price:{series.provider_symbol}:{series.bars[0].trading_date}:"
                f"{series.bars[-1].trading_date}:{series.adjustment_mode}:{content_hash}"
            )
            ingested_at = datetime.now(UTC)
            batch_row = connection.execute(
                """
                INSERT INTO analytics.ingestion_batch (
                    provider_id, request_key, status, parser_version,
                    normalization_version, started_at, completed_at
                ) VALUES (%s, %s, 'SUCCEEDED', %s, %s, %s, %s)
                ON CONFLICT (provider_id, request_key) DO NOTHING
                RETURNING id
                """,
                (
                    provider_id,
                    request_key,
                    series.provider_descriptor.parser_version,
                    "market-normalization-v1.0.0",
                    ingested_at,
                    ingested_at,
                ),
            ).fetchone()
            if batch_row is None:
                batch_row = connection.execute(
                    """
                    SELECT id FROM analytics.ingestion_batch
                    WHERE provider_id = %s AND request_key = %s
                    """,
                    (provider_id, request_key),
                ).fetchone()
            assert batch_row is not None
            source_row = connection.execute(
                """
                INSERT INTO analytics.source_record (
                    ingestion_batch_id, provider_id, provider_record_id, source_reference,
                    available_at, ingested_at, schema_version, revision_status,
                    quality_status, content_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'AS_REPORTED',
                          'PROVISIONAL', %s)
                ON CONFLICT (provider_id, source_reference, content_hash)
                DO NOTHING RETURNING id
                """,
                (
                    batch_row[0],
                    provider_id,
                    series.provider_record_id,
                    series.source_reference,
                    series.available_at,
                    ingested_at,
                    series.provider_descriptor.provider_schema_version,
                    content_hash,
                ),
            ).fetchone()
            if source_row is None:
                source_row = connection.execute(
                    """
                    SELECT id FROM analytics.source_record
                    WHERE provider_id = %s AND source_reference = %s
                      AND content_hash = %s
                    """,
                    (
                        provider_id,
                        series.source_reference,
                        content_hash,
                    ),
                ).fetchone()
            assert source_row is not None

            rows: Sequence[tuple[object, ...]] = [
                (
                    security_id,
                    bar.trading_date,
                    bar.open_price,
                    bar.high_price,
                    bar.low_price,
                    bar.close_price,
                    bar.volume,
                    series.provider,
                    str(series.adjustment_mode),
                    series.security.exchange_timezone,
                )
                for bar in series.bars
            ]
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO analytics.daily_price (
                        security_id,
                        trading_date,
                        open_price,
                        high_price,
                        low_price,
                        close_price,
                        volume,
                        provider,
                        adjustment_mode,
                        source_timezone
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (
                        security_id,
                        trading_date,
                        provider,
                        adjustment_mode
                    ) DO UPDATE SET
                        open_price = EXCLUDED.open_price,
                        high_price = EXCLUDED.high_price,
                        low_price = EXCLUDED.low_price,
                        close_price = EXCLUDED.close_price,
                        volume = EXCLUDED.volume,
                        source_timezone = EXCLUDED.source_timezone,
                        ingested_at = CURRENT_TIMESTAMP
                    """,
                    rows,
                )
                immutable_rows = []
                for bar in series.bars:
                    existing = connection.execute(
                        """
                        SELECT 1 FROM analytics.daily_price_observation
                        WHERE security_id = %s AND trading_date = %s
                          AND provider_id = %s AND adjustment_mode = %s
                          AND source_record_id = %s
                        """,
                        (
                            security_id,
                            bar.trading_date,
                            provider_id,
                            str(series.adjustment_mode),
                            source_row[0],
                        ),
                    ).fetchone()
                    if existing is not None:
                        continue
                    revision = connection.execute(
                        """
                        SELECT COALESCE(MAX(revision_number), 0) + 1
                        FROM analytics.daily_price_observation
                        WHERE security_id = %s AND trading_date = %s
                          AND provider_id = %s AND adjustment_mode = %s
                        """,
                        (
                            security_id,
                            bar.trading_date,
                            provider_id,
                            str(series.adjustment_mode),
                        ),
                    ).fetchone()
                    assert revision is not None
                    immutable_rows.append(
                        (
                            security_id,
                            bar.trading_date,
                            bar.open_price,
                            bar.high_price,
                            bar.low_price,
                            bar.close_price,
                            bar.adjusted_close,
                            bar.volume,
                            provider_id,
                            str(series.adjustment_mode),
                            series.security.exchange_timezone,
                            source_row[0],
                            series.available_at,
                            ingested_at,
                            revision[0],
                        )
                    )
                cursor.executemany(
                    """
                    INSERT INTO analytics.daily_price_observation (
                        security_id, trading_date, open_price, high_price,
                        low_price, close_price, adjusted_close, volume, provider_id,
                        adjustment_mode, source_timezone, source_record_id,
                        available_at, ingested_at, normalization_version,
                        quality_status, revision_number
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, 'market-normalization-v1.0.0', 'PROVISIONAL', %s
                    )
                    ON CONFLICT (
                        security_id, trading_date, provider_id,
                        adjustment_mode, revision_number
                    ) DO NOTHING
                    """,
                    immutable_rows,
                )
        return len(rows)
