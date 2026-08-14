DO $$
BEGIN
  IF to_regclass('analytics.fv_cq_forward_enrollment_v1') IS NULL
     OR to_regclass('analytics.fv_cq_forward_decision_session_v1') IS NULL
     OR to_regclass('analytics.fv_cq_forward_planned_entry_v1') IS NULL
     OR to_regclass('analytics.fv_cq_forward_member_v1') IS NULL
     OR to_regclass('analytics.fv_cq_forward_member_evidence_v1') IS NULL
     OR to_regclass('analytics.fv_cq_forward_normalized_parent_v1') IS NULL
     OR to_regclass('analytics.fv_cq_forward_member_reason_v1') IS NULL
     OR to_regclass('analytics.fv_cq_forward_maturity_v1') IS NULL
     OR to_regclass('analytics.fv_cq_forward_enrollment_seal_v1') IS NULL THEN
    RAISE EXCEPTION 'V24 company-quality Forward enrollment tables are incomplete';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles
                 WHERE rolname='analytics_fv_cq_forward_writer_v1') THEN
    RAISE EXCEPTION 'V24 semantic writer role is missing';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles
                 WHERE rolname='analytics_fv_cq_normalized_parent_writer_v1') THEN
    RAISE EXCEPTION 'V24 normalized-parent writer role is missing';
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='analytics'
               AND table_name='fv_cq_forward_normalized_parent_v1'
               AND column_name='listing_mic') THEN
    RAISE EXCEPTION 'V24 normalized parent must not duplicate listing MIC';
  END IF;
  IF has_table_privilege('analytics_writer',
       'analytics.fv_cq_forward_enrollment_v1','INSERT') THEN
    RAISE EXCEPTION 'generic analytics_writer must not insert V24 enrollments';
  END IF;
  IF NOT has_table_privilege('analytics_fv_cq_forward_writer_v1',
       'analytics.fv_cq_forward_enrollment_v1','INSERT')
     OR NOT has_table_privilege('analytics_fv_cq_forward_writer_v1',
       'analytics.canonical_evidence_v1','SELECT')
     OR NOT has_table_privilege('analytics_fv_cq_forward_writer_v1',
       'analytics.evidence_raw_manifest_v1','SELECT')
     OR has_table_privilege('analytics_fv_cq_forward_writer_v1',
       'analytics.evidence_raw_manifest_v1','INSERT,UPDATE,DELETE,TRUNCATE')
     OR NOT has_table_privilege('analytics_fv_cq_forward_writer_v1',
       'analytics.fv_cq_forward_parent_role_v1','SELECT')
     OR NOT has_table_privilege('analytics_fv_cq_forward_writer_v1',
       'analytics.fv_cq_forward_decision_session_v1','INSERT')
     OR NOT has_table_privilege('analytics_fv_cq_forward_writer_v1',
       'analytics.fv_cq_forward_planned_entry_v1','INSERT')
     OR has_table_privilege('analytics_fv_cq_forward_writer_v1',
       'analytics.fv_cq_forward_normalized_parent_v1','INSERT')
     OR has_table_privilege('analytics_writer',
       'analytics.fv_cq_forward_parent_role_v1','UPDATE')
     OR has_table_privilege('analytics_writer',
       'analytics.fv_cq_forward_enrollment_v1','INSERT') THEN
    RAISE EXCEPTION 'V24 semantic writer privileges are incomplete';
  END IF;
  IF NOT has_table_privilege('analytics_fv_cq_normalized_parent_writer_v1',
       'analytics.fv_cq_forward_normalized_parent_v1','INSERT')
     OR has_table_privilege('analytics_fv_cq_normalized_parent_writer_v1',
       'analytics.fv_cq_forward_normalized_parent_v1','UPDATE')
     OR has_table_privilege('analytics_fv_cq_forward_writer_v1',
       'analytics.fv_cq_forward_normalized_parent_v1','INSERT') THEN
    RAISE EXCEPTION 'V24 normalized-parent writer separation is incomplete';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger
    WHERE tgrelid='analytics.fv_cq_forward_enrollment_seal_v1'::regclass
      AND tgname='fv_cq_forward_seal_immutable_v1') THEN
    RAISE EXCEPTION 'V24 seal immutability trigger is missing';
  END IF;
  IF (SELECT count(*) FROM pg_trigger trigger_row
      JOIN pg_proc function_row ON function_row.oid=trigger_row.tgfoid
      WHERE trigger_row.tgname IN (
        'fv_cq_forward_decision_session_complete_v1',
        'fv_cq_forward_planned_entry_complete_v1',
        'fv_cq_forward_member_complete_v1',
        'fv_cq_forward_evidence_complete_v1',
        'fv_cq_forward_reason_complete_v1',
        'fv_cq_forward_maturity_complete_v1',
        'fv_cq_forward_seal_complete_v1')
        AND trigger_row.tgdeferrable AND trigger_row.tginitdeferred
        AND function_row.proname='validate_fv_cq_forward_enrollment_v1')<>7 THEN
    RAISE EXCEPTION 'V24 child aggregate revalidation trigger coverage is incomplete';
  END IF;
  IF EXISTS (SELECT 1 FROM analytics.fv_cq_forward_enrollment_v1) THEN
    RAISE EXCEPTION 'V24 migration must not seed or backdate a real enrollment';
  END IF;
  IF pg_get_functiondef('analytics.validate_fv_cq_forward_enrollment_v1()'::regprocedure)
       NOT LIKE '%policy.domain_constraints->>''metricCode''=link.canonical_field_code%'
     OR pg_get_functiondef('analytics.validate_fv_cq_forward_enrollment_v1()'::regprocedure)
       NOT LIKE '%seal.seal_content_hash IS DISTINCT FROM computed_seal_content_hash%'
     OR pg_get_functiondef('analytics.validate_fv_cq_forward_enrollment_v1()'::regprocedure)
       NOT LIKE '%seal_marker.creator_xid8=pg_current_xact_id()%'
     OR pg_get_functiondef('analytics.validate_fv_cq_forward_enrollment_v1()'::regprocedure)
       LIKE '%validated_enrollment_ids%'
     OR NOT EXISTS (SELECT 1 FROM information_schema.columns
       WHERE table_schema='analytics'
         AND table_name='fv_cq_forward_enrollment_seal_v1'
         AND column_name='creator_xid8' AND udt_name='xid8')
     OR NOT EXISTS (SELECT 1 FROM pg_trigger
       WHERE tgrelid='analytics.fv_cq_forward_enrollment_seal_v1'::regclass
         AND tgname='fv_cq_forward_seal_creator_xid8_v1'
         AND tgfoid='analytics.set_fv_cq_forward_seal_creator_xid8_v1()'::regprocedure)
     OR pg_get_functiondef('analytics.validate_fv_cq_forward_enrollment_v1()'::regprocedure)
       NOT LIKE '%bad_row_hash_count<>0%'
     OR pg_get_functiondef('analytics.fv_cq_forward_expected_score_v1(uuid,integer)'::regprocedure)
       NOT LIKE '%fv_cq_context28_v1%'
     OR pg_get_functiondef('analytics.fv_cq_forward_expected_score_v1(uuid,integer)'::regprocedure)
       NOT LIKE '%revenue_periods[1:4] IS DISTINCT FROM operating_periods[1:4]%'
     OR pg_get_functiondef('analytics.fv_cq_forward_expected_score_v1(uuid,integer)'::regprocedure)
       NOT LIKE '%parent_period_end<=inferred_start%'
      OR pg_get_functiondef('analytics.fv_cq_forward_expected_score_v1(uuid,integer)'::regprocedure)
        NOT LIKE '%unnest(capex_rows)%'
      OR analytics.fv_cq_forward_hash_atom_v1(chr(9))
      OR analytics.fv_cq_forward_hash_atom_v1(chr(10))
      OR analytics.fv_cq_forward_hash_atom_v1(
           ' '||chr(9)||chr(10)||chr(13)||chr(12)||chr(11))
      OR NOT analytics.fv_cq_forward_hash_atom_v1(chr(160))
     OR analytics.fv_cq_context28_v1(0.12501750000000000000001::NUMERIC)
       <> 0.12501750000000000000001::NUMERIC
     OR analytics.fv_cq_div_context28_v1(
          12501750000000000000001::NUMERIC,100000000000000000000000::NUMERIC)
       <> 0.12501750000000000000001::NUMERIC
     OR analytics.fv_cq_forward_date_text_v1(DATE '2026-07-31') <> '2026-07-31'
     OR analytics.fv_cq_forward_date_text_v1(DATE '0001-01-01') <> '0001-01-01'
     OR analytics.fv_cq_forward_date_text_v1(DATE '9999-12-31') <> '9999-12-31'
     OR analytics.fv_cq_forward_utc_text_v1(
          TIMESTAMPTZ '0001-01-01 00:00:00+00') <> '0001-01-01 00:00:00+00'
     OR analytics.fv_cq_forward_utc_text_v1(
          TIMESTAMPTZ '9999-12-31 23:59:59+00') <> '9999-12-31 23:59:59+00'
     OR pg_get_functiondef('analytics.validate_fv_cq_forward_enrollment_v1()'::regprocedure)
       LIKE '%parent_period_end::TEXT%'
     OR analytics.fv_round_half_even_v1(greatest(0::NUMERIC,least(100::NUMERIC,
          ((0.12501750000000000000001::NUMERIC+0.05)/0.35)*100)),2) <> 50.01
     OR (SELECT sum(required_count)
         FROM analytics.fv_cq_forward_parent_role_v1) <> 63
     OR NOT EXISTS (SELECT 1 FROM analytics.fv_cq_forward_parent_role_v1
         WHERE operand_code='STOCKHOLDERS_EQUITY'
           AND canonical_field_code='TOTAL_EQUITY'
           AND provenance_kind='V22_SELECTED_EVIDENCE')
     OR NOT EXISTS (SELECT 1 FROM analytics.fv_cq_forward_parent_role_v1
         WHERE operand_code='INCOME_TAX'
           AND provenance_kind='V24_PROVIDER_NORMALIZED_PARENT') THEN
    RAISE EXCEPTION 'V24 semantic replay checks are incomplete';
  END IF;
END $$;

DO $$
DECLARE rejected BOOLEAN;
BEGIN
  rejected := false;
  BEGIN
    PERFORM analytics.fv_cq_forward_date_text_v1(DATE '0001-01-01 BC');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM LIKE '%DATE_OUTSIDE_TYPED_RANGE%' THEN rejected := true; ELSE RAISE; END IF;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'V24 BC date range refusal is missing'; END IF;

  rejected := false;
  BEGIN
    PERFORM analytics.fv_cq_forward_date_text_v1(DATE '10000-01-01');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM LIKE '%DATE_OUTSIDE_TYPED_RANGE%' THEN rejected := true; ELSE RAISE; END IF;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'V24 year-10000 date range refusal is missing'; END IF;

  rejected := false;
  BEGIN
    PERFORM analytics.fv_cq_forward_utc_text_v1(
      TIMESTAMPTZ '0001-01-01 00:00:00 BC UTC');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM LIKE '%TIMESTAMP_OUTSIDE_TYPED_RANGE%' THEN rejected := true; ELSE RAISE; END IF;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'V24 BC timestamp range refusal is missing'; END IF;

  rejected := false;
  BEGIN
    PERFORM analytics.fv_cq_forward_utc_text_v1(
      TIMESTAMPTZ '10000-01-01 00:00:00+00');
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM LIKE '%TIMESTAMP_OUTSIDE_TYPED_RANGE%' THEN rejected := true; ELSE RAISE; END IF;
  END;
  IF NOT rejected THEN RAISE EXCEPTION 'V24 year-10000 timestamp refusal is missing'; END IF;
END $$;
