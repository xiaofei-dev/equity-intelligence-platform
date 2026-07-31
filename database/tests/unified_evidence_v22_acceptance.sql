\set ON_ERROR_STOP on

DO $$
DECLARE
    missing_table_count INTEGER;
    append_only_trigger_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing_table_count
    FROM (
        VALUES
            ('evidence_company_identity_v1'),
            ('evidence_instrument_identity_v1'),
            ('evidence_share_class_identity_v1'),
            ('evidence_listing_identity_v1'),
            ('evidence_ticker_assignment_v1'),
            ('evidence_trading_calendar_v1'),
            ('evidence_completed_session_v1'),
            ('evidence_provider_contract_v1'),
            ('evidence_raw_manifest_v1'),
            ('canonical_evidence_v1'),
            ('canonical_evidence_parent_v1'),
            ('canonical_evidence_parent_seal_v1'),
            ('evidence_selector_policy_v1'),
            ('evidence_selector_provider_priority_v1'),
            ('evidence_selector_policy_seal_v1'),
            ('evidence_selection_request_v1'),
            ('evidence_selection_candidate_v1'),
            ('evidence_selection_result_v1'),
            ('evidence_selection_rejection_v1'),
            ('evidence_selection_seal_v1'),
            ('model_applicability_routing_v1')
    ) expected(table_name)
    WHERE to_regclass('analytics.' || expected.table_name) IS NULL;

    SELECT COUNT(*) INTO append_only_trigger_count
    FROM pg_trigger trigger_definition
    JOIN pg_proc trigger_function
      ON trigger_function.oid = trigger_definition.tgfoid
    JOIN pg_namespace function_namespace
      ON function_namespace.oid = trigger_function.pronamespace
    WHERE NOT trigger_definition.tgisinternal
      AND function_namespace.nspname = 'analytics'
      AND trigger_function.proname =
          'reject_evidence_foundation_v1_change';

    IF missing_table_count <> 0 OR append_only_trigger_count <> 21 THEN
        RAISE EXCEPTION
            'Unified evidence V22 tables or append-only triggers are incomplete';
    END IF;
    IF NOT has_table_privilege(
        'analytics_writer',
        'analytics.canonical_evidence_v1',
        'SELECT'
    ) OR NOT has_table_privilege(
        'analytics_writer',
        'analytics.canonical_evidence_v1',
        'INSERT'
    ) OR has_table_privilege(
        'analytics_reader',
        'analytics.evidence_raw_manifest_v1',
        'SELECT'
    ) THEN
        RAISE EXCEPTION
            'Unified evidence V22 Python ownership or raw access boundary is invalid';
    END IF;
END;
$$;

BEGIN;

INSERT INTO analytics.evidence_company_identity_v1 (
    company_id, registry_version
) VALUES (
    '22000000-0000-4000-8000-000000000001',
    'security-identity-registry-v1.0.0'
);

INSERT INTO analytics.evidence_instrument_identity_v1 (
    instrument_id, company_id, registry_version
) VALUES (
    '22000000-0000-4000-8000-000000000002',
    '22000000-0000-4000-8000-000000000001',
    'security-identity-registry-v1.0.0'
);

INSERT INTO analytics.evidence_share_class_identity_v1 (
    share_class_id, instrument_id, registry_version
) VALUES (
    '22000000-0000-4000-8000-000000000003',
    '22000000-0000-4000-8000-000000000002',
    'security-identity-registry-v1.0.0'
);

INSERT INTO analytics.evidence_listing_identity_v1 (
    listing_id, share_class_id, security_id, mic, currency, registry_version
)
SELECT
    '22000000-0000-4000-8000-000000000004',
    '22000000-0000-4000-8000-000000000003',
    public_id, 'XNAS', 'USD', 'security-identity-registry-v1.0.0'
FROM analytics.security
WHERE symbol = 'AAPL';

INSERT INTO analytics.evidence_ticker_assignment_v1 (
    ticker_assignment_id, listing_id, ticker, valid_from, registry_version
) VALUES (
    '22000000-0000-4000-8000-000000000005',
    '22000000-0000-4000-8000-000000000004',
    'AAPL', DATE '2026-01-01', 'security-identity-registry-v1.0.0'
);

INSERT INTO analytics.evidence_trading_calendar_v1 (
    calendar_id, calendar_version, mic, timezone, calendar_content_hash
) VALUES (
    'XNAS', 'XNAS-2026-v1', 'XNAS', 'America/New_York',
    'sha256:' || repeat('1', 64)
);

INSERT INTO analytics.evidence_completed_session_v1 (
    id, calendar_id, calendar_version, mic, session_date, timezone,
    scheduled_open, scheduled_close, early_close, status, completed_at,
    session_content_hash
) VALUES (
    '22000000-0000-4000-8000-000000000006',
    'XNAS', 'XNAS-2026-v1', 'XNAS', DATE '2026-07-29',
    'America/New_York',
    TIMESTAMPTZ '2026-07-29 13:30:00+00',
    TIMESTAMPTZ '2026-07-29 20:00:00+00',
    FALSE, 'COMPLETED',
    TIMESTAMPTZ '2026-07-29 20:00:01+00',
    'sha256:' || repeat('2', 64)
);

INSERT INTO analytics.evidence_provider_contract_v1 (
    provider_code, provider_contract_version, licensing_classification, status
) VALUES
    (
        'provider-primary', 'provider-contract-v1',
        'PRIVATE_LICENSED', 'ACTIVE'
    ),
    (
        'provider-secondary', 'provider-contract-v1',
        'PRIVATE_LICENSED', 'ACTIVE'
    ),
    (
        'internal-derived', 'internal-derived-v1',
        'INTERNAL_DERIVED', 'ACTIVE'
    );

INSERT INTO analytics.evidence_raw_manifest_v1 (
    id, provider_code, provider_schema_version, source_record_id,
    source_revision, source_content_hash, storage_class,
    payload_stored_in_git, storage_reference, effective_at, available_at,
    retrieved_at, ingested_at
) VALUES
    (
        '22000000-0000-4000-8000-000000000010',
        'provider-primary', 'provider-schema-v3', 'price-primary-20260729',
        2, 'sha256:' || repeat('a', 64), 'PRIVATE_GIT_IGNORED', FALSE,
        'storage/private/provider-primary/price-primary-20260729',
        TIMESTAMPTZ '2026-07-29 20:00:00+00',
        TIMESTAMPTZ '2026-07-29 20:01:00+00',
        TIMESTAMPTZ '2026-07-29 20:03:00+00',
        TIMESTAMPTZ '2026-07-29 20:04:00+00'
    ),
    (
        '22000000-0000-4000-8000-000000000011',
        'provider-secondary', 'provider-schema-v8',
        'price-secondary-20260729',
        5, 'sha256:' || repeat('c', 64), 'PRIVATE_GIT_IGNORED', FALSE,
        'storage/private/provider-secondary/price-secondary-20260729',
        TIMESTAMPTZ '2026-07-29 20:00:00+00',
        TIMESTAMPTZ '2026-07-29 20:01:00+00',
        TIMESTAMPTZ '2026-07-29 20:03:00+00',
        TIMESTAMPTZ '2026-07-29 20:04:00+00'
    ),
    (
        '22000000-0000-4000-8000-000000000012',
        'provider-primary', 'provider-schema-v3',
        'classification-primary-20260101',
        1, 'sha256:' || repeat('d', 64), 'PRIVATE_GIT_IGNORED', FALSE,
        'storage/private/provider-primary/classification-primary-20260101',
        TIMESTAMPTZ '2026-01-01 00:00:00+00',
        TIMESTAMPTZ '2026-01-01 01:00:00+00',
        TIMESTAMPTZ '2026-01-01 01:01:00+00',
        TIMESTAMPTZ '2026-01-01 01:02:00+00'
    ),
    (
        '22000000-0000-4000-8000-000000000013',
        'provider-primary', 'provider-schema-v3', 'price-missing-20260730',
        1, 'sha256:' || repeat('e', 64), 'PRIVATE_GIT_IGNORED', FALSE,
        'storage/private/provider-primary/price-missing-20260730',
        TIMESTAMPTZ '2026-07-30 20:00:00+00',
        TIMESTAMPTZ '2026-07-30 20:01:00+00',
        NULL,
        TIMESTAMPTZ '2026-07-30 20:02:00+00'
    );

INSERT INTO analytics.canonical_evidence_v1 (
    evidence_id, contract_version, domain, layer, state, reason_code,
    security_id, company_id, instrument_id, share_class_id, listing_id,
    ticker_assignment_id, ticker, mic, currency, provider_code,
    provider_schema_version, adapter_version, normalization_version,
    source_record_id, source_revision, source_content_hash,
    normalized_record_hash, effective_at, available_at, retrieved_at,
    ingested_at, freshness_policy_version, stale_after, strictness_class,
    claim_class, conflict_status, conflict_criticality, affected_factors,
    observation_reference, raw_manifest_id, canonical_data
)
SELECT
    '22000000-0000-4000-8000-000000000020',
    'unified-market-data-evidence-foundation-v1.0.0',
    'DAILY_PRICE', 'NORMALIZED_OBSERVATION', 'VALID', NULL,
    security.public_id,
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000002',
    '22000000-0000-4000-8000-000000000003',
    '22000000-0000-4000-8000-000000000004',
    '22000000-0000-4000-8000-000000000005',
    'AAPL', 'XNAS', 'USD', 'provider-primary',
    'provider-schema-v3', 'provider-neutral-adapter-v1.0.0',
    'canonical-equity-v1.0.0', 'price-primary-20260729', 2,
    'sha256:' || repeat('a', 64),
    'sha256:' || repeat('b', 64),
    TIMESTAMPTZ '2026-07-29 20:00:00+00',
    TIMESTAMPTZ '2026-07-29 20:01:00+00',
    TIMESTAMPTZ '2026-07-29 20:03:00+00',
    TIMESTAMPTZ '2026-07-29 20:04:00+00',
    'daily-price-completed-session-v1.0.0',
    TIMESTAMPTZ '2026-07-30 20:00:00+00',
    'STRICT_IDENTITY_AND_CHRONOLOGY', 'CURRENT_ONLY',
    'NONE', 'NONE', '[]'::jsonb,
    'analytics.canonical_evidence_v1:primary-price',
    '22000000-0000-4000-8000-000000000010',
    '{
        "sessionDate":"2026-07-29",
        "adjustmentMode":"TOTAL_RETURN_ADJUSTED",
        "currency":"USD",
        "open":"99.00",
        "high":"102.00",
        "low":"98.50",
        "close":"100.00",
        "adjustedClose":"100.00",
        "volume":1000000
    }'::jsonb
FROM analytics.security security
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.canonical_evidence_v1 (
    evidence_id, contract_version, domain, layer, state, reason_code,
    security_id, company_id, instrument_id, share_class_id, listing_id,
    ticker_assignment_id, ticker, mic, currency, provider_code,
    provider_schema_version, adapter_version, normalization_version,
    source_record_id, source_revision, source_content_hash,
    normalized_record_hash, effective_at, available_at, retrieved_at,
    ingested_at, freshness_policy_version, stale_after, strictness_class,
    claim_class, conflict_status, conflict_criticality, affected_factors,
    observation_reference, raw_manifest_id, canonical_data
)
SELECT
    '22000000-0000-4000-8000-000000000021',
    'unified-market-data-evidence-foundation-v1.0.0',
    'DAILY_PRICE', 'NORMALIZED_OBSERVATION', 'VALID', NULL,
    security.public_id,
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000002',
    '22000000-0000-4000-8000-000000000003',
    '22000000-0000-4000-8000-000000000004',
    '22000000-0000-4000-8000-000000000005',
    'AAPL', 'XNAS', 'USD', 'provider-secondary',
    'provider-schema-v8', 'provider-neutral-adapter-v1.0.0',
    'canonical-equity-v1.0.0', 'price-secondary-20260729', 5,
    'sha256:' || repeat('c', 64),
    'sha256:' || repeat('d', 64),
    TIMESTAMPTZ '2026-07-29 20:00:00+00',
    TIMESTAMPTZ '2026-07-29 20:01:00+00',
    TIMESTAMPTZ '2026-07-29 20:03:00+00',
    TIMESTAMPTZ '2026-07-29 20:04:00+00',
    'daily-price-completed-session-v1.0.0',
    TIMESTAMPTZ '2026-07-30 20:00:00+00',
    'STRICT_IDENTITY_AND_CHRONOLOGY', 'CURRENT_ONLY',
    'NONE', 'NONE', '[]'::jsonb,
    'analytics.canonical_evidence_v1:secondary-price',
    '22000000-0000-4000-8000-000000000011',
    '{
        "sessionDate":"2026-07-29",
        "adjustmentMode":"TOTAL_RETURN_ADJUSTED",
        "currency":"USD",
        "open":"99.00",
        "high":"102.00",
        "low":"98.50",
        "close":"100.00",
        "adjustedClose":"100.00",
        "volume":1000000
    }'::jsonb
FROM analytics.security security
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.canonical_evidence_v1 (
    evidence_id, contract_version, domain, layer, state, reason_code,
    security_id, company_id, instrument_id, share_class_id, listing_id,
    ticker_assignment_id, ticker, mic, currency, provider_code,
    provider_schema_version, adapter_version, normalization_version,
    source_record_id, source_revision, source_content_hash,
    normalized_record_hash, effective_at, available_at, retrieved_at,
    ingested_at, freshness_policy_version, stale_after, strictness_class,
    claim_class, conflict_status, conflict_criticality, affected_factors,
    observation_reference, raw_manifest_id, canonical_data
)
SELECT
    '22000000-0000-4000-8000-000000000022',
    'unified-market-data-evidence-foundation-v1.0.0',
    'CLASSIFICATION', 'NORMALIZED_OBSERVATION', 'VALID', NULL,
    security.public_id,
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000002',
    '22000000-0000-4000-8000-000000000003',
    '22000000-0000-4000-8000-000000000004',
    '22000000-0000-4000-8000-000000000005',
    'AAPL', 'XNAS', 'USD', 'provider-primary',
    'provider-schema-v3', 'provider-neutral-adapter-v1.0.0',
    'canonical-equity-v1.0.0', 'classification-primary-20260101', 1,
    'sha256:' || repeat('d', 64),
    'sha256:' || repeat('4', 64),
    TIMESTAMPTZ '2026-01-01 00:00:00+00',
    TIMESTAMPTZ '2026-01-01 01:00:00+00',
    TIMESTAMPTZ '2026-01-01 01:01:00+00',
    TIMESTAMPTZ '2026-01-01 01:02:00+00',
    'classification-v1.0.0', NULL,
    'STRICT_IDENTITY_AND_CHRONOLOGY', 'CURRENT_ONLY',
    'NONE', 'NONE', '[]'::jsonb,
    'analytics.canonical_evidence_v1:classification',
    '22000000-0000-4000-8000-000000000012',
    '{
        "taxonomyCode":"GICS",
        "taxonomyVersion":"GICS-2025",
        "sectorCode":"45",
        "industryCode":"45102010",
        "companyType":"MATURE_OPERATING_COMPANY",
        "effectiveFrom":"2026-01-01"
    }'::jsonb
FROM analytics.security security
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.canonical_evidence_v1 (
    evidence_id, contract_version, domain, layer, state, reason_code,
    security_id, company_id, instrument_id, share_class_id, listing_id,
    ticker_assignment_id, ticker, mic, currency, provider_code,
    provider_schema_version, adapter_version, normalization_version,
    source_record_id, source_revision, source_content_hash,
    normalized_record_hash, effective_at, available_at, retrieved_at,
    ingested_at, freshness_policy_version, stale_after, strictness_class,
    claim_class, conflict_status, conflict_criticality, affected_factors,
    observation_reference, raw_manifest_id, canonical_data
)
SELECT
    '22000000-0000-4000-8000-000000000023',
    'unified-market-data-evidence-foundation-v1.0.0',
    'DAILY_PRICE', 'NORMALIZED_OBSERVATION', 'MISSING',
    'NO_COMPLETED_SESSION_OBSERVATION',
    security.public_id,
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000002',
    '22000000-0000-4000-8000-000000000003',
    '22000000-0000-4000-8000-000000000004',
    '22000000-0000-4000-8000-000000000005',
    'AAPL', 'XNAS', 'USD', 'provider-primary',
    'provider-schema-v3', 'provider-neutral-adapter-v1.0.0',
    'canonical-equity-v1.0.0', 'price-missing-20260730', 1,
    'sha256:' || repeat('e', 64),
    'sha256:' || repeat('5', 64),
    TIMESTAMPTZ '2026-07-30 20:00:00+00',
    TIMESTAMPTZ '2026-07-30 20:01:00+00',
    NULL,
    TIMESTAMPTZ '2026-07-30 20:02:00+00',
    'daily-price-completed-session-v1.0.0', NULL,
    'STRICT_IDENTITY_AND_CHRONOLOGY', 'CURRENT_ONLY',
    'NONE', 'NONE', '[]'::jsonb,
    'analytics.canonical_evidence_v1:missing-price',
    '22000000-0000-4000-8000-000000000013',
    NULL
FROM analytics.security security
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.canonical_evidence_v1 (
    evidence_id, contract_version, domain, layer, state, reason_code,
    security_id, company_id, instrument_id, share_class_id, listing_id,
    ticker_assignment_id, ticker, mic, currency, provider_code,
    provider_schema_version, adapter_version, normalization_version,
    source_record_id, source_revision, source_content_hash,
    normalized_record_hash, effective_at, available_at, retrieved_at,
    ingested_at, freshness_policy_version, stale_after, strictness_class,
    claim_class, conflict_status, conflict_criticality, affected_factors,
    observation_reference, derivation_version, derivation_output_hash,
    canonical_data
)
SELECT
    '22000000-0000-4000-8000-000000000024',
    'unified-market-data-evidence-foundation-v1.0.0',
    'LIQUIDITY', 'ENGINE_DERIVED', 'VALID', NULL,
    security.public_id,
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000002',
    '22000000-0000-4000-8000-000000000003',
    '22000000-0000-4000-8000-000000000004',
    '22000000-0000-4000-8000-000000000005',
    'AAPL', 'XNAS', 'USD', 'internal-derived',
    'internal-derived-v1', 'liquidity-engine-v1.0.0',
    'canonical-equity-v1.0.0', 'liquidity-AAPL-20260729', 1,
    'sha256:' || repeat('6', 64),
    'sha256:' || repeat('7', 64),
    TIMESTAMPTZ '2026-07-29 20:00:00+00',
    TIMESTAMPTZ '2026-07-29 20:04:00+00',
    NULL,
    TIMESTAMPTZ '2026-07-29 20:04:00+00',
    'daily-liquidity-v1.0.0',
    TIMESTAMPTZ '2026-07-30 20:00:00+00',
    'STRICT_IDENTITY_AND_CHRONOLOGY', 'CURRENT_ONLY',
    'NONE', 'NONE', '[]'::jsonb,
    'analytics.canonical_evidence_v1:liquidity',
    'daily-liquidity-v1.0.0',
    'sha256:' || repeat('7', 64),
    '{
        "windowCompletedSessions":1,
        "windowEndSessionDate":"2026-07-29",
        "validObservationCount":1,
        "averageDailyDollarVolume":"25000000.00",
        "averageDailyShareVolume":"250000.00",
        "currency":"USD",
        "liquidityPolicyVersion":"daily-liquidity-v1.0.0"
    }'::jsonb
FROM analytics.security security
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.canonical_evidence_parent_v1 (
    evidence_id, parent_ordinal, parent_evidence_id, parent_evidence_hash
) VALUES (
    '22000000-0000-4000-8000-000000000024',
    1,
    '22000000-0000-4000-8000-000000000020',
    'sha256:' || repeat('b', 64)
);

INSERT INTO analytics.canonical_evidence_parent_seal_v1 (
    evidence_id, parent_count
) VALUES (
    '22000000-0000-4000-8000-000000000024', 1
);

INSERT INTO analytics.evidence_selector_policy_v1 (
    id, selector_version, policy_version, domain, field_code,
    required_layer, domain_constraints, required_strictness_class,
    required_claim_class, required_normalization_version,
    policy_content_hash
) VALUES (
    '22000000-0000-4000-8000-000000000030',
    'deterministic-evidence-selector-v1.0.0',
    'daily-price-selection-v1.0.0',
    'DAILY_PRICE', 'CLOSE_PRICE', 'NORMALIZED_OBSERVATION',
    '{
        "sessionDate":"2026-07-29",
        "adjustmentMode":"TOTAL_RETURN_ADJUSTED",
        "currency":"USD",
        "mic":"XNAS",
        "listingId":"22000000-0000-4000-8000-000000000004"
    }'::jsonb,
    'STRICT_IDENTITY_AND_CHRONOLOGY', 'CURRENT_ONLY',
    'canonical-equity-v1.0.0',
    'sha256:' || repeat('8', 64)
);

INSERT INTO analytics.evidence_selector_provider_priority_v1 (
    policy_id, priority_ordinal, provider_code
) VALUES
    (
        '22000000-0000-4000-8000-000000000030',
        1, 'provider-primary'
    ),
    (
        '22000000-0000-4000-8000-000000000030',
        2, 'provider-secondary'
    );

INSERT INTO analytics.evidence_selector_policy_seal_v1 (
    policy_id, provider_priority_count
) VALUES (
    '22000000-0000-4000-8000-000000000030', 2
);

INSERT INTO analytics.evidence_selection_request_v1 (
    request_id, contract_version, policy_id, security_id, company_id,
    instrument_id, share_class_id, listing_id, ticker_assignment_id,
    completed_session_id, decision_cutoff, sealed_ingestion_cutoff,
    request_content_hash
)
SELECT
    '22000000-0000-4000-8000-000000000031',
    'unified-market-data-evidence-foundation-v1.0.0',
    '22000000-0000-4000-8000-000000000030',
    security.public_id,
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000002',
    '22000000-0000-4000-8000-000000000003',
    '22000000-0000-4000-8000-000000000004',
    '22000000-0000-4000-8000-000000000005',
    '22000000-0000-4000-8000-000000000006',
    TIMESTAMPTZ '2026-07-29 20:05:00+00',
    TIMESTAMPTZ '2026-07-29 20:07:00+00',
    'sha256:' || repeat('9', 64)
FROM analytics.security security
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.evidence_selection_candidate_v1 (
    request_id, candidate_ordinal, evidence_id
) VALUES
    (
        '22000000-0000-4000-8000-000000000031',
        1, '22000000-0000-4000-8000-000000000020'
    ),
    (
        '22000000-0000-4000-8000-000000000031',
        2, '22000000-0000-4000-8000-000000000021'
    );

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.evidence_selection_result_v1 (
            request_id, selector_version, state, reason_code,
            selected_evidence_id, result_content_hash
        ) VALUES (
            '22000000-0000-4000-8000-000000000031',
            'deterministic-evidence-selector-v1.0.0',
            'MISSING', 'NO_OBSERVATION_CANDIDATES', NULL,
            'sha256:' || repeat('0', 64)
        );
        RAISE EXCEPTION 'Unjustified non-VALID selector result was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM =
                'Unjustified non-VALID selector result was accepted' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO analytics.evidence_selection_result_v1 (
    request_id, selector_version, state, reason_code,
    selected_evidence_id, result_content_hash
) VALUES (
    '22000000-0000-4000-8000-000000000031',
    'deterministic-evidence-selector-v1.0.0',
    'VALID', 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
    '22000000-0000-4000-8000-000000000020',
    analytics.evidence_selection_result_content_hash_v1(
        '22000000-0000-4000-8000-000000000031',
        'deterministic-evidence-selector-v1.0.0',
        'VALID', 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
        '22000000-0000-4000-8000-000000000020',
        ARRAY['22000000-0000-4000-8000-000000000021']::UUID[],
        ARRAY['LOWER_PROVIDER_PRIORITY_OR_REVISION']::VARCHAR[]
    )
);

INSERT INTO analytics.evidence_selection_rejection_v1 (
    request_id, rejection_ordinal, evidence_id, reason_code
) VALUES (
    '22000000-0000-4000-8000-000000000031',
    1, '22000000-0000-4000-8000-000000000021',
    'LOWER_PROVIDER_PRIORITY_OR_REVISION'
);

INSERT INTO analytics.evidence_selection_seal_v1 (
    request_id, candidate_count, rejection_count
) VALUES (
    '22000000-0000-4000-8000-000000000031', 2, 1
);

INSERT INTO analytics.model_applicability_routing_v1 (
    routing_id, company_id, classification_evidence_id, model_family,
    company_type, applicability, specialized_model_code, routing_version,
    routing_revision, effective_at, routing_content_hash
) VALUES (
    '22000000-0000-4000-8000-000000000040',
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000022',
    'FUNDAMENTAL_VALUE', 'MATURE_OPERATING_COMPANY', 'APPLICABLE', NULL,
    'fundamental-applicability-routing-v1.0.0',
    1, TIMESTAMPTZ '2026-01-01 01:03:00+00',
    analytics.model_applicability_routing_content_hash_v1(
        '22000000-0000-4000-8000-000000000040',
        '22000000-0000-4000-8000-000000000001',
        '22000000-0000-4000-8000-000000000022',
        'FUNDAMENTAL_VALUE', 'MATURE_OPERATING_COMPANY', 'APPLICABLE',
        NULL, 'fundamental-applicability-routing-v1.0.0',
        1, TIMESTAMPTZ '2026-01-01 01:03:00+00', NULL
    )
);

COMMIT;

BEGIN;

DO $$
DECLARE
    selected_count INTEGER;
    parent_count INTEGER;
    missing_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO selected_count
    FROM analytics.evidence_selection_result_v1
    WHERE request_id = '22000000-0000-4000-8000-000000000031'
      AND state = 'VALID'
      AND selected_evidence_id = '22000000-0000-4000-8000-000000000020';

    SELECT COUNT(*) INTO parent_count
    FROM analytics.canonical_evidence_parent_v1
    WHERE evidence_id = '22000000-0000-4000-8000-000000000024'
      AND parent_evidence_hash = 'sha256:' || repeat('b', 64);

    SELECT COUNT(*) INTO missing_count
    FROM analytics.canonical_evidence_v1
    WHERE evidence_id = '22000000-0000-4000-8000-000000000023'
      AND state = 'MISSING'
      AND reason_code = 'NO_COMPLETED_SESSION_OBSERVATION'
      AND canonical_data IS NULL;

    IF selected_count <> 1 OR parent_count <> 1 OR missing_count <> 1 THEN
        RAISE EXCEPTION 'Unified evidence V22 representative rows did not round-trip';
    END IF;
END;
$$;

DO $$
DECLARE
    security_public_id UUID;
BEGIN
    SELECT public_id INTO security_public_id
    FROM analytics.security
    WHERE symbol = 'AAPL';

    BEGIN
        INSERT INTO analytics.canonical_evidence_v1 (
            evidence_id, contract_version, domain, layer, state, reason_code,
            security_id, company_id, instrument_id, share_class_id,
            listing_id, ticker_assignment_id, ticker, mic, currency,
            provider_code, provider_schema_version, adapter_version,
            normalization_version, source_record_id, source_revision,
            source_content_hash, normalized_record_hash, effective_at,
            available_at, retrieved_at, ingested_at,
            freshness_policy_version, stale_after, strictness_class,
            claim_class, conflict_status, conflict_criticality,
            affected_factors, observation_reference, raw_manifest_id,
            canonical_data
        ) VALUES (
            '22000000-0000-4000-8000-000000000050',
            'unified-market-data-evidence-foundation-v1.0.0',
            'DAILY_PRICE', 'NORMALIZED_OBSERVATION', 'VALID', NULL,
            security_public_id,
            '22000000-0000-4000-8000-000000000099',
            '22000000-0000-4000-8000-000000000002',
            '22000000-0000-4000-8000-000000000003',
            '22000000-0000-4000-8000-000000000004',
            '22000000-0000-4000-8000-000000000005',
            'AAPL', 'XNAS', 'USD', 'provider-primary',
            'provider-schema-v3', 'provider-neutral-adapter-v1.0.0',
            'canonical-equity-v1.0.0', 'price-primary-20260729', 2,
            'sha256:' || repeat('a', 64),
            'sha256:' || repeat('0', 64),
            TIMESTAMPTZ '2026-07-29 20:00:00+00',
            TIMESTAMPTZ '2026-07-29 20:01:00+00',
            TIMESTAMPTZ '2026-07-29 20:03:00+00',
            TIMESTAMPTZ '2026-07-29 20:04:00+00',
            'daily-price-completed-session-v1.0.0',
            TIMESTAMPTZ '2026-07-30 20:00:00+00',
            'STRICT_IDENTITY_AND_CHRONOLOGY', 'CURRENT_ONLY',
            'NONE', 'NONE', '[]'::jsonb,
            'invalid-identity', '22000000-0000-4000-8000-000000000010',
            '{
                "sessionDate":"2026-07-29",
                "adjustmentMode":"TOTAL_RETURN_ADJUSTED",
                "currency":"USD",
                "open":"99","high":"102","low":"98","close":"100",
                "adjustedClose":"100","volume":1
            }'::jsonb
        );
        RAISE EXCEPTION 'Missing durable identity binding was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Missing durable identity binding was accepted' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO analytics.canonical_evidence_v1 (
            evidence_id, contract_version, domain, layer, state, reason_code,
            security_id, company_id, instrument_id, share_class_id,
            listing_id, ticker_assignment_id, ticker, mic, currency,
            provider_code, provider_schema_version, adapter_version,
            normalization_version, source_record_id, source_revision,
            source_content_hash, normalized_record_hash, effective_at,
            available_at, retrieved_at, ingested_at,
            freshness_policy_version, stale_after, strictness_class,
            claim_class, conflict_status, conflict_criticality,
            affected_factors, observation_reference, raw_manifest_id,
            canonical_data
        ) VALUES (
            '22000000-0000-4000-8000-000000000051',
            'unified-market-data-evidence-foundation-v1.0.0',
            'DAILY_PRICE', 'NORMALIZED_OBSERVATION', 'VALID', NULL,
            security_public_id,
            '22000000-0000-4000-8000-000000000001',
            '22000000-0000-4000-8000-000000000002',
            '22000000-0000-4000-8000-000000000003',
            '22000000-0000-4000-8000-000000000004',
            '22000000-0000-4000-8000-000000000005',
            'AAPL', 'XNAS', 'USD', 'provider-primary',
            'provider-schema-v3', 'provider-neutral-adapter-v1.0.0',
            'canonical-equity-v1.0.0', 'price-primary-20260729', 2,
            'sha256:' || repeat('f', 64),
            'sha256:' || repeat('0', 64),
            TIMESTAMPTZ '2026-07-29 20:00:00+00',
            TIMESTAMPTZ '2026-07-29 20:01:00+00',
            TIMESTAMPTZ '2026-07-29 20:03:00+00',
            TIMESTAMPTZ '2026-07-29 20:04:00+00',
            'daily-price-completed-session-v1.0.0',
            TIMESTAMPTZ '2026-07-30 20:00:00+00',
            'STRICT_IDENTITY_AND_CHRONOLOGY', 'CURRENT_ONLY',
            'NONE', 'NONE', '[]'::jsonb,
            'hash-drift', '22000000-0000-4000-8000-000000000010',
            '{
                "sessionDate":"2026-07-29",
                "adjustmentMode":"TOTAL_RETURN_ADJUSTED",
                "currency":"USD",
                "open":"99","high":"102","low":"98","close":"100",
                "adjustedClose":"100","volume":1
            }'::jsonb
        );
        RAISE EXCEPTION 'Raw-manifest hash drift was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Raw-manifest hash drift was accepted' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO analytics.canonical_evidence_v1 (
            evidence_id, contract_version, domain, layer, state, reason_code,
            security_id, company_id, instrument_id, share_class_id,
            listing_id, ticker_assignment_id, ticker, mic, currency,
            provider_code, provider_schema_version, adapter_version,
            normalization_version, source_record_id, source_revision,
            source_content_hash, normalized_record_hash, effective_at,
            available_at, retrieved_at, ingested_at,
            freshness_policy_version, stale_after, strictness_class,
            claim_class, conflict_status, conflict_criticality,
            affected_factors, observation_reference, raw_manifest_id,
            canonical_data
        ) VALUES (
            '22000000-0000-4000-8000-000000000052',
            'unified-market-data-evidence-foundation-v1.0.0',
            'DAILY_PRICE', 'NORMALIZED_OBSERVATION', 'MISSING',
            'NO_OBSERVATION',
            security_public_id,
            '22000000-0000-4000-8000-000000000001',
            '22000000-0000-4000-8000-000000000002',
            '22000000-0000-4000-8000-000000000003',
            '22000000-0000-4000-8000-000000000004',
            '22000000-0000-4000-8000-000000000005',
            'AAPL', 'XNAS', 'USD', 'provider-primary',
            'provider-schema-v3', 'provider-neutral-adapter-v1.0.0',
            'canonical-equity-v1.0.0', 'price-primary-20260729', 2,
            'sha256:' || repeat('a', 64),
            'sha256:' || repeat('0', 64),
            TIMESTAMPTZ '2026-07-29 20:00:00+00',
            TIMESTAMPTZ '2026-07-29 20:01:00+00',
            TIMESTAMPTZ '2026-07-29 20:03:00+00',
            TIMESTAMPTZ '2026-07-29 20:04:00+00',
            'daily-price-completed-session-v1.0.0',
            TIMESTAMPTZ '2026-07-30 20:00:00+00',
            'STRICT_IDENTITY_AND_CHRONOLOGY', 'CURRENT_ONLY',
            'NONE', 'NONE', '[]'::jsonb,
            'missing-as-zero', '22000000-0000-4000-8000-000000000010',
            '{
                "sessionDate":"2026-07-29",
                "adjustmentMode":"TOTAL_RETURN_ADJUSTED",
                "currency":"USD",
                "open":"0","high":"0","low":"0","close":"0",
                "adjustedClose":"0","volume":0
            }'::jsonb
        );
        RAISE EXCEPTION 'Missing evidence was stored as zero';
    EXCEPTION
        WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO analytics.canonical_evidence_v1 (
            evidence_id, contract_version, domain, layer, state, reason_code,
            security_id, company_id, instrument_id, share_class_id,
            listing_id, ticker_assignment_id, ticker, mic, currency,
            provider_code, provider_schema_version, adapter_version,
            normalization_version, source_record_id, source_revision,
            source_content_hash, normalized_record_hash, effective_at,
            available_at, retrieved_at, ingested_at,
            freshness_policy_version, stale_after, strictness_class,
            claim_class, conflict_status, conflict_criticality,
            affected_factors, observation_reference, raw_manifest_id,
            canonical_data
        ) VALUES (
            '22000000-0000-4000-8000-000000000053',
            'unified-market-data-evidence-foundation-v1.0.0',
            'DAILY_PRICE', 'NORMALIZED_OBSERVATION', 'VALID', NULL,
            security_public_id,
            '22000000-0000-4000-8000-000000000001',
            '22000000-0000-4000-8000-000000000002',
            '22000000-0000-4000-8000-000000000003',
            '22000000-0000-4000-8000-000000000004',
            '22000000-0000-4000-8000-000000000005',
            'AAPL', 'XNAS', 'USD', 'provider-primary',
            'provider-schema-v3', 'provider-neutral-adapter-v1.0.0',
            'canonical-equity-v1.0.0', 'price-primary-20260729', 2,
            'sha256:' || repeat('a', 64),
            'sha256:' || repeat('0', 64),
            TIMESTAMPTZ '2026-07-29 20:00:00+00',
            TIMESTAMPTZ '2026-07-29 20:01:00+00',
            TIMESTAMPTZ '2026-07-29 20:03:00+00',
            TIMESTAMPTZ '2026-07-29 20:04:00+00',
            'daily-price-completed-session-v1.0.0',
            TIMESTAMPTZ '2026-07-30 20:00:00+00',
            'STRICT_IDENTITY_AND_CHRONOLOGY', 'CURRENT_ONLY',
            'NONE', 'NONE', '[]'::jsonb,
            'provider-score-leakage',
            '22000000-0000-4000-8000-000000000010',
            '{
                "sessionDate":"2026-07-29",
                "adjustmentMode":"TOTAL_RETURN_ADJUSTED",
                "currency":"USD",
                "open":{"metadata":{"providerScore":"0.99"}},
                "high":"102","low":"98","close":"100",
                "adjustedClose":"100","volume":1
            }'::jsonb
        );
        RAISE EXCEPTION 'Provider-native score leakage was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Provider-native score leakage was accepted' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        UPDATE analytics.canonical_evidence_v1
        SET state = 'STALE', reason_code = 'MUTATION'
        WHERE evidence_id = '22000000-0000-4000-8000-000000000020';
        RAISE EXCEPTION 'Unsafe canonical evidence mutation was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Unsafe canonical evidence mutation was accepted' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO analytics.canonical_evidence_v1 (
    evidence_id, contract_version, domain, layer, state, reason_code,
    security_id, company_id, instrument_id, share_class_id, listing_id,
    ticker_assignment_id, ticker, mic, currency, provider_code,
    provider_schema_version, adapter_version, normalization_version,
    source_record_id, source_revision, source_content_hash,
    normalized_record_hash, effective_at, available_at, retrieved_at,
    ingested_at, freshness_policy_version, stale_after, strictness_class,
    claim_class, conflict_status, conflict_criticality, affected_factors,
    observation_reference, raw_manifest_id, canonical_data
)
SELECT
    '22000000-0000-4000-8000-000000000054',
    'unified-market-data-evidence-foundation-v1.0.0',
    'DAILY_PRICE', 'NORMALIZED_OBSERVATION', 'VALID', NULL,
    security.public_id,
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000002',
    '22000000-0000-4000-8000-000000000003',
    '22000000-0000-4000-8000-000000000004',
    '22000000-0000-4000-8000-000000000005',
    'AAPL', 'XNAS', 'USD', 'provider-primary',
    'provider-schema-v3', 'provider-neutral-adapter-v1.0.0',
    'canonical-equity-v1.0.0', 'price-primary-20260729', 2,
    'sha256:' || repeat('a', 64),
    'sha256:' || repeat('0', 64),
    TIMESTAMPTZ '2026-07-29 20:00:00+00',
    TIMESTAMPTZ '2026-07-29 20:01:00+00',
    TIMESTAMPTZ '2026-07-29 20:03:00+00',
    TIMESTAMPTZ '2026-07-29 20:04:00+00',
    'daily-price-completed-session-v1.0.0',
    TIMESTAMPTZ '2026-07-30 20:00:00+00',
    'STRICT_IDENTITY_AND_CHRONOLOGY', 'CURRENT_ONLY',
    'NONE', 'NONE', '[]'::jsonb,
    'ambiguity-probe', '22000000-0000-4000-8000-000000000010',
    '{
        "sessionDate":"2026-07-29",
        "adjustmentMode":"TOTAL_RETURN_ADJUSTED",
        "currency":"USD",
        "open":"99","high":"102","low":"98","close":"100",
        "adjustedClose":"100","volume":1
    }'::jsonb
FROM analytics.security security
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.evidence_selection_request_v1 (
    request_id, contract_version, policy_id, security_id, company_id,
    instrument_id, share_class_id, listing_id, ticker_assignment_id,
    completed_session_id, decision_cutoff, sealed_ingestion_cutoff,
    request_content_hash
)
SELECT
    '22000000-0000-4000-8000-000000000055',
    'unified-market-data-evidence-foundation-v1.0.0',
    '22000000-0000-4000-8000-000000000030',
    security.public_id,
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000002',
    '22000000-0000-4000-8000-000000000003',
    '22000000-0000-4000-8000-000000000004',
    '22000000-0000-4000-8000-000000000005',
    '22000000-0000-4000-8000-000000000006',
    TIMESTAMPTZ '2026-07-29 20:05:00+00',
    TIMESTAMPTZ '2026-07-29 20:07:00+00',
    'sha256:' || repeat('0', 64)
FROM analytics.security security
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.evidence_selection_candidate_v1 (
    request_id, candidate_ordinal, evidence_id
) VALUES
    (
        '22000000-0000-4000-8000-000000000055',
        1, '22000000-0000-4000-8000-000000000020'
    ),
    (
        '22000000-0000-4000-8000-000000000055',
        2, '22000000-0000-4000-8000-000000000054'
    );

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.evidence_selection_result_v1 (
            request_id, selector_version, state, reason_code,
            selected_evidence_id, result_content_hash
        ) VALUES (
            '22000000-0000-4000-8000-000000000055',
            'deterministic-evidence-selector-v1.0.0',
            'VALID', 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
            '22000000-0000-4000-8000-000000000020',
            'sha256:' || repeat('1', 64)
        );
        RAISE EXCEPTION 'Ambiguous provider revision was selected';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Ambiguous provider revision was selected' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO analytics.evidence_selection_result_v1 (
    request_id, selector_version, state, reason_code,
    selected_evidence_id, result_content_hash
) VALUES (
    '22000000-0000-4000-8000-000000000055',
    'deterministic-evidence-selector-v1.0.0',
    'INVALID', 'AMBIGUOUS_PROVIDER_REVISION', NULL,
    analytics.evidence_selection_result_content_hash_v1(
        '22000000-0000-4000-8000-000000000055',
        'deterministic-evidence-selector-v1.0.0',
        'INVALID', 'AMBIGUOUS_PROVIDER_REVISION', NULL,
        ARRAY[
            '22000000-0000-4000-8000-000000000020',
            '22000000-0000-4000-8000-000000000054'
        ]::UUID[],
        ARRAY[
            'AMBIGUOUS_PROVIDER_REVISION',
            'AMBIGUOUS_PROVIDER_REVISION'
        ]::VARCHAR[]
    )
);

INSERT INTO analytics.evidence_selection_rejection_v1 (
    request_id, rejection_ordinal, evidence_id, reason_code
) VALUES
    (
        '22000000-0000-4000-8000-000000000055',
        1, '22000000-0000-4000-8000-000000000020',
        'AMBIGUOUS_PROVIDER_REVISION'
    ),
    (
        '22000000-0000-4000-8000-000000000055',
        2, '22000000-0000-4000-8000-000000000054',
        'AMBIGUOUS_PROVIDER_REVISION'
    );

INSERT INTO analytics.evidence_selection_seal_v1 (
    request_id, candidate_count, rejection_count
) VALUES (
    '22000000-0000-4000-8000-000000000055', 2, 2
);

INSERT INTO analytics.evidence_selection_request_v1 (
    request_id, contract_version, policy_id, security_id, company_id,
    instrument_id, share_class_id, listing_id, ticker_assignment_id,
    completed_session_id, decision_cutoff, sealed_ingestion_cutoff,
    request_content_hash
)
SELECT
    '22000000-0000-4000-8000-000000000056',
    'unified-market-data-evidence-foundation-v1.0.0',
    '22000000-0000-4000-8000-000000000030',
    security.public_id,
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000002',
    '22000000-0000-4000-8000-000000000003',
    '22000000-0000-4000-8000-000000000004',
    '22000000-0000-4000-8000-000000000005',
    '22000000-0000-4000-8000-000000000006',
    TIMESTAMPTZ '2026-07-29 20:00:30+00',
    TIMESTAMPTZ '2026-07-29 20:00:45+00',
    'sha256:' || repeat('2', 64)
FROM analytics.security security
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.evidence_selection_candidate_v1 (
    request_id, candidate_ordinal, evidence_id
) VALUES (
    '22000000-0000-4000-8000-000000000056',
    1, '22000000-0000-4000-8000-000000000020'
);

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.evidence_selection_result_v1 (
            request_id, selector_version, state, reason_code,
            selected_evidence_id, result_content_hash
        ) VALUES (
            '22000000-0000-4000-8000-000000000056',
            'deterministic-evidence-selector-v1.0.0',
            'VALID', 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
            '22000000-0000-4000-8000-000000000020',
            'sha256:' || repeat('3', 64)
        );
        RAISE EXCEPTION 'Evidence after the cutoff was selected';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Evidence after the cutoff was selected' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO analytics.evidence_selection_result_v1 (
    request_id, selector_version, state, reason_code,
    selected_evidence_id, result_content_hash
) VALUES (
    '22000000-0000-4000-8000-000000000056',
    'deterministic-evidence-selector-v1.0.0',
    'EXCLUDED', 'EVIDENCE_AFTER_DECISION_OR_INGESTION_CUTOFF', NULL,
    analytics.evidence_selection_result_content_hash_v1(
        '22000000-0000-4000-8000-000000000056',
        'deterministic-evidence-selector-v1.0.0',
        'EXCLUDED',
        'EVIDENCE_AFTER_DECISION_OR_INGESTION_CUTOFF',
        NULL,
        ARRAY['22000000-0000-4000-8000-000000000020']::UUID[],
        ARRAY[
            'EVIDENCE_AFTER_DECISION_OR_INGESTION_CUTOFF'
        ]::VARCHAR[]
    )
);

INSERT INTO analytics.evidence_selection_rejection_v1 (
    request_id, rejection_ordinal, evidence_id, reason_code
) VALUES (
    '22000000-0000-4000-8000-000000000056',
    1, '22000000-0000-4000-8000-000000000020',
    'EVIDENCE_AFTER_DECISION_OR_INGESTION_CUTOFF'
);

INSERT INTO analytics.evidence_selection_seal_v1 (
    request_id, candidate_count, rejection_count
) VALUES (
    '22000000-0000-4000-8000-000000000056', 1, 1
);

DO $$
BEGIN
    IF analytics.validate_canonical_domain_data_v1(
        'DAILY_PRICE',
        'NORMALIZED_OBSERVATION',
        '{
            "sessionDate":"2026-07-29",
            "adjustmentMode":"TOTAL_RETURN_ADJUSTED",
            "currency":"USD",
            "open":"99","high":"102","low":"98","close":null,
            "adjustedClose":"100","volume":1
        }'::jsonb,
        TIMESTAMPTZ '2026-07-29 20:01:00+00',
        TIMESTAMPTZ '2026-07-29 20:04:00+00'
    ) OR analytics.validate_canonical_domain_data_v1(
        'DAILY_PRICE',
        'NORMALIZED_OBSERVATION',
        '{
            "sessionDate":"2026-07-29",
            "adjustmentMode":"TOTAL_RETURN_ADJUSTED",
            "currency":"USD",
            "open":{"providerRank":1},
            "high":"102","low":"98","close":"100",
            "adjustedClose":"100","volume":1
        }'::jsonb,
        TIMESTAMPTZ '2026-07-29 20:01:00+00',
        TIMESTAMPTZ '2026-07-29 20:04:00+00'
    ) OR analytics.validate_canonical_domain_data_v1(
        'FUNDAMENTAL',
        'NORMALIZED_OBSERVATION',
        '{
            "metricCode":"REVENUE","numericValue":"1","unit":"USD",
            "currency":"USD","periodStart":"2026-07-01",
            "periodEnd":"2026-06-30","fiscalPeriod":"Q2",
            "formType":"10-Q","accessionNumber":"invalid-period",
            "filedAt":"2026-07-29T20:00:00Z",
            "mappingVersion":"fundamental-v1"
        }'::jsonb,
        TIMESTAMPTZ '2026-07-29 20:01:00+00',
        TIMESTAMPTZ '2026-07-29 20:04:00+00'
    ) OR analytics.validate_canonical_domain_data_v1(
        'DAILY_PRICE',
        'NORMALIZED_OBSERVATION',
        '{
            "sessionDate":"2026-7-29",
            "adjustmentMode":"TOTAL_RETURN_ADJUSTED",
            "currency":"USD",
            "open":"99","high":"102","low":"98","close":"100",
            "adjustedClose":"100","volume":1
        }'::jsonb,
        TIMESTAMPTZ '2026-07-29 20:01:00+00',
        TIMESTAMPTZ '2026-07-29 20:04:00+00'
    ) OR analytics.validate_canonical_domain_data_v1(
        'FUNDAMENTAL',
        'NORMALIZED_OBSERVATION',
        '{
            "metricCode":"REVENUE","numericValue":"1","unit":"USD",
            "currency":"USD","periodStart":"2026-01-01",
            "periodEnd":"2026-06-30","fiscalPeriod":"Q2",
            "formType":"10-Q","accessionNumber":"invalid-filed-at",
            "filedAt":"2026-07-29","mappingVersion":"fundamental-v1"
        }'::jsonb,
        TIMESTAMPTZ '2026-07-29 20:01:00+00',
        TIMESTAMPTZ '2026-07-29 20:04:00+00'
    ) OR analytics.validate_canonical_domain_data_v1(
        'MARKET_BENCHMARK',
        'NORMALIZED_OBSERVATION',
        '{
            "benchmarkKind":"SECTOR","benchmarkCode":"XLK",
            "benchmarkSecurityId":"22000000-0000-4000-8000-000000000004",
            "sectorCode":"45","mappingVersion":"benchmark-v1",
            "effectiveFrom":"2026-01-01","effectiveTo":null
        }'::jsonb,
        TIMESTAMPTZ '2026-01-01 00:00:00+00',
        TIMESTAMPTZ '2026-01-01 00:00:00+00'
    ) THEN
        RAISE EXCEPTION 'Invalid canonical domain values were accepted';
    END IF;
END;
$$;

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.evidence_completed_session_v1 (
            id, calendar_id, calendar_version, mic, session_date, timezone,
            scheduled_open, scheduled_close, early_close, status,
            completed_at, session_content_hash
        ) VALUES (
            '22000000-0000-4000-8000-000000000071',
            'XNAS', 'XNAS-2026-v1', 'XNAS', DATE '2026-07-30',
            'UTC',
            TIMESTAMPTZ '2026-07-30 13:30:00+00',
            TIMESTAMPTZ '2026-07-30 20:00:00+00',
            FALSE, 'COMPLETED',
            TIMESTAMPTZ '2026-07-30 20:00:01+00',
            'sha256:' || repeat('7', 64)
        );
        RAISE EXCEPTION 'Completed-session calendar mismatch was accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO analytics.evidence_completed_session_v1 (
            id, calendar_id, calendar_version, mic, session_date, timezone,
            scheduled_open, scheduled_close, early_close, status,
            completed_at, session_content_hash
        ) VALUES (
            '22000000-0000-4000-8000-000000000074',
            'XNAS', 'XNAS-2026-v1', 'XNAS', DATE '2026-07-30',
            'America/New_York',
            TIMESTAMPTZ '2026-07-29 13:30:00+00',
            TIMESTAMPTZ '2026-07-29 20:00:00+00',
            FALSE, 'COMPLETED',
            TIMESTAMPTZ '2026-07-29 20:00:01+00',
            'sha256:' || repeat('4', 64)
        );
        RAISE EXCEPTION
            'Completed-session wrong local trading date was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM =
                'Completed-session wrong local trading date was accepted' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO analytics.evidence_ticker_assignment_v1 (
            ticker_assignment_id, listing_id, ticker, valid_from, valid_to,
            registry_version
        ) VALUES (
            '22000000-0000-4000-8000-000000000072',
            '22000000-0000-4000-8000-000000000004',
            'AAPL2', DATE '2026-06-01', DATE '2026-12-31',
            'security-identity-registry-v1.0.0'
        );
        RAISE EXCEPTION 'Overlapping ticker validity was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Overlapping ticker validity was accepted' THEN
                RAISE;
            END IF;
    END;
END;
$$;

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.evidence_selector_policy_v1 (
            id, selector_version, policy_version, domain, field_code,
            required_layer, domain_constraints, required_strictness_class,
            required_claim_class, required_normalization_version,
            policy_content_hash
        ) VALUES (
            '22000000-0000-4000-8000-000000000073',
            'deterministic-evidence-selector-v1.0.0',
            'nested-provider-rank-probe-v1',
            'DAILY_PRICE', 'CLOSE_PRICE', 'NORMALIZED_OBSERVATION',
            '{
                "sessionDate":"2026-07-29",
                "adjustmentMode":"TOTAL_RETURN_ADJUSTED",
                "currency":"USD","mic":"XNAS",
                "listingId":"22000000-0000-4000-8000-000000000004",
                "metadata":{"providerRank":1}
            }'::jsonb,
            'STRICT_IDENTITY_AND_CHRONOLOGY', 'CURRENT_ONLY',
            'canonical-equity-v1.0.0',
            'sha256:' || repeat('7', 64)
        );
        INSERT INTO analytics.evidence_selector_provider_priority_v1 (
            policy_id, priority_ordinal, provider_code
        ) VALUES (
            '22000000-0000-4000-8000-000000000073',
            1, 'provider-primary'
        );
        INSERT INTO analytics.evidence_selector_policy_seal_v1 (
            policy_id, provider_priority_count
        ) VALUES (
            '22000000-0000-4000-8000-000000000073', 1
        );
        RAISE EXCEPTION 'Nested provider rank leakage was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Nested provider rank leakage was accepted' THEN
                RAISE;
            END IF;
    END;
END;
$$;

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.canonical_evidence_parent_v1 (
            evidence_id, parent_ordinal, parent_evidence_id,
            parent_evidence_hash
        ) VALUES (
            '22000000-0000-4000-8000-000000000024',
            2, '22000000-0000-4000-8000-000000000021',
            'sha256:' || repeat('d', 64)
        );
        RAISE EXCEPTION 'Late derived parent was accepted after seal';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Late derived parent was accepted after seal' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO analytics.evidence_selector_provider_priority_v1 (
            policy_id, priority_ordinal, provider_code
        ) VALUES (
            '22000000-0000-4000-8000-000000000030',
            3, 'internal-derived'
        );
        RAISE EXCEPTION 'Late provider priority was accepted after seal';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Late provider priority was accepted after seal' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO analytics.evidence_selection_candidate_v1 (
            request_id, candidate_ordinal, evidence_id
        ) VALUES (
            '22000000-0000-4000-8000-000000000031',
            3, '22000000-0000-4000-8000-000000000023'
        );
        RAISE EXCEPTION 'Late selection candidate was accepted after seal';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Late selection candidate was accepted after seal' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO analytics.evidence_selection_rejection_v1 (
            request_id, rejection_ordinal, evidence_id, reason_code
        ) VALUES (
            '22000000-0000-4000-8000-000000000031',
            2, '22000000-0000-4000-8000-000000000020',
            'LATE_REJECTION'
        );
        RAISE EXCEPTION 'Late selection rejection was accepted after seal';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Late selection rejection was accepted after seal' THEN
                RAISE;
            END IF;
    END;
END;
$$;

COMMIT;
