CREATE TABLE analytics.refresh_plan (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_key VARCHAR(128) NOT NULL,
    plan_version INTEGER NOT NULL,
    dataset_code VARCHAR(128) NOT NULL
        REFERENCES analytics.dataset_definition (dataset_code),
    provider_id BIGINT REFERENCES analytics.data_provider (id),
    cadence VARCHAR(32) NOT NULL,
    target_scope JSONB NOT NULL,
    freshness_target INTERVAL NOT NULL,
    task_timeout INTERVAL NOT NULL,
    maximum_attempts INTEGER NOT NULL,
    active_from TIMESTAMPTZ NOT NULL,
    active_to TIMESTAMPTZ,
    definition_hash VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_refresh_plan_version UNIQUE (plan_key, plan_version),
    CONSTRAINT uq_refresh_plan_hash UNIQUE (definition_hash),
    CONSTRAINT ck_refresh_plan_version CHECK (plan_version > 0),
    CONSTRAINT ck_refresh_plan_cadence
        CHECK (cadence IN ('DAILY', 'WEEKLY', 'MONTHLY', 'ON_DEMAND')),
    CONSTRAINT ck_refresh_plan_scope CHECK (jsonb_typeof(target_scope) = 'object'),
    CONSTRAINT ck_refresh_plan_intervals
        CHECK (freshness_target > INTERVAL '0' AND task_timeout > INTERVAL '0'),
    CONSTRAINT ck_refresh_plan_attempts CHECK (maximum_attempts > 0),
    CONSTRAINT ck_refresh_plan_range
        CHECK (active_to IS NULL OR active_to > active_from)
);

CREATE TABLE analytics.refresh_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    refresh_plan_id UUID NOT NULL REFERENCES analytics.refresh_plan (id),
    idempotency_key VARCHAR(255) NOT NULL,
    canonical_request_hash VARCHAR(128) NOT NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    checkpoint_sequence INTEGER NOT NULL DEFAULT 0,
    result_hash VARCHAR(128),
    error_code VARCHAR(64),
    CONSTRAINT uq_refresh_run_idempotency
        UNIQUE (refresh_plan_id, idempotency_key),
    CONSTRAINT ck_refresh_run_status
        CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')),
    CONSTRAINT ck_refresh_run_checkpoint CHECK (checkpoint_sequence >= 0),
    CONSTRAINT ck_refresh_run_times CHECK (
        (status = 'PENDING' AND started_at IS NULL AND completed_at IS NULL)
        OR (status = 'RUNNING' AND started_at IS NOT NULL AND completed_at IS NULL)
        OR (status IN ('SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')
            AND completed_at IS NOT NULL
            AND (started_at IS NULL OR completed_at >= started_at))
    ),
    CONSTRAINT ck_refresh_run_result
        CHECK (status <> 'SUCCEEDED' OR result_hash IS NOT NULL),
    CONSTRAINT ck_refresh_run_error
        CHECK (status NOT IN ('PARTIAL', 'FAILED') OR error_code IS NOT NULL)
);

CREATE INDEX ix_refresh_run_claim
    ON analytics.refresh_run (status, scheduled_for, requested_at)
    WHERE status IN ('PENDING', 'RUNNING');
CREATE INDEX ix_refresh_run_plan_history
    ON analytics.refresh_run (refresh_plan_id, scheduled_for DESC);

CREATE TABLE analytics.refresh_task (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    refresh_run_id UUID NOT NULL REFERENCES analytics.refresh_run (id),
    security_id BIGINT REFERENCES analytics.security (id),
    partition_key VARCHAR(255) NOT NULL,
    task_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    attempt_number INTEGER NOT NULL DEFAULT 1,
    available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    claimed_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    ingestion_batch_id UUID REFERENCES analytics.ingestion_batch (id),
    records_observed BIGINT NOT NULL DEFAULT 0,
    records_rejected BIGINT NOT NULL DEFAULT 0,
    error_code VARCHAR(64),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_refresh_task_attempt
        UNIQUE (refresh_run_id, partition_key, task_type, attempt_number),
    CONSTRAINT ck_refresh_task_status
        CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'SKIPPED', 'FAILED')),
    CONSTRAINT ck_refresh_task_attempt CHECK (attempt_number > 0),
    CONSTRAINT ck_refresh_task_counts
        CHECK (records_observed >= 0 AND records_rejected >= 0),
    CONSTRAINT ck_refresh_task_lease
        CHECK (
            (status = 'RUNNING' AND claimed_at IS NOT NULL
                AND lease_expires_at > claimed_at AND completed_at IS NULL)
            OR status <> 'RUNNING'
        ),
    CONSTRAINT ck_refresh_task_completed
        CHECK (
            status IN ('PENDING', 'RUNNING')
            OR completed_at IS NOT NULL
        ),
    CONSTRAINT ck_refresh_task_error
        CHECK (status <> 'FAILED' OR error_code IS NOT NULL)
);

CREATE INDEX ix_refresh_task_claim
    ON analytics.refresh_task (status, available_at, lease_expires_at)
    WHERE status IN ('PENDING', 'RUNNING');
CREATE INDEX ix_refresh_task_security
    ON analytics.refresh_task (security_id, task_type, completed_at DESC)
    WHERE security_id IS NOT NULL;

CREATE TABLE analytics.refresh_checkpoint (
    refresh_run_id UUID NOT NULL REFERENCES analytics.refresh_run (id),
    sequence_number INTEGER NOT NULL,
    checkpoint_key VARCHAR(255) NOT NULL,
    checkpoint_value JSONB NOT NULL,
    checkpoint_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (refresh_run_id, sequence_number),
    CONSTRAINT uq_refresh_checkpoint_key
        UNIQUE (refresh_run_id, checkpoint_key),
    CONSTRAINT ck_refresh_checkpoint_sequence CHECK (sequence_number > 0),
    CONSTRAINT ck_refresh_checkpoint_value
        CHECK (jsonb_typeof(checkpoint_value) = 'object')
);

CREATE TABLE analytics.security_dataset_freshness (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    security_id BIGINT NOT NULL REFERENCES analytics.security (id),
    dataset_code VARCHAR(128) NOT NULL
        REFERENCES analytics.dataset_definition (dataset_code),
    provider_id BIGINT REFERENCES analytics.data_provider (id),
    refresh_task_id UUID NOT NULL REFERENCES analytics.refresh_task (id),
    status VARCHAR(32) NOT NULL,
    last_successful_effective_at TIMESTAMPTZ,
    last_successful_available_at TIMESTAMPTZ,
    last_successful_ingested_at TIMESTAMPTZ,
    evaluated_at TIMESTAMPTZ NOT NULL,
    stale_after TIMESTAMPTZ,
    reason_code VARCHAR(64),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_security_dataset_freshness_event
        UNIQUE NULLS NOT DISTINCT (
            security_id, dataset_code, provider_id, refresh_task_id
        ),
    CONSTRAINT ck_security_dataset_freshness_status
        CHECK (status IN ('CURRENT', 'STALE', 'MISSING', 'INVALID', 'NOT_APPLICABLE')),
    CONSTRAINT ck_security_dataset_freshness_success CHECK (
        (
            status IN ('CURRENT', 'STALE')
            AND last_successful_effective_at IS NOT NULL
            AND last_successful_available_at IS NOT NULL
            AND last_successful_ingested_at IS NOT NULL
            AND stale_after IS NOT NULL
        )
        OR (
            status IN ('MISSING', 'INVALID', 'NOT_APPLICABLE')
            AND reason_code IS NOT NULL
        )
    ),
    CONSTRAINT ck_security_dataset_freshness_times CHECK (
        last_successful_effective_at IS NULL
        OR (
            last_successful_available_at >= last_successful_effective_at
            AND last_successful_ingested_at >= last_successful_available_at
        )
    )
);

CREATE INDEX ix_security_dataset_freshness_latest
    ON analytics.security_dataset_freshness (
        security_id, dataset_code, provider_id, evaluated_at DESC
    );
CREATE INDEX ix_security_dataset_freshness_stale
    ON analytics.security_dataset_freshness (
        dataset_code, status, stale_after, security_id
    );

CREATE TABLE analytics.provider_usage_event (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    provider_id BIGINT NOT NULL REFERENCES analytics.data_provider (id),
    refresh_run_id UUID REFERENCES analytics.refresh_run (id),
    refresh_task_id UUID REFERENCES analytics.refresh_task (id),
    account_reference_hash VARCHAR(128),
    endpoint_code VARCHAR(128) NOT NULL,
    request_count INTEGER NOT NULL,
    unit_count NUMERIC(20, 6) NOT NULL,
    estimated_cost NUMERIC(20, 8),
    cost_currency CHAR(3),
    quota_limit NUMERIC(20, 6),
    quota_remaining NUMERIC(20, 6),
    window_started_at TIMESTAMPTZ,
    window_ends_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_provider_usage_idempotency
        UNIQUE (provider_id, idempotency_key),
    CONSTRAINT ck_provider_usage_counts
        CHECK (request_count >= 0 AND unit_count >= 0),
    CONSTRAINT ck_provider_usage_cost
        CHECK (estimated_cost IS NULL OR estimated_cost >= 0),
    CONSTRAINT ck_provider_usage_quota
        CHECK (
            (quota_limit IS NULL AND quota_remaining IS NULL)
            OR (quota_limit >= 0 AND quota_remaining BETWEEN 0 AND quota_limit)
        ),
    CONSTRAINT ck_provider_usage_window
        CHECK (
            window_started_at IS NULL
            OR (window_ends_at IS NOT NULL AND window_ends_at > window_started_at)
        ),
    CONSTRAINT ck_provider_usage_currency
        CHECK (
            (estimated_cost IS NULL AND cost_currency IS NULL)
            OR (estimated_cost IS NOT NULL AND cost_currency IS NOT NULL)
        )
);

CREATE INDEX ix_provider_usage_window
    ON analytics.provider_usage_event (provider_id, observed_at DESC);
CREATE INDEX ix_provider_usage_run
    ON analytics.provider_usage_event (refresh_run_id)
    WHERE refresh_run_id IS NOT NULL;

CREATE TABLE analytics.analytics_audit_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(64) NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    entity_id VARCHAR(255) NOT NULL,
    actor_service VARCHAR(32) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    correlation_id VARCHAR(255),
    event_hash VARCHAR(128) NOT NULL,
    detail JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_analytics_audit_hash UNIQUE (event_hash),
    CONSTRAINT ck_analytics_audit_actor
        CHECK (actor_service IN ('PYTHON_ANALYTICS', 'FLYWAY')),
    CONSTRAINT ck_analytics_audit_detail CHECK (jsonb_typeof(detail) = 'object')
);

CREATE INDEX ix_analytics_audit_entity
    ON analytics.analytics_audit_event (entity_type, entity_id, occurred_at DESC);
CREATE INDEX ix_analytics_audit_correlation
    ON analytics.analytics_audit_event (correlation_id)
    WHERE correlation_id IS NOT NULL;

CREATE INDEX ix_daily_price_observation_daily_workload
    ON analytics.daily_price_observation (
        provider_id, adjustment_mode, trading_date DESC, security_id,
        available_at DESC, ingested_at DESC
    );
CREATE INDEX ix_fundamental_fact_daily_workload
    ON analytics.fundamental_fact (
        security_id, available_at DESC, ingested_at DESC, metric_code, period_end DESC
    )
    WHERE quality_status <> 'REJECTED';
CREATE INDEX ix_security_listing_pit
    ON analytics.security_listing (
        security_id, valid_from DESC, valid_to, symbol, mic
    );
CREATE INDEX ix_security_classification_pit
    ON analytics.security_classification (
        security_id, effective_from DESC, effective_to,
        normalized_sector, normalized_industry
    );

CREATE FUNCTION analytics.reject_terminal_refresh_run_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status IN ('SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED') THEN
        RAISE EXCEPTION 'Terminal refresh runs are immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.reject_terminal_refresh_task_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status IN ('SUCCEEDED', 'SKIPPED', 'FAILED') THEN
        RAISE EXCEPTION 'Terminal refresh tasks are immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER tr_refresh_plan_append_only
BEFORE UPDATE OR DELETE ON analytics.refresh_plan
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();
CREATE TRIGGER tr_refresh_run_terminal_immutable
BEFORE UPDATE OR DELETE ON analytics.refresh_run
FOR EACH ROW EXECUTE FUNCTION analytics.reject_terminal_refresh_run_change();
CREATE TRIGGER tr_refresh_task_terminal_immutable
BEFORE UPDATE OR DELETE ON analytics.refresh_task
FOR EACH ROW EXECUTE FUNCTION analytics.reject_terminal_refresh_task_change();
CREATE TRIGGER tr_refresh_checkpoint_append_only
BEFORE UPDATE OR DELETE ON analytics.refresh_checkpoint
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();
CREATE TRIGGER tr_security_freshness_append_only
BEFORE UPDATE OR DELETE ON analytics.security_dataset_freshness
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();
CREATE TRIGGER tr_provider_usage_append_only
BEFORE UPDATE OR DELETE ON analytics.provider_usage_event
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();
CREATE TRIGGER tr_analytics_audit_append_only
BEFORE UPDATE OR DELETE ON analytics.analytics_audit_event
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();

COMMENT ON TABLE analytics.refresh_run IS
    'Python-owned idempotent refresh execution; operational status updates are permitted until terminal.';
COMMENT ON TABLE analytics.security_dataset_freshness IS
    'Append-only per-security freshness assessments; the latest event is the current projection.';
COMMENT ON TABLE analytics.provider_usage_event IS
    'Append-only quota and estimated-cost telemetry containing no credential or secret values.';
COMMENT ON TABLE analytics.analytics_audit_event IS
    'Append-only analytics audit trail retained according to documented policy.';
