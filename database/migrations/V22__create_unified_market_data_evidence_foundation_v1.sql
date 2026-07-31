CREATE TABLE analytics.evidence_company_identity_v1 (
    company_id UUID PRIMARY KEY,
    registry_version VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_evidence_company_registry_version
        CHECK (registry_version = 'security-identity-registry-v1.0.0')
);

CREATE TABLE analytics.evidence_instrument_identity_v1 (
    instrument_id UUID PRIMARY KEY,
    company_id UUID NOT NULL
        REFERENCES analytics.evidence_company_identity_v1 (company_id),
    registry_version VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_evidence_instrument_registry_version
        CHECK (registry_version = 'security-identity-registry-v1.0.0')
);

CREATE TABLE analytics.evidence_share_class_identity_v1 (
    share_class_id UUID PRIMARY KEY,
    instrument_id UUID NOT NULL
        REFERENCES analytics.evidence_instrument_identity_v1 (instrument_id),
    registry_version VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_evidence_share_class_registry_version
        CHECK (registry_version = 'security-identity-registry-v1.0.0')
);

CREATE TABLE analytics.evidence_listing_identity_v1 (
    listing_id UUID PRIMARY KEY,
    share_class_id UUID NOT NULL
        REFERENCES analytics.evidence_share_class_identity_v1 (share_class_id),
    security_id UUID NOT NULL UNIQUE
        REFERENCES analytics.security (public_id),
    mic CHAR(4) NOT NULL,
    currency CHAR(3) NOT NULL,
    registry_version VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_evidence_listing_registry_version
        CHECK (registry_version = 'security-identity-registry-v1.0.0'),
    CONSTRAINT ck_evidence_listing_mic CHECK (mic ~ '^[A-Z0-9]{4}$'),
    CONSTRAINT ck_evidence_listing_currency CHECK (currency ~ '^[A-Z]{3}$')
);

CREATE TABLE analytics.evidence_ticker_assignment_v1 (
    ticker_assignment_id UUID PRIMARY KEY,
    listing_id UUID NOT NULL
        REFERENCES analytics.evidence_listing_identity_v1 (listing_id),
    ticker VARCHAR(32) NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE,
    registry_version VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (listing_id, ticker, valid_from),
    CONSTRAINT ck_evidence_ticker_range
        CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ck_evidence_ticker_registry_version
        CHECK (registry_version = 'security-identity-registry-v1.0.0')
);

CREATE UNIQUE INDEX uq_evidence_ticker_current_v1
    ON analytics.evidence_ticker_assignment_v1 (listing_id)
    WHERE valid_to IS NULL;

CREATE TABLE analytics.evidence_trading_calendar_v1 (
    calendar_id VARCHAR(64) NOT NULL,
    calendar_version VARCHAR(128) NOT NULL,
    mic CHAR(4) NOT NULL,
    timezone VARCHAR(64) NOT NULL,
    calendar_content_hash VARCHAR(71) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (calendar_id, calendar_version),
    UNIQUE (calendar_id, calendar_version, mic, timezone),
    CONSTRAINT ck_evidence_calendar_hash CHECK (
        calendar_content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_evidence_calendar_mic CHECK (mic ~ '^[A-Z0-9]{4}$')
);

CREATE TABLE analytics.evidence_completed_session_v1 (
    id UUID PRIMARY KEY,
    calendar_id VARCHAR(64) NOT NULL,
    calendar_version VARCHAR(128) NOT NULL,
    mic CHAR(4) NOT NULL,
    session_date DATE NOT NULL,
    timezone VARCHAR(64) NOT NULL,
    scheduled_open TIMESTAMPTZ NOT NULL,
    scheduled_close TIMESTAMPTZ NOT NULL,
    early_close BOOLEAN NOT NULL,
    status VARCHAR(32) NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    session_content_hash VARCHAR(71) NOT NULL UNIQUE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (calendar_id, calendar_version)
        REFERENCES analytics.evidence_trading_calendar_v1 (
            calendar_id, calendar_version
        ),
    FOREIGN KEY (calendar_id, calendar_version, mic, timezone)
        REFERENCES analytics.evidence_trading_calendar_v1 (
            calendar_id, calendar_version, mic, timezone
        ),
    UNIQUE (calendar_id, calendar_version, session_date),
    CONSTRAINT ck_evidence_completed_session_status
        CHECK (status = 'COMPLETED'),
    CONSTRAINT ck_evidence_completed_session_chronology CHECK (
        scheduled_open < scheduled_close
        AND scheduled_close <= completed_at
    ),
    CONSTRAINT ck_evidence_completed_session_hash CHECK (
        session_content_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE TABLE analytics.evidence_provider_contract_v1 (
    provider_code VARCHAR(128) PRIMARY KEY,
    provider_contract_version VARCHAR(128) NOT NULL,
    licensing_classification VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_evidence_provider_status
        CHECK (status IN ('ACTIVE', 'RESTRICTED', 'RETIRED')),
    CONSTRAINT ck_evidence_provider_licensing CHECK (
        licensing_classification IN (
            'PRIVATE_LICENSED', 'PUBLIC_PERMITTED', 'INTERNAL_DERIVED'
        )
    )
);

CREATE TABLE analytics.evidence_raw_manifest_v1 (
    id UUID PRIMARY KEY,
    provider_code VARCHAR(128) NOT NULL
        REFERENCES analytics.evidence_provider_contract_v1 (provider_code),
    provider_schema_version VARCHAR(128) NOT NULL,
    source_record_id VARCHAR(255) NOT NULL,
    source_revision INTEGER NOT NULL,
    source_content_hash VARCHAR(71) NOT NULL,
    storage_class VARCHAR(64) NOT NULL,
    payload_stored_in_git BOOLEAN NOT NULL,
    storage_reference VARCHAR(2048) NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    retrieved_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (
        provider_code, source_record_id, source_revision, source_content_hash
    ),
    CONSTRAINT ck_evidence_raw_revision CHECK (source_revision > 0),
    CONSTRAINT ck_evidence_raw_hash CHECK (
        source_content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_evidence_raw_private_storage CHECK (
        storage_class = 'PRIVATE_GIT_IGNORED'
        AND payload_stored_in_git = FALSE
    ),
    CONSTRAINT ck_evidence_raw_chronology CHECK (
        effective_at <= available_at
        AND available_at <= ingested_at
        AND (
            retrieved_at IS NULL
            OR (
                available_at <= retrieved_at
                AND retrieved_at <= ingested_at
            )
        )
    )
);

CREATE FUNCTION analytics.evidence_json_nonblank_string_array_v1(value JSONB)
RETURNS BOOLEAN
LANGUAGE SQL
IMMUTABLE
AS $$
SELECT CASE
    WHEN jsonb_typeof(value) <> 'array' THEN FALSE
    ELSE NOT EXISTS (
        SELECT 1
        FROM jsonb_array_elements(value) element
        WHERE jsonb_typeof(element) <> 'string'
           OR btrim(element #>> '{}') = ''
    )
END;
$$;

CREATE TABLE analytics.canonical_evidence_v1 (
    evidence_id UUID PRIMARY KEY,
    contract_version VARCHAR(128) NOT NULL,
    domain VARCHAR(32) NOT NULL,
    layer VARCHAR(32) NOT NULL,
    state VARCHAR(32) NOT NULL,
    reason_code VARCHAR(128),
    security_id UUID NOT NULL,
    company_id UUID NOT NULL,
    instrument_id UUID NOT NULL,
    share_class_id UUID NOT NULL,
    listing_id UUID NOT NULL,
    ticker_assignment_id UUID NOT NULL,
    ticker VARCHAR(32) NOT NULL,
    mic CHAR(4) NOT NULL,
    currency CHAR(3) NOT NULL,
    provider_code VARCHAR(128) NOT NULL
        REFERENCES analytics.evidence_provider_contract_v1 (provider_code),
    provider_schema_version VARCHAR(128) NOT NULL,
    adapter_version VARCHAR(128) NOT NULL,
    normalization_version VARCHAR(128) NOT NULL,
    source_record_id VARCHAR(255) NOT NULL,
    source_revision INTEGER NOT NULL,
    source_content_hash VARCHAR(71) NOT NULL,
    normalized_record_hash VARCHAR(71) NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    retrieved_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ NOT NULL,
    freshness_policy_version VARCHAR(128) NOT NULL,
    stale_after TIMESTAMPTZ,
    strictness_class VARCHAR(64) NOT NULL,
    claim_class VARCHAR(64) NOT NULL,
    conflict_status VARCHAR(64) NOT NULL,
    conflict_criticality VARCHAR(32) NOT NULL,
    affected_factors JSONB NOT NULL,
    tolerance_policy_version VARCHAR(128),
    tolerance_field_code VARCHAR(128),
    tolerance_alignment JSONB,
    observation_reference VARCHAR(2048) NOT NULL,
    raw_manifest_id UUID
        REFERENCES analytics.evidence_raw_manifest_v1 (id),
    derivation_version VARCHAR(128),
    derivation_output_hash VARCHAR(71),
    canonical_data JSONB,
    supersedes_evidence_id UUID UNIQUE
        REFERENCES analytics.canonical_evidence_v1 (evidence_id),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (
        provider_code, source_record_id, source_revision,
        normalized_record_hash, domain, listing_id
    ),
    CONSTRAINT ck_canonical_evidence_contract CHECK (
        contract_version =
            'unified-market-data-evidence-foundation-v1.0.0'
    ),
    CONSTRAINT ck_canonical_evidence_domain CHECK (
        domain IN (
            'DAILY_PRICE', 'CORPORATE_ACTION', 'FUNDAMENTAL',
            'CLASSIFICATION', 'MARKET_BENCHMARK',
            'SECTOR_BENCHMARK', 'LIQUIDITY'
        )
    ),
    CONSTRAINT ck_canonical_evidence_layer CHECK (
        layer IN ('NORMALIZED_OBSERVATION', 'ENGINE_DERIVED')
        AND (
            (domain = 'LIQUIDITY' AND layer = 'ENGINE_DERIVED')
            OR (domain <> 'LIQUIDITY' AND layer = 'NORMALIZED_OBSERVATION')
        )
    ),
    CONSTRAINT ck_canonical_evidence_state CHECK (
        state IN (
            'VALID', 'MISSING', 'STALE', 'INVALID',
            'NOT_APPLICABLE', 'EXCLUDED'
        )
        AND (
            (state = 'VALID' AND reason_code IS NULL AND canonical_data IS NOT NULL)
            OR (
                state <> 'VALID'
                AND reason_code IS NOT NULL
                AND btrim(reason_code) <> ''
                AND canonical_data IS NULL
            )
        )
    ),
    CONSTRAINT ck_canonical_evidence_revision CHECK (source_revision > 0),
    CONSTRAINT ck_canonical_evidence_hashes CHECK (
        source_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND normalized_record_hash ~ '^sha256:[0-9a-f]{64}$'
        AND (
            derivation_output_hash IS NULL
            OR derivation_output_hash ~ '^sha256:[0-9a-f]{64}$'
        )
    ),
    CONSTRAINT ck_canonical_evidence_chronology CHECK (
        effective_at <= available_at
        AND available_at <= ingested_at
        AND (
            retrieved_at IS NULL
            OR (
                available_at <= retrieved_at
                AND retrieved_at <= ingested_at
            )
        )
    ),
    CONSTRAINT ck_canonical_evidence_strictness CHECK (
        strictness_class IN (
            'STRICT_IDENTITY_AND_CHRONOLOGY',
            'DOMAIN_TOLERANT_NUMERIC',
            'APPROXIMATE_HISTORICAL_RESEARCH'
        )
    ),
    CONSTRAINT ck_canonical_evidence_claim CHECK (
        claim_class IN (
            'CURRENT_ONLY', 'APPROXIMATE_HISTORICAL',
            'STRICT_PIT', 'SEALED_PROSPECTIVE'
        )
        AND NOT (
            strictness_class = 'APPROXIMATE_HISTORICAL_RESEARCH'
            AND claim_class IN ('STRICT_PIT', 'SEALED_PROSPECTIVE')
        )
    ),
    CONSTRAINT ck_canonical_evidence_affected_factors CHECK (
        analytics.evidence_json_nonblank_string_array_v1(affected_factors)
    ),
    CONSTRAINT ck_canonical_evidence_conflict CHECK (
        conflict_status IN (
            'NONE', 'RESOLVED_WITHIN_TOLERANCE', 'UNRESOLVED'
        )
        AND conflict_criticality IN ('NONE', 'NONCRITICAL', 'CRITICAL')
        AND (
            (
                conflict_status = 'NONE'
                AND conflict_criticality = 'NONE'
                AND affected_factors = '[]'::jsonb
            )
            OR (
                conflict_status = 'RESOLVED_WITHIN_TOLERANCE'
                AND conflict_criticality = 'NONCRITICAL'
                AND strictness_class = 'DOMAIN_TOLERANT_NUMERIC'
            )
            OR (
                conflict_status = 'UNRESOLVED'
                AND conflict_criticality IN ('NONCRITICAL', 'CRITICAL')
            )
        )
    ),
    CONSTRAINT ck_canonical_evidence_tolerance CHECK (
        (
            strictness_class = 'DOMAIN_TOLERANT_NUMERIC'
            AND tolerance_policy_version IS NOT NULL
            AND btrim(tolerance_policy_version) <> ''
            AND tolerance_field_code IS NOT NULL
            AND btrim(tolerance_field_code) <> ''
            AND tolerance_alignment = '{
                "semantic": true,
                "identity": true,
                "period": true,
                "unit": true,
                "currency": true,
                "adjustment": true,
                "chronology": true
            }'::jsonb
        )
        OR (
            strictness_class <> 'DOMAIN_TOLERANT_NUMERIC'
            AND tolerance_policy_version IS NULL
            AND tolerance_field_code IS NULL
            AND tolerance_alignment IS NULL
        )
    ),
    CONSTRAINT ck_canonical_evidence_layer_binding CHECK (
        (
            layer = 'NORMALIZED_OBSERVATION'
            AND raw_manifest_id IS NOT NULL
            AND derivation_version IS NULL
            AND derivation_output_hash IS NULL
        )
        OR (
            layer = 'ENGINE_DERIVED'
            AND raw_manifest_id IS NULL
            AND derivation_version IS NOT NULL
            AND btrim(derivation_version) <> ''
            AND derivation_output_hash = normalized_record_hash
        )
    ),
    CONSTRAINT ck_canonical_evidence_not_self_superseding CHECK (
        supersedes_evidence_id IS NULL
        OR supersedes_evidence_id <> evidence_id
    )
);

CREATE TABLE analytics.canonical_evidence_parent_v1 (
    evidence_id UUID NOT NULL
        REFERENCES analytics.canonical_evidence_v1 (evidence_id),
    parent_ordinal INTEGER NOT NULL,
    parent_evidence_id UUID NOT NULL
        REFERENCES analytics.canonical_evidence_v1 (evidence_id),
    parent_evidence_hash VARCHAR(71) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (evidence_id, parent_ordinal),
    UNIQUE (evidence_id, parent_evidence_hash),
    UNIQUE (evidence_id, parent_evidence_id),
    CONSTRAINT ck_canonical_evidence_parent_ordinal
        CHECK (parent_ordinal > 0),
    CONSTRAINT ck_canonical_evidence_parent_hash CHECK (
        parent_evidence_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_canonical_evidence_parent_not_self
        CHECK (evidence_id <> parent_evidence_id)
);

CREATE TABLE analytics.canonical_evidence_parent_seal_v1 (
    evidence_id UUID PRIMARY KEY
        REFERENCES analytics.canonical_evidence_v1 (evidence_id),
    parent_count INTEGER NOT NULL,
    sealed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_canonical_evidence_parent_seal_count
        CHECK (parent_count > 0)
);

CREATE TABLE analytics.evidence_selector_policy_v1 (
    id UUID PRIMARY KEY,
    selector_version VARCHAR(128) NOT NULL,
    policy_version VARCHAR(128) NOT NULL UNIQUE,
    domain VARCHAR(32) NOT NULL,
    field_code VARCHAR(128) NOT NULL,
    required_layer VARCHAR(32) NOT NULL,
    domain_constraints JSONB NOT NULL,
    required_strictness_class VARCHAR(64) NOT NULL,
    required_claim_class VARCHAR(64) NOT NULL,
    required_normalization_version VARCHAR(128) NOT NULL,
    policy_content_hash VARCHAR(71) NOT NULL UNIQUE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_evidence_selector_version CHECK (
        selector_version = 'deterministic-evidence-selector-v1.0.0'
    ),
    CONSTRAINT ck_evidence_selector_policy_domain CHECK (
        domain IN (
            'DAILY_PRICE', 'CORPORATE_ACTION', 'FUNDAMENTAL',
            'CLASSIFICATION', 'MARKET_BENCHMARK',
            'SECTOR_BENCHMARK', 'LIQUIDITY'
        )
    ),
    CONSTRAINT ck_evidence_selector_policy_layer CHECK (
        required_layer IN ('NORMALIZED_OBSERVATION', 'ENGINE_DERIVED')
    ),
    CONSTRAINT ck_evidence_selector_policy_field CHECK (
        (
            domain = 'DAILY_PRICE'
            AND field_code IN (
                'OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE',
                'CLOSE_PRICE', 'ADJUSTED_CLOSE', 'VOLUME'
            )
            AND required_layer = 'NORMALIZED_OBSERVATION'
        )
        OR (
            domain = 'CORPORATE_ACTION'
            AND field_code = 'CORPORATE_ACTION'
            AND required_layer = 'NORMALIZED_OBSERVATION'
        )
        OR (
            domain = 'FUNDAMENTAL'
            AND field_code IN (
                'REVENUE', 'OPERATING_INCOME', 'NET_INCOME',
                'TOTAL_ASSETS', 'TOTAL_EQUITY', 'OPERATING_CASH_FLOW',
                'CAPITAL_EXPENDITURE', 'FREE_CASH_FLOW',
                'DILUTED_SHARES', 'CURRENT_ASSETS',
                'CURRENT_LIABILITIES', 'CASH_AND_EQUIVALENTS',
                'TOTAL_DEBT', 'INTEREST_EXPENSE'
            )
            AND required_layer = 'NORMALIZED_OBSERVATION'
        )
        OR (
            domain = 'CLASSIFICATION'
            AND field_code IN (
                'SECTOR_CODE', 'INDUSTRY_CODE', 'COMPANY_TYPE'
            )
            AND required_layer = 'NORMALIZED_OBSERVATION'
        )
        OR (
            domain IN ('MARKET_BENCHMARK', 'SECTOR_BENCHMARK')
            AND field_code = 'BENCHMARK_MAPPING'
            AND required_layer = 'NORMALIZED_OBSERVATION'
        )
        OR (
            domain = 'LIQUIDITY'
            AND field_code IN (
                'AVERAGE_DAILY_DOLLAR_VOLUME',
                'AVERAGE_DAILY_SHARE_VOLUME'
            )
            AND required_layer = 'ENGINE_DERIVED'
        )
    ),
    CONSTRAINT ck_evidence_selector_policy_strictness CHECK (
        required_strictness_class IN (
            'STRICT_IDENTITY_AND_CHRONOLOGY',
            'DOMAIN_TOLERANT_NUMERIC',
            'APPROXIMATE_HISTORICAL_RESEARCH'
        )
    ),
    CONSTRAINT ck_evidence_selector_policy_claim CHECK (
        required_claim_class IN (
            'CURRENT_ONLY', 'APPROXIMATE_HISTORICAL',
            'STRICT_PIT', 'SEALED_PROSPECTIVE'
        )
    ),
    CONSTRAINT ck_evidence_selector_policy_constraints CHECK (
        jsonb_typeof(domain_constraints) = 'object'
        AND NOT domain_constraints ?| ARRAY[
            'deterministicScore', 'providerScore', 'score',
            'rank', 'recommendation'
        ]
    ),
    CONSTRAINT ck_evidence_selector_policy_hash CHECK (
        policy_content_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE TABLE analytics.evidence_selector_provider_priority_v1 (
    policy_id UUID NOT NULL
        REFERENCES analytics.evidence_selector_policy_v1 (id),
    priority_ordinal INTEGER NOT NULL,
    provider_code VARCHAR(128) NOT NULL
        REFERENCES analytics.evidence_provider_contract_v1 (provider_code),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (policy_id, priority_ordinal),
    UNIQUE (policy_id, provider_code),
    CONSTRAINT ck_evidence_selector_priority_ordinal
        CHECK (priority_ordinal > 0)
);

CREATE TABLE analytics.evidence_selector_policy_seal_v1 (
    policy_id UUID PRIMARY KEY
        REFERENCES analytics.evidence_selector_policy_v1 (id),
    provider_priority_count INTEGER NOT NULL,
    sealed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_evidence_selector_policy_seal_count
        CHECK (provider_priority_count > 0)
);

CREATE TABLE analytics.evidence_selection_request_v1 (
    request_id UUID PRIMARY KEY,
    contract_version VARCHAR(128) NOT NULL,
    policy_id UUID NOT NULL
        REFERENCES analytics.evidence_selector_policy_v1 (id),
    security_id UUID NOT NULL,
    company_id UUID NOT NULL,
    instrument_id UUID NOT NULL,
    share_class_id UUID NOT NULL,
    listing_id UUID NOT NULL,
    ticker_assignment_id UUID NOT NULL,
    completed_session_id UUID NOT NULL
        REFERENCES analytics.evidence_completed_session_v1 (id),
    decision_cutoff TIMESTAMPTZ NOT NULL,
    sealed_ingestion_cutoff TIMESTAMPTZ NOT NULL,
    request_content_hash VARCHAR(71) NOT NULL UNIQUE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_evidence_selection_request_contract CHECK (
        contract_version =
            'unified-market-data-evidence-foundation-v1.0.0'
    ),
    CONSTRAINT ck_evidence_selection_request_cutoffs CHECK (
        decision_cutoff <= sealed_ingestion_cutoff
    ),
    CONSTRAINT ck_evidence_selection_request_hash CHECK (
        request_content_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE TABLE analytics.evidence_selection_candidate_v1 (
    request_id UUID NOT NULL
        REFERENCES analytics.evidence_selection_request_v1 (request_id),
    candidate_ordinal INTEGER NOT NULL,
    evidence_id UUID NOT NULL
        REFERENCES analytics.canonical_evidence_v1 (evidence_id),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (request_id, candidate_ordinal),
    UNIQUE (request_id, evidence_id),
    CONSTRAINT ck_evidence_selection_candidate_ordinal
        CHECK (candidate_ordinal > 0)
);

CREATE TABLE analytics.evidence_selection_result_v1 (
    request_id UUID PRIMARY KEY
        REFERENCES analytics.evidence_selection_request_v1 (request_id),
    selector_version VARCHAR(128) NOT NULL,
    state VARCHAR(32) NOT NULL,
    reason_code VARCHAR(128) NOT NULL,
    selected_evidence_id UUID,
    result_content_hash VARCHAR(71) NOT NULL UNIQUE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (request_id, selected_evidence_id)
        REFERENCES analytics.evidence_selection_candidate_v1 (
            request_id, evidence_id
        ),
    CONSTRAINT ck_evidence_selection_result_version CHECK (
        selector_version = 'deterministic-evidence-selector-v1.0.0'
    ),
    CONSTRAINT ck_evidence_selection_result_reason
        CHECK (btrim(reason_code) <> ''),
    CONSTRAINT ck_evidence_selection_result_state CHECK (
        state IN (
            'VALID', 'MISSING', 'STALE', 'INVALID',
            'NOT_APPLICABLE', 'EXCLUDED'
        )
        AND (
            (state = 'VALID' AND selected_evidence_id IS NOT NULL)
            OR (state <> 'VALID' AND selected_evidence_id IS NULL)
        )
    ),
    CONSTRAINT ck_evidence_selection_result_hash CHECK (
        result_content_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE TABLE analytics.evidence_selection_rejection_v1 (
    request_id UUID NOT NULL
        REFERENCES analytics.evidence_selection_result_v1 (request_id),
    rejection_ordinal INTEGER NOT NULL,
    evidence_id UUID NOT NULL
        REFERENCES analytics.canonical_evidence_v1 (evidence_id),
    reason_code VARCHAR(128) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (request_id, rejection_ordinal),
    UNIQUE (request_id, evidence_id),
    CONSTRAINT ck_evidence_selection_rejection_ordinal
        CHECK (rejection_ordinal > 0),
    CONSTRAINT ck_evidence_selection_rejection_reason
        CHECK (btrim(reason_code) <> '')
);

CREATE TABLE analytics.evidence_selection_seal_v1 (
    request_id UUID PRIMARY KEY
        REFERENCES analytics.evidence_selection_result_v1 (request_id),
    candidate_count INTEGER NOT NULL,
    rejection_count INTEGER NOT NULL,
    sealed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_evidence_selection_seal_counts CHECK (
        candidate_count >= 0
        AND rejection_count >= 0
        AND rejection_count <= candidate_count
    )
);

CREATE TABLE analytics.model_applicability_routing_v1 (
    routing_id UUID PRIMARY KEY,
    company_id UUID NOT NULL
        REFERENCES analytics.evidence_company_identity_v1 (company_id),
    classification_evidence_id UUID NOT NULL
        REFERENCES analytics.canonical_evidence_v1 (evidence_id),
    model_family VARCHAR(64) NOT NULL,
    company_type VARCHAR(64) NOT NULL,
    applicability VARCHAR(64) NOT NULL,
    specialized_model_code VARCHAR(128),
    routing_version VARCHAR(128) NOT NULL,
    routing_revision INTEGER NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    routing_content_hash VARCHAR(71) NOT NULL UNIQUE,
    supersedes_routing_id UUID UNIQUE
        REFERENCES analytics.model_applicability_routing_v1 (routing_id),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_model_applicability_family
        CHECK (model_family = 'FUNDAMENTAL_VALUE'),
    CONSTRAINT ck_model_applicability_state CHECK (
        applicability IN (
            'APPLICABLE', 'SPECIALIZED_MODEL_REQUIRED',
            'NOT_APPLICABLE', 'INSUFFICIENT_EVIDENCE'
        )
        AND (
            (
                applicability = 'SPECIALIZED_MODEL_REQUIRED'
                AND specialized_model_code IS NOT NULL
                AND btrim(specialized_model_code) <> ''
            )
            OR (
                applicability <> 'SPECIALIZED_MODEL_REQUIRED'
                AND specialized_model_code IS NULL
            )
        )
    ),
    CONSTRAINT ck_model_applicability_hash CHECK (
        routing_content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_model_applicability_version CHECK (
        btrim(routing_version) <> ''
    ),
    CONSTRAINT ck_model_applicability_revision CHECK (
        routing_revision > 0
    ),
    CONSTRAINT ck_model_applicability_not_self_superseding CHECK (
        supersedes_routing_id IS NULL
        OR supersedes_routing_id <> routing_id
    )
);

CREATE FUNCTION analytics.reject_evidence_foundation_v1_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

CREATE FUNCTION analytics.evidence_json_has_decision_leakage_v1(payload JSONB)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    entry RECORD;
BEGIN
    IF payload IS NULL THEN
        RETURN FALSE;
    ELSIF jsonb_typeof(payload) = 'object' THEN
        FOR entry IN SELECT key, value FROM jsonb_each(payload)
        LOOP
            IF regexp_replace(lower(entry.key), '[_-]', '', 'g') IN (
                'score', 'deterministicscore', 'providerscore',
                'rank', 'ranking', 'providerrank', 'providerranking',
                'recommendation', 'providerrecommendation',
                'providernativevalue'
            ) OR analytics.evidence_json_has_decision_leakage_v1(
                entry.value
            ) THEN
                RETURN TRUE;
            END IF;
        END LOOP;
    ELSIF jsonb_typeof(payload) = 'array' THEN
        FOR entry IN SELECT value FROM jsonb_array_elements(payload)
        LOOP
            IF analytics.evidence_json_has_decision_leakage_v1(
                entry.value
            ) THEN
                RETURN TRUE;
            END IF;
        END LOOP;
    END IF;
    RETURN FALSE;
END;
$$;

CREATE FUNCTION analytics.validate_evidence_ticker_assignment_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.listing_id::TEXT, 220022)
    );
    IF EXISTS (
        SELECT 1
        FROM analytics.evidence_ticker_assignment_v1 assignment
        WHERE assignment.listing_id = NEW.listing_id
          AND daterange(
                assignment.valid_from,
                COALESCE(assignment.valid_to, 'infinity'::DATE),
                '[)'
              ) && daterange(
                NEW.valid_from,
                COALESCE(NEW.valid_to, 'infinity'::DATE),
                '[)'
              )
    ) THEN
        RAISE EXCEPTION 'Ticker assignment validity overlaps an existing assignment';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_evidence_trading_calendar_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_timezone_names timezone_name
        WHERE timezone_name.name = NEW.timezone
    ) THEN
        RAISE EXCEPTION 'Trading calendar timezone is not an IANA timezone';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_evidence_completed_session_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF (NEW.scheduled_open AT TIME ZONE NEW.timezone)::DATE
            <> NEW.session_date
       OR (NEW.scheduled_close AT TIME ZONE NEW.timezone)::DATE
            <> NEW.session_date THEN
        RAISE EXCEPTION
            'Completed-session date does not match its local trading date';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.evidence_json_decimal_string_v1(value JSONB)
RETURNS BOOLEAN
LANGUAGE SQL
IMMUTABLE
AS $$
SELECT jsonb_typeof(value) = 'string'
   AND (value #>> '{}') ~ '^-?(0|[1-9][0-9]*)(\.[0-9]+)?$';
$$;

CREATE FUNCTION analytics.evidence_json_iso_date_v1(value JSONB)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    date_text TEXT;
BEGIN
    IF jsonb_typeof(value) <> 'string' THEN
        RETURN FALSE;
    END IF;
    date_text := value #>> '{}';
    RETURN date_text ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
       AND to_char(date_text::DATE, 'YYYY-MM-DD') = date_text;
EXCEPTION
    WHEN invalid_datetime_format OR datetime_field_overflow THEN
        RETURN FALSE;
END;
$$;

CREATE FUNCTION analytics.evidence_json_rfc3339_instant_v1(value JSONB)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    instant_text TEXT;
BEGIN
    IF jsonb_typeof(value) <> 'string' THEN
        RETURN FALSE;
    END IF;
    instant_text := value #>> '{}';
    IF instant_text !~
        '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$' THEN
        RETURN FALSE;
    END IF;
    PERFORM instant_text::TIMESTAMPTZ;
    RETURN TRUE;
EXCEPTION
    WHEN invalid_datetime_format OR datetime_field_overflow THEN
        RETURN FALSE;
END;
$$;

CREATE FUNCTION analytics.validate_canonical_domain_data_v1(
    checked_domain VARCHAR,
    checked_layer VARCHAR,
    data JSONB,
    evidence_available_at TIMESTAMPTZ,
    evidence_ingested_at TIMESTAMPTZ
)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    period_start DATE;
    period_end DATE;
    effective_from DATE;
    effective_to DATE;
    filed_at TIMESTAMPTZ;
BEGIN
    IF jsonb_typeof(data) <> 'object' THEN
        RETURN FALSE;
    END IF;
    IF checked_domain = 'DAILY_PRICE' THEN
        RETURN checked_layer = 'NORMALIZED_OBSERVATION'
           AND analytics.evidence_json_iso_date_v1(data->'sessionDate')
           AND jsonb_typeof(data->'adjustmentMode') = 'string'
           AND data->>'adjustmentMode' IN (
                'UNADJUSTED', 'SPLIT_ADJUSTED', 'TOTAL_RETURN_ADJUSTED'
           )
           AND jsonb_typeof(data->'currency') = 'string'
           AND btrim(data->>'currency') <> ''
           AND analytics.evidence_json_decimal_string_v1(data->'open')
           AND analytics.evidence_json_decimal_string_v1(data->'high')
           AND analytics.evidence_json_decimal_string_v1(data->'low')
           AND analytics.evidence_json_decimal_string_v1(data->'close')
           AND (
                data->'adjustedClose' = 'null'::jsonb
                OR analytics.evidence_json_decimal_string_v1(
                    data->'adjustedClose'
                )
           )
           AND jsonb_typeof(data->'volume') = 'number'
           AND (data->>'volume') ~ '^[0-9]+$';
    ELSIF checked_domain = 'CORPORATE_ACTION' THEN
        IF checked_layer <> 'NORMALIZED_OBSERVATION'
           OR jsonb_typeof(data->'actionId') <> 'string'
           OR btrim(data->>'actionId') = ''
           OR jsonb_typeof(data->'actionType') <> 'string'
           OR data->>'actionType' NOT IN (
                'DIVIDEND', 'SPLIT', 'SYMBOL_CHANGE', 'LISTING',
                'DELISTING', 'SPIN_OFF'
           )
           OR NOT analytics.evidence_json_iso_date_v1(
                data->'effectiveDate'
           ) THEN
            RETURN FALSE;
        END IF;
        RETURN CASE data->>'actionType'
            WHEN 'DIVIDEND' THEN
                analytics.evidence_json_decimal_string_v1(data->'amount')
                AND jsonb_typeof(data->'currency') = 'string'
                AND btrim(data->>'currency') <> ''
            WHEN 'SPLIT' THEN
                analytics.evidence_json_decimal_string_v1(data->'splitFrom')
                AND analytics.evidence_json_decimal_string_v1(data->'splitTo')
                AND (data->>'splitFrom')::NUMERIC > 0
                AND (data->>'splitTo')::NUMERIC > 0
            WHEN 'SYMBOL_CHANGE' THEN
                jsonb_typeof(data->'newTicker') = 'string'
                AND btrim(data->>'newTicker') <> ''
            ELSE TRUE
        END;
    ELSIF checked_domain = 'FUNDAMENTAL' THEN
        IF checked_layer <> 'NORMALIZED_OBSERVATION'
           OR jsonb_typeof(data->'metricCode') <> 'string'
           OR btrim(data->>'metricCode') = ''
           OR NOT analytics.evidence_json_decimal_string_v1(
                data->'numericValue'
           )
           OR jsonb_typeof(data->'unit') <> 'string'
           OR btrim(data->>'unit') = ''
           OR NOT (
                data->'currency' = 'null'::jsonb
                OR (
                    jsonb_typeof(data->'currency') = 'string'
                    AND btrim(data->>'currency') <> ''
                )
           )
           OR NOT (
                data->'periodStart' = 'null'::jsonb
                OR jsonb_typeof(data->'periodStart') = 'string'
           )
           OR NOT analytics.evidence_json_iso_date_v1(data->'periodEnd')
           OR NOT analytics.evidence_json_rfc3339_instant_v1(data->'filedAt')
           OR jsonb_typeof(data->'fiscalPeriod') <> 'string'
           OR btrim(data->>'fiscalPeriod') = ''
           OR jsonb_typeof(data->'formType') <> 'string'
           OR btrim(data->>'formType') = ''
           OR jsonb_typeof(data->'accessionNumber') <> 'string'
           OR btrim(data->>'accessionNumber') = ''
           OR jsonb_typeof(data->'mappingVersion') <> 'string'
           OR btrim(data->>'mappingVersion') = '' THEN
            RETURN FALSE;
        END IF;
        period_start := CASE
            WHEN data->'periodStart' = 'null'::jsonb THEN NULL
            ELSE (data->>'periodStart')::DATE
        END;
        IF data->'periodStart' <> 'null'::jsonb
           AND NOT analytics.evidence_json_iso_date_v1(
                data->'periodStart'
           ) THEN
            RETURN FALSE;
        END IF;
        period_end := (data->>'periodEnd')::DATE;
        filed_at := (data->>'filedAt')::TIMESTAMPTZ;
        RETURN (period_start IS NULL OR period_start <= period_end)
           AND filed_at <= evidence_available_at
           AND filed_at <= evidence_ingested_at;
    ELSIF checked_domain = 'CLASSIFICATION' THEN
        RETURN checked_layer = 'NORMALIZED_OBSERVATION'
           AND jsonb_typeof(data->'taxonomyCode') = 'string'
           AND btrim(data->>'taxonomyCode') <> ''
           AND jsonb_typeof(data->'taxonomyVersion') = 'string'
           AND btrim(data->>'taxonomyVersion') <> ''
           AND jsonb_typeof(data->'sectorCode') = 'string'
           AND btrim(data->>'sectorCode') <> ''
           AND jsonb_typeof(data->'industryCode') = 'string'
           AND btrim(data->>'industryCode') <> ''
           AND jsonb_typeof(data->'companyType') = 'string'
           AND btrim(data->>'companyType') <> ''
           AND analytics.evidence_json_iso_date_v1(data->'effectiveFrom');
    ELSIF checked_domain IN (
        'MARKET_BENCHMARK', 'SECTOR_BENCHMARK'
    ) THEN
        IF checked_layer <> 'NORMALIZED_OBSERVATION'
           OR jsonb_typeof(data->'benchmarkKind') <> 'string'
           OR jsonb_typeof(data->'benchmarkCode') <> 'string'
           OR btrim(data->>'benchmarkCode') = ''
           OR jsonb_typeof(data->'benchmarkSecurityId') <> 'string'
           OR (data->>'benchmarkSecurityId')::UUID IS NULL
           OR jsonb_typeof(data->'mappingVersion') <> 'string'
           OR btrim(data->>'mappingVersion') = ''
           OR NOT analytics.evidence_json_iso_date_v1(data->'effectiveFrom')
           OR NOT (
                data->'effectiveTo' = 'null'::jsonb
                OR analytics.evidence_json_iso_date_v1(data->'effectiveTo')
           ) THEN
            RETURN FALSE;
        END IF;
        effective_from := (data->>'effectiveFrom')::DATE;
        effective_to := CASE
            WHEN data->'effectiveTo' = 'null'::jsonb THEN NULL
            ELSE (data->>'effectiveTo')::DATE
        END;
        RETURN (
                (
                    checked_domain = 'MARKET_BENCHMARK'
                    AND data->>'benchmarkKind' = 'MARKET'
                    AND data->'sectorCode' = 'null'::jsonb
                )
                OR (
                    checked_domain = 'SECTOR_BENCHMARK'
                    AND data->>'benchmarkKind' = 'SECTOR'
                    AND jsonb_typeof(data->'sectorCode') = 'string'
                    AND btrim(data->>'sectorCode') <> ''
                )
           )
           AND (effective_to IS NULL OR effective_from < effective_to);
    ELSIF checked_domain = 'LIQUIDITY' THEN
        RETURN checked_layer = 'ENGINE_DERIVED'
           AND jsonb_typeof(data->'windowCompletedSessions') = 'number'
           AND (data->>'windowCompletedSessions') ~ '^[1-9][0-9]*$'
           AND jsonb_typeof(data->'validObservationCount') = 'number'
           AND (data->>'validObservationCount') ~ '^[1-9][0-9]*$'
           AND (data->>'validObservationCount')::INTEGER
                <= (data->>'windowCompletedSessions')::INTEGER
           AND analytics.evidence_json_iso_date_v1(
                data->'windowEndSessionDate'
           )
           AND analytics.evidence_json_decimal_string_v1(
                data->'averageDailyDollarVolume'
           )
           AND analytics.evidence_json_decimal_string_v1(
                data->'averageDailyShareVolume'
           )
           AND jsonb_typeof(data->'currency') = 'string'
           AND btrim(data->>'currency') <> ''
           AND jsonb_typeof(data->'liquidityPolicyVersion') = 'string'
           AND btrim(data->>'liquidityPolicyVersion') <> '';
    END IF;
    RETURN FALSE;
EXCEPTION
    WHEN invalid_text_representation OR datetime_field_overflow
         OR numeric_value_out_of_range THEN
        RETURN FALSE;
END;
$$;

CREATE FUNCTION analytics.validate_selector_domain_constraints_v1(
    checked_domain VARCHAR,
    checked_field_code VARCHAR,
    data JSONB
)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    expected_keys TEXT[];
BEGIN
    expected_keys := CASE checked_domain
        WHEN 'DAILY_PRICE' THEN ARRAY[
            'sessionDate', 'adjustmentMode', 'currency', 'mic', 'listingId'
        ]
        WHEN 'CORPORATE_ACTION' THEN ARRAY['actionType', 'effectiveDate']
        WHEN 'FUNDAMENTAL' THEN ARRAY[
            'metricCode', 'periodEnd', 'unit', 'currency'
        ]
        WHEN 'CLASSIFICATION' THEN ARRAY['taxonomyVersion', 'effectiveOn']
        WHEN 'MARKET_BENCHMARK' THEN ARRAY[
            'benchmarkCode', 'effectiveOn', 'sectorCode'
        ]
        WHEN 'SECTOR_BENCHMARK' THEN ARRAY[
            'benchmarkCode', 'effectiveOn', 'sectorCode'
        ]
        WHEN 'LIQUIDITY' THEN ARRAY[
            'windowEndSessionDate', 'windowCompletedSessions', 'currency'
        ]
    END;
    IF jsonb_typeof(data) <> 'object'
       OR expected_keys IS NULL
       OR NOT data ?& expected_keys
       OR data - expected_keys <> '{}'::jsonb THEN
        RETURN FALSE;
    END IF;
    IF checked_domain = 'DAILY_PRICE' THEN
        RETURN analytics.evidence_json_iso_date_v1(data->'sessionDate')
           AND jsonb_typeof(data->'adjustmentMode') = 'string'
           AND data->>'adjustmentMode' IN (
                'UNADJUSTED', 'SPLIT_ADJUSTED', 'TOTAL_RETURN_ADJUSTED'
           )
           AND jsonb_typeof(data->'currency') = 'string'
           AND btrim(data->>'currency') <> ''
           AND jsonb_typeof(data->'mic') = 'string'
           AND btrim(data->>'mic') <> ''
           AND jsonb_typeof(data->'listingId') = 'string'
           AND (data->>'listingId')::UUID IS NOT NULL;
    ELSIF checked_domain = 'CORPORATE_ACTION' THEN
        RETURN jsonb_typeof(data->'actionType') = 'string'
           AND data->>'actionType' IN (
                'DIVIDEND', 'SPLIT', 'SYMBOL_CHANGE', 'LISTING',
                'DELISTING', 'SPIN_OFF'
           )
           AND analytics.evidence_json_iso_date_v1(data->'effectiveDate');
    ELSIF checked_domain = 'FUNDAMENTAL' THEN
        RETURN jsonb_typeof(data->'metricCode') = 'string'
           AND data->>'metricCode' = checked_field_code
           AND analytics.evidence_json_iso_date_v1(data->'periodEnd')
           AND jsonb_typeof(data->'unit') = 'string'
           AND btrim(data->>'unit') <> ''
           AND (
                data->'currency' = 'null'::jsonb
                OR (
                    jsonb_typeof(data->'currency') = 'string'
                    AND btrim(data->>'currency') <> ''
                )
           );
    ELSIF checked_domain = 'CLASSIFICATION' THEN
        RETURN jsonb_typeof(data->'taxonomyVersion') = 'string'
           AND btrim(data->>'taxonomyVersion') <> ''
           AND analytics.evidence_json_iso_date_v1(data->'effectiveOn');
    ELSIF checked_domain IN (
        'MARKET_BENCHMARK', 'SECTOR_BENCHMARK'
    ) THEN
        RETURN jsonb_typeof(data->'benchmarkCode') = 'string'
           AND btrim(data->>'benchmarkCode') <> ''
           AND analytics.evidence_json_iso_date_v1(data->'effectiveOn')
           AND (
                (
                    checked_domain = 'MARKET_BENCHMARK'
                    AND data->'sectorCode' = 'null'::jsonb
                )
                OR (
                    checked_domain = 'SECTOR_BENCHMARK'
                    AND jsonb_typeof(data->'sectorCode') = 'string'
                    AND btrim(data->>'sectorCode') <> ''
                )
           );
    ELSIF checked_domain = 'LIQUIDITY' THEN
        RETURN analytics.evidence_json_iso_date_v1(
                data->'windowEndSessionDate'
           )
           AND jsonb_typeof(data->'windowCompletedSessions') = 'number'
           AND (data->>'windowCompletedSessions') ~ '^[1-9][0-9]*$'
           AND jsonb_typeof(data->'currency') = 'string'
           AND btrim(data->>'currency') <> '';
    END IF;
    RETURN FALSE;
EXCEPTION
    WHEN invalid_text_representation OR datetime_field_overflow
         OR numeric_value_out_of_range THEN
        RETURN FALSE;
END;
$$;

CREATE FUNCTION analytics.validate_canonical_evidence_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    allowed_keys TEXT[];
    required_keys TEXT[];
    identity_matches BOOLEAN;
    raw_record analytics.evidence_raw_manifest_v1%ROWTYPE;
    predecessor analytics.canonical_evidence_v1%ROWTYPE;
    latest_stream_record analytics.canonical_evidence_v1%ROWTYPE;
    provider_record analytics.evidence_provider_contract_v1%ROWTYPE;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            concat_ws(
                '|',
                NEW.provider_code,
                NEW.source_record_id,
                NEW.domain,
                NEW.security_id::TEXT,
                NEW.listing_id::TEXT
            ),
            220026
        )
    );
    SELECT EXISTS (
        SELECT 1
        FROM analytics.evidence_company_identity_v1 company
        JOIN analytics.evidence_instrument_identity_v1 instrument
          ON instrument.company_id = company.company_id
        JOIN analytics.evidence_share_class_identity_v1 share_class
          ON share_class.instrument_id = instrument.instrument_id
        JOIN analytics.evidence_listing_identity_v1 listing
          ON listing.share_class_id = share_class.share_class_id
        JOIN analytics.evidence_ticker_assignment_v1 ticker
          ON ticker.listing_id = listing.listing_id
        WHERE company.company_id = NEW.company_id
          AND instrument.instrument_id = NEW.instrument_id
          AND share_class.share_class_id = NEW.share_class_id
          AND listing.listing_id = NEW.listing_id
          AND listing.security_id = NEW.security_id
          AND listing.mic = NEW.mic
          AND listing.currency = NEW.currency
          AND ticker.ticker_assignment_id = NEW.ticker_assignment_id
          AND ticker.ticker = NEW.ticker
          AND ticker.valid_from <= NEW.effective_at::DATE
          AND (
                ticker.valid_to IS NULL
                OR NEW.effective_at::DATE < ticker.valid_to
          )
    ) INTO identity_matches;

    IF NOT identity_matches THEN
        RAISE EXCEPTION 'Canonical evidence durable identity binding is invalid';
    END IF;

    SELECT * INTO provider_record
    FROM analytics.evidence_provider_contract_v1
    WHERE provider_code = NEW.provider_code;
    IF provider_record.provider_code IS NULL
       OR provider_record.status <> 'ACTIVE'
       OR (
            NEW.layer = 'NORMALIZED_OBSERVATION'
            AND provider_record.licensing_classification
                NOT IN ('PRIVATE_LICENSED', 'PUBLIC_PERMITTED')
       )
       OR (
            NEW.layer = 'ENGINE_DERIVED'
            AND provider_record.licensing_classification
                <> 'INTERNAL_DERIVED'
       ) THEN
        RAISE EXCEPTION 'Evidence provider ownership is invalid for its layer';
    END IF;

    IF NEW.layer = 'NORMALIZED_OBSERVATION' THEN
        SELECT * INTO raw_record
        FROM analytics.evidence_raw_manifest_v1
        WHERE id = NEW.raw_manifest_id;
        IF raw_record.id IS NULL
           OR raw_record.provider_code <> NEW.provider_code
           OR raw_record.provider_schema_version <> NEW.provider_schema_version
           OR raw_record.source_record_id <> NEW.source_record_id
           OR raw_record.source_revision <> NEW.source_revision
           OR raw_record.source_content_hash <> NEW.source_content_hash
           OR raw_record.effective_at <> NEW.effective_at
           OR raw_record.available_at <> NEW.available_at
           OR raw_record.retrieved_at IS DISTINCT FROM NEW.retrieved_at
           OR raw_record.ingested_at <> NEW.ingested_at THEN
            RAISE EXCEPTION 'Normalized evidence raw-manifest binding is invalid';
        END IF;
    END IF;

    SELECT * INTO latest_stream_record
    FROM analytics.canonical_evidence_v1 prior
    WHERE prior.provider_code = NEW.provider_code
      AND prior.source_record_id = NEW.source_record_id
      AND prior.domain = NEW.domain
      AND prior.security_id = NEW.security_id
      AND prior.listing_id = NEW.listing_id
    ORDER BY prior.source_revision DESC, prior.recorded_at DESC,
             prior.evidence_id
    LIMIT 1;

    IF latest_stream_record.evidence_id IS NOT NULL
       AND NEW.source_revision > latest_stream_record.source_revision
       AND NEW.supersedes_evidence_id
            IS DISTINCT FROM latest_stream_record.evidence_id THEN
        RAISE EXCEPTION
            'Later evidence revision requires the latest stream predecessor';
    ELSIF latest_stream_record.evidence_id IS NOT NULL
          AND NEW.source_revision < latest_stream_record.source_revision THEN
        RAISE EXCEPTION 'Evidence revision cannot backdate an existing stream';
    ELSIF (
        latest_stream_record.evidence_id IS NULL
        OR NEW.source_revision = latest_stream_record.source_revision
    ) AND NEW.supersedes_evidence_id IS NOT NULL THEN
        RAISE EXCEPTION
            'Evidence supersession is only valid for a later stream revision';
    END IF;

    IF NEW.supersedes_evidence_id IS NOT NULL THEN
        SELECT * INTO predecessor
        FROM analytics.canonical_evidence_v1
        WHERE evidence_id = NEW.supersedes_evidence_id;
        IF predecessor.evidence_id IS NULL
           OR predecessor.provider_code <> NEW.provider_code
           OR predecessor.source_record_id <> NEW.source_record_id
           OR predecessor.domain <> NEW.domain
           OR predecessor.security_id <> NEW.security_id
           OR predecessor.company_id <> NEW.company_id
           OR predecessor.instrument_id <> NEW.instrument_id
           OR predecessor.share_class_id <> NEW.share_class_id
           OR predecessor.listing_id <> NEW.listing_id
           OR predecessor.ticker_assignment_id
                <> NEW.ticker_assignment_id
           OR NEW.source_revision <> predecessor.source_revision + 1
           OR NEW.effective_at <> predecessor.effective_at
           OR NEW.available_at < predecessor.available_at
           OR NEW.ingested_at <= predecessor.ingested_at THEN
            RAISE EXCEPTION 'Canonical evidence correction predecessor is invalid';
        END IF;
    END IF;

    IF NEW.state <> 'VALID' THEN
        RETURN NEW;
    END IF;

    CASE NEW.domain
        WHEN 'DAILY_PRICE' THEN
            allowed_keys := ARRAY[
                'sessionDate', 'adjustmentMode', 'currency',
                'open', 'high', 'low', 'close', 'adjustedClose', 'volume'
            ];
            required_keys := allowed_keys;
        WHEN 'CORPORATE_ACTION' THEN
            IF NEW.canonical_data->>'actionType' = 'DIVIDEND' THEN
                allowed_keys := ARRAY[
                    'actionId', 'actionType', 'effectiveDate',
                    'amount', 'currency'
                ];
            ELSIF NEW.canonical_data->>'actionType' = 'SPLIT' THEN
                allowed_keys := ARRAY[
                    'actionId', 'actionType', 'effectiveDate',
                    'splitFrom', 'splitTo'
                ];
            ELSIF NEW.canonical_data->>'actionType' = 'SYMBOL_CHANGE' THEN
                allowed_keys := ARRAY[
                    'actionId', 'actionType', 'effectiveDate', 'newTicker'
                ];
            ELSE
                allowed_keys := ARRAY[
                    'actionId', 'actionType', 'effectiveDate'
                ];
            END IF;
            required_keys := allowed_keys;
        WHEN 'FUNDAMENTAL' THEN
            allowed_keys := ARRAY[
                'metricCode', 'numericValue', 'unit', 'currency',
                'periodStart', 'periodEnd', 'fiscalPeriod', 'formType',
                'accessionNumber', 'filedAt', 'mappingVersion'
            ];
            required_keys := allowed_keys;
        WHEN 'CLASSIFICATION' THEN
            allowed_keys := ARRAY[
                'taxonomyCode', 'taxonomyVersion', 'sectorCode',
                'industryCode', 'companyType', 'effectiveFrom'
            ];
            required_keys := allowed_keys;
        WHEN 'MARKET_BENCHMARK' THEN
            allowed_keys := ARRAY[
                'benchmarkKind', 'benchmarkCode', 'benchmarkSecurityId',
                'sectorCode', 'mappingVersion', 'effectiveFrom', 'effectiveTo'
            ];
            required_keys := allowed_keys;
        WHEN 'SECTOR_BENCHMARK' THEN
            allowed_keys := ARRAY[
                'benchmarkKind', 'benchmarkCode', 'benchmarkSecurityId',
                'sectorCode', 'mappingVersion', 'effectiveFrom', 'effectiveTo'
            ];
            required_keys := allowed_keys;
        WHEN 'LIQUIDITY' THEN
            allowed_keys := ARRAY[
                'windowCompletedSessions', 'windowEndSessionDate',
                'validObservationCount', 'averageDailyDollarVolume',
                'averageDailyShareVolume', 'currency',
                'liquidityPolicyVersion'
            ];
            required_keys := allowed_keys;
    END CASE;

    IF jsonb_typeof(NEW.canonical_data) <> 'object'
       OR NOT NEW.canonical_data ?& required_keys
       OR NEW.canonical_data - allowed_keys <> '{}'::jsonb
       OR analytics.evidence_json_has_decision_leakage_v1(
            NEW.canonical_data
       )
       OR NOT analytics.validate_canonical_domain_data_v1(
            NEW.domain,
            NEW.layer,
            NEW.canonical_data,
            NEW.available_at,
            NEW.ingested_at
       ) THEN
        RAISE EXCEPTION
            'Canonical evidence contains missing or provider-native fields';
    END IF;

    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_canonical_evidence_completeness_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    parent_count INTEGER;
    invalid_parent_count INTEGER;
    sealed_parent_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO parent_count
    FROM analytics.canonical_evidence_parent_v1
    WHERE evidence_id = NEW.evidence_id;

    SELECT COUNT(*) INTO invalid_parent_count
    FROM analytics.canonical_evidence_parent_v1 parent
    JOIN analytics.canonical_evidence_v1 parent_evidence
      ON parent_evidence.evidence_id = parent.parent_evidence_id
    WHERE parent.evidence_id = NEW.evidence_id
      AND parent.parent_evidence_hash
            <> parent_evidence.normalized_record_hash;

    SELECT seal.parent_count INTO sealed_parent_count
    FROM analytics.canonical_evidence_parent_seal_v1 seal
    WHERE seal.evidence_id = NEW.evidence_id;

    IF (
        NEW.layer = 'NORMALIZED_OBSERVATION'
        AND (
            parent_count <> 0
            OR sealed_parent_count IS NOT NULL
        )
    ) OR (
        NEW.layer = 'ENGINE_DERIVED'
        AND NEW.state = 'VALID'
        AND (
            parent_count = 0
            OR invalid_parent_count <> 0
            OR sealed_parent_count IS NULL
            OR sealed_parent_count <> parent_count
        )
    ) OR (
        NEW.layer = 'ENGINE_DERIVED'
        AND NEW.state <> 'VALID'
        AND (
            parent_count <> 0
            OR sealed_parent_count IS NOT NULL
        )
    ) THEN
        RAISE EXCEPTION 'Canonical evidence layer completeness is invalid';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION analytics.validate_canonical_evidence_parent_insert_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    owner_record analytics.canonical_evidence_v1%ROWTYPE;
    parent_record analytics.canonical_evidence_v1%ROWTYPE;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.evidence_id::TEXT, 220023)
    );
    IF EXISTS (
        SELECT 1
        FROM analytics.canonical_evidence_parent_seal_v1 seal
        WHERE seal.evidence_id = NEW.evidence_id
    ) THEN
        RAISE EXCEPTION 'Canonical evidence parent set is sealed';
    END IF;
    SELECT * INTO owner_record
    FROM analytics.canonical_evidence_v1
    WHERE evidence_id = NEW.evidence_id;
    SELECT * INTO parent_record
    FROM analytics.canonical_evidence_v1
    WHERE evidence_id = NEW.parent_evidence_id;
    IF owner_record.layer <> 'ENGINE_DERIVED'
       OR owner_record.state <> 'VALID'
       OR parent_record.evidence_id IS NULL
       OR parent_record.state <> 'VALID'
       OR parent_record.layer <> 'NORMALIZED_OBSERVATION'
       OR (
            owner_record.domain = 'LIQUIDITY'
            AND parent_record.domain <> 'DAILY_PRICE'
       )
       OR parent_record.security_id <> owner_record.security_id
       OR parent_record.listing_id <> owner_record.listing_id
       OR parent_record.normalized_record_hash <> NEW.parent_evidence_hash
       OR parent_record.effective_at > owner_record.effective_at
       OR parent_record.available_at > owner_record.available_at
       OR parent_record.ingested_at > owner_record.ingested_at THEN
        RAISE EXCEPTION 'Canonical evidence parent binding is invalid';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_canonical_evidence_parent_seal_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    owner_record analytics.canonical_evidence_v1%ROWTYPE;
    actual_count INTEGER;
    invalid_count INTEGER;
    distinct_session_count INTEGER;
    completed_window_count INTEGER;
    out_of_window_count INTEGER;
    valid_observation_count INTEGER;
    window_completed_sessions INTEGER;
    window_end_session_date DATE;
    latest_parent_session_date DATE;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.evidence_id::TEXT, 220023)
    );
    SELECT * INTO owner_record
    FROM analytics.canonical_evidence_v1
    WHERE evidence_id = NEW.evidence_id;
    IF owner_record.layer <> 'ENGINE_DERIVED'
       OR owner_record.state <> 'VALID' THEN
        RAISE EXCEPTION 'Canonical evidence parent seal is incomplete';
    END IF;
    SELECT COUNT(*) INTO actual_count
    FROM analytics.canonical_evidence_parent_v1
    WHERE evidence_id = NEW.evidence_id;
    SELECT COUNT(*) INTO invalid_count
    FROM analytics.canonical_evidence_parent_v1 parent
    JOIN analytics.canonical_evidence_v1 evidence
      ON evidence.evidence_id = parent.parent_evidence_id
    WHERE parent.evidence_id = NEW.evidence_id
      AND parent.parent_evidence_hash <> evidence.normalized_record_hash;
    valid_observation_count :=
        (owner_record.canonical_data->>'validObservationCount')::INTEGER;
    window_completed_sessions :=
        (owner_record.canonical_data->>'windowCompletedSessions')::INTEGER;
    window_end_session_date :=
        (owner_record.canonical_data->>'windowEndSessionDate')::DATE;
    SELECT
        COUNT(
            DISTINCT (evidence.canonical_data->>'sessionDate')::DATE
        ),
        MAX((evidence.canonical_data->>'sessionDate')::DATE)
    INTO distinct_session_count, latest_parent_session_date
    FROM analytics.canonical_evidence_parent_v1 parent
    JOIN analytics.canonical_evidence_v1 evidence
      ON evidence.evidence_id = parent.parent_evidence_id
    WHERE parent.evidence_id = NEW.evidence_id;
    SELECT COUNT(*) INTO completed_window_count
    FROM (
        SELECT DISTINCT session_date
        FROM analytics.evidence_completed_session_v1
        WHERE mic = owner_record.mic
          AND session_date <= window_end_session_date
        ORDER BY session_date DESC
        LIMIT window_completed_sessions
    ) completed_window;
    SELECT COUNT(*) INTO out_of_window_count
    FROM analytics.canonical_evidence_parent_v1 parent
    JOIN analytics.canonical_evidence_v1 evidence
      ON evidence.evidence_id = parent.parent_evidence_id
    WHERE parent.evidence_id = NEW.evidence_id
      AND (evidence.canonical_data->>'sessionDate')::DATE NOT IN (
            SELECT session_date
            FROM (
                SELECT DISTINCT session_date
                FROM analytics.evidence_completed_session_v1
                WHERE mic = owner_record.mic
                  AND session_date <= window_end_session_date
                ORDER BY session_date DESC
                LIMIT window_completed_sessions
            ) completed_window
      );
    IF actual_count <> NEW.parent_count
       OR actual_count <> valid_observation_count
       OR distinct_session_count <> actual_count
       OR latest_parent_session_date <> window_end_session_date
       OR completed_window_count <> window_completed_sessions
       OR out_of_window_count <> 0
       OR invalid_count <> 0 THEN
        RAISE EXCEPTION 'Canonical evidence parent seal is incomplete';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_evidence_selector_policy_complete_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    actual_count INTEGER;
    sealed_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO actual_count
    FROM analytics.evidence_selector_provider_priority_v1
    WHERE policy_id = NEW.id;
    SELECT provider_priority_count INTO sealed_count
    FROM analytics.evidence_selector_policy_seal_v1
    WHERE policy_id = NEW.id;
    IF actual_count = 0
       OR sealed_count IS NULL
       OR sealed_count <> actual_count
       OR analytics.evidence_json_has_decision_leakage_v1(
            NEW.domain_constraints
       )
       OR NOT analytics.validate_selector_domain_constraints_v1(
            NEW.domain,
            NEW.field_code,
            NEW.domain_constraints
       ) THEN
        RAISE EXCEPTION 'Evidence selector policy is unsealed or unsafe';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION analytics.validate_evidence_selector_priority_insert_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.policy_id::TEXT, 220024)
    );
    IF EXISTS (
        SELECT 1
        FROM analytics.evidence_selector_policy_seal_v1 seal
        WHERE seal.policy_id = NEW.policy_id
    ) THEN
        RAISE EXCEPTION 'Evidence selector provider priority is sealed';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_evidence_selector_policy_seal_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    actual_count INTEGER;
    ordinal_count INTEGER;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.policy_id::TEXT, 220024)
    );
    SELECT COUNT(*), COUNT(DISTINCT priority_ordinal)
    INTO actual_count, ordinal_count
    FROM analytics.evidence_selector_provider_priority_v1
    WHERE policy_id = NEW.policy_id;
    IF actual_count <> NEW.provider_priority_count
       OR ordinal_count <> actual_count
       OR NOT EXISTS (
            SELECT 1
            FROM analytics.evidence_selector_policy_v1 policy
            WHERE policy.id = NEW.policy_id
              AND NOT analytics.evidence_json_has_decision_leakage_v1(
                    policy.domain_constraints
              )
              AND analytics.validate_selector_domain_constraints_v1(
                    policy.domain,
                    policy.field_code,
                    policy.domain_constraints
              )
       ) THEN
        RAISE EXCEPTION 'Evidence selector provider priority seal is incomplete';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_evidence_selection_request_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    identity_matches BOOLEAN;
    session_record analytics.evidence_completed_session_v1%ROWTYPE;
    listing_record analytics.evidence_listing_identity_v1%ROWTYPE;
    policy_record analytics.evidence_selector_policy_v1%ROWTYPE;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM analytics.evidence_company_identity_v1 company
        JOIN analytics.evidence_instrument_identity_v1 instrument
          ON instrument.company_id = company.company_id
        JOIN analytics.evidence_share_class_identity_v1 share_class
          ON share_class.instrument_id = instrument.instrument_id
        JOIN analytics.evidence_listing_identity_v1 listing
          ON listing.share_class_id = share_class.share_class_id
        JOIN analytics.evidence_ticker_assignment_v1 ticker
          ON ticker.listing_id = listing.listing_id
        WHERE company.company_id = NEW.company_id
          AND instrument.instrument_id = NEW.instrument_id
          AND share_class.share_class_id = NEW.share_class_id
          AND listing.listing_id = NEW.listing_id
          AND listing.security_id = NEW.security_id
          AND ticker.ticker_assignment_id = NEW.ticker_assignment_id
          AND ticker.valid_from <= (
                SELECT session_date
                FROM analytics.evidence_completed_session_v1
                WHERE id = NEW.completed_session_id
          )
          AND (
                ticker.valid_to IS NULL
                OR (
                    SELECT session_date
                    FROM analytics.evidence_completed_session_v1
                    WHERE id = NEW.completed_session_id
                ) < ticker.valid_to
          )
    ) INTO identity_matches;

    SELECT * INTO session_record
    FROM analytics.evidence_completed_session_v1
    WHERE id = NEW.completed_session_id;
    SELECT * INTO listing_record
    FROM analytics.evidence_listing_identity_v1
    WHERE listing_id = NEW.listing_id;
    SELECT * INTO policy_record
    FROM analytics.evidence_selector_policy_v1
    WHERE id = NEW.policy_id;

    IF NOT identity_matches
       OR session_record.id IS NULL
       OR listing_record.listing_id IS NULL
       OR NOT EXISTS (
            SELECT 1
            FROM analytics.evidence_selector_policy_seal_v1 seal
            WHERE seal.policy_id = NEW.policy_id
       )
       OR session_record.mic <> listing_record.mic
       OR session_record.completed_at > NEW.decision_cutoff
       OR NEW.decision_cutoff > NEW.sealed_ingestion_cutoff
       OR (
            policy_record.domain = 'DAILY_PRICE'
            AND (
                policy_record.domain_constraints->>'sessionDate'
                    <> session_record.session_date::TEXT
                OR policy_record.domain_constraints->>'listingId'
                    <> NEW.listing_id::TEXT
                OR policy_record.domain_constraints->>'mic'
                    <> listing_record.mic
                OR policy_record.domain_constraints->>'currency'
                    <> listing_record.currency
            )
       )
       OR (
            policy_record.domain = 'LIQUIDITY'
            AND (
                policy_record.domain_constraints->>'windowEndSessionDate'
                    <> session_record.session_date::TEXT
                OR policy_record.domain_constraints->>'currency'
                    <> listing_record.currency
            )
       ) THEN
        RAISE EXCEPTION
            'Evidence selection request identity or completed-session binding is invalid';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.evidence_candidate_structurally_matches_v1(
    checked_request_id UUID,
    checked_evidence_id UUID
)
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    request_record analytics.evidence_selection_request_v1%ROWTYPE;
    policy_record analytics.evidence_selector_policy_v1%ROWTYPE;
    evidence_record analytics.canonical_evidence_v1%ROWTYPE;
BEGIN
    SELECT * INTO request_record
    FROM analytics.evidence_selection_request_v1
    WHERE request_id = checked_request_id;
    SELECT * INTO policy_record
    FROM analytics.evidence_selector_policy_v1
    WHERE id = request_record.policy_id;
    SELECT * INTO evidence_record
    FROM analytics.canonical_evidence_v1
    WHERE evidence_id = checked_evidence_id;
    RETURN evidence_record.evidence_id IS NOT NULL
       AND evidence_record.security_id = request_record.security_id
       AND evidence_record.company_id = request_record.company_id
       AND evidence_record.instrument_id = request_record.instrument_id
       AND evidence_record.share_class_id = request_record.share_class_id
       AND evidence_record.listing_id = request_record.listing_id
       AND evidence_record.ticker_assignment_id
            = request_record.ticker_assignment_id
       AND evidence_record.domain = policy_record.domain
       AND evidence_record.layer = policy_record.required_layer
       AND evidence_record.normalization_version
            = policy_record.required_normalization_version
       AND evidence_record.strictness_class
            = policy_record.required_strictness_class
       AND evidence_record.claim_class = policy_record.required_claim_class
       AND EXISTS (
            SELECT 1
            FROM analytics.evidence_selector_provider_priority_v1 priority
            WHERE priority.policy_id = policy_record.id
              AND priority.provider_code = evidence_record.provider_code
       );
END;
$$;

CREATE FUNCTION analytics.evidence_candidate_domain_matches_v1(
    checked_request_id UUID,
    checked_evidence_id UUID
)
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    request_record analytics.evidence_selection_request_v1%ROWTYPE;
    policy_record analytics.evidence_selector_policy_v1%ROWTYPE;
    evidence_record analytics.canonical_evidence_v1%ROWTYPE;
    field_key TEXT;
BEGIN
    SELECT * INTO request_record
    FROM analytics.evidence_selection_request_v1
    WHERE request_id = checked_request_id;
    SELECT * INTO policy_record
    FROM analytics.evidence_selector_policy_v1
    WHERE id = request_record.policy_id;
    SELECT * INTO evidence_record
    FROM analytics.canonical_evidence_v1
    WHERE evidence_id = checked_evidence_id;
    IF evidence_record.state <> 'VALID' THEN
        RETURN TRUE;
    ELSIF policy_record.domain = 'DAILY_PRICE' THEN
        field_key := CASE policy_record.field_code
            WHEN 'OPEN_PRICE' THEN 'open'
            WHEN 'HIGH_PRICE' THEN 'high'
            WHEN 'LOW_PRICE' THEN 'low'
            WHEN 'CLOSE_PRICE' THEN 'close'
            WHEN 'ADJUSTED_CLOSE' THEN 'adjustedClose'
            WHEN 'VOLUME' THEN 'volume'
        END;
        RETURN evidence_record.canonical_data ? field_key
           AND evidence_record.canonical_data->field_key
                IS DISTINCT FROM 'null'::jsonb
           AND evidence_record.canonical_data->>'sessionDate'
                = policy_record.domain_constraints->>'sessionDate'
           AND evidence_record.canonical_data->>'adjustmentMode'
                = policy_record.domain_constraints->>'adjustmentMode'
           AND evidence_record.canonical_data->>'currency'
                = policy_record.domain_constraints->>'currency';
    ELSIF policy_record.domain = 'CORPORATE_ACTION' THEN
        RETURN evidence_record.canonical_data->>'actionType'
                = policy_record.domain_constraints->>'actionType'
           AND evidence_record.canonical_data->>'effectiveDate'
                = policy_record.domain_constraints->>'effectiveDate';
    ELSIF policy_record.domain = 'FUNDAMENTAL' THEN
        RETURN evidence_record.canonical_data->>'metricCode'
                = policy_record.field_code
           AND policy_record.field_code
                = policy_record.domain_constraints->>'metricCode'
           AND evidence_record.canonical_data->>'periodEnd'
                = policy_record.domain_constraints->>'periodEnd'
           AND evidence_record.canonical_data->>'unit'
                = policy_record.domain_constraints->>'unit'
           AND evidence_record.canonical_data->'currency'
                IS NOT DISTINCT FROM
                policy_record.domain_constraints->'currency';
    ELSIF policy_record.domain = 'CLASSIFICATION' THEN
        RETURN evidence_record.canonical_data->>'taxonomyVersion'
                = policy_record.domain_constraints->>'taxonomyVersion'
           AND (
                evidence_record.canonical_data->>'effectiveFrom'
           )::DATE <= (
                policy_record.domain_constraints->>'effectiveOn'
           )::DATE;
    ELSIF policy_record.domain IN (
        'MARKET_BENCHMARK', 'SECTOR_BENCHMARK'
    ) THEN
        RETURN evidence_record.canonical_data->>'benchmarkCode'
                = policy_record.domain_constraints->>'benchmarkCode'
           AND evidence_record.canonical_data->'sectorCode'
                IS NOT DISTINCT FROM
                policy_record.domain_constraints->'sectorCode'
           AND (
                evidence_record.canonical_data->>'effectiveFrom'
           )::DATE <= (
                policy_record.domain_constraints->>'effectiveOn'
           )::DATE
           AND (
                evidence_record.canonical_data->'effectiveTo' = 'null'::jsonb
                OR (
                    policy_record.domain_constraints->>'effectiveOn'
                )::DATE < (
                    evidence_record.canonical_data->>'effectiveTo'
                )::DATE
           );
    END IF;
    RETURN evidence_record.canonical_data->>'windowEndSessionDate'
                = policy_record.domain_constraints->>'windowEndSessionDate'
       AND evidence_record.canonical_data->>'windowCompletedSessions'
                = policy_record.domain_constraints->>'windowCompletedSessions'
       AND evidence_record.canonical_data->>'currency'
                = policy_record.domain_constraints->>'currency';
END;
$$;

CREATE FUNCTION analytics.validate_evidence_selection_candidate_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    request_record analytics.evidence_selection_request_v1%ROWTYPE;
    policy_record analytics.evidence_selector_policy_v1%ROWTYPE;
    evidence_record analytics.canonical_evidence_v1%ROWTYPE;
    field_key TEXT;
    domain_binding_matches BOOLEAN := TRUE;
BEGIN
    SELECT * INTO request_record
    FROM analytics.evidence_selection_request_v1
    WHERE request_id = NEW.request_id;
    SELECT * INTO policy_record
    FROM analytics.evidence_selector_policy_v1
    WHERE id = request_record.policy_id;
    SELECT * INTO evidence_record
    FROM analytics.canonical_evidence_v1
    WHERE evidence_id = NEW.evidence_id;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.request_id::TEXT, 220025)
    );
    IF EXISTS (
        SELECT 1
        FROM analytics.evidence_selection_seal_v1 seal
        WHERE seal.request_id = NEW.request_id
    ) THEN
        RAISE EXCEPTION 'Evidence selection candidate set is sealed';
    END IF;

    IF evidence_record.state = 'VALID' THEN
        IF policy_record.domain = 'DAILY_PRICE' THEN
            field_key := CASE policy_record.field_code
                WHEN 'OPEN_PRICE' THEN 'open'
                WHEN 'HIGH_PRICE' THEN 'high'
                WHEN 'LOW_PRICE' THEN 'low'
                WHEN 'CLOSE_PRICE' THEN 'close'
                WHEN 'ADJUSTED_CLOSE' THEN 'adjustedClose'
                WHEN 'VOLUME' THEN 'volume'
            END;
            domain_binding_matches := (
                evidence_record.canonical_data ? field_key
                AND (
                    policy_record.field_code <> 'ADJUSTED_CLOSE'
                    OR analytics.evidence_json_decimal_string_v1(
                        evidence_record.canonical_data->field_key
                    )
                )
                AND evidence_record.canonical_data->>'sessionDate'
                    = policy_record.domain_constraints->>'sessionDate'
                AND evidence_record.canonical_data->>'adjustmentMode'
                    = policy_record.domain_constraints->>'adjustmentMode'
                AND evidence_record.canonical_data->>'currency'
                    = policy_record.domain_constraints->>'currency'
            );
        ELSIF policy_record.domain = 'CORPORATE_ACTION' THEN
            domain_binding_matches := (
                evidence_record.canonical_data->>'actionType'
                    = policy_record.domain_constraints->>'actionType'
                AND evidence_record.canonical_data->>'effectiveDate'
                    = policy_record.domain_constraints->>'effectiveDate'
            );
        ELSIF policy_record.domain = 'FUNDAMENTAL' THEN
            domain_binding_matches := (
                evidence_record.canonical_data->>'metricCode'
                    = policy_record.field_code
                AND policy_record.field_code
                    = policy_record.domain_constraints->>'metricCode'
                AND evidence_record.canonical_data->>'periodEnd'
                    = policy_record.domain_constraints->>'periodEnd'
                AND evidence_record.canonical_data->>'unit'
                    = policy_record.domain_constraints->>'unit'
                AND evidence_record.canonical_data->'currency'
                    IS NOT DISTINCT FROM
                    policy_record.domain_constraints->'currency'
            );
        ELSIF policy_record.domain = 'CLASSIFICATION' THEN
            domain_binding_matches := (
                evidence_record.canonical_data->>'taxonomyVersion'
                    = policy_record.domain_constraints->>'taxonomyVersion'
                AND (
                    evidence_record.canonical_data->>'effectiveFrom'
                )::DATE <= (
                    policy_record.domain_constraints->>'effectiveOn'
                )::DATE
            );
        ELSIF policy_record.domain IN (
            'MARKET_BENCHMARK', 'SECTOR_BENCHMARK'
        ) THEN
            domain_binding_matches := (
                evidence_record.canonical_data->>'benchmarkCode'
                    = policy_record.domain_constraints->>'benchmarkCode'
                AND evidence_record.canonical_data->'sectorCode'
                    IS NOT DISTINCT FROM
                    policy_record.domain_constraints->'sectorCode'
                AND (
                    evidence_record.canonical_data->>'effectiveFrom'
                )::DATE <= (
                    policy_record.domain_constraints->>'effectiveOn'
                )::DATE
                AND (
                    evidence_record.canonical_data->'effectiveTo' = 'null'::jsonb
                    OR (
                        policy_record.domain_constraints->>'effectiveOn'
                    )::DATE < (
                        evidence_record.canonical_data->>'effectiveTo'
                    )::DATE
                )
            );
        ELSIF policy_record.domain = 'LIQUIDITY' THEN
            domain_binding_matches := (
                evidence_record.canonical_data->>'windowEndSessionDate'
                    = policy_record.domain_constraints->>'windowEndSessionDate'
                AND evidence_record.canonical_data->>'windowCompletedSessions'
                    = policy_record.domain_constraints->>'windowCompletedSessions'
                AND evidence_record.canonical_data->>'currency'
                    = policy_record.domain_constraints->>'currency'
            );
        END IF;
    END IF;

    IF request_record.request_id IS NULL
       OR evidence_record.evidence_id IS NULL THEN
        RAISE EXCEPTION 'Evidence candidate binding does not exist';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.assert_evidence_selection_result_v1(
    checked_request_id UUID,
    checked_state VARCHAR,
    checked_reason_code VARCHAR,
    checked_selected_evidence_id UUID
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    request_record analytics.evidence_selection_request_v1%ROWTYPE;
    policy_record analytics.evidence_selector_policy_v1%ROWTYPE;
    ambiguous_count INTEGER;
    critical_count INTEGER;
    expected_state VARCHAR(32);
    expected_reason_code VARCHAR(128);
    expected_selected_evidence_id UUID;
BEGIN
    SELECT * INTO request_record
    FROM analytics.evidence_selection_request_v1
    WHERE request_id = checked_request_id;
    SELECT * INTO policy_record
    FROM analytics.evidence_selector_policy_v1
    WHERE id = request_record.policy_id;

    SELECT COUNT(*) INTO ambiguous_count
    FROM (
        SELECT evidence.provider_code, evidence.source_revision
        FROM analytics.evidence_selection_candidate_v1 candidate
        JOIN analytics.canonical_evidence_v1 evidence
          ON evidence.evidence_id = candidate.evidence_id
        WHERE candidate.request_id = checked_request_id
          AND analytics.evidence_candidate_structurally_matches_v1(
                checked_request_id,
                candidate.evidence_id
          )
        GROUP BY evidence.provider_code, evidence.source_revision
        HAVING COUNT(DISTINCT evidence.normalized_record_hash) > 1
    ) ambiguity;

    IF ambiguous_count > 0 THEN
        expected_state := 'INVALID';
        expected_reason_code := 'AMBIGUOUS_PROVIDER_REVISION';
        expected_selected_evidence_id := NULL;
    ELSE
        SELECT COUNT(*) INTO critical_count
        FROM analytics.evidence_selection_candidate_v1 candidate
        JOIN analytics.canonical_evidence_v1 evidence
          ON evidence.evidence_id = candidate.evidence_id
        WHERE candidate.request_id = checked_request_id
          AND analytics.evidence_candidate_structurally_matches_v1(
                checked_request_id,
                candidate.evidence_id
          )
          AND evidence.available_at <= request_record.decision_cutoff
          AND evidence.ingested_at <= request_record.sealed_ingestion_cutoff
          AND evidence.conflict_criticality = 'CRITICAL';

        IF critical_count > 0 THEN
            expected_state := 'INVALID';
            expected_reason_code := 'CRITICAL_EVIDENCE_CONFLICT';
            expected_selected_evidence_id := NULL;
        ELSE
            SELECT evidence.evidence_id
            INTO expected_selected_evidence_id
            FROM analytics.evidence_selection_candidate_v1 candidate
            JOIN analytics.canonical_evidence_v1 evidence
              ON evidence.evidence_id = candidate.evidence_id
            JOIN analytics.evidence_selector_provider_priority_v1 priority
              ON priority.policy_id = policy_record.id
             AND priority.provider_code = evidence.provider_code
            WHERE candidate.request_id = checked_request_id
              AND analytics.evidence_candidate_structurally_matches_v1(
                    checked_request_id,
                    candidate.evidence_id
              )
              AND evidence.available_at <= request_record.decision_cutoff
              AND evidence.ingested_at <= request_record.sealed_ingestion_cutoff
              AND evidence.conflict_criticality <> 'CRITICAL'
              AND NOT (
                    evidence.conflict_status = 'UNRESOLVED'
                    AND evidence.conflict_criticality = 'NONCRITICAL'
                    AND evidence.affected_factors ? policy_record.field_code
              )
              AND evidence.state = 'VALID'
              AND (
                    evidence.tolerance_field_code IS NULL
                    OR evidence.tolerance_field_code
                        = policy_record.field_code
              )
              AND analytics.evidence_candidate_domain_matches_v1(
                    checked_request_id,
                    candidate.evidence_id
              )
              AND (
                    evidence.stale_after IS NULL
                    OR evidence.stale_after > request_record.decision_cutoff
              )
            ORDER BY priority.priority_ordinal,
                     evidence.source_revision DESC,
                     evidence.normalized_record_hash,
                     evidence.evidence_id
            LIMIT 1;

            IF expected_selected_evidence_id IS NOT NULL THEN
                expected_state := 'VALID';
                expected_reason_code :=
                    'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK';
            ELSE
                SELECT
                    CASE
                        WHEN evidence.available_at
                                > request_record.decision_cutoff
                          OR evidence.ingested_at
                                > request_record.sealed_ingestion_cutoff
                            THEN 'EXCLUDED'
                        WHEN evidence.conflict_status = 'UNRESOLVED'
                         AND evidence.conflict_criticality = 'NONCRITICAL'
                         AND evidence.affected_factors
                                ? policy_record.field_code
                            THEN 'MISSING'
                        WHEN evidence.state = 'STALE'
                          OR (
                                evidence.stale_after IS NOT NULL
                                AND evidence.stale_after
                                    <= request_record.decision_cutoff
                            )
                            THEN 'STALE'
                        WHEN evidence.state <> 'VALID'
                            THEN evidence.state
                        WHEN evidence.tolerance_field_code IS NOT NULL
                         AND evidence.tolerance_field_code
                                <> policy_record.field_code
                            THEN 'MISSING'
                        WHEN NOT analytics.evidence_candidate_domain_matches_v1(
                            checked_request_id,
                            evidence.evidence_id
                        ) THEN 'MISSING'
                        ELSE evidence.state
                    END,
                    CASE
                        WHEN evidence.available_at
                                > request_record.decision_cutoff
                          OR evidence.ingested_at
                                > request_record.sealed_ingestion_cutoff
                            THEN 'EVIDENCE_AFTER_DECISION_OR_INGESTION_CUTOFF'
                        WHEN evidence.conflict_status = 'UNRESOLVED'
                         AND evidence.conflict_criticality = 'NONCRITICAL'
                         AND evidence.affected_factors
                                ? policy_record.field_code
                            THEN 'DEPENDENT_FIELD_CONFLICT'
                        WHEN evidence.state = 'STALE'
                          OR (
                                evidence.stale_after IS NOT NULL
                                AND evidence.stale_after
                                    <= request_record.decision_cutoff
                            )
                            THEN 'FRESHNESS_POLICY_EXPIRED'
                        WHEN evidence.state <> 'VALID'
                            THEN COALESCE(
                                evidence.reason_code, 'NONVALID_EVIDENCE'
                            )
                        WHEN evidence.tolerance_field_code IS NOT NULL
                         AND evidence.tolerance_field_code
                                <> policy_record.field_code
                            THEN 'TOLERANCE_FIELD_MISMATCH'
                        WHEN NOT analytics.evidence_candidate_domain_matches_v1(
                            checked_request_id,
                            evidence.evidence_id
                        ) THEN 'DOMAIN_CONSTRAINT_MISMATCH'
                        ELSE COALESCE(
                            evidence.reason_code, 'NONVALID_EVIDENCE'
                        )
                    END
                INTO expected_state, expected_reason_code
                FROM analytics.evidence_selection_candidate_v1 candidate
                JOIN analytics.canonical_evidence_v1 evidence
                  ON evidence.evidence_id = candidate.evidence_id
                JOIN analytics.evidence_selector_provider_priority_v1 priority
                  ON priority.policy_id = policy_record.id
                 AND priority.provider_code = evidence.provider_code
                WHERE candidate.request_id = checked_request_id
                  AND analytics.evidence_candidate_structurally_matches_v1(
                        checked_request_id,
                        candidate.evidence_id
                  )
                ORDER BY priority.priority_ordinal,
                         evidence.source_revision DESC,
                         evidence.normalized_record_hash,
                         evidence.evidence_id
                LIMIT 1;

                IF expected_state IS NULL THEN
                    expected_state := 'MISSING';
                    expected_reason_code := CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM analytics.evidence_selection_candidate_v1
                            WHERE request_id = checked_request_id
                        ) THEN 'NO_CONTRACT_ELIGIBLE_EVIDENCE'
                        ELSE 'NO_OBSERVATION_CANDIDATES'
                    END;
                END IF;
            END IF;
        END IF;
    END IF;

    IF checked_state <> expected_state
       OR checked_reason_code <> expected_reason_code
       OR checked_selected_evidence_id
            IS DISTINCT FROM expected_selected_evidence_id THEN
        RAISE EXCEPTION
            'Persisted selector result does not match deterministic selector semantics';
    END IF;
END;
$$;

CREATE FUNCTION analytics.evidence_selection_result_content_hash_v1(
    checked_request_id UUID,
    checked_selector_version VARCHAR,
    checked_state VARCHAR,
    checked_reason_code VARCHAR,
    checked_selected_evidence_id UUID,
    checked_rejection_evidence_ids UUID[],
    checked_rejection_reason_codes VARCHAR[]
)
RETURNS VARCHAR
LANGUAGE SQL
STABLE
AS $$
    SELECT
        'sha256:' || encode(
            sha256(
                convert_to(
                    concat_ws(
                        chr(31),
                        request.request_id::TEXT,
                        request.request_content_hash,
                        request.contract_version,
                        policy.id::TEXT,
                        policy.policy_content_hash,
                        policy.policy_version,
                        policy.selector_version,
                        checked_selector_version,
                        checked_state,
                        COALESCE(checked_reason_code, ''),
                        COALESCE(checked_selected_evidence_id::TEXT, '')
                    ) || COALESCE(
                        chr(31) || (
                            SELECT string_agg(
                                rejection.evidence_id::TEXT
                                    || chr(31)
                                    || rejection.reason_code,
                                chr(31)
                                ORDER BY rejection.evidence_id,
                                         rejection.reason_code
                            )
                            FROM unnest(
                                checked_rejection_evidence_ids,
                                checked_rejection_reason_codes
                            ) AS rejection(evidence_id, reason_code)
                        ),
                        ''
                    ),
                    'UTF8'
                )
            ),
            'hex'
        )
    FROM analytics.evidence_selection_request_v1 request
    JOIN analytics.evidence_selector_policy_v1 policy
      ON policy.id = request.policy_id
    WHERE request.request_id = checked_request_id
      AND cardinality(checked_rejection_evidence_ids)
            = cardinality(checked_rejection_reason_codes);
$$;

CREATE FUNCTION analytics.evidence_selection_result_content_hash_v1(
    checked_request_id UUID
)
RETURNS VARCHAR
LANGUAGE SQL
STABLE
AS $$
    SELECT analytics.evidence_selection_result_content_hash_v1(
        result.request_id,
        result.selector_version,
        result.state,
        result.reason_code,
        result.selected_evidence_id,
        COALESCE(
            array_agg(
                rejection.evidence_id
                ORDER BY rejection.evidence_id, rejection.reason_code
            ) FILTER (WHERE rejection.evidence_id IS NOT NULL),
            ARRAY[]::UUID[]
        ),
        COALESCE(
            array_agg(
                rejection.reason_code
                ORDER BY rejection.evidence_id, rejection.reason_code
            ) FILTER (WHERE rejection.evidence_id IS NOT NULL),
            ARRAY[]::VARCHAR[]
        )
    )
    FROM analytics.evidence_selection_result_v1 result
    LEFT JOIN analytics.evidence_selection_rejection_v1 rejection
      ON rejection.request_id = result.request_id
    WHERE result.request_id = checked_request_id
    GROUP BY
        result.request_id,
        result.selector_version,
        result.state,
        result.reason_code,
        result.selected_evidence_id;
$$;

CREATE FUNCTION analytics.validate_evidence_selection_result_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM analytics.assert_evidence_selection_result_v1(
        NEW.request_id,
        NEW.state,
        NEW.reason_code,
        NEW.selected_evidence_id
    );
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.expected_evidence_rejection_reason_v1(
    checked_request_id UUID,
    checked_evidence_id UUID
)
RETURNS VARCHAR
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    request_record analytics.evidence_selection_request_v1%ROWTYPE;
    policy_record analytics.evidence_selector_policy_v1%ROWTYPE;
    evidence_record analytics.canonical_evidence_v1%ROWTYPE;
    result_record analytics.evidence_selection_result_v1%ROWTYPE;
    ambiguous_request BOOLEAN;
    ambiguous_candidate BOOLEAN;
    critical_request BOOLEAN;
BEGIN
    SELECT * INTO request_record
    FROM analytics.evidence_selection_request_v1
    WHERE request_id = checked_request_id;
    SELECT * INTO policy_record
    FROM analytics.evidence_selector_policy_v1
    WHERE id = request_record.policy_id;
    SELECT evidence.* INTO evidence_record
    FROM analytics.evidence_selection_candidate_v1 candidate
    JOIN analytics.canonical_evidence_v1 evidence
      ON evidence.evidence_id = candidate.evidence_id
    WHERE candidate.request_id = checked_request_id
      AND candidate.evidence_id = checked_evidence_id;
    SELECT * INTO result_record
    FROM analytics.evidence_selection_result_v1
    WHERE request_id = checked_request_id;

    IF evidence_record.evidence_id IS NULL
       OR result_record.request_id IS NULL THEN
        RAISE EXCEPTION
            'Evidence rejection requires a persisted candidate and result';
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM analytics.evidence_selection_candidate_v1 candidate
        JOIN analytics.canonical_evidence_v1 evidence
          ON evidence.evidence_id = candidate.evidence_id
        WHERE candidate.request_id = checked_request_id
          AND analytics.evidence_candidate_structurally_matches_v1(
                checked_request_id,
                candidate.evidence_id
          )
        GROUP BY evidence.provider_code, evidence.source_revision
        HAVING COUNT(DISTINCT evidence.normalized_record_hash) > 1
    ) INTO ambiguous_request;

    SELECT EXISTS (
        SELECT 1
        FROM analytics.evidence_selection_candidate_v1 candidate
        JOIN analytics.canonical_evidence_v1 evidence
          ON evidence.evidence_id = candidate.evidence_id
        WHERE candidate.request_id = checked_request_id
          AND analytics.evidence_candidate_structurally_matches_v1(
                checked_request_id,
                candidate.evidence_id
          )
          AND evidence.provider_code = evidence_record.provider_code
          AND evidence.source_revision = evidence_record.source_revision
          AND evidence.normalized_record_hash
                <> evidence_record.normalized_record_hash
    ) INTO ambiguous_candidate;

    IF ambiguous_request THEN
        RETURN CASE
            WHEN ambiguous_candidate THEN 'AMBIGUOUS_PROVIDER_REVISION'
            ELSE 'SELECTION_ABORTED_BY_AMBIGUOUS_PROVIDER_REVISION'
        END;
    END IF;
    IF NOT analytics.evidence_candidate_structurally_matches_v1(
        checked_request_id,
        checked_evidence_id
    ) THEN
        RETURN 'NO_CONTRACT_ELIGIBLE_EVIDENCE';
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM analytics.evidence_selection_candidate_v1 candidate
        JOIN analytics.canonical_evidence_v1 evidence
          ON evidence.evidence_id = candidate.evidence_id
        WHERE candidate.request_id = checked_request_id
          AND analytics.evidence_candidate_structurally_matches_v1(
                checked_request_id,
                candidate.evidence_id
          )
          AND evidence.available_at <= request_record.decision_cutoff
          AND evidence.ingested_at
                <= request_record.sealed_ingestion_cutoff
          AND evidence.conflict_criticality = 'CRITICAL'
    ) INTO critical_request;

    IF evidence_record.available_at > request_record.decision_cutoff
       OR evidence_record.ingested_at
            > request_record.sealed_ingestion_cutoff THEN
        RETURN 'EVIDENCE_AFTER_DECISION_OR_INGESTION_CUTOFF';
    ELSIF evidence_record.conflict_criticality = 'CRITICAL' THEN
        RETURN 'CRITICAL_EVIDENCE_CONFLICT';
    ELSIF evidence_record.conflict_status = 'UNRESOLVED'
          AND evidence_record.conflict_criticality = 'NONCRITICAL'
          AND evidence_record.affected_factors ? policy_record.field_code THEN
        RETURN 'DEPENDENT_FIELD_CONFLICT';
    ELSIF evidence_record.state = 'STALE'
          OR (
                evidence_record.stale_after IS NOT NULL
                AND evidence_record.stale_after
                    <= request_record.decision_cutoff
          ) THEN
        RETURN 'FRESHNESS_POLICY_EXPIRED';
    ELSIF evidence_record.state <> 'VALID' THEN
        RETURN COALESCE(evidence_record.reason_code, 'NONVALID_EVIDENCE');
    ELSIF evidence_record.tolerance_field_code IS NOT NULL
          AND evidence_record.tolerance_field_code
                <> policy_record.field_code THEN
        RETURN 'TOLERANCE_FIELD_MISMATCH';
    ELSIF NOT analytics.evidence_candidate_domain_matches_v1(
        checked_request_id,
        checked_evidence_id
    ) THEN
        RETURN 'DOMAIN_CONSTRAINT_MISMATCH';
    ELSIF critical_request THEN
        RETURN 'SELECTION_ABORTED_BY_CRITICAL_CONFLICT';
    ELSIF evidence_record.evidence_id = result_record.selected_evidence_id THEN
        RETURN NULL;
    END IF;
    RETURN 'LOWER_PROVIDER_PRIORITY_OR_REVISION';
END;
$$;

CREATE FUNCTION analytics.validate_evidence_selection_child_insert_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    expected_reason_code VARCHAR;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.request_id::TEXT, 220025)
    );
    IF EXISTS (
        SELECT 1
        FROM analytics.evidence_selection_seal_v1 seal
        WHERE seal.request_id = NEW.request_id
    ) THEN
        RAISE EXCEPTION 'Evidence selection aggregate is sealed';
    END IF;
    IF TG_TABLE_NAME = 'evidence_selection_rejection_v1' THEN
        IF NOT EXISTS (
            SELECT 1
            FROM analytics.evidence_selection_candidate_v1 candidate
            WHERE candidate.request_id = NEW.request_id
              AND candidate.evidence_id = NEW.evidence_id
        ) THEN
            RAISE EXCEPTION
                'Evidence rejection must reference a request candidate';
        END IF;
        expected_reason_code :=
            analytics.expected_evidence_rejection_reason_v1(
                NEW.request_id,
                NEW.evidence_id
            );
        IF NEW.reason_code IS DISTINCT FROM expected_reason_code THEN
            RAISE EXCEPTION
                'Evidence rejection reason does not match selector semantics';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_evidence_selection_seal_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    actual_candidate_count INTEGER;
    actual_rejection_count INTEGER;
    selected_evidence_id UUID;
    incomplete_rejection_count INTEGER;
    invalid_rejection_reason_count INTEGER;
    expected_result_content_hash VARCHAR(71);
    result_record analytics.evidence_selection_result_v1%ROWTYPE;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.request_id::TEXT, 220025)
    );
    SELECT * INTO result_record
    FROM analytics.evidence_selection_result_v1
    WHERE request_id = NEW.request_id;
    SELECT COUNT(*) INTO actual_candidate_count
    FROM analytics.evidence_selection_candidate_v1
    WHERE request_id = NEW.request_id;
    SELECT COUNT(*) INTO actual_rejection_count
    FROM analytics.evidence_selection_rejection_v1
    WHERE request_id = NEW.request_id;
    selected_evidence_id := result_record.selected_evidence_id;
    SELECT COUNT(*) INTO incomplete_rejection_count
    FROM analytics.evidence_selection_candidate_v1 candidate
    WHERE candidate.request_id = NEW.request_id
      AND (
            (
                candidate.evidence_id = selected_evidence_id
                AND EXISTS (
                    SELECT 1
                    FROM analytics.evidence_selection_rejection_v1 rejection
                    WHERE rejection.request_id = candidate.request_id
                      AND rejection.evidence_id = candidate.evidence_id
                )
            )
            OR (
                candidate.evidence_id
                    IS DISTINCT FROM selected_evidence_id
                AND NOT EXISTS (
                    SELECT 1
                    FROM analytics.evidence_selection_rejection_v1 rejection
                    WHERE rejection.request_id = candidate.request_id
                      AND rejection.evidence_id = candidate.evidence_id
                )
            )
      );
    SELECT COUNT(*) INTO invalid_rejection_reason_count
    FROM analytics.evidence_selection_rejection_v1 rejection
    WHERE rejection.request_id = NEW.request_id
      AND rejection.reason_code IS DISTINCT FROM
            analytics.expected_evidence_rejection_reason_v1(
                rejection.request_id,
                rejection.evidence_id
            );
    IF result_record.request_id IS NULL
       OR actual_candidate_count <> NEW.candidate_count
       OR actual_rejection_count <> NEW.rejection_count
       OR incomplete_rejection_count <> 0
       OR invalid_rejection_reason_count <> 0 THEN
        RAISE EXCEPTION 'Evidence selection seal is incomplete';
    END IF;
    PERFORM analytics.assert_evidence_selection_result_v1(
        result_record.request_id,
        result_record.state,
        result_record.reason_code,
        result_record.selected_evidence_id
    );
    expected_result_content_hash :=
        analytics.evidence_selection_result_content_hash_v1(
            result_record.request_id
        );
    IF expected_result_content_hash IS NULL
       OR result_record.result_content_hash
            <> expected_result_content_hash THEN
        RAISE EXCEPTION
            'Persisted selector result content hash is invalid';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_evidence_selection_complete_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM analytics.evidence_selection_seal_v1 seal
        WHERE seal.request_id = NEW.request_id
    ) THEN
        RAISE EXCEPTION 'Evidence selection result must be sealed';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION analytics.model_applicability_routing_content_hash_v1(
    checked_routing_id UUID,
    checked_company_id UUID,
    checked_classification_evidence_id UUID,
    checked_model_family VARCHAR,
    checked_company_type VARCHAR,
    checked_applicability VARCHAR,
    checked_specialized_model_code VARCHAR,
    checked_routing_version VARCHAR,
    checked_routing_revision INTEGER,
    checked_effective_at TIMESTAMPTZ,
    checked_supersedes_routing_id UUID
)
RETURNS VARCHAR
LANGUAGE SQL
IMMUTABLE
AS $$
SELECT 'sha256:' || encode(
    sha256(
        convert_to(
            concat_ws(
                chr(31),
                checked_routing_id::TEXT,
                checked_company_id::TEXT,
                checked_classification_evidence_id::TEXT,
                checked_model_family,
                checked_company_type,
                checked_applicability,
                COALESCE(checked_specialized_model_code, ''),
                checked_routing_version,
                checked_routing_revision::TEXT,
                (
                    extract(epoch FROM checked_effective_at) * 1000000
                )::BIGINT::TEXT,
                COALESCE(checked_supersedes_routing_id::TEXT, '')
            ),
            'UTF8'
        )
    ),
    'hex'
);
$$;

CREATE FUNCTION analytics.validate_model_applicability_routing_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    evidence_record analytics.canonical_evidence_v1%ROWTYPE;
    latest_route analytics.model_applicability_routing_v1%ROWTYPE;
    expected_applicability VARCHAR;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            NEW.company_id::TEXT || '|' || NEW.model_family,
            220027
        )
    );
    SELECT * INTO evidence_record
    FROM analytics.canonical_evidence_v1
    WHERE evidence_id = NEW.classification_evidence_id;
    IF evidence_record.evidence_id IS NULL
       OR evidence_record.company_id <> NEW.company_id
       OR evidence_record.domain <> 'CLASSIFICATION'
       OR evidence_record.state <> 'VALID'
       OR evidence_record.canonical_data->>'companyType' <> NEW.company_type THEN
        RAISE EXCEPTION 'Model applicability classification binding is invalid';
    END IF;

    expected_applicability := CASE
        WHEN NEW.company_type = 'MATURE_OPERATING_COMPANY'
            THEN 'APPLICABLE'
        WHEN NEW.company_type IN (
            'FINANCIAL', 'BANK', 'INSURER', 'REIT', 'RESOURCE',
            'BIOTECHNOLOGY', 'EMERGING_GROWTH',
            'SPECIAL_SITUATION'
        ) THEN 'SPECIALIZED_MODEL_REQUIRED'
        WHEN NEW.company_type = 'BENCHMARK' THEN 'NOT_APPLICABLE'
        ELSE 'INSUFFICIENT_EVIDENCE'
    END;
    IF NEW.applicability <> expected_applicability THEN
        RAISE EXCEPTION
            'Model applicability does not match the frozen company-type map';
    END IF;
    IF NEW.effective_at < evidence_record.ingested_at THEN
        RAISE EXCEPTION
            'Model applicability predates its classification evidence';
    END IF;
    IF NEW.routing_content_hash <>
        analytics.model_applicability_routing_content_hash_v1(
            NEW.routing_id,
            NEW.company_id,
            NEW.classification_evidence_id,
            NEW.model_family,
            NEW.company_type,
            NEW.applicability,
            NEW.specialized_model_code,
            NEW.routing_version,
            NEW.routing_revision,
            NEW.effective_at,
            NEW.supersedes_routing_id
        ) THEN
        RAISE EXCEPTION
            'Model applicability routing content hash is invalid';
    END IF;

    SELECT * INTO latest_route
    FROM analytics.model_applicability_routing_v1 route
    WHERE route.company_id = NEW.company_id
      AND route.model_family = NEW.model_family
    ORDER BY route.routing_revision DESC, route.effective_at DESC,
             route.routing_id
    LIMIT 1;

    IF latest_route.routing_id IS NULL THEN
        IF NEW.routing_revision <> 1
           OR NEW.supersedes_routing_id IS NOT NULL THEN
            RAISE EXCEPTION
                'Initial model applicability route must start revision one';
        END IF;
    ELSIF NEW.supersedes_routing_id
                IS DISTINCT FROM latest_route.routing_id
          OR NEW.routing_revision <> latest_route.routing_revision + 1
          OR NEW.effective_at <= latest_route.effective_at THEN
        RAISE EXCEPTION
            'Model applicability route must supersede the latest revision';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER tr_validate_canonical_evidence_v1
BEFORE INSERT ON analytics.canonical_evidence_v1
FOR EACH ROW EXECUTE FUNCTION analytics.validate_canonical_evidence_v1();

CREATE TRIGGER tr_validate_evidence_trading_calendar_v1
BEFORE INSERT ON analytics.evidence_trading_calendar_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_evidence_trading_calendar_v1();

CREATE TRIGGER tr_validate_evidence_completed_session_v1
BEFORE INSERT ON analytics.evidence_completed_session_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_evidence_completed_session_v1();

CREATE TRIGGER tr_validate_evidence_ticker_assignment_v1
BEFORE INSERT ON analytics.evidence_ticker_assignment_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_evidence_ticker_assignment_v1();

CREATE TRIGGER tr_validate_canonical_evidence_parent_insert_v1
BEFORE INSERT ON analytics.canonical_evidence_parent_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_canonical_evidence_parent_insert_v1();

CREATE TRIGGER tr_validate_canonical_evidence_parent_seal_v1
BEFORE INSERT ON analytics.canonical_evidence_parent_seal_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_canonical_evidence_parent_seal_v1();

CREATE CONSTRAINT TRIGGER tr_canonical_evidence_complete_v1
AFTER INSERT ON analytics.canonical_evidence_v1
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_canonical_evidence_completeness_v1();

CREATE CONSTRAINT TRIGGER tr_evidence_selector_policy_complete_v1
AFTER INSERT ON analytics.evidence_selector_policy_v1
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_evidence_selector_policy_complete_v1();

CREATE TRIGGER tr_validate_evidence_selector_priority_insert_v1
BEFORE INSERT ON analytics.evidence_selector_provider_priority_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_evidence_selector_priority_insert_v1();

CREATE TRIGGER tr_validate_evidence_selector_policy_seal_v1
BEFORE INSERT ON analytics.evidence_selector_policy_seal_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_evidence_selector_policy_seal_v1();

CREATE TRIGGER tr_validate_evidence_selection_request_v1
BEFORE INSERT ON analytics.evidence_selection_request_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_evidence_selection_request_v1();

CREATE TRIGGER tr_validate_evidence_selection_candidate_v1
BEFORE INSERT ON analytics.evidence_selection_candidate_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_evidence_selection_candidate_v1();

CREATE TRIGGER tr_validate_evidence_selection_candidate_seal_v1
BEFORE INSERT ON analytics.evidence_selection_candidate_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_evidence_selection_child_insert_v1();

CREATE TRIGGER tr_validate_evidence_selection_result_v1
BEFORE INSERT ON analytics.evidence_selection_result_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_evidence_selection_result_v1();

CREATE TRIGGER tr_validate_evidence_selection_rejection_v1
BEFORE INSERT ON analytics.evidence_selection_rejection_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_evidence_selection_child_insert_v1();

CREATE TRIGGER tr_validate_evidence_selection_seal_v1
BEFORE INSERT ON analytics.evidence_selection_seal_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_evidence_selection_seal_v1();

CREATE CONSTRAINT TRIGGER tr_evidence_selection_complete_v1
AFTER INSERT ON analytics.evidence_selection_result_v1
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_evidence_selection_complete_v1();

CREATE TRIGGER tr_validate_model_applicability_routing_v1
BEFORE INSERT ON analytics.model_applicability_routing_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_model_applicability_routing_v1();

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'evidence_company_identity_v1',
        'evidence_instrument_identity_v1',
        'evidence_share_class_identity_v1',
        'evidence_listing_identity_v1',
        'evidence_ticker_assignment_v1',
        'evidence_trading_calendar_v1',
        'evidence_completed_session_v1',
        'evidence_provider_contract_v1',
        'evidence_raw_manifest_v1',
        'canonical_evidence_v1',
        'canonical_evidence_parent_v1',
        'canonical_evidence_parent_seal_v1',
        'evidence_selector_policy_v1',
        'evidence_selector_provider_priority_v1',
        'evidence_selector_policy_seal_v1',
        'evidence_selection_request_v1',
        'evidence_selection_candidate_v1',
        'evidence_selection_result_v1',
        'evidence_selection_rejection_v1',
        'evidence_selection_seal_v1',
        'model_applicability_routing_v1'
    ]
    LOOP
        EXECUTE format(
            'CREATE TRIGGER tr_%s_append_only '
            'BEFORE UPDATE OR DELETE ON analytics.%I '
            'FOR EACH ROW EXECUTE FUNCTION '
            'analytics.reject_evidence_foundation_v1_change()',
            table_name,
            table_name
        );
    END LOOP;
END;
$$;

CREATE INDEX ix_canonical_evidence_selector_v1
    ON analytics.canonical_evidence_v1 (
        listing_id, domain, provider_code, source_revision DESC
    );
CREATE INDEX ix_canonical_evidence_cutoff_v1
    ON analytics.canonical_evidence_v1 (
        listing_id, available_at, ingested_at
    );
CREATE INDEX ix_canonical_evidence_raw_manifest_v1
    ON analytics.canonical_evidence_v1 (raw_manifest_id);
CREATE INDEX ix_evidence_selection_candidate_evidence_v1
    ON analytics.evidence_selection_candidate_v1 (evidence_id);
CREATE INDEX ix_model_applicability_company_v1
    ON analytics.model_applicability_routing_v1 (
        company_id, recorded_at DESC
    );

COMMENT ON TABLE analytics.canonical_evidence_v1 IS
    'Provider-neutral normalized or engine-derived evidence. Non-VALID rows never carry canonical values.';
COMMENT ON TABLE analytics.evidence_raw_manifest_v1 IS
    'Git-safe lineage for licensed raw data stored only in private Git-ignored storage.';
COMMENT ON TABLE analytics.evidence_selection_result_v1 IS
    'Immutable deterministic selector outcome; provider identity is provenance and priority only.';
COMMENT ON TABLE analytics.canonical_evidence_parent_seal_v1 IS
    'Immutable completeness boundary for one engine-derived evidence parent set.';
COMMENT ON TABLE analytics.evidence_selector_policy_seal_v1 IS
    'Immutable completeness boundary for one ordered provider-priority policy.';
COMMENT ON TABLE analytics.evidence_selection_seal_v1 IS
    'Immutable completeness boundary for request candidates, result, and per-candidate rejections.';
COMMENT ON TABLE analytics.model_applicability_routing_v1 IS
    'Classification-bound generic or specialized Fundamental Value model applicability; no score or formula.';
