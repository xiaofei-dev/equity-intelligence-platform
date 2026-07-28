ALTER TABLE analytics.data_snapshot
    ADD COLUMN market_data_provider VARCHAR(64) NOT NULL DEFAULT 'twelve_data',
    ADD COLUMN market_adjustment_mode VARCHAR(32) NOT NULL DEFAULT 'SPLIT_ADJUSTED';

ALTER TABLE analytics.data_snapshot
    ADD CONSTRAINT ck_data_snapshot_market_adjustment_mode
    CHECK (
        market_adjustment_mode IN (
            'UNADJUSTED', 'SPLIT_ADJUSTED', 'TOTAL_RETURN_ADJUSTED'
        )
    );

CREATE INDEX ix_data_snapshot_market_provider
    ON analytics.data_snapshot (market_data_provider, as_of_time DESC);
