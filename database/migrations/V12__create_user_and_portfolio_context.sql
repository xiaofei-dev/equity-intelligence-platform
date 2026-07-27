CREATE TABLE app.user_account (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    display_name VARCHAR(160) NOT NULL,
    locale VARCHAR(35) NOT NULL DEFAULT 'en-US',
    time_zone VARCHAR(64) NOT NULL DEFAULT 'UTC',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TIMESTAMPTZ,
    CONSTRAINT uq_user_account_owner UNIQUE (id),
    CONSTRAINT ck_user_account_status
        CHECK (status IN ('ACTIVE', 'SUSPENDED', 'ARCHIVED')),
    CONSTRAINT ck_user_account_archive
        CHECK ((status = 'ARCHIVED') = (archived_at IS NOT NULL))
);

CREATE TABLE app.authentication_identity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app.user_account (id),
    provider VARCHAR(64) NOT NULL,
    issuer VARCHAR(255) NOT NULL,
    subject VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMPTZ,
    CONSTRAINT uq_authentication_identity_subject
        UNIQUE (provider, issuer, subject),
    CONSTRAINT uq_authentication_identity_owner UNIQUE (id, user_id)
);

CREATE TABLE app.investment_profile_version (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app.user_account (id),
    version_number INTEGER NOT NULL,
    investment_approach VARCHAR(32) NOT NULL,
    primary_horizon VARCHAR(32) NOT NULL,
    risk_tolerance VARCHAR(32) NOT NULL,
    liquidity_needs TEXT,
    notes TEXT,
    idempotency_key VARCHAR(128) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_investment_profile_version UNIQUE (user_id, version_number),
    CONSTRAINT uq_investment_profile_idempotency UNIQUE (user_id, idempotency_key),
    CONSTRAINT uq_investment_profile_owner UNIQUE (id, user_id),
    CONSTRAINT ck_investment_profile_version CHECK (version_number > 0),
    CONSTRAINT ck_investment_profile_approach CHECK (
        investment_approach IN ('DEFENSIVE', 'ENTERPRISING', 'SPECULATIVE_LIMITED')
    ),
    CONSTRAINT ck_investment_profile_horizon CHECK (
        primary_horizon IN ('SHORT_TERM', 'MEDIUM_TERM', 'LONG_TERM')
    ),
    CONSTRAINT ck_investment_profile_risk CHECK (
        risk_tolerance IN ('CONSERVATIVE', 'MODERATE', 'AGGRESSIVE')
    )
);

CREATE TABLE app.investment_goal (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    profile_version_id UUID NOT NULL,
    goal_type VARCHAR(64) NOT NULL,
    priority INTEGER NOT NULL,
    target_date DATE,
    target_amount NUMERIC(24, 10),
    currency CHAR(3),
    description TEXT,
    CONSTRAINT fk_investment_goal_profile
        FOREIGN KEY (profile_version_id, user_id)
        REFERENCES app.investment_profile_version (id, user_id),
    CONSTRAINT ck_investment_goal_priority CHECK (priority > 0),
    CONSTRAINT ck_investment_goal_amount CHECK (
        target_amount IS NULL OR (target_amount >= 0 AND currency IS NOT NULL)
    )
);

CREATE TABLE app.sector_preference (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    profile_version_id UUID NOT NULL,
    taxonomy_code VARCHAR(64) NOT NULL,
    taxonomy_version VARCHAR(64) NOT NULL,
    sector_code VARCHAR(128) NOT NULL,
    preference VARCHAR(32) NOT NULL,
    CONSTRAINT fk_sector_preference_profile
        FOREIGN KEY (profile_version_id, user_id)
        REFERENCES app.investment_profile_version (id, user_id),
    CONSTRAINT uq_sector_preference UNIQUE (
        profile_version_id, taxonomy_code, taxonomy_version, sector_code
    ),
    CONSTRAINT ck_sector_preference_value
        CHECK (preference IN ('PREFER', 'NEUTRAL', 'AVOID', 'EXCLUDE'))
);

CREATE TABLE app.investment_account (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app.user_account (id),
    name VARCHAR(160) NOT NULL,
    account_type VARCHAR(32) NOT NULL,
    base_currency CHAR(3) NOT NULL DEFAULT 'USD',
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TIMESTAMPTZ,
    CONSTRAINT uq_investment_account_owner UNIQUE (id, user_id),
    CONSTRAINT ck_investment_account_type
        CHECK (account_type IN ('REAL', 'SIMULATED', 'RETIREMENT')),
    CONSTRAINT ck_investment_account_status
        CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    CONSTRAINT ck_investment_account_archive
        CHECK ((status = 'ARCHIVED') = (archived_at IS NOT NULL))
);

CREATE TABLE app.account_snapshot (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    account_id UUID NOT NULL,
    as_of_time TIMESTAMPTZ NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_reference VARCHAR(255),
    completeness VARCHAR(32) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    sealed_at TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_account_snapshot_account
        FOREIGN KEY (account_id, user_id)
        REFERENCES app.investment_account (id, user_id),
    CONSTRAINT uq_account_snapshot_owner UNIQUE (id, user_id),
    CONSTRAINT uq_account_snapshot_hash UNIQUE (account_id, content_hash),
    CONSTRAINT uq_account_snapshot_idempotency
        UNIQUE (account_id, idempotency_key),
    CONSTRAINT ck_account_snapshot_source
        CHECK (source_type IN ('MANUAL', 'FILE_IMPORT', 'SYSTEM')),
    CONSTRAINT ck_account_snapshot_completeness
        CHECK (completeness IN ('COMPLETE', 'PARTIAL'))
);

CREATE TABLE app.cash_balance_snapshot (
    snapshot_id UUID NOT NULL,
    user_id UUID NOT NULL,
    currency CHAR(3) NOT NULL,
    settled_amount NUMERIC(24, 10) NOT NULL DEFAULT 0,
    unsettled_amount NUMERIC(24, 10) NOT NULL DEFAULT 0,
    restricted_amount NUMERIC(24, 10) NOT NULL DEFAULT 0,
    PRIMARY KEY (snapshot_id, currency),
    CONSTRAINT fk_cash_balance_snapshot
        FOREIGN KEY (snapshot_id, user_id)
        REFERENCES app.account_snapshot (id, user_id),
    CONSTRAINT ck_cash_balance_restricted CHECK (restricted_amount >= 0)
);

CREATE TABLE app.position_snapshot (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id UUID NOT NULL,
    user_id UUID NOT NULL,
    security_public_id UUID NOT NULL,
    quantity NUMERIC(24, 10) NOT NULL,
    average_cost NUMERIC(24, 10) NOT NULL,
    cost_currency CHAR(3) NOT NULL,
    CONSTRAINT fk_position_snapshot
        FOREIGN KEY (snapshot_id, user_id)
        REFERENCES app.account_snapshot (id, user_id),
    CONSTRAINT uq_position_snapshot_security
        UNIQUE (snapshot_id, security_public_id),
    CONSTRAINT ck_position_snapshot_quantity CHECK (quantity <> 0),
    CONSTRAINT ck_position_snapshot_average_cost CHECK (average_cost >= 0)
);

CREATE TABLE app.financial_liability (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app.user_account (id),
    account_id UUID,
    name VARCHAR(160) NOT NULL,
    liability_type VARCHAR(32) NOT NULL,
    currency CHAR(3) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TIMESTAMPTZ,
    CONSTRAINT fk_financial_liability_account
        FOREIGN KEY (account_id, user_id)
        REFERENCES app.investment_account (id, user_id),
    CONSTRAINT uq_financial_liability_owner UNIQUE (id, user_id),
    CONSTRAINT ck_financial_liability_type CHECK (
        liability_type IN ('MARGIN', 'LOAN', 'OTHER')
    ),
    CONSTRAINT ck_financial_liability_status
        CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    CONSTRAINT ck_financial_liability_archive
        CHECK ((status = 'ARCHIVED') = (archived_at IS NOT NULL))
);

CREATE TABLE app.liability_balance_snapshot (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    liability_id UUID NOT NULL,
    as_of_time TIMESTAMPTZ NOT NULL,
    balance NUMERIC(24, 10) NOT NULL,
    annual_interest_rate NUMERIC(12, 8),
    source_type VARCHAR(32) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_liability_balance_owner
        FOREIGN KEY (liability_id, user_id)
        REFERENCES app.financial_liability (id, user_id),
    CONSTRAINT uq_liability_balance_owner UNIQUE (id, user_id),
    CONSTRAINT uq_liability_balance_time UNIQUE (liability_id, as_of_time),
    CONSTRAINT uq_liability_balance_idempotency
        UNIQUE (liability_id, idempotency_key),
    CONSTRAINT ck_liability_balance CHECK (balance >= 0),
    CONSTRAINT ck_liability_interest CHECK (
        annual_interest_rate IS NULL OR annual_interest_rate >= 0
    ),
    CONSTRAINT ck_liability_balance_source
        CHECK (source_type IN ('MANUAL', 'FILE_IMPORT', 'SYSTEM'))
);

CREATE TABLE app.portfolio (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app.user_account (id),
    name VARCHAR(160) NOT NULL,
    base_currency CHAR(3) NOT NULL DEFAULT 'USD',
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TIMESTAMPTZ,
    CONSTRAINT uq_portfolio_owner UNIQUE (id, user_id),
    CONSTRAINT uq_portfolio_name UNIQUE (user_id, name),
    CONSTRAINT ck_portfolio_base_currency CHECK (base_currency = 'USD'),
    CONSTRAINT ck_portfolio_status CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    CONSTRAINT ck_portfolio_archive
        CHECK ((status = 'ARCHIVED') = (archived_at IS NOT NULL))
);

CREATE TABLE app.portfolio_account_membership (
    portfolio_id UUID NOT NULL,
    account_id UUID NOT NULL,
    user_id UUID NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (portfolio_id, account_id),
    CONSTRAINT fk_portfolio_membership_portfolio
        FOREIGN KEY (portfolio_id, user_id) REFERENCES app.portfolio (id, user_id),
    CONSTRAINT fk_portfolio_membership_account
        FOREIGN KEY (account_id, user_id)
        REFERENCES app.investment_account (id, user_id)
);

CREATE TABLE app.portfolio_liability_membership (
    portfolio_id UUID NOT NULL,
    liability_id UUID NOT NULL,
    user_id UUID NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (portfolio_id, liability_id),
    CONSTRAINT fk_portfolio_liability_portfolio
        FOREIGN KEY (portfolio_id, user_id) REFERENCES app.portfolio (id, user_id),
    CONSTRAINT fk_portfolio_liability_liability
        FOREIGN KEY (liability_id, user_id)
        REFERENCES app.financial_liability (id, user_id)
);

CREATE TABLE app.constraint_policy_version (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app.user_account (id),
    scope_type VARCHAR(32) NOT NULL,
    portfolio_id UUID,
    account_id UUID,
    version_number INTEGER NOT NULL,
    maximum_position_count INTEGER,
    maximum_position_weight NUMERIC(9, 8),
    maximum_sector_weight NUMERIC(9, 8),
    minimum_cash_weight NUMERIC(9, 8),
    maximum_leverage_ratio NUMERIC(12, 8),
    maximum_speculative_weight NUMERIC(9, 8),
    idempotency_key VARCHAR(128) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_constraint_policy_portfolio
        FOREIGN KEY (portfolio_id, user_id) REFERENCES app.portfolio (id, user_id),
    CONSTRAINT fk_constraint_policy_account
        FOREIGN KEY (account_id, user_id)
        REFERENCES app.investment_account (id, user_id),
    CONSTRAINT uq_constraint_policy_owner UNIQUE (id, user_id),
    CONSTRAINT uq_constraint_policy_idempotency UNIQUE (user_id, idempotency_key),
    CONSTRAINT ck_constraint_policy_scope CHECK (
        (scope_type = 'USER' AND portfolio_id IS NULL AND account_id IS NULL)
        OR (scope_type = 'PORTFOLIO' AND portfolio_id IS NOT NULL AND account_id IS NULL)
        OR (scope_type = 'ACCOUNT' AND portfolio_id IS NULL AND account_id IS NOT NULL)
    ),
    CONSTRAINT ck_constraint_policy_version CHECK (version_number > 0),
    CONSTRAINT ck_constraint_policy_position_count
        CHECK (maximum_position_count IS NULL OR maximum_position_count > 0),
    CONSTRAINT ck_constraint_policy_weights CHECK (
        (maximum_position_weight IS NULL OR maximum_position_weight BETWEEN 0 AND 1)
        AND (maximum_sector_weight IS NULL OR maximum_sector_weight BETWEEN 0 AND 1)
        AND (minimum_cash_weight IS NULL OR minimum_cash_weight BETWEEN 0 AND 1)
        AND (maximum_speculative_weight IS NULL OR maximum_speculative_weight BETWEEN 0 AND 1)
        AND (maximum_leverage_ratio IS NULL OR maximum_leverage_ratio >= 0)
    )
);

CREATE UNIQUE INDEX uq_constraint_policy_scope_version
ON app.constraint_policy_version (
    user_id,
    scope_type,
    COALESCE(portfolio_id, '00000000-0000-0000-0000-000000000000'::UUID),
    COALESCE(account_id, '00000000-0000-0000-0000-000000000000'::UUID),
    version_number
);

CREATE TABLE app.sector_constraint (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    policy_version_id UUID NOT NULL,
    taxonomy_code VARCHAR(64) NOT NULL,
    taxonomy_version VARCHAR(64) NOT NULL,
    sector_code VARCHAR(128) NOT NULL,
    maximum_weight NUMERIC(9, 8),
    excluded BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT fk_sector_constraint_policy
        FOREIGN KEY (policy_version_id, user_id)
        REFERENCES app.constraint_policy_version (id, user_id),
    CONSTRAINT uq_sector_constraint UNIQUE (
        policy_version_id, taxonomy_code, taxonomy_version, sector_code
    ),
    CONSTRAINT ck_sector_constraint_weight
        CHECK (maximum_weight IS NULL OR maximum_weight BETWEEN 0 AND 1)
);

CREATE TABLE app.portfolio_scenario (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    portfolio_id UUID NOT NULL,
    scenario_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
    base_currency CHAR(3) NOT NULL DEFAULT 'USD',
    new_money_amount NUMERIC(24, 10) NOT NULL DEFAULT 0,
    idempotency_key VARCHAR(128) NOT NULL,
    created_by_identity_id UUID NOT NULL,
    submitted_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    sealed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_portfolio_scenario_portfolio
        FOREIGN KEY (portfolio_id, user_id) REFERENCES app.portfolio (id, user_id),
    CONSTRAINT fk_portfolio_scenario_identity
        FOREIGN KEY (created_by_identity_id, user_id)
        REFERENCES app.authentication_identity (id, user_id),
    CONSTRAINT uq_portfolio_scenario_owner UNIQUE (id, user_id),
    CONSTRAINT uq_portfolio_scenario_idempotency
        UNIQUE (user_id, idempotency_key),
    CONSTRAINT ck_portfolio_scenario_type CHECK (
        scenario_type IN ('NEW_MONEY', 'CONSTRAINED_REBALANCING', 'TARGET_PORTFOLIO')
    ),
    CONSTRAINT ck_portfolio_scenario_status CHECK (
        status IN ('DRAFT', 'SUBMITTED', 'SUCCEEDED', 'FAILED', 'SEALED')
    ),
    CONSTRAINT ck_portfolio_scenario_currency CHECK (base_currency = 'USD'),
    CONSTRAINT ck_portfolio_scenario_new_money CHECK (new_money_amount >= 0)
);

CREATE TABLE app.portfolio_scenario_input (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id UUID NOT NULL,
    user_id UUID NOT NULL,
    input_type VARCHAR(32) NOT NULL,
    source_id UUID NOT NULL,
    source_version INTEGER,
    payload_hash VARCHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_portfolio_scenario_input
        FOREIGN KEY (scenario_id, user_id)
        REFERENCES app.portfolio_scenario (id, user_id),
    CONSTRAINT uq_portfolio_scenario_input
        UNIQUE (scenario_id, input_type, source_id),
    CONSTRAINT ck_portfolio_scenario_input_type CHECK (
        input_type IN (
            'ACCOUNT_SNAPSHOT', 'LIABILITY_SNAPSHOT', 'INVESTMENT_PROFILE',
            'CONSTRAINT_POLICY', 'FX_SNAPSHOT'
        )
    )
);

CREATE TABLE app.rebalancing_permission (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id UUID NOT NULL,
    user_id UUID NOT NULL,
    security_public_id UUID NOT NULL,
    permission VARCHAR(32) NOT NULL,
    maximum_quantity_change NUMERIC(24, 10),
    maximum_weight_change NUMERIC(9, 8),
    CONSTRAINT fk_rebalancing_permission_scenario
        FOREIGN KEY (scenario_id, user_id)
        REFERENCES app.portfolio_scenario (id, user_id),
    CONSTRAINT uq_rebalancing_permission
        UNIQUE (scenario_id, security_public_id),
    CONSTRAINT ck_rebalancing_permission_value CHECK (
        permission IN ('LOCKED', 'BUY_ONLY', 'SELL_ONLY', 'BUY_AND_SELL')
    ),
    CONSTRAINT ck_rebalancing_permission_quantity CHECK (
        maximum_quantity_change IS NULL OR maximum_quantity_change >= 0
    ),
    CONSTRAINT ck_rebalancing_permission_weight CHECK (
        maximum_weight_change IS NULL OR maximum_weight_change BETWEEN 0 AND 1
    )
);

CREATE TABLE app.portfolio_scenario_result (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id UUID NOT NULL,
    user_id UUID NOT NULL,
    result_version VARCHAR(64) NOT NULL,
    analytics_task_id VARCHAR(128),
    valuation_status VARCHAR(32) NOT NULL,
    constraint_status VARCHAR(32) NOT NULL,
    result_payload JSONB NOT NULL,
    result_hash VARCHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_portfolio_scenario_result
        FOREIGN KEY (scenario_id, user_id)
        REFERENCES app.portfolio_scenario (id, user_id),
    CONSTRAINT uq_portfolio_scenario_result UNIQUE (scenario_id),
    CONSTRAINT uq_portfolio_scenario_result_owner UNIQUE (id, user_id),
    CONSTRAINT ck_portfolio_scenario_valuation CHECK (
        valuation_status IN ('COMPLETE', 'INCOMPLETE')
    ),
    CONSTRAINT ck_portfolio_scenario_constraint CHECK (
        constraint_status IN ('PASSED', 'VIOLATED')
    ),
    CONSTRAINT ck_portfolio_scenario_result_payload
        CHECK (jsonb_typeof(result_payload) = 'object')
);

CREATE TABLE app.investment_decision (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    portfolio_id UUID NOT NULL,
    scenario_result_id UUID NOT NULL,
    created_by_identity_id UUID NOT NULL,
    supersedes_decision_id UUID,
    conclusion VARCHAR(32) NOT NULL,
    rationale TEXT NOT NULL,
    thesis TEXT,
    counterevidence TEXT,
    invalidation_conditions TEXT,
    analysis_references JSONB NOT NULL DEFAULT '[]'::JSONB,
    content_hash VARCHAR(64) NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_investment_decision_portfolio
        FOREIGN KEY (portfolio_id, user_id) REFERENCES app.portfolio (id, user_id),
    CONSTRAINT fk_investment_decision_identity
        FOREIGN KEY (created_by_identity_id, user_id)
        REFERENCES app.authentication_identity (id, user_id),
    CONSTRAINT fk_investment_decision_supersedes
        FOREIGN KEY (supersedes_decision_id, user_id)
        REFERENCES app.investment_decision (id, user_id),
    CONSTRAINT uq_investment_decision_owner UNIQUE (id, user_id),
    CONSTRAINT uq_investment_decision_result UNIQUE (scenario_result_id),
    CONSTRAINT ck_investment_decision_conclusion CHECK (
        conclusion IN ('ACCEPTED', 'REJECTED', 'DEFERRED', 'NO_ACTION')
    ),
    CONSTRAINT ck_investment_decision_analysis_references
        CHECK (jsonb_typeof(analysis_references) = 'array'),
    CONSTRAINT ck_investment_decision_not_self_superseding
        CHECK (supersedes_decision_id IS NULL OR supersedes_decision_id <> id)
);

ALTER TABLE app.investment_decision
ADD CONSTRAINT fk_investment_decision_scenario_result
FOREIGN KEY (scenario_result_id, user_id)
REFERENCES app.portfolio_scenario_result (id, user_id);

CREATE TABLE app.audit_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app.user_account (id),
    actor_identity_id UUID,
    correlation_id VARCHAR(128) NOT NULL,
    action VARCHAR(128) NOT NULL,
    entity_type VARCHAR(128) NOT NULL,
    entity_id UUID,
    outcome VARCHAR(32) NOT NULL,
    before_hash VARCHAR(64),
    after_hash VARCHAR(64),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_audit_event_identity
        FOREIGN KEY (actor_identity_id, user_id)
        REFERENCES app.authentication_identity (id, user_id),
    CONSTRAINT ck_audit_event_outcome
        CHECK (outcome IN ('SUCCEEDED', 'REJECTED', 'FAILED'))
);

CREATE FUNCTION app.reject_immutable_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is immutable', TG_TABLE_NAME;
END;
$$;

CREATE FUNCTION app.seal_account_snapshot()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'account_snapshot is immutable';
    END IF;
    IF OLD.sealed_at IS NULL
       AND NEW.sealed_at IS NOT NULL
       AND NEW.id = OLD.id
       AND NEW.user_id = OLD.user_id
       AND NEW.account_id = OLD.account_id
       AND NEW.as_of_time = OLD.as_of_time
       AND NEW.source_type = OLD.source_type
       AND NEW.source_reference IS NOT DISTINCT FROM OLD.source_reference
       AND NEW.completeness = OLD.completeness
       AND NEW.content_hash = OLD.content_hash
       AND NEW.idempotency_key = OLD.idempotency_key
       AND NEW.recorded_at = OLD.recorded_at THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'account_snapshot is immutable after creation';
END;
$$;

CREATE FUNCTION app.protect_account_snapshot_item()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    parent_sealed_at TIMESTAMPTZ;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION '% is immutable', TG_TABLE_NAME;
    END IF;
    SELECT sealed_at INTO parent_sealed_at
    FROM app.account_snapshot
    WHERE id = NEW.snapshot_id AND user_id = NEW.user_id;
    IF parent_sealed_at IS NOT NULL THEN
        RAISE EXCEPTION 'Cannot add an item to a sealed account snapshot';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER tr_investment_profile_immutable
BEFORE UPDATE OR DELETE ON app.investment_profile_version
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_investment_goal_immutable
BEFORE UPDATE OR DELETE ON app.investment_goal
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_sector_preference_immutable
BEFORE UPDATE OR DELETE ON app.sector_preference
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_account_snapshot_immutable
BEFORE UPDATE OR DELETE ON app.account_snapshot
FOR EACH ROW EXECUTE FUNCTION app.seal_account_snapshot();
CREATE TRIGGER tr_cash_balance_snapshot_immutable
BEFORE INSERT OR UPDATE OR DELETE ON app.cash_balance_snapshot
FOR EACH ROW EXECUTE FUNCTION app.protect_account_snapshot_item();
CREATE TRIGGER tr_position_snapshot_immutable
BEFORE INSERT OR UPDATE OR DELETE ON app.position_snapshot
FOR EACH ROW EXECUTE FUNCTION app.protect_account_snapshot_item();
CREATE TRIGGER tr_liability_balance_snapshot_immutable
BEFORE UPDATE OR DELETE ON app.liability_balance_snapshot
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_constraint_policy_immutable
BEFORE UPDATE OR DELETE ON app.constraint_policy_version
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_sector_constraint_immutable
BEFORE UPDATE OR DELETE ON app.sector_constraint
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_scenario_input_immutable
BEFORE UPDATE OR DELETE ON app.portfolio_scenario_input
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_scenario_result_immutable
BEFORE UPDATE OR DELETE ON app.portfolio_scenario_result
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_investment_decision_immutable
BEFORE UPDATE OR DELETE ON app.investment_decision
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_audit_event_immutable
BEFORE UPDATE OR DELETE ON app.audit_event
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();

CREATE INDEX ix_authentication_identity_user
    ON app.authentication_identity (user_id);
CREATE INDEX ix_account_snapshot_latest
    ON app.account_snapshot (account_id, as_of_time DESC);
CREATE INDEX ix_liability_balance_latest
    ON app.liability_balance_snapshot (liability_id, as_of_time DESC);
CREATE INDEX ix_portfolio_scenario_user
    ON app.portfolio_scenario (user_id, created_at DESC);
CREATE INDEX ix_investment_decision_user
    ON app.investment_decision (user_id, decided_at DESC);
CREATE INDEX ix_audit_event_user
    ON app.audit_event (user_id, recorded_at DESC);
