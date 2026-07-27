CREATE TABLE analytics.data_snapshot (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_key VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'BUILDING',
    as_of_time TIMESTAMPTZ NOT NULL,
    ingestion_cutoff TIMESTAMPTZ NOT NULL,
    market_normalization_version VARCHAR(64) NOT NULL,
    fundamental_normalization_version VARCHAR(64) NOT NULL,
    action_normalization_version VARCHAR(64) NOT NULL,
    manifest_hash VARCHAR(128) NOT NULL,
    source_count INTEGER,
    security_count INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sealed_at TIMESTAMPTZ,
    failure_code VARCHAR(64),
    CONSTRAINT uq_data_snapshot_key UNIQUE (snapshot_key),
    CONSTRAINT uq_data_snapshot_manifest_hash UNIQUE (manifest_hash),
    CONSTRAINT ck_data_snapshot_status
        CHECK (status IN ('BUILDING', 'READY', 'FAILED')),
    CONSTRAINT ck_data_snapshot_cutoff
        CHECK (ingestion_cutoff >= as_of_time),
    CONSTRAINT ck_data_snapshot_counts
        CHECK (
            (source_count IS NULL OR source_count >= 0)
            AND (security_count IS NULL OR security_count >= 0)
        ),
    CONSTRAINT ck_data_snapshot_completion
        CHECK (
            (status = 'BUILDING' AND sealed_at IS NULL)
            OR (
                status = 'READY'
                AND sealed_at IS NOT NULL
                AND source_count IS NOT NULL
                AND security_count IS NOT NULL
            )
            OR (status = 'FAILED' AND sealed_at IS NOT NULL)
        )
);

CREATE INDEX ix_data_snapshot_as_of
    ON analytics.data_snapshot (as_of_time DESC);
CREATE INDEX ix_data_snapshot_status_created
    ON analytics.data_snapshot (status, created_at);

CREATE TABLE analytics.data_snapshot_source (
    snapshot_id UUID NOT NULL REFERENCES analytics.data_snapshot (id),
    ingestion_batch_id UUID NOT NULL REFERENCES analytics.ingestion_batch (id),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (snapshot_id, ingestion_batch_id)
);

CREATE INDEX ix_data_snapshot_source_batch
    ON analytics.data_snapshot_source (ingestion_batch_id);

CREATE TABLE analytics.universe_definition (
    version VARCHAR(128) PRIMARY KEY,
    effective_at TIMESTAMPTZ NOT NULL,
    configuration JSONB NOT NULL,
    configuration_hash VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_universe_definition_hash UNIQUE (configuration_hash),
    CONSTRAINT ck_universe_definition_configuration
        CHECK (jsonb_typeof(configuration) = 'object')
);

CREATE TABLE analytics.snapshot_universe_member (
    snapshot_id UUID NOT NULL REFERENCES analytics.data_snapshot (id),
    universe_version VARCHAR(128) NOT NULL
        REFERENCES analytics.universe_definition (version),
    security_id BIGINT NOT NULL REFERENCES analytics.security (id),
    membership_status VARCHAR(32) NOT NULL,
    membership_reason VARCHAR(255) NOT NULL,
    symbol_at_snapshot VARCHAR(32) NOT NULL,
    company_type_at_snapshot VARCHAR(64) NOT NULL,
    normalized_sector_at_snapshot VARCHAR(128),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (snapshot_id, universe_version, security_id),
    CONSTRAINT ck_snapshot_universe_membership_status
        CHECK (membership_status IN ('INCLUDED', 'EXCLUDED', 'REFERENCE_ONLY'))
);

CREATE INDEX ix_snapshot_universe_member_status
    ON analytics.snapshot_universe_member
        (snapshot_id, universe_version, membership_status);
CREATE INDEX ix_snapshot_universe_member_security
    ON analytics.snapshot_universe_member (security_id, snapshot_id);

CREATE FUNCTION analytics.reject_sealed_snapshot_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status IN ('READY', 'FAILED') THEN
        RAISE EXCEPTION 'Sealed data snapshots are immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER tr_data_snapshot_immutable
BEFORE UPDATE OR DELETE ON analytics.data_snapshot
FOR EACH ROW EXECUTE FUNCTION analytics.reject_sealed_snapshot_change();

CREATE FUNCTION analytics.reject_sealed_snapshot_child_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    parent_status VARCHAR(32);
BEGIN
    SELECT status INTO parent_status
    FROM analytics.data_snapshot
    WHERE id = COALESCE(NEW.snapshot_id, OLD.snapshot_id);

    IF parent_status IN ('READY', 'FAILED') THEN
        RAISE EXCEPTION 'Children of sealed data snapshots are immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER tr_data_snapshot_source_immutable
BEFORE INSERT OR UPDATE OR DELETE ON analytics.data_snapshot_source
FOR EACH ROW EXECUTE FUNCTION analytics.reject_sealed_snapshot_child_change();

CREATE TRIGGER tr_snapshot_universe_member_immutable
BEFORE INSERT OR UPDATE OR DELETE ON analytics.snapshot_universe_member
FOR EACH ROW EXECUTE FUNCTION analytics.reject_sealed_snapshot_child_change();

INSERT INTO analytics.universe_definition (
    version,
    effective_at,
    configuration,
    configuration_hash
)
VALUES (
    'universe-us-general-company-v1.0.0',
    TIMESTAMPTZ '2026-07-26 00:00:00Z',
    '{"market":"US","instrument":"COMMON_STOCK","currency":"USD","companyType":"MATURE_OPERATING_COMPANY","minimumMarketCapUsd":500000000,"minimumMedianDollarVolume60dUsd":2000000}'::jsonb,
    'sha256:universe-us-general-company-v1.0.0'
);
