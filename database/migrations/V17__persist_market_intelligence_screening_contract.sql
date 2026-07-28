CREATE TABLE analytics.security_profile_snapshot (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_version VARCHAR(128) NOT NULL,
    security_id BIGINT NOT NULL REFERENCES analytics.security (id),
    data_snapshot_id UUID REFERENCES analytics.data_snapshot (id),
    snapshot_as_of TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    issuer_name VARCHAR(255) NOT NULL,
    exchange_mic CHAR(4) NOT NULL,
    currency CHAR(3) NOT NULL,
    instrument_type VARCHAR(32) NOT NULL,
    cik VARCHAR(32),
    durable_provider_id VARCHAR(255),
    taxonomy_code VARCHAR(64),
    taxonomy_version VARCHAR(64),
    sector_code VARCHAR(64),
    sector_name VARCHAR(255),
    industry_code VARCHAR(64),
    industry_name VARCHAR(255),
    company_type VARCHAR(64),
    classification_effective_at TIMESTAMPTZ,
    classification_source_record_id UUID
        REFERENCES analytics.source_record (id),
    profile_state VARCHAR(16) NOT NULL,
    ranking_state VARCHAR(16) NOT NULL,
    objective_rating_status VARCHAR(32) NOT NULL,
    objective_rating_version VARCHAR(128) NOT NULL,
    objective_quality_score NUMERIC(9, 4),
    objective_valuation_score NUMERIC(9, 4),
    explainability JSONB NOT NULL,
    input_payload_hash VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_security_profile_snapshot
        UNIQUE (
            security_id, snapshot_as_of, contract_version, input_payload_hash
        ),
    FOREIGN KEY (taxonomy_code, taxonomy_version, sector_code)
        REFERENCES analytics.classification_node (
            taxonomy_code, taxonomy_version, node_code
        ),
    FOREIGN KEY (taxonomy_code, taxonomy_version, industry_code)
        REFERENCES analytics.classification_node (
            taxonomy_code, taxonomy_version, node_code
        ),
    CONSTRAINT ck_security_profile_state
        CHECK (profile_state IN ('COMPLETE', 'PARTIAL', 'INELIGIBLE')),
    CONSTRAINT ck_security_profile_ranking_state
        CHECK (ranking_state IN ('ELIGIBLE', 'NOT_ELIGIBLE')),
    CONSTRAINT ck_security_profile_objective_scores CHECK (
        (objective_quality_score IS NULL OR objective_quality_score BETWEEN 0 AND 100)
        AND (objective_valuation_score IS NULL OR objective_valuation_score BETWEEN 0 AND 100)
        AND (
            objective_rating_status = 'SCORED'
            OR (
                objective_quality_score IS NULL
                AND objective_valuation_score IS NULL
            )
        )
    ),
    CONSTRAINT ck_security_profile_classification CHECK (
        (
            taxonomy_code IS NULL
            AND taxonomy_version IS NULL
            AND sector_code IS NULL
            AND sector_name IS NULL
            AND industry_code IS NULL
            AND industry_name IS NULL
            AND company_type IS NULL
            AND classification_effective_at IS NULL
            AND classification_source_record_id IS NULL
        )
        OR (
            taxonomy_code IS NOT NULL
            AND taxonomy_version IS NOT NULL
            AND sector_code IS NOT NULL
            AND sector_name IS NOT NULL
            AND industry_code IS NOT NULL
            AND industry_name IS NOT NULL
            AND company_type IS NOT NULL
            AND classification_effective_at IS NOT NULL
            AND classification_source_record_id IS NOT NULL
        )
    ),
    CONSTRAINT ck_security_profile_explainability
        CHECK (jsonb_typeof(explainability) = 'array')
);

CREATE INDEX ix_security_profile_security_as_of
    ON analytics.security_profile_snapshot (
        security_id, snapshot_as_of DESC, contract_version
    );
CREATE INDEX ix_security_profile_screening
    ON analytics.security_profile_snapshot (
        ranking_state, taxonomy_version, sector_code, industry_code,
        company_type, snapshot_as_of DESC
    );
CREATE INDEX ix_security_profile_data_snapshot
    ON analytics.security_profile_snapshot (data_snapshot_id)
    WHERE data_snapshot_id IS NOT NULL;

CREATE TABLE analytics.security_profile_classification_lineage (
    profile_id UUID NOT NULL REFERENCES analytics.security_profile_snapshot (id),
    lineage_ordinal INTEGER NOT NULL,
    source_record_id UUID NOT NULL REFERENCES analytics.source_record (id),
    effective_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (profile_id, lineage_ordinal),
    CONSTRAINT uq_security_profile_classification_source
        UNIQUE (profile_id, source_record_id),
    CONSTRAINT ck_profile_classification_lineage_ordinal
        CHECK (lineage_ordinal > 0),
    CONSTRAINT ck_profile_classification_lineage_times
        CHECK (
            available_at >= effective_at
            AND retrieved_at >= available_at
        )
);

CREATE TABLE analytics.security_profile_fact (
    profile_id UUID NOT NULL REFERENCES analytics.security_profile_snapshot (id),
    fact_name VARCHAR(128) NOT NULL,
    metric_observation_id BIGINT NOT NULL
        REFERENCES analytics.metric_observation (id),
    display_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile_id, fact_name),
    CONSTRAINT uq_security_profile_fact_observation
        UNIQUE (profile_id, metric_observation_id),
    CONSTRAINT ck_security_profile_fact_order CHECK (display_order >= 0)
);

CREATE INDEX ix_security_profile_fact_observation
    ON analytics.security_profile_fact (metric_observation_id);

CREATE TABLE analytics.security_profile_fact_lineage (
    profile_id UUID NOT NULL,
    fact_name VARCHAR(128) NOT NULL,
    lineage_ordinal INTEGER NOT NULL,
    source_record_id UUID NOT NULL REFERENCES analytics.source_record (id),
    effective_at TIMESTAMPTZ,
    available_at TIMESTAMPTZ NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (profile_id, fact_name, lineage_ordinal),
    FOREIGN KEY (profile_id, fact_name)
        REFERENCES analytics.security_profile_fact (profile_id, fact_name),
    CONSTRAINT uq_security_profile_fact_source
        UNIQUE (profile_id, fact_name, source_record_id),
    CONSTRAINT ck_profile_fact_lineage_ordinal CHECK (lineage_ordinal > 0),
    CONSTRAINT ck_profile_fact_lineage_times
        CHECK (
            (effective_at IS NULL OR available_at >= effective_at)
            AND retrieved_at >= available_at
        )
);

CREATE INDEX ix_security_profile_fact_lineage_source
    ON analytics.security_profile_fact_lineage (source_record_id);

CREATE TABLE analytics.comparable_cohort_snapshot (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES analytics.security_profile_snapshot (id),
    cohort_id VARCHAR(255) NOT NULL,
    taxonomy_version VARCHAR(64) NOT NULL,
    sector_code VARCHAR(64) NOT NULL,
    industry_code VARCHAR(64),
    company_type VARCHAR(64) NOT NULL,
    size_band VARCHAR(32),
    eligible_member_count INTEGER NOT NULL,
    minimum_member_count INTEGER NOT NULL,
    is_sufficient BOOLEAN GENERATED ALWAYS AS (
        eligible_member_count >= minimum_member_count
    ) STORED,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_comparable_cohort_snapshot
        UNIQUE (profile_id, cohort_id),
    CONSTRAINT ck_comparable_cohort_counts
        CHECK (eligible_member_count >= 0 AND minimum_member_count > 0)
);

CREATE INDEX ix_comparable_cohort_sufficiency
    ON analytics.comparable_cohort_snapshot (
        profile_id, is_sufficient, taxonomy_version, sector_code
    );

CREATE TABLE analytics.market_intelligence_horizon_view (
    profile_id UUID NOT NULL REFERENCES analytics.security_profile_snapshot (id),
    horizon VARCHAR(32) NOT NULL,
    model_id VARCHAR(128) NOT NULL,
    model_version VARCHAR(128) NOT NULL,
    view_state VARCHAR(32) NOT NULL,
    model_as_of TIMESTAMPTZ NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    score NUMERIC(9, 4),
    label VARCHAR(128) NOT NULL,
    input_hash VARCHAR(128) NOT NULL,
    evidence_hash VARCHAR(128) NOT NULL,
    missing_inputs JSONB NOT NULL,
    explanation JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (profile_id, horizon),
    CONSTRAINT ck_market_intelligence_horizon
        CHECK (horizon IN (
            'ONE_WEEK', 'ONE_MONTH', 'THREE_MONTHS', 'TWELVE_MONTHS_PLUS'
        )),
    CONSTRAINT ck_market_intelligence_view_state
        CHECK (view_state IN (
            'ASSESSED', 'INSUFFICIENT_DATA', 'NOT_APPLICABLE'
        )),
    CONSTRAINT ck_market_intelligence_view_score CHECK (
        (
            view_state = 'ASSESSED'
            AND score BETWEEN 0 AND 100
        )
        OR (
            view_state <> 'ASSESSED'
            AND score IS NULL
        )
    ),
    CONSTRAINT ck_market_intelligence_view_expiry
        CHECK (expires_at IS NULL OR expires_at >= effective_at),
    CONSTRAINT ck_market_intelligence_view_json
        CHECK (
            jsonb_typeof(missing_inputs) = 'array'
            AND jsonb_typeof(explanation) = 'array'
        )
);

CREATE INDEX ix_market_intelligence_horizon_screening
    ON analytics.market_intelligence_horizon_view (
        horizon, view_state, score DESC, effective_at, expires_at
    );

CREATE TABLE analytics.market_intelligence_valuation_evidence (
    profile_id UUID PRIMARY KEY REFERENCES analytics.security_profile_snapshot (id),
    evidence_state VARCHAR(32) NOT NULL,
    evidence_as_of TIMESTAMPTZ NOT NULL,
    objective_valuation_score NUMERIC(9, 4),
    long_horizon_valuation_score NUMERIC(9, 4),
    own_history_percentile NUMERIC(9, 4),
    limitations JSONB NOT NULL,
    evidence_hash VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_market_intelligence_valuation_state
        CHECK (evidence_state IN ('VALID', 'MISSING', 'INVALID', 'NOT_APPLICABLE')),
    CONSTRAINT ck_market_intelligence_valuation_values CHECK (
        (
            evidence_state = 'VALID'
            AND objective_valuation_score BETWEEN 0 AND 100
            AND long_horizon_valuation_score BETWEEN 0 AND 100
            AND own_history_percentile BETWEEN 0 AND 100
        )
        OR (
            evidence_state <> 'VALID'
            AND objective_valuation_score IS NULL
            AND long_horizon_valuation_score IS NULL
            AND own_history_percentile IS NULL
        )
    ),
    CONSTRAINT ck_market_intelligence_valuation_limitations
        CHECK (jsonb_typeof(limitations) = 'array')
);

CREATE TABLE analytics.market_intelligence_ranking_exclusion (
    profile_id UUID NOT NULL REFERENCES analytics.security_profile_snapshot (id),
    reason_ordinal INTEGER NOT NULL,
    reason_code VARCHAR(128) NOT NULL,
    exclusion_category VARCHAR(32) NOT NULL,
    PRIMARY KEY (profile_id, reason_ordinal),
    CONSTRAINT uq_market_intelligence_ranking_reason
        UNIQUE (profile_id, reason_code),
    CONSTRAINT ck_market_intelligence_reason_ordinal CHECK (reason_ordinal > 0),
    CONSTRAINT ck_market_intelligence_exclusion_category
        CHECK (exclusion_category IN (
            'CLASSIFICATION', 'FACT', 'STALE', 'COHORT',
            'FORMULA', 'MODEL', 'FILTER', 'RANKING'
        ))
);

CREATE INDEX ix_market_intelligence_exclusion_reason
    ON analytics.market_intelligence_ranking_exclusion (
        exclusion_category, reason_code, profile_id
    );

CREATE TABLE analytics.market_intelligence_screening_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_version VARCHAR(128) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    canonical_request_hash VARCHAR(128) NOT NULL,
    as_of_time TIMESTAMPTZ NOT NULL,
    data_snapshot_id UUID REFERENCES analytics.data_snapshot (id),
    filter_payload JSONB NOT NULL,
    rank_metric VARCHAR(64) NOT NULL,
    sort_direction VARCHAR(16) NOT NULL,
    result_limit INTEGER NOT NULL,
    methodology_reference VARCHAR(255) NOT NULL,
    input_snapshot_hash VARCHAR(128) NOT NULL,
    eligible_count INTEGER NOT NULL,
    excluded_count INTEGER NOT NULL,
    sector_coverage_count INTEGER NOT NULL,
    security_coverage_count INTEGER NOT NULL,
    fresh_profile_count INTEGER NOT NULL,
    explainable_count INTEGER NOT NULL,
    gate_status VARCHAR(32) NOT NULL,
    result_hash VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sealed_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_market_intelligence_rank_metric
        CHECK (rank_metric IN (
            'OBJECTIVE_QUALITY', 'OBJECTIVE_VALUATION',
            'TACTICAL_ONE_WEEK', 'TACTICAL_ONE_MONTH',
            'TACTICAL_THREE_MONTHS', 'LONG_HORIZON',
            'BUYING_OPPORTUNITY'
        )),
    CONSTRAINT ck_market_intelligence_sort_direction
        CHECK (sort_direction IN ('ASCENDING', 'DESCENDING')),
    CONSTRAINT ck_market_intelligence_result_limit
        CHECK (result_limit BETWEEN 1 AND 500),
    CONSTRAINT ck_market_intelligence_run_counts CHECK (
        eligible_count >= 0
        AND excluded_count >= 0
        AND sector_coverage_count >= 0
        AND security_coverage_count >= 0
        AND fresh_profile_count BETWEEN 0 AND security_coverage_count
        AND explainable_count BETWEEN 0 AND security_coverage_count
        AND eligible_count + excluded_count <= security_coverage_count
    ),
    CONSTRAINT ck_market_intelligence_gate_status
        CHECK (gate_status IN ('PASS', 'FAIL', 'NO_ELIGIBLE_RESULTS')),
    CONSTRAINT ck_market_intelligence_filter
        CHECK (jsonb_typeof(filter_payload) = 'object'),
    CONSTRAINT ck_market_intelligence_run_sealed
        CHECK (sealed_at >= created_at)
);

CREATE INDEX ix_market_intelligence_run_as_of
    ON analytics.market_intelligence_screening_run (
        as_of_time DESC, rank_metric, gate_status
    );
CREATE INDEX ix_market_intelligence_run_snapshot
    ON analytics.market_intelligence_screening_run (data_snapshot_id)
    WHERE data_snapshot_id IS NOT NULL;

CREATE TABLE analytics.market_intelligence_screening_result (
    run_id UUID NOT NULL REFERENCES analytics.market_intelligence_screening_run (id),
    profile_id UUID NOT NULL REFERENCES analytics.security_profile_snapshot (id),
    rank INTEGER NOT NULL,
    metric_value NUMERIC(30, 12) NOT NULL,
    sector_code VARCHAR(64) NOT NULL,
    industry_code VARCHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, profile_id),
    CONSTRAINT uq_market_intelligence_screening_rank UNIQUE (run_id, rank),
    CONSTRAINT ck_market_intelligence_screening_rank CHECK (rank > 0)
);

CREATE INDEX ix_market_intelligence_result_profile
    ON analytics.market_intelligence_screening_result (profile_id, run_id);

CREATE TABLE analytics.market_intelligence_ai_narrative (
    profile_id UUID PRIMARY KEY REFERENCES analytics.security_profile_snapshot (id),
    status VARCHAR(32) NOT NULL,
    narrative TEXT,
    source_references JSONB NOT NULL,
    generated_at TIMESTAMPTZ,
    prompt_version VARCHAR(128),
    model_version VARCHAR(128),
    confidence VARCHAR(32),
    narrative_hash VARCHAR(128),
    may_affect_deterministic_fields BOOLEAN NOT NULL DEFAULT FALSE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_market_intelligence_ai_status
        CHECK (status IN ('NOT_EXECUTED', 'AVAILABLE', 'FAILED', 'REJECTED')),
    CONSTRAINT ck_market_intelligence_ai_boundary
        CHECK (may_affect_deterministic_fields = FALSE),
    CONSTRAINT ck_market_intelligence_ai_sources
        CHECK (
            jsonb_typeof(source_references) = 'array'
            AND (
                narrative IS NULL
                OR jsonb_array_length(source_references) > 0
            )
        ),
    CONSTRAINT ck_market_intelligence_ai_generation CHECK (
        (
            status = 'AVAILABLE'
            AND narrative IS NOT NULL
            AND generated_at IS NOT NULL
            AND prompt_version IS NOT NULL
            AND model_version IS NOT NULL
            AND confidence IS NOT NULL
            AND narrative_hash IS NOT NULL
        )
        OR status <> 'AVAILABLE'
    )
);

CREATE TRIGGER tr_security_profile_snapshot_append_only
BEFORE UPDATE OR DELETE ON analytics.security_profile_snapshot
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();
CREATE TRIGGER tr_profile_classification_lineage_append_only
BEFORE UPDATE OR DELETE ON analytics.security_profile_classification_lineage
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();
CREATE TRIGGER tr_security_profile_fact_append_only
BEFORE UPDATE OR DELETE ON analytics.security_profile_fact
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();
CREATE TRIGGER tr_security_profile_fact_lineage_append_only
BEFORE UPDATE OR DELETE ON analytics.security_profile_fact_lineage
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();
CREATE TRIGGER tr_comparable_cohort_snapshot_append_only
BEFORE UPDATE OR DELETE ON analytics.comparable_cohort_snapshot
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();
CREATE TRIGGER tr_market_intelligence_horizon_append_only
BEFORE UPDATE OR DELETE ON analytics.market_intelligence_horizon_view
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();
CREATE TRIGGER tr_market_intelligence_valuation_append_only
BEFORE UPDATE OR DELETE ON analytics.market_intelligence_valuation_evidence
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();
CREATE TRIGGER tr_market_intelligence_exclusion_append_only
BEFORE UPDATE OR DELETE ON analytics.market_intelligence_ranking_exclusion
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();
CREATE TRIGGER tr_market_intelligence_run_append_only
BEFORE UPDATE OR DELETE ON analytics.market_intelligence_screening_run
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();
CREATE TRIGGER tr_market_intelligence_result_append_only
BEFORE UPDATE OR DELETE ON analytics.market_intelligence_screening_result
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();
CREATE TRIGGER tr_market_intelligence_ai_append_only
BEFORE UPDATE OR DELETE ON analytics.market_intelligence_ai_narrative
FOR EACH ROW EXECUTE FUNCTION analytics.reject_immutable_observation_change();

COMMENT ON TABLE analytics.security_profile_snapshot IS
    'Immutable assembled MARKET-INTELLIGENCE-SCREENING-v1 profile projection over existing PIT evidence.';
COMMENT ON TABLE analytics.security_profile_fact IS
    'Selects existing metric observations into a sealed profile without duplicating observed values.';
COMMENT ON TABLE analytics.market_intelligence_horizon_view IS
    'Immutable versioned deterministic horizon output; AI narratives cannot write this table.';
COMMENT ON TABLE analytics.market_intelligence_screening_run IS
    'Immutable profile-filtering and ranking result, distinct from Objective Rating calculation runs.';
COMMENT ON TABLE analytics.market_intelligence_ai_narrative IS
    'Optional cited AI narrative isolated from deterministic facts, eligibility, scores, and ranks.';
