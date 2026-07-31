\set ON_ERROR_STOP on

DO $$
DECLARE
    enrollment_count INTEGER;
    total_enrollment_count INTEGER;
    maturity_count INTEGER;
    source_fixture_count INTEGER;
    contract_definition TEXT;
    chronology_definition TEXT;
    contract_validated BOOLEAN;
    chronology_validated BOOLEAN;
    completeness_trigger_enabled TEXT;
BEGIN
    SELECT COUNT(*) INTO enrollment_count
    FROM analytics.forward_dqv_enrollment_v2
    WHERE id = '00000000-0000-4000-8000-000000000119'
      AND idempotency_key = 'v19-test-b'
      AND contract_version = 'FORWARD-DQV-ENROLLMENT-v2.1.0'
      AND canonical_request_hash =
          'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
      AND enrollment_content_hash =
          'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
      AND decision_as_of = TIMESTAMPTZ '2026-07-30 12:00:00+00'
      AND effective_at_completed_session_open =
          TIMESTAMPTZ '2026-07-30 13:00:00+00'
      AND sealed_at = TIMESTAMPTZ '2026-07-30 14:00:00+00';

    SELECT COUNT(*) INTO total_enrollment_count
    FROM analytics.forward_dqv_enrollment_v2;

    SELECT COUNT(*) INTO maturity_count
    FROM analytics.forward_dqv_maturity_schedule_v2
    WHERE enrollment_id = '00000000-0000-4000-8000-000000000119';

    SELECT COUNT(*) INTO source_fixture_count
    FROM analytics.forward_dqv_enrollment_v2 enrollment
    JOIN analytics.data_snapshot snapshot
      ON snapshot.id = enrollment.decision_data_snapshot_id
    JOIN analytics.universe_definition universe
      ON universe.version = enrollment.universe_version
    WHERE enrollment.id = '00000000-0000-4000-8000-000000000119'
      AND snapshot.manifest_hash = 'sha256:v19-refusal-snapshot'
      AND universe.configuration_hash = 'sha256:v19-refusal-universe';

    SELECT pg_get_constraintdef(oid), convalidated
    INTO contract_definition, contract_validated
    FROM pg_constraint
    WHERE conrelid = 'analytics.forward_dqv_enrollment_v2'::regclass
      AND conname = 'ck_forward_dqv_enrollment_contract';

    SELECT pg_get_constraintdef(oid), convalidated
    INTO chronology_definition, chronology_validated
    FROM pg_constraint
    WHERE conrelid = 'analytics.forward_dqv_enrollment_v2'::regclass
      AND conname = 'ck_forward_dqv_enrollment_chronology';

    SELECT tgenabled INTO completeness_trigger_enabled
    FROM pg_trigger
    WHERE tgrelid = 'analytics.forward_dqv_enrollment_v2'::regclass
      AND tgname = 'tr_forward_dqv_enrollment_complete';

    IF enrollment_count <> 1
       OR total_enrollment_count <> 1
       OR maturity_count <> 0
       OR source_fixture_count <> 1
       OR contract_definition
            NOT LIKE '%FORWARD-DQV-ENROLLMENT-v2.1.0%'
       OR contract_definition LIKE '%FORWARD-DQV-ENROLLMENT-v2.1.1%'
       OR chronology_definition
            NOT LIKE '%decision_as_of <= effective_at_completed_session_open%'
       OR chronology_definition
            NOT LIKE '%effective_at_completed_session_open <= sealed_at%'
       OR NOT contract_validated
       OR NOT chronology_validated
       OR completeness_trigger_enabled <> 'O' THEN
        RAISE EXCEPTION
            'V19 refusal changed the preexisting V18 enrollment, constraints, or trigger state';
    END IF;
END;
$$;
