\set ON_ERROR_STOP on

BEGIN;

INSERT INTO analytics.evidence_raw_manifest_v1 (
    id, provider_code, provider_schema_version, source_record_id,
    source_revision, source_content_hash, storage_class,
    payload_stored_in_git, storage_reference, effective_at, available_at,
    retrieved_at, ingested_at
) VALUES (
    '22100000-0000-4000-8000-000000000074',
    'provider-primary', 'provider-schema-v3',
    'price-primary-20260729', 3,
    'sha256:' || repeat('9', 64),
    'PRIVATE_GIT_IGNORED', FALSE,
    'storage/private/provider-primary/price-primary-20260729-r3',
    TIMESTAMPTZ '2026-07-29 20:00:00+00',
    TIMESTAMPTZ '2026-07-29 20:01:00+00',
    TIMESTAMPTZ '2026-07-29 20:08:00+00',
    TIMESTAMPTZ '2026-07-29 20:09:00+00'
);

INSERT INTO analytics.canonical_evidence_v1
SELECT (
    jsonb_populate_record(
        NULL::analytics.canonical_evidence_v1,
        to_jsonb(base) || jsonb_build_object(
            'evidence_id', '22100000-0000-4000-8000-000000000075',
            'source_revision', 3,
            'source_content_hash', 'sha256:' || repeat('9', 64),
            'normalized_record_hash', 'sha256:' || repeat('a', 64),
            'retrieved_at', '2026-07-29T20:08:00Z',
            'ingested_at', '2026-07-29T20:09:00Z',
            'raw_manifest_id', '22100000-0000-4000-8000-000000000074',
            'supersedes_evidence_id',
                '22000000-0000-4000-8000-000000000054',
            'observation_reference', 'correction-revision-three'
        )
    )
).*
FROM analytics.canonical_evidence_v1 base
WHERE base.evidence_id = '22000000-0000-4000-8000-000000000054';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM analytics.canonical_evidence_v1
        WHERE evidence_id = '22100000-0000-4000-8000-000000000075'
          AND supersedes_evidence_id =
              '22000000-0000-4000-8000-000000000054'
          AND source_revision = 3
    ) THEN
        RAISE EXCEPTION 'Canonical correction chain was not preserved';
    END IF;

    BEGIN
        INSERT INTO analytics.evidence_raw_manifest_v1 (
            id, provider_code, provider_schema_version, source_record_id,
            source_revision, source_content_hash, storage_class,
            payload_stored_in_git, storage_reference, effective_at,
            available_at, retrieved_at, ingested_at
        ) VALUES (
            '22100000-0000-4000-8000-000000000076',
            'provider-primary', 'provider-schema-v3',
            'price-primary-20260729', 4,
            'sha256:' || repeat('c', 64),
            'PRIVATE_GIT_IGNORED', FALSE,
            'storage/private/provider-primary/price-primary-20260729-r4',
            TIMESTAMPTZ '2026-07-29 20:00:00+00',
            TIMESTAMPTZ '2026-07-29 20:01:00+00',
            TIMESTAMPTZ '2026-07-29 20:09:30+00',
            TIMESTAMPTZ '2026-07-29 20:10:00+00'
        );
        INSERT INTO analytics.canonical_evidence_v1
        SELECT (
            jsonb_populate_record(
                NULL::analytics.canonical_evidence_v1,
                to_jsonb(base) || jsonb_build_object(
                    'evidence_id',
                        '22100000-0000-4000-8000-000000000076',
                    'source_revision', 4,
                    'source_content_hash', 'sha256:' || repeat('c', 64),
                    'normalized_record_hash',
                        'sha256:' || repeat('d', 64),
                    'retrieved_at', '2026-07-29T20:09:30Z',
                    'ingested_at', '2026-07-29T20:10:00Z',
                    'raw_manifest_id',
                        '22100000-0000-4000-8000-000000000076',
                    'supersedes_evidence_id', NULL,
                    'observation_reference', 'missing-correction-link'
                )
            )
        ).*
        FROM analytics.canonical_evidence_v1 base
        WHERE base.evidence_id =
            '22100000-0000-4000-8000-000000000075';
        RAISE EXCEPTION 'Later revision without supersession was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM =
                'Later revision without supersession was accepted' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO analytics.evidence_raw_manifest_v1 (
    id, provider_code, provider_schema_version, source_record_id,
    source_revision, source_content_hash, storage_class,
    payload_stored_in_git, storage_reference, effective_at, available_at,
    retrieved_at, ingested_at
) VALUES
    (
        '22300000-0000-4000-8000-000000000001',
        'provider-secondary', 'provider-schema-v8',
        'deterministic-tie-a', 1, 'sha256:' || repeat('6', 64),
        'PRIVATE_GIT_IGNORED', FALSE,
        'storage/private/provider-secondary/deterministic-tie-a',
        TIMESTAMPTZ '2026-07-29 20:00:00+00',
        TIMESTAMPTZ '2026-07-29 20:01:00+00',
        TIMESTAMPTZ '2026-07-29 20:03:00+00',
        TIMESTAMPTZ '2026-07-29 20:04:00+00'
    ),
    (
        '22300000-0000-4000-8000-000000000002',
        'provider-secondary', 'provider-schema-v8',
        'deterministic-tie-b', 1, 'sha256:' || repeat('7', 64),
        'PRIVATE_GIT_IGNORED', FALSE,
        'storage/private/provider-secondary/deterministic-tie-b',
        TIMESTAMPTZ '2026-07-29 20:00:00+00',
        TIMESTAMPTZ '2026-07-29 20:01:00+00',
        TIMESTAMPTZ '2026-07-29 20:03:00+00',
        TIMESTAMPTZ '2026-07-29 20:04:00+00'
    );

INSERT INTO analytics.canonical_evidence_v1
SELECT (
    jsonb_populate_record(
        NULL::analytics.canonical_evidence_v1,
        to_jsonb(base) || jsonb_build_object(
            'evidence_id', fixture.evidence_id,
            'source_record_id', fixture.source_record_id,
            'source_revision', 1,
            'source_content_hash', fixture.source_content_hash,
            'normalized_record_hash', 'sha256:' || repeat('8', 64),
            'raw_manifest_id', fixture.raw_manifest_id,
            'supersedes_evidence_id', NULL,
            'observation_reference', fixture.observation_reference
        )
    )
).*
FROM analytics.canonical_evidence_v1 base
CROSS JOIN (
    VALUES
        (
            '22300000-0000-4000-8000-000000000001',
            'deterministic-tie-a',
            'sha256:' || repeat('6', 64),
            '22300000-0000-4000-8000-000000000001',
            'deterministic-tie-a'
        ),
        (
            '22300000-0000-4000-8000-000000000002',
            'deterministic-tie-b',
            'sha256:' || repeat('7', 64),
            '22300000-0000-4000-8000-000000000002',
            'deterministic-tie-b'
        )
) fixture(
    evidence_id, source_record_id, source_content_hash,
    raw_manifest_id, observation_reference
)
WHERE base.evidence_id = '22000000-0000-4000-8000-000000000021';

INSERT INTO analytics.evidence_selection_request_v1 (
    request_id, contract_version, policy_id, security_id, company_id,
    instrument_id, share_class_id, listing_id, ticker_assignment_id,
    completed_session_id, decision_cutoff, sealed_ingestion_cutoff,
    request_content_hash
)
SELECT
    '22300000-0000-4000-8000-000000000003',
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
    'sha256:' || repeat('4', 64)
FROM analytics.security security
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.evidence_selection_candidate_v1 (
    request_id, candidate_ordinal, evidence_id
) VALUES
    (
        '22300000-0000-4000-8000-000000000003',
        1, '22300000-0000-4000-8000-000000000002'
    ),
    (
        '22300000-0000-4000-8000-000000000003',
        2, '22300000-0000-4000-8000-000000000001'
    );

INSERT INTO analytics.evidence_selection_result_v1 (
    request_id, selector_version, state, reason_code,
    selected_evidence_id, result_content_hash
) VALUES (
    '22300000-0000-4000-8000-000000000003',
    'deterministic-evidence-selector-v1.0.0',
    'VALID', 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
    '22300000-0000-4000-8000-000000000001',
    analytics.evidence_selection_result_content_hash_v1(
        '22300000-0000-4000-8000-000000000003',
        'deterministic-evidence-selector-v1.0.0',
        'VALID', 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
        '22300000-0000-4000-8000-000000000001',
        ARRAY['22300000-0000-4000-8000-000000000002']::UUID[],
        ARRAY['LOWER_PROVIDER_PRIORITY_OR_REVISION']::VARCHAR[]
    )
);

INSERT INTO analytics.evidence_selection_rejection_v1 (
    request_id, rejection_ordinal, evidence_id, reason_code
) VALUES (
    '22300000-0000-4000-8000-000000000003',
    1, '22300000-0000-4000-8000-000000000002',
    'LOWER_PROVIDER_PRIORITY_OR_REVISION'
);

INSERT INTO analytics.evidence_selection_seal_v1 (
    request_id, candidate_count, rejection_count
) VALUES (
    '22300000-0000-4000-8000-000000000003', 2, 1
);

INSERT INTO analytics.evidence_raw_manifest_v1 (
    id, provider_code, provider_schema_version, source_record_id,
    source_revision, source_content_hash, storage_class,
    payload_stored_in_git, storage_reference, effective_at, available_at,
    retrieved_at, ingested_at
) VALUES
    (
        '22100000-0000-4000-8000-000000000084',
        'provider-primary', 'provider-schema-v3',
        'critical-conflict-stream', 1, 'sha256:' || repeat('2', 64),
        'PRIVATE_GIT_IGNORED', FALSE,
        'storage/private/provider-primary/critical-conflict',
        TIMESTAMPTZ '2026-07-29 20:00:00+00',
        TIMESTAMPTZ '2026-07-29 20:01:00+00',
        TIMESTAMPTZ '2026-07-29 20:03:00+00',
        TIMESTAMPTZ '2026-07-29 20:04:00+00'
    ),
    (
        '22100000-0000-4000-8000-000000000085',
        'provider-primary', 'provider-schema-v3',
        'dependent-conflict-stream', 1, 'sha256:' || repeat('4', 64),
        'PRIVATE_GIT_IGNORED', FALSE,
        'storage/private/provider-primary/dependent-conflict',
        TIMESTAMPTZ '2026-07-29 20:00:00+00',
        TIMESTAMPTZ '2026-07-29 20:01:00+00',
        TIMESTAMPTZ '2026-07-29 20:03:00+00',
        TIMESTAMPTZ '2026-07-29 20:04:00+00'
    );

INSERT INTO analytics.canonical_evidence_v1
SELECT (
    jsonb_populate_record(
        NULL::analytics.canonical_evidence_v1,
        to_jsonb(base) || jsonb_build_object(
            'evidence_id', '22100000-0000-4000-8000-000000000084',
            'source_record_id', 'critical-conflict-stream',
            'source_revision', 1,
            'source_content_hash', 'sha256:' || repeat('2', 64),
            'normalized_record_hash', 'sha256:' || repeat('3', 64),
            'raw_manifest_id', '22100000-0000-4000-8000-000000000084',
            'conflict_status', 'UNRESOLVED',
            'conflict_criticality', 'CRITICAL',
            'affected_factors', '["CLOSE_PRICE"]'::jsonb,
            'supersedes_evidence_id', NULL,
            'observation_reference', 'critical-conflict'
        )
    )
).*
FROM analytics.canonical_evidence_v1 base
WHERE base.evidence_id = '22000000-0000-4000-8000-000000000020';

INSERT INTO analytics.canonical_evidence_v1
SELECT (
    jsonb_populate_record(
        NULL::analytics.canonical_evidence_v1,
        to_jsonb(base) || jsonb_build_object(
            'evidence_id', '22100000-0000-4000-8000-000000000085',
            'source_record_id', 'dependent-conflict-stream',
            'source_revision', 1,
            'source_content_hash', 'sha256:' || repeat('4', 64),
            'normalized_record_hash', 'sha256:' || repeat('5', 64),
            'raw_manifest_id', '22100000-0000-4000-8000-000000000085',
            'conflict_status', 'UNRESOLVED',
            'conflict_criticality', 'NONCRITICAL',
            'affected_factors', '["CLOSE_PRICE"]'::jsonb,
            'supersedes_evidence_id', NULL,
            'observation_reference', 'dependent-conflict'
        )
    )
).*
FROM analytics.canonical_evidence_v1 base
WHERE base.evidence_id = '22000000-0000-4000-8000-000000000020';

INSERT INTO analytics.evidence_selection_request_v1 (
    request_id, contract_version, policy_id, security_id, company_id,
    instrument_id, share_class_id, listing_id, ticker_assignment_id,
    completed_session_id, decision_cutoff, sealed_ingestion_cutoff,
    request_content_hash
)
SELECT
    request_id, 'unified-market-data-evidence-foundation-v1.0.0',
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
    request_hash
FROM analytics.security security
CROSS JOIN (
    VALUES
        (
            '22100000-0000-4000-8000-000000000086'::UUID,
            'sha256:' || repeat('6', 64)
        ),
        (
            '22100000-0000-4000-8000-000000000087'::UUID,
            'sha256:' || repeat('7', 64)
        )
) requests(request_id, request_hash)
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.evidence_selection_candidate_v1 (
    request_id, candidate_ordinal, evidence_id
) VALUES
    (
        '22100000-0000-4000-8000-000000000086',
        1, '22100000-0000-4000-8000-000000000084'
    ),
    (
        '22100000-0000-4000-8000-000000000087',
        1, '22100000-0000-4000-8000-000000000085'
    );

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.evidence_selection_result_v1 (
            request_id, selector_version, state, reason_code,
            selected_evidence_id, result_content_hash
        ) VALUES (
            '22100000-0000-4000-8000-000000000086',
            'deterministic-evidence-selector-v1.0.0',
            'VALID', 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
            '22100000-0000-4000-8000-000000000084',
            'sha256:' || repeat('8', 64)
        );
        RAISE EXCEPTION 'Critical-conflict evidence was selected';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Critical-conflict evidence was selected' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO analytics.evidence_selection_result_v1 (
    request_id, selector_version, state, reason_code,
    selected_evidence_id, result_content_hash
) VALUES
    (
        '22100000-0000-4000-8000-000000000086',
        'deterministic-evidence-selector-v1.0.0',
        'INVALID', 'CRITICAL_EVIDENCE_CONFLICT', NULL,
        analytics.evidence_selection_result_content_hash_v1(
            '22100000-0000-4000-8000-000000000086',
            'deterministic-evidence-selector-v1.0.0',
            'INVALID', 'CRITICAL_EVIDENCE_CONFLICT', NULL,
            ARRAY['22100000-0000-4000-8000-000000000084']::UUID[],
            ARRAY['CRITICAL_EVIDENCE_CONFLICT']::VARCHAR[]
        )
    ),
    (
        '22100000-0000-4000-8000-000000000087',
        'deterministic-evidence-selector-v1.0.0',
        'MISSING', 'DEPENDENT_FIELD_CONFLICT', NULL,
        analytics.evidence_selection_result_content_hash_v1(
            '22100000-0000-4000-8000-000000000087',
            'deterministic-evidence-selector-v1.0.0',
            'MISSING', 'DEPENDENT_FIELD_CONFLICT', NULL,
            ARRAY['22100000-0000-4000-8000-000000000085']::UUID[],
            ARRAY['DEPENDENT_FIELD_CONFLICT']::VARCHAR[]
        )
    );

INSERT INTO analytics.evidence_selection_rejection_v1 (
    request_id, rejection_ordinal, evidence_id, reason_code
) VALUES
    (
        '22100000-0000-4000-8000-000000000086',
        1, '22100000-0000-4000-8000-000000000084',
        'CRITICAL_EVIDENCE_CONFLICT'
    ),
    (
        '22100000-0000-4000-8000-000000000087',
        1, '22100000-0000-4000-8000-000000000085',
        'DEPENDENT_FIELD_CONFLICT'
    );

INSERT INTO analytics.evidence_selection_seal_v1 (
    request_id, candidate_count, rejection_count
) VALUES
    (
        '22100000-0000-4000-8000-000000000086', 1, 1
    ),
    (
        '22100000-0000-4000-8000-000000000087', 1, 1
    );

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.evidence_raw_manifest_v1 (
            id, provider_code, provider_schema_version, source_record_id,
            source_revision, source_content_hash, storage_class,
            payload_stored_in_git, storage_reference, effective_at,
            available_at, retrieved_at, ingested_at
        ) VALUES (
            '22100000-0000-4000-8000-000000000092',
            'internal-derived', 'internal-derived-v1',
            'internal-provider-normalized-probe', 1,
            'sha256:' || repeat('a', 64),
            'PRIVATE_GIT_IGNORED', FALSE,
            'storage/private/internal-provider-normalized-probe',
            TIMESTAMPTZ '2026-07-29 20:00:00+00',
            TIMESTAMPTZ '2026-07-29 20:01:00+00',
            NULL,
            TIMESTAMPTZ '2026-07-29 20:02:00+00'
        );
        INSERT INTO analytics.canonical_evidence_v1
        SELECT (
            jsonb_populate_record(
                NULL::analytics.canonical_evidence_v1,
                to_jsonb(base) || jsonb_build_object(
                    'evidence_id',
                        '22100000-0000-4000-8000-000000000092',
                    'provider_code', 'internal-derived',
                    'provider_schema_version', 'internal-derived-v1',
                    'source_record_id',
                        'internal-provider-normalized-probe',
                    'source_revision', 1,
                    'source_content_hash',
                        'sha256:' || repeat('a', 64),
                    'normalized_record_hash',
                        'sha256:' || repeat('b', 64),
                    'raw_manifest_id',
                        '22100000-0000-4000-8000-000000000092',
                    'retrieved_at', NULL,
                    'ingested_at', '2026-07-29T20:02:00Z',
                    'supersedes_evidence_id', NULL,
                    'observation_reference',
                        'internal-provider-normalized-probe'
                )
            )
        ).*
        FROM analytics.canonical_evidence_v1 base
        WHERE base.evidence_id =
            '22000000-0000-4000-8000-000000000020';
        RAISE EXCEPTION 'Internal provider owned normalized evidence';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Internal provider owned normalized evidence' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO analytics.canonical_evidence_v1
        SELECT (
            jsonb_populate_record(
                NULL::analytics.canonical_evidence_v1,
                to_jsonb(base) || jsonb_build_object(
                    'evidence_id',
                        '22100000-0000-4000-8000-000000000094',
                    'provider_code', 'provider-primary',
                    'source_record_id', 'external-provider-derived-probe',
                    'normalized_record_hash',
                        'sha256:' || repeat('c', 64),
                    'source_content_hash',
                        'sha256:' || repeat('d', 64),
                    'derivation_output_hash',
                        'sha256:' || repeat('c', 64),
                    'observation_reference',
                        'external-provider-derived-probe'
                )
            )
        ).*
        FROM analytics.canonical_evidence_v1 base
        WHERE base.evidence_id =
            '22000000-0000-4000-8000-000000000024';
        RAISE EXCEPTION 'External provider owned derived evidence';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'External provider owned derived evidence' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO analytics.evidence_company_identity_v1 (
    company_id, registry_version
) VALUES (
    '22200000-0000-4000-8000-000000000001',
    'security-identity-registry-v1.0.0'
);

INSERT INTO analytics.evidence_instrument_identity_v1 (
    instrument_id, company_id, registry_version
) VALUES (
    '22200000-0000-4000-8000-000000000002',
    '22200000-0000-4000-8000-000000000001',
    'security-identity-registry-v1.0.0'
);

INSERT INTO analytics.evidence_share_class_identity_v1 (
    share_class_id, instrument_id, registry_version
) VALUES (
    '22200000-0000-4000-8000-000000000003',
    '22200000-0000-4000-8000-000000000002',
    'security-identity-registry-v1.0.0'
);

INSERT INTO analytics.evidence_listing_identity_v1 (
    listing_id, share_class_id, security_id, mic, currency, registry_version
)
SELECT
    '22200000-0000-4000-8000-000000000004',
    '22200000-0000-4000-8000-000000000003',
    public_id, 'XNAS', 'USD', 'security-identity-registry-v1.0.0'
FROM analytics.security
WHERE symbol = 'MSFT';

INSERT INTO analytics.evidence_ticker_assignment_v1 (
    ticker_assignment_id, listing_id, ticker, valid_from, registry_version
) VALUES (
    '22200000-0000-4000-8000-000000000005',
    '22200000-0000-4000-8000-000000000004',
    'MSFT', DATE '2026-01-01', 'security-identity-registry-v1.0.0'
);

INSERT INTO analytics.evidence_raw_manifest_v1 (
    id, provider_code, provider_schema_version, source_record_id,
    source_revision, source_content_hash, storage_class,
    payload_stored_in_git, storage_reference, effective_at, available_at,
    retrieved_at, ingested_at
) VALUES (
    '22200000-0000-4000-8000-000000000006',
    'provider-secondary', 'provider-schema-v8',
    'cross-security-same-hash', 1, 'sha256:' || repeat('e', 64),
    'PRIVATE_GIT_IGNORED', FALSE,
    'storage/private/provider-secondary/cross-security-same-hash',
    TIMESTAMPTZ '2026-07-29 20:00:00+00',
    TIMESTAMPTZ '2026-07-29 20:01:00+00',
    TIMESTAMPTZ '2026-07-29 20:03:00+00',
    TIMESTAMPTZ '2026-07-29 20:04:00+00'
);

INSERT INTO analytics.canonical_evidence_v1
SELECT (
    jsonb_populate_record(
        NULL::analytics.canonical_evidence_v1,
        to_jsonb(base) || jsonb_build_object(
            'evidence_id', '22200000-0000-4000-8000-000000000007',
            'security_id', security.public_id,
            'company_id', '22200000-0000-4000-8000-000000000001',
            'instrument_id', '22200000-0000-4000-8000-000000000002',
            'share_class_id', '22200000-0000-4000-8000-000000000003',
            'listing_id', '22200000-0000-4000-8000-000000000004',
            'ticker_assignment_id',
                '22200000-0000-4000-8000-000000000005',
            'ticker', 'MSFT',
            'provider_code', 'provider-secondary',
            'provider_schema_version', 'provider-schema-v8',
            'source_record_id', 'cross-security-same-hash',
            'source_revision', 1,
            'source_content_hash', 'sha256:' || repeat('e', 64),
            'normalized_record_hash', 'sha256:' || repeat('b', 64),
            'raw_manifest_id', '22200000-0000-4000-8000-000000000006',
            'supersedes_evidence_id', NULL,
            'observation_reference', 'cross-security-same-hash'
        )
    )
).*
FROM analytics.canonical_evidence_v1 base
CROSS JOIN analytics.security security
WHERE base.evidence_id = '22000000-0000-4000-8000-000000000020'
  AND security.symbol = 'MSFT';

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.canonical_evidence_v1
        SELECT (
            jsonb_populate_record(
                NULL::analytics.canonical_evidence_v1,
                to_jsonb(base) || jsonb_build_object(
                    'evidence_id',
                        '22200000-0000-4000-8000-000000000008',
                    'source_record_id', 'cross-security-parent-probe',
                    'normalized_record_hash',
                        'sha256:' || repeat('f', 64),
                    'source_content_hash',
                        'sha256:' || repeat('1', 64),
                    'derivation_output_hash',
                        'sha256:' || repeat('f', 64),
                    'observation_reference',
                        'cross-security-parent-probe'
                )
            )
        ).*
        FROM analytics.canonical_evidence_v1 base
        WHERE base.evidence_id =
            '22000000-0000-4000-8000-000000000024';
        INSERT INTO analytics.canonical_evidence_parent_v1 (
            evidence_id, parent_ordinal, parent_evidence_id,
            parent_evidence_hash
        ) VALUES (
            '22200000-0000-4000-8000-000000000008',
            1, '22200000-0000-4000-8000-000000000007',
            'sha256:' || repeat('b', 64)
        );
        RAISE EXCEPTION 'Cross-security same-hash parent was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM =
                'Cross-security same-hash parent was accepted' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO analytics.evidence_selection_request_v1 (
    request_id, contract_version, policy_id, security_id, company_id,
    instrument_id, share_class_id, listing_id, ticker_assignment_id,
    completed_session_id, decision_cutoff, sealed_ingestion_cutoff,
    request_content_hash
)
SELECT
    '22100000-0000-4000-8000-000000000077',
    'unified-market-data-evidence-foundation-v1.0.0',
    '22000000-0000-4000-8000-000000000030',
    security.public_id,
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000002',
    '22000000-0000-4000-8000-000000000003',
    '22000000-0000-4000-8000-000000000004',
    '22000000-0000-4000-8000-000000000005',
    '22000000-0000-4000-8000-000000000006',
    TIMESTAMPTZ '2026-07-29 20:10:00+00',
    TIMESTAMPTZ '2026-07-29 20:11:00+00',
    'sha256:' || repeat('b', 64)
FROM analytics.security security
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.evidence_selection_candidate_v1 (
    request_id, candidate_ordinal, evidence_id
) VALUES
    (
        '22100000-0000-4000-8000-000000000077',
        1, '22000000-0000-4000-8000-000000000020'
    ),
    (
        '22100000-0000-4000-8000-000000000077',
        2, '22100000-0000-4000-8000-000000000075'
    );

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.evidence_selection_result_v1 (
            request_id, selector_version, state, reason_code,
            selected_evidence_id, result_content_hash
        ) VALUES (
            '22100000-0000-4000-8000-000000000077',
            'deterministic-evidence-selector-v1.0.0',
            'VALID', 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
            '22000000-0000-4000-8000-000000000020',
            'sha256:' || repeat('c', 64)
        );
        RAISE EXCEPTION 'Older provider revision was selected';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Older provider revision was selected' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO analytics.evidence_selection_result_v1 (
    request_id, selector_version, state, reason_code,
    selected_evidence_id, result_content_hash
) VALUES (
    '22100000-0000-4000-8000-000000000077',
    'deterministic-evidence-selector-v1.0.0',
    'VALID', 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
    '22100000-0000-4000-8000-000000000075',
    analytics.evidence_selection_result_content_hash_v1(
        '22100000-0000-4000-8000-000000000077',
        'deterministic-evidence-selector-v1.0.0',
        'VALID', 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
        '22100000-0000-4000-8000-000000000075',
        ARRAY['22000000-0000-4000-8000-000000000020']::UUID[],
        ARRAY['LOWER_PROVIDER_PRIORITY_OR_REVISION']::VARCHAR[]
    )
);

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.evidence_selection_seal_v1 (
            request_id, candidate_count, rejection_count
        ) VALUES (
            '22100000-0000-4000-8000-000000000077', 2, 0
        );
        RAISE EXCEPTION 'Incomplete selector rejection set was sealed';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Incomplete selector rejection set was sealed' THEN
                RAISE;
            END IF;
    END;
END;
$$;

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.evidence_selection_rejection_v1 (
            request_id, rejection_ordinal, evidence_id, reason_code
        ) VALUES (
            '22100000-0000-4000-8000-000000000077',
            1, '22000000-0000-4000-8000-000000000020',
            'FRESHNESS_POLICY_EXPIRED'
        );
        RAISE EXCEPTION
            'Incorrect per-candidate rejection reason was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM =
                'Incorrect per-candidate rejection reason was accepted' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO analytics.evidence_selection_rejection_v1 (
    request_id, rejection_ordinal, evidence_id, reason_code
) VALUES (
    '22100000-0000-4000-8000-000000000077',
    1, '22000000-0000-4000-8000-000000000020',
    'LOWER_PROVIDER_PRIORITY_OR_REVISION'
);

INSERT INTO analytics.evidence_selection_seal_v1 (
    request_id, candidate_count, rejection_count
) VALUES (
    '22100000-0000-4000-8000-000000000077', 2, 1
);

INSERT INTO analytics.evidence_raw_manifest_v1 (
    id, provider_code, provider_schema_version, source_record_id,
    source_revision, source_content_hash, storage_class,
    payload_stored_in_git, storage_reference, effective_at, available_at,
    retrieved_at, ingested_at
) VALUES (
    '22100000-0000-4000-8000-000000000080',
    'provider-secondary', 'provider-schema-v8',
    'tolerance-stream', 1, 'sha256:' || repeat('e', 64),
    'PRIVATE_GIT_IGNORED', FALSE,
    'storage/private/provider-secondary/tolerance-stream',
    TIMESTAMPTZ '2026-07-29 20:00:00+00',
    TIMESTAMPTZ '2026-07-29 20:01:00+00',
    TIMESTAMPTZ '2026-07-29 20:03:00+00',
    TIMESTAMPTZ '2026-07-29 20:04:00+00'
);

INSERT INTO analytics.canonical_evidence_v1
SELECT (
    jsonb_populate_record(
        NULL::analytics.canonical_evidence_v1,
        to_jsonb(base) || jsonb_build_object(
            'evidence_id', '22100000-0000-4000-8000-000000000080',
            'source_record_id', 'tolerance-stream',
            'source_revision', 1,
            'source_content_hash', 'sha256:' || repeat('e', 64),
            'normalized_record_hash', 'sha256:' || repeat('f', 64),
            'raw_manifest_id', '22100000-0000-4000-8000-000000000080',
            'strictness_class', 'DOMAIN_TOLERANT_NUMERIC',
            'conflict_status', 'RESOLVED_WITHIN_TOLERANCE',
            'conflict_criticality', 'NONCRITICAL',
            'affected_factors', '["CLOSE_PRICE"]'::jsonb,
            'tolerance_policy_version', 'daily-close-tolerance-v1',
            'tolerance_field_code', 'CLOSE_PRICE',
            'tolerance_alignment', '{
                "semantic":true,"identity":true,"period":true,
                "unit":true,"currency":true,"adjustment":true,
                "chronology":true
            }'::jsonb,
            'supersedes_evidence_id', NULL,
            'observation_reference', 'tolerance-positive'
        )
    )
).*
FROM analytics.canonical_evidence_v1 base
WHERE base.evidence_id = '22000000-0000-4000-8000-000000000021';

INSERT INTO analytics.evidence_selector_policy_v1 (
    id, selector_version, policy_version, domain, field_code,
    required_layer, domain_constraints, required_strictness_class,
    required_claim_class, required_normalization_version,
    policy_content_hash
) VALUES (
    '22100000-0000-4000-8000-000000000081',
    'deterministic-evidence-selector-v1.0.0',
    'daily-close-tolerant-selection-v1',
    'DAILY_PRICE', 'CLOSE_PRICE', 'NORMALIZED_OBSERVATION',
    '{
        "sessionDate":"2026-07-29",
        "adjustmentMode":"TOTAL_RETURN_ADJUSTED",
        "currency":"USD","mic":"XNAS",
        "listingId":"22000000-0000-4000-8000-000000000004"
    }'::jsonb,
    'DOMAIN_TOLERANT_NUMERIC', 'CURRENT_ONLY',
    'canonical-equity-v1.0.0',
    'sha256:' || repeat('d', 64)
);

INSERT INTO analytics.evidence_selector_provider_priority_v1 (
    policy_id, priority_ordinal, provider_code
) VALUES (
    '22100000-0000-4000-8000-000000000081',
    1, 'provider-secondary'
);

INSERT INTO analytics.evidence_selector_policy_seal_v1 (
    policy_id, provider_priority_count
) VALUES (
    '22100000-0000-4000-8000-000000000081', 1
);

INSERT INTO analytics.evidence_selection_request_v1 (
    request_id, contract_version, policy_id, security_id, company_id,
    instrument_id, share_class_id, listing_id, ticker_assignment_id,
    completed_session_id, decision_cutoff, sealed_ingestion_cutoff,
    request_content_hash
)
SELECT
    '22100000-0000-4000-8000-000000000082',
    'unified-market-data-evidence-foundation-v1.0.0',
    '22100000-0000-4000-8000-000000000081',
    security.public_id,
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000002',
    '22000000-0000-4000-8000-000000000003',
    '22000000-0000-4000-8000-000000000004',
    '22000000-0000-4000-8000-000000000005',
    '22000000-0000-4000-8000-000000000006',
    TIMESTAMPTZ '2026-07-29 20:05:00+00',
    TIMESTAMPTZ '2026-07-29 20:07:00+00',
    'sha256:' || repeat('e', 64)
FROM analytics.security security
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.evidence_selection_candidate_v1 (
    request_id, candidate_ordinal, evidence_id
) VALUES (
    '22100000-0000-4000-8000-000000000082',
    1, '22100000-0000-4000-8000-000000000080'
);

INSERT INTO analytics.evidence_selection_result_v1 (
    request_id, selector_version, state, reason_code,
    selected_evidence_id, result_content_hash
) VALUES (
    '22100000-0000-4000-8000-000000000082',
    'deterministic-evidence-selector-v1.0.0',
    'VALID', 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
    '22100000-0000-4000-8000-000000000080',
    analytics.evidence_selection_result_content_hash_v1(
        '22100000-0000-4000-8000-000000000082',
        'deterministic-evidence-selector-v1.0.0',
        'VALID', 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
        '22100000-0000-4000-8000-000000000080',
        ARRAY[]::UUID[],
        ARRAY[]::VARCHAR[]
    )
);

INSERT INTO analytics.evidence_selection_seal_v1 (
    request_id, candidate_count, rejection_count
) VALUES (
    '22100000-0000-4000-8000-000000000082', 1, 0
);

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.canonical_evidence_v1
        SELECT (
            jsonb_populate_record(
                NULL::analytics.canonical_evidence_v1,
                to_jsonb(base) || jsonb_build_object(
                    'evidence_id',
                        '22100000-0000-4000-8000-000000000083',
                    'normalized_record_hash',
                        'sha256:' || repeat('1', 64),
                    'conflict_criticality', 'CRITICAL',
                    'observation_reference', 'resolved-critical-invalid'
                )
            )
        ).*
        FROM analytics.canonical_evidence_v1 base
        WHERE base.evidence_id =
            '22100000-0000-4000-8000-000000000080';
        RAISE EXCEPTION 'Resolved critical tolerance was accepted';
    EXCEPTION
        WHEN check_violation THEN NULL;
    END;
END;
$$;

DO $$
DECLARE
    child_function TEXT;
    seal_function TEXT;
BEGIN
    SELECT pg_get_functiondef(
        'analytics.validate_evidence_selection_child_insert_v1()'::regprocedure
    ) INTO child_function;
    SELECT pg_get_functiondef(
        'analytics.validate_evidence_selection_seal_v1()'::regprocedure
    ) INTO seal_function;
    IF child_function NOT LIKE '%pg_advisory_xact_lock%'
       OR seal_function NOT LIKE '%pg_advisory_xact_lock%' THEN
        RAISE EXCEPTION 'Selection child/seal concurrency lock is missing';
    END IF;
END;
$$;

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.canonical_evidence_v1
        SELECT (
            jsonb_populate_record(
                NULL::analytics.canonical_evidence_v1,
                to_jsonb(base) || jsonb_build_object(
                    'evidence_id',
                        '22100000-0000-4000-8000-000000000090',
                    'source_record_id', 'derived-invalid-parent-domain',
                    'normalized_record_hash',
                        'sha256:' || repeat('2', 64),
                    'source_content_hash',
                        'sha256:' || repeat('3', 64),
                    'derivation_output_hash',
                        'sha256:' || repeat('2', 64),
                    'observation_reference',
                        'derived-invalid-parent-domain'
                )
            )
        ).*
        FROM analytics.canonical_evidence_v1 base
        WHERE base.evidence_id =
            '22000000-0000-4000-8000-000000000024';
        INSERT INTO analytics.canonical_evidence_parent_v1 (
            evidence_id, parent_ordinal, parent_evidence_id,
            parent_evidence_hash
        ) VALUES (
            '22100000-0000-4000-8000-000000000090',
            1, '22000000-0000-4000-8000-000000000022',
            'sha256:' || repeat('4', 64)
        );
        RAISE EXCEPTION 'Unauthorized derived parent domain was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Unauthorized derived parent domain was accepted' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO analytics.canonical_evidence_v1
        SELECT (
            jsonb_populate_record(
                NULL::analytics.canonical_evidence_v1,
                to_jsonb(base) || jsonb_build_object(
                    'evidence_id',
                        '22100000-0000-4000-8000-000000000091',
                    'source_record_id', 'derived-future-parent',
                    'normalized_record_hash',
                        'sha256:' || repeat('5', 64),
                    'source_content_hash',
                        'sha256:' || repeat('6', 64),
                    'derivation_output_hash',
                        'sha256:' || repeat('5', 64),
                    'available_at', '2026-07-29T20:08:00Z',
                    'ingested_at', '2026-07-29T20:08:00Z',
                    'observation_reference', 'derived-future-parent'
                )
            )
        ).*
        FROM analytics.canonical_evidence_v1 base
        WHERE base.evidence_id =
            '22000000-0000-4000-8000-000000000024';
        INSERT INTO analytics.canonical_evidence_parent_v1 (
            evidence_id, parent_ordinal, parent_evidence_id,
            parent_evidence_hash
        ) VALUES (
            '22100000-0000-4000-8000-000000000091',
            1, '22100000-0000-4000-8000-000000000075',
            'sha256:' || repeat('a', 64)
        );
        RAISE EXCEPTION 'Future derived parent was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Future derived parent was accepted' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO analytics.evidence_raw_manifest_v1 (
    id, provider_code, provider_schema_version, source_record_id,
    source_revision, source_content_hash, storage_class,
    payload_stored_in_git, storage_reference, effective_at, available_at,
    retrieved_at, ingested_at
) VALUES (
    '22300000-0000-4000-8000-000000000100',
    'provider-primary', 'provider-schema-v3',
    'adjusted-close-null', 1, 'sha256:' || repeat('1', 64),
    'PRIVATE_GIT_IGNORED', FALSE,
    'storage/private/provider-primary/adjusted-close-null',
    TIMESTAMPTZ '2026-07-29 20:00:00+00',
    TIMESTAMPTZ '2026-07-29 20:01:00+00',
    TIMESTAMPTZ '2026-07-29 20:03:00+00',
    TIMESTAMPTZ '2026-07-29 20:04:00+00'
);

INSERT INTO analytics.canonical_evidence_v1
SELECT (
    jsonb_populate_record(
        NULL::analytics.canonical_evidence_v1,
        to_jsonb(base) || jsonb_build_object(
            'evidence_id', '22300000-0000-4000-8000-000000000101',
            'source_record_id', 'adjusted-close-null',
            'source_revision', 1,
            'source_content_hash', 'sha256:' || repeat('1', 64),
            'normalized_record_hash', 'sha256:' || repeat('2', 64),
            'raw_manifest_id', '22300000-0000-4000-8000-000000000100',
            'supersedes_evidence_id', NULL,
            'canonical_data', jsonb_set(
                base.canonical_data,
                '{adjustedClose}',
                'null'::jsonb
            ),
            'observation_reference', 'adjusted-close-null'
        )
    )
).*
FROM analytics.canonical_evidence_v1 base
WHERE base.evidence_id = '22000000-0000-4000-8000-000000000020';

INSERT INTO analytics.evidence_selector_policy_v1 (
    id, selector_version, policy_version, domain, field_code,
    required_layer, domain_constraints, required_strictness_class,
    required_claim_class, required_normalization_version,
    policy_content_hash
) VALUES (
    '22300000-0000-4000-8000-000000000102',
    'deterministic-evidence-selector-v1.0.0',
    'adjusted-close-null-selection-v1',
    'DAILY_PRICE', 'ADJUSTED_CLOSE', 'NORMALIZED_OBSERVATION',
    '{
        "sessionDate":"2026-07-29",
        "adjustmentMode":"TOTAL_RETURN_ADJUSTED",
        "currency":"USD",
        "mic":"XNAS",
        "listingId":"22000000-0000-4000-8000-000000000004"
    }'::jsonb,
    'STRICT_IDENTITY_AND_CHRONOLOGY', 'CURRENT_ONLY',
    'canonical-equity-v1.0.0',
    'sha256:' || repeat('3', 64)
);

INSERT INTO analytics.evidence_selector_provider_priority_v1 (
    policy_id, priority_ordinal, provider_code
) VALUES (
    '22300000-0000-4000-8000-000000000102', 1, 'provider-primary'
);

INSERT INTO analytics.evidence_selector_policy_seal_v1 (
    policy_id, provider_priority_count
) VALUES ('22300000-0000-4000-8000-000000000102', 1);

INSERT INTO analytics.evidence_selection_request_v1 (
    request_id, contract_version, policy_id, security_id, company_id,
    instrument_id, share_class_id, listing_id, ticker_assignment_id,
    completed_session_id, decision_cutoff, sealed_ingestion_cutoff,
    request_content_hash
)
SELECT
    '22300000-0000-4000-8000-000000000103',
    'unified-market-data-evidence-foundation-v1.0.0',
    '22300000-0000-4000-8000-000000000102',
    security.public_id,
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000002',
    '22000000-0000-4000-8000-000000000003',
    '22000000-0000-4000-8000-000000000004',
    '22000000-0000-4000-8000-000000000005',
    '22000000-0000-4000-8000-000000000006',
    TIMESTAMPTZ '2026-07-29 20:05:00+00',
    TIMESTAMPTZ '2026-07-29 20:07:00+00',
    'sha256:' || repeat('4', 63) || '1'
FROM analytics.security security
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.evidence_selection_candidate_v1 (
    request_id, candidate_ordinal, evidence_id
) VALUES
    (
        '22300000-0000-4000-8000-000000000103',
        1, '22300000-0000-4000-8000-000000000101'
    ),
    (
        '22300000-0000-4000-8000-000000000103',
        2, '22000000-0000-4000-8000-000000000022'
    );

INSERT INTO analytics.evidence_selection_result_v1 (
    request_id, selector_version, state, reason_code,
    selected_evidence_id, result_content_hash
) VALUES (
    '22300000-0000-4000-8000-000000000103',
    'deterministic-evidence-selector-v1.0.0',
    'MISSING', 'DOMAIN_CONSTRAINT_MISMATCH', NULL,
    analytics.evidence_selection_result_content_hash_v1(
        '22300000-0000-4000-8000-000000000103',
        'deterministic-evidence-selector-v1.0.0',
        'MISSING', 'DOMAIN_CONSTRAINT_MISMATCH', NULL,
        ARRAY[
            '22300000-0000-4000-8000-000000000101',
            '22000000-0000-4000-8000-000000000022'
        ]::UUID[],
        ARRAY[
            'DOMAIN_CONSTRAINT_MISMATCH',
            'NO_CONTRACT_ELIGIBLE_EVIDENCE'
        ]::VARCHAR[]
    )
);

INSERT INTO analytics.evidence_selection_rejection_v1 (
    request_id, rejection_ordinal, evidence_id, reason_code
) VALUES
    (
        '22300000-0000-4000-8000-000000000103',
        1, '22300000-0000-4000-8000-000000000101',
        'DOMAIN_CONSTRAINT_MISMATCH'
    ),
    (
        '22300000-0000-4000-8000-000000000103',
        2, '22000000-0000-4000-8000-000000000022',
        'NO_CONTRACT_ELIGIBLE_EVIDENCE'
    );

INSERT INTO analytics.evidence_selection_seal_v1 (
    request_id, candidate_count, rejection_count
) VALUES ('22300000-0000-4000-8000-000000000103', 2, 2);

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.canonical_evidence_v1
        SELECT (
            jsonb_populate_record(
                NULL::analytics.canonical_evidence_v1,
                to_jsonb(base) || jsonb_build_object(
                    'evidence_id',
                        '22300000-0000-4000-8000-000000000110',
                    'source_record_id', 'invalid-liquidity-cardinality',
                    'source_content_hash', 'sha256:' || repeat('6', 64),
                    'normalized_record_hash', 'sha256:' || repeat('7', 64),
                    'derivation_output_hash', 'sha256:' || repeat('7', 64),
                    'canonical_data', jsonb_set(
                        jsonb_set(
                            base.canonical_data,
                            '{windowCompletedSessions}',
                            '20'::jsonb
                        ),
                        '{validObservationCount}',
                        '20'::jsonb
                    ),
                    'observation_reference',
                        'invalid-liquidity-cardinality'
                )
            )
        ).*
        FROM analytics.canonical_evidence_v1 base
        WHERE base.evidence_id =
            '22000000-0000-4000-8000-000000000024';
        INSERT INTO analytics.canonical_evidence_parent_v1 (
            evidence_id, parent_ordinal, parent_evidence_id,
            parent_evidence_hash
        ) VALUES (
            '22300000-0000-4000-8000-000000000110',
            1, '22000000-0000-4000-8000-000000000020',
            'sha256:' || repeat('b', 64)
        );
        INSERT INTO analytics.canonical_evidence_parent_seal_v1 (
            evidence_id, parent_count
        ) VALUES ('22300000-0000-4000-8000-000000000110', 1);
        RAISE EXCEPTION
            'One-parent twenty-observation liquidity was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM =
                'One-parent twenty-observation liquidity was accepted' THEN
                RAISE;
            END IF;
    END;
END;
$$;

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.model_applicability_routing_v1 (
            routing_id, company_id, classification_evidence_id,
            model_family, company_type, applicability,
            specialized_model_code, routing_version, routing_revision,
            effective_at, routing_content_hash, supersedes_routing_id
        ) VALUES (
            '22300000-0000-4000-8000-000000000120',
            '22000000-0000-4000-8000-000000000001',
            '22000000-0000-4000-8000-000000000022',
            'FUNDAMENTAL_VALUE', 'MATURE_OPERATING_COMPANY',
            'SPECIALIZED_MODEL_REQUIRED', 'UNSAFE_GENERIC',
            'fundamental-applicability-routing-v1.0.0', 2,
            TIMESTAMPTZ '2026-01-01 01:04:00+00',
            analytics.model_applicability_routing_content_hash_v1(
                '22300000-0000-4000-8000-000000000120',
                '22000000-0000-4000-8000-000000000001',
                '22000000-0000-4000-8000-000000000022',
                'FUNDAMENTAL_VALUE', 'MATURE_OPERATING_COMPANY',
                'SPECIALIZED_MODEL_REQUIRED', 'UNSAFE_GENERIC',
                'fundamental-applicability-routing-v1.0.0', 2,
                TIMESTAMPTZ '2026-01-01 01:04:00+00',
                '22000000-0000-4000-8000-000000000040'
            ),
            '22000000-0000-4000-8000-000000000040'
        );
        RAISE EXCEPTION 'Wrong company-type applicability mapping was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM =
                'Wrong company-type applicability mapping was accepted' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO analytics.model_applicability_routing_v1 (
            routing_id, company_id, classification_evidence_id,
            model_family, company_type, applicability,
            specialized_model_code, routing_version, routing_revision,
            effective_at, routing_content_hash, supersedes_routing_id
        ) VALUES (
            '22300000-0000-4000-8000-000000000121',
            '22000000-0000-4000-8000-000000000001',
            '22000000-0000-4000-8000-000000000022',
            'FUNDAMENTAL_VALUE', 'MATURE_OPERATING_COMPANY',
            'APPLICABLE', NULL,
            'fundamental-applicability-routing-v1.0.0', 2,
            TIMESTAMPTZ '2026-01-01 01:04:00+00',
            'sha256:' || repeat('0', 64),
            '22000000-0000-4000-8000-000000000040'
        );
        RAISE EXCEPTION 'Arbitrary applicability hash was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Arbitrary applicability hash was accepted' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO analytics.model_applicability_routing_v1 (
            routing_id, company_id, classification_evidence_id,
            model_family, company_type, applicability,
            specialized_model_code, routing_version, routing_revision,
            effective_at, routing_content_hash, supersedes_routing_id
        ) VALUES (
            '22300000-0000-4000-8000-000000000122',
            '22000000-0000-4000-8000-000000000001',
            '22000000-0000-4000-8000-000000000022',
            'FUNDAMENTAL_VALUE', 'MATURE_OPERATING_COMPANY',
            'APPLICABLE', NULL,
            'fundamental-applicability-routing-v1.0.0', 2,
            TIMESTAMPTZ '2026-01-01 01:04:00+00',
            analytics.model_applicability_routing_content_hash_v1(
                '22300000-0000-4000-8000-000000000122',
                '22000000-0000-4000-8000-000000000001',
                '22000000-0000-4000-8000-000000000022',
                'FUNDAMENTAL_VALUE', 'MATURE_OPERATING_COMPANY',
                'APPLICABLE', NULL,
                'fundamental-applicability-routing-v1.0.0', 2,
                TIMESTAMPTZ '2026-01-01 01:04:00+00', NULL
            ),
            NULL
        );
        RAISE EXCEPTION 'Missing applicability successor was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM = 'Missing applicability successor was accepted' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO analytics.model_applicability_routing_v1 (
    routing_id, company_id, classification_evidence_id, model_family,
    company_type, applicability, specialized_model_code, routing_version,
    routing_revision, effective_at, routing_content_hash,
    supersedes_routing_id
) VALUES (
    '22300000-0000-4000-8000-000000000123',
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000022',
    'FUNDAMENTAL_VALUE', 'MATURE_OPERATING_COMPANY', 'APPLICABLE', NULL,
    'fundamental-applicability-routing-v1.0.0', 2,
    TIMESTAMPTZ '2026-01-01 01:04:00+00',
    analytics.model_applicability_routing_content_hash_v1(
        '22300000-0000-4000-8000-000000000123',
        '22000000-0000-4000-8000-000000000001',
        '22000000-0000-4000-8000-000000000022',
        'FUNDAMENTAL_VALUE', 'MATURE_OPERATING_COMPANY', 'APPLICABLE',
        NULL, 'fundamental-applicability-routing-v1.0.0', 2,
        TIMESTAMPTZ '2026-01-01 01:04:00+00',
        '22000000-0000-4000-8000-000000000040'
    ),
    '22000000-0000-4000-8000-000000000040'
);

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.model_applicability_routing_v1 (
            routing_id, company_id, classification_evidence_id,
            model_family, company_type, applicability,
            specialized_model_code, routing_version, routing_revision,
            effective_at, routing_content_hash, supersedes_routing_id
        ) VALUES (
            '22300000-0000-4000-8000-000000000124',
            '22000000-0000-4000-8000-000000000001',
            '22000000-0000-4000-8000-000000000022',
            'FUNDAMENTAL_VALUE', 'MATURE_OPERATING_COMPANY',
            'APPLICABLE', NULL,
            'fundamental-applicability-routing-v1.0.0', 3,
            TIMESTAMPTZ '2026-01-01 01:05:00+00',
            analytics.model_applicability_routing_content_hash_v1(
                '22300000-0000-4000-8000-000000000124',
                '22000000-0000-4000-8000-000000000001',
                '22000000-0000-4000-8000-000000000022',
                'FUNDAMENTAL_VALUE', 'MATURE_OPERATING_COMPANY',
                'APPLICABLE', NULL,
                'fundamental-applicability-routing-v1.0.0', 3,
                TIMESTAMPTZ '2026-01-01 01:05:00+00',
                '22000000-0000-4000-8000-000000000040'
            ),
            '22000000-0000-4000-8000-000000000040'
        );
        RAISE EXCEPTION 'Bypassed latest applicability route was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM =
                'Bypassed latest applicability route was accepted' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO analytics.model_applicability_routing_v1 (
            routing_id, company_id, classification_evidence_id,
            model_family, company_type, applicability,
            specialized_model_code, routing_version, routing_revision,
            effective_at, routing_content_hash, supersedes_routing_id
        ) VALUES (
            '22300000-0000-4000-8000-000000000125',
            '22000000-0000-4000-8000-000000000001',
            '22000000-0000-4000-8000-000000000022',
            'FUNDAMENTAL_VALUE', 'MATURE_OPERATING_COMPANY',
            'APPLICABLE', NULL,
            'fundamental-applicability-routing-v1.0.0', 3,
            TIMESTAMPTZ '2026-01-01 01:04:00+00',
            analytics.model_applicability_routing_content_hash_v1(
                '22300000-0000-4000-8000-000000000125',
                '22000000-0000-4000-8000-000000000001',
                '22000000-0000-4000-8000-000000000022',
                'FUNDAMENTAL_VALUE', 'MATURE_OPERATING_COMPANY',
                'APPLICABLE', NULL,
                'fundamental-applicability-routing-v1.0.0', 3,
                TIMESTAMPTZ '2026-01-01 01:04:00+00',
                '22300000-0000-4000-8000-000000000123'
            ),
            '22300000-0000-4000-8000-000000000123'
        );
        RAISE EXCEPTION
            'Non-monotonic applicability chronology was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM =
                'Non-monotonic applicability chronology was accepted' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO analytics.evidence_raw_manifest_v1 (
    id, provider_code, provider_schema_version, source_record_id,
    source_revision, source_content_hash, storage_class,
    payload_stored_in_git, storage_reference, effective_at, available_at,
    retrieved_at, ingested_at
) VALUES (
    '22400000-0000-4000-8000-000000000000',
    'provider-secondary', 'provider-schema-v8',
    'malformed-affected-factors', 1,
    'sha256:' || repeat('a', 63) || '1',
    'PRIVATE_GIT_IGNORED', FALSE,
    'storage/private/provider-secondary/malformed-affected-factors',
    TIMESTAMPTZ '2026-07-29 20:00:00+00',
    TIMESTAMPTZ '2026-07-29 20:01:00+00',
    TIMESTAMPTZ '2026-07-29 20:03:00+00',
    TIMESTAMPTZ '2026-07-29 20:04:00+00'
);

DO $$
DECLARE
    invalid_factors JSONB;
BEGIN
    FOREACH invalid_factors IN ARRAY ARRAY[
        '[null]'::jsonb,
        '[""]'::jsonb,
        '1'::jsonb,
        '[1]'::jsonb,
        '[{"CLOSE_PRICE":true}]'::jsonb
    ]
    LOOP
        BEGIN
            INSERT INTO analytics.canonical_evidence_v1
            SELECT (
                jsonb_populate_record(
                    NULL::analytics.canonical_evidence_v1,
                    to_jsonb(base) || jsonb_build_object(
                        'evidence_id',
                            '22400000-0000-4000-8000-000000000001',
                        'source_record_id', 'malformed-affected-factors',
                        'source_revision', 1,
                        'source_content_hash',
                            'sha256:' || repeat('a', 63) || '1',
                        'normalized_record_hash',
                            'sha256:' || repeat('b', 63) || '1',
                        'raw_manifest_id',
                            '22400000-0000-4000-8000-000000000000',
                        'conflict_status', 'UNRESOLVED',
                        'conflict_criticality', 'NONCRITICAL',
                        'affected_factors', invalid_factors,
                        'supersedes_evidence_id', NULL,
                        'observation_reference',
                            'malformed-affected-factors'
                    )
                )
            ).*
            FROM analytics.canonical_evidence_v1 base
            WHERE base.evidence_id =
                '22000000-0000-4000-8000-000000000021';
            RAISE EXCEPTION
                'Malformed affectedFactors array was accepted';
        EXCEPTION
            WHEN check_violation THEN
                NULL;
        END;
    END LOOP;
END;
$$;

INSERT INTO analytics.canonical_evidence_v1
SELECT (
    jsonb_populate_record(
        NULL::analytics.canonical_evidence_v1,
        to_jsonb(base) || jsonb_build_object(
            'evidence_id', fixture.evidence_id,
            'state', fixture.state,
            'reason_code', fixture.reason_code,
            'source_record_id', fixture.source_record_id,
            'source_revision', 1,
            'source_content_hash', fixture.source_content_hash,
            'normalized_record_hash', fixture.normalized_record_hash,
            'derivation_output_hash', fixture.normalized_record_hash,
            'canonical_data', NULL,
            'supersedes_evidence_id', NULL,
            'observation_reference', fixture.observation_reference
        )
    )
).*
FROM analytics.canonical_evidence_v1 base
CROSS JOIN (
    VALUES
        (
            '22400000-0000-4000-8000-000000000010',
            'MISSING', 'MISSING_LIQUIDITY_EVIDENCE',
            'nonvalid-liquidity-missing',
            'sha256:' || repeat('a', 63) || '0',
            'sha256:' || repeat('b', 63) || '0',
            'nonvalid-liquidity-missing'
        ),
        (
            '22400000-0000-4000-8000-000000000011',
            'STALE', 'STALE_LIQUIDITY_EVIDENCE',
            'nonvalid-liquidity-stale',
            'sha256:' || repeat('a', 63) || '1',
            'sha256:' || repeat('b', 63) || '1',
            'nonvalid-liquidity-stale'
        ),
        (
            '22400000-0000-4000-8000-000000000012',
            'INVALID', 'INVALID_LIQUIDITY_EVIDENCE',
            'nonvalid-liquidity-invalid',
            'sha256:' || repeat('a', 63) || '2',
            'sha256:' || repeat('b', 63) || '2',
            'nonvalid-liquidity-invalid'
        ),
        (
            '22400000-0000-4000-8000-000000000013',
            'NOT_APPLICABLE', 'NOT_APPLICABLE_LIQUIDITY_EVIDENCE',
            'nonvalid-liquidity-not-applicable',
            'sha256:' || repeat('a', 63) || '3',
            'sha256:' || repeat('b', 63) || '3',
            'nonvalid-liquidity-not-applicable'
        ),
        (
            '22400000-0000-4000-8000-000000000014',
            'EXCLUDED', 'EXCLUDED_LIQUIDITY_EVIDENCE',
            'nonvalid-liquidity-excluded',
            'sha256:' || repeat('a', 63) || '4',
            'sha256:' || repeat('b', 63) || '4',
            'nonvalid-liquidity-excluded'
        )
) fixture(
    evidence_id, state, reason_code, source_record_id,
    source_content_hash, normalized_record_hash, observation_reference
)
WHERE base.evidence_id = '22000000-0000-4000-8000-000000000024';

DO $$
DECLARE
    nonvalid_count INTEGER;
    parent_count INTEGER;
    seal_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO nonvalid_count
    FROM analytics.canonical_evidence_v1
    WHERE evidence_id IN (
        '22400000-0000-4000-8000-000000000010',
        '22400000-0000-4000-8000-000000000011',
        '22400000-0000-4000-8000-000000000012',
        '22400000-0000-4000-8000-000000000013',
        '22400000-0000-4000-8000-000000000014'
    )
      AND canonical_data IS NULL;
    SELECT COUNT(*) INTO parent_count
    FROM analytics.canonical_evidence_parent_v1
    WHERE evidence_id IN (
        '22400000-0000-4000-8000-000000000010',
        '22400000-0000-4000-8000-000000000011',
        '22400000-0000-4000-8000-000000000012',
        '22400000-0000-4000-8000-000000000013',
        '22400000-0000-4000-8000-000000000014'
    );
    SELECT COUNT(*) INTO seal_count
    FROM analytics.canonical_evidence_parent_seal_v1
    WHERE evidence_id IN (
        '22400000-0000-4000-8000-000000000010',
        '22400000-0000-4000-8000-000000000011',
        '22400000-0000-4000-8000-000000000012',
        '22400000-0000-4000-8000-000000000013',
        '22400000-0000-4000-8000-000000000014'
    );
    IF nonvalid_count <> 5 OR parent_count <> 0 OR seal_count <> 0 THEN
        RAISE EXCEPTION
            'Non-VALID derived liquidity zero-parent contract was not preserved';
    END IF;

    BEGIN
        INSERT INTO analytics.canonical_evidence_parent_v1 (
            evidence_id, parent_ordinal, parent_evidence_id,
            parent_evidence_hash
        ) VALUES (
            '22400000-0000-4000-8000-000000000010',
            1, '22000000-0000-4000-8000-000000000020',
            'sha256:' || repeat('b', 64)
        );
        RAISE EXCEPTION
            'Non-VALID derived liquidity accepted a parent';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM =
                'Non-VALID derived liquidity accepted a parent' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO analytics.canonical_evidence_parent_seal_v1 (
            evidence_id, parent_count
        ) VALUES (
            '22400000-0000-4000-8000-000000000010', 1
        );
        RAISE EXCEPTION
            'Non-VALID derived liquidity accepted a parent seal';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM =
                'Non-VALID derived liquidity accepted a parent seal' THEN
                RAISE;
            END IF;
    END;
END;
$$;

INSERT INTO analytics.evidence_raw_manifest_v1 (
    id, provider_code, provider_schema_version, source_record_id,
    source_revision, source_content_hash, storage_class,
    payload_stored_in_git, storage_reference, effective_at, available_at,
    retrieved_at, ingested_at
) VALUES (
    '22400000-0000-4000-8000-000000000020',
    'provider-secondary', 'provider-schema-v8',
    'nonvalid-tolerance-precedence', 1,
    'sha256:' || repeat('c', 63) || '1',
    'PRIVATE_GIT_IGNORED', FALSE,
    'storage/private/provider-secondary/nonvalid-tolerance-precedence',
    TIMESTAMPTZ '2026-07-29 20:00:00+00',
    TIMESTAMPTZ '2026-07-29 20:01:00+00',
    TIMESTAMPTZ '2026-07-29 20:03:00+00',
    TIMESTAMPTZ '2026-07-29 20:04:00+00'
);

INSERT INTO analytics.canonical_evidence_v1
SELECT (
    jsonb_populate_record(
        NULL::analytics.canonical_evidence_v1,
        to_jsonb(base) || jsonb_build_object(
            'evidence_id', '22400000-0000-4000-8000-000000000021',
            'state', 'MISSING',
            'reason_code', 'NO_PROVIDER_OBSERVATION',
            'source_record_id', 'nonvalid-tolerance-precedence',
            'source_revision', 1,
            'source_content_hash', 'sha256:' || repeat('c', 63) || '1',
            'normalized_record_hash',
                'sha256:' || repeat('d', 63) || '1',
            'raw_manifest_id', '22400000-0000-4000-8000-000000000020',
            'strictness_class', 'DOMAIN_TOLERANT_NUMERIC',
            'conflict_status', 'NONE',
            'conflict_criticality', 'NONE',
            'affected_factors', '[]'::jsonb,
            'tolerance_policy_version', 'daily-volume-tolerance-v1',
            'tolerance_field_code', 'VOLUME',
            'tolerance_alignment', '{
                "semantic":true,"identity":true,"period":true,
                "unit":true,"currency":true,"adjustment":true,
                "chronology":true
            }'::jsonb,
            'canonical_data', NULL,
            'supersedes_evidence_id', NULL,
            'observation_reference', 'nonvalid-tolerance-precedence'
        )
    )
).*
FROM analytics.canonical_evidence_v1 base
WHERE base.evidence_id = '22000000-0000-4000-8000-000000000021';

INSERT INTO analytics.evidence_selection_request_v1 (
    request_id, contract_version, policy_id, security_id, company_id,
    instrument_id, share_class_id, listing_id, ticker_assignment_id,
    completed_session_id, decision_cutoff, sealed_ingestion_cutoff,
    request_content_hash
)
SELECT
    '22400000-0000-4000-8000-000000000022',
    'unified-market-data-evidence-foundation-v1.0.0',
    '22100000-0000-4000-8000-000000000081',
    security.public_id,
    '22000000-0000-4000-8000-000000000001',
    '22000000-0000-4000-8000-000000000002',
    '22000000-0000-4000-8000-000000000003',
    '22000000-0000-4000-8000-000000000004',
    '22000000-0000-4000-8000-000000000005',
    '22000000-0000-4000-8000-000000000006',
    TIMESTAMPTZ '2026-07-29 20:05:00+00',
    TIMESTAMPTZ '2026-07-29 20:07:00+00',
    'sha256:' || repeat('6', 63) || '1'
FROM analytics.security security
WHERE security.symbol = 'AAPL';

INSERT INTO analytics.evidence_selection_candidate_v1 (
    request_id, candidate_ordinal, evidence_id
) VALUES (
    '22400000-0000-4000-8000-000000000022',
    1, '22400000-0000-4000-8000-000000000021'
);

INSERT INTO analytics.evidence_selection_result_v1 (
    request_id, selector_version, state, reason_code,
    selected_evidence_id, result_content_hash
) VALUES (
    '22400000-0000-4000-8000-000000000022',
    'deterministic-evidence-selector-v1.0.0',
    'MISSING', 'NO_PROVIDER_OBSERVATION', NULL,
    analytics.evidence_selection_result_content_hash_v1(
        '22400000-0000-4000-8000-000000000022',
        'deterministic-evidence-selector-v1.0.0',
        'MISSING', 'NO_PROVIDER_OBSERVATION', NULL,
        ARRAY['22400000-0000-4000-8000-000000000021']::UUID[],
        ARRAY['NO_PROVIDER_OBSERVATION']::VARCHAR[]
    )
);

INSERT INTO analytics.evidence_selection_rejection_v1 (
    request_id, rejection_ordinal, evidence_id, reason_code
) VALUES (
    '22400000-0000-4000-8000-000000000022',
    1, '22400000-0000-4000-8000-000000000021',
    'NO_PROVIDER_OBSERVATION'
);

INSERT INTO analytics.evidence_selection_seal_v1 (
    request_id, candidate_count, rejection_count
) VALUES (
    '22400000-0000-4000-8000-000000000022', 1, 1
);

DO $$
DECLARE
    first_request_hash VARCHAR(71);
    second_request_hash VARCHAR(71);
    changed_rejection_hash VARCHAR(71);
BEGIN
    first_request_hash :=
        analytics.evidence_selection_result_content_hash_v1(
            '22300000-0000-4000-8000-000000000003',
            'deterministic-evidence-selector-v1.0.0',
            'MISSING', 'NO_OBSERVATION_CANDIDATES', NULL,
            ARRAY[]::UUID[],
            ARRAY[]::VARCHAR[]
        );
    second_request_hash :=
        analytics.evidence_selection_result_content_hash_v1(
            '22100000-0000-4000-8000-000000000082',
            'deterministic-evidence-selector-v1.0.0',
            'MISSING', 'NO_OBSERVATION_CANDIDATES', NULL,
            ARRAY[]::UUID[],
            ARRAY[]::VARCHAR[]
        );
    changed_rejection_hash :=
        analytics.evidence_selection_result_content_hash_v1(
            '22300000-0000-4000-8000-000000000003',
            'deterministic-evidence-selector-v1.0.0',
            'MISSING', 'NO_OBSERVATION_CANDIDATES', NULL,
            ARRAY['22300000-0000-4000-8000-000000000002']::UUID[],
            ARRAY['DIFFERENT_DETERMINISTIC_REASON']::VARCHAR[]
        );
    IF first_request_hash = second_request_hash
       OR first_request_hash = changed_rejection_hash THEN
        RAISE EXCEPTION
            'Selector result hash is not request and rejection bound';
    END IF;
END;
$$;

DO $$
BEGIN
    BEGIN
        INSERT INTO analytics.evidence_selection_request_v1 (
            request_id, contract_version, policy_id, security_id, company_id,
            instrument_id, share_class_id, listing_id, ticker_assignment_id,
            completed_session_id, decision_cutoff, sealed_ingestion_cutoff,
            request_content_hash
        )
        SELECT
            '22500000-0000-4000-8000-000000000001',
            contract_version, policy_id, security_id, company_id,
            instrument_id, share_class_id, listing_id, ticker_assignment_id,
            completed_session_id, decision_cutoff, sealed_ingestion_cutoff,
            'sha256:' || repeat('a', 62) || '91'
        FROM analytics.evidence_selection_request_v1
        WHERE request_id = '22000000-0000-4000-8000-000000000031';

        INSERT INTO analytics.evidence_selection_candidate_v1 (
            request_id, candidate_ordinal, evidence_id
        ) VALUES
            (
                '22500000-0000-4000-8000-000000000001',
                1, '22000000-0000-4000-8000-000000000020'
            ),
            (
                '22500000-0000-4000-8000-000000000001',
                2, '22000000-0000-4000-8000-000000000021'
            );

        INSERT INTO analytics.evidence_selection_result_v1 (
            request_id, selector_version, state, reason_code,
            selected_evidence_id, result_content_hash
        ) VALUES (
            '22500000-0000-4000-8000-000000000001',
            'deterministic-evidence-selector-v1.0.0',
            'VALID', 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
            '22000000-0000-4000-8000-000000000020',
            analytics.evidence_selection_result_content_hash_v1(
                '22500000-0000-4000-8000-000000000001',
                'deterministic-evidence-selector-v1.0.0',
                'VALID', 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK',
                '22000000-0000-4000-8000-000000000020',
                ARRAY[
                    '22000000-0000-4000-8000-000000000021'
                ]::UUID[],
                ARRAY['DIFFERENT_DETERMINISTIC_REASON']::VARCHAR[]
            )
        );

        INSERT INTO analytics.evidence_selection_rejection_v1 (
            request_id, rejection_ordinal, evidence_id, reason_code
        ) VALUES (
            '22500000-0000-4000-8000-000000000001',
            1, '22000000-0000-4000-8000-000000000021',
            'LOWER_PROVIDER_PRIORITY_OR_REVISION'
        );

        INSERT INTO analytics.evidence_selection_seal_v1 (
            request_id, candidate_count, rejection_count
        ) VALUES (
            '22500000-0000-4000-8000-000000000001', 2, 1
        );
        RAISE EXCEPTION
            'Changed selector rejection-map hash was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM =
                'Changed selector rejection-map hash was accepted' THEN
                RAISE;
            ELSIF SQLERRM <>
                'Persisted selector result content hash is invalid' THEN
                RAISE;
            END IF;
    END;
END;
$$;

COMMIT;
