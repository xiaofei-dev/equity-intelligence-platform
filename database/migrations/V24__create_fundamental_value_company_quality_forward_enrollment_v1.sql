-- Development-only prospective enrollment for the narrow Fundamental Value
-- company-quality predictor. This is not a complete Fundamental Value result.

CREATE FUNCTION analytics.fv_cq_forward_utc_text_v1(value TIMESTAMPTZ)
RETURNS TEXT LANGUAGE plpgsql IMMUTABLE STRICT AS $$
BEGIN
  IF NOT isfinite(value) THEN
    RAISE EXCEPTION 'FV_CQ_FORWARD_TIMESTAMP_NOT_FINITE';
  END IF;
  IF value < TIMESTAMPTZ '0001-01-01 00:00:00+00'
     OR value > TIMESTAMPTZ '9999-12-31 23:59:59+00' THEN
    RAISE EXCEPTION 'FV_CQ_FORWARD_TIMESTAMP_OUTSIDE_TYPED_RANGE';
  END IF;
  IF date_trunc('second',value)<>value THEN
    RAISE EXCEPTION 'FV_CQ_FORWARD_TIMESTAMP_NOT_WHOLE_SECOND';
  END IF;
  RETURN to_char(value AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS')||'+00';
END
$$;

CREATE FUNCTION analytics.fv_cq_forward_date_text_v1(value DATE)
RETURNS TEXT LANGUAGE plpgsql IMMUTABLE STRICT AS $$
BEGIN
  IF NOT isfinite(value) THEN
    RAISE EXCEPTION 'FV_CQ_FORWARD_DATE_NOT_FINITE';
  END IF;
  IF value < DATE '0001-01-01' OR value > DATE '9999-12-31' THEN
    RAISE EXCEPTION 'FV_CQ_FORWARD_DATE_OUTSIDE_TYPED_RANGE';
  END IF;
  RETURN to_char(value,'YYYY-MM-DD');
END
$$;

CREATE FUNCTION analytics.fv_cq_forward_decimal_text_v1(value NUMERIC)
RETURNS TEXT LANGUAGE SQL IMMUTABLE STRICT AS $$
  SELECT CASE WHEN value=0 THEN '0'
    WHEN position('.' IN value::TEXT)>0
      THEN rtrim(rtrim(value::TEXT,'0'),'.')
    ELSE value::TEXT END
$$;

CREATE FUNCTION analytics.fv_cq_forward_hash_atom_v1(value TEXT)
RETURNS BOOLEAN LANGUAGE SQL IMMUTABLE STRICT AS $$
  SELECT btrim(value,' '||chr(9)||chr(10)||chr(13)||chr(12)||chr(11))<>''
    AND position(':' IN value)=0 AND position('|' IN value)=0
$$;

CREATE TABLE analytics.fv_cq_forward_enrollment_v1 (
    enrollment_id UUID PRIMARY KEY,
    contract_version VARCHAR(128) NOT NULL,
    claim_scope VARCHAR(64) NOT NULL,
    evidence_label VARCHAR(32) NOT NULL,
    evidence_stratum VARCHAR(64) NOT NULL,
    population_scope VARCHAR(64) NOT NULL,
    decision_cutoff TIMESTAMPTZ NOT NULL,
    evidence_cutoff TIMESTAMPTZ NOT NULL,
    sealed_at TIMESTAMPTZ NOT NULL,
    population_content_hash VARCHAR(71) NOT NULL,
    evidence_manifest_content_hash VARCHAR(71) NOT NULL,
    predictor_contract_content_hash VARCHAR(71) NOT NULL,
    model_version VARCHAR(128) NOT NULL,
    producer_version VARCHAR(128) NOT NULL,
    arithmetic_version VARCHAR(128) NOT NULL,
    cost_policy_version VARCHAR(128) NOT NULL,
    outcome_policy_version VARCHAR(128) NOT NULL,
    outcome_protocol_content_hash VARCHAR(71) NOT NULL,
    stage7_acceptance_content_hash VARCHAR(71) NOT NULL,
    stage8a_content_hash VARCHAR(71) NOT NULL,
    expected_decision_session_count INTEGER NOT NULL,
    decision_session_set_hash VARCHAR(71) NOT NULL,
    expected_entry_session_count INTEGER NOT NULL,
    entry_session_set_hash VARCHAR(71) NOT NULL,
    expected_member_count INTEGER NOT NULL,
    expected_usable_count INTEGER NOT NULL,
    expected_reason_count INTEGER NOT NULL,
    primary_horizon_sessions INTEGER NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    enrollment_content_hash VARCHAR(71) NOT NULL UNIQUE,
    supersedes_enrollment_id UUID,
    enrollment_revision INTEGER NOT NULL,
    no_outcome_accessed BOOLEAN NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT date_trunc('second',CURRENT_TIMESTAMP),
    CHECK (contract_version = 'FV-CQ-FORWARD-ENROLLMENT-v1.0.0'),
    CHECK (claim_scope = 'COMPANY_QUALITY_ONLY'),
    CHECK (evidence_label = 'NOT_VALIDATED'),
    CHECK (evidence_stratum = 'CURRENT_REVISION_APPROXIMATION'),
    CHECK (population_scope = 'CURRENT_SURVIVOR_DEVELOPMENT_POPULATION'),
    CHECK (model_version = 'FUNDAMENTAL-VALUE-v1.0.0'),
    CHECK (producer_version =
        'FV-STAGE7C5-EODHD-PROVIDER-NATIVE-COMPANY-QUALITY-v1.0.0'),
    CHECK (arithmetic_version = 'FV-STAGE7C9-DECIMAL-ARITHMETIC-v1.0.0'),
    CHECK (cost_policy_version = 'LIQUIDITY-SENSITIVE-COST-v1.0.0'),
    CHECK (outcome_policy_version =
        'FV-STAGE8A-READINESS-PREREGISTRATION-v1.0.0'),
    CHECK (primary_horizon_sessions = 756),
    CHECK (enrollment_revision = 1 AND supersedes_enrollment_id IS NULL),
    CHECK (expected_decision_session_count = 2 AND expected_entry_session_count=2
        AND decision_session_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND entry_session_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND expected_member_count = 191 AND expected_usable_count >= 100
        AND expected_usable_count <= expected_member_count
        AND expected_reason_count >= 0),
    CHECK (no_outcome_accessed),
    CHECK (analytics.fv_cq_forward_utc_text_v1(decision_cutoff) IS NOT NULL
        AND analytics.fv_cq_forward_utc_text_v1(evidence_cutoff) IS NOT NULL
        AND analytics.fv_cq_forward_utc_text_v1(sealed_at) IS NOT NULL
        AND analytics.fv_cq_forward_utc_text_v1(recorded_at) IS NOT NULL
        AND evidence_cutoff = decision_cutoff
        AND decision_cutoff <= sealed_at AND sealed_at <= recorded_at
        ),
    CHECK (population_content_hash =
          'sha256:b29306ce3b1a047c074b68fda07149fff72f7b2ecd2bc0d78aad7b42692656c7'
        AND evidence_manifest_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND predictor_contract_content_hash =
          'sha256:a9a8787104d9cb9bb764a21df3de6b22807f893ff86da5c69609b6bbbd89a995'
        AND stage7_acceptance_content_hash =
          'sha256:97048a8497f44740edd3c072aabd3de86a26d82181462fb620174b8e217bff6b'
        AND stage8a_content_hash =
          'sha256:c10dce1cdf46f4ef0a90b227e39230874db2dfa7edd49349859890f7a9800f10'
        AND outcome_protocol_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND enrollment_content_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE analytics.fv_cq_forward_decision_session_v1 (
    enrollment_id UUID NOT NULL REFERENCES analytics.fv_cq_forward_enrollment_v1,
    mic CHAR(4) NOT NULL,
    completed_session_id UUID NOT NULL REFERENCES analytics.evidence_completed_session_v1(id),
    calendar_id VARCHAR(64) NOT NULL,
    calendar_version VARCHAR(128) NOT NULL,
    session_date DATE NOT NULL,
    scheduled_open TIMESTAMPTZ NOT NULL,
    scheduled_close TIMESTAMPTZ NOT NULL,
    early_close BOOLEAN NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    session_content_hash VARCHAR(71) NOT NULL,
    calendar_content_hash VARCHAR(71) NOT NULL,
    row_content_hash VARCHAR(71) NOT NULL,
    PRIMARY KEY (enrollment_id,mic),
    UNIQUE (enrollment_id,completed_session_id),
    UNIQUE (enrollment_id,calendar_id,calendar_version),
    UNIQUE (enrollment_id,session_content_hash),
    CHECK (mic IN ('XNYS','XNAS')
        AND analytics.fv_cq_forward_date_text_v1(session_date) IS NOT NULL
        AND analytics.fv_cq_forward_utc_text_v1(scheduled_open) IS NOT NULL
        AND analytics.fv_cq_forward_utc_text_v1(scheduled_close) IS NOT NULL
        AND analytics.fv_cq_forward_utc_text_v1(completed_at) IS NOT NULL
        AND analytics.fv_cq_forward_utc_text_v1(recorded_at) IS NOT NULL
        AND analytics.fv_cq_forward_hash_atom_v1(calendar_id)
        AND analytics.fv_cq_forward_hash_atom_v1(calendar_version)
        AND scheduled_open<scheduled_close
        AND scheduled_close<=completed_at
        AND completed_at<=recorded_at
        AND session_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND calendar_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND row_content_hash ~ '^sha256:[0-9a-f]{64}$'
        )
);

CREATE TABLE analytics.fv_cq_forward_planned_entry_v1 (
    enrollment_id UUID NOT NULL REFERENCES analytics.fv_cq_forward_enrollment_v1,
    mic CHAR(4) NOT NULL,
    schedule_source_id VARCHAR(128) NOT NULL,
    schedule_source_version VARCHAR(128) NOT NULL,
    schedule_source_content_hash VARCHAR(71) NOT NULL,
    entry_date DATE NOT NULL,
    scheduled_open TIMESTAMPTZ NOT NULL,
    scheduled_close TIMESTAMPTZ NOT NULL,
    early_close BOOLEAN NOT NULL,
    schedule_content_hash VARCHAR(71) NOT NULL,
    state VARCHAR(32) NOT NULL,
    row_content_hash VARCHAR(71) NOT NULL,
    PRIMARY KEY (enrollment_id,mic),
    CHECK (mic IN ('XNYS','XNAS')
        AND analytics.fv_cq_forward_date_text_v1(entry_date) IS NOT NULL
        AND analytics.fv_cq_forward_utc_text_v1(scheduled_open) IS NOT NULL
        AND analytics.fv_cq_forward_utc_text_v1(scheduled_close) IS NOT NULL
        AND analytics.fv_cq_forward_hash_atom_v1(schedule_source_id)
        AND analytics.fv_cq_forward_hash_atom_v1(schedule_source_version)
        AND scheduled_open<scheduled_close
        AND entry_date=(scheduled_open AT TIME ZONE 'UTC')::DATE
        AND entry_date=(scheduled_close AT TIME ZONE 'UTC')::DATE
        AND state='SCHEDULED_NOT_COMPLETED'
        AND schedule_source_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND schedule_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND row_content_hash ~ '^sha256:[0-9a-f]{64}$'
        )
);

CREATE TABLE analytics.fv_cq_forward_parent_role_v1 (
    operand_code VARCHAR(64) PRIMARY KEY,
    canonical_field_code VARCHAR(64) NOT NULL,
    provenance_kind VARCHAR(40) NOT NULL,
    required_count INTEGER NOT NULL CHECK (required_count > 0),
    UNIQUE (canonical_field_code, provenance_kind),
    UNIQUE (operand_code, canonical_field_code, provenance_kind),
    CHECK (provenance_kind IN ('V22_SELECTED_EVIDENCE','V24_PROVIDER_NORMALIZED_PARENT'))
);

INSERT INTO analytics.fv_cq_forward_parent_role_v1 VALUES
('REVENUE','REVENUE','V22_SELECTED_EVIDENCE',8),
('OPERATING_INCOME','OPERATING_INCOME','V22_SELECTED_EVIDENCE',8),
('NET_INCOME','NET_INCOME','V22_SELECTED_EVIDENCE',8),
('OPERATING_CASH_FLOW','OPERATING_CASH_FLOW','V22_SELECTED_EVIDENCE',8),
('CAPITAL_EXPENDITURE','CAPITAL_EXPENDITURE','V22_SELECTED_EVIDENCE',8),
('INCOME_TAX','INCOME_TAX','V24_PROVIDER_NORMALIZED_PARENT',4),
('PRETAX_INCOME','PRETAX_INCOME','V24_PROVIDER_NORMALIZED_PARENT',4),
('STOCKHOLDERS_EQUITY','TOTAL_EQUITY','V22_SELECTED_EVIDENCE',5),
('TOTAL_DEBT','TOTAL_DEBT','V22_SELECTED_EVIDENCE',5),
('CASH_AND_EQUIVALENTS','CASH_AND_EQUIVALENTS','V22_SELECTED_EVIDENCE',5);

CREATE TABLE analytics.fv_cq_forward_normalized_parent_v1 (
    normalized_parent_id UUID PRIMARY KEY,
    security_id UUID NOT NULL REFERENCES analytics.security (public_id),
    company_id UUID NOT NULL REFERENCES analytics.evidence_company_identity_v1,
    instrument_id UUID NOT NULL REFERENCES analytics.evidence_instrument_identity_v1,
    share_class_id UUID NOT NULL REFERENCES analytics.evidence_share_class_identity_v1,
    listing_id UUID NOT NULL REFERENCES analytics.evidence_listing_identity_v1,
    ticker_assignment_id UUID NOT NULL REFERENCES analytics.evidence_ticker_assignment_v1,
    raw_manifest_id UUID NOT NULL REFERENCES analytics.evidence_raw_manifest_v1 (id),
    canonical_field_code VARCHAR(64) NOT NULL,
    numeric_value NUMERIC NOT NULL,
    period_start DATE,
    period_end DATE NOT NULL,
    source_content_hash VARCHAR(71) NOT NULL,
    normalized_record_hash VARCHAR(71) NOT NULL UNIQUE,
    provider_code VARCHAR(128) NOT NULL,
    provider_schema_version VARCHAR(128) NOT NULL,
    source_record_id VARCHAR(255) NOT NULL,
    source_revision INTEGER NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL,
    currency CHAR(3) NOT NULL,
    unit VARCHAR(32) NOT NULL,
    UNIQUE (raw_manifest_id,canonical_field_code,period_end),
    CHECK (canonical_field_code IN ('INCOME_TAX','PRETAX_INCOME')
        AND numeric_value::TEXT NOT IN ('NaN','Infinity','-Infinity')
        AND source_revision > 0 AND currency='USD' AND btrim(unit)<>''
        AND analytics.fv_cq_forward_date_text_v1(period_end) IS NOT NULL
        AND (period_start IS NULL OR
          (analytics.fv_cq_forward_date_text_v1(period_start) IS NOT NULL
            AND period_start<=period_end))
        AND analytics.fv_cq_forward_hash_atom_v1(provider_code)
        AND analytics.fv_cq_forward_hash_atom_v1(provider_schema_version)
        AND analytics.fv_cq_forward_hash_atom_v1(source_record_id)
        AND analytics.fv_cq_forward_hash_atom_v1(unit)
        AND source_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND normalized_record_hash ~ '^sha256:[0-9a-f]{64}$'
        AND analytics.fv_cq_forward_utc_text_v1(effective_at) IS NOT NULL
        AND analytics.fv_cq_forward_utc_text_v1(available_at) IS NOT NULL
        AND analytics.fv_cq_forward_utc_text_v1(ingested_at) IS NOT NULL
        AND effective_at<=available_at AND available_at<=ingested_at)
);

CREATE TABLE analytics.fv_cq_forward_member_v1 (
    enrollment_id UUID NOT NULL REFERENCES analytics.fv_cq_forward_enrollment_v1,
    member_ordinal INTEGER NOT NULL,
    security_id UUID NOT NULL REFERENCES analytics.security (public_id),
    company_id UUID NOT NULL REFERENCES analytics.evidence_company_identity_v1,
    instrument_id UUID NOT NULL REFERENCES analytics.evidence_instrument_identity_v1,
    share_class_id UUID NOT NULL REFERENCES analytics.evidence_share_class_identity_v1,
    listing_id UUID NOT NULL REFERENCES analytics.evidence_listing_identity_v1,
    ticker_assignment_id UUID NOT NULL REFERENCES analytics.evidence_ticker_assignment_v1,
    listing_mic CHAR(4) NOT NULL,
    terminal_state VARCHAR(40) NOT NULL,
    predictor_score NUMERIC,
    predictor_rank INTEGER,
    predictor_group VARCHAR(8),
    evidence_available_at TIMESTAMPTZ,
    evidence_ingested_at TIMESTAMPTZ,
    evidence_content_hash VARCHAR(71),
    source_content_hash VARCHAR(71),
    producer_contract_content_hash VARCHAR(71),
    producer_output_content_hash VARCHAR(71),
    row_content_hash VARCHAR(71) NOT NULL,
    expected_evidence_count INTEGER NOT NULL,
    expected_reason_count INTEGER NOT NULL,
    PRIMARY KEY (enrollment_id, member_ordinal),
    UNIQUE (enrollment_id, security_id),
    UNIQUE (enrollment_id, listing_id),
    UNIQUE (enrollment_id, ticker_assignment_id),
    FOREIGN KEY (enrollment_id,listing_mic)
        REFERENCES analytics.fv_cq_forward_decision_session_v1(enrollment_id,mic),
    CHECK (member_ordinal > 0 AND expected_reason_count >= 0
        AND expected_evidence_count >= 0 AND listing_mic IN ('XNYS','XNAS')),
    CHECK (terminal_state IN ('USABLE_VALID','MISSING','STALE','INVALID',
        'NOT_APPLICABLE','SPECIALIZED_MODEL_REQUIRED','EXCLUDED','INSUFFICIENT_DATA')),
    CHECK (row_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK ((terminal_state = 'USABLE_VALID'
        AND predictor_score IS NOT NULL
        AND predictor_score::TEXT NOT IN ('NaN','Infinity','-Infinity')
        AND predictor_rank > 0 AND predictor_group IN ('HIGH','MIDDLE','LOW')
        AND evidence_available_at IS NOT NULL AND evidence_ingested_at IS NOT NULL
        AND analytics.fv_cq_forward_utc_text_v1(evidence_available_at) IS NOT NULL
        AND analytics.fv_cq_forward_utc_text_v1(evidence_ingested_at) IS NOT NULL
        AND evidence_available_at <= evidence_ingested_at
        AND evidence_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND source_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND producer_contract_content_hash =
          'sha256:a9a8787104d9cb9bb764a21df3de6b22807f893ff86da5c69609b6bbbd89a995'
        AND producer_output_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND expected_reason_count = 0 AND expected_evidence_count > 0)
      OR (terminal_state <> 'USABLE_VALID'
        AND predictor_score IS NULL AND predictor_rank IS NULL
        AND predictor_group IS NULL AND evidence_available_at IS NULL
        AND evidence_ingested_at IS NULL AND evidence_content_hash IS NULL
        AND source_content_hash IS NULL AND producer_contract_content_hash IS NULL
        AND producer_output_content_hash IS NULL AND expected_reason_count > 0
        AND expected_evidence_count = 0))
);

CREATE TABLE analytics.fv_cq_forward_member_evidence_v1 (
    enrollment_id UUID NOT NULL,
    member_ordinal INTEGER NOT NULL,
    evidence_ordinal INTEGER NOT NULL,
    operand_code VARCHAR(64) NOT NULL,
    canonical_field_code VARCHAR(64) NOT NULL,
    provenance_kind VARCHAR(40) NOT NULL,
    numeric_value NUMERIC NOT NULL,
    selection_request_id UUID
        REFERENCES analytics.evidence_selection_request_v1 (request_id),
    selection_result_hash VARCHAR(71),
    canonical_evidence_id UUID
        REFERENCES analytics.canonical_evidence_v1 (evidence_id),
    normalized_parent_id UUID
        REFERENCES analytics.fv_cq_forward_normalized_parent_v1 (normalized_parent_id),
    raw_manifest_id UUID NOT NULL REFERENCES analytics.evidence_raw_manifest_v1 (id),
    provider_code VARCHAR(128) NOT NULL,
    provider_schema_version VARCHAR(128) NOT NULL,
    source_record_id VARCHAR(255) NOT NULL,
    source_revision INTEGER NOT NULL,
    parent_period_start DATE,
    parent_period_end DATE NOT NULL,
    parent_source_content_hash VARCHAR(71) NOT NULL,
    parent_normalized_record_hash VARCHAR(71) NOT NULL,
    parent_effective_at TIMESTAMPTZ NOT NULL,
    parent_available_at TIMESTAMPTZ NOT NULL,
    parent_ingested_at TIMESTAMPTZ NOT NULL,
    currency CHAR(3) NOT NULL,
    unit VARCHAR(32) NOT NULL,
    PRIMARY KEY (enrollment_id, member_ordinal, evidence_ordinal),
    UNIQUE (enrollment_id, member_ordinal, operand_code, parent_period_end),
    UNIQUE (enrollment_id, selection_request_id),
    UNIQUE (enrollment_id, selection_result_hash),
    UNIQUE (enrollment_id, canonical_evidence_id),
    FOREIGN KEY (enrollment_id, member_ordinal)
        REFERENCES analytics.fv_cq_forward_member_v1,
    FOREIGN KEY (operand_code,canonical_field_code,provenance_kind)
        REFERENCES analytics.fv_cq_forward_parent_role_v1
        (operand_code,canonical_field_code,provenance_kind),
    CHECK (evidence_ordinal > 0),
    CHECK (operand_code IN ('REVENUE','OPERATING_INCOME','NET_INCOME',
        'INCOME_TAX','PRETAX_INCOME','STOCKHOLDERS_EQUITY','TOTAL_DEBT',
        'CASH_AND_EQUIVALENTS','OPERATING_CASH_FLOW','CAPITAL_EXPENDITURE')),
    CHECK (provenance_kind IN ('V22_SELECTED_EVIDENCE','V24_PROVIDER_NORMALIZED_PARENT')
        AND numeric_value::TEXT NOT IN ('NaN','Infinity','-Infinity')
        AND abs(numeric_value)<=1e100::NUMERIC
        AND CASE
          WHEN position('.' IN analytics.fv_cq_forward_decimal_text_v1(numeric_value))=0
            THEN TRUE
          ELSE length(split_part(
            analytics.fv_cq_forward_decimal_text_v1(numeric_value),'.',2))<=100
          END
        AND (operand_code<>'CAPITAL_EXPENDITURE' OR numeric_value>=0)
        AND source_revision > 0),
    CHECK ((operand_code IN ('INCOME_TAX','PRETAX_INCOME')
          AND provenance_kind='V24_PROVIDER_NORMALIZED_PARENT'
          AND selection_request_id IS NULL AND selection_result_hash IS NULL
          AND canonical_evidence_id IS NULL AND normalized_parent_id IS NOT NULL)
        OR (operand_code NOT IN ('INCOME_TAX','PRETAX_INCOME')
          AND provenance_kind='V22_SELECTED_EVIDENCE'
          AND selection_request_id IS NOT NULL AND selection_result_hash IS NOT NULL
          AND canonical_evidence_id IS NOT NULL AND normalized_parent_id IS NULL)),
    CHECK ((selection_result_hash IS NULL OR selection_result_hash ~ '^sha256:[0-9a-f]{64}$')
        AND parent_source_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND parent_normalized_record_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (currency='USD' AND btrim(unit)<>''
          AND analytics.fv_cq_forward_date_text_v1(parent_period_end) IS NOT NULL
          AND (parent_period_start IS NULL OR
            (analytics.fv_cq_forward_date_text_v1(parent_period_start) IS NOT NULL
              AND parent_period_start<=parent_period_end))
          AND analytics.fv_cq_forward_hash_atom_v1(provider_code)
          AND analytics.fv_cq_forward_hash_atom_v1(provider_schema_version)
          AND analytics.fv_cq_forward_hash_atom_v1(source_record_id)
          AND analytics.fv_cq_forward_hash_atom_v1(unit)
          AND analytics.fv_cq_forward_utc_text_v1(parent_effective_at) IS NOT NULL
          AND analytics.fv_cq_forward_utc_text_v1(parent_available_at) IS NOT NULL
          AND analytics.fv_cq_forward_utc_text_v1(parent_ingested_at) IS NOT NULL
          AND parent_effective_at<=parent_available_at
          AND parent_available_at<=parent_ingested_at)
);

CREATE UNIQUE INDEX fv_cq_forward_provider_normalized_parent_uq
ON analytics.fv_cq_forward_member_evidence_v1(enrollment_id,normalized_parent_id)
WHERE provenance_kind='V24_PROVIDER_NORMALIZED_PARENT';

CREATE UNIQUE INDEX fv_cq_forward_provider_normalized_hash_uq
ON analytics.fv_cq_forward_member_evidence_v1(
  enrollment_id,parent_normalized_record_hash)
WHERE provenance_kind='V24_PROVIDER_NORMALIZED_PARENT';

CREATE UNIQUE INDEX fv_cq_forward_provider_raw_field_period_uq
ON analytics.fv_cq_forward_member_evidence_v1(
  enrollment_id,raw_manifest_id,canonical_field_code,parent_period_end)
WHERE provenance_kind='V24_PROVIDER_NORMALIZED_PARENT';

CREATE TABLE analytics.fv_cq_forward_member_reason_v1 (
    enrollment_id UUID NOT NULL,
    member_ordinal INTEGER NOT NULL,
    reason_ordinal INTEGER NOT NULL,
    reason_code VARCHAR(128) NOT NULL,
    PRIMARY KEY (enrollment_id, member_ordinal, reason_ordinal),
    UNIQUE (enrollment_id, member_ordinal, reason_code),
    CHECK (analytics.fv_cq_forward_hash_atom_v1(reason_code)),
    FOREIGN KEY (enrollment_id, member_ordinal)
        REFERENCES analytics.fv_cq_forward_member_v1,
    CHECK (reason_ordinal > 0 AND btrim(reason_code) <> '')
);

CREATE TABLE analytics.fv_cq_forward_maturity_v1 (
    enrollment_id UUID NOT NULL REFERENCES analytics.fv_cq_forward_enrollment_v1,
    horizon_sessions INTEGER NOT NULL,
    maturity_state VARCHAR(32) NOT NULL,
    outcome_row_count INTEGER NOT NULL,
    horizon_role VARCHAR(16) NOT NULL,
    protocol_content_hash VARCHAR(71) NOT NULL,
    schedule_content_hash VARCHAR(71) NOT NULL,
    PRIMARY KEY (enrollment_id, horizon_sessions),
    CHECK (horizon_sessions IN (252,504,756)),
    CHECK (maturity_state = 'AWAITING_NATURAL_MATURITY'),
    CHECK (outcome_row_count = 0),
    CHECK (horizon_role = CASE horizon_sessions WHEN 252 THEN 'DIAGNOSTIC'
        WHEN 504 THEN 'SUPPORTING' ELSE 'PRIMARY' END),
    CHECK (protocol_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND schedule_content_hash ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE analytics.fv_cq_forward_enrollment_seal_v1 (
    enrollment_id UUID PRIMARY KEY REFERENCES analytics.fv_cq_forward_enrollment_v1,
    decision_session_set_hash VARCHAR(71) NOT NULL,
    entry_session_set_hash VARCHAR(71) NOT NULL,
    member_set_hash VARCHAR(71) NOT NULL,
    ranked_group_set_hash VARCHAR(71) NOT NULL,
    reason_set_hash VARCHAR(71) NOT NULL,
    evidence_set_hash VARCHAR(71) NOT NULL,
    maturity_set_hash VARCHAR(71) NOT NULL,
    seal_content_hash VARCHAR(71) NOT NULL UNIQUE,
    sealed_at TIMESTAMPTZ NOT NULL,
    creator_xid8 xid8 NOT NULL DEFAULT pg_current_xact_id(),
    CHECK (decision_session_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND entry_session_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND member_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND ranked_group_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND reason_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND evidence_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND maturity_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND seal_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND analytics.fv_cq_forward_utc_text_v1(sealed_at) IS NOT NULL)
);

CREATE FUNCTION analytics.set_fv_cq_forward_seal_creator_xid8_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$ BEGIN
  NEW.creator_xid8 := pg_current_xact_id();
  RETURN NEW;
END $$;

CREATE TRIGGER fv_cq_forward_seal_creator_xid8_v1 BEFORE INSERT
ON analytics.fv_cq_forward_enrollment_seal_v1 FOR EACH ROW
EXECUTE FUNCTION analytics.set_fv_cq_forward_seal_creator_xid8_v1();

CREATE FUNCTION analytics.fv_round_half_even_v1(value NUMERIC, scale_digits INTEGER)
RETURNS NUMERIC LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE
  magnitude NUMERIC := abs(value);
  quantum NUMERIC := ('1e'||(-scale_digits)::TEXT)::NUMERIC;
  base NUMERIC := trunc(abs(value),scale_digits);
  remainder NUMERIC;
  rounded NUMERIC;
BEGIN
  remainder := magnitude-base;
  IF remainder=quantum*0.5 THEN
    rounded := base + CASE WHEN mod(trunc(base/quantum),2)=0 THEN 0 ELSE quantum END;
  ELSIF remainder>quantum*0.5 THEN
    rounded := base+quantum;
  ELSE
    rounded := base;
  END IF;
  RETURN CASE WHEN value<0 THEN -rounded ELSE rounded END;
END $$;

CREATE FUNCTION analytics.fv_cq_context28_v1(value NUMERIC)
RETURNS NUMERIC LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE
  scale_digits INTEGER;
BEGIN
  IF value=0 THEN RETURN 0; END IF;
  scale_digits := 27-floor(log(abs(value)))::INTEGER;
  RETURN analytics.fv_round_half_even_v1(value,scale_digits);
END $$;

CREATE FUNCTION analytics.fv_cq_sum_context28_v1(values_to_sum NUMERIC[])
RETURNS NUMERIC LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE
  item NUMERIC;
  result NUMERIC := 0;
BEGIN
  FOREACH item IN ARRAY values_to_sum LOOP
    result := analytics.fv_cq_context28_v1(result+item);
  END LOOP;
  RETURN result;
END $$;

CREATE FUNCTION analytics.fv_cq_div_context28_v1(numerator NUMERIC, denominator NUMERIC)
RETURNS NUMERIC LANGUAGE plpgsql IMMUTABLE STRICT AS $$
BEGIN
  IF denominator=0 THEN RAISE EXCEPTION 'FV_CQ_DIVISION_BY_ZERO'; END IF;
  RETURN analytics.fv_cq_context28_v1(
    ((numerator*1e60::NUMERIC)/denominator)*1e-60::NUMERIC);
END $$;

CREATE FUNCTION analytics.fv_cq_sqrt_context28_v1(value NUMERIC)
RETURNS NUMERIC LANGUAGE plpgsql IMMUTABLE STRICT AS $$
BEGIN
  IF value<0 THEN RAISE EXCEPTION 'FV_CQ_SQRT_NEGATIVE'; END IF;
  RETURN analytics.fv_cq_context28_v1(sqrt(value*1e120::NUMERIC)*1e-60::NUMERIC);
END $$;

CREATE FUNCTION analytics.fv_cq_stability_context28_v1(values_to_score NUMERIC[])
RETURNS NUMERIC LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE
  item NUMERIC;
  mean_value NUMERIC;
  delta NUMERIC;
  variance_sum NUMERIC := 0;
  variance_value NUMERIC;
  stability_value NUMERIC;
BEGIN
  IF cardinality(values_to_score)=0 THEN RETURN NULL; END IF;
  mean_value := analytics.fv_cq_div_context28_v1(
    analytics.fv_cq_sum_context28_v1(values_to_score),cardinality(values_to_score));
  IF abs(mean_value)<=0.000001 THEN RETURN NULL; END IF;
  FOREACH item IN ARRAY values_to_score LOOP
    delta := analytics.fv_cq_context28_v1(item-mean_value);
    variance_sum := analytics.fv_cq_context28_v1(
      variance_sum+analytics.fv_cq_context28_v1(delta*delta));
  END LOOP;
  variance_value := analytics.fv_cq_div_context28_v1(
    variance_sum,cardinality(values_to_score));
  stability_value := analytics.fv_cq_context28_v1(
    1-analytics.fv_cq_context28_v1(
      analytics.fv_cq_div_context28_v1(
        analytics.fv_cq_sqrt_context28_v1(variance_value),abs(mean_value))));
  RETURN greatest(0::NUMERIC,least(1::NUMERIC,stability_value));
END $$;

CREATE FUNCTION analytics.fv_cq_forward_expected_score_v1(
  checked_enrollment_id UUID, checked_member_ordinal INTEGER
) RETURNS NUMERIC LANGUAGE plpgsql STABLE AS $$
DECLARE
  revenue_rows NUMERIC[]; operating_rows NUMERIC[]; ocf_rows NUMERIC[];
  capex_rows NUMERIC[]; tax_rows NUMERIC[]; pretax_rows NUMERIC[];
  earnings_rows NUMERIC[]; equity_rows NUMERIC[]; debt_rows NUMERIC[];
  cash_rows NUMERIC[];
  revenue_periods DATE[]; operating_periods DATE[]; ocf_periods DATE[];
  capex_periods DATE[]; tax_periods DATE[]; pretax_periods DATE[];
  first_end DATE; last_end DATE; inferred_start DATE;
  revenue NUMERIC; operating NUMERIC; ocf NUMERIC; capex NUMERIC;
  tax_value NUMERIC; pretax NUMERIC; tax_rate NUMERIC; average_capital NUMERIC;
  capital_new NUMERIC; capital_old NUMERIC; roic NUMERIC;
  operating_margin NUMERIC; fcf_margin NUMERIC;
  earnings_stability NUMERIC; cash_stability NUMERIC;
  a NUMERIC; b NUMERIC; c NUMERIC; d NUMERIC; e NUMERIC;
BEGIN
  SELECT
    array_agg(numeric_value ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='REVENUE'),
    array_agg(numeric_value ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='OPERATING_INCOME'),
    array_agg(numeric_value ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='OPERATING_CASH_FLOW'),
    array_agg(numeric_value ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='CAPITAL_EXPENDITURE'),
    array_agg(numeric_value ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='INCOME_TAX'),
    array_agg(numeric_value ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='PRETAX_INCOME'),
    array_agg(numeric_value ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='NET_INCOME'),
    array_agg(numeric_value ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='STOCKHOLDERS_EQUITY'),
    array_agg(numeric_value ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='TOTAL_DEBT'),
    array_agg(numeric_value ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='CASH_AND_EQUIVALENTS'),
    array_agg(parent_period_end ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='REVENUE'),
    array_agg(parent_period_end ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='OPERATING_INCOME'),
    array_agg(parent_period_end ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='OPERATING_CASH_FLOW'),
    array_agg(parent_period_end ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='CAPITAL_EXPENDITURE'),
    array_agg(parent_period_end ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='INCOME_TAX'),
    array_agg(parent_period_end ORDER BY parent_period_end DESC)
      FILTER (WHERE operand_code='PRETAX_INCOME')
  INTO revenue_rows,operating_rows,ocf_rows,capex_rows,tax_rows,pretax_rows,
       earnings_rows,equity_rows,debt_rows,cash_rows,revenue_periods,
       operating_periods,ocf_periods,capex_periods,tax_periods,pretax_periods
  FROM analytics.fv_cq_forward_member_evidence_v1
  WHERE enrollment_id=checked_enrollment_id AND member_ordinal=checked_member_ordinal;
  IF cardinality(revenue_rows)<>8 OR cardinality(operating_rows)<>8
     OR cardinality(ocf_rows)<>8 OR cardinality(capex_rows)<>8
     OR cardinality(tax_rows)<>4 OR cardinality(pretax_rows)<>4
     OR cardinality(earnings_rows)<>8 OR cardinality(equity_rows)<>5
     OR cardinality(debt_rows)<>5 OR cardinality(cash_rows)<>5 THEN RETURN NULL; END IF;
  IF EXISTS (SELECT 1 FROM unnest(capex_rows) value WHERE value<0) THEN RETURN NULL; END IF;
  IF revenue_periods[1:4] IS DISTINCT FROM operating_periods[1:4]
     OR revenue_periods[1:4] IS DISTINCT FROM ocf_periods[1:4]
     OR revenue_periods[1:4] IS DISTINCT FROM capex_periods[1:4]
     OR revenue_periods[1:4] IS DISTINCT FROM tax_periods
     OR revenue_periods[1:4] IS DISTINCT FROM pretax_periods THEN RETURN NULL; END IF;
  first_end:=revenue_periods[4];
  last_end:=revenue_periods[1];
  inferred_start:=first_end-(last_end-revenue_periods[2]);
  IF EXISTS (SELECT 1 FROM analytics.fv_cq_forward_member_evidence_v1
      WHERE enrollment_id=checked_enrollment_id AND member_ordinal=checked_member_ordinal
        AND operand_code IN ('STOCKHOLDERS_EQUITY','TOTAL_DEBT','CASH_AND_EQUIVALENTS')
        AND parent_period_end>last_end) THEN RETURN NULL; END IF;
  revenue:=analytics.fv_cq_sum_context28_v1(revenue_rows[1:4]);
  operating:=analytics.fv_cq_sum_context28_v1(operating_rows[1:4]);
  ocf:=analytics.fv_cq_sum_context28_v1(ocf_rows[1:4]);
  capex:=analytics.fv_cq_sum_context28_v1(capex_rows[1:4]);
  tax_value:=analytics.fv_cq_sum_context28_v1(tax_rows);
  pretax:=analytics.fv_cq_sum_context28_v1(pretax_rows);
  IF revenue<=0 OR pretax<=0 OR capex<0
     OR EXISTS (SELECT 1 FROM unnest(capex_rows[1:4]) value WHERE value<0)
     THEN RETURN NULL; END IF;
  tax_rate:=analytics.fv_cq_div_context28_v1(tax_value,pretax);
  IF tax_rate NOT BETWEEN 0 AND 0.5 THEN RETURN NULL; END IF;
  SELECT analytics.fv_cq_context28_v1(
      analytics.fv_cq_context28_v1(eq.numeric_value+debt.numeric_value)-cash.numeric_value)
    INTO capital_old
    FROM LATERAL (SELECT numeric_value,parent_period_end
      FROM analytics.fv_cq_forward_member_evidence_v1
      WHERE enrollment_id=checked_enrollment_id AND member_ordinal=checked_member_ordinal
        AND operand_code='STOCKHOLDERS_EQUITY' AND parent_period_end<=inferred_start
        AND inferred_start-parent_period_end<=120 ORDER BY parent_period_end DESC LIMIT 1) eq,
    LATERAL (SELECT numeric_value FROM analytics.fv_cq_forward_member_evidence_v1
      WHERE enrollment_id=checked_enrollment_id AND member_ordinal=checked_member_ordinal
        AND operand_code='TOTAL_DEBT' AND parent_period_end<=inferred_start
        AND inferred_start-parent_period_end<=120 ORDER BY parent_period_end DESC LIMIT 1) debt,
    LATERAL (SELECT numeric_value FROM analytics.fv_cq_forward_member_evidence_v1
      WHERE enrollment_id=checked_enrollment_id AND member_ordinal=checked_member_ordinal
        AND operand_code='CASH_AND_EQUIVALENTS' AND parent_period_end<=inferred_start
        AND inferred_start-parent_period_end<=120 ORDER BY parent_period_end DESC LIMIT 1) cash;
  SELECT analytics.fv_cq_context28_v1(
      analytics.fv_cq_context28_v1(eq.numeric_value+debt.numeric_value)-cash.numeric_value)
    INTO capital_new
    FROM LATERAL (SELECT numeric_value FROM analytics.fv_cq_forward_member_evidence_v1
      WHERE enrollment_id=checked_enrollment_id AND member_ordinal=checked_member_ordinal
        AND operand_code='STOCKHOLDERS_EQUITY' AND parent_period_end<=last_end
        AND last_end-parent_period_end<=120 ORDER BY parent_period_end DESC LIMIT 1) eq,
    LATERAL (SELECT numeric_value FROM analytics.fv_cq_forward_member_evidence_v1
      WHERE enrollment_id=checked_enrollment_id AND member_ordinal=checked_member_ordinal
        AND operand_code='TOTAL_DEBT' AND parent_period_end<=last_end
        AND last_end-parent_period_end<=120 ORDER BY parent_period_end DESC LIMIT 1) debt,
    LATERAL (SELECT numeric_value FROM analytics.fv_cq_forward_member_evidence_v1
      WHERE enrollment_id=checked_enrollment_id AND member_ordinal=checked_member_ordinal
        AND operand_code='CASH_AND_EQUIVALENTS' AND parent_period_end<=last_end
        AND last_end-parent_period_end<=120 ORDER BY parent_period_end DESC LIMIT 1) cash;
  IF capital_old IS NULL OR capital_new IS NULL THEN RETURN NULL; END IF;
  average_capital:=analytics.fv_cq_div_context28_v1(
    analytics.fv_cq_context28_v1(capital_new+capital_old),2);
  IF average_capital<=0 THEN RETURN NULL; END IF;
  roic:=analytics.fv_cq_div_context28_v1(
    analytics.fv_cq_context28_v1(
      operating*analytics.fv_cq_context28_v1(1-tax_rate)),average_capital);
  operating_margin:=analytics.fv_cq_div_context28_v1(operating,revenue);
  fcf_margin:=analytics.fv_cq_div_context28_v1(
    analytics.fv_cq_context28_v1(ocf-capex),revenue);
  earnings_stability:=analytics.fv_cq_stability_context28_v1(earnings_rows);
  cash_stability:=analytics.fv_cq_stability_context28_v1(ocf_rows);
  IF roic NOT BETWEEN -1 AND 2 OR operating_margin NOT BETWEEN -1 AND 1
     OR fcf_margin NOT BETWEEN -2 AND 2 OR earnings_stability IS NULL
     OR cash_stability IS NULL THEN RETURN NULL; END IF;
  -- Stage 2 evaluates already-produced operands under its own precision-50 context.
  a:=analytics.fv_round_half_even_v1(greatest(0::NUMERIC,least(100::NUMERIC,
    ((roic+0.05)/0.30)*100)),2);
  b:=analytics.fv_round_half_even_v1(greatest(0::NUMERIC,least(100::NUMERIC,
    ((operating_margin+0.05)/0.35)*100)),2);
  c:=analytics.fv_round_half_even_v1(greatest(0::NUMERIC,least(100::NUMERIC,
    ((fcf_margin+0.10)/0.35)*100)),2);
  d:=analytics.fv_round_half_even_v1(earnings_stability*100,2);
  e:=analytics.fv_round_half_even_v1(cash_stability*100,2);
  RETURN analytics.fv_round_half_even_v1((a+b+c+d+e)/5,2);
END
$$;

CREATE FUNCTION analytics.validate_fv_cq_forward_enrollment_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    parent analytics.fv_cq_forward_enrollment_v1%ROWTYPE;
    member_count INTEGER;
    usable_count INTEGER;
    reason_count INTEGER;
    maturity_count INTEGER;
    decision_session_count INTEGER;
    entry_session_count INTEGER;
    bad_decision_session_count INTEGER;
    bad_entry_session_count INTEGER;
    bad_chronology INTEGER;
    bad_rank_count INTEGER;
    bad_identity_count INTEGER;
    bad_evidence_count INTEGER;
    bad_group_count INTEGER;
    bad_score_order_count INTEGER;
    bad_row_hash_count INTEGER;
    bad_schedule_count INTEGER;
    bad_member_evidence_hash_count INTEGER;
    bad_producer_output_count INTEGER;
    bad_freshness_count INTEGER;
    bad_period_alignment_count INTEGER;
    bad_balance_boundary_count INTEGER;
    seal analytics.fv_cq_forward_enrollment_seal_v1%ROWTYPE;
    computed_member_hash VARCHAR(71);
    computed_rank_hash VARCHAR(71);
    computed_reason_hash VARCHAR(71);
    computed_evidence_hash VARCHAR(71);
    computed_maturity_hash VARCHAR(71);
    computed_decision_session_hash VARCHAR(71);
    computed_entry_session_hash VARCHAR(71);
    computed_enrollment_hash VARCHAR(71);
    computed_seal_content_hash VARCHAR(71);
BEGIN
    -- Initial graph child events share the seal's server-stamped full xid8 and
    -- are covered by the enrollment-header validator. A later transaction cannot
    -- forge creator_xid8 and must run the full aggregate replay.
    IF TG_TABLE_NAME<>'fv_cq_forward_enrollment_v1' AND EXISTS (
      SELECT 1 FROM analytics.fv_cq_forward_enrollment_seal_v1 seal_marker
      WHERE seal_marker.enrollment_id=COALESCE(NEW.enrollment_id,OLD.enrollment_id)
        AND seal_marker.creator_xid8=pg_current_xact_id()) THEN
      RETURN NULL;
    END IF;
    SELECT * INTO parent FROM analytics.fv_cq_forward_enrollment_v1
      WHERE enrollment_id = COALESCE(NEW.enrollment_id, OLD.enrollment_id);
    SELECT count(*), count(*) FILTER (WHERE terminal_state='USABLE_VALID')
      INTO member_count, usable_count FROM analytics.fv_cq_forward_member_v1
      WHERE enrollment_id=parent.enrollment_id;
    SELECT count(*) INTO reason_count FROM analytics.fv_cq_forward_member_reason_v1
      WHERE enrollment_id=parent.enrollment_id;
    SELECT count(*) INTO maturity_count FROM analytics.fv_cq_forward_maturity_v1
      WHERE enrollment_id=parent.enrollment_id;
    SELECT count(*) INTO decision_session_count
      FROM analytics.fv_cq_forward_decision_session_v1
      WHERE enrollment_id=parent.enrollment_id;
    SELECT count(*) INTO entry_session_count
      FROM analytics.fv_cq_forward_planned_entry_v1
      WHERE enrollment_id=parent.enrollment_id;
    SELECT 'sha256:'||encode(sha256(convert_to(coalesce(string_agg(
      mic||':'||completed_session_id::TEXT||':'||calendar_id||':'||calendar_version||':'||
      analytics.fv_cq_forward_date_text_v1(session_date)||':'||
      analytics.fv_cq_forward_utc_text_v1(scheduled_open)||':'||
      analytics.fv_cq_forward_utc_text_v1(scheduled_close)||':'||lower(early_close::TEXT)||':'||
      analytics.fv_cq_forward_utc_text_v1(completed_at)||':'||
      analytics.fv_cq_forward_utc_text_v1(recorded_at)||':'||session_content_hash||':'||
      calendar_content_hash,'|' ORDER BY mic),''),'UTF8')),'hex')
      INTO computed_decision_session_hash
      FROM analytics.fv_cq_forward_decision_session_v1
      WHERE enrollment_id=parent.enrollment_id;
    SELECT 'sha256:'||encode(sha256(convert_to(coalesce(string_agg(
      mic||':'||schedule_source_id||':'||schedule_source_version||':'||
      schedule_source_content_hash||':'||analytics.fv_cq_forward_date_text_v1(entry_date)||':'||
      analytics.fv_cq_forward_utc_text_v1(scheduled_open)||':'||
      analytics.fv_cq_forward_utc_text_v1(scheduled_close)||':'||
      lower(early_close::TEXT)||':'||schedule_content_hash||':'||state,
      '|' ORDER BY mic),''),'UTF8')),'hex') INTO computed_entry_session_hash
      FROM analytics.fv_cq_forward_planned_entry_v1
      WHERE enrollment_id=parent.enrollment_id;
    SELECT * INTO seal FROM analytics.fv_cq_forward_enrollment_seal_v1
      WHERE enrollment_id=parent.enrollment_id;
    SELECT 'sha256:'||encode(sha256(convert_to(coalesce(string_agg(
      member_ordinal::TEXT||':'||security_id::TEXT||':'||terminal_state||':'||row_content_hash,
      '|' ORDER BY member_ordinal),''),'UTF8')),'hex') INTO computed_member_hash
      FROM analytics.fv_cq_forward_member_v1 WHERE enrollment_id=parent.enrollment_id;
    SELECT 'sha256:'||encode(sha256(convert_to(coalesce(string_agg(
      security_id::TEXT||':'||analytics.fv_cq_forward_decimal_text_v1(predictor_score)||':'||
      predictor_rank::TEXT||':'||predictor_group,
      '|' ORDER BY predictor_rank),''),'UTF8')),'hex') INTO computed_rank_hash
      FROM analytics.fv_cq_forward_member_v1 WHERE enrollment_id=parent.enrollment_id
        AND terminal_state='USABLE_VALID';
    SELECT 'sha256:'||encode(sha256(convert_to(coalesce(string_agg(
      member_ordinal::TEXT||':'||reason_ordinal::TEXT||':'||reason_code,
      '|' ORDER BY member_ordinal,reason_ordinal),''),'UTF8')),'hex') INTO computed_reason_hash
      FROM analytics.fv_cq_forward_member_reason_v1 WHERE enrollment_id=parent.enrollment_id;
    SELECT 'sha256:'||encode(sha256(convert_to(coalesce(string_agg(
      member_ordinal::TEXT||':'||evidence_ordinal::TEXT||':'||operand_code||':'||
      canonical_field_code||':'||provenance_kind||':'||
      analytics.fv_cq_forward_decimal_text_v1(numeric_value)||':'||
      coalesce(selection_request_id::TEXT,'')||':'||coalesce(selection_result_hash,'')||':'||
      coalesce(canonical_evidence_id::TEXT,'')||':'||coalesce(normalized_parent_id::TEXT,'')||':'||
      raw_manifest_id::TEXT||':'||provider_code||':'||
      provider_schema_version||':'||source_record_id||':'||source_revision::TEXT||':'||
      coalesce(analytics.fv_cq_forward_date_text_v1(parent_period_start),'')||':'||
      analytics.fv_cq_forward_date_text_v1(parent_period_end)||':'||
      parent_source_content_hash||':'||parent_normalized_record_hash||
      ':'||analytics.fv_cq_forward_utc_text_v1(parent_effective_at)||':'||
      analytics.fv_cq_forward_utc_text_v1(parent_available_at)||':'||
      analytics.fv_cq_forward_utc_text_v1(parent_ingested_at)||':'||currency||':'||unit,
      '|' ORDER BY member_ordinal,evidence_ordinal),''),'UTF8')),'hex') INTO computed_evidence_hash
      FROM analytics.fv_cq_forward_member_evidence_v1 WHERE enrollment_id=parent.enrollment_id;
    SELECT 'sha256:'||encode(sha256(convert_to(coalesce(string_agg(
      horizon_sessions::TEXT||':'||horizon_role||':'||protocol_content_hash||':'||schedule_content_hash,
      '|' ORDER BY horizon_sessions),''),'UTF8')),'hex') INTO computed_maturity_hash
      FROM analytics.fv_cq_forward_maturity_v1 WHERE enrollment_id=parent.enrollment_id;
    computed_enrollment_hash := 'sha256:'||encode(sha256(convert_to(
      parent.enrollment_id::TEXT||'|'||
      analytics.fv_cq_forward_utc_text_v1(parent.decision_cutoff)||'|'||
      analytics.fv_cq_forward_utc_text_v1(parent.evidence_cutoff)||'|'||
      analytics.fv_cq_forward_utc_text_v1(parent.sealed_at)||'|'||
      parent.population_content_hash||'|'||
      parent.evidence_manifest_content_hash||'|'||parent.predictor_contract_content_hash||'|'||
      parent.outcome_protocol_content_hash||'|'||parent.stage7_acceptance_content_hash||'|'||
      parent.stage8a_content_hash||'|'||computed_decision_session_hash||'|'||
      computed_entry_session_hash||'|'||
      computed_member_hash||'|'||computed_rank_hash||'|'||
      computed_reason_hash||'|'||computed_evidence_hash||'|'||computed_maturity_hash,'UTF8')),'hex');
    computed_seal_content_hash := 'sha256:'||encode(sha256(convert_to(
      computed_enrollment_hash||'|'||computed_decision_session_hash||'|'||
      computed_entry_session_hash||'|'||
      computed_member_hash||'|'||computed_rank_hash||'|'||
      computed_reason_hash||'|'||computed_evidence_hash||'|'||computed_maturity_hash,'UTF8')),'hex');
    SELECT count(*) INTO bad_schedule_count FROM analytics.fv_cq_forward_maturity_v1 maturity
      WHERE maturity.enrollment_id=parent.enrollment_id AND (
        maturity.protocol_content_hash IS DISTINCT FROM parent.outcome_protocol_content_hash OR
        maturity.schedule_content_hash IS DISTINCT FROM 'sha256:'||encode(sha256(convert_to(
          parent.enrollment_id::TEXT||'|'||maturity.horizon_sessions::TEXT||'|'||
          parent.outcome_protocol_content_hash||'|'||computed_entry_session_hash,
          'UTF8')),'hex'));
    SELECT count(*) INTO bad_row_hash_count FROM analytics.fv_cq_forward_member_v1 member
      WHERE member.enrollment_id=parent.enrollment_id AND member.row_content_hash IS DISTINCT FROM
        'sha256:'||encode(sha256(convert_to(
          member.member_ordinal::TEXT||'|'||member.security_id::TEXT||'|'||member.company_id::TEXT||'|'||
          member.instrument_id::TEXT||'|'||member.share_class_id::TEXT||'|'||member.listing_id::TEXT||'|'||
          member.ticker_assignment_id::TEXT||'|'||member.listing_mic||'|'||member.terminal_state||'|'||
          coalesce(analytics.fv_cq_forward_decimal_text_v1(member.predictor_score),'')||'|'||
          coalesce(member.predictor_rank::TEXT,'')||'|'||
          coalesce(member.predictor_group,'')||'|'||coalesce(member.evidence_content_hash,'')||'|'||
          coalesce(member.source_content_hash,'')||'|'||
          coalesce(member.producer_contract_content_hash,'')||'|'||
          coalesce(member.producer_output_content_hash,'')||'|'||
          coalesce(analytics.fv_cq_forward_utc_text_v1(member.evidence_available_at),'')||'|'||
          coalesce(analytics.fv_cq_forward_utc_text_v1(member.evidence_ingested_at),'')||'|'||
          (SELECT 'sha256:'||encode(sha256(convert_to(coalesce(string_agg(
            evidence.evidence_ordinal::TEXT||':'||evidence.operand_code||':'||
            evidence.canonical_field_code||':'||evidence.provenance_kind||':'||
            analytics.fv_cq_forward_decimal_text_v1(evidence.numeric_value)||':'||
            coalesce(evidence.selection_request_id::TEXT,'')||':'||
            coalesce(evidence.selection_result_hash,'')||':'||
            coalesce(evidence.canonical_evidence_id::TEXT,'')||':'||
            coalesce(evidence.normalized_parent_id::TEXT,'')||':'||evidence.raw_manifest_id::TEXT||':'||
            evidence.provider_code||':'||evidence.provider_schema_version||':'||
            evidence.source_record_id||':'||evidence.source_revision::TEXT||':'||
            coalesce(analytics.fv_cq_forward_date_text_v1(evidence.parent_period_start),'')||':'||
            analytics.fv_cq_forward_date_text_v1(evidence.parent_period_end)||':'||
            evidence.parent_source_content_hash||':'||evidence.parent_normalized_record_hash||':'||
            analytics.fv_cq_forward_utc_text_v1(evidence.parent_effective_at)||':'||
            analytics.fv_cq_forward_utc_text_v1(evidence.parent_available_at)||':'||
            analytics.fv_cq_forward_utc_text_v1(evidence.parent_ingested_at)||':'||
            evidence.currency||':'||evidence.unit,
            '|' ORDER BY evidence.evidence_ordinal),''),'UTF8')),'hex')
           FROM analytics.fv_cq_forward_member_evidence_v1 evidence
           WHERE evidence.enrollment_id=member.enrollment_id AND evidence.member_ordinal=member.member_ordinal)||'|'||
          (SELECT 'sha256:'||encode(sha256(convert_to(coalesce(string_agg(reason.reason_code,
            '|' ORDER BY reason.reason_ordinal),''),'UTF8')),'hex')
           FROM analytics.fv_cq_forward_member_reason_v1 reason
           WHERE reason.enrollment_id=member.enrollment_id AND reason.member_ordinal=member.member_ordinal),
          'UTF8')),'hex');
    SELECT count(*) INTO bad_member_evidence_hash_count
      FROM analytics.fv_cq_forward_member_v1 member
      WHERE member.enrollment_id=parent.enrollment_id AND member.terminal_state='USABLE_VALID'
        AND (member.evidence_content_hash IS DISTINCT FROM (SELECT 'sha256:'||encode(sha256(convert_to(
          coalesce(string_agg(evidence.provenance_kind||':'||evidence.raw_manifest_id::TEXT||':'||
            coalesce(evidence.canonical_evidence_id::TEXT,'')||':'||
            coalesce(evidence.normalized_parent_id::TEXT,'')||':'||
            evidence.parent_normalized_record_hash,'|' ORDER BY evidence.evidence_ordinal),''),
          'UTF8')),'hex') FROM analytics.fv_cq_forward_member_evidence_v1 evidence
          WHERE evidence.enrollment_id=member.enrollment_id
            AND evidence.member_ordinal=member.member_ordinal)
        OR member.source_content_hash IS DISTINCT FROM (SELECT 'sha256:'||encode(sha256(convert_to(
          coalesce(string_agg(evidence.parent_source_content_hash,
            '|' ORDER BY evidence.evidence_ordinal),''),'UTF8')),'hex')
          FROM analytics.fv_cq_forward_member_evidence_v1 evidence
          WHERE evidence.enrollment_id=member.enrollment_id
            AND evidence.member_ordinal=member.member_ordinal));
    SELECT count(*) INTO bad_producer_output_count
      FROM analytics.fv_cq_forward_member_v1 member
      WHERE member.enrollment_id=parent.enrollment_id AND member.terminal_state='USABLE_VALID'
        AND (member.predictor_score IS DISTINCT FROM
             analytics.fv_cq_forward_expected_score_v1(
               member.enrollment_id,member.member_ordinal)
          OR member.producer_output_content_hash IS DISTINCT FROM 'sha256:'||encode(sha256(convert_to(
            member.producer_contract_content_hash||'|'||
            analytics.fv_cq_forward_decimal_text_v1(member.predictor_score)||'|'||
            member.evidence_content_hash||'|'||member.source_content_hash,'UTF8')),'hex'));
    SELECT count(*) INTO bad_freshness_count FROM (
      SELECT evidence.enrollment_id,evidence.member_ordinal,evidence.operand_code,
        evidence.parent_period_end,
        lag(evidence.parent_period_end) OVER (
          PARTITION BY evidence.enrollment_id,evidence.member_ordinal,evidence.operand_code
          ORDER BY evidence.parent_period_end DESC) AS prior_period_end
      FROM analytics.fv_cq_forward_member_evidence_v1 evidence
      WHERE evidence.enrollment_id=parent.enrollment_id
    ) periods WHERE parent_period_end>(parent.decision_cutoff AT TIME ZONE 'UTC')::DATE
      OR (prior_period_end IS NOT NULL
        AND (prior_period_end-parent_period_end<60 OR prior_period_end-parent_period_end>120));
    WITH role_periods AS (
      SELECT member_ordinal,operand_code,
        (array_agg(parent_period_end ORDER BY parent_period_end DESC))[1:4] AS periods
      FROM analytics.fv_cq_forward_member_evidence_v1
      WHERE enrollment_id=parent.enrollment_id AND operand_code IN
        ('REVENUE','OPERATING_INCOME','OPERATING_CASH_FLOW','CAPITAL_EXPENDITURE',
         'INCOME_TAX','PRETAX_INCOME')
      GROUP BY member_ordinal,operand_code
    ), compared AS (
      SELECT member_ordinal,count(DISTINCT periods)=1 AS aligned
      FROM role_periods GROUP BY member_ordinal
    ) SELECT count(*) INTO bad_period_alignment_count FROM compared WHERE NOT aligned;
    WITH flow_bounds AS (
      SELECT member_ordinal,periods[1] AS last_end,periods[4] AS first_end,
        periods[4]-(periods[1]-periods[2]) AS inferred_start
      FROM (SELECT member_ordinal,
          array_agg(parent_period_end ORDER BY parent_period_end DESC) AS periods
        FROM analytics.fv_cq_forward_member_evidence_v1
        WHERE enrollment_id=parent.enrollment_id AND operand_code='INCOME_TAX'
        GROUP BY member_ordinal) ordered
    ) SELECT count(*) INTO bad_balance_boundary_count
      FROM analytics.fv_cq_forward_member_v1 member
      JOIN flow_bounds bounds USING (member_ordinal)
      WHERE member.enrollment_id=parent.enrollment_id
        AND member.terminal_state='USABLE_VALID' AND (
          EXISTS (SELECT 1 FROM analytics.fv_cq_forward_member_evidence_v1 evidence
            WHERE evidence.enrollment_id=member.enrollment_id
              AND evidence.member_ordinal=member.member_ordinal
              AND evidence.operand_code IN
                ('STOCKHOLDERS_EQUITY','TOTAL_DEBT','CASH_AND_EQUIVALENTS')
              AND evidence.parent_period_end>bounds.last_end)
          OR EXISTS (SELECT 1 FROM (VALUES ('STOCKHOLDERS_EQUITY'),('TOTAL_DEBT'),
              ('CASH_AND_EQUIVALENTS')) role(role_code)
            CROSS JOIN LATERAL (VALUES (bounds.inferred_start),(bounds.last_end)) boundary(on_date)
            WHERE NOT EXISTS (SELECT 1 FROM analytics.fv_cq_forward_member_evidence_v1 evidence
              WHERE evidence.enrollment_id=member.enrollment_id
                AND evidence.member_ordinal=member.member_ordinal
                AND evidence.operand_code=role.role_code
                AND evidence.parent_period_end<=boundary.on_date
                AND boundary.on_date-evidence.parent_period_end<=120)));
    IF EXISTS (SELECT 1 FROM analytics.fv_cq_forward_member_v1 member
      WHERE member.enrollment_id=parent.enrollment_id AND member.terminal_state='USABLE_VALID'
        AND ((SELECT max(evidence.parent_period_end)
          FROM analytics.fv_cq_forward_member_evidence_v1 evidence
          WHERE evidence.enrollment_id=member.enrollment_id
            AND evidence.member_ordinal=member.member_ordinal)
          < (parent.decision_cutoff AT TIME ZONE 'UTC')::DATE-150
        OR EXISTS (SELECT 1 FROM (VALUES ('STOCKHOLDERS_EQUITY'),('TOTAL_DEBT'),
          ('CASH_AND_EQUIVALENTS')) balance(role_code)
          WHERE (SELECT max(evidence.parent_period_end)
            FROM analytics.fv_cq_forward_member_evidence_v1 evidence
            WHERE evidence.enrollment_id=member.enrollment_id
              AND evidence.member_ordinal=member.member_ordinal
              AND evidence.operand_code=balance.role_code)
            < (parent.decision_cutoff AT TIME ZONE 'UTC')::DATE-120))) THEN
      bad_freshness_count := bad_freshness_count + 1;
    END IF;
    SELECT count(*) INTO bad_chronology FROM analytics.fv_cq_forward_member_v1
      WHERE enrollment_id=parent.enrollment_id AND terminal_state='USABLE_VALID'
        AND (evidence_available_at > parent.evidence_cutoff
          OR evidence_ingested_at > parent.evidence_cutoff
          OR evidence_available_at <> (SELECT max(evidence.parent_available_at)
             FROM analytics.fv_cq_forward_member_evidence_v1 evidence
             WHERE evidence.enrollment_id=parent.enrollment_id
               AND evidence.member_ordinal=fv_cq_forward_member_v1.member_ordinal)
          OR evidence_ingested_at <> (SELECT max(evidence.parent_ingested_at)
             FROM analytics.fv_cq_forward_member_evidence_v1 evidence
             WHERE evidence.enrollment_id=parent.enrollment_id
               AND evidence.member_ordinal=fv_cq_forward_member_v1.member_ordinal));
    SELECT count(*) INTO bad_rank_count FROM (
      SELECT predictor_rank, count(*) AS n
      FROM analytics.fv_cq_forward_member_v1
      WHERE enrollment_id=parent.enrollment_id AND terminal_state='USABLE_VALID'
      GROUP BY predictor_rank HAVING count(*) <> 1
    ) duplicate_ranks;
    SELECT count(*) INTO bad_decision_session_count
      FROM analytics.fv_cq_forward_decision_session_v1 bound
      LEFT JOIN analytics.evidence_completed_session_v1 session
        ON session.id=bound.completed_session_id
      LEFT JOIN analytics.evidence_trading_calendar_v1 calendar
        ON calendar.calendar_id=bound.calendar_id
       AND calendar.calendar_version=bound.calendar_version
      WHERE bound.enrollment_id=parent.enrollment_id AND NOT (
        session.mic=bound.mic
        AND session.calendar_id=bound.calendar_id
        AND session.calendar_version=bound.calendar_version
        AND session.session_date=bound.session_date
        AND session.scheduled_open=bound.scheduled_open
        AND session.scheduled_close=bound.scheduled_close
        AND session.early_close=bound.early_close
        AND session.completed_at=bound.completed_at
        AND session.recorded_at=bound.recorded_at
        AND bound.completed_at<=bound.recorded_at
        AND session.session_content_hash=bound.session_content_hash
        AND calendar.mic=bound.mic
        AND calendar.calendar_content_hash=bound.calendar_content_hash
        AND bound.session_date<=(parent.decision_cutoff AT TIME ZONE 'UTC')::DATE
        AND bound.scheduled_close<=parent.decision_cutoff
        AND bound.completed_at<=parent.decision_cutoff
        AND bound.recorded_at<=parent.evidence_cutoff
        AND NOT EXISTS (SELECT 1 FROM analytics.evidence_completed_session_v1 later
          WHERE later.calendar_id=bound.calendar_id
            AND later.calendar_version=bound.calendar_version
            AND later.session_date>bound.session_date
            AND later.completed_at<=parent.decision_cutoff)
        AND bound.row_content_hash IS NOT DISTINCT FROM 'sha256:'||encode(sha256(convert_to(
          bound.mic||':'||bound.completed_session_id::TEXT||':'||bound.calendar_id||':'||
          bound.calendar_version||':'||analytics.fv_cq_forward_date_text_v1(bound.session_date)||':'||
          analytics.fv_cq_forward_utc_text_v1(bound.scheduled_open)||':'||
          analytics.fv_cq_forward_utc_text_v1(bound.scheduled_close)||':'||
          lower(bound.early_close::TEXT)||':'||
          analytics.fv_cq_forward_utc_text_v1(bound.completed_at)||':'||
          analytics.fv_cq_forward_utc_text_v1(bound.recorded_at)||':'||
          bound.session_content_hash||':'||bound.calendar_content_hash,'UTF8')),'hex'));
    SELECT count(*) INTO bad_entry_session_count
      FROM analytics.fv_cq_forward_planned_entry_v1 entry
      WHERE entry.enrollment_id=parent.enrollment_id AND NOT (
        entry.entry_date>(parent.decision_cutoff AT TIME ZONE 'UTC')::DATE
        AND entry.scheduled_open>parent.sealed_at
        AND entry.scheduled_open<entry.scheduled_close
        AND entry.state='SCHEDULED_NOT_COMPLETED'
        AND entry.row_content_hash IS NOT DISTINCT FROM 'sha256:'||encode(sha256(convert_to(
          entry.mic||':'||entry.schedule_source_id||':'||entry.schedule_source_version||':'||
          entry.schedule_source_content_hash||':'||
          analytics.fv_cq_forward_date_text_v1(entry.entry_date)||':'||
          analytics.fv_cq_forward_utc_text_v1(entry.scheduled_open)||':'||
          analytics.fv_cq_forward_utc_text_v1(entry.scheduled_close)||':'||
          lower(entry.early_close::TEXT)||':'||entry.schedule_content_hash||':'||entry.state,
          'UTF8')),'hex'));
    SELECT count(*) INTO bad_identity_count
      FROM analytics.fv_cq_forward_member_v1 member
      JOIN analytics.evidence_instrument_identity_v1 instrument
        ON instrument.instrument_id=member.instrument_id
      JOIN analytics.evidence_share_class_identity_v1 share_class
        ON share_class.share_class_id=member.share_class_id
      JOIN analytics.evidence_listing_identity_v1 listing
        ON listing.listing_id=member.listing_id
      JOIN analytics.evidence_ticker_assignment_v1 ticker
        ON ticker.ticker_assignment_id=member.ticker_assignment_id
      JOIN analytics.fv_cq_forward_decision_session_v1 bound
        ON bound.enrollment_id=member.enrollment_id AND bound.mic=member.listing_mic
      WHERE member.enrollment_id=parent.enrollment_id AND NOT (
        instrument.company_id=member.company_id
        AND share_class.instrument_id=member.instrument_id
        AND listing.share_class_id=member.share_class_id
        AND listing.security_id=member.security_id
        AND listing.mic=member.listing_mic
        AND ticker.listing_id=member.listing_id
        AND ticker.valid_from <= bound.session_date
        AND (ticker.valid_to IS NULL OR ticker.valid_to > bound.session_date));
    SELECT count(*) INTO bad_evidence_count
      FROM analytics.fv_cq_forward_member_evidence_v1 link
      JOIN analytics.fv_cq_forward_member_v1 member USING (enrollment_id,member_ordinal)
      WHERE link.enrollment_id=parent.enrollment_id AND NOT (
       (link.provenance_kind='V22_SELECTED_EVIDENCE' AND EXISTS (
        SELECT 1 FROM analytics.evidence_selection_request_v1 request
        JOIN analytics.evidence_selection_result_v1 result
          ON result.request_id=request.request_id
        JOIN analytics.canonical_evidence_v1 evidence
          ON evidence.evidence_id=result.selected_evidence_id
        JOIN analytics.evidence_selector_policy_v1 policy ON policy.id=request.policy_id
        WHERE request.request_id=link.selection_request_id
          AND member.terminal_state='USABLE_VALID' AND result.state='VALID'
          AND result.selected_evidence_id=link.canonical_evidence_id
          AND result.result_content_hash=link.selection_result_hash
          AND policy.domain='FUNDAMENTAL' AND policy.field_code=link.canonical_field_code
          AND policy.domain_constraints->>'metricCode'=link.canonical_field_code
          AND policy.domain_constraints->>'periodEnd'=
              analytics.fv_cq_forward_date_text_v1(link.parent_period_end)
          AND policy.domain_constraints->>'unit'=link.unit
          AND policy.domain_constraints->>'currency'=link.currency
          AND evidence.state='VALID' AND evidence.domain='FUNDAMENTAL'
          AND evidence.canonical_data->>'metricCode'=link.canonical_field_code
          AND (evidence.canonical_data->>'numericValue')::NUMERIC=link.numeric_value
          AND evidence.canonical_data->>'periodEnd'=
              analytics.fv_cq_forward_date_text_v1(link.parent_period_end)
          AND (evidence.canonical_data->>'periodStart')::DATE
              IS NOT DISTINCT FROM link.parent_period_start
          AND request.security_id=member.security_id
          AND request.company_id=member.company_id
          AND request.instrument_id=member.instrument_id
          AND request.share_class_id=member.share_class_id
          AND request.listing_id=member.listing_id
          AND request.ticker_assignment_id=member.ticker_assignment_id
          AND request.completed_session_id=(SELECT bound.completed_session_id
              FROM analytics.fv_cq_forward_decision_session_v1 bound
              WHERE bound.enrollment_id=member.enrollment_id
                AND bound.mic=member.listing_mic)
          AND request.decision_cutoff=parent.decision_cutoff
          AND request.sealed_ingestion_cutoff<=parent.evidence_cutoff
          AND evidence.security_id=member.security_id
          AND evidence.company_id=member.company_id
          AND evidence.instrument_id=member.instrument_id
          AND evidence.share_class_id=member.share_class_id
          AND evidence.listing_id=member.listing_id
          AND evidence.ticker_assignment_id=member.ticker_assignment_id
          AND evidence.source_content_hash=link.parent_source_content_hash
          AND evidence.normalized_record_hash=link.parent_normalized_record_hash
          AND evidence.provider_code=link.provider_code
          AND evidence.provider_schema_version=link.provider_schema_version
          AND evidence.source_record_id=link.source_record_id
          AND evidence.source_revision=link.source_revision
          AND evidence.effective_at=link.parent_effective_at
          AND evidence.available_at=link.parent_available_at
          AND evidence.ingested_at=link.parent_ingested_at
          AND evidence.currency=link.currency
          AND evidence.canonical_data->>'unit'=link.unit
          AND evidence.raw_manifest_id=link.raw_manifest_id
          AND evidence.available_at <= parent.evidence_cutoff
          AND evidence.ingested_at <= parent.evidence_cutoff))
       OR (link.provenance_kind='V24_PROVIDER_NORMALIZED_PARENT' AND EXISTS (
          SELECT 1 FROM analytics.fv_cq_forward_normalized_parent_v1 normalized
          JOIN analytics.evidence_raw_manifest_v1 raw ON raw.id=normalized.raw_manifest_id
          WHERE normalized.normalized_parent_id=link.normalized_parent_id
            AND normalized.security_id=member.security_id
            AND normalized.company_id=member.company_id
            AND normalized.instrument_id=member.instrument_id
            AND normalized.share_class_id=member.share_class_id
            AND normalized.listing_id=member.listing_id
            AND normalized.ticker_assignment_id=member.ticker_assignment_id
            AND normalized.raw_manifest_id=link.raw_manifest_id
            AND normalized.canonical_field_code=link.canonical_field_code
            AND normalized.numeric_value=link.numeric_value
            AND normalized.period_start IS NOT DISTINCT FROM link.parent_period_start
            AND normalized.period_end=link.parent_period_end
            AND normalized.source_content_hash=link.parent_source_content_hash
            AND normalized.normalized_record_hash=link.parent_normalized_record_hash
            AND normalized.provider_code=link.provider_code
            AND normalized.provider_schema_version=link.provider_schema_version
            AND normalized.source_record_id=link.source_record_id
            AND normalized.source_revision=link.source_revision
            AND normalized.effective_at=link.parent_effective_at
            AND normalized.available_at=link.parent_available_at
            AND normalized.ingested_at=link.parent_ingested_at
            AND normalized.currency=link.currency AND normalized.unit=link.unit
            AND raw.provider_code=link.provider_code
            AND raw.provider_schema_version=link.provider_schema_version
            AND raw.source_record_id=link.source_record_id
            AND raw.source_revision=link.source_revision
            AND raw.source_content_hash=link.parent_source_content_hash
            AND raw.effective_at=link.parent_effective_at
            AND raw.available_at=link.parent_available_at
            AND raw.ingested_at=link.parent_ingested_at
            AND raw.available_at<=parent.evidence_cutoff
            AND raw.ingested_at<=parent.evidence_cutoff)));
    SELECT count(*) INTO bad_group_count
      FROM analytics.fv_cq_forward_member_v1 member
      WHERE member.enrollment_id=parent.enrollment_id
        AND member.terminal_state='USABLE_VALID' AND member.predictor_group <>
          CASE WHEN member.predictor_rank <= floor(usable_count / 5.0) THEN 'HIGH'
               WHEN member.predictor_rank > usable_count-floor(usable_count / 5.0) THEN 'LOW'
               ELSE 'MIDDLE' END;
    SELECT count(*) INTO bad_score_order_count FROM (
      SELECT predictor_score,security_id,
        lag(predictor_score) OVER (ORDER BY predictor_rank) AS prior_score,
        lag(security_id) OVER (ORDER BY predictor_rank) AS prior_security
      FROM analytics.fv_cq_forward_member_v1
      WHERE enrollment_id=parent.enrollment_id AND terminal_state='USABLE_VALID'
    ) ranked WHERE prior_score < predictor_score
       OR (prior_score=predictor_score AND prior_security::TEXT > security_id::TEXT);
    IF member_count <> parent.expected_member_count
       OR usable_count <> parent.expected_usable_count
       OR reason_count <> parent.expected_reason_count
       OR maturity_count <> 3 OR seal.enrollment_id IS NULL
       OR decision_session_count<>parent.expected_decision_session_count
       OR parent.decision_session_set_hash IS DISTINCT FROM computed_decision_session_hash
       OR seal.decision_session_set_hash IS DISTINCT FROM computed_decision_session_hash
       OR bad_decision_session_count<>0
       OR entry_session_count<>parent.expected_entry_session_count
       OR parent.entry_session_set_hash IS DISTINCT FROM computed_entry_session_hash
       OR seal.entry_session_set_hash IS DISTINCT FROM computed_entry_session_hash
       OR bad_entry_session_count<>0
       OR EXISTS (SELECT mic FROM analytics.fv_cq_forward_decision_session_v1
            WHERE enrollment_id=parent.enrollment_id
          EXCEPT SELECT DISTINCT listing_mic FROM analytics.fv_cq_forward_member_v1
            WHERE enrollment_id=parent.enrollment_id)
       OR EXISTS (SELECT DISTINCT listing_mic FROM analytics.fv_cq_forward_member_v1
            WHERE enrollment_id=parent.enrollment_id
          EXCEPT SELECT mic FROM analytics.fv_cq_forward_decision_session_v1
            WHERE enrollment_id=parent.enrollment_id)
       OR (SELECT count(*) FROM analytics.fv_cq_forward_member_v1
            WHERE enrollment_id=parent.enrollment_id AND listing_mic='XNYS')<>122
       OR (SELECT count(*) FROM analytics.fv_cq_forward_member_v1
            WHERE enrollment_id=parent.enrollment_id AND listing_mic='XNAS')<>69
       OR EXISTS (SELECT mic FROM analytics.fv_cq_forward_planned_entry_v1
            WHERE enrollment_id=parent.enrollment_id
          EXCEPT SELECT DISTINCT listing_mic FROM analytics.fv_cq_forward_member_v1
            WHERE enrollment_id=parent.enrollment_id)
       OR EXISTS (SELECT DISTINCT listing_mic FROM analytics.fv_cq_forward_member_v1
            WHERE enrollment_id=parent.enrollment_id
          EXCEPT SELECT mic FROM analytics.fv_cq_forward_planned_entry_v1
            WHERE enrollment_id=parent.enrollment_id)
       OR (SELECT count(DISTINCT session_date)
            FROM analytics.fv_cq_forward_decision_session_v1
            WHERE enrollment_id=parent.enrollment_id)<>1
       OR (SELECT count(DISTINCT entry_date)
            FROM analytics.fv_cq_forward_planned_entry_v1
            WHERE enrollment_id=parent.enrollment_id)<>1
       OR seal.member_set_hash IS DISTINCT FROM computed_member_hash
       OR seal.ranked_group_set_hash IS DISTINCT FROM computed_rank_hash
       OR seal.reason_set_hash IS DISTINCT FROM computed_reason_hash
       OR seal.evidence_set_hash IS DISTINCT FROM computed_evidence_hash
       OR seal.maturity_set_hash IS DISTINCT FROM computed_maturity_hash
       OR parent.enrollment_content_hash IS DISTINCT FROM computed_enrollment_hash
       OR seal.seal_content_hash IS DISTINCT FROM computed_seal_content_hash
       OR bad_row_hash_count<>0 OR bad_schedule_count<>0
       OR bad_member_evidence_hash_count<>0
       OR bad_producer_output_count<>0
       OR bad_freshness_count<>0
       OR bad_period_alignment_count<>0 OR bad_balance_boundary_count<>0
       OR seal.sealed_at<>parent.sealed_at
       OR bad_chronology <> 0 OR bad_rank_count <> 0
       OR bad_identity_count <> 0 OR bad_evidence_count <> 0
       OR bad_group_count <> 0 OR bad_score_order_count <> 0
       OR EXISTS (SELECT 1 FROM analytics.fv_cq_forward_member_v1 member
          WHERE member.enrollment_id=parent.enrollment_id AND
          (SELECT count(*) FROM analytics.fv_cq_forward_member_evidence_v1 evidence
           WHERE evidence.enrollment_id=member.enrollment_id
             AND evidence.member_ordinal=member.member_ordinal)
          <> member.expected_evidence_count OR EXISTS (
            SELECT 1 FROM analytics.fv_cq_forward_member_evidence_v1 evidence
            WHERE evidence.enrollment_id=member.enrollment_id
              AND evidence.member_ordinal=member.member_ordinal
            GROUP BY evidence.enrollment_id,evidence.member_ordinal
            HAVING min(evidence.evidence_ordinal)<>1
              OR max(evidence.evidence_ordinal)<>member.expected_evidence_count))
       OR EXISTS (SELECT 1 FROM analytics.fv_cq_forward_member_v1 member
          WHERE member.enrollment_id=parent.enrollment_id AND member.terminal_state='USABLE_VALID'
            AND (member.expected_evidence_count<>(SELECT sum(required_count)
                 FROM analytics.fv_cq_forward_parent_role_v1)
              OR EXISTS (SELECT 1 FROM analytics.fv_cq_forward_parent_role_v1 required
              WHERE (SELECT count(*) FROM analytics.fv_cq_forward_member_evidence_v1 evidence
                WHERE evidence.enrollment_id=member.enrollment_id
                  AND evidence.member_ordinal=member.member_ordinal
                  AND evidence.operand_code=required.operand_code)<>required.required_count)))
       OR EXISTS (SELECT 1 FROM analytics.fv_cq_forward_member_v1 member
          WHERE member.enrollment_id=parent.enrollment_id AND
          (SELECT count(*) FROM analytics.fv_cq_forward_member_reason_v1 reason
           WHERE reason.enrollment_id=member.enrollment_id
             AND reason.member_ordinal=member.member_ordinal)
          <> member.expected_reason_count OR EXISTS (
            SELECT 1 FROM analytics.fv_cq_forward_member_reason_v1 reason
            WHERE reason.enrollment_id=member.enrollment_id
              AND reason.member_ordinal=member.member_ordinal
            GROUP BY reason.enrollment_id,reason.member_ordinal
            HAVING min(reason.reason_ordinal)<>1
              OR max(reason.reason_ordinal)<>member.expected_reason_count))
       OR EXISTS (SELECT 1 FROM analytics.fv_cq_forward_member_v1 member
          WHERE member.enrollment_id=parent.enrollment_id AND member.member_ordinal NOT BETWEEN 1 AND parent.expected_member_count)
       OR (usable_count > 0 AND NOT EXISTS (
          SELECT 1 FROM analytics.fv_cq_forward_member_v1
          WHERE enrollment_id=parent.enrollment_id AND terminal_state='USABLE_VALID'
          GROUP BY enrollment_id HAVING min(predictor_rank)=1
             AND max(predictor_rank)=usable_count)) THEN
      RAISE EXCEPTION 'FV_CQ_FORWARD_ENROLLMENT_INCOMPLETE_OR_INVALID';
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER fv_cq_forward_enrollment_complete_v1
AFTER INSERT ON analytics.fv_cq_forward_enrollment_v1 DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION analytics.validate_fv_cq_forward_enrollment_v1();

-- Every aggregate-contributing child queues the same deferred validator. The
-- seal-row MVCC identity prevents O(child-count) full replays in the creating
-- transaction while forcing a fresh validation in every later transaction.
CREATE CONSTRAINT TRIGGER fv_cq_forward_decision_session_complete_v1
AFTER INSERT ON analytics.fv_cq_forward_decision_session_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION analytics.validate_fv_cq_forward_enrollment_v1();
CREATE CONSTRAINT TRIGGER fv_cq_forward_planned_entry_complete_v1
AFTER INSERT ON analytics.fv_cq_forward_planned_entry_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION analytics.validate_fv_cq_forward_enrollment_v1();
CREATE CONSTRAINT TRIGGER fv_cq_forward_member_complete_v1
AFTER INSERT ON analytics.fv_cq_forward_member_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION analytics.validate_fv_cq_forward_enrollment_v1();
CREATE CONSTRAINT TRIGGER fv_cq_forward_evidence_complete_v1
AFTER INSERT ON analytics.fv_cq_forward_member_evidence_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION analytics.validate_fv_cq_forward_enrollment_v1();
CREATE CONSTRAINT TRIGGER fv_cq_forward_reason_complete_v1
AFTER INSERT ON analytics.fv_cq_forward_member_reason_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION analytics.validate_fv_cq_forward_enrollment_v1();
CREATE CONSTRAINT TRIGGER fv_cq_forward_maturity_complete_v1
AFTER INSERT ON analytics.fv_cq_forward_maturity_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION analytics.validate_fv_cq_forward_enrollment_v1();
CREATE CONSTRAINT TRIGGER fv_cq_forward_seal_complete_v1
AFTER INSERT ON analytics.fv_cq_forward_enrollment_seal_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION analytics.validate_fv_cq_forward_enrollment_v1();

CREATE FUNCTION analytics.reject_fv_cq_forward_mutation_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'FV_CQ_FORWARD_APPEND_ONLY';
END $$;

CREATE FUNCTION analytics.set_fv_cq_forward_recorded_at_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$ BEGIN
  NEW.recorded_at := date_trunc('second',transaction_timestamp());
  RETURN NEW;
END $$;

CREATE TRIGGER fv_cq_forward_server_recorded_at_v1 BEFORE INSERT
ON analytics.fv_cq_forward_enrollment_v1 FOR EACH ROW
EXECUTE FUNCTION analytics.set_fv_cq_forward_recorded_at_v1();

CREATE FUNCTION analytics.reject_fv_cq_forward_late_child_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$ BEGIN
  IF EXISTS (SELECT 1 FROM analytics.fv_cq_forward_enrollment_seal_v1
    WHERE enrollment_id=NEW.enrollment_id) THEN
    RAISE EXCEPTION 'FV_CQ_FORWARD_ALREADY_SEALED';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER fv_cq_forward_member_no_late_insert_v1 BEFORE INSERT
ON analytics.fv_cq_forward_member_v1 FOR EACH ROW
EXECUTE FUNCTION analytics.reject_fv_cq_forward_late_child_v1();
CREATE TRIGGER fv_cq_forward_decision_session_no_late_insert_v1 BEFORE INSERT
ON analytics.fv_cq_forward_decision_session_v1 FOR EACH ROW
EXECUTE FUNCTION analytics.reject_fv_cq_forward_late_child_v1();
CREATE TRIGGER fv_cq_forward_planned_entry_no_late_insert_v1 BEFORE INSERT
ON analytics.fv_cq_forward_planned_entry_v1 FOR EACH ROW
EXECUTE FUNCTION analytics.reject_fv_cq_forward_late_child_v1();
CREATE TRIGGER fv_cq_forward_evidence_no_late_insert_v1 BEFORE INSERT
ON analytics.fv_cq_forward_member_evidence_v1 FOR EACH ROW
EXECUTE FUNCTION analytics.reject_fv_cq_forward_late_child_v1();
CREATE TRIGGER fv_cq_forward_reason_no_late_insert_v1 BEFORE INSERT
ON analytics.fv_cq_forward_member_reason_v1 FOR EACH ROW
EXECUTE FUNCTION analytics.reject_fv_cq_forward_late_child_v1();
CREATE TRIGGER fv_cq_forward_maturity_no_late_insert_v1 BEFORE INSERT
ON analytics.fv_cq_forward_maturity_v1 FOR EACH ROW
EXECUTE FUNCTION analytics.reject_fv_cq_forward_late_child_v1();

CREATE TRIGGER fv_cq_forward_enrollment_immutable_v1
BEFORE UPDATE OR DELETE OR TRUNCATE ON analytics.fv_cq_forward_enrollment_v1
FOR EACH STATEMENT EXECUTE FUNCTION analytics.reject_fv_cq_forward_mutation_v1();
CREATE TRIGGER fv_cq_forward_member_immutable_v1
BEFORE UPDATE OR DELETE OR TRUNCATE ON analytics.fv_cq_forward_member_v1
FOR EACH STATEMENT EXECUTE FUNCTION analytics.reject_fv_cq_forward_mutation_v1();
CREATE TRIGGER fv_cq_forward_decision_session_immutable_v1
BEFORE UPDATE OR DELETE OR TRUNCATE ON analytics.fv_cq_forward_decision_session_v1
FOR EACH STATEMENT EXECUTE FUNCTION analytics.reject_fv_cq_forward_mutation_v1();
CREATE TRIGGER fv_cq_forward_planned_entry_immutable_v1
BEFORE UPDATE OR DELETE OR TRUNCATE ON analytics.fv_cq_forward_planned_entry_v1
FOR EACH STATEMENT EXECUTE FUNCTION analytics.reject_fv_cq_forward_mutation_v1();
CREATE TRIGGER fv_cq_forward_reason_immutable_v1
BEFORE UPDATE OR DELETE OR TRUNCATE ON analytics.fv_cq_forward_member_reason_v1
FOR EACH STATEMENT EXECUTE FUNCTION analytics.reject_fv_cq_forward_mutation_v1();
CREATE TRIGGER fv_cq_forward_evidence_immutable_v1
BEFORE UPDATE OR DELETE OR TRUNCATE ON analytics.fv_cq_forward_member_evidence_v1
FOR EACH STATEMENT EXECUTE FUNCTION analytics.reject_fv_cq_forward_mutation_v1();
CREATE TRIGGER fv_cq_forward_normalized_parent_immutable_v1
BEFORE UPDATE OR DELETE OR TRUNCATE ON analytics.fv_cq_forward_normalized_parent_v1
FOR EACH STATEMENT EXECUTE FUNCTION analytics.reject_fv_cq_forward_mutation_v1();
CREATE TRIGGER fv_cq_forward_parent_role_immutable_v1
BEFORE UPDATE OR DELETE OR TRUNCATE ON analytics.fv_cq_forward_parent_role_v1
FOR EACH STATEMENT EXECUTE FUNCTION analytics.reject_fv_cq_forward_mutation_v1();
CREATE TRIGGER fv_cq_forward_maturity_immutable_v1
BEFORE UPDATE OR DELETE OR TRUNCATE ON analytics.fv_cq_forward_maturity_v1
FOR EACH STATEMENT EXECUTE FUNCTION analytics.reject_fv_cq_forward_mutation_v1();
CREATE TRIGGER fv_cq_forward_seal_immutable_v1
BEFORE UPDATE OR DELETE OR TRUNCATE ON analytics.fv_cq_forward_enrollment_seal_v1
FOR EACH STATEMENT EXECUTE FUNCTION analytics.reject_fv_cq_forward_mutation_v1();

DO $$
DECLARE table_name TEXT;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles
                 WHERE rolname='analytics_fv_cq_normalized_parent_writer_v1') THEN
    CREATE ROLE analytics_fv_cq_normalized_parent_writer_v1 NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='analytics_fv_cq_forward_writer_v1') THEN
    CREATE ROLE analytics_fv_cq_forward_writer_v1 NOLOGIN;
  END IF;
  GRANT USAGE ON SCHEMA analytics TO analytics_fv_cq_forward_writer_v1;
  GRANT USAGE ON SCHEMA analytics TO analytics_fv_cq_normalized_parent_writer_v1;
  REVOKE INSERT,UPDATE,DELETE,TRUNCATE ON analytics.fv_cq_forward_parent_role_v1
    FROM analytics_writer,analytics_fv_cq_forward_writer_v1,PUBLIC;
  GRANT SELECT ON analytics.fv_cq_forward_parent_role_v1
    TO analytics_fv_cq_forward_writer_v1,analytics_reader;
  GRANT SELECT ON analytics.security,analytics.evidence_company_identity_v1,
    analytics.evidence_instrument_identity_v1,analytics.evidence_share_class_identity_v1,
    analytics.evidence_listing_identity_v1,analytics.evidence_ticker_assignment_v1,
    analytics.evidence_trading_calendar_v1,analytics.evidence_completed_session_v1,
    analytics.evidence_selection_request_v1,analytics.evidence_selection_result_v1,
    analytics.evidence_selector_policy_v1,analytics.canonical_evidence_v1,
    analytics.evidence_raw_manifest_v1,analytics.fv_cq_forward_normalized_parent_v1
    TO analytics_fv_cq_forward_writer_v1;
  REVOKE INSERT,UPDATE,DELETE,TRUNCATE ON analytics.fv_cq_forward_normalized_parent_v1
    FROM analytics_writer,analytics_fv_cq_forward_writer_v1,PUBLIC;
  GRANT SELECT ON analytics.fv_cq_forward_normalized_parent_v1 TO analytics_reader;
  GRANT SELECT,INSERT ON analytics.fv_cq_forward_normalized_parent_v1
    TO analytics_fv_cq_normalized_parent_writer_v1;
  REVOKE UPDATE,DELETE,TRUNCATE ON analytics.fv_cq_forward_normalized_parent_v1
    FROM analytics_fv_cq_normalized_parent_writer_v1;
  GRANT analytics_fv_cq_forward_writer_v1 TO analytics_fundamental_value_writer_v1;
  FOREACH table_name IN ARRAY ARRAY['fv_cq_forward_enrollment_v1',
    'fv_cq_forward_decision_session_v1','fv_cq_forward_planned_entry_v1',
    'fv_cq_forward_member_v1','fv_cq_forward_member_evidence_v1',
    'fv_cq_forward_member_reason_v1','fv_cq_forward_maturity_v1',
    'fv_cq_forward_enrollment_seal_v1'] LOOP
    EXECUTE format('REVOKE INSERT,UPDATE,DELETE,TRUNCATE ON analytics.%I FROM analytics_writer,PUBLIC',table_name);
    EXECUTE format('GRANT SELECT,INSERT ON analytics.%I TO analytics_fv_cq_forward_writer_v1',table_name);
    EXECUTE format('REVOKE UPDATE,DELETE,TRUNCATE ON analytics.%I FROM analytics_fv_cq_forward_writer_v1',table_name);
    EXECUTE format('GRANT SELECT ON analytics.%I TO analytics_reader',table_name);
  END LOOP;
END $$;
