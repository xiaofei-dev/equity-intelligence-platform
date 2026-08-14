CREATE TABLE analytics.quant_research_decision_v1 (
    decision_id UUID PRIMARY KEY,
    contract_version VARCHAR(128) NOT NULL,
    projection_version VARCHAR(128) NOT NULL,
    assembly_version VARCHAR(128) NOT NULL,
    model_version VARCHAR(128) NOT NULL,
    strategy_version VARCHAR(128) NOT NULL,
    formula_version VARCHAR(128) NOT NULL,
    entry_exit_policy_version VARCHAR(128) NOT NULL,
    model_evidence_label VARCHAR(32) NOT NULL,
    decision_date DATE NOT NULL,
    rebalance_ordinal INTEGER NOT NULL,
    expected_security_count INTEGER NOT NULL,
    assembly_manifest_hash VARCHAR(71) NOT NULL,
    decision_content_hash VARCHAR(71) NOT NULL UNIQUE,
    canonical_body_text TEXT NOT NULL,
    payload_sha256 VARCHAR(71) NOT NULL UNIQUE,
    canonical_payload_text TEXT NOT NULL,
    canonical_payload JSONB NOT NULL,
    deterministic_research_signal_authorized BOOLEAN NOT NULL,
    deterministic_final_weight_authorized BOOLEAN NOT NULL,
    automatic_brokerage_execution_authorized BOOLEAN NOT NULL,
    llm_signal_or_weight_authority BOOLEAN NOT NULL,
    future_return_guaranteed BOOLEAN NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL
        DEFAULT date_trunc('second', CURRENT_TIMESTAMP),
    CONSTRAINT ck_quant_research_decision_contract_v1 CHECK (
        contract_version = 'quant-trading-research-decision-v1.1.0'
        AND projection_version = 'quant-trading-public-projection-v1.1.0'
        AND assembly_version = 'quant-trading-v22-assembly-v1.1.0'
        AND model_version = 'QUANT-TRADING-v1.1.0'
        AND strategy_version = 'DUAL-MOMENTUM-TREND-v1.1.0'
        AND formula_version = 'DUAL-MOMENTUM-TREND-FORMULAS-v1.1.0'
        AND entry_exit_policy_version =
            'DUAL-MOMENTUM-TREND-ENTRY-EXIT-v1.1.0'
        AND model_evidence_label = 'NOT_VALIDATED'
        AND rebalance_ordinal >= 0
        AND rebalance_ordinal % 5 = 0
        AND expected_security_count >= 20
        AND deterministic_research_signal_authorized
        AND NOT deterministic_final_weight_authorized
        AND NOT automatic_brokerage_execution_authorized
        AND NOT llm_signal_or_weight_authority
        AND NOT future_return_guaranteed
        AND date_trunc('second', recorded_at) = recorded_at
    ),
    CONSTRAINT ck_quant_research_decision_hash_v1 CHECK (
        assembly_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
        AND decision_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND payload_sha256 ~ '^sha256:[0-9a-f]{64}$'
        AND decision_content_hash = 'sha256:' ||
            encode(sha256(convert_to(canonical_body_text, 'UTF8')), 'hex')
        AND payload_sha256 = 'sha256:' ||
            encode(sha256(convert_to(canonical_payload_text, 'UTF8')), 'hex')
        AND canonical_payload_text::jsonb = canonical_payload
    ),
    CONSTRAINT ck_quant_research_decision_payload_v1 CHECK (
        jsonb_typeof(canonical_payload) = 'object'
        AND canonical_payload->>'decisionId' = decision_id::text
        AND canonical_payload->>'contractVersion' = contract_version
        AND canonical_payload->>'projectionVersion' = projection_version
        AND canonical_payload->>'assemblyVersion' = assembly_version
        AND canonical_payload->>'modelVersion' = model_version
        AND canonical_payload->>'strategyVersion' = strategy_version
        AND canonical_payload->>'formulaVersion' = formula_version
        AND canonical_payload->>'entryExitPolicyVersion' =
            entry_exit_policy_version
        AND canonical_payload->>'modelEvidenceLabel' = model_evidence_label
        AND canonical_payload->>'decisionDate' =
            to_char(decision_date, 'YYYY-MM-DD')
        AND (canonical_payload->>'rebalanceOrdinal')::integer =
            rebalance_ordinal
        AND (canonical_payload->>'expectedSecurityCount')::integer =
            expected_security_count
        AND canonical_payload->>'assemblyManifestHash' =
            assembly_manifest_hash
        AND canonical_payload->>'contentHash' = decision_content_hash
        AND jsonb_typeof(canonical_payload->'signals') = 'array'
        AND jsonb_array_length(canonical_payload->'signals') =
            expected_security_count
        AND canonical_payload->'authority' = jsonb_build_object(
            'automaticBrokerageExecution', false,
            'deterministicFinalPortfolioWeight', false,
            'deterministicResearchSignal', true,
            'futureReturnGuaranteed', false,
            'llmSignalOrWeightAuthority', false
        )
        AND NOT jsonb_path_exists(canonical_payload, '$.**.finalWeight')
        AND NOT jsonb_path_exists(canonical_payload, '$.**.orderQuantity')
        AND NOT jsonb_path_exists(canonical_payload, '$.**.brokerageInstruction')
    )
);

CREATE FUNCTION analytics.validate_quant_research_decision_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    actual_count INTEGER;
    distinct_count INTEGER;
    ordered_ids TEXT[];
BEGIN
    SELECT count(*), count(DISTINCT item->>'securityId'),
           array_agg(item->>'securityId' ORDER BY item->>'securityId')
      INTO actual_count, distinct_count, ordered_ids
    FROM jsonb_array_elements(NEW.canonical_payload->'signals') item;

    IF actual_count <> NEW.expected_security_count
       OR distinct_count <> NEW.expected_security_count
       OR ordered_ids <> ARRAY(
            SELECT item->>'securityId'
            FROM jsonb_array_elements(NEW.canonical_payload->'signals') item
       )
       OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements(NEW.canonical_payload->'signals') item
            WHERE item->>'securityId' !~
                '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
               OR item->>'researchClassification' NOT IN (
                    'ENTRY_CANDIDATE','HOLD_REVIEW','EXIT_REVIEW','NO_SIGNAL',
                    'NOT_APPLICABLE','INSUFFICIENT_EVIDENCE'
               )
               OR item->'rawSignal'->>'state' NOT IN (
                    'ELIGIBLE','INELIGIBLE','MISSING','INVALID'
               )
               OR item->'ranking'->>'state' NOT IN (
                    'ENTRY_ELIGIBLE','HOLD_ELIGIBLE','EXIT_ELIGIBLE','NOT_RANKED'
               )
       ) THEN
        RAISE EXCEPTION 'Quant research decision signal set is invalid';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER tr_validate_quant_research_decision_v1
BEFORE INSERT ON analytics.quant_research_decision_v1
FOR EACH ROW EXECUTE FUNCTION analytics.validate_quant_research_decision_v1();

CREATE FUNCTION analytics.reject_quant_research_decision_change_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Quant research decision v1 is append-only';
END;
$$;

CREATE TRIGGER tr_reject_quant_research_decision_change_v1
BEFORE UPDATE OR DELETE ON analytics.quant_research_decision_v1
FOR EACH ROW EXECUTE FUNCTION
    analytics.reject_quant_research_decision_change_v1();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'analytics_quant_research_writer_v1'
    ) THEN
        CREATE ROLE analytics_quant_research_writer_v1 NOLOGIN;
    END IF;
END;
$$;

REVOKE ALL ON analytics.quant_research_decision_v1 FROM PUBLIC;
GRANT USAGE ON SCHEMA analytics TO analytics_quant_research_writer_v1;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON analytics.quant_research_decision_v1 FROM analytics_writer, PUBLIC;
GRANT SELECT, INSERT ON analytics.quant_research_decision_v1
    TO analytics_quant_research_writer_v1;
REVOKE UPDATE, DELETE, TRUNCATE ON analytics.quant_research_decision_v1
    FROM analytics_quant_research_writer_v1;
GRANT SELECT ON analytics.quant_research_decision_v1 TO analytics_reader;

COMMENT ON TABLE analytics.quant_research_decision_v1 IS
    'Append-only public-safe Quant v1.1 research projection. No final weights, brokerage instructions, or provider values.';
