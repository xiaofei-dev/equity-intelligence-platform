\set ON_ERROR_STOP on

DO $$
DECLARE
    decision_id_value UUID := '27000000-0000-4000-8000-000000000001';
    body JSONB;
    body_text TEXT;
    content_hash TEXT;
    payload JSONB;
    payload_text TEXT;
    payload_hash TEXT;
BEGIN
    SELECT jsonb_build_object(
        'contractVersion', 'quant-trading-research-decision-v1.1.0',
        'projectionVersion', 'quant-trading-public-projection-v1.1.0',
        'assemblyVersion', 'quant-trading-v22-assembly-v1.1.0',
        'modelVersion', 'QUANT-TRADING-v1.1.0',
        'strategyVersion', 'DUAL-MOMENTUM-TREND-v1.1.0',
        'formulaVersion', 'DUAL-MOMENTUM-TREND-FORMULAS-v1.1.0',
        'entryExitPolicyVersion', 'DUAL-MOMENTUM-TREND-ENTRY-EXIT-v1.1.0',
        'modelEvidenceLabel', 'NOT_VALIDATED',
        'decisionDate', '2026-08-13',
        'rebalanceOrdinal', 0,
        'expectedSecurityCount', 20,
        'assemblyManifestHash', 'sha256:' || repeat('a', 64),
        'signals', jsonb_agg(
            jsonb_build_object(
                'securityId', format(
                    '27000000-0000-4000-8000-%s',
                    lpad(series_number::text, 12, '0')
                ),
                'assemblyState', 'MISSING',
                'applicability', 'INSUFFICIENT_EVIDENCE',
                'assemblyReasonCodes', jsonb_build_array('TEST_EVIDENCE_MISSING'),
                'rawSignal', jsonb_build_object(
                    'state', 'MISSING',
                    'reasonCodes', jsonb_build_array('TEST_EVIDENCE_MISSING'),
                    'inputHash', 'sha256:' || repeat('b', 64),
                    'contentHash', 'sha256:' || repeat('c', 64),
                    'signalClose', NULL,
                    'features', NULL
                ),
                'ranking', jsonb_build_object(
                    'state', 'NOT_RANKED',
                    'rank', NULL,
                    'crossSectionCount', 0,
                    'momentum252Percentile', NULL,
                    'momentum126Percentile', NULL,
                    'compositeScore', NULL,
                    'crossSectionHash', 'sha256:' || repeat('d', 64),
                    'contentHash', 'sha256:' || repeat('e', 64)
                ),
                'entryPlan', NULL,
                'researchClassification', 'INSUFFICIENT_EVIDENCE'
            ) ORDER BY series_number
        ),
        'authority', jsonb_build_object(
            'deterministicResearchSignal', true,
            'deterministicFinalPortfolioWeight', false,
            'automaticBrokerageExecution', false,
            'llmSignalOrWeightAuthority', false,
            'futureReturnGuaranteed', false
        )
    ) INTO body
    FROM generate_series(1, 20) AS series_number;

    body_text := body::text;
    content_hash := 'sha256:' ||
        encode(sha256(convert_to(body_text, 'UTF8')), 'hex');
    payload := body || jsonb_build_object(
        'decisionId', decision_id_value::text,
        'contentHash', content_hash
    );
    payload_text := payload::text;
    payload_hash := 'sha256:' ||
        encode(sha256(convert_to(payload_text, 'UTF8')), 'hex');

    SET LOCAL ROLE analytics_quant_research_writer_v1;
    INSERT INTO analytics.quant_research_decision_v1 (
        decision_id,
        contract_version,
        projection_version,
        assembly_version,
        model_version,
        strategy_version,
        formula_version,
        entry_exit_policy_version,
        model_evidence_label,
        decision_date,
        rebalance_ordinal,
        expected_security_count,
        assembly_manifest_hash,
        decision_content_hash,
        canonical_body_text,
        payload_sha256,
        canonical_payload_text,
        canonical_payload,
        deterministic_research_signal_authorized,
        deterministic_final_weight_authorized,
        automatic_brokerage_execution_authorized,
        llm_signal_or_weight_authority,
        future_return_guaranteed
    ) VALUES (
        decision_id_value,
        'quant-trading-research-decision-v1.1.0',
        'quant-trading-public-projection-v1.1.0',
        'quant-trading-v22-assembly-v1.1.0',
        'QUANT-TRADING-v1.1.0',
        'DUAL-MOMENTUM-TREND-v1.1.0',
        'DUAL-MOMENTUM-TREND-FORMULAS-v1.1.0',
        'DUAL-MOMENTUM-TREND-ENTRY-EXIT-v1.1.0',
        'NOT_VALIDATED',
        DATE '2026-08-13',
        0,
        20,
        'sha256:' || repeat('a', 64),
        content_hash,
        body_text,
        payload_hash,
        payload_text,
        payload,
        true,
        false,
        false,
        false,
        false
    );

END;
$$;

RESET ROLE;

DO $$
DECLARE
    decision_count INTEGER;
    signal_count INTEGER;
    update_rejected BOOLEAN := false;
    delete_rejected BOOLEAN := false;
BEGIN
    SELECT count(*), sum(jsonb_array_length(canonical_payload->'signals'))
      INTO decision_count, signal_count
    FROM analytics.quant_research_decision_v1;

    IF decision_count <> 1 OR signal_count <> 20 THEN
        RAISE EXCEPTION 'V27 representative decision readback failed';
    END IF;

    BEGIN
        UPDATE analytics.quant_research_decision_v1
        SET rebalance_ordinal = 5
        WHERE decision_id = '27000000-0000-4000-8000-000000000001';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'Quant research decision v1 is append-only' THEN
            update_rejected := true;
        ELSE
            RAISE;
        END IF;
    END;
    IF NOT update_rejected THEN
        RAISE EXCEPTION 'V27 update was not rejected';
    END IF;

    BEGIN
        DELETE FROM analytics.quant_research_decision_v1
        WHERE decision_id = '27000000-0000-4000-8000-000000000001';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'Quant research decision v1 is append-only' THEN
            delete_rejected := true;
        ELSE
            RAISE;
        END IF;
    END;
    IF NOT delete_rejected THEN
        RAISE EXCEPTION 'V27 delete was not rejected';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM analytics.quant_research_decision_v1
        WHERE deterministic_final_weight_authorized
           OR automatic_brokerage_execution_authorized
           OR llm_signal_or_weight_authority
           OR future_return_guaranteed
           OR jsonb_path_exists(canonical_payload, '$.**.finalWeight')
           OR jsonb_path_exists(canonical_payload, '$.**.orderQuantity')
           OR jsonb_path_exists(canonical_payload, '$.**.brokerageInstruction')
    ) THEN
        RAISE EXCEPTION 'V27 prohibited authority was persisted';
    END IF;
END;
$$;
