CREATE TABLE app.portfolio_decision_plan_v1 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    portfolio_id UUID NOT NULL,
    created_by_identity_id UUID NOT NULL,
    supersedes_plan_id UUID,
    contract_version VARCHAR(64) NOT NULL,
    plan_status VARCHAR(32) NOT NULL,
    as_of_time TIMESTAMPTZ NOT NULL,
    evidence_state VARCHAR(32) NOT NULL,
    claim_ceiling VARCHAR(32) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_hash VARCHAR(71) NOT NULL,
    content_hash VARCHAR(71) NOT NULL,
    automatic_brokerage_execution BOOLEAN NOT NULL DEFAULT FALSE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_portfolio_decision_plan_portfolio
        FOREIGN KEY (portfolio_id, user_id)
        REFERENCES app.portfolio (id, user_id),
    CONSTRAINT fk_portfolio_decision_plan_identity
        FOREIGN KEY (created_by_identity_id, user_id)
        REFERENCES app.authentication_identity (id, user_id),
    CONSTRAINT fk_portfolio_decision_plan_supersedes
        FOREIGN KEY (supersedes_plan_id, user_id, portfolio_id)
        REFERENCES app.portfolio_decision_plan_v1 (id, user_id, portfolio_id),
    CONSTRAINT uq_portfolio_decision_plan_owner UNIQUE (id, user_id),
    CONSTRAINT uq_portfolio_decision_plan_portfolio_owner
        UNIQUE (id, user_id, portfolio_id),
    CONSTRAINT uq_portfolio_decision_plan_idempotency
        UNIQUE (user_id, idempotency_key),
    CONSTRAINT uq_portfolio_decision_plan_content
        UNIQUE (portfolio_id, content_hash),
    CONSTRAINT ck_portfolio_decision_plan_version
        CHECK (
            contract_version =
                'INVESTMENT-TRADING-DECISION-ARCHITECTURE-v1.0.0'
        ),
    CONSTRAINT ck_portfolio_decision_plan_status
        CHECK (plan_status IN ('PROPOSED', 'ACCEPTED', 'REJECTED', 'NO_ACTION')),
    CONSTRAINT ck_portfolio_decision_plan_evidence_state
        CHECK (
            evidence_state IN (
                'VALID', 'MISSING', 'STALE', 'INVALID', 'NOT_APPLICABLE'
            )
        ),
    CONSTRAINT ck_portfolio_decision_plan_claim_ceiling
        CHECK (
            claim_ceiling IN (
                'BLOCKED', 'DIAGNOSTIC_ONLY',
                'PROVISIONAL_ONLY', 'VALIDATION_ELIGIBLE'
            )
        ),
    CONSTRAINT ck_portfolio_decision_plan_request_hash
        CHECK (request_hash ~ '^(sha256:)?[0-9A-Fa-f]{64}$'),
    CONSTRAINT ck_portfolio_decision_plan_content_hash
        CHECK (content_hash ~ '^(sha256:)?[0-9A-Fa-f]{64}$'),
    CONSTRAINT ck_portfolio_decision_plan_not_self_superseding
        CHECK (supersedes_plan_id IS NULL OR supersedes_plan_id <> id),
    CONSTRAINT ck_portfolio_decision_plan_no_automatic_execution
        CHECK (automatic_brokerage_execution = FALSE)
);

CREATE UNIQUE INDEX uq_portfolio_decision_plan_successor
    ON app.portfolio_decision_plan_v1 (supersedes_plan_id)
    WHERE supersedes_plan_id IS NOT NULL;

CREATE TABLE app.portfolio_sleeve_policy_v1 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    plan_id UUID NOT NULL,
    sleeve_type VARCHAR(32) NOT NULL,
    owning_lane VARCHAR(32) NOT NULL,
    target_holding_count INTEGER NOT NULL,
    maximum_security_weight NUMERIC(9, 8) NOT NULL,
    maximum_sector_weight NUMERIC(9, 8) NOT NULL,
    minimum_cash_weight NUMERIC(9, 8) NOT NULL,
    minimum_turnover_weight NUMERIC(9, 8) NOT NULL,
    maximum_turnover_weight NUMERIC(9, 8) NOT NULL,
    issuer_deduplication_policy VARCHAR(64) NOT NULL,
    rebalance_rule VARCHAR(64) NOT NULL,
    pnl_binding_required BOOLEAN NOT NULL DEFAULT TRUE,
    evidence_binding_required BOOLEAN NOT NULL DEFAULT TRUE,
    automatic_brokerage_execution BOOLEAN NOT NULL DEFAULT FALSE,
    policy_hash VARCHAR(71) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_portfolio_sleeve_policy_plan
        FOREIGN KEY (plan_id, user_id)
        REFERENCES app.portfolio_decision_plan_v1 (id, user_id),
    CONSTRAINT uq_portfolio_sleeve_policy_owner UNIQUE (id, user_id),
    CONSTRAINT uq_portfolio_sleeve_policy_plan_owner
        UNIQUE (id, user_id, plan_id),
    CONSTRAINT uq_portfolio_sleeve_policy_type UNIQUE (plan_id, sleeve_type),
    CONSTRAINT ck_portfolio_sleeve_policy_lane CHECK (
        (sleeve_type = 'CORE' AND owning_lane = 'LONG_TERM_INVESTMENT')
        OR (
            sleeve_type = 'TACTICAL'
            AND owning_lane = 'TACTICAL_TRADING'
        )
    ),
    CONSTRAINT ck_portfolio_sleeve_policy_target_holdings
        CHECK (target_holding_count BETWEEN 10 AND 15),
    CONSTRAINT ck_portfolio_sleeve_policy_security_weight
        CHECK (maximum_security_weight > 0 AND maximum_security_weight <= 1),
    CONSTRAINT ck_portfolio_sleeve_policy_sector_weight
        CHECK (maximum_sector_weight > 0 AND maximum_sector_weight <= 1),
    CONSTRAINT ck_portfolio_sleeve_policy_cash_weight
        CHECK (minimum_cash_weight >= 0 AND minimum_cash_weight < 1),
    CONSTRAINT ck_portfolio_sleeve_policy_turnover_band CHECK (
        minimum_turnover_weight >= 0
        AND maximum_turnover_weight <= 2
        AND minimum_turnover_weight <= maximum_turnover_weight
    ),
    CONSTRAINT ck_portfolio_sleeve_policy_issuer_deduplication
        CHECK (issuer_deduplication_policy = 'ONE_SECURITY_PER_ISSUER'),
    CONSTRAINT ck_portfolio_sleeve_policy_rebalance_rule CHECK (
        (
            sleeve_type = 'CORE'
            AND rebalance_rule = 'ANNUAL_WITH_QUARTERLY_RISK_REVIEW'
        )
        OR (
            sleeve_type = 'TACTICAL'
            AND rebalance_rule = 'HORIZON_EXPIRY_OR_INVALIDATION'
        )
    ),
    CONSTRAINT ck_portfolio_sleeve_policy_required_bindings
        CHECK (pnl_binding_required = TRUE AND evidence_binding_required = TRUE),
    CONSTRAINT ck_portfolio_sleeve_policy_no_automatic_execution
        CHECK (automatic_brokerage_execution = FALSE),
    CONSTRAINT ck_portfolio_sleeve_policy_hash
        CHECK (policy_hash ~ '^(sha256:)?[0-9A-Fa-f]{64}$')
);

CREATE TABLE app.portfolio_sleeve_evidence_binding_v1 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    plan_id UUID NOT NULL,
    sleeve_policy_id UUID NOT NULL,
    decision_lane VARCHAR(32) NOT NULL,
    evidence_kind VARCHAR(48) NOT NULL,
    evidence_reference_id VARCHAR(255) NOT NULL,
    evidence_content_hash VARCHAR(71) NOT NULL,
    evidence_as_of TIMESTAMPTZ NOT NULL,
    evidence_state VARCHAR(32) NOT NULL,
    claim_ceiling VARCHAR(32) NOT NULL,
    may_affect_deterministic_fields BOOLEAN NOT NULL DEFAULT FALSE,
    may_affect_weights BOOLEAN NOT NULL DEFAULT FALSE,
    may_create_orders BOOLEAN NOT NULL DEFAULT FALSE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_portfolio_sleeve_evidence_plan
        FOREIGN KEY (plan_id, user_id)
        REFERENCES app.portfolio_decision_plan_v1 (id, user_id),
    CONSTRAINT fk_portfolio_sleeve_evidence_policy
        FOREIGN KEY (sleeve_policy_id, user_id, plan_id)
        REFERENCES app.portfolio_sleeve_policy_v1 (id, user_id, plan_id),
    CONSTRAINT uq_portfolio_sleeve_evidence_owner UNIQUE (id, user_id),
    CONSTRAINT uq_portfolio_sleeve_evidence_reference UNIQUE (
        sleeve_policy_id, decision_lane, evidence_reference_id,
        evidence_content_hash
    ),
    CONSTRAINT ck_portfolio_sleeve_evidence_lane CHECK (
        decision_lane IN (
            'LONG_TERM_INVESTMENT', 'TACTICAL_TRADING',
            'AI_RESEARCH', 'PORTFOLIO_CONSTRUCTION'
        )
    ),
    CONSTRAINT ck_portfolio_sleeve_evidence_kind CHECK (
        evidence_kind IN (
            'DETERMINISTIC_MODEL_OUTPUT', 'VALIDATION_RESULT',
            'POINT_IN_TIME_INPUT', 'AI_NARRATIVE', 'PORTFOLIO_RULE_OUTPUT'
        )
    ),
    CONSTRAINT ck_portfolio_sleeve_evidence_kind_lane CHECK (
        (decision_lane = 'AI_RESEARCH' AND evidence_kind = 'AI_NARRATIVE')
        OR (
            decision_lane = 'PORTFOLIO_CONSTRUCTION'
            AND evidence_kind = 'PORTFOLIO_RULE_OUTPUT'
        )
        OR (
            decision_lane IN (
                'LONG_TERM_INVESTMENT', 'TACTICAL_TRADING'
            )
            AND evidence_kind IN (
                'DETERMINISTIC_MODEL_OUTPUT', 'VALIDATION_RESULT',
                'POINT_IN_TIME_INPUT'
            )
        )
    ),
    CONSTRAINT ck_portfolio_sleeve_evidence_state
        CHECK (
            evidence_state IN (
                'VALID', 'MISSING', 'STALE', 'INVALID', 'NOT_APPLICABLE'
            )
        ),
    CONSTRAINT ck_portfolio_sleeve_evidence_claim_ceiling
        CHECK (
            claim_ceiling IN (
                'BLOCKED', 'DIAGNOSTIC_ONLY',
                'PROVISIONAL_ONLY', 'VALIDATION_ELIGIBLE'
            )
        ),
    CONSTRAINT ck_portfolio_sleeve_evidence_hash
        CHECK (evidence_content_hash ~ '^(sha256:)?[0-9A-Fa-f]{64}$'),
    CONSTRAINT ck_portfolio_sleeve_evidence_no_direct_action
        CHECK (may_affect_weights = FALSE AND may_create_orders = FALSE),
    CONSTRAINT ck_portfolio_sleeve_evidence_ai_boundary CHECK (
        decision_lane <> 'AI_RESEARCH'
        OR (
            may_affect_deterministic_fields = FALSE
            AND may_affect_weights = FALSE
            AND may_create_orders = FALSE
        )
    )
);

CREATE TABLE app.portfolio_sleeve_pnl_binding_v1 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    plan_id UUID NOT NULL,
    sleeve_policy_id UUID NOT NULL,
    as_of_time TIMESTAMPTZ NOT NULL,
    base_currency CHAR(3) NOT NULL DEFAULT 'USD',
    valuation_state VARCHAR(32) NOT NULL,
    total_value NUMERIC(24, 10),
    cash_value NUMERIC(24, 10),
    period_pnl NUMERIC(24, 10),
    cumulative_pnl NUMERIC(24, 10),
    pnl_reference_id VARCHAR(255) NOT NULL,
    pnl_content_hash VARCHAR(71) NOT NULL,
    claim_ceiling VARCHAR(32) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_portfolio_sleeve_pnl_plan
        FOREIGN KEY (plan_id, user_id)
        REFERENCES app.portfolio_decision_plan_v1 (id, user_id),
    CONSTRAINT fk_portfolio_sleeve_pnl_policy
        FOREIGN KEY (sleeve_policy_id, user_id, plan_id)
        REFERENCES app.portfolio_sleeve_policy_v1 (id, user_id, plan_id),
    CONSTRAINT uq_portfolio_sleeve_pnl_owner UNIQUE (id, user_id),
    CONSTRAINT uq_portfolio_sleeve_pnl_time
        UNIQUE (sleeve_policy_id, as_of_time),
    CONSTRAINT ck_portfolio_sleeve_pnl_currency CHECK (base_currency = 'USD'),
    CONSTRAINT ck_portfolio_sleeve_pnl_state
        CHECK (
            valuation_state IN (
                'VALID', 'MISSING', 'STALE', 'INVALID', 'NOT_APPLICABLE'
            )
        ),
    CONSTRAINT ck_portfolio_sleeve_pnl_explicit_missing CHECK (
        (
            valuation_state = 'VALID'
            AND total_value IS NOT NULL
            AND cash_value IS NOT NULL
            AND period_pnl IS NOT NULL
            AND cumulative_pnl IS NOT NULL
            AND total_value >= 0
            AND cash_value >= 0
        )
        OR (
            valuation_state <> 'VALID'
            AND total_value IS NULL
            AND cash_value IS NULL
            AND period_pnl IS NULL
            AND cumulative_pnl IS NULL
        )
    ),
    CONSTRAINT ck_portfolio_sleeve_pnl_claim_ceiling
        CHECK (
            claim_ceiling IN (
                'BLOCKED', 'DIAGNOSTIC_ONLY',
                'PROVISIONAL_ONLY', 'VALIDATION_ELIGIBLE'
            )
        ),
    CONSTRAINT ck_portfolio_sleeve_pnl_hash
        CHECK (pnl_content_hash ~ '^(sha256:)?[0-9A-Fa-f]{64}$')
);

CREATE TABLE app.suggested_order_v1 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    plan_id UUID NOT NULL,
    sleeve_policy_id UUID NOT NULL,
    created_by_identity_id UUID NOT NULL,
    supersedes_order_id UUID,
    security_public_id UUID NOT NULL,
    issuer_reference VARCHAR(255) NOT NULL,
    side VARCHAR(16) NOT NULL,
    quantity NUMERIC(24, 10) NOT NULL,
    estimated_price NUMERIC(24, 10) NOT NULL,
    estimated_transaction_cost NUMERIC(24, 10) NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'USD',
    rationale TEXT NOT NULL,
    confirmation_status VARCHAR(32) NOT NULL,
    execution_status VARCHAR(32) NOT NULL,
    automatic_brokerage_execution BOOLEAN NOT NULL DEFAULT FALSE,
    idempotency_key VARCHAR(128) NOT NULL,
    content_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_suggested_order_plan
        FOREIGN KEY (plan_id, user_id)
        REFERENCES app.portfolio_decision_plan_v1 (id, user_id),
    CONSTRAINT fk_suggested_order_policy
        FOREIGN KEY (sleeve_policy_id, user_id, plan_id)
        REFERENCES app.portfolio_sleeve_policy_v1 (id, user_id, plan_id),
    CONSTRAINT fk_suggested_order_identity
        FOREIGN KEY (created_by_identity_id, user_id)
        REFERENCES app.authentication_identity (id, user_id),
    CONSTRAINT fk_suggested_order_supersedes
        FOREIGN KEY (supersedes_order_id, user_id, plan_id)
        REFERENCES app.suggested_order_v1 (id, user_id, plan_id),
    CONSTRAINT uq_suggested_order_owner UNIQUE (id, user_id),
    CONSTRAINT uq_suggested_order_plan_owner UNIQUE (id, user_id, plan_id),
    CONSTRAINT uq_suggested_order_idempotency UNIQUE (user_id, idempotency_key),
    CONSTRAINT ck_suggested_order_side CHECK (side IN ('BUY', 'SELL')),
    CONSTRAINT ck_suggested_order_quantity CHECK (quantity > 0),
    CONSTRAINT ck_suggested_order_price CHECK (estimated_price > 0),
    CONSTRAINT ck_suggested_order_cost
        CHECK (estimated_transaction_cost >= 0),
    CONSTRAINT ck_suggested_order_currency CHECK (currency = 'USD'),
    CONSTRAINT ck_suggested_order_confirmation
        CHECK (confirmation_status = 'HUMAN_CONFIRMATION_REQUIRED'),
    CONSTRAINT ck_suggested_order_execution
        CHECK (execution_status = 'NOT_EXECUTED'),
    CONSTRAINT ck_suggested_order_no_automatic_execution
        CHECK (automatic_brokerage_execution = FALSE),
    CONSTRAINT ck_suggested_order_hash
        CHECK (content_hash ~ '^(sha256:)?[0-9A-Fa-f]{64}$'),
    CONSTRAINT ck_suggested_order_not_self_superseding
        CHECK (supersedes_order_id IS NULL OR supersedes_order_id <> id)
);

CREATE UNIQUE INDEX uq_suggested_order_successor
    ON app.suggested_order_v1 (supersedes_order_id)
    WHERE supersedes_order_id IS NOT NULL;

CREATE TRIGGER tr_portfolio_decision_plan_v1_immutable
BEFORE UPDATE OR DELETE ON app.portfolio_decision_plan_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();

CREATE TRIGGER tr_portfolio_sleeve_policy_v1_immutable
BEFORE UPDATE OR DELETE ON app.portfolio_sleeve_policy_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();

CREATE TRIGGER tr_portfolio_sleeve_evidence_v1_immutable
BEFORE UPDATE OR DELETE ON app.portfolio_sleeve_evidence_binding_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();

CREATE TRIGGER tr_portfolio_sleeve_pnl_v1_immutable
BEFORE UPDATE OR DELETE ON app.portfolio_sleeve_pnl_binding_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();

CREATE TRIGGER tr_suggested_order_v1_immutable
BEFORE UPDATE OR DELETE ON app.suggested_order_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();

CREATE INDEX ix_portfolio_decision_plan_v1_portfolio
    ON app.portfolio_decision_plan_v1 (portfolio_id, as_of_time DESC);

CREATE INDEX ix_portfolio_sleeve_evidence_v1_plan
    ON app.portfolio_sleeve_evidence_binding_v1 (
        plan_id, decision_lane, evidence_as_of DESC
    );

CREATE INDEX ix_portfolio_sleeve_pnl_v1_plan
    ON app.portfolio_sleeve_pnl_binding_v1 (plan_id, as_of_time DESC);

CREATE INDEX ix_suggested_order_v1_plan
    ON app.suggested_order_v1 (plan_id, created_at DESC);

COMMENT ON TABLE app.portfolio_decision_plan_v1 IS
    'Immutable user-facing portfolio decision plan. Changes require a successor row.';
COMMENT ON TABLE app.portfolio_sleeve_policy_v1 IS
    'Separate deterministic Core and Tactical sleeve policies with no brokerage execution.';
COMMENT ON TABLE app.portfolio_sleeve_evidence_binding_v1 IS
    'Immutable references to lane-owned evidence IDs and hashes; analytics scores are not copied.';
COMMENT ON TABLE app.portfolio_sleeve_pnl_binding_v1 IS
    'Sleeve-specific P&L evidence with explicit non-valid states.';
COMMENT ON TABLE app.suggested_order_v1 IS
    'Non-executed order suggestion that always requires human confirmation.';
