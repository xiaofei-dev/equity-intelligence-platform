from collections.abc import Sequence

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
                ON CONFLICT (symbol, exchange) DO UPDATE SET
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
                    series.adjustment_mode,
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
        return len(rows)
