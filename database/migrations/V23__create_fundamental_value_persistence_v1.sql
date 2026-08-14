-- Fundamental Value v1 persistence. This migration is intentionally limited to
-- deterministic assembly and assessment records. It owns no raw-data retention,
-- deletion, legal-hold, portfolio-weight, order, or brokerage responsibility.

CREATE FUNCTION analytics.fundamental_value_finite_numeric_v1(value NUMERIC)
RETURNS BOOLEAN LANGUAGE SQL IMMUTABLE PARALLEL SAFE AS $$
    SELECT value IS NOT NULL AND value::TEXT NOT IN ('NaN', 'Infinity', '-Infinity')
$$;

CREATE TABLE analytics.fundamental_value_operand_producer_contract_v1 (
    operand_code VARCHAR(128) NOT NULL,
    source_kind VARCHAR(64) NOT NULL,
    contract_version VARCHAR(128) NOT NULL,
    evaluator_id VARCHAR(128) NOT NULL,
    governance_status VARCHAR(32) NOT NULL,
    output_semantics VARCHAR(128) NOT NULL,
    parent_slot_count INTEGER NOT NULL,
    contract_content_hash VARCHAR(71) NOT NULL UNIQUE,
    PRIMARY KEY (operand_code, contract_version),
    CHECK (source_kind IN ('DERIVATION_REQUIRED','POLICY_EVIDENCE_REQUIRED')),
    CHECK (governance_status='TEST_ONLY' AND parent_slot_count > 0),
    CHECK (contract_version LIKE 'test-only-%' AND evaluator_id LIKE 'test-only-%'),
    CHECK (contract_content_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE analytics.fundamental_value_producer_parent_slot_v1 (
    operand_code VARCHAR(128) NOT NULL,
    contract_version VARCHAR(128) NOT NULL,
    parent_ordinal INTEGER NOT NULL,
    role_code VARCHAR(128) NOT NULL,
    domain VARCHAR(64) NOT NULL,
    field_code VARCHAR(128) NOT NULL,
    unit VARCHAR(32) NOT NULL,
    currency_rule VARCHAR(32) NOT NULL,
    fiscal_period VARCHAR(32) NOT NULL,
    period_identity VARCHAR(64) NOT NULL,
    period_start DATE,
    period_end DATE NOT NULL,
    PRIMARY KEY (operand_code, contract_version, parent_ordinal),
    FOREIGN KEY (operand_code, contract_version)
        REFERENCES analytics.fundamental_value_operand_producer_contract_v1
        (operand_code, contract_version),
    CHECK (parent_ordinal > 0 AND btrim(role_code)<>''),
    CHECK (currency_rule IN ('MATCH_OUTPUT','NOT_APPLICABLE')),
    CHECK (period_start IS NULL OR period_start <= period_end)
);

CREATE TABLE analytics.fundamental_value_assembly_v1 (
    assembly_id UUID PRIMARY KEY,
    contract_version VARCHAR(128) NOT NULL,
    manifest_version VARCHAR(128) NOT NULL,
    assembly_version VARCHAR(128) NOT NULL,
    security_id UUID NOT NULL REFERENCES analytics.security (public_id),
    company_id UUID NOT NULL REFERENCES analytics.evidence_company_identity_v1 (company_id),
    instrument_id UUID NOT NULL REFERENCES analytics.evidence_instrument_identity_v1 (instrument_id),
    share_class_id UUID NOT NULL REFERENCES analytics.evidence_share_class_identity_v1 (share_class_id),
    listing_id UUID NOT NULL REFERENCES analytics.evidence_listing_identity_v1 (listing_id),
    ticker_assignment_id UUID NOT NULL REFERENCES analytics.evidence_ticker_assignment_v1 (ticker_assignment_id),
    ticker VARCHAR(32) NOT NULL,
    mic CHAR(4) NOT NULL,
    currency CHAR(3) NOT NULL,
    completed_session_id UUID NOT NULL REFERENCES analytics.evidence_completed_session_v1 (id),
    classification_request_id UUID NOT NULL REFERENCES analytics.evidence_selection_request_v1 (request_id),
    classification_evidence_id UUID NOT NULL REFERENCES analytics.canonical_evidence_v1 (evidence_id),
    classification_request_content_hash VARCHAR(71) NOT NULL,
    classification_result_content_hash VARCHAR(71) NOT NULL,
    classification_source_content_hash VARCHAR(71) NOT NULL,
    classification_normalized_record_hash VARCHAR(71) NOT NULL,
    classification_source_revision INTEGER NOT NULL,
    classification_effective_at TIMESTAMPTZ NOT NULL,
    classification_available_at TIMESTAMPTZ NOT NULL,
    classification_ingested_at TIMESTAMPTZ NOT NULL,
    classification_selector_policy_version VARCHAR(128) NOT NULL,
    classification_selector_version VARCHAR(128) NOT NULL,
    classification_freshness_policy_version VARCHAR(128) NOT NULL,
    classification_normalization_version VARCHAR(128) NOT NULL,
    classification_provider_schema_version VARCHAR(128) NOT NULL,
    classification_adapter_version VARCHAR(128) NOT NULL,
    applicability_routing_id UUID NOT NULL REFERENCES analytics.model_applicability_routing_v1 (routing_id),
    applicability_routing_content_hash VARCHAR(71) NOT NULL,
    applicability_routing_revision INTEGER NOT NULL,
    decision_cutoff TIMESTAMPTZ NOT NULL,
    sealed_ingestion_cutoff TIMESTAMPTZ NOT NULL,
    company_type VARCHAR(64) NOT NULL,
    applicability VARCHAR(64) NOT NULL,
    state VARCHAR(32) NOT NULL,
    projection_years INTEGER NOT NULL,
    evidence_contract_version VARCHAR(128) NOT NULL,
    selector_version VARCHAR(128) NOT NULL,
    applicability_routing_version VARCHAR(128) NOT NULL,
    model_version VARCHAR(128) NOT NULL,
    strategy_version VARCHAR(128) NOT NULL,
    formula_version VARCHAR(128) NOT NULL,
    assumption_policy_version VARCHAR(128) NOT NULL,
    aggregation_version VARCHAR(128) NOT NULL,
    risk_policy_version VARCHAR(128) NOT NULL,
    core_invocation_authorized BOOLEAN NOT NULL,
    core_input_hash VARCHAR(71),
    input_seal_version VARCHAR(128),
    input_seal_content_hash VARCHAR(71),
    expected_operand_count INTEGER NOT NULL,
    expected_reason_count INTEGER NOT NULL,
    manifest_content_hash VARCHAR(71) NOT NULL,
    assembly_revision INTEGER NOT NULL,
    supersedes_assembly_id UUID UNIQUE REFERENCES analytics.fundamental_value_assembly_v1 (assembly_id),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_fv_assembly_versions CHECK (
        contract_version = 'fundamental-value-assembly-persistence-v1.0.0'
        AND manifest_version = 'fundamental-value-assembly-manifest-v1.0.0'
        AND assembly_version = 'fundamental-value-v22-assembly-v1.0.0'
        AND evidence_contract_version = 'unified-market-data-evidence-foundation-v1.0.0'
        AND selector_version = 'deterministic-evidence-selector-v1.0.0'
        AND applicability_routing_version = 'fundamental-value-applicability-v1.0.0'
        AND model_version = 'FUNDAMENTAL-VALUE-v1.0.0'
        AND strategy_version = 'LONG-TERM-CORE-v1.0.0'
        AND formula_version = 'fundamental-value-formulas-v1.1.0'
        AND assumption_policy_version = 'fundamental-value-assumptions-v1.1.0'
        AND aggregation_version = 'FUNDAMENTAL-VALUE-WEIGHTED-MEDIAN-QUANTILE-v1.0.0'
        AND risk_policy_version = 'LONG-TERM-CORE-RISK-CAP-TIERS-v1.0.0'
    ),
    CONSTRAINT ck_fv_assembly_state CHECK (state IN ('VALID','MISSING','STALE','INVALID','NOT_APPLICABLE','EXCLUDED')),
    CONSTRAINT ck_fv_assembly_applicability CHECK (applicability IN ('APPLICABLE','SPECIALIZED_MODEL_REQUIRED','NOT_APPLICABLE','INSUFFICIENT_EVIDENCE')),
    CONSTRAINT ck_fv_assembly_horizon CHECK (projection_years BETWEEN 3 AND 10),
    CONSTRAINT ck_fv_assembly_counts CHECK (expected_operand_count >= 0 AND expected_reason_count >= 0),
    CONSTRAINT ck_fv_assembly_authority CHECK (
        core_invocation_authorized = (state = 'VALID' AND applicability = 'APPLICABLE'
            AND company_type = 'MATURE_OPERATING_COMPANY')
    ),
    CONSTRAINT ck_fv_assembly_core_input_hash CHECK (
        input_seal_version IS NOT NULL AND input_seal_content_hash IS NOT NULL AND (
        (core_invocation_authorized AND core_input_hash ~ '^sha256:[0-9a-f]{64}$'
            AND input_seal_version='fundamental-value-private-input-seal-v1.0.0'
            AND input_seal_content_hash ~ '^sha256:[0-9a-f]{64}$')
        OR (NOT core_invocation_authorized AND core_input_hash IS NULL
            AND input_seal_version='fundamental-value-private-input-seal-v1.0.0'
            AND input_seal_content_hash ~ '^sha256:[0-9a-f]{64}$'))
    ),
    CONSTRAINT ck_fv_assembly_hash CHECK (manifest_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_fv_classification_hashes CHECK (
        classification_request_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND classification_result_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND classification_source_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND classification_normalized_record_hash ~ '^sha256:[0-9a-f]{64}$'
        AND applicability_routing_content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_fv_classification_revision CHECK (classification_source_revision > 0 AND applicability_routing_revision > 0),
    CONSTRAINT ck_fv_classification_chronology CHECK (isfinite(classification_effective_at)
        AND isfinite(classification_available_at) AND isfinite(classification_ingested_at)
        AND classification_effective_at <= classification_available_at AND classification_available_at <= classification_ingested_at),
    CONSTRAINT ck_fv_classification_versions CHECK (
        classification_selector_policy_version = 'fundamental-value-company-type-selection-v1.0.0'
        AND classification_selector_version = 'deterministic-evidence-selector-v1.0.0'
        AND classification_freshness_policy_version = 'classification-current-v1.0.0'
        AND classification_normalization_version = 'canonical-classification-v1.0.0'
    ),
    CONSTRAINT ck_fv_assembly_revision CHECK (assembly_revision > 0),
    CONSTRAINT ck_fv_assembly_chronology CHECK (isfinite(decision_cutoff) AND isfinite(sealed_ingestion_cutoff)
        AND isfinite(recorded_at) AND decision_cutoff <= sealed_ingestion_cutoff),
    CONSTRAINT ck_fv_assembly_not_self_superseding CHECK (supersedes_assembly_id IS NULL OR supersedes_assembly_id <> assembly_id),
    UNIQUE (security_id, company_id, instrument_id, share_class_id, listing_id,
        ticker_assignment_id, assembly_version, assembly_revision)
);

CREATE TABLE analytics.fundamental_value_assembly_reason_v1 (
    assembly_id UUID NOT NULL REFERENCES analytics.fundamental_value_assembly_v1 (assembly_id),
    reason_ordinal INTEGER NOT NULL,
    reason_code VARCHAR(128) NOT NULL,
    PRIMARY KEY (assembly_id, reason_ordinal),
    UNIQUE (assembly_id, reason_code),
    CHECK (reason_ordinal > 0 AND btrim(reason_code) <> '')
);

CREATE TABLE analytics.fundamental_value_assembly_operand_v1 (
    assembly_id UUID NOT NULL REFERENCES analytics.fundamental_value_assembly_v1 (assembly_id),
    operand_ordinal INTEGER NOT NULL,
    operand_code VARCHAR(128) NOT NULL,
    source_kind VARCHAR(64) NOT NULL,
    required_for_core BOOLEAN NOT NULL,
    state VARCHAR(32) NOT NULL,
    numeric_value NUMERIC,
    selector_request_id UUID REFERENCES analytics.evidence_selection_request_v1 (request_id),
    selected_evidence_id UUID REFERENCES analytics.canonical_evidence_v1 (evidence_id),
    request_content_hash VARCHAR(71),
    result_content_hash VARCHAR(71),
    source_content_hash VARCHAR(71),
    normalized_record_hash VARCHAR(71),
    source_revision INTEGER,
    effective_at TIMESTAMPTZ,
    available_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ,
    selector_policy_version VARCHAR(128),
    freshness_policy_version VARCHAR(128),
    normalization_version VARCHAR(128),
    provider_schema_version VARCHAR(128),
    adapter_version VARCHAR(128),
    tolerance_policy_version VARCHAR(128),
    derivation_version VARCHAR(128),
    output_content_hash VARCHAR(71),
    producer_contract_content_hash VARCHAR(71),
    expected_evidence_count INTEGER NOT NULL,
    expected_reason_count INTEGER NOT NULL,
    PRIMARY KEY (assembly_id, operand_ordinal),
    UNIQUE (assembly_id, operand_code),
    UNIQUE (assembly_id, selected_evidence_id),
    CHECK (operand_ordinal > 0 AND btrim(operand_code) <> ''),
    CHECK (source_kind IN ('DAILY_PRICE','DIRECT_FUNDAMENTAL','DERIVATION_REQUIRED','POLICY_EVIDENCE_REQUIRED')),
    CHECK (state IN ('VALID','MISSING','STALE','INVALID','NOT_APPLICABLE','EXCLUDED')),
    CHECK (expected_evidence_count >= 0 AND expected_reason_count >= 0),
    CHECK (numeric_value IS NULL OR analytics.fundamental_value_finite_numeric_v1(numeric_value)),
    CHECK (
        (state = 'VALID' AND numeric_value IS NOT NULL AND expected_evidence_count > 0
         AND expected_reason_count = 0
         AND ((source_kind IN ('DAILY_PRICE','DIRECT_FUNDAMENTAL') AND selector_request_id IS NOT NULL AND selected_evidence_id IS NOT NULL)
           OR (source_kind IN ('DERIVATION_REQUIRED','POLICY_EVIDENCE_REQUIRED') AND selected_evidence_id IS NULL)))
        OR (state <> 'VALID' AND numeric_value IS NULL AND expected_evidence_count = 0 AND expected_reason_count > 0)
    ),
    CHECK (source_revision IS NULL OR source_revision > 0),
    CHECK (request_content_hash IS NULL OR request_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (result_content_hash IS NULL OR result_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (source_content_hash IS NULL OR source_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (normalized_record_hash IS NULL OR normalized_record_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (output_content_hash IS NULL OR output_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (producer_contract_content_hash IS NULL OR producer_contract_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK ((state='VALID' AND source_kind IN ('DERIVATION_REQUIRED','POLICY_EVIDENCE_REQUIRED')
            AND derivation_version IS NOT NULL AND btrim(derivation_version)<>''
            AND output_content_hash IS NOT NULL AND producer_contract_content_hash IS NOT NULL)
        OR (NOT (state='VALID' AND source_kind IN ('DERIVATION_REQUIRED','POLICY_EVIDENCE_REQUIRED'))
            AND output_content_hash IS NULL AND producer_contract_content_hash IS NULL)),
    CHECK (effective_at IS NULL OR (isfinite(effective_at) AND isfinite(available_at) AND isfinite(ingested_at)
        AND effective_at <= available_at AND available_at <= ingested_at))
);

CREATE TABLE analytics.fundamental_value_operand_evidence_v1 (
    assembly_id UUID NOT NULL,
    operand_ordinal INTEGER NOT NULL,
    parent_ordinal INTEGER NOT NULL,
    evidence_id UUID NOT NULL REFERENCES analytics.canonical_evidence_v1 (evidence_id),
    source_content_hash VARCHAR(71) NOT NULL,
    normalized_record_hash VARCHAR(71) NOT NULL,
    source_revision INTEGER NOT NULL,
    dependency_code VARCHAR(128) NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (assembly_id, operand_ordinal, parent_ordinal),
    UNIQUE (assembly_id, operand_ordinal, evidence_id),
    FOREIGN KEY (assembly_id, operand_ordinal) REFERENCES analytics.fundamental_value_assembly_operand_v1 (assembly_id, operand_ordinal),
    CHECK (parent_ordinal > 0 AND source_revision > 0 AND btrim(dependency_code) <> ''),
    CHECK (source_content_hash ~ '^sha256:[0-9a-f]{64}$' AND normalized_record_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (isfinite(effective_at) AND isfinite(available_at) AND isfinite(ingested_at)
        AND effective_at <= available_at AND available_at <= ingested_at)
);

CREATE TABLE analytics.fundamental_value_operand_reason_v1 (
    assembly_id UUID NOT NULL,
    operand_ordinal INTEGER NOT NULL,
    reason_ordinal INTEGER NOT NULL,
    reason_code VARCHAR(128) NOT NULL,
    PRIMARY KEY (assembly_id, operand_ordinal, reason_ordinal),
    UNIQUE (assembly_id, operand_ordinal, reason_code),
    FOREIGN KEY (assembly_id, operand_ordinal) REFERENCES analytics.fundamental_value_assembly_operand_v1 (assembly_id, operand_ordinal),
    CHECK (reason_ordinal > 0 AND btrim(reason_code) <> '')
);

CREATE TABLE analytics.fundamental_value_assembly_seal_v1 (
    assembly_id UUID PRIMARY KEY REFERENCES analytics.fundamental_value_assembly_v1 (assembly_id),
    operand_count INTEGER NOT NULL,
    assembly_reason_count INTEGER NOT NULL,
    operand_reason_count INTEGER NOT NULL,
    operand_evidence_count INTEGER NOT NULL,
    sealed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (operand_count >= 0 AND assembly_reason_count >= 0 AND operand_reason_count >= 0 AND operand_evidence_count >= 0)
);

CREATE TABLE analytics.fundamental_value_assessment_v1 (
    assessment_id UUID PRIMARY KEY,
    assembly_id UUID NOT NULL UNIQUE REFERENCES analytics.fundamental_value_assembly_v1 (assembly_id),
    contract_version VARCHAR(128) NOT NULL,
    sleeve VARCHAR(32) NOT NULL,
    company_type VARCHAR(64) NOT NULL,
    applicability VARCHAR(64) NOT NULL,
    currency CHAR(3) NOT NULL,
    projection_years INTEGER NOT NULL,
    reference_price NUMERIC NOT NULL,
    claim_ceiling VARCHAR(64) NOT NULL,
    model_evidence_label VARCHAR(64) NOT NULL,
    risk_cap_ceiling NUMERIC NOT NULL,
    model_version VARCHAR(128) NOT NULL,
    strategy_version VARCHAR(128) NOT NULL,
    formula_version VARCHAR(128) NOT NULL,
    assumption_policy_version VARCHAR(128) NOT NULL,
    aggregation_version VARCHAR(128) NOT NULL,
    risk_policy_version VARCHAR(128) NOT NULL,
    input_hash VARCHAR(71) NOT NULL,
    result_content_hash VARCHAR(71) NOT NULL,
    deterministic_ranking_authorized BOOLEAN NOT NULL DEFAULT FALSE,
    final_portfolio_weight_authorized BOOLEAN NOT NULL DEFAULT FALSE,
    automatic_brokerage_execution_authorized BOOLEAN NOT NULL DEFAULT FALSE,
    expected_dimension_count INTEGER NOT NULL,
    expected_method_count INTEGER NOT NULL,
    expected_range_count INTEGER NOT NULL,
    expected_condition_count INTEGER NOT NULL,
    expected_risk_reason_count INTEGER NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (contract_version = 'fundamental-value-assessment-persistence-v1.0.0'),
    CHECK (sleeve = 'LONG_TERM_CORE'),
    CHECK (projection_years BETWEEN 3 AND 10 AND reference_price > 0),
    CHECK (analytics.fundamental_value_finite_numeric_v1(reference_price)),
    CHECK (analytics.fundamental_value_finite_numeric_v1(risk_cap_ceiling)),
    CHECK (model_evidence_label = 'NOT_VALIDATED'),
    CHECK (claim_ceiling IN ('FULL_CURRENT_DECISION','LIMITED_MISSING_ADVANCED_EVIDENCE','BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY')),
    CHECK (risk_cap_ceiling IN (0,0.01,0.02)),
    CHECK (claim_ceiling <> 'LIMITED_MISSING_ADVANCED_EVIDENCE' OR risk_cap_ceiling <= 0.01),
    CHECK (claim_ceiling <> 'BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY' OR risk_cap_ceiling = 0),
    CHECK (model_version = 'FUNDAMENTAL-VALUE-v1.0.0'
       AND strategy_version = 'LONG-TERM-CORE-v1.0.0'
       AND formula_version = 'fundamental-value-formulas-v1.1.0'
       AND assumption_policy_version = 'fundamental-value-assumptions-v1.1.0'
       AND aggregation_version = 'FUNDAMENTAL-VALUE-WEIGHTED-MEDIAN-QUANTILE-v1.0.0'
       AND risk_policy_version = 'LONG-TERM-CORE-RISK-CAP-TIERS-v1.0.0'),
    CHECK (input_hash ~ '^sha256:[0-9a-f]{64}$' AND result_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (NOT deterministic_ranking_authorized AND NOT final_portfolio_weight_authorized AND NOT automatic_brokerage_execution_authorized),
    CHECK (company_type = 'MATURE_OPERATING_COMPANY' AND applicability = 'APPLICABLE'),
    CHECK (expected_dimension_count = 5 AND expected_method_count = 4
       AND expected_range_count = 3 AND expected_condition_count = 8 AND expected_risk_reason_count >= 1),
    UNIQUE (assembly_id, model_version, formula_version, assumption_policy_version)
);

CREATE TABLE analytics.fundamental_value_dimension_v1 (
    assessment_id UUID NOT NULL REFERENCES analytics.fundamental_value_assessment_v1 (assessment_id),
    dimension_ordinal INTEGER NOT NULL,
    dimension_code VARCHAR(64) NOT NULL,
    state VARCHAR(32) NOT NULL,
    score NUMERIC,
    expected_reason_count INTEGER NOT NULL,
    PRIMARY KEY (assessment_id, dimension_ordinal),
    UNIQUE (assessment_id, dimension_code),
    CHECK (dimension_ordinal > 0),
    CHECK (dimension_code IN ('COMPANY_QUALITY','FINANCIAL_RESILIENCE','EARNINGS_AND_CASH_FLOW_QUALITY','CAPITAL_ALLOCATION_QUALITY','DOWNSIDE_RISK')),
    CHECK (state IN ('VALID','MISSING','STALE','INVALID','NOT_APPLICABLE','EXCLUDED')),
    CHECK (score IS NULL OR analytics.fundamental_value_finite_numeric_v1(score)),
    CHECK ((state = 'VALID' AND score BETWEEN 0 AND 100 AND expected_reason_count = 0)
        OR (state <> 'VALID' AND score IS NULL AND expected_reason_count > 0))
);

CREATE TABLE analytics.fundamental_value_valuation_method_v1 (
    assessment_id UUID NOT NULL REFERENCES analytics.fundamental_value_assessment_v1 (assessment_id),
    method_ordinal INTEGER NOT NULL,
    method_code VARCHAR(64) NOT NULL,
    method_role VARCHAR(32) NOT NULL,
    method_weight NUMERIC NOT NULL,
    state VARCHAR(32) NOT NULL,
    terminal_value_share NUMERIC,
    expected_reason_count INTEGER NOT NULL,
    PRIMARY KEY (assessment_id, method_ordinal),
    UNIQUE (assessment_id, method_code),
    CHECK (method_ordinal > 0),
    CHECK (method_code IN ('FCFF_DCF','NORMALIZED_OWNER_EARNINGS','EARNINGS_POWER','COMPARABLE_CROSS_CHECK')),
    CHECK ((method_code = 'FCFF_DCF' AND method_role='PRIMARY' AND method_weight=0.35)
        OR (method_code='NORMALIZED_OWNER_EARNINGS' AND method_role='PRIMARY' AND method_weight=0.30)
        OR (method_code='EARNINGS_POWER' AND method_role='PRIMARY' AND method_weight=0.25)
        OR (method_code='COMPARABLE_CROSS_CHECK' AND method_role='CROSS_CHECK_ONLY' AND method_weight=0.10)),
    CHECK (method_weight > 0 AND method_weight <= 1),
    CHECK (analytics.fundamental_value_finite_numeric_v1(method_weight)),
    CHECK (terminal_value_share IS NULL OR analytics.fundamental_value_finite_numeric_v1(terminal_value_share)),
    CHECK (state IN ('VALID','MISSING','STALE','INVALID','NOT_APPLICABLE','EXCLUDED')),
    CHECK ((state = 'VALID' AND expected_reason_count = 0) OR (state <> 'VALID' AND expected_reason_count > 0)),
    CHECK (terminal_value_share IS NULL OR (method_code = 'FCFF_DCF' AND state = 'VALID' AND terminal_value_share BETWEEN 0 AND 1))
);

CREATE TABLE analytics.fundamental_value_valuation_scenario_v1 (
    assessment_id UUID NOT NULL,
    method_ordinal INTEGER NOT NULL,
    scenario_ordinal INTEGER NOT NULL,
    scenario_code VARCHAR(16) NOT NULL,
    fair_value_per_share NUMERIC NOT NULL,
    PRIMARY KEY (assessment_id, method_ordinal, scenario_ordinal),
    UNIQUE (assessment_id, method_ordinal, scenario_code),
    FOREIGN KEY (assessment_id, method_ordinal) REFERENCES analytics.fundamental_value_valuation_method_v1 (assessment_id, method_ordinal),
    CHECK (scenario_ordinal BETWEEN 1 AND 3),
    CHECK (scenario_code IN ('LOW','CENTRAL','HIGH')),
    CHECK (analytics.fundamental_value_finite_numeric_v1(fair_value_per_share) AND fair_value_per_share > 0)
);

CREATE TABLE analytics.fundamental_value_ordered_range_v1 (
    assessment_id UUID NOT NULL REFERENCES analytics.fundamental_value_assessment_v1 (assessment_id),
    range_ordinal INTEGER NOT NULL,
    range_code VARCHAR(32) NOT NULL,
    state VARCHAR(32) NOT NULL,
    low_value NUMERIC,
    central_value NUMERIC,
    high_value NUMERIC,
    expected_reason_count INTEGER NOT NULL,
    PRIMARY KEY (assessment_id, range_ordinal),
    UNIQUE (assessment_id, range_code),
    CHECK (range_ordinal BETWEEN 1 AND 3),
    CHECK (range_code IN ('FAIR_VALUE','MARGIN_OF_SAFETY','EXPECTED_RETURN')),
    CHECK (state IN ('VALID','MISSING','STALE','INVALID','NOT_APPLICABLE','EXCLUDED')),
    CHECK ((low_value IS NULL OR analytics.fundamental_value_finite_numeric_v1(low_value))
       AND (central_value IS NULL OR analytics.fundamental_value_finite_numeric_v1(central_value))
       AND (high_value IS NULL OR analytics.fundamental_value_finite_numeric_v1(high_value))),
    CHECK ((state = 'VALID' AND low_value IS NOT NULL AND low_value <= central_value AND central_value <= high_value AND expected_reason_count = 0)
        OR (state <> 'VALID' AND low_value IS NULL AND central_value IS NULL AND high_value IS NULL AND expected_reason_count > 0))
);

CREATE TABLE analytics.fundamental_value_condition_v1 (
    assessment_id UUID NOT NULL REFERENCES analytics.fundamental_value_assessment_v1 (assessment_id),
    condition_kind VARCHAR(32) NOT NULL,
    condition_ordinal INTEGER NOT NULL,
    condition_code VARCHAR(128) NOT NULL,
    state VARCHAR(32) NOT NULL,
    observed_value NUMERIC,
    threshold_value NUMERIC,
    satisfied BOOLEAN,
    expected_reason_count INTEGER NOT NULL,
    PRIMARY KEY (assessment_id, condition_kind, condition_ordinal),
    UNIQUE (assessment_id, condition_kind, condition_code),
    CHECK (condition_kind IN ('THESIS','COUNTER_THESIS','INVALIDATION')),
    CHECK (condition_ordinal > 0),
    CHECK (state IN ('VALID','MISSING','STALE','INVALID','NOT_APPLICABLE','EXCLUDED')),
    CHECK ((observed_value IS NULL OR analytics.fundamental_value_finite_numeric_v1(observed_value))
       AND (threshold_value IS NULL OR analytics.fundamental_value_finite_numeric_v1(threshold_value))),
    CHECK ((state = 'VALID' AND observed_value IS NOT NULL AND threshold_value IS NOT NULL AND satisfied IS NOT NULL AND expected_reason_count = 0)
        OR (state <> 'VALID' AND observed_value IS NULL AND satisfied IS NULL AND expected_reason_count > 0))
);

CREATE TABLE analytics.fundamental_value_component_reason_v1 (
    assessment_id UUID NOT NULL REFERENCES analytics.fundamental_value_assessment_v1 (assessment_id),
    component_kind VARCHAR(32) NOT NULL,
    component_code VARCHAR(128) NOT NULL,
    reason_ordinal INTEGER NOT NULL,
    reason_code VARCHAR(128) NOT NULL,
    PRIMARY KEY (assessment_id, component_kind, component_code, reason_ordinal),
    UNIQUE (assessment_id, component_kind, component_code, reason_code),
    CHECK (component_kind IN ('DIMENSION','VALUATION_METHOD','ORDERED_RANGE','CONDITION')),
    CHECK (reason_ordinal > 0 AND btrim(reason_code) <> '')
);

CREATE TABLE analytics.fundamental_value_risk_cap_reason_v1 (
    assessment_id UUID NOT NULL REFERENCES analytics.fundamental_value_assessment_v1 (assessment_id),
    reason_ordinal INTEGER NOT NULL,
    reason_code VARCHAR(128) NOT NULL,
    PRIMARY KEY (assessment_id, reason_ordinal),
    UNIQUE (assessment_id, reason_code),
    CHECK (reason_ordinal > 0 AND btrim(reason_code) <> '')
);

CREATE TABLE analytics.fundamental_value_assessment_seal_v1 (
    assessment_id UUID PRIMARY KEY REFERENCES analytics.fundamental_value_assessment_v1 (assessment_id),
    dimension_count INTEGER NOT NULL,
    method_count INTEGER NOT NULL,
    scenario_count INTEGER NOT NULL,
    range_count INTEGER NOT NULL,
    condition_count INTEGER NOT NULL,
    component_reason_count INTEGER NOT NULL,
    risk_reason_count INTEGER NOT NULL,
    sealed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (dimension_count >= 0 AND method_count >= 0 AND scenario_count >= 0 AND range_count >= 0 AND condition_count >= 0 AND component_reason_count >= 0 AND risk_reason_count >= 0)
);

CREATE FUNCTION analytics.reject_fundamental_value_v1_change()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Fundamental Value v1 records are append-only';
END;
$$;

CREATE FUNCTION analytics.validate_fundamental_value_assembly_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    request_record analytics.evidence_selection_request_v1%ROWTYPE;
    route_record analytics.model_applicability_routing_v1%ROWTYPE;
    listing_record analytics.evidence_listing_identity_v1%ROWTYPE;
    ticker_record analytics.evidence_ticker_assignment_v1%ROWTYPE;
    session_record analytics.evidence_completed_session_v1%ROWTYPE;
    selected_id UUID;
    result_record analytics.evidence_selection_result_v1%ROWTYPE;
    evidence_record analytics.canonical_evidence_v1%ROWTYPE;
    policy_version VARCHAR(128);
    prior_record analytics.fundamental_value_assembly_v1%ROWTYPE;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(concat_ws('|', NEW.security_id, NEW.company_id,
        NEW.instrument_id, NEW.share_class_id, NEW.listing_id, NEW.ticker_assignment_id,
        NEW.assembly_version), 230000));
    SELECT * INTO request_record FROM analytics.evidence_selection_request_v1 WHERE request_id = NEW.classification_request_id;
    SELECT selected_evidence_id INTO selected_id FROM analytics.evidence_selection_result_v1 WHERE request_id = NEW.classification_request_id AND state = 'VALID';
    SELECT * INTO result_record FROM analytics.evidence_selection_result_v1 WHERE request_id = NEW.classification_request_id;
    SELECT * INTO evidence_record FROM analytics.canonical_evidence_v1 WHERE evidence_id = NEW.classification_evidence_id;
    SELECT policy.policy_version INTO policy_version FROM analytics.evidence_selector_policy_v1 policy WHERE policy.id = request_record.policy_id;
    SELECT * INTO route_record FROM analytics.model_applicability_routing_v1 WHERE routing_id = NEW.applicability_routing_id;
    SELECT * INTO listing_record FROM analytics.evidence_listing_identity_v1 WHERE listing_id = NEW.listing_id;
    SELECT * INTO ticker_record FROM analytics.evidence_ticker_assignment_v1 WHERE ticker_assignment_id = NEW.ticker_assignment_id;
    SELECT * INTO session_record FROM analytics.evidence_completed_session_v1 WHERE id = NEW.completed_session_id;
    IF request_record.request_id IS NULL OR selected_id IS DISTINCT FROM NEW.classification_evidence_id
       OR route_record.routing_id IS NULL OR route_record.classification_evidence_id <> NEW.classification_evidence_id
       OR request_record.request_content_hash <> NEW.classification_request_content_hash
       OR result_record.result_content_hash <> NEW.classification_result_content_hash
       OR evidence_record.source_content_hash <> NEW.classification_source_content_hash
       OR evidence_record.normalized_record_hash <> NEW.classification_normalized_record_hash
       OR evidence_record.source_revision <> NEW.classification_source_revision
       OR evidence_record.effective_at <> NEW.classification_effective_at
       OR evidence_record.available_at <> NEW.classification_available_at
       OR evidence_record.ingested_at <> NEW.classification_ingested_at
       OR policy_version <> NEW.classification_selector_policy_version
       OR result_record.selector_version <> NEW.classification_selector_version
       OR evidence_record.freshness_policy_version <> NEW.classification_freshness_policy_version
       OR evidence_record.normalization_version <> NEW.classification_normalization_version
       OR evidence_record.provider_schema_version <> NEW.classification_provider_schema_version
       OR evidence_record.adapter_version <> NEW.classification_adapter_version
       OR route_record.routing_content_hash <> NEW.applicability_routing_content_hash
       OR route_record.routing_revision <> NEW.applicability_routing_revision
       OR route_record.routing_version <> NEW.applicability_routing_version
       OR route_record.company_id <> NEW.company_id OR route_record.company_type <> NEW.company_type
       OR route_record.applicability <> NEW.applicability
       OR request_record.security_id <> NEW.security_id OR request_record.company_id <> NEW.company_id
       OR request_record.instrument_id <> NEW.instrument_id OR request_record.share_class_id <> NEW.share_class_id
       OR request_record.listing_id <> NEW.listing_id OR request_record.ticker_assignment_id <> NEW.ticker_assignment_id
       OR request_record.completed_session_id <> NEW.completed_session_id
       OR listing_record.security_id <> NEW.security_id OR listing_record.mic <> NEW.mic OR listing_record.currency <> NEW.currency
       OR ticker_record.listing_id <> NEW.listing_id OR ticker_record.ticker <> NEW.ticker
       OR session_record.id IS NULL OR session_record.mic <> NEW.mic
       OR request_record.decision_cutoff <> NEW.decision_cutoff
       OR request_record.sealed_ingestion_cutoff <> NEW.sealed_ingestion_cutoff
       OR route_record.effective_at > NEW.decision_cutoff THEN
        RAISE EXCEPTION 'Fundamental Value assembly V22 binding is invalid';
    END IF;
    SELECT * INTO prior_record FROM analytics.fundamental_value_assembly_v1
     WHERE security_id=NEW.security_id AND company_id=NEW.company_id AND instrument_id=NEW.instrument_id
       AND share_class_id=NEW.share_class_id AND listing_id=NEW.listing_id
       AND ticker_assignment_id=NEW.ticker_assignment_id AND assembly_version=NEW.assembly_version
     ORDER BY assembly_revision DESC LIMIT 1;
    IF prior_record.assembly_id IS NULL THEN
        IF NEW.assembly_revision <> 1 OR NEW.supersedes_assembly_id IS NOT NULL THEN
            RAISE EXCEPTION 'Initial Fundamental Value assembly must start revision one';
        END IF;
    ELSIF NEW.supersedes_assembly_id IS DISTINCT FROM prior_record.assembly_id
       OR NEW.assembly_revision <> prior_record.assembly_revision + 1
       OR NEW.security_id <> prior_record.security_id OR NEW.instrument_id <> prior_record.instrument_id
       OR NEW.share_class_id <> prior_record.share_class_id OR NEW.listing_id <> prior_record.listing_id
       OR NEW.ticker_assignment_id <> prior_record.ticker_assignment_id
       OR session_record.session_date < (SELECT session_date FROM analytics.evidence_completed_session_v1
            WHERE id=prior_record.completed_session_id)
       OR NEW.decision_cutoff < prior_record.decision_cutoff
       OR NEW.sealed_ingestion_cutoff < prior_record.sealed_ingestion_cutoff THEN
        RAISE EXCEPTION 'Fundamental Value assembly must supersede the latest revision';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.guard_fundamental_value_assembly_child_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.assembly_id::TEXT, 230001));
    IF EXISTS (SELECT 1 FROM analytics.fundamental_value_assembly_seal_v1 WHERE assembly_id = NEW.assembly_id) THEN
        RAISE EXCEPTION 'Fundamental Value assembly child set is sealed';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_fundamental_value_operand_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    result_record analytics.evidence_selection_result_v1%ROWTYPE;
    request_record analytics.evidence_selection_request_v1%ROWTYPE;
    policy_record analytics.evidence_selector_policy_v1%ROWTYPE;
    evidence_record analytics.canonical_evidence_v1%ROWTYPE;
    assembly_record analytics.fundamental_value_assembly_v1%ROWTYPE;
    session_record analytics.evidence_completed_session_v1%ROWTYPE;
    producer_record analytics.fundamental_value_operand_producer_contract_v1%ROWTYPE;
BEGIN
    IF NEW.state='VALID' AND NEW.source_kind IN ('DERIVATION_REQUIRED','POLICY_EVIDENCE_REQUIRED') THEN
        SELECT * INTO producer_record
        FROM analytics.fundamental_value_operand_producer_contract_v1
        WHERE operand_code=NEW.operand_code AND contract_version=NEW.derivation_version;
        IF producer_record.operand_code IS NULL
           OR producer_record.source_kind<>NEW.source_kind
           OR producer_record.governance_status<>'TEST_ONLY'
           OR producer_record.contract_content_hash<>NEW.producer_contract_content_hash
           OR producer_record.parent_slot_count<>NEW.expected_evidence_count THEN
            RAISE EXCEPTION 'Fundamental Value operand producer contract is unavailable';
        END IF;
    END IF;
    IF NEW.selector_request_id IS NULL THEN RETURN NEW; END IF;
    SELECT * INTO result_record FROM analytics.evidence_selection_result_v1 WHERE request_id = NEW.selector_request_id;
    SELECT * INTO request_record FROM analytics.evidence_selection_request_v1 WHERE request_id = NEW.selector_request_id;
    SELECT * INTO policy_record FROM analytics.evidence_selector_policy_v1 WHERE id=request_record.policy_id;
    SELECT * INTO assembly_record FROM analytics.fundamental_value_assembly_v1 WHERE assembly_id = NEW.assembly_id;
    SELECT * INTO session_record FROM analytics.evidence_completed_session_v1 WHERE id=assembly_record.completed_session_id;
    IF result_record.request_id IS NULL OR result_record.state <> NEW.state
       OR request_record.request_content_hash IS DISTINCT FROM NEW.request_content_hash
       OR result_record.result_content_hash IS DISTINCT FROM NEW.result_content_hash
       OR request_record.security_id<>assembly_record.security_id OR request_record.company_id<>assembly_record.company_id
       OR request_record.instrument_id<>assembly_record.instrument_id OR request_record.share_class_id<>assembly_record.share_class_id
       OR request_record.listing_id<>assembly_record.listing_id OR request_record.ticker_assignment_id<>assembly_record.ticker_assignment_id
       OR request_record.completed_session_id<>assembly_record.completed_session_id
       OR request_record.decision_cutoff<>assembly_record.decision_cutoff OR request_record.sealed_ingestion_cutoff<>assembly_record.sealed_ingestion_cutoff
       OR policy_record.selector_version<>'deterministic-evidence-selector-v1.0.0'
       OR policy_record.required_layer<>'NORMALIZED_OBSERVATION'
       OR (NEW.operand_code='reference_price' AND (policy_record.domain<>'DAILY_PRICE' OR policy_record.field_code<>'CLOSE_PRICE'
          OR policy_record.policy_version<>'daily-price-selection-v1.0.0' OR policy_record.required_normalization_version<>'canonical-equity-v1.0.0'
          OR policy_record.required_strictness_class<>'STRICT_IDENTITY_AND_CHRONOLOGY'
          OR policy_record.required_claim_class<>'CURRENT_ONLY'
          OR policy_record.domain_constraints<>jsonb_build_object(
               'sessionDate',session_record.session_date::TEXT,
               'adjustmentMode','UNADJUSTED','currency',btrim(assembly_record.currency),
               'mic',btrim(assembly_record.mic),'listingId',assembly_record.listing_id::TEXT)))
       OR (NEW.source_kind='DIRECT_FUNDAMENTAL' AND (policy_record.domain<>'FUNDAMENTAL'
          OR policy_record.field_code<>CASE NEW.operand_code WHEN 'diluted_shares' THEN 'DILUTED_SHARES' WHEN 'cash' THEN 'CASH_AND_EQUIVALENTS' WHEN 'debt' THEN 'TOTAL_DEBT' WHEN 'ebit' THEN 'OPERATING_INCOME' WHEN 'capital_expenditures' THEN 'CAPITAL_EXPENDITURE' WHEN 'normalized_free_cash_flow' THEN 'FREE_CASH_FLOW' ELSE '' END
          OR policy_record.required_normalization_version<>'canonical-fundamental-v1.0.0'
          OR policy_record.required_strictness_class<>'STRICT_IDENTITY_AND_CHRONOLOGY'
          OR policy_record.required_claim_class<>'STRICT_PIT'
          OR policy_record.policy_version<>('fundamental-value-'||replace(NEW.operand_code,'_','-')||'-selection-v1.0.0')
          OR NOT policy_record.domain_constraints ?& ARRAY['metricCode','periodEnd','unit','currency']
          OR (SELECT COUNT(*) FROM jsonb_object_keys(policy_record.domain_constraints))<>4
          OR policy_record.domain_constraints->>'metricCode'<>policy_record.field_code
          OR (policy_record.domain_constraints->>'periodEnd')::DATE>session_record.session_date
          OR policy_record.domain_constraints->>'unit'<>CASE NEW.operand_code WHEN 'diluted_shares' THEN 'SHARES' ELSE 'CURRENCY' END
          OR policy_record.domain_constraints->'currency' IS DISTINCT FROM CASE WHEN NEW.operand_code='diluted_shares' THEN 'null'::JSONB ELSE to_jsonb(btrim(assembly_record.currency)) END)) THEN
        RAISE EXCEPTION 'Fundamental Value operand selector seal is invalid';
    END IF;
    IF NEW.selected_evidence_id IS NOT NULL THEN
        SELECT * INTO evidence_record FROM analytics.canonical_evidence_v1 WHERE evidence_id = NEW.selected_evidence_id;
        IF result_record.selected_evidence_id IS DISTINCT FROM NEW.selected_evidence_id
           OR NEW.selected_evidence_id=assembly_record.classification_evidence_id
           OR evidence_record.security_id <> assembly_record.security_id
           OR evidence_record.company_id <> assembly_record.company_id
           OR evidence_record.listing_id <> assembly_record.listing_id
           OR evidence_record.source_content_hash IS DISTINCT FROM NEW.source_content_hash
           OR evidence_record.normalized_record_hash IS DISTINCT FROM NEW.normalized_record_hash
           OR evidence_record.source_revision IS DISTINCT FROM NEW.source_revision
           OR evidence_record.effective_at IS DISTINCT FROM NEW.effective_at
           OR evidence_record.available_at IS DISTINCT FROM NEW.available_at
           OR evidence_record.ingested_at IS DISTINCT FROM NEW.ingested_at
           OR evidence_record.state<>'VALID'
           OR evidence_record.normalization_version IS DISTINCT FROM NEW.normalization_version
           OR evidence_record.freshness_policy_version IS DISTINCT FROM NEW.freshness_policy_version
           OR evidence_record.provider_schema_version IS DISTINCT FROM NEW.provider_schema_version
           OR evidence_record.adapter_version IS DISTINCT FROM NEW.adapter_version
           OR evidence_record.tolerance_policy_version IS DISTINCT FROM NEW.tolerance_policy_version
           OR evidence_record.derivation_version IS DISTINCT FROM NEW.derivation_version
           OR evidence_record.available_at > assembly_record.decision_cutoff
           OR evidence_record.ingested_at > assembly_record.sealed_ingestion_cutoff
           OR (NEW.source_kind='DAILY_PRICE' AND (
                evidence_record.domain<>'DAILY_PRICE'
                OR evidence_record.canonical_data->>'sessionDate'<>session_record.session_date::TEXT
                OR evidence_record.canonical_data->>'adjustmentMode'<>'UNADJUSTED'
                OR evidence_record.canonical_data->>'currency'<>btrim(assembly_record.currency)
                OR NOT evidence_record.canonical_data ? 'close'
                OR NEW.numeric_value IS DISTINCT FROM (evidence_record.canonical_data->>'close')::NUMERIC))
           OR (NEW.source_kind='DIRECT_FUNDAMENTAL' AND (
                evidence_record.domain<>'FUNDAMENTAL'
                OR evidence_record.canonical_data->>'metricCode'<>policy_record.field_code
                OR evidence_record.canonical_data->>'periodEnd'<>policy_record.domain_constraints->>'periodEnd'
                OR evidence_record.canonical_data->>'unit'<>policy_record.domain_constraints->>'unit'
                OR evidence_record.canonical_data->'currency' IS DISTINCT FROM policy_record.domain_constraints->'currency'
                OR NOT evidence_record.canonical_data ? 'numericValue'
                OR NEW.numeric_value IS DISTINCT FROM (evidence_record.canonical_data->>'numericValue')::NUMERIC)) THEN
            RAISE EXCEPTION 'Fundamental Value operand evidence seal is invalid';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_fundamental_value_assembly_seal_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent analytics.fundamental_value_assembly_v1%ROWTYPE; actual_operands INTEGER; actual_reasons INTEGER; actual_operand_reasons INTEGER; actual_operand_evidence INTEGER;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.assembly_id::TEXT, 230001));
    SELECT * INTO parent FROM analytics.fundamental_value_assembly_v1 WHERE assembly_id = NEW.assembly_id;
    SELECT COUNT(*) INTO actual_operands FROM analytics.fundamental_value_assembly_operand_v1 WHERE assembly_id = NEW.assembly_id;
    SELECT COUNT(*) INTO actual_reasons FROM analytics.fundamental_value_assembly_reason_v1 WHERE assembly_id = NEW.assembly_id;
    SELECT COUNT(*) INTO actual_operand_reasons FROM analytics.fundamental_value_operand_reason_v1 WHERE assembly_id = NEW.assembly_id;
    SELECT COUNT(*) INTO actual_operand_evidence FROM analytics.fundamental_value_operand_evidence_v1 WHERE assembly_id = NEW.assembly_id;
    IF actual_operands <> NEW.operand_count OR actual_operands <> parent.expected_operand_count
       OR actual_reasons <> NEW.assembly_reason_count OR actual_reasons <> parent.expected_reason_count
       OR actual_operand_reasons <> NEW.operand_reason_count
       OR actual_operand_evidence <> NEW.operand_evidence_count
       OR EXISTS (SELECT 1 FROM analytics.fundamental_value_assembly_operand_v1 o WHERE o.assembly_id=NEW.assembly_id AND o.expected_evidence_count <> (SELECT COUNT(*) FROM analytics.fundamental_value_operand_evidence_v1 e WHERE e.assembly_id=o.assembly_id AND e.operand_ordinal=o.operand_ordinal))
       OR EXISTS (SELECT 1 FROM analytics.fundamental_value_assembly_operand_v1 o WHERE o.assembly_id=NEW.assembly_id AND o.expected_reason_count <> (SELECT COUNT(*) FROM analytics.fundamental_value_operand_reason_v1 r WHERE r.assembly_id=o.assembly_id AND r.operand_ordinal=o.operand_ordinal))
       OR (parent.applicability='APPLICABLE' AND parent.company_type='MATURE_OPERATING_COMPANY' AND (actual_operands <> 34 OR EXISTS (
            SELECT 1 FROM (VALUES
              (1,'reference_price','DAILY_PRICE'),(2,'diluted_shares','DIRECT_FUNDAMENTAL'),
              (3,'cash','DIRECT_FUNDAMENTAL'),(4,'debt','DIRECT_FUNDAMENTAL'),(5,'ebit','DIRECT_FUNDAMENTAL'),
              (6,'tax_rate','DERIVATION_REQUIRED'),(7,'depreciation_and_amortization','DERIVATION_REQUIRED'),
              (8,'capital_expenditures','DIRECT_FUNDAMENTAL'),(9,'change_in_working_capital','DERIVATION_REQUIRED'),
              (10,'normalized_free_cash_flow','DIRECT_FUNDAMENTAL'),(11,'normalized_after_tax_operating_earnings','DERIVATION_REQUIRED'),
              (12,'ebitda','DERIVATION_REQUIRED'),(13,'comparable_ev_to_ebitda','POLICY_EVIDENCE_REQUIRED'),
              (14,'conservative_growth_rate','DERIVATION_REQUIRED'),(15,'discount_rate','POLICY_EVIDENCE_REQUIRED'),
              (16,'terminal_growth_rate','POLICY_EVIDENCE_REQUIRED'),(17,'net_distribution_yield','DERIVATION_REQUIRED'),
              (18,'return_on_invested_capital','DERIVATION_REQUIRED'),(19,'operating_margin','DERIVATION_REQUIRED'),
              (20,'free_cash_flow_margin','DERIVATION_REQUIRED'),(21,'earnings_stability','DERIVATION_REQUIRED'),
              (22,'cash_flow_stability','DERIVATION_REQUIRED'),(23,'net_debt_to_ebitda','DERIVATION_REQUIRED'),
              (24,'interest_coverage','DERIVATION_REQUIRED'),(25,'current_ratio','DERIVATION_REQUIRED'),
              (26,'diluted_share_growth','DERIVATION_REQUIRED'),(27,'cash_flow_to_net_income','DERIVATION_REQUIRED'),
              (28,'incremental_return_on_invested_capital','DERIVATION_REQUIRED'),(29,'acquisition_discipline','POLICY_EVIDENCE_REQUIRED'),
              (30,'shareholder_distribution_coverage','DERIVATION_REQUIRED'),(31,'cyclicality_risk','POLICY_EVIDENCE_REQUIRED'),
              (32,'concentration_risk','POLICY_EVIDENCE_REQUIRED'),(33,'event_risk','POLICY_EVIDENCE_REQUIRED'),
              (34,'debt_maturity_schedule','POLICY_EVIDENCE_REQUIRED')
            ) expected(ordinal,code,kind)
            LEFT JOIN analytics.fundamental_value_assembly_operand_v1 actual
              ON actual.assembly_id=NEW.assembly_id AND actual.operand_ordinal=expected.ordinal
             AND actual.operand_code=expected.code AND actual.source_kind=expected.kind
             AND actual.required_for_core=(expected.ordinal NOT IN (13,17,34))
            WHERE actual.assembly_id IS NULL
       )))
       OR (parent.core_invocation_authorized AND EXISTS (SELECT 1 FROM analytics.fundamental_value_assembly_operand_v1 o WHERE o.assembly_id=NEW.assembly_id AND o.required_for_core AND o.state<>'VALID'))
       OR (parent.applicability IN ('SPECIALIZED_MODEL_REQUIRED','NOT_APPLICABLE','INSUFFICIENT_EVIDENCE') AND actual_operands <> 0) THEN
        RAISE EXCEPTION 'Fundamental Value assembly seal cardinality is invalid';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_fundamental_value_operand_evidence_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE evidence_record analytics.canonical_evidence_v1%ROWTYPE; assembly_record analytics.fundamental_value_assembly_v1%ROWTYPE; operand_record analytics.fundamental_value_assembly_operand_v1%ROWTYPE; slot_record analytics.fundamental_value_producer_parent_slot_v1%ROWTYPE;
BEGIN
    SELECT * INTO evidence_record FROM analytics.canonical_evidence_v1 WHERE evidence_id=NEW.evidence_id;
    SELECT * INTO assembly_record FROM analytics.fundamental_value_assembly_v1 WHERE assembly_id=NEW.assembly_id;
    SELECT * INTO operand_record FROM analytics.fundamental_value_assembly_operand_v1 WHERE assembly_id=NEW.assembly_id AND operand_ordinal=NEW.operand_ordinal;
    IF operand_record.source_kind IN ('DERIVATION_REQUIRED','POLICY_EVIDENCE_REQUIRED') THEN
        SELECT * INTO slot_record FROM analytics.fundamental_value_producer_parent_slot_v1
        WHERE operand_code=operand_record.operand_code
          AND contract_version=operand_record.derivation_version
          AND parent_ordinal=NEW.parent_ordinal;
    END IF;
    IF evidence_record.evidence_id IS NULL OR evidence_record.state<>'VALID'
       OR evidence_record.security_id<>assembly_record.security_id OR evidence_record.company_id<>assembly_record.company_id
       OR evidence_record.instrument_id<>assembly_record.instrument_id OR evidence_record.share_class_id<>assembly_record.share_class_id
       OR evidence_record.listing_id<>assembly_record.listing_id OR evidence_record.ticker_assignment_id<>assembly_record.ticker_assignment_id
       OR NEW.evidence_id=assembly_record.classification_evidence_id
       OR evidence_record.source_content_hash<>NEW.source_content_hash OR evidence_record.normalized_record_hash<>NEW.normalized_record_hash
       OR evidence_record.source_revision<>NEW.source_revision OR evidence_record.effective_at<>NEW.effective_at
       OR evidence_record.available_at<>NEW.available_at OR evidence_record.ingested_at<>NEW.ingested_at
       OR NEW.available_at>assembly_record.decision_cutoff OR NEW.ingested_at>assembly_record.sealed_ingestion_cutoff
       OR (operand_record.source_kind IN ('DAILY_PRICE','DIRECT_FUNDAMENTAL') AND (
            operand_record.selected_evidence_id<>NEW.evidence_id
            OR NEW.dependency_code <> 'SELECTED_CANONICAL_' || upper(operand_record.operand_code)))
       OR (operand_record.source_kind IN ('DERIVATION_REQUIRED','POLICY_EVIDENCE_REQUIRED') AND (
            slot_record.operand_code IS NULL OR NEW.dependency_code<>slot_record.role_code
            OR evidence_record.domain<>slot_record.domain
            OR evidence_record.canonical_data->>'metricCode'<>slot_record.field_code
            OR evidence_record.canonical_data->>'unit'<>slot_record.unit
            OR evidence_record.canonical_data->>'fiscalPeriod'<>slot_record.fiscal_period
            OR evidence_record.canonical_data->>'periodStart' IS DISTINCT FROM
                CASE WHEN slot_record.period_start IS NULL THEN NULL ELSE slot_record.period_start::TEXT END
            OR evidence_record.canonical_data->>'periodEnd'<>slot_record.period_end::TEXT
            OR (slot_record.currency_rule='MATCH_OUTPUT'
                AND evidence_record.canonical_data->>'currency'<>btrim(assembly_record.currency))
            OR (slot_record.currency_rule='NOT_APPLICABLE'
                AND evidence_record.canonical_data->'currency'<>'null'::JSONB))) THEN
        RAISE EXCEPTION 'Fundamental Value operand parent evidence seal is invalid';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_fundamental_value_assembly_complete_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM analytics.fundamental_value_assembly_seal_v1 WHERE assembly_id=NEW.assembly_id) THEN
        RAISE EXCEPTION 'Fundamental Value assembly is incomplete';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION analytics.validate_fundamental_value_assessment_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE assembly_record analytics.fundamental_value_assembly_v1%ROWTYPE;
BEGIN
    SELECT * INTO assembly_record FROM analytics.fundamental_value_assembly_v1 WHERE assembly_id=NEW.assembly_id;
    IF NOT assembly_record.core_invocation_authorized OR assembly_record.state <> 'VALID'
       OR NOT EXISTS (SELECT 1 FROM analytics.fundamental_value_assembly_seal_v1 WHERE assembly_id=NEW.assembly_id)
       OR NEW.projection_years <> assembly_record.projection_years
       OR NEW.company_type <> assembly_record.company_type OR NEW.applicability <> assembly_record.applicability
       OR NEW.currency <> assembly_record.currency OR NEW.input_hash <> assembly_record.core_input_hash
       OR NEW.reference_price IS DISTINCT FROM (SELECT numeric_value FROM analytics.fundamental_value_assembly_operand_v1
            WHERE assembly_id=NEW.assembly_id AND operand_code='reference_price' AND state='VALID')
       OR NEW.model_version <> assembly_record.model_version OR NEW.strategy_version <> assembly_record.strategy_version
       OR NEW.formula_version <> assembly_record.formula_version OR NEW.assumption_policy_version <> assembly_record.assumption_policy_version
       OR NEW.aggregation_version <> assembly_record.aggregation_version OR NEW.risk_policy_version <> assembly_record.risk_policy_version THEN
        RAISE EXCEPTION 'Fundamental Value assessment assembly binding is invalid';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.guard_fundamental_value_assessment_child_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.assessment_id::TEXT, 230002));
    IF EXISTS (SELECT 1 FROM analytics.fundamental_value_assessment_seal_v1 WHERE assessment_id=NEW.assessment_id) THEN
        RAISE EXCEPTION 'Fundamental Value assessment child set is sealed';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_fundamental_value_assessment_seal_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE parent analytics.fundamental_value_assessment_v1%ROWTYPE; dimensions INTEGER; methods INTEGER; scenarios INTEGER; ranges INTEGER; conditions INTEGER; component_reasons INTEGER; risk_reasons INTEGER;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.assessment_id::TEXT, 230002));
    SELECT * INTO parent FROM analytics.fundamental_value_assessment_v1 WHERE assessment_id=NEW.assessment_id;
    SELECT COUNT(*) INTO dimensions FROM analytics.fundamental_value_dimension_v1 WHERE assessment_id=NEW.assessment_id;
    SELECT COUNT(*) INTO methods FROM analytics.fundamental_value_valuation_method_v1 WHERE assessment_id=NEW.assessment_id;
    SELECT COUNT(*) INTO scenarios FROM analytics.fundamental_value_valuation_scenario_v1 WHERE assessment_id=NEW.assessment_id;
    SELECT COUNT(*) INTO ranges FROM analytics.fundamental_value_ordered_range_v1 WHERE assessment_id=NEW.assessment_id;
    SELECT COUNT(*) INTO conditions FROM analytics.fundamental_value_condition_v1 WHERE assessment_id=NEW.assessment_id;
    SELECT COUNT(*) INTO component_reasons FROM analytics.fundamental_value_component_reason_v1 WHERE assessment_id=NEW.assessment_id;
    SELECT COUNT(*) INTO risk_reasons FROM analytics.fundamental_value_risk_cap_reason_v1 WHERE assessment_id=NEW.assessment_id;
    IF dimensions<>NEW.dimension_count OR dimensions<>parent.expected_dimension_count OR methods<>NEW.method_count OR methods<>parent.expected_method_count
       OR scenarios<>NEW.scenario_count OR ranges<>NEW.range_count OR ranges<>parent.expected_range_count
       OR conditions<>NEW.condition_count OR conditions<>parent.expected_condition_count OR component_reasons<>NEW.component_reason_count
       OR risk_reasons<>NEW.risk_reason_count OR risk_reasons<>parent.expected_risk_reason_count
       OR EXISTS (SELECT 1 FROM (VALUES (1,'COMPANY_QUALITY'),(2,'FINANCIAL_RESILIENCE'),(3,'EARNINGS_AND_CASH_FLOW_QUALITY'),(4,'CAPITAL_ALLOCATION_QUALITY'),(5,'DOWNSIDE_RISK')) e(ord,code)
          LEFT JOIN analytics.fundamental_value_dimension_v1 d ON d.assessment_id=NEW.assessment_id AND d.dimension_ordinal=e.ord AND d.dimension_code=e.code WHERE d.assessment_id IS NULL)
       OR EXISTS (SELECT 1 FROM (VALUES (1,'FCFF_DCF','PRIMARY'),(2,'NORMALIZED_OWNER_EARNINGS','PRIMARY'),(3,'EARNINGS_POWER','PRIMARY'),(4,'COMPARABLE_CROSS_CHECK','CROSS_CHECK_ONLY')) e(ord,code,role)
          LEFT JOIN analytics.fundamental_value_valuation_method_v1 m ON m.assessment_id=NEW.assessment_id AND m.method_ordinal=e.ord AND m.method_code=e.code AND m.method_role=e.role WHERE m.assessment_id IS NULL)
       OR EXISTS (SELECT 1 FROM (VALUES (1,'FAIR_VALUE'),(2,'MARGIN_OF_SAFETY'),(3,'EXPECTED_RETURN')) e(ord,code)
          LEFT JOIN analytics.fundamental_value_ordered_range_v1 r ON r.assessment_id=NEW.assessment_id AND r.range_ordinal=e.ord AND r.range_code=e.code WHERE r.assessment_id IS NULL)
       OR EXISTS (SELECT 1 FROM (VALUES
          ('THESIS',1,'QUALITY_AT_LEAST_65'),('THESIS',2,'RESILIENCE_AT_LEAST_60'),('THESIS',3,'CONSERVATIVE_MARGIN_OF_SAFETY_AT_LEAST_15_PERCENT'),
          ('COUNTER_THESIS',1,'DOWNSIDE_RISK_AT_LEAST_60'),('COUNTER_THESIS',2,'NET_DEBT_TO_EBITDA_ABOVE_3'),
          ('INVALIDATION',1,'ROIC_BELOW_8_PERCENT'),('INVALIDATION',2,'INTEREST_COVERAGE_BELOW_3'),('INVALIDATION',3,'CENTRAL_MARGIN_OF_SAFETY_BELOW_ZERO')) e(kind,ord,code)
          LEFT JOIN analytics.fundamental_value_condition_v1 c ON c.assessment_id=NEW.assessment_id AND c.condition_kind=e.kind AND c.condition_ordinal=e.ord AND c.condition_code=e.code WHERE c.assessment_id IS NULL)
       OR (SELECT COUNT(*) FROM analytics.fundamental_value_valuation_method_v1 WHERE assessment_id=NEW.assessment_id AND method_role='PRIMARY') <> 3
       OR EXISTS (SELECT 1 FROM analytics.fundamental_value_valuation_method_v1 m WHERE m.assessment_id=NEW.assessment_id AND m.state='VALID' AND 3 <> (SELECT COUNT(*) FROM analytics.fundamental_value_valuation_scenario_v1 s WHERE s.assessment_id=m.assessment_id AND s.method_ordinal=m.method_ordinal))
       OR EXISTS (SELECT 1 FROM analytics.fundamental_value_valuation_method_v1 m WHERE m.assessment_id=NEW.assessment_id AND m.state<>'VALID' AND 0 <> (SELECT COUNT(*) FROM analytics.fundamental_value_valuation_scenario_v1 s WHERE s.assessment_id=m.assessment_id AND s.method_ordinal=m.method_ordinal))
       OR EXISTS (SELECT 1 FROM analytics.fundamental_value_valuation_method_v1 m WHERE m.assessment_id=NEW.assessment_id AND m.state='VALID' AND NOT EXISTS (
            SELECT 1 FROM analytics.fundamental_value_valuation_scenario_v1 low
            JOIN analytics.fundamental_value_valuation_scenario_v1 central ON central.assessment_id=low.assessment_id AND central.method_ordinal=low.method_ordinal AND central.scenario_ordinal=2 AND central.scenario_code='CENTRAL'
            JOIN analytics.fundamental_value_valuation_scenario_v1 high ON high.assessment_id=low.assessment_id AND high.method_ordinal=low.method_ordinal AND high.scenario_ordinal=3 AND high.scenario_code='HIGH'
            WHERE low.assessment_id=m.assessment_id AND low.method_ordinal=m.method_ordinal AND low.scenario_ordinal=1 AND low.scenario_code='LOW'
              AND low.fair_value_per_share <= central.fair_value_per_share AND central.fair_value_per_share <= high.fair_value_per_share))
       OR EXISTS (SELECT 1 FROM analytics.fundamental_value_dimension_v1 d WHERE d.assessment_id=NEW.assessment_id AND d.expected_reason_count <> (SELECT COUNT(*) FROM analytics.fundamental_value_component_reason_v1 r WHERE r.assessment_id=d.assessment_id AND r.component_kind='DIMENSION' AND r.component_code=d.dimension_code))
       OR EXISTS (SELECT 1 FROM analytics.fundamental_value_valuation_method_v1 m WHERE m.assessment_id=NEW.assessment_id AND m.expected_reason_count <> (SELECT COUNT(*) FROM analytics.fundamental_value_component_reason_v1 r WHERE r.assessment_id=m.assessment_id AND r.component_kind='VALUATION_METHOD' AND r.component_code=m.method_code))
       OR EXISTS (SELECT 1 FROM analytics.fundamental_value_ordered_range_v1 o WHERE o.assessment_id=NEW.assessment_id AND o.expected_reason_count <> (SELECT COUNT(*) FROM analytics.fundamental_value_component_reason_v1 r WHERE r.assessment_id=o.assessment_id AND r.component_kind='ORDERED_RANGE' AND r.component_code=o.range_code))
       OR EXISTS (SELECT 1 FROM analytics.fundamental_value_condition_v1 c WHERE c.assessment_id=NEW.assessment_id AND c.expected_reason_count <> (SELECT COUNT(*) FROM analytics.fundamental_value_component_reason_v1 r WHERE r.assessment_id=c.assessment_id AND r.component_kind='CONDITION' AND r.component_code=c.condition_code))
       OR EXISTS (SELECT 1 FROM analytics.fundamental_value_component_reason_v1 r WHERE r.assessment_id=NEW.assessment_id AND NOT (
            (r.component_kind='DIMENSION' AND EXISTS (SELECT 1 FROM analytics.fundamental_value_dimension_v1 d WHERE d.assessment_id=r.assessment_id AND d.dimension_code=r.component_code))
         OR (r.component_kind='VALUATION_METHOD' AND EXISTS (SELECT 1 FROM analytics.fundamental_value_valuation_method_v1 m WHERE m.assessment_id=r.assessment_id AND m.method_code=r.component_code))
         OR (r.component_kind='ORDERED_RANGE' AND EXISTS (SELECT 1 FROM analytics.fundamental_value_ordered_range_v1 o WHERE o.assessment_id=r.assessment_id AND o.range_code=r.component_code))
         OR (r.component_kind='CONDITION' AND EXISTS (SELECT 1 FROM analytics.fundamental_value_condition_v1 c WHERE c.assessment_id=r.assessment_id AND c.condition_code=r.component_code)))) THEN
        RAISE EXCEPTION 'Fundamental Value assessment seal cardinality is invalid';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_fundamental_value_assessment_complete_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM analytics.fundamental_value_assessment_seal_v1 WHERE assessment_id=NEW.assessment_id) THEN
        RAISE EXCEPTION 'Fundamental Value assessment is incomplete';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER tr_validate_fv_assembly BEFORE INSERT ON analytics.fundamental_value_assembly_v1 FOR EACH ROW EXECUTE FUNCTION analytics.validate_fundamental_value_assembly_v1();
CREATE CONSTRAINT TRIGGER tr_fv_assembly_complete AFTER INSERT ON analytics.fundamental_value_assembly_v1 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analytics.validate_fundamental_value_assembly_complete_v1();
CREATE TRIGGER tr_guard_fv_assembly_reason BEFORE INSERT ON analytics.fundamental_value_assembly_reason_v1 FOR EACH ROW EXECUTE FUNCTION analytics.guard_fundamental_value_assembly_child_v1();
CREATE TRIGGER tr_guard_fv_operand BEFORE INSERT ON analytics.fundamental_value_assembly_operand_v1 FOR EACH ROW EXECUTE FUNCTION analytics.guard_fundamental_value_assembly_child_v1();
CREATE TRIGGER tr_validate_fv_operand BEFORE INSERT ON analytics.fundamental_value_assembly_operand_v1 FOR EACH ROW EXECUTE FUNCTION analytics.validate_fundamental_value_operand_v1();
CREATE TRIGGER tr_guard_fv_operand_reason BEFORE INSERT ON analytics.fundamental_value_operand_reason_v1 FOR EACH ROW EXECUTE FUNCTION analytics.guard_fundamental_value_assembly_child_v1();
CREATE TRIGGER tr_guard_fv_operand_evidence BEFORE INSERT ON analytics.fundamental_value_operand_evidence_v1 FOR EACH ROW EXECUTE FUNCTION analytics.guard_fundamental_value_assembly_child_v1();
CREATE TRIGGER tr_validate_fv_operand_evidence BEFORE INSERT ON analytics.fundamental_value_operand_evidence_v1 FOR EACH ROW EXECUTE FUNCTION analytics.validate_fundamental_value_operand_evidence_v1();
CREATE TRIGGER tr_validate_fv_assembly_seal BEFORE INSERT ON analytics.fundamental_value_assembly_seal_v1 FOR EACH ROW EXECUTE FUNCTION analytics.validate_fundamental_value_assembly_seal_v1();
CREATE TRIGGER tr_validate_fv_assessment BEFORE INSERT ON analytics.fundamental_value_assessment_v1 FOR EACH ROW EXECUTE FUNCTION analytics.validate_fundamental_value_assessment_v1();
CREATE CONSTRAINT TRIGGER tr_fv_assessment_complete AFTER INSERT ON analytics.fundamental_value_assessment_v1 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analytics.validate_fundamental_value_assessment_complete_v1();

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['fundamental_value_dimension_v1','fundamental_value_valuation_method_v1','fundamental_value_valuation_scenario_v1','fundamental_value_ordered_range_v1','fundamental_value_condition_v1','fundamental_value_component_reason_v1','fundamental_value_risk_cap_reason_v1'] LOOP
        EXECUTE format('CREATE TRIGGER tr_guard_%s BEFORE INSERT ON analytics.%I FOR EACH ROW EXECUTE FUNCTION analytics.guard_fundamental_value_assessment_child_v1()', table_name, table_name);
    END LOOP;
END;
$$;
CREATE TRIGGER tr_validate_fv_assessment_seal BEFORE INSERT ON analytics.fundamental_value_assessment_seal_v1 FOR EACH ROW EXECUTE FUNCTION analytics.validate_fundamental_value_assessment_seal_v1();

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['fundamental_value_assembly_v1','fundamental_value_assembly_reason_v1','fundamental_value_assembly_operand_v1','fundamental_value_operand_evidence_v1','fundamental_value_operand_reason_v1','fundamental_value_assembly_seal_v1','fundamental_value_assessment_v1','fundamental_value_dimension_v1','fundamental_value_valuation_method_v1','fundamental_value_valuation_scenario_v1','fundamental_value_ordered_range_v1','fundamental_value_condition_v1','fundamental_value_component_reason_v1','fundamental_value_risk_cap_reason_v1','fundamental_value_assessment_seal_v1'] LOOP
        EXECUTE format('CREATE TRIGGER tr_%s_append_only BEFORE UPDATE OR DELETE ON analytics.%I FOR EACH ROW EXECUTE FUNCTION analytics.reject_fundamental_value_v1_change()', table_name, table_name);
    END LOOP;
END;
$$;
CREATE TRIGGER tr_fundamental_value_operand_producer_contract_v1_append_only
BEFORE UPDATE OR DELETE ON analytics.fundamental_value_operand_producer_contract_v1
FOR EACH ROW EXECUTE FUNCTION analytics.reject_fundamental_value_v1_change();
CREATE TRIGGER tr_fundamental_value_producer_parent_slot_v1_append_only
BEFORE UPDATE OR DELETE ON analytics.fundamental_value_producer_parent_slot_v1
FOR EACH ROW EXECUTE FUNCTION analytics.reject_fundamental_value_v1_change();

DO $$
DECLARE table_name TEXT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='analytics_fundamental_value_writer_v1') THEN
        CREATE ROLE analytics_fundamental_value_writer_v1 NOLOGIN;
    END IF;
    GRANT USAGE ON SCHEMA analytics TO analytics_fundamental_value_writer_v1;
    GRANT SELECT ON analytics.security, analytics.evidence_company_identity_v1,
        analytics.evidence_instrument_identity_v1, analytics.evidence_share_class_identity_v1,
        analytics.evidence_listing_identity_v1, analytics.evidence_ticker_assignment_v1,
        analytics.evidence_completed_session_v1, analytics.evidence_selection_request_v1,
        analytics.evidence_selection_result_v1, analytics.evidence_selector_policy_v1,
        analytics.canonical_evidence_v1, analytics.model_applicability_routing_v1
        TO analytics_fundamental_value_writer_v1;
    GRANT SELECT ON analytics.fundamental_value_operand_producer_contract_v1,
        analytics.fundamental_value_producer_parent_slot_v1
        TO analytics_fundamental_value_writer_v1, analytics_reader;
    REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON
        analytics.fundamental_value_operand_producer_contract_v1,
        analytics.fundamental_value_producer_parent_slot_v1
        FROM analytics_writer, analytics_fundamental_value_writer_v1, PUBLIC;
    FOREACH table_name IN ARRAY ARRAY['fundamental_value_assembly_v1','fundamental_value_assembly_reason_v1','fundamental_value_assembly_operand_v1','fundamental_value_operand_evidence_v1','fundamental_value_operand_reason_v1','fundamental_value_assembly_seal_v1','fundamental_value_assessment_v1','fundamental_value_dimension_v1','fundamental_value_valuation_method_v1','fundamental_value_valuation_scenario_v1','fundamental_value_ordered_range_v1','fundamental_value_condition_v1','fundamental_value_component_reason_v1','fundamental_value_risk_cap_reason_v1','fundamental_value_assessment_seal_v1'] LOOP
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON analytics.%I FROM analytics_writer, PUBLIC', table_name);
        EXECUTE format('GRANT SELECT, INSERT ON analytics.%I TO analytics_fundamental_value_writer_v1', table_name);
        EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON analytics.%I FROM analytics_fundamental_value_writer_v1', table_name);
        EXECUTE format('GRANT SELECT ON analytics.%I TO analytics_reader', table_name);
    END LOOP;
END;
$$;

CREATE INDEX ix_fv_assembly_security_v1 ON analytics.fundamental_value_assembly_v1 (security_id, decision_cutoff DESC);
CREATE INDEX ix_fv_operand_evidence_v1 ON analytics.fundamental_value_assembly_operand_v1 (selected_evidence_id);
CREATE INDEX ix_fv_assessment_assembly_v1 ON analytics.fundamental_value_assessment_v1 (assembly_id);

COMMENT ON TABLE analytics.fundamental_value_assembly_v1 IS 'Append-only, V22-bound Fundamental Value input assembly; no raw retention governance.';
COMMENT ON TABLE analytics.fundamental_value_assessment_v1 IS 'Append-only deterministic LONG_TERM_CORE ceiling result; never a final portfolio weight or brokerage action.';
