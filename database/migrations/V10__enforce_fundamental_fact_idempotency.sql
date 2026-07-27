ALTER TABLE analytics.fundamental_fact
    DROP CONSTRAINT uq_fundamental_fact_source;

ALTER TABLE analytics.fundamental_fact
    ADD CONSTRAINT uq_fundamental_fact_source
    UNIQUE NULLS NOT DISTINCT (
        security_id,
        metric_code,
        period_start,
        period_end,
        fiscal_period,
        source_record_id
    );
