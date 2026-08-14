\set ON_ERROR_STOP on

DO $$
DECLARE definition TEXT;
BEGIN
  SELECT pg_get_functiondef('app.task5_validate_position_evidence_v1()'::regprocedure)
  INTO definition;
  IF definition NOT LIKE '%p.field_code=''CLOSE_PRICE''%'
     OR length(definition)-length(replace(definition,
          'adjustmentMode''=''UNADJUSTED''',''))
        <> 2*length('adjustmentMode''=''UNADJUSTED''')
     OR definition LIKE '%TOTAL_RETURN_ADJUSTED%'
     OR definition LIKE '%ADJUSTED_CLOSE%'
  THEN
    RAISE EXCEPTION 'V35 current price evidence binding is not exact';
  END IF;

  IF pg_get_functiondef('app.task5_v31_selector_price_v1(uuid,uuid,uuid)'::regprocedure)
       NOT LIKE '%TOTAL_RETURN_ADJUSTED%'
  THEN
    RAISE EXCEPTION 'V35 changed V31 longitudinal total-return semantics';
  END IF;
END $$;
