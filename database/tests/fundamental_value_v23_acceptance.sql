\set ON_ERROR_STOP on

BEGIN;
INSERT INTO analytics.evidence_raw_manifest_v1 (
 id,provider_code,provider_schema_version,source_record_id,source_revision,
 source_content_hash,storage_class,payload_stored_in_git,storage_reference,
 effective_at,available_at,retrieved_at,ingested_at
) VALUES (
 '23000000-0000-4000-8000-000000000000','provider-primary','provider-schema-v3',
 'fv-v23-classification',1,'sha256:'||repeat('5',64),'PRIVATE_GIT_IGNORED',false,
 'private://fv-v23-classification',TIMESTAMPTZ '2026-01-01 00:00:00+00',
 TIMESTAMPTZ '2026-01-01 01:00:00+00',TIMESTAMPTZ '2026-01-01 01:01:00+00',
 TIMESTAMPTZ '2026-01-01 01:02:00+00'
);
INSERT INTO analytics.canonical_evidence_v1 (
 evidence_id,contract_version,domain,layer,state,reason_code,security_id,company_id,
 instrument_id,share_class_id,listing_id,ticker_assignment_id,ticker,mic,currency,
 provider_code,provider_schema_version,adapter_version,normalization_version,
 source_record_id,source_revision,source_content_hash,normalized_record_hash,
 effective_at,available_at,retrieved_at,ingested_at,freshness_policy_version,
 strictness_class,claim_class,conflict_status,conflict_criticality,affected_factors,
 observation_reference,raw_manifest_id,canonical_data
) SELECT
 '23000000-0000-4000-8000-000000000004',contract_version,domain,layer,state,reason_code,
 security_id,company_id,instrument_id,share_class_id,listing_id,ticker_assignment_id,ticker,mic,currency,
 provider_code,'provider-schema-v3','provider-neutral-adapter-v1.0.0','canonical-classification-v1.0.0',
 'fv-v23-classification',1,'sha256:'||repeat('5',64),'sha256:'||repeat('6',64),
 TIMESTAMPTZ '2026-01-01 00:00:00+00',TIMESTAMPTZ '2026-01-01 01:00:00+00',
 TIMESTAMPTZ '2026-01-01 01:01:00+00',TIMESTAMPTZ '2026-01-01 01:02:00+00',
 'classification-current-v1.0.0',strictness_class,claim_class,conflict_status,
 conflict_criticality,affected_factors,'fv-v23-classification',
 '23000000-0000-4000-8000-000000000000',canonical_data
 FROM analytics.canonical_evidence_v1 WHERE evidence_id='22000000-0000-4000-8000-000000000022';
INSERT INTO analytics.evidence_selector_policy_v1 (
 id,selector_version,policy_version,domain,field_code,required_layer,
 domain_constraints,required_strictness_class,required_claim_class,
 required_normalization_version,policy_content_hash
) VALUES (
 '23000000-0000-4000-8000-000000000001','deterministic-evidence-selector-v1.0.0',
 'fundamental-value-company-type-selection-v1.0.0','CLASSIFICATION','COMPANY_TYPE','NORMALIZED_OBSERVATION',
 '{"taxonomyVersion":"GICS-2025","effectiveOn":"2026-07-29"}'::jsonb,
 'STRICT_IDENTITY_AND_CHRONOLOGY','CURRENT_ONLY','canonical-classification-v1.0.0',
 'sha256:'||repeat('1',64)
);
INSERT INTO analytics.evidence_selector_provider_priority_v1 VALUES
 ('23000000-0000-4000-8000-000000000001',1,'provider-primary',CURRENT_TIMESTAMP);
INSERT INTO analytics.evidence_selector_policy_seal_v1 (policy_id,provider_priority_count)
 VALUES ('23000000-0000-4000-8000-000000000001',1);
INSERT INTO analytics.evidence_selection_request_v1 (
 request_id,contract_version,policy_id,security_id,company_id,instrument_id,
 share_class_id,listing_id,ticker_assignment_id,completed_session_id,
 decision_cutoff,sealed_ingestion_cutoff,request_content_hash
) SELECT
 '23000000-0000-4000-8000-000000000002','unified-market-data-evidence-foundation-v1.0.0',
 '23000000-0000-4000-8000-000000000001',security_id,company_id,instrument_id,
 share_class_id,listing_id,ticker_assignment_id,'22000000-0000-4000-8000-000000000006',
 TIMESTAMPTZ '2026-07-29 20:05:00+00',TIMESTAMPTZ '2026-07-29 20:07:00+00',
 'sha256:626f97834032d8eb47eb32981a629a985e0a39ba7dc79b79fe44af483f5dd84f'
 FROM analytics.canonical_evidence_v1 WHERE evidence_id='23000000-0000-4000-8000-000000000004';
INSERT INTO analytics.evidence_selection_candidate_v1 VALUES
 ('23000000-0000-4000-8000-000000000002',1,'23000000-0000-4000-8000-000000000004',CURRENT_TIMESTAMP);
INSERT INTO analytics.evidence_selection_result_v1 (
 request_id,selector_version,state,reason_code,selected_evidence_id,result_content_hash
) VALUES (
 '23000000-0000-4000-8000-000000000002','deterministic-evidence-selector-v1.0.0','VALID',
 'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK','23000000-0000-4000-8000-000000000004',
 analytics.evidence_selection_result_content_hash_v1(
  '23000000-0000-4000-8000-000000000002','deterministic-evidence-selector-v1.0.0','VALID',
  'SELECTED_BY_VERSIONED_PROVIDER_FALLBACK','23000000-0000-4000-8000-000000000004',ARRAY[]::UUID[],ARRAY[]::VARCHAR[])
);
INSERT INTO analytics.evidence_selection_seal_v1 VALUES
 ('23000000-0000-4000-8000-000000000002',1,0,CURRENT_TIMESTAMP);
INSERT INTO analytics.model_applicability_routing_v1 (
 routing_id,company_id,classification_evidence_id,model_family,company_type,
 applicability,specialized_model_code,routing_version,routing_revision,effective_at,
 routing_content_hash,supersedes_routing_id
) VALUES (
 '23000000-0000-4000-8000-000000000003','22000000-0000-4000-8000-000000000001',
 '23000000-0000-4000-8000-000000000004','FUNDAMENTAL_VALUE','MATURE_OPERATING_COMPANY',
 'APPLICABLE',NULL,'fundamental-value-applicability-v1.0.0',3,TIMESTAMPTZ '2026-01-01 01:05:00+00',
 analytics.model_applicability_routing_content_hash_v1(
  '23000000-0000-4000-8000-000000000003','22000000-0000-4000-8000-000000000001',
  '23000000-0000-4000-8000-000000000004','FUNDAMENTAL_VALUE','MATURE_OPERATING_COMPANY',
  'APPLICABLE',NULL,'fundamental-value-applicability-v1.0.0',3,TIMESTAMPTZ '2026-01-01 01:05:00+00',
  '22300000-0000-4000-8000-000000000123'),
 '22300000-0000-4000-8000-000000000123'
);

INSERT INTO analytics.fundamental_value_assembly_v1 (
 assembly_id,contract_version,manifest_version,assembly_version,security_id,company_id,
 instrument_id,share_class_id,listing_id,ticker_assignment_id,ticker,mic,currency,completed_session_id,
 classification_request_id,classification_evidence_id,classification_request_content_hash,
 classification_result_content_hash,classification_source_content_hash,classification_normalized_record_hash,
 classification_source_revision,classification_effective_at,classification_available_at,classification_ingested_at,
 classification_selector_policy_version,classification_selector_version,classification_freshness_policy_version,
 classification_normalization_version,classification_provider_schema_version,classification_adapter_version,
 applicability_routing_id,applicability_routing_content_hash,applicability_routing_revision,
 decision_cutoff,sealed_ingestion_cutoff,company_type,applicability,state,projection_years,
 evidence_contract_version,selector_version,applicability_routing_version,model_version,strategy_version,
 formula_version,assumption_policy_version,aggregation_version,risk_policy_version,core_invocation_authorized,
 core_input_hash,input_seal_version,input_seal_content_hash,
 expected_operand_count,expected_reason_count,manifest_content_hash,assembly_revision
) SELECT
 '23000000-0000-4000-8000-000000000010','fundamental-value-assembly-persistence-v1.0.0',
 'fundamental-value-assembly-manifest-v1.0.0','fundamental-value-v22-assembly-v1.0.0',
 e.security_id,e.company_id,e.instrument_id,e.share_class_id,e.listing_id,e.ticker_assignment_id,e.ticker,e.mic,e.currency,
 '22000000-0000-4000-8000-000000000006','23000000-0000-4000-8000-000000000002',e.evidence_id,
 q.request_content_hash,s.result_content_hash,e.source_content_hash,e.normalized_record_hash,e.source_revision,
 e.effective_at,e.available_at,e.ingested_at,p.policy_version,s.selector_version,e.freshness_policy_version,
 e.normalization_version,e.provider_schema_version,e.adapter_version,r.routing_id,r.routing_content_hash,r.routing_revision,
 q.decision_cutoff,q.sealed_ingestion_cutoff,r.company_type,r.applicability,'MISSING',5,
 'unified-market-data-evidence-foundation-v1.0.0','deterministic-evidence-selector-v1.0.0',
 'fundamental-value-applicability-v1.0.0','FUNDAMENTAL-VALUE-v1.0.0','LONG-TERM-CORE-v1.0.0',
 'fundamental-value-formulas-v1.1.0','fundamental-value-assumptions-v1.1.0',
 'FUNDAMENTAL-VALUE-WEIGHTED-MEDIAN-QUANTILE-v1.0.0','LONG-TERM-CORE-RISK-CAP-TIERS-v1.0.0',
 false,NULL,'fundamental-value-private-input-seal-v1.0.0','sha256:'||repeat('2',64),
 34,1,'sha256:'||repeat('3',64),1
 FROM analytics.canonical_evidence_v1 e
 JOIN analytics.evidence_selection_request_v1 q ON q.request_id='23000000-0000-4000-8000-000000000002'
 JOIN analytics.evidence_selection_result_v1 s ON s.request_id=q.request_id
 JOIN analytics.evidence_selector_policy_v1 p ON p.id=q.policy_id
 JOIN analytics.model_applicability_routing_v1 r ON r.routing_id='23000000-0000-4000-8000-000000000003'
 WHERE e.evidence_id='23000000-0000-4000-8000-000000000004';
INSERT INTO analytics.fundamental_value_assembly_reason_v1 VALUES
 ('23000000-0000-4000-8000-000000000010',1,'REQUIRED_OPERANDS_MISSING');
INSERT INTO analytics.fundamental_value_assembly_operand_v1 (
 assembly_id,operand_ordinal,operand_code,source_kind,required_for_core,state,expected_evidence_count,expected_reason_count
) SELECT '23000000-0000-4000-8000-000000000010',ordinal,code,kind,
  ordinal NOT IN (13,17,34),'MISSING',0,1 FROM (VALUES
 (1,'reference_price','DAILY_PRICE'),(2,'diluted_shares','DIRECT_FUNDAMENTAL'),(3,'cash','DIRECT_FUNDAMENTAL'),(4,'debt','DIRECT_FUNDAMENTAL'),(5,'ebit','DIRECT_FUNDAMENTAL'),(6,'tax_rate','DERIVATION_REQUIRED'),(7,'depreciation_and_amortization','DERIVATION_REQUIRED'),(8,'capital_expenditures','DIRECT_FUNDAMENTAL'),(9,'change_in_working_capital','DERIVATION_REQUIRED'),(10,'normalized_free_cash_flow','DIRECT_FUNDAMENTAL'),(11,'normalized_after_tax_operating_earnings','DERIVATION_REQUIRED'),(12,'ebitda','DERIVATION_REQUIRED'),(13,'comparable_ev_to_ebitda','POLICY_EVIDENCE_REQUIRED'),(14,'conservative_growth_rate','DERIVATION_REQUIRED'),(15,'discount_rate','POLICY_EVIDENCE_REQUIRED'),(16,'terminal_growth_rate','POLICY_EVIDENCE_REQUIRED'),(17,'net_distribution_yield','DERIVATION_REQUIRED'),(18,'return_on_invested_capital','DERIVATION_REQUIRED'),(19,'operating_margin','DERIVATION_REQUIRED'),(20,'free_cash_flow_margin','DERIVATION_REQUIRED'),(21,'earnings_stability','DERIVATION_REQUIRED'),(22,'cash_flow_stability','DERIVATION_REQUIRED'),(23,'net_debt_to_ebitda','DERIVATION_REQUIRED'),(24,'interest_coverage','DERIVATION_REQUIRED'),(25,'current_ratio','DERIVATION_REQUIRED'),(26,'diluted_share_growth','DERIVATION_REQUIRED'),(27,'cash_flow_to_net_income','DERIVATION_REQUIRED'),(28,'incremental_return_on_invested_capital','DERIVATION_REQUIRED'),(29,'acquisition_discipline','POLICY_EVIDENCE_REQUIRED'),(30,'shareholder_distribution_coverage','DERIVATION_REQUIRED'),(31,'cyclicality_risk','POLICY_EVIDENCE_REQUIRED'),(32,'concentration_risk','POLICY_EVIDENCE_REQUIRED'),(33,'event_risk','POLICY_EVIDENCE_REQUIRED'),(34,'debt_maturity_schedule','POLICY_EVIDENCE_REQUIRED')) v(ordinal,code,kind);
INSERT INTO analytics.fundamental_value_operand_reason_v1
 SELECT assembly_id,operand_ordinal,1,'OPERAND_EVIDENCE_MISSING' FROM analytics.fundamental_value_assembly_operand_v1 WHERE assembly_id='23000000-0000-4000-8000-000000000010';
INSERT INTO analytics.fundamental_value_assembly_seal_v1 VALUES
 ('23000000-0000-4000-8000-000000000010',34,1,34,0,CURRENT_TIMESTAMP);
COMMIT;

BEGIN;
INSERT INTO analytics.security (public_id,symbol,exchange,name,instrument_type,currency)
 VALUES ('23000000-0000-4000-8000-000000000100','NBN','NASDAQ','Synthetic NBN Bank','COMMON_STOCK','USD');
INSERT INTO analytics.evidence_company_identity_v1 VALUES ('23000000-0000-4000-8000-000000000101','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP);
INSERT INTO analytics.evidence_instrument_identity_v1 VALUES ('23000000-0000-4000-8000-000000000102','23000000-0000-4000-8000-000000000101','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP);
INSERT INTO analytics.evidence_share_class_identity_v1 VALUES ('23000000-0000-4000-8000-000000000103','23000000-0000-4000-8000-000000000102','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP);
INSERT INTO analytics.evidence_listing_identity_v1 VALUES ('23000000-0000-4000-8000-000000000104','23000000-0000-4000-8000-000000000103','23000000-0000-4000-8000-000000000100','XNAS','USD','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP);
INSERT INTO analytics.evidence_ticker_assignment_v1 VALUES ('23000000-0000-4000-8000-000000000105','23000000-0000-4000-8000-000000000104','NBN',DATE '2020-01-01',NULL,'security-identity-registry-v1.0.0',CURRENT_TIMESTAMP);
INSERT INTO analytics.evidence_raw_manifest_v1 (
 id,provider_code,provider_schema_version,source_record_id,source_revision,source_content_hash,
 storage_class,payload_stored_in_git,storage_reference,effective_at,available_at,retrieved_at,ingested_at
) VALUES ('23000000-0000-4000-8000-000000000106','provider-primary','provider-schema-v3','fv-v23-nbn-classification',1,
 'sha256:'||repeat('7',64),'PRIVATE_GIT_IGNORED',false,'private://fv-v23-nbn',TIMESTAMPTZ '2026-01-01 00:00:00+00',
 TIMESTAMPTZ '2026-01-01 01:00:00+00',TIMESTAMPTZ '2026-01-01 01:01:00+00',TIMESTAMPTZ '2026-01-01 01:02:00+00');
INSERT INTO analytics.canonical_evidence_v1 (
 evidence_id,contract_version,domain,layer,state,security_id,company_id,instrument_id,share_class_id,listing_id,ticker_assignment_id,
 ticker,mic,currency,provider_code,provider_schema_version,adapter_version,normalization_version,source_record_id,source_revision,
 source_content_hash,normalized_record_hash,effective_at,available_at,retrieved_at,ingested_at,freshness_policy_version,
 strictness_class,claim_class,conflict_status,conflict_criticality,affected_factors,observation_reference,raw_manifest_id,canonical_data
) VALUES ('23000000-0000-4000-8000-000000000107','unified-market-data-evidence-foundation-v1.0.0','CLASSIFICATION','NORMALIZED_OBSERVATION','VALID',
 '23000000-0000-4000-8000-000000000100','23000000-0000-4000-8000-000000000101','23000000-0000-4000-8000-000000000102',
 '23000000-0000-4000-8000-000000000103','23000000-0000-4000-8000-000000000104','23000000-0000-4000-8000-000000000105',
 'NBN','XNAS','USD','provider-primary','provider-schema-v3','provider-neutral-adapter-v1.0.0','canonical-classification-v1.0.0',
 'fv-v23-nbn-classification',1,'sha256:'||repeat('7',64),'sha256:'||repeat('8',64),TIMESTAMPTZ '2026-01-01 00:00:00+00',
 TIMESTAMPTZ '2026-01-01 01:00:00+00',TIMESTAMPTZ '2026-01-01 01:01:00+00',TIMESTAMPTZ '2026-01-01 01:02:00+00',
 'classification-current-v1.0.0','STRICT_IDENTITY_AND_CHRONOLOGY','CURRENT_ONLY','NONE','NONE','[]'::jsonb,'fv-v23-nbn',
 '23000000-0000-4000-8000-000000000106','{"taxonomyCode":"GICS","taxonomyVersion":"GICS-2025","sectorCode":"40","industryCode":"40101010","companyType":"BANK","effectiveFrom":"2026-01-01"}'::jsonb);
INSERT INTO analytics.evidence_selection_request_v1 (
 request_id,contract_version,policy_id,security_id,company_id,instrument_id,share_class_id,listing_id,ticker_assignment_id,
 completed_session_id,decision_cutoff,sealed_ingestion_cutoff,request_content_hash
) VALUES ('23000000-0000-4000-8000-000000000108','unified-market-data-evidence-foundation-v1.0.0','23000000-0000-4000-8000-000000000001',
 '23000000-0000-4000-8000-000000000100','23000000-0000-4000-8000-000000000101','23000000-0000-4000-8000-000000000102',
 '23000000-0000-4000-8000-000000000103','23000000-0000-4000-8000-000000000104','23000000-0000-4000-8000-000000000105',
 '22000000-0000-4000-8000-000000000006',TIMESTAMPTZ '2026-07-29 20:05:00+00',TIMESTAMPTZ '2026-07-29 20:07:00+00','sha256:'||repeat('90abcdef',8));
INSERT INTO analytics.evidence_selection_candidate_v1 VALUES ('23000000-0000-4000-8000-000000000108',1,'23000000-0000-4000-8000-000000000107',CURRENT_TIMESTAMP);
INSERT INTO analytics.evidence_selection_result_v1 VALUES ('23000000-0000-4000-8000-000000000108','deterministic-evidence-selector-v1.0.0','VALID','SELECTED_BY_VERSIONED_PROVIDER_FALLBACK','23000000-0000-4000-8000-000000000107',
 analytics.evidence_selection_result_content_hash_v1('23000000-0000-4000-8000-000000000108','deterministic-evidence-selector-v1.0.0','VALID','SELECTED_BY_VERSIONED_PROVIDER_FALLBACK','23000000-0000-4000-8000-000000000107',ARRAY[]::UUID[],ARRAY[]::VARCHAR[]),CURRENT_TIMESTAMP);
INSERT INTO analytics.evidence_selection_seal_v1 VALUES ('23000000-0000-4000-8000-000000000108',1,0,CURRENT_TIMESTAMP);
INSERT INTO analytics.model_applicability_routing_v1 (
 routing_id,company_id,classification_evidence_id,model_family,company_type,applicability,specialized_model_code,routing_version,routing_revision,effective_at,routing_content_hash
) VALUES ('23000000-0000-4000-8000-000000000109','23000000-0000-4000-8000-000000000101','23000000-0000-4000-8000-000000000107',
 'FUNDAMENTAL_VALUE','BANK','SPECIALIZED_MODEL_REQUIRED','BANK_MODEL_REQUIRED','fundamental-value-applicability-v1.0.0',1,TIMESTAMPTZ '2026-01-01 01:05:00+00',
 analytics.model_applicability_routing_content_hash_v1('23000000-0000-4000-8000-000000000109','23000000-0000-4000-8000-000000000101','23000000-0000-4000-8000-000000000107','FUNDAMENTAL_VALUE','BANK','SPECIALIZED_MODEL_REQUIRED','BANK_MODEL_REQUIRED','fundamental-value-applicability-v1.0.0',1,TIMESTAMPTZ '2026-01-01 01:05:00+00',NULL));
INSERT INTO analytics.fundamental_value_assembly_v1
SELECT (jsonb_populate_record(NULL::analytics.fundamental_value_assembly_v1,
 to_jsonb(base)||jsonb_build_object(
  'assembly_id','23000000-0000-4000-8000-000000000110','security_id','23000000-0000-4000-8000-000000000100',
  'company_id','23000000-0000-4000-8000-000000000101','instrument_id','23000000-0000-4000-8000-000000000102',
  'share_class_id','23000000-0000-4000-8000-000000000103','listing_id','23000000-0000-4000-8000-000000000104',
  'ticker_assignment_id','23000000-0000-4000-8000-000000000105','ticker','NBN','classification_request_id','23000000-0000-4000-8000-000000000108',
  'classification_evidence_id','23000000-0000-4000-8000-000000000107','classification_request_content_hash','sha256:'||repeat('90abcdef',8),
  'classification_result_content_hash',result.result_content_hash,'classification_source_content_hash',evidence.source_content_hash,
  'classification_normalized_record_hash',evidence.normalized_record_hash,'classification_source_revision',evidence.source_revision,
  'classification_effective_at',evidence.effective_at,'classification_available_at',evidence.available_at,'classification_ingested_at',evidence.ingested_at,
  'applicability_routing_id',route.routing_id,'applicability_routing_content_hash',route.routing_content_hash,'applicability_routing_revision',1,
  'company_type','BANK','applicability','SPECIALIZED_MODEL_REQUIRED','state','NOT_APPLICABLE','core_invocation_authorized',false,
  'expected_operand_count',0,'expected_reason_count',1,'manifest_content_hash','sha256:'||repeat('a',64),'assembly_revision',1,
  'supersedes_assembly_id',NULL,'recorded_at',CURRENT_TIMESTAMP))).*
FROM analytics.fundamental_value_assembly_v1 base
JOIN analytics.canonical_evidence_v1 evidence ON evidence.evidence_id='23000000-0000-4000-8000-000000000107'
JOIN analytics.evidence_selection_result_v1 result ON result.request_id='23000000-0000-4000-8000-000000000108'
JOIN analytics.model_applicability_routing_v1 route ON route.routing_id='23000000-0000-4000-8000-000000000109'
WHERE base.assembly_id='23000000-0000-4000-8000-000000000010';
INSERT INTO analytics.fundamental_value_assembly_reason_v1 VALUES ('23000000-0000-4000-8000-000000000110',1,'APPLICABILITY_SPECIALIZED_MODEL_REQUIRED');
INSERT INTO analytics.fundamental_value_assembly_seal_v1 VALUES ('23000000-0000-4000-8000-000000000110',0,1,0,0,CURRENT_TIMESTAMP);
COMMIT;

DO $$
DECLARE
    missing_tables INTEGER;
    append_only_triggers INTEGER;
    forbidden_columns INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing_tables
    FROM (VALUES
      ('fundamental_value_operand_producer_contract_v1'),
      ('fundamental_value_producer_parent_slot_v1'),
      ('fundamental_value_assembly_v1'),('fundamental_value_assembly_reason_v1'),
      ('fundamental_value_assembly_operand_v1'),('fundamental_value_operand_reason_v1'),
      ('fundamental_value_operand_evidence_v1'),
      ('fundamental_value_assembly_seal_v1'),('fundamental_value_assessment_v1'),
      ('fundamental_value_dimension_v1'),('fundamental_value_valuation_method_v1'),
      ('fundamental_value_valuation_scenario_v1'),('fundamental_value_ordered_range_v1'),
      ('fundamental_value_condition_v1'),('fundamental_value_component_reason_v1'),
      ('fundamental_value_risk_cap_reason_v1'),('fundamental_value_assessment_seal_v1')
    ) expected(name)
    WHERE to_regclass('analytics.' || expected.name) IS NULL;
    IF missing_tables <> 0 THEN
        RAISE EXCEPTION 'Fundamental Value V23 tables are incomplete';
    END IF;

    SELECT COUNT(*) INTO append_only_triggers
    FROM pg_trigger
    WHERE tgrelid IN (
      SELECT to_regclass('analytics.' || expected.name)
      FROM (VALUES
        ('fundamental_value_operand_producer_contract_v1'),
        ('fundamental_value_producer_parent_slot_v1'),
        ('fundamental_value_assembly_v1'),('fundamental_value_assembly_reason_v1'),
        ('fundamental_value_assembly_operand_v1'),('fundamental_value_operand_reason_v1'),('fundamental_value_operand_evidence_v1'),
        ('fundamental_value_assembly_seal_v1'),('fundamental_value_assessment_v1'),
        ('fundamental_value_dimension_v1'),('fundamental_value_valuation_method_v1'),
        ('fundamental_value_valuation_scenario_v1'),('fundamental_value_ordered_range_v1'),
        ('fundamental_value_condition_v1'),('fundamental_value_component_reason_v1'),
        ('fundamental_value_risk_cap_reason_v1'),('fundamental_value_assessment_seal_v1')
      ) expected(name)
    ) AND tgname LIKE '%append_only' AND NOT tgisinternal;
    IF append_only_triggers <> 17 THEN
        RAISE EXCEPTION 'Fundamental Value V23 append-only triggers are incomplete';
    END IF;

    SELECT COUNT(*) INTO forbidden_columns
    FROM information_schema.columns
    WHERE table_schema='analytics' AND table_name LIKE 'fundamental_value_%'
      AND (column_name LIKE '%retention%' OR column_name LIKE '%deletion%'
        OR column_name LIKE '%legal_hold%' OR column_name LIKE '%disposition%'
        OR column_name IN ('final_portfolio_weight','brokerage_action','order_action')
        OR column_name LIKE '%raw_payload%');
    IF forbidden_columns <> 0 THEN
        RAISE EXCEPTION 'Fundamental Value V23 crossed a prohibited responsibility boundary';
    END IF;

    IF has_table_privilege('analytics_writer','analytics.fundamental_value_assembly_v1','INSERT')
       OR has_table_privilege('analytics_reader','analytics.fundamental_value_assembly_v1','INSERT')
       OR NOT has_table_privilege('analytics_fundamental_value_writer_v1','analytics.fundamental_value_assembly_v1','INSERT') THEN
        RAISE EXCEPTION 'Fundamental Value V23 write-role boundary is invalid';
    END IF;

    IF EXISTS (SELECT 1 FROM analytics.fundamental_value_operand_producer_contract_v1)
       OR has_table_privilege('analytics_writer',
          'analytics.fundamental_value_operand_producer_contract_v1','INSERT')
       OR has_table_privilege('analytics_fundamental_value_writer_v1',
          'analytics.fundamental_value_operand_producer_contract_v1','INSERT') THEN
        RAISE EXCEPTION 'Fundamental Value production producer registry must be empty and unwritable';
    END IF;

    IF pg_get_functiondef('analytics.validate_fundamental_value_assembly_seal_v1()'::regprocedure)
         NOT LIKE '%pg_advisory_xact_lock%'
       OR pg_get_functiondef('analytics.validate_fundamental_value_assembly_v1()'::regprocedure)
         NOT LIKE '%pg_advisory_xact_lock%'
       OR pg_get_functiondef('analytics.validate_fundamental_value_assessment_seal_v1()'::regprocedure)
         NOT LIKE '%pg_advisory_xact_lock%' THEN
        RAISE EXCEPTION 'Fundamental Value V23 seal concurrency locks are missing';
    END IF;

    IF pg_get_functiondef('analytics.validate_fundamental_value_operand_v1()'::regprocedure)
         NOT ILIKE '%STRICT_IDENTITY_AND_CHRONOLOGY%'
       OR pg_get_functiondef('analytics.validate_fundamental_value_operand_v1()'::regprocedure)
         NOT ILIKE '%STRICT_PIT%'
       OR pg_get_functiondef('analytics.validate_fundamental_value_operand_v1()'::regprocedure)
         NOT ILIKE '%CURRENT_ONLY%'
       OR pg_get_functiondef('analytics.validate_fundamental_value_operand_v1()'::regprocedure)
         NOT ILIKE '%jsonb_object_keys(policy_record.domain_constraints)%'
       OR pg_get_functiondef('analytics.validate_fundamental_value_operand_v1()'::regprocedure)
         NOT ILIKE '%effective_at IS DISTINCT FROM new.effective_at%'
       OR pg_get_functiondef('analytics.validate_fundamental_value_operand_v1()'::regprocedure)
         NOT ILIKE '%tolerance_policy_version IS DISTINCT FROM new.tolerance_policy_version%'
       OR pg_get_functiondef('analytics.validate_fundamental_value_operand_v1()'::regprocedure)
         NOT ILIKE '%new.numeric_value is distinct from%canonical_data%close%'
       OR pg_get_functiondef('analytics.validate_fundamental_value_operand_v1()'::regprocedure)
         NOT ILIKE '%new.numeric_value is distinct from%canonical_data%numericValue%' THEN
        RAISE EXCEPTION 'Fundamental Value V23 selector-semantic tamper guards are incomplete';
    END IF;
END;
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM analytics.fundamental_value_assembly_operand_v1
        WHERE assembly_id='23000000-0000-4000-8000-000000000010'
          AND required_for_core IS DISTINCT FROM (operand_ordinal NOT IN (13,17,34))
    ) THEN
        RAISE EXCEPTION 'Fundamental Value required-for-core tuple drift was accepted';
    END IF;
END;
$$;

DO $$
DECLARE cap_constraint_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO cap_constraint_count
    FROM pg_constraint
    WHERE conrelid='analytics.fundamental_value_assessment_v1'::regclass
      AND pg_get_constraintdef(oid) LIKE '%risk_cap_ceiling%0.02%';
    IF cap_constraint_count <> 1 THEN
        RAISE EXCEPTION 'Fundamental Value risk-cap tier constraint is missing';
    END IF;
END;
$$;

DO $$
BEGIN
    BEGIN
        UPDATE analytics.fundamental_value_assembly_v1 SET state='VALID'
        WHERE assembly_id='23000000-0000-4000-8000-000000000010';
        RAISE EXCEPTION 'Fundamental Value append-only update was accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='Fundamental Value append-only update was accepted' THEN RAISE; END IF;
    END;
    BEGIN
        DELETE FROM analytics.fundamental_value_assembly_operand_v1
        WHERE assembly_id='23000000-0000-4000-8000-000000000010' AND operand_ordinal=1;
        RAISE EXCEPTION 'Fundamental Value append-only delete was accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='Fundamental Value append-only delete was accepted' THEN RAISE; END IF;
    END;
    BEGIN
        INSERT INTO analytics.fundamental_value_assembly_operand_v1 (
          assembly_id,operand_ordinal,operand_code,source_kind,required_for_core,
          state,numeric_value,expected_evidence_count,expected_reason_count
        ) VALUES (
          '23000000-0000-4000-8000-000000000010',35,'fabricated_operand',
          'DERIVATION_REQUIRED',true,'MISSING',0,0,1
        );
        RAISE EXCEPTION 'Numeric value was accepted on a non-usable operand';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'Fundamental Value assembly child set is sealed' THEN RAISE; END IF;
    END;
    BEGIN
        INSERT INTO analytics.fundamental_value_assembly_reason_v1 VALUES
          ('23000000-0000-4000-8000-000000000010',2,'LATE_REASON');
        RAISE EXCEPTION 'Late assembly child was accepted after seal';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM='Late assembly child was accepted after seal' THEN RAISE; END IF;
    END;
END;
$$;

-- Existing V22 evidence and V21 lane semantics remain independently covered by
-- their unchanged acceptance suites, which the migration runner executes first.
