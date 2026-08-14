CREATE TABLE app.unified_portfolio_context_v1 (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    portfolio_id UUID NOT NULL,
    created_by_identity_id UUID NOT NULL,
    constraint_policy_version_id UUID NOT NULL,
    contract_version VARCHAR(64) NOT NULL,
    calculation_version VARCHAR(64) NOT NULL,
    as_of_time TIMESTAMPTZ NOT NULL,
    base_currency CHAR(3) NOT NULL,
    context_state VARCHAR(16) NOT NULL,
    risk_status VARCHAR(16) NOT NULL,
    cash_value NUMERIC NOT NULL,
    invested_value NUMERIC NOT NULL,
    asset_value NUMERIC NOT NULL,
    liability_value NUMERIC NOT NULL,
    net_portfolio_value NUMERIC NOT NULL,
    cash_weight NUMERIC NOT NULL,
    leverage_ratio NUMERIC NOT NULL,
    maximum_position_weight NUMERIC NOT NULL,
    maximum_sector_weight NUMERIC NOT NULL,
    minimum_cash_weight NUMERIC NOT NULL,
    maximum_leverage_ratio NUMERIC NOT NULL,
    account_binding_count INTEGER NOT NULL,
    position_count INTEGER NOT NULL,
    risk_reason_count INTEGER NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    source_request_hash VARCHAR(71) NOT NULL,
    content_hash VARCHAR(71) NOT NULL,
    public_payload JSONB NOT NULL,
    automatic_brokerage_execution BOOLEAN NOT NULL DEFAULT FALSE,
    final_weight_authority BOOLEAN NOT NULL DEFAULT FALSE,
    order_authority BOOLEAN NOT NULL DEFAULT FALSE,
    llm_decision_authority BOOLEAN NOT NULL DEFAULT FALSE,
    human_decision_required BOOLEAN NOT NULL DEFAULT TRUE,
    sealed_at TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_unified_portfolio_context_portfolio
        FOREIGN KEY (portfolio_id, user_id) REFERENCES app.portfolio (id, user_id),
    CONSTRAINT fk_unified_portfolio_context_identity
        FOREIGN KEY (created_by_identity_id, user_id)
        REFERENCES app.authentication_identity (id, user_id),
    CONSTRAINT fk_unified_portfolio_context_constraint_policy
        FOREIGN KEY (constraint_policy_version_id, user_id)
        REFERENCES app.constraint_policy_version (id, user_id),
    CONSTRAINT uq_unified_portfolio_context_owner UNIQUE (id, user_id),
    CONSTRAINT uq_unified_portfolio_context_idempotency UNIQUE (user_id, idempotency_key),
    CONSTRAINT uq_unified_portfolio_context_content UNIQUE (portfolio_id, content_hash),
    CONSTRAINT ck_unified_portfolio_context_contract
        CHECK (contract_version = 'unified-portfolio-risk-result-v1.0.0'),
    CONSTRAINT ck_unified_portfolio_context_calculation
        CHECK (calculation_version = 'UNIFIED-PORTFOLIO-RISK-CALCULATION-v1.0.0'),
    CONSTRAINT ck_unified_portfolio_context_currency CHECK (base_currency = 'USD'),
    CONSTRAINT ck_unified_portfolio_context_state CHECK (context_state IN ('VALID', 'PARTIAL')),
    CONSTRAINT ck_unified_portfolio_context_risk CHECK (risk_status IN ('PASSED', 'VIOLATED')),
    CONSTRAINT ck_unified_portfolio_context_values CHECK (
        cash_value >= 0 AND invested_value >= 0 AND asset_value > 0
        AND liability_value >= 0 AND net_portfolio_value > 0
        AND asset_value = cash_value + invested_value
        AND net_portfolio_value = asset_value - liability_value
        AND cash_weight >= 0 AND cash_weight <= 1 AND leverage_ratio >= 0
    ),
    CONSTRAINT ck_unified_portfolio_context_constraints CHECK (
        maximum_position_weight BETWEEN 0 AND 1
        AND maximum_sector_weight BETWEEN 0 AND 1
        AND minimum_cash_weight BETWEEN 0 AND 1
        AND maximum_leverage_ratio >= 0
    ),
    CONSTRAINT ck_unified_portfolio_context_counts CHECK (
        account_binding_count >= 0 AND position_count >= 0 AND risk_reason_count >= 0
    ),
    CONSTRAINT ck_unified_portfolio_context_hashes CHECK (
        source_request_hash ~ '^sha256:[0-9a-f]{64}$'
        AND content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_unified_portfolio_context_payload CHECK (jsonb_typeof(public_payload) = 'object'),
    CONSTRAINT ck_unified_portfolio_context_no_automation CHECK (
        automatic_brokerage_execution = FALSE
        AND final_weight_authority = FALSE
        AND order_authority = FALSE
        AND llm_decision_authority = FALSE
        AND human_decision_required = TRUE
    )
);

CREATE TABLE app.unified_portfolio_account_binding_v1 (
    context_id UUID NOT NULL,
    user_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    account_snapshot_id UUID NOT NULL,
    PRIMARY KEY (context_id, ordinal),
    CONSTRAINT fk_unified_portfolio_account_context
        FOREIGN KEY (context_id, user_id) REFERENCES app.unified_portfolio_context_v1 (id, user_id),
    CONSTRAINT fk_unified_portfolio_account_snapshot
        FOREIGN KEY (account_snapshot_id, user_id) REFERENCES app.account_snapshot (id, user_id),
    CONSTRAINT uq_unified_portfolio_account_snapshot UNIQUE (context_id, account_snapshot_id),
    CONSTRAINT ck_unified_portfolio_account_ordinal CHECK (ordinal > 0)
);

CREATE TABLE app.unified_portfolio_position_v1 (
    context_id UUID NOT NULL,
    user_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    security_public_id UUID NOT NULL,
    ticker VARCHAR(32) NOT NULL,
    sleeve_type VARCHAR(32) NOT NULL,
    sector_code VARCHAR(128) NOT NULL,
    data_state VARCHAR(16) NOT NULL,
    market_value NUMERIC,
    asset_weight NUMERIC,
    PRIMARY KEY (context_id, ordinal),
    CONSTRAINT fk_unified_portfolio_position_context
        FOREIGN KEY (context_id, user_id) REFERENCES app.unified_portfolio_context_v1 (id, user_id),
    CONSTRAINT uq_unified_portfolio_position_security UNIQUE (context_id, security_public_id),
    CONSTRAINT ck_unified_portfolio_position_ordinal CHECK (ordinal > 0),
    CONSTRAINT ck_unified_portfolio_position_sleeve
        CHECK (sleeve_type IN ('LONG_TERM_CORE', 'QUANT_TRADING', 'UNASSIGNED')),
    CONSTRAINT ck_unified_portfolio_position_state
        CHECK (data_state IN ('VALID', 'MISSING', 'STALE', 'INVALID')),
    CONSTRAINT ck_unified_portfolio_position_value CHECK (
        (data_state = 'VALID' AND market_value IS NOT NULL AND market_value >= 0
            AND asset_weight IS NOT NULL AND asset_weight >= 0 AND asset_weight <= 1)
        OR (data_state <> 'VALID' AND market_value IS NULL AND asset_weight IS NULL)
    )
);

CREATE TABLE app.unified_portfolio_sleeve_v1 (
    context_id UUID NOT NULL,
    user_id UUID NOT NULL,
    sleeve_type VARCHAR(32) NOT NULL,
    market_value NUMERIC NOT NULL,
    asset_weight NUMERIC NOT NULL,
    position_count INTEGER NOT NULL,
    model_version VARCHAR(96) NOT NULL,
    model_evidence_label VARCHAR(32) NOT NULL,
    research_use_allowed BOOLEAN NOT NULL,
    evidence_reference_id VARCHAR(255) NOT NULL,
    evidence_reference_hash VARCHAR(71) NOT NULL,
    PRIMARY KEY (context_id, sleeve_type),
    CONSTRAINT fk_unified_portfolio_sleeve_context
        FOREIGN KEY (context_id, user_id) REFERENCES app.unified_portfolio_context_v1 (id, user_id),
    CONSTRAINT ck_unified_portfolio_sleeve_type
        CHECK (sleeve_type IN ('LONG_TERM_CORE', 'QUANT_TRADING')),
    CONSTRAINT ck_unified_portfolio_sleeve_values CHECK (
        market_value >= 0 AND asset_weight >= 0 AND asset_weight <= 1 AND position_count >= 0
    ),
    CONSTRAINT ck_unified_portfolio_sleeve_evidence_label CHECK (
        model_evidence_label IN (
            'NOT_VALIDATED', 'DEVELOPMENT_OBSERVED', 'BACKTEST_SUPPORTED',
            'PIT_SUPPORTED', 'FORWARD_SUPPORTED'
        )
    ),
    CONSTRAINT ck_unified_portfolio_sleeve_hash
        CHECK (evidence_reference_hash ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_unified_portfolio_sleeve_quant_v2 CHECK (
        model_version <> 'QUANT-TRADING-v2.0.0' OR research_use_allowed = FALSE
    )
);

CREATE TABLE app.unified_portfolio_risk_reason_v1 (
    context_id UUID NOT NULL,
    user_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    reason_code VARCHAR(96) NOT NULL,
    PRIMARY KEY (context_id, ordinal),
    CONSTRAINT fk_unified_portfolio_risk_reason_context
        FOREIGN KEY (context_id, user_id) REFERENCES app.unified_portfolio_context_v1 (id, user_id),
    CONSTRAINT uq_unified_portfolio_risk_reason UNIQUE (context_id, reason_code),
    CONSTRAINT ck_unified_portfolio_risk_reason_ordinal CHECK (ordinal > 0)
);

CREATE TABLE app.unified_portfolio_review_v1 (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    context_id UUID NOT NULL,
    created_by_identity_id UUID NOT NULL,
    conclusion VARCHAR(32) NOT NULL,
    rationale TEXT NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_hash VARCHAR(71) NOT NULL,
    content_hash VARCHAR(71) NOT NULL,
    reviewed_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    automatic_brokerage_execution BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT fk_unified_portfolio_review_context
        FOREIGN KEY (context_id, user_id) REFERENCES app.unified_portfolio_context_v1 (id, user_id),
    CONSTRAINT fk_unified_portfolio_review_identity
        FOREIGN KEY (created_by_identity_id, user_id)
        REFERENCES app.authentication_identity (id, user_id),
    CONSTRAINT uq_unified_portfolio_review_context UNIQUE (context_id),
    CONSTRAINT uq_unified_portfolio_review_idempotency UNIQUE (user_id, idempotency_key),
    CONSTRAINT ck_unified_portfolio_review_conclusion
        CHECK (conclusion IN ('ACKNOWLEDGED', 'REVIEW_REQUIRED', 'NO_ACTION')),
    CONSTRAINT ck_unified_portfolio_review_hash CHECK (
        request_hash ~ '^sha256:[0-9a-f]{64}$'
        AND content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_unified_portfolio_review_no_execution CHECK (automatic_brokerage_execution = FALSE)
);

CREATE FUNCTION app.validate_unified_portfolio_context_seal_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    actual_accounts INTEGER;
    actual_positions INTEGER;
    actual_reasons INTEGER;
    actual_sleeves INTEGER;
BEGIN
    IF OLD.sealed_at IS NOT NULL THEN
        RAISE EXCEPTION 'Unified portfolio context is immutable after sealing';
    END IF;
    IF NEW.sealed_at IS NULL THEN
        RAISE EXCEPTION 'Unified portfolio context update may only seal the context';
    END IF;
    IF (to_jsonb(NEW) - 'sealed_at') <> (to_jsonb(OLD) - 'sealed_at') THEN
        RAISE EXCEPTION 'Unified portfolio context fields cannot change while sealing';
    END IF;
    SELECT count(*) INTO actual_accounts FROM app.unified_portfolio_account_binding_v1 WHERE context_id = NEW.id;
    SELECT count(*) INTO actual_positions FROM app.unified_portfolio_position_v1 WHERE context_id = NEW.id;
    SELECT count(*) INTO actual_reasons FROM app.unified_portfolio_risk_reason_v1 WHERE context_id = NEW.id;
    SELECT count(*) INTO actual_sleeves FROM app.unified_portfolio_sleeve_v1 WHERE context_id = NEW.id;
    IF actual_accounts <> NEW.account_binding_count
       OR actual_positions <> NEW.position_count
       OR actual_reasons <> NEW.risk_reason_count
       OR actual_sleeves <> 2 THEN
        RAISE EXCEPTION 'Unified portfolio context child cardinality is incomplete';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION app.reject_unified_portfolio_late_child_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    parent_sealed_at TIMESTAMPTZ;
BEGIN
    SELECT sealed_at INTO parent_sealed_at
    FROM app.unified_portfolio_context_v1 WHERE id = NEW.context_id FOR UPDATE;
    IF parent_sealed_at IS NOT NULL THEN
        RAISE EXCEPTION 'Unified portfolio context rejects late child rows';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER tr_unified_portfolio_context_seal_v1
BEFORE UPDATE ON app.unified_portfolio_context_v1
FOR EACH ROW EXECUTE FUNCTION app.validate_unified_portfolio_context_seal_v1();
CREATE TRIGGER tr_unified_portfolio_context_delete_v1
BEFORE DELETE ON app.unified_portfolio_context_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();

CREATE TRIGGER tr_unified_portfolio_account_late_v1 BEFORE INSERT ON app.unified_portfolio_account_binding_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_unified_portfolio_late_child_v1();
CREATE TRIGGER tr_unified_portfolio_position_late_v1 BEFORE INSERT ON app.unified_portfolio_position_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_unified_portfolio_late_child_v1();
CREATE TRIGGER tr_unified_portfolio_sleeve_late_v1 BEFORE INSERT ON app.unified_portfolio_sleeve_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_unified_portfolio_late_child_v1();
CREATE TRIGGER tr_unified_portfolio_reason_late_v1 BEFORE INSERT ON app.unified_portfolio_risk_reason_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_unified_portfolio_late_child_v1();

CREATE TRIGGER tr_unified_portfolio_account_immutable_v1 BEFORE UPDATE OR DELETE ON app.unified_portfolio_account_binding_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_unified_portfolio_position_immutable_v1 BEFORE UPDATE OR DELETE ON app.unified_portfolio_position_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_unified_portfolio_sleeve_immutable_v1 BEFORE UPDATE OR DELETE ON app.unified_portfolio_sleeve_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_unified_portfolio_reason_immutable_v1 BEFORE UPDATE OR DELETE ON app.unified_portfolio_risk_reason_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_unified_portfolio_review_immutable_v1 BEFORE UPDATE OR DELETE ON app.unified_portfolio_review_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();

CREATE INDEX ix_unified_portfolio_context_latest_v1
    ON app.unified_portfolio_context_v1 (portfolio_id, as_of_time DESC, recorded_at DESC);

COMMENT ON TABLE app.unified_portfolio_context_v1 IS
    'Immutable human-controlled unified valuation and risk snapshot over V12 portfolio context.';
COMMENT ON TABLE app.unified_portfolio_sleeve_v1 IS
    'Independent LONG_TERM_CORE and QUANT_TRADING research sleeves; no final allocation authority.';
