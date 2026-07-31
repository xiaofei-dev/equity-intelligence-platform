\set ON_ERROR_STOP on

DO $$
DECLARE
    enrollment_count INTEGER;
    schedule_count INTEGER;
    schedule_hash_mismatch_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO enrollment_count
    FROM analytics.forward_dqv_enrollment_v2
    WHERE id = '19000000-0000-4000-8000-000000000002'
      AND idempotency_key = 'v19-test-a'
      AND contract_version = 'FORWARD-DQV-ENROLLMENT-v2.1.1'
      AND canonical_request_hash = 'sha256:' || repeat('3', 64)
      AND decision_manifest_content_hash = 'sha256:' || repeat('5', 64)
      AND enrollment_content_hash = 'sha256:' || repeat('b', 64)
      AND decision_as_of = TIMESTAMPTZ '2026-07-30 11:00:00+00'
      AND sealed_at = TIMESTAMPTZ '2026-07-30 11:30:00+00'
      AND effective_at_completed_session_open =
          TIMESTAMPTZ '2026-07-30 12:00:00+00';

    SELECT COUNT(*) INTO schedule_count
    FROM analytics.forward_dqv_maturity_schedule_v2
    WHERE enrollment_id = '19000000-0000-4000-8000-000000000002';

    SELECT COUNT(*) INTO schedule_hash_mismatch_count
    FROM analytics.forward_dqv_maturity_schedule_v2
    WHERE enrollment_id = '19000000-0000-4000-8000-000000000002'
      AND schedule_content_hash <>
          'sha256:' || lpad(completed_sessions::text, 64, '0');

    IF enrollment_count <> 1
       OR schedule_count <> 5
       OR schedule_hash_mismatch_count <> 0 THEN
        RAISE EXCEPTION
            'Preexisting V19 enrollment or its hashes changed during V20/V21 upgrade';
    END IF;
END;
$$;
