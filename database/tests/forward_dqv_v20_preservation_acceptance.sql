\set ON_ERROR_STOP on

DO $$
DECLARE
    enrollment_count INTEGER;
    ledger_count INTEGER;
    family_count INTEGER;
    variant_count INTEGER;
    holding_count INTEGER;
    binding_count INTEGER;
    family_outcome_count INTEGER;
    family_hash_mismatch_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO enrollment_count
    FROM analytics.forward_dqv_enrollment_v2
    WHERE id = '20000000-0000-4000-8000-000000000002'
      AND enrollment_content_hash =
          'sha256:2000000000000000000000000000000000000000000000000000000000000011';

    SELECT COUNT(*) INTO ledger_count
    FROM analytics.forward_dqv_benchmark_ledger_v3
    WHERE id = '20000000-0000-4000-8000-000000000003'
      AND enrollment_id = '20000000-0000-4000-8000-000000000002'
      AND ledger_content_hash =
          'sha256:2000000000000000000000000000000000000000000000000000000000000019'
      AND persistence_content_hash =
          'sha256:2000000000000000000000000000000000000000000000000000000000000021';

    SELECT COUNT(*) INTO family_count
    FROM analytics.forward_dqv_benchmark_family_v3
    WHERE ledger_id = '20000000-0000-4000-8000-000000000003';

    SELECT COUNT(*) INTO family_hash_mismatch_count
    FROM analytics.forward_dqv_benchmark_family_v3
    WHERE ledger_id = '20000000-0000-4000-8000-000000000003'
      AND family_content_hash <> 'sha256:' || repeat('a', 64);

    SELECT COUNT(*) INTO variant_count
    FROM analytics.forward_dqv_benchmark_variant_v3
    WHERE ledger_id = '20000000-0000-4000-8000-000000000003';

    SELECT COUNT(*) INTO holding_count
    FROM analytics.forward_dqv_benchmark_holding_v3
    WHERE ledger_id = '20000000-0000-4000-8000-000000000003';

    SELECT COUNT(*) INTO binding_count
    FROM analytics.forward_dqv_security_benchmark_binding_v3
    WHERE ledger_id = '20000000-0000-4000-8000-000000000003';

    SELECT COUNT(*) INTO family_outcome_count
    FROM analytics.forward_dqv_benchmark_family_outcome_v3
    WHERE outcome_batch_id = '20000000-0000-4000-8000-000000000004';

    IF enrollment_count <> 1
       OR ledger_count <> 1
       OR family_count <> 6
       OR family_hash_mismatch_count <> 0
       OR variant_count <> 7
       OR holding_count <> 14
       OR binding_count <> 396
       OR family_outcome_count <> 6 THEN
        RAISE EXCEPTION
            'Preexisting V20 rows or hashes changed during V21 upgrade';
    END IF;
END;
$$;
