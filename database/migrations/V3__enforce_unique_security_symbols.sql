WITH canonical_security AS (
    SELECT symbol, MIN(id) AS canonical_id
    FROM analytics.security
    GROUP BY symbol
),
duplicate_prices AS (
    SELECT
        canonical_security.canonical_id AS security_id,
        price.trading_date,
        price.open_price,
        price.high_price,
        price.low_price,
        price.close_price,
        price.volume,
        price.provider,
        price.adjustment_mode,
        price.source_timezone,
        price.ingested_at
    FROM analytics.daily_price price
    JOIN analytics.security security
        ON security.id = price.security_id
    JOIN canonical_security
        ON canonical_security.symbol = security.symbol
    WHERE price.security_id <> canonical_security.canonical_id
)
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
    source_timezone,
    ingested_at
)
SELECT
    security_id,
    trading_date,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    provider,
    adjustment_mode,
    source_timezone,
    ingested_at
FROM duplicate_prices
ON CONFLICT (security_id, trading_date, provider, adjustment_mode)
DO UPDATE SET
    open_price = EXCLUDED.open_price,
    high_price = EXCLUDED.high_price,
    low_price = EXCLUDED.low_price,
    close_price = EXCLUDED.close_price,
    volume = EXCLUDED.volume,
    source_timezone = EXCLUDED.source_timezone,
    ingested_at = GREATEST(
        analytics.daily_price.ingested_at,
        EXCLUDED.ingested_at
    );

WITH canonical_security AS (
    SELECT symbol, MIN(id) AS canonical_id
    FROM analytics.security
    GROUP BY symbol
)
DELETE FROM analytics.daily_price price
USING analytics.security security, canonical_security
WHERE price.security_id = security.id
  AND canonical_security.symbol = security.symbol
  AND security.id <> canonical_security.canonical_id;

WITH canonical_security AS (
    SELECT symbol, MIN(id) AS canonical_id
    FROM analytics.security
    GROUP BY symbol
)
DELETE FROM analytics.security security
USING canonical_security
WHERE canonical_security.symbol = security.symbol
  AND security.id <> canonical_security.canonical_id;

ALTER TABLE analytics.security
    DROP CONSTRAINT uq_security_symbol_exchange;

ALTER TABLE analytics.security
    ADD CONSTRAINT uq_security_symbol UNIQUE (symbol);
