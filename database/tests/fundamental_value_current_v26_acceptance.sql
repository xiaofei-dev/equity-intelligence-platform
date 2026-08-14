\set ON_ERROR_STOP on

DO $$
DECLARE
  producer_count INTEGER;
  trigger_count INTEGER;
BEGIN
  IF to_regclass('analytics.fv_current_assessment_v1') IS NULL
     OR to_regclass('analytics.fv_current_assessment_authority_v1') IS NULL
     OR to_regclass('analytics.fv_current_assessment_source_v1') IS NULL
     OR to_regclass('analytics.fv_current_assessment_operand_v1') IS NULL
     OR to_regclass('analytics.fv_current_assessment_operand_parent_v1') IS NULL
     OR to_regclass('analytics.fv_current_assessment_operand_reason_v1') IS NULL
     OR to_regclass('analytics.fv_current_assessment_seal_v1') IS NULL
     OR to_regclass('analytics.fv_current_producer_contract_v1') IS NULL THEN
    RAISE EXCEPTION 'V26 current Fundamental Value persistence graph is incomplete';
  END IF;
  IF (SELECT count(*) FROM analytics.fv_current_assessment_authority_v1) <> 0 THEN
    RAISE EXCEPTION 'V26 must not seed current-assessment authority';
  END IF;
  SELECT count(*) INTO producer_count
  FROM analytics.fv_current_producer_contract_v1;
  IF producer_count <> 34 THEN
    RAISE EXCEPTION 'V26 producer registry cardinality drift';
  END IF;
  IF (SELECT array_agg(operand_ordinal ORDER BY operand_ordinal)
      FROM analytics.fv_current_producer_contract_v1)
      <> ARRAY(SELECT generate_series(1,34)) THEN
    RAISE EXCEPTION 'V26 producer registry ordinals drift';
  END IF;
  SELECT count(*) INTO trigger_count
  FROM pg_trigger
  WHERE NOT tgisinternal
    AND tgrelid IN (
      'analytics.fv_current_assessment_v1'::regclass,
      'analytics.fv_current_assessment_source_v1'::regclass,
      'analytics.fv_current_assessment_operand_v1'::regclass,
      'analytics.fv_current_assessment_operand_parent_v1'::regclass,
      'analytics.fv_current_assessment_operand_reason_v1'::regclass,
      'analytics.fv_current_assessment_seal_v1'::regclass
    )
    AND pg_get_triggerdef(oid) LIKE '%DEFERRABLE INITIALLY DEFERRED%';
  IF trigger_count <> 6 THEN
    RAISE EXCEPTION 'V26 deferred aggregate validation coverage drift';
  END IF;
END;
$$;

DO $$
BEGIN
  BEGIN
    UPDATE analytics.fv_current_assessment_authority_v1
    SET recorded_at=TIMESTAMPTZ '2001-01-01 00:00:00+00';
    IF FOUND THEN RAISE EXCEPTION 'V26 authority update unexpectedly succeeded'; END IF;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%immutable%' AND
       SQLERRM NOT LIKE '%unexpectedly succeeded%' THEN RAISE; END IF;
  END;
  BEGIN
    DELETE FROM analytics.fv_current_assessment_authority_v1;
    IF FOUND THEN RAISE EXCEPTION 'V26 authority delete unexpectedly succeeded'; END IF;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%immutable%' AND
       SQLERRM NOT LIKE '%unexpectedly succeeded%' THEN RAISE; END IF;
  END;
  BEGIN
    UPDATE analytics.fv_current_producer_contract_v1
    SET governance='ALTERED' WHERE operand_ordinal=1;
    RAISE EXCEPTION 'V26 producer update unexpectedly succeeded';
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE '%immutable%' THEN RAISE; END IF;
  END;
  IF has_table_privilege(
       'analytics_fv_current_assessment_writer_v1',
       'analytics.fv_current_producer_contract_v1','INSERT')
     OR has_table_privilege(
       'analytics_fv_current_assessment_writer_v1',
       'analytics.fv_current_assessment_v1','UPDATE')
     OR has_table_privilege(
       'analytics_fv_current_assessment_writer_v1',
       'analytics.fv_current_assessment_v1','DELETE')
     OR NOT has_table_privilege(
       'analytics_fv_current_assessment_writer_v1',
       'analytics.fv_current_assessment_v1','INSERT') THEN
    RAISE EXCEPTION 'V26 semantic writer privileges drift';
  END IF;
  IF NOT has_schema_privilege(
       'analytics_fv_current_assessment_writer_v1','analytics','USAGE') THEN
    RAISE EXCEPTION 'V26 semantic writer schema usage drift';
  END IF;
  IF has_table_privilege(
       'analytics_fv_current_assessment_writer_v1',
       'analytics.fv_current_assessment_authority_v1','INSERT')
     OR NOT has_table_privilege(
       'analytics_fv_current_assessment_writer_v1',
       'analytics.fv_current_assessment_authority_v1','SELECT')
     OR NOT has_table_privilege(
       'analytics_fv_current_assessment_authority_writer_v1',
       'analytics.fv_current_assessment_authority_v1','INSERT')
     OR has_table_privilege(
       'analytics_fv_current_assessment_authority_writer_v1',
       'analytics.fv_current_assessment_authority_v1','UPDATE')
     OR has_table_privilege(
       'analytics_fv_current_assessment_authority_writer_v1',
       'analytics.fv_current_assessment_authority_v1','DELETE') THEN
    RAISE EXCEPTION 'V26 authority writer privileges drift';
  END IF;
END;
$$;

DO $$
BEGIN
  IF NOT pg_has_role(
       'analytics_fundamental_value_writer_v1',
       'analytics_fv_current_assessment_writer_v1',
       'MEMBER') THEN
    RAISE EXCEPTION 'V26 umbrella writer role membership drift';
  END IF;
  IF pg_has_role(
       'analytics_fundamental_value_writer_v1',
       'analytics_fv_current_assessment_authority_writer_v1',
       'MEMBER') THEN
    RAISE EXCEPTION 'V26 authority writer must remain out of band';
  END IF;
END;
$$;

SELECT 'Current Fundamental Value V26 structural acceptance passed.'
  AS acceptance_result;
