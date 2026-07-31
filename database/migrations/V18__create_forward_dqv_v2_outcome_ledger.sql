CREATE TABLE analytics.forward_dqv_enrollment_v2 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    canonical_request_hash VARCHAR(128) NOT NULL,
    contract_version VARCHAR(128) NOT NULL,
    preregistration_content_hash VARCHAR(128) NOT NULL,
    decision_manifest_content_hash VARCHAR(128) NOT NULL,
    decision_controlled_artifact_hash VARCHAR(128) NOT NULL,
    decision_controlled_artifact_reference VARCHAR(2048) NOT NULL,
    decision_data_snapshot_id UUID NOT NULL REFERENCES analytics.data_snapshot (id),
    decision_as_of TIMESTAMPTZ NOT NULL,
    effective_at_completed_session_open TIMESTAMPTZ NOT NULL,
    universe_version VARCHAR(128) NOT NULL
        REFERENCES analytics.universe_definition (version),
    frozen_population_hash VARCHAR(128) NOT NULL,
    model_freeze_hashes JSONB NOT NULL,
    benchmark_contract_version VARCHAR(128) NOT NULL,
    benchmark_contract_hash VARCHAR(128) NOT NULL,
    cost_policy_version VARCHAR(128) NOT NULL,
    cost_policy_hash VARCHAR(128) NOT NULL,
    security_count INTEGER NOT NULL,
    terminal_counts JSONB NOT NULL,
    enrollment_content_hash VARCHAR(128) NOT NULL UNIQUE,
    sealed_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_forward_dqv_enrollment_contract
        CHECK (contract_version = 'FORWARD-DQV-ENROLLMENT-v2.1.0'),
    CONSTRAINT ck_forward_dqv_enrollment_hashes CHECK (
        canonical_request_hash ~ '^sha256:[0-9a-f]{64}$'
        AND preregistration_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND decision_manifest_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND decision_controlled_artifact_hash ~ '^sha256:[0-9a-f]{64}$'
        AND frozen_population_hash ~ '^sha256:[0-9a-f]{64}$'
        AND benchmark_contract_hash ~ '^sha256:[0-9a-f]{64}$'
        AND cost_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        AND enrollment_content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_forward_dqv_enrollment_population
        CHECK (security_count > 0),
    CONSTRAINT ck_forward_dqv_enrollment_json CHECK (
        jsonb_typeof(model_freeze_hashes) = 'object'
        AND model_freeze_hashes <> '{}'::jsonb
        AND jsonb_typeof(terminal_counts) = 'object'
        AND terminal_counts <> '{}'::jsonb
    ),
    CONSTRAINT ck_forward_dqv_enrollment_chronology CHECK (
        decision_as_of <= effective_at_completed_session_open
        AND effective_at_completed_session_open <= sealed_at
    )
);

CREATE TABLE analytics.forward_dqv_maturity_schedule_v2 (
    enrollment_id UUID NOT NULL
        REFERENCES analytics.forward_dqv_enrollment_v2 (id),
    completed_sessions INTEGER NOT NULL,
    evaluation_role VARCHAR(64) NOT NULL,
    formal_gate_eligible BOOLEAN NOT NULL,
    matures_at_completed_session TIMESTAMPTZ NOT NULL,
    schedule_content_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (enrollment_id, completed_sessions),
    CONSTRAINT ck_forward_dqv_maturity_horizon
        CHECK (completed_sessions IN (5, 20, 60, 126, 252)),
    CONSTRAINT ck_forward_dqv_maturity_role CHECK (
        (
            completed_sessions IN (5, 20, 60)
            AND evaluation_role = 'TACTICAL_FORMAL'
            AND formal_gate_eligible
        )
        OR (
            completed_sessions = 126
            AND evaluation_role = 'LONG_HORIZON_INTERIM_DIAGNOSTIC'
            AND NOT formal_gate_eligible
        )
        OR (
            completed_sessions = 252
            AND evaluation_role = 'LONG_HORIZON_FORMAL'
            AND formal_gate_eligible
        )
    ),
    CONSTRAINT ck_forward_dqv_maturity_hash
        CHECK (schedule_content_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE analytics.forward_dqv_outcome_batch_v2 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id UUID NOT NULL,
    completed_sessions INTEGER NOT NULL,
    contract_version VARCHAR(128) NOT NULL,
    result_version INTEGER NOT NULL,
    supersedes_batch_id UUID UNIQUE
        REFERENCES analytics.forward_dqv_outcome_batch_v2 (id),
    observed_at TIMESTAMPTZ NOT NULL,
    matured_at_completed_session TIMESTAMPTZ NOT NULL,
    evaluation_role VARCHAR(64) NOT NULL,
    operational_completeness VARCHAR(32) NOT NULL,
    security_count INTEGER NOT NULL,
    benchmark_count INTEGER NOT NULL,
    terminal_counts JSONB NOT NULL,
    preregistration_content_hash VARCHAR(128) NOT NULL,
    decision_manifest_content_hash VARCHAR(128) NOT NULL,
    frozen_population_hash VARCHAR(128) NOT NULL,
    model_freeze_hashes JSONB NOT NULL,
    benchmark_contract_hash VARCHAR(128) NOT NULL,
    cost_policy_hash VARCHAR(128) NOT NULL,
    source_manifest_hash VARCHAR(128) NOT NULL,
    calendar_evidence_hash VARCHAR(128) NOT NULL,
    action_evidence_hash VARCHAR(128) NOT NULL,
    price_evidence_hash VARCHAR(128) NOT NULL,
    evidence_blockers JSONB NOT NULL DEFAULT '[]'::jsonb,
    outcome_batch_content_hash VARCHAR(128) NOT NULL UNIQUE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_forward_dqv_batch_maturity
        FOREIGN KEY (enrollment_id, completed_sessions)
        REFERENCES analytics.forward_dqv_maturity_schedule_v2 (
            enrollment_id, completed_sessions
        ),
    CONSTRAINT uq_forward_dqv_batch_version
        UNIQUE (enrollment_id, completed_sessions, result_version),
    CONSTRAINT ck_forward_dqv_batch_contract
        CHECK (contract_version = 'FORWARD-DQV-OUTCOME-v2.1.0'),
    CONSTRAINT ck_forward_dqv_batch_version CHECK (result_version > 0),
    CONSTRAINT ck_forward_dqv_batch_state
        CHECK (operational_completeness IN ('COMPLETE', 'INCOMPLETE', 'BLOCKED')),
    CONSTRAINT ck_forward_dqv_batch_counts CHECK (
        security_count > 0
        AND benchmark_count BETWEEN 0 AND 6
    ),
    CONSTRAINT ck_forward_dqv_batch_json CHECK (
        jsonb_typeof(terminal_counts) = 'object'
        AND jsonb_typeof(model_freeze_hashes) = 'object'
        AND model_freeze_hashes <> '{}'::jsonb
        AND jsonb_typeof(evidence_blockers) = 'array'
    ),
    CONSTRAINT ck_forward_dqv_batch_blockers CHECK (
        (operational_completeness = 'COMPLETE' AND evidence_blockers = '[]'::jsonb)
        OR (operational_completeness <> 'COMPLETE' AND evidence_blockers <> '[]'::jsonb)
    ),
    CONSTRAINT ck_forward_dqv_batch_hashes CHECK (
        preregistration_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND decision_manifest_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND frozen_population_hash ~ '^sha256:[0-9a-f]{64}$'
        AND benchmark_contract_hash ~ '^sha256:[0-9a-f]{64}$'
        AND cost_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        AND source_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
        AND calendar_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
        AND action_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
        AND price_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
        AND outcome_batch_content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_forward_dqv_batch_chronology
        CHECK (matured_at_completed_session <= observed_at),
    CONSTRAINT ck_forward_dqv_batch_correction_shape CHECK (
        (result_version = 1 AND supersedes_batch_id IS NULL)
        OR (result_version > 1 AND supersedes_batch_id IS NOT NULL)
    )
);

CREATE TABLE analytics.forward_dqv_security_outcome_v2 (
    outcome_batch_id UUID NOT NULL
        REFERENCES analytics.forward_dqv_outcome_batch_v2 (id),
    security_id BIGINT NOT NULL REFERENCES analytics.security (id),
    record_ordinal INTEGER NOT NULL,
    public_security_id UUID NOT NULL,
    state VARCHAR(32) NOT NULL,
    gross_return NUMERIC(30, 12),
    round_trip_cost_rate NUMERIC(30, 12),
    net_return NUMERIC(30, 12),
    price_action_evidence_hash VARCHAR(128),
    source_manifest_hash VARCHAR(128),
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    record_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (outcome_batch_id, security_id),
    CONSTRAINT uq_forward_dqv_security_ordinal
        UNIQUE (outcome_batch_id, record_ordinal),
    CONSTRAINT ck_forward_dqv_security_ordinal CHECK (record_ordinal >= 0),
    CONSTRAINT ck_forward_dqv_security_state CHECK (
        state IN ('ASSESSED', 'MISSING', 'STALE', 'INVALID', 'NOT_APPLICABLE', 'EXCLUDED')
    ),
    CONSTRAINT ck_forward_dqv_security_reason_json
        CHECK (jsonb_typeof(reason_codes) = 'array'),
    CONSTRAINT ck_forward_dqv_security_values CHECK (
        (
            state = 'ASSESSED'
            AND gross_return IS NOT NULL
            AND round_trip_cost_rate IS NOT NULL
            AND net_return IS NOT NULL
            AND round_trip_cost_rate >= 0
            AND abs(net_return - (gross_return - round_trip_cost_rate))
                <= 0.000000000001
            AND price_action_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
            AND source_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
            AND reason_codes = '[]'::jsonb
        )
        OR (
            state <> 'ASSESSED'
            AND gross_return IS NULL
            AND round_trip_cost_rate IS NULL
            AND net_return IS NULL
            AND price_action_evidence_hash IS NULL
            AND source_manifest_hash IS NULL
            AND reason_codes <> '[]'::jsonb
        )
    ),
    CONSTRAINT ck_forward_dqv_security_record_hash
        CHECK (record_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE analytics.forward_dqv_benchmark_outcome_v2 (
    outcome_batch_id UUID NOT NULL
        REFERENCES analytics.forward_dqv_outcome_batch_v2 (id),
    record_ordinal INTEGER NOT NULL,
    benchmark_kind VARCHAR(32) NOT NULL,
    benchmark_identifier VARCHAR(255) NOT NULL,
    state VARCHAR(32) NOT NULL,
    gross_return NUMERIC(30, 12),
    round_trip_cost_rate NUMERIC(30, 12),
    net_return NUMERIC(30, 12),
    price_action_evidence_hash VARCHAR(128),
    source_manifest_hash VARCHAR(128),
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    record_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (outcome_batch_id, benchmark_kind),
    CONSTRAINT uq_forward_dqv_benchmark_ordinal
        UNIQUE (outcome_batch_id, record_ordinal),
    CONSTRAINT ck_forward_dqv_benchmark_ordinal CHECK (record_ordinal >= 0),
    CONSTRAINT ck_forward_dqv_benchmark_kind CHECK (
        benchmark_kind IN (
            'SPY', 'SECTOR', 'EQUAL_WEIGHT',
            'PURE_MOMENTUM', 'PURE_VALUE', 'PURE_QUALITY'
        )
    ),
    CONSTRAINT ck_forward_dqv_benchmark_state
        CHECK (state IN ('AVAILABLE', 'MISSING', 'STALE', 'INVALID')),
    CONSTRAINT ck_forward_dqv_benchmark_reason_json
        CHECK (jsonb_typeof(reason_codes) = 'array'),
    CONSTRAINT ck_forward_dqv_benchmark_values CHECK (
        (
            state = 'AVAILABLE'
            AND gross_return IS NOT NULL
            AND round_trip_cost_rate IS NOT NULL
            AND net_return IS NOT NULL
            AND round_trip_cost_rate >= 0
            AND abs(net_return - (gross_return - round_trip_cost_rate))
                <= 0.000000000001
            AND price_action_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
            AND source_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
            AND reason_codes = '[]'::jsonb
        )
        OR (
            state <> 'AVAILABLE'
            AND gross_return IS NULL
            AND round_trip_cost_rate IS NULL
            AND net_return IS NULL
            AND price_action_evidence_hash IS NULL
            AND source_manifest_hash IS NULL
            AND reason_codes <> '[]'::jsonb
        )
    ),
    CONSTRAINT ck_forward_dqv_benchmark_record_hash
        CHECK (record_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE analytics.forward_dqv_path_metric_v2 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outcome_batch_id UUID NOT NULL
        REFERENCES analytics.forward_dqv_outcome_batch_v2 (id),
    record_ordinal INTEGER NOT NULL,
    subject_type VARCHAR(16) NOT NULL,
    security_id BIGINT REFERENCES analytics.security (id),
    benchmark_kind VARCHAR(32),
    metric_code VARCHAR(64) NOT NULL,
    state VARCHAR(32) NOT NULL,
    metric_value NUMERIC(30, 12),
    source_evidence_hash VARCHAR(128),
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    metric_record_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_forward_dqv_metric_ordinal
        UNIQUE (outcome_batch_id, record_ordinal),
    CONSTRAINT ck_forward_dqv_metric_ordinal CHECK (record_ordinal >= 0),
    CONSTRAINT ck_forward_dqv_metric_subject_type
        CHECK (subject_type IN ('SECURITY', 'BENCHMARK', 'AGGREGATE')),
    CONSTRAINT ck_forward_dqv_metric_subject CHECK (
        (subject_type = 'SECURITY' AND security_id IS NOT NULL AND benchmark_kind IS NULL)
        OR (
            subject_type = 'BENCHMARK'
            AND security_id IS NULL
            AND benchmark_kind IN (
                'SPY', 'SECTOR', 'EQUAL_WEIGHT',
                'PURE_MOMENTUM', 'PURE_VALUE', 'PURE_QUALITY'
            )
        )
        OR (
            subject_type = 'AGGREGATE'
            AND security_id IS NULL
            AND benchmark_kind IS NULL
        )
    ),
    CONSTRAINT ck_forward_dqv_metric_code CHECK (
        metric_code IN (
            'MAXIMUM_ADVERSE_EXCURSION',
            'MAXIMUM_FAVORABLE_EXCURSION',
            'MAXIMUM_DRAWDOWN',
            'DOWNSIDE_CAPTURE',
            'BENCHMARK_MAXIMUM_DRAWDOWN'
        )
    ),
    CONSTRAINT ck_forward_dqv_metric_state
        CHECK (state IN ('VALID', 'MISSING', 'INVALID', 'NOT_APPLICABLE')),
    CONSTRAINT ck_forward_dqv_metric_reason_json
        CHECK (jsonb_typeof(reason_codes) = 'array'),
    CONSTRAINT ck_forward_dqv_metric_values CHECK (
        (
            state = 'VALID'
            AND metric_value IS NOT NULL
            AND source_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
            AND reason_codes = '[]'::jsonb
        )
        OR (
            state <> 'VALID'
            AND metric_value IS NULL
            AND source_evidence_hash IS NULL
            AND reason_codes <> '[]'::jsonb
        )
    ),
    CONSTRAINT ck_forward_dqv_metric_ranges CHECK (
        state <> 'VALID'
        OR metric_code NOT IN ('MAXIMUM_ADVERSE_EXCURSION', 'MAXIMUM_DRAWDOWN')
        OR metric_value BETWEEN -1 AND 0
    ),
    CONSTRAINT ck_forward_dqv_metric_mfe CHECK (
        state <> 'VALID'
        OR metric_code <> 'MAXIMUM_FAVORABLE_EXCURSION'
        OR metric_value >= 0
    ),
    CONSTRAINT ck_forward_dqv_metric_downside CHECK (
        state <> 'VALID'
        OR metric_code <> 'DOWNSIDE_CAPTURE'
        OR metric_value >= 0
    ),
    CONSTRAINT ck_forward_dqv_metric_record_hash
        CHECK (metric_record_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE UNIQUE INDEX uq_forward_dqv_security_metric
    ON analytics.forward_dqv_path_metric_v2 (
        outcome_batch_id, security_id, metric_code
    )
    WHERE subject_type = 'SECURITY';
CREATE UNIQUE INDEX uq_forward_dqv_benchmark_metric
    ON analytics.forward_dqv_path_metric_v2 (
        outcome_batch_id, benchmark_kind, metric_code
    )
    WHERE subject_type = 'BENCHMARK';
CREATE UNIQUE INDEX uq_forward_dqv_aggregate_metric
    ON analytics.forward_dqv_path_metric_v2 (
        outcome_batch_id, metric_code
    )
    WHERE subject_type = 'AGGREGATE';

CREATE TABLE analytics.forward_dqv_quality_report_v2 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id UUID NOT NULL
        REFERENCES analytics.forward_dqv_enrollment_v2 (id),
    completed_sessions INTEGER NOT NULL,
    contract_version VARCHAR(128) NOT NULL,
    model_track VARCHAR(32) NOT NULL,
    model_version VARCHAR(128) NOT NULL,
    evaluation_role VARCHAR(64) NOT NULL,
    result_version INTEGER NOT NULL,
    supersedes_report_id UUID UNIQUE
        REFERENCES analytics.forward_dqv_quality_report_v2 (id),
    assessed_at TIMESTAMPTZ NOT NULL,
    matured_through TIMESTAMPTZ NOT NULL,
    preregistration_content_hash VARCHAR(128) NOT NULL,
    operational_completeness VARCHAR(32) NOT NULL,
    model_quality_status VARCHAR(32) NOT NULL,
    target_results JSONB NOT NULL,
    source_outcome_batch_hashes JSONB NOT NULL,
    source_decision_manifest_hashes JSONB NOT NULL,
    resampling_policy_version VARCHAR(128) NOT NULL,
    resampling_policy_hash VARCHAR(128) NOT NULL,
    report_content_hash VARCHAR(128) NOT NULL UNIQUE,
    ordinary_iid_bootstrap_used BOOLEAN NOT NULL DEFAULT FALSE,
    ai_influence BOOLEAN NOT NULL DEFAULT FALSE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_forward_dqv_report_maturity
        FOREIGN KEY (enrollment_id, completed_sessions)
        REFERENCES analytics.forward_dqv_maturity_schedule_v2 (
            enrollment_id, completed_sessions
        ),
    CONSTRAINT uq_forward_dqv_report_version
        UNIQUE (enrollment_id, completed_sessions, model_track, result_version),
    CONSTRAINT ck_forward_dqv_report_contract
        CHECK (contract_version = 'FORWARD-DQV-QUALITY-REPORT-v2.1.0'),
    CONSTRAINT ck_forward_dqv_report_track
        CHECK (model_track IN ('TACTICAL', 'LONG_HORIZON')),
    CONSTRAINT ck_forward_dqv_report_version CHECK (result_version > 0),
    CONSTRAINT ck_forward_dqv_report_state CHECK (
        operational_completeness IN ('COMPLETE', 'INCOMPLETE', 'BLOCKED')
        AND model_quality_status IN (
            'NOT_MATURED', 'DIAGNOSTIC_ONLY', 'VALIDATED', 'MIXED',
            'NOT_VALIDATED', 'INSUFFICIENT_EVIDENCE', 'BLOCKED_BY_DATA'
        )
    ),
    CONSTRAINT ck_forward_dqv_report_json CHECK (
        jsonb_typeof(target_results) = 'array'
        AND target_results <> '[]'::jsonb
        AND jsonb_typeof(source_outcome_batch_hashes) = 'array'
        AND source_outcome_batch_hashes <> '[]'::jsonb
        AND jsonb_typeof(source_decision_manifest_hashes) = 'array'
        AND source_decision_manifest_hashes <> '[]'::jsonb
    ),
    CONSTRAINT ck_forward_dqv_report_hashes CHECK (
        preregistration_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND resampling_policy_hash ~ '^sha256:[0-9a-f]{64}$'
        AND report_content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_forward_dqv_report_chronology
        CHECK (matured_through <= assessed_at),
    CONSTRAINT ck_forward_dqv_report_correction_shape CHECK (
        (result_version = 1 AND supersedes_report_id IS NULL)
        OR (result_version > 1 AND supersedes_report_id IS NOT NULL)
    ),
    CONSTRAINT ck_forward_dqv_report_safety
        CHECK (NOT ordinary_iid_bootstrap_used AND NOT ai_influence)
);

CREATE FUNCTION analytics.validate_forward_dqv_batch_correction()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    predecessor analytics.forward_dqv_outcome_batch_v2%ROWTYPE;
BEGIN
    IF NEW.supersedes_batch_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT * INTO predecessor
    FROM analytics.forward_dqv_outcome_batch_v2
    WHERE id = NEW.supersedes_batch_id;

    IF predecessor.id IS NULL
       OR predecessor.enrollment_id <> NEW.enrollment_id
       OR predecessor.completed_sessions <> NEW.completed_sessions
       OR predecessor.result_version + 1 <> NEW.result_version THEN
        RAISE EXCEPTION 'Forward DQV batch correction predecessor is invalid';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_forward_dqv_report_correction()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    predecessor analytics.forward_dqv_quality_report_v2%ROWTYPE;
BEGIN
    IF NEW.supersedes_report_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT * INTO predecessor
    FROM analytics.forward_dqv_quality_report_v2
    WHERE id = NEW.supersedes_report_id;

    IF predecessor.id IS NULL
       OR predecessor.enrollment_id <> NEW.enrollment_id
       OR predecessor.completed_sessions <> NEW.completed_sessions
       OR predecessor.model_track <> NEW.model_track
       OR predecessor.result_version + 1 <> NEW.result_version THEN
        RAISE EXCEPTION 'Forward DQV quality-report correction predecessor is invalid';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_forward_dqv_enrollment_completeness()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    schedule_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO schedule_count
    FROM analytics.forward_dqv_maturity_schedule_v2
    WHERE enrollment_id = NEW.id;

    IF schedule_count <> 5 THEN
        RAISE EXCEPTION 'Forward DQV enrollment requires exactly five maturity rows';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION analytics.validate_forward_dqv_batch_completeness()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    expected_security_count INTEGER;
    actual_security_count INTEGER;
    actual_benchmark_count INTEGER;
    distinct_public_security_count INTEGER;
    invalid_identity_count INTEGER;
BEGIN
    IF NEW.operational_completeness <> 'COMPLETE' THEN
        RETURN NULL;
    END IF;

    SELECT security_count INTO expected_security_count
    FROM analytics.forward_dqv_enrollment_v2
    WHERE id = NEW.enrollment_id;

    SELECT COUNT(*), COUNT(DISTINCT public_security_id)
    INTO actual_security_count, distinct_public_security_count
    FROM analytics.forward_dqv_security_outcome_v2
    WHERE outcome_batch_id = NEW.id;

    SELECT COUNT(*) INTO invalid_identity_count
    FROM analytics.forward_dqv_security_outcome_v2 outcome
    JOIN analytics.security security ON security.id = outcome.security_id
    WHERE outcome.outcome_batch_id = NEW.id
      AND security.public_id <> outcome.public_security_id;

    SELECT COUNT(*) INTO actual_benchmark_count
    FROM analytics.forward_dqv_benchmark_outcome_v2
    WHERE outcome_batch_id = NEW.id;

    IF expected_security_count <> NEW.security_count
       OR actual_security_count <> expected_security_count
       OR distinct_public_security_count <> expected_security_count
       OR invalid_identity_count <> 0
       OR actual_benchmark_count <> 6
       OR NEW.benchmark_count <> 6 THEN
        RAISE EXCEPTION
            'Complete Forward DQV batch requires frozen population and six benchmarks';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER tr_forward_dqv_batch_correction
BEFORE INSERT ON analytics.forward_dqv_outcome_batch_v2
FOR EACH ROW EXECUTE FUNCTION analytics.validate_forward_dqv_batch_correction();

CREATE TRIGGER tr_forward_dqv_report_correction
BEFORE INSERT ON analytics.forward_dqv_quality_report_v2
FOR EACH ROW EXECUTE FUNCTION analytics.validate_forward_dqv_report_correction();

CREATE CONSTRAINT TRIGGER tr_forward_dqv_enrollment_complete
AFTER INSERT ON analytics.forward_dqv_enrollment_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION analytics.validate_forward_dqv_enrollment_completeness();

CREATE CONSTRAINT TRIGGER tr_forward_dqv_batch_complete
AFTER INSERT ON analytics.forward_dqv_outcome_batch_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION analytics.validate_forward_dqv_batch_completeness();

CREATE TRIGGER tr_forward_dqv_enrollment_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_enrollment_v2
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_maturity_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_maturity_schedule_v2
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_batch_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_outcome_batch_v2
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_security_outcome_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_security_outcome_v2
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_benchmark_outcome_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_benchmark_outcome_v2
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_path_metric_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_path_metric_v2
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();
CREATE TRIGGER tr_forward_dqv_quality_report_append_only
BEFORE UPDATE OR DELETE ON analytics.forward_dqv_quality_report_v2
FOR EACH ROW EXECUTE FUNCTION analytics.reject_forward_append_only_change();

CREATE INDEX ix_forward_dqv_enrollment_snapshot
    ON analytics.forward_dqv_enrollment_v2 (decision_data_snapshot_id, decision_as_of);
CREATE INDEX ix_forward_dqv_batch_enrollment
    ON analytics.forward_dqv_outcome_batch_v2 (
        enrollment_id, completed_sessions, result_version DESC
    );
CREATE INDEX ix_forward_dqv_security_public_id
    ON analytics.forward_dqv_security_outcome_v2 (
        public_security_id, outcome_batch_id
    );
CREATE INDEX ix_forward_dqv_security_record_hash
    ON analytics.forward_dqv_security_outcome_v2 (record_hash);
CREATE INDEX ix_forward_dqv_benchmark_record_hash
    ON analytics.forward_dqv_benchmark_outcome_v2 (record_hash);
CREATE INDEX ix_forward_dqv_metric_record_hash
    ON analytics.forward_dqv_path_metric_v2 (metric_record_hash);
CREATE INDEX ix_forward_dqv_report_enrollment
    ON analytics.forward_dqv_quality_report_v2 (
        enrollment_id, completed_sessions, model_track, result_version DESC
    );
