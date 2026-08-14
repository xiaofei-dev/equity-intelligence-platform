CREATE TABLE analytics.fv_current_producer_contract_v1 (
    operand_ordinal INTEGER PRIMARY KEY,
    operand_code VARCHAR(128) NOT NULL UNIQUE,
    evaluator_version VARCHAR(255) NOT NULL,
    evidence_kind VARCHAR(64) NOT NULL,
    source_roles JSONB NOT NULL,
    governance VARCHAR(64) NOT NULL,
    producer_contract_hash VARCHAR(71) NOT NULL UNIQUE,
    UNIQUE (operand_code,producer_contract_hash),
    CONSTRAINT ck_fv_current_producer_contract_v1 CHECK (
        operand_ordinal BETWEEN 1 AND 34
        AND operand_code ~ '^[a-z][a-z0-9_]{0,127}$'
        AND evaluator_version =
            'FV-CURRENT-REVISION-PRODUCER-v1.0.0:' || operand_code
        AND evidence_kind IN (
            'PROVIDER_NORMALIZED_DERIVATION','POLICY_EVIDENCE','ADVANCED_EVIDENCE'
        )
        AND analytics.evidence_json_nonblank_string_array_v1(source_roles)
        AND jsonb_array_length(source_roles) > 0
        AND governance = 'CURRENT_REVISION_APPROXIMATION_ONLY'
        AND producer_contract_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

INSERT INTO analytics.fv_current_producer_contract_v1 VALUES
(1,'reference_price','FV-CURRENT-REVISION-PRODUCER-v1.0.0:reference_price','PROVIDER_NORMALIZED_DERIVATION','["COMPLETED_CLOSE_PRICE"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:05af5682c2787742290896ce37b26b2b77b34dc39404edab5500d4744ed2e14c'),
(2,'diluted_shares','FV-CURRENT-REVISION-PRODUCER-v1.0.0:diluted_shares','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:5b8d3a5bfe52ac694a30c4b7604807f04dbbc0a5bd48d75a3b363656f6ae8701'),
(3,'cash','FV-CURRENT-REVISION-PRODUCER-v1.0.0:cash','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:6567606809ee55e6b17c724e87ad27a39113f7095cf13b0c8e9cd6478974ec5a'),
(4,'debt','FV-CURRENT-REVISION-PRODUCER-v1.0.0:debt','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:59da573d0b8daea0e9791fe6670a615ee1009cb4d6de4b218f9a94d682dd2db0'),
(5,'ebit','FV-CURRENT-REVISION-PRODUCER-v1.0.0:ebit','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:8d16632ea45c6197ceed494497c6f56a3a9a5f839b19343c5fc4b86c92f3b48a'),
(6,'tax_rate','FV-CURRENT-REVISION-PRODUCER-v1.0.0:tax_rate','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:c453dd35dbba5cf90bb6f41ff27ed3849456e65868841ab311c04645edb5f517'),
(7,'depreciation_and_amortization','FV-CURRENT-REVISION-PRODUCER-v1.0.0:depreciation_and_amortization','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:febd3d167de80eef77f34677fc1ed4b344d8a92f0c2dab24c0d55e41b019106d'),
(8,'capital_expenditures','FV-CURRENT-REVISION-PRODUCER-v1.0.0:capital_expenditures','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:f341d5ebdde86422a869ada2e104f6a2f5d5164a6e7673c0bda173e8571ee560'),
(9,'change_in_working_capital','FV-CURRENT-REVISION-PRODUCER-v1.0.0:change_in_working_capital','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:06dcd713b4fd0f60b9746d01fa12c058faaaecf6480e4f4762a91462a1b06823'),
(10,'normalized_free_cash_flow','FV-CURRENT-REVISION-PRODUCER-v1.0.0:normalized_free_cash_flow','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:76e2bafa36ce9464641071e49434bf0857058f15060b647c59f141072457f59b'),
(11,'normalized_after_tax_operating_earnings','FV-CURRENT-REVISION-PRODUCER-v1.0.0:normalized_after_tax_operating_earnings','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:e4bd90d6d44d639324a187805b93fab8676dc626114856b47b6995bace2ad41b'),
(12,'ebitda','FV-CURRENT-REVISION-PRODUCER-v1.0.0:ebitda','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:f56d75bb2cf17b4c3df1a2d9137c84bbc1b3cfe0aed7a9ce4fef1157bc62f279'),
(13,'comparable_ev_to_ebitda','FV-CURRENT-REVISION-PRODUCER-v1.0.0:comparable_ev_to_ebitda','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:8c4a3d698b75899a32d351a8a9840ad9493affaca33b225eef7e6c1cfb07c19a'),
(14,'conservative_growth_rate','FV-CURRENT-REVISION-PRODUCER-v1.0.0:conservative_growth_rate','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:dacb15080d7974f1290754cb8573bc4d8188c927ca087838832bc0037138efd7'),
(15,'discount_rate','FV-CURRENT-REVISION-PRODUCER-v1.0.0:discount_rate','POLICY_EVIDENCE','["FIXED_RISK_FREE_ASSUMPTION","EODHD_BETA"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:0032d1d8d787269a3bbb32d5abebc0405a00167fa3517175bbee1ca4bdd0bbee'),
(16,'terminal_growth_rate','FV-CURRENT-REVISION-PRODUCER-v1.0.0:terminal_growth_rate','POLICY_EVIDENCE','["FIXED_TERMINAL_GROWTH_ASSUMPTION"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:4aaff62c2595ef25a52a24f2edfecc9a4bb95ca190f90d283763652a78a8fd56'),
(17,'net_distribution_yield','FV-CURRENT-REVISION-PRODUCER-v1.0.0:net_distribution_yield','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:079e68950fed68013b274db9fe5f03ac565e2fa4de9dbf8d0a9020a40ce4c1b0'),
(18,'return_on_invested_capital','FV-CURRENT-REVISION-PRODUCER-v1.0.0:return_on_invested_capital','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:88a8a938426e69dd80c1c490577f3b37dfee21ff858a83815c097725b3b28b18'),
(19,'operating_margin','FV-CURRENT-REVISION-PRODUCER-v1.0.0:operating_margin','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:d877c376bcdedbf16d5af08d1a5e345050a087091418faf78bc657585c23a68c'),
(20,'free_cash_flow_margin','FV-CURRENT-REVISION-PRODUCER-v1.0.0:free_cash_flow_margin','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:f5b31ebbdfb553c656d78685728b488aaa3412bcdb38b590213415f6800cd9de'),
(21,'earnings_stability','FV-CURRENT-REVISION-PRODUCER-v1.0.0:earnings_stability','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:e5fddcc06015fac616789f395054eded95460e417ca60aedf91bea4e2199a366'),
(22,'cash_flow_stability','FV-CURRENT-REVISION-PRODUCER-v1.0.0:cash_flow_stability','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:9b068cf6edb78814e03c2d64816258add32e00930031ec29e5e6cf59fa09423a'),
(23,'net_debt_to_ebitda','FV-CURRENT-REVISION-PRODUCER-v1.0.0:net_debt_to_ebitda','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:b3e5b0d429b3fe52fbdcb5e66aeeaf94b885a9be5616ccee61a981a5bf0e93b7'),
(24,'interest_coverage','FV-CURRENT-REVISION-PRODUCER-v1.0.0:interest_coverage','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:9771f160a352520b002f6496e094cf6a202154975456e28e233249dfe7b5dde5'),
(25,'current_ratio','FV-CURRENT-REVISION-PRODUCER-v1.0.0:current_ratio','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:233b4704e4708ba8ae57459ec9fe92a6cd474379235327a21f891b02a735842e'),
(26,'diluted_share_growth','FV-CURRENT-REVISION-PRODUCER-v1.0.0:diluted_share_growth','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:588da96ebb10419177f53b45834fc8fa29e14dd915422cd1d65c2f1a512e1671'),
(27,'cash_flow_to_net_income','FV-CURRENT-REVISION-PRODUCER-v1.0.0:cash_flow_to_net_income','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:ee1d152cd76223c2599b70c8440c39eaf30b3ff6ff532764f58a87654fa190ce'),
(28,'incremental_return_on_invested_capital','FV-CURRENT-REVISION-PRODUCER-v1.0.0:incremental_return_on_invested_capital','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:501f9008bfecd6ddd9ade7a8124062ea78bcdbc1985b1254cd55563f1b1b5b2d'),
(29,'acquisition_discipline','FV-CURRENT-REVISION-PRODUCER-v1.0.0:acquisition_discipline','POLICY_EVIDENCE','["EODHD_INCREMENTAL_ROIC_AND_GOODWILL_PROXY"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:8e81201ad576d19c14c8273afdae54387abb33e1e4bb403a0b91cd6619a8e95d'),
(30,'shareholder_distribution_coverage','FV-CURRENT-REVISION-PRODUCER-v1.0.0:shareholder_distribution_coverage','PROVIDER_NORMALIZED_DERIVATION','["EODHD_CURRENT_REVISION_FINANCIALS"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:c0ee03cd70f7344022929abb53cd387f05144a90b2a4292e7703c5aa33492ad5'),
(31,'cyclicality_risk','FV-CURRENT-REVISION-PRODUCER-v1.0.0:cyclicality_risk','POLICY_EVIDENCE','["EODHD_FIVE_YEAR_REVENUE_VARIABILITY_PROXY"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:e099af8af7a45a645ce62dae8da3977beecd343a16fa9d5f8edf8672f219a04a'),
(32,'concentration_risk','FV-CURRENT-REVISION-PRODUCER-v1.0.0:concentration_risk','POLICY_EVIDENCE','["EODHD_OPERATING_LEVERAGE_CONCENTRATION_PROXY"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:f63cce3629993c9594f2709107745fadae974670f567d34734484d334a4cc32d'),
(33,'event_risk','FV-CURRENT-REVISION-PRODUCER-v1.0.0:event_risk','POLICY_EVIDENCE','["EODHD_BETA_EARNINGS_SHOCK_AND_LEVERAGE_PROXY"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:d79ab7d9de2851d9d3e325f15d9e94c2482a84c060d2d38a49498338423495ac'),
(34,'debt_maturity_schedule','FV-CURRENT-REVISION-PRODUCER-v1.0.0:debt_maturity_schedule','ADVANCED_EVIDENCE','["DEBT_MATURITY_SOURCE_REQUIRED"]','CURRENT_REVISION_APPROXIMATION_ONLY','sha256:40be80039816a51a58395a09aa8d8dc50a8d48275cddcbfeea2c02ff05b56fe2');

CREATE TABLE analytics.fv_current_assessment_authority_v1 (
    authority_id UUID PRIMARY KEY,
    contract_version VARCHAR(128) NOT NULL,
    identity_authority_id UUID NOT NULL UNIQUE
      REFERENCES analytics.fv_identity_authority_v2(authority_id),
    identity_projection_content_hash VARCHAR(71) NOT NULL,
    authorized_symbols JSONB NOT NULL,
    evidence_track VARCHAR(128) NOT NULL,
    model_evidence_label VARCHAR(32) NOT NULL,
    authorization_reference VARCHAR(255) NOT NULL,
    authorization_content_hash VARCHAR(71) NOT NULL,
    assessment_persistence_authorized BOOLEAN NOT NULL,
    read_only_publication_authorized BOOLEAN NOT NULL,
    deterministic_action_authorized BOOLEAN NOT NULL,
    deterministic_ranking_authorized BOOLEAN NOT NULL,
    final_portfolio_weight_authorized BOOLEAN NOT NULL,
    automatic_brokerage_execution_authorized BOOLEAN NOT NULL,
    evidence_label_upgrade_authorized BOOLEAN NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT date_trunc('second',CURRENT_TIMESTAMP),
    CONSTRAINT ck_fv_current_assessment_authority_v1 CHECK (
      contract_version='FV-CURRENT-ASSESSMENT-AUTHORITY-v1.0.0'
      AND identity_projection_content_hash ~ '^sha256:[0-9a-f]{64}$'
      AND authorized_symbols='["GOOG","FOX","MSFT"]'::jsonb
      AND evidence_track='EODHD_PROVIDER_NORMALIZED_CURRENT_REVISION_APPROXIMATION'
      AND model_evidence_label='NOT_VALIDATED'
      AND authorization_reference=
        'CODEX_THREAD_USER_APPROVAL_2026-08-12_UTF8_SHA256'
      AND authorization_content_hash=
        'sha256:8cbe697b157364a5b13646285b38409dc53ec5287deeb7913493e65b275cd14d'
      AND assessment_persistence_authorized AND read_only_publication_authorized
      AND NOT deterministic_action_authorized
      AND NOT deterministic_ranking_authorized
      AND NOT final_portfolio_weight_authorized
      AND NOT automatic_brokerage_execution_authorized
      AND NOT evidence_label_upgrade_authorized
      AND date_trunc('second',recorded_at)=recorded_at
    )
);

CREATE TABLE analytics.fv_current_assessment_v1 (
    assessment_id UUID PRIMARY KEY,
    current_assessment_authority_id UUID NOT NULL
      REFERENCES analytics.fv_current_assessment_authority_v1(authority_id),
    contract_version VARCHAR(128) NOT NULL,
    producer_version VARCHAR(128) NOT NULL,
    policy_version VARCHAR(128) NOT NULL,
    evidence_track VARCHAR(128) NOT NULL,
    claim_ceiling VARCHAR(128) NOT NULL,
    model_evidence_label VARCHAR(32) NOT NULL,
    identity_authority_id UUID NOT NULL,
    identity_authority_member_ordinal INTEGER NOT NULL,
    security_id UUID NOT NULL REFERENCES analytics.security(public_id),
    company_id UUID NOT NULL REFERENCES analytics.evidence_company_identity_v1(company_id),
    instrument_id UUID NOT NULL REFERENCES analytics.evidence_instrument_identity_v1(instrument_id),
    share_class_id UUID NOT NULL REFERENCES analytics.evidence_share_class_identity_v1(share_class_id),
    listing_id UUID NOT NULL REFERENCES analytics.evidence_listing_identity_v1(listing_id),
    ticker_assignment_id UUID NOT NULL REFERENCES analytics.evidence_ticker_assignment_v1(ticker_assignment_id),
    symbol VARCHAR(32) NOT NULL,
    mic CHAR(4) NOT NULL,
    currency CHAR(3) NOT NULL,
    decision_cutoff TIMESTAMPTZ NOT NULL,
    price_session_date DATE NOT NULL,
    latest_fundamental_period_end DATE NOT NULL,
    completed_session_id UUID NOT NULL REFERENCES analytics.evidence_completed_session_v1(id),
    completed_session_hash VARCHAR(71) NOT NULL,
    classification_routing_id UUID NOT NULL REFERENCES analytics.model_applicability_routing_v1(routing_id),
    classification_routing_hash VARCHAR(71) NOT NULL,
    classification_request_id UUID NOT NULL REFERENCES analytics.evidence_selection_request_v1(request_id),
    classification_request_hash VARCHAR(71) NOT NULL,
    classification_result_hash VARCHAR(71) NOT NULL,
    classification_policy_hash VARCHAR(71) NOT NULL,
    classification_evidence_id UUID NOT NULL REFERENCES analytics.canonical_evidence_v1(evidence_id),
    classification_evidence_hash VARCHAR(71) NOT NULL,
    price_request_id UUID NOT NULL REFERENCES analytics.evidence_selection_request_v1(request_id),
    price_request_hash VARCHAR(71) NOT NULL,
    price_result_hash VARCHAR(71) NOT NULL,
    price_policy_hash VARCHAR(71) NOT NULL,
    price_evidence_id UUID NOT NULL REFERENCES analytics.canonical_evidence_v1(evidence_id),
    price_evidence_hash VARCHAR(71) NOT NULL,
    state VARCHAR(32) NOT NULL,
    investment_category VARCHAR(64) NOT NULL,
    company_quality NUMERIC NOT NULL,
    financial_resilience NUMERIC NOT NULL,
    earnings_cash_flow_quality NUMERIC NOT NULL,
    capital_allocation_quality NUMERIC NOT NULL,
    downside_risk NUMERIC NOT NULL,
    fair_value_low NUMERIC NOT NULL,
    fair_value_central NUMERIC NOT NULL,
    fair_value_high NUMERIC NOT NULL,
    margin_of_safety_low NUMERIC NOT NULL,
    margin_of_safety_central NUMERIC NOT NULL,
    margin_of_safety_high NUMERIC NOT NULL,
    expected_return_low NUMERIC NOT NULL,
    expected_return_central NUMERIC NOT NULL,
    expected_return_high NUMERIC NOT NULL,
    risk_cap_ceiling NUMERIC NOT NULL,
    source_count INTEGER NOT NULL,
    operand_count INTEGER NOT NULL,
    parent_count INTEGER NOT NULL,
    reason_count INTEGER NOT NULL,
    assessment_content_hash VARCHAR(71) NOT NULL UNIQUE,
    canonical_body_text TEXT NOT NULL,
    payload_sha256 VARCHAR(71) NOT NULL UNIQUE,
    canonical_payload_text TEXT NOT NULL,
    canonical_payload JSONB NOT NULL,
    deterministic_action_authorized BOOLEAN NOT NULL,
    deterministic_ranking_authorized BOOLEAN NOT NULL,
    final_portfolio_weight_authorized BOOLEAN NOT NULL,
    automatic_brokerage_execution_authorized BOOLEAN NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL
        DEFAULT date_trunc('second', CURRENT_TIMESTAMP),
    FOREIGN KEY (identity_authority_id,identity_authority_member_ordinal)
      REFERENCES analytics.fv_identity_authority_member_v2(authority_id,member_ordinal),
    UNIQUE (security_id,decision_cutoff,contract_version),
    CONSTRAINT ck_fv_current_assessment_contract_v1 CHECK (
      contract_version='FV-CURRENT-FUNDAMENTAL-ASSESSMENT-v1.0.0'
      AND producer_version='FV-CURRENT-REVISION-PRODUCER-v1.0.0'
      AND policy_version='FV-CURRENT-INVESTMENT-POLICY-v1.0.0'
      AND evidence_track='EODHD_PROVIDER_NORMALIZED_CURRENT_REVISION_APPROXIMATION'
      AND claim_ceiling='DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION'
      AND model_evidence_label='NOT_VALIDATED'
      AND state='VALID'
      AND source_count=2 AND operand_count=34 AND parent_count=32 AND reason_count=1
      AND NOT deterministic_action_authorized
      AND NOT deterministic_ranking_authorized
      AND NOT final_portfolio_weight_authorized
        AND NOT automatic_brokerage_execution_authorized
        AND date_trunc('second', recorded_at) = recorded_at
    ),
    CONSTRAINT ck_fv_current_assessment_identity_v1 CHECK (
      symbol ~ '^[A-Z][A-Z0-9.-]{0,31}$' AND mic ~ '^[A-Z0-9]{4}$'
      AND currency ~ '^[A-Z]{3}$'
    ),
    CONSTRAINT ck_fv_current_assessment_chronology_v1 CHECK (
      price_session_date <= (decision_cutoff AT TIME ZONE 'UTC')::date
      AND latest_fundamental_period_end <= (decision_cutoff AT TIME ZONE 'UTC')::date
    ),
    CONSTRAINT ck_fv_current_assessment_ranges_v1 CHECK (
      company_quality::text NOT IN ('NaN','Infinity','-Infinity')
      AND financial_resilience::text NOT IN ('NaN','Infinity','-Infinity')
      AND earnings_cash_flow_quality::text NOT IN ('NaN','Infinity','-Infinity')
      AND capital_allocation_quality::text NOT IN ('NaN','Infinity','-Infinity')
      AND downside_risk::text NOT IN ('NaN','Infinity','-Infinity')
      AND fair_value_low::text NOT IN ('NaN','Infinity','-Infinity')
      AND fair_value_central::text NOT IN ('NaN','Infinity','-Infinity')
      AND fair_value_high::text NOT IN ('NaN','Infinity','-Infinity')
      AND margin_of_safety_low::text NOT IN ('NaN','Infinity','-Infinity')
      AND margin_of_safety_central::text NOT IN ('NaN','Infinity','-Infinity')
      AND margin_of_safety_high::text NOT IN ('NaN','Infinity','-Infinity')
      AND expected_return_low::text NOT IN ('NaN','Infinity','-Infinity')
      AND expected_return_central::text NOT IN ('NaN','Infinity','-Infinity')
      AND expected_return_high::text NOT IN ('NaN','Infinity','-Infinity')
      AND risk_cap_ceiling::text NOT IN ('NaN','Infinity','-Infinity')
      AND company_quality BETWEEN 0 AND 100 AND financial_resilience BETWEEN 0 AND 100
      AND earnings_cash_flow_quality BETWEEN 0 AND 100
      AND capital_allocation_quality BETWEEN 0 AND 100
      AND downside_risk BETWEEN 0 AND 100
      AND fair_value_low <= fair_value_central AND fair_value_central <= fair_value_high
      AND margin_of_safety_low <= margin_of_safety_central
      AND margin_of_safety_central <= margin_of_safety_high
      AND expected_return_low <= expected_return_central
      AND expected_return_central <= expected_return_high
      AND risk_cap_ceiling BETWEEN 0 AND 0.02
    ),
    CONSTRAINT ck_fv_current_assessment_hash_v1 CHECK (
      assessment_content_hash ~ '^sha256:[0-9a-f]{64}$'
      AND payload_sha256 ~ '^sha256:[0-9a-f]{64}$'
      AND assessment_content_hash='sha256:'||encode(sha256(convert_to(canonical_body_text,'UTF8')),'hex')
      AND payload_sha256='sha256:'||encode(sha256(convert_to(canonical_payload_text,'UTF8')),'hex')
      AND canonical_payload_text::jsonb=canonical_payload
      AND canonical_payload->>'content_hash'=assessment_content_hash
    )
);

CREATE INDEX ix_fv_current_assessment_security_v1
  ON analytics.fv_current_assessment_v1(security_id,decision_cutoff DESC);
CREATE INDEX ix_fv_current_assessment_symbol_v1
  ON analytics.fv_current_assessment_v1(symbol,decision_cutoff DESC);

CREATE TABLE analytics.fv_current_assessment_source_v1 (
    assessment_id UUID NOT NULL REFERENCES analytics.fv_current_assessment_v1(assessment_id),
    source_ordinal INTEGER NOT NULL,
    source_role VARCHAR(32) NOT NULL,
    raw_manifest_id UUID NOT NULL REFERENCES analytics.evidence_raw_manifest_v1(id),
    provider_code VARCHAR(128) NOT NULL,
    schema_version VARCHAR(128) NOT NULL,
    source_reference TEXT NOT NULL,
    file_sha256 CHAR(64) NOT NULL,
    source_content_hash VARCHAR(71) NOT NULL,
    normalized_record_hash VARCHAR(71) NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    retrieved_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ NOT NULL,
    source_revision INTEGER NOT NULL,
    adapter_version VARCHAR(128) NOT NULL,
    normalization_version VARCHAR(128) NOT NULL,
    freshness_policy_version VARCHAR(128) NOT NULL,
    source_record_id UUID NOT NULL,
    request_identity CHAR(64) NOT NULL,
    plan_hash CHAR(64) NOT NULL,
    checkpoint_reference TEXT NOT NULL,
    PRIMARY KEY (assessment_id,source_ordinal),
    UNIQUE (assessment_id,source_role),
    UNIQUE (assessment_id,raw_manifest_id),
    UNIQUE (assessment_id,source_ordinal,raw_manifest_id),
    CONSTRAINT ck_fv_current_assessment_source_v1 CHECK (
      source_ordinal BETWEEN 1 AND 2
      AND ((source_ordinal=1 AND source_role='FUNDAMENTALS' AND provider_code='EODHD')
        OR (source_ordinal=2 AND source_role='PRICE' AND provider_code IN ('YAHOO','EODHD')))
      AND file_sha256 ~ '^[0-9A-F]{64}$'
      AND source_content_hash='sha256:'||lower(file_sha256)
      AND normalized_record_hash ~ '^sha256:[0-9a-f]{64}$'
      AND source_revision > 0 AND available_at <= ingested_at
      AND (retrieved_at IS NULL OR available_at <= retrieved_at AND retrieved_at <= ingested_at)
      AND request_identity ~ '^[0-9A-F]{64}$' AND plan_hash ~ '^[0-9A-F]{64}$'
      AND btrim(schema_version)<>'' AND btrim(source_reference)<>''
      AND btrim(adapter_version)<>'' AND btrim(normalization_version)<>''
      AND btrim(freshness_policy_version)<>'' AND btrim(checkpoint_reference)<>''
    )
);

CREATE TABLE analytics.fv_current_assessment_operand_v1 (
    assessment_id UUID NOT NULL REFERENCES analytics.fv_current_assessment_v1(assessment_id),
    operand_ordinal INTEGER NOT NULL,
    operand_code VARCHAR(128) NOT NULL,
    state VARCHAR(32) NOT NULL,
    numeric_value NUMERIC,
    evidence_kind VARCHAR(64) NOT NULL,
    source_roles JSONB NOT NULL,
    producer_contract_hash VARCHAR(71) NOT NULL,
    output_content_hash VARCHAR(71) NOT NULL,
    parent_count INTEGER NOT NULL,
    reason_count INTEGER NOT NULL,
    PRIMARY KEY (assessment_id,operand_ordinal),
    UNIQUE (assessment_id,operand_code),
    FOREIGN KEY (operand_code,producer_contract_hash)
      REFERENCES analytics.fv_current_producer_contract_v1(operand_code,producer_contract_hash),
    CONSTRAINT ck_fv_current_assessment_operand_v1 CHECK (
      operand_ordinal BETWEEN 1 AND 34
      AND state IN ('VALID','MISSING','STALE','INVALID','EXCLUDED','NOT_APPLICABLE')
      AND analytics.evidence_json_nonblank_string_array_v1(source_roles)
      AND jsonb_array_length(source_roles)>0
      AND output_content_hash ~ '^sha256:[0-9a-f]{64}$'
      AND ((state='VALID' AND numeric_value IS NOT NULL AND reason_count=0)
        OR (state<>'VALID' AND numeric_value IS NULL AND reason_count>0))
      AND (numeric_value IS NULL
        OR numeric_value::text NOT IN ('NaN','Infinity','-Infinity'))
      AND parent_count BETWEEN 0 AND 1
    )
);

CREATE TABLE analytics.fv_current_assessment_operand_parent_v1 (
    assessment_id UUID NOT NULL,
    operand_ordinal INTEGER NOT NULL,
    parent_ordinal INTEGER NOT NULL,
    raw_manifest_id UUID NOT NULL,
    source_ordinal INTEGER NOT NULL,
    PRIMARY KEY (assessment_id,operand_ordinal,parent_ordinal),
    FOREIGN KEY (assessment_id,operand_ordinal)
      REFERENCES analytics.fv_current_assessment_operand_v1(assessment_id,operand_ordinal),
    FOREIGN KEY (assessment_id,source_ordinal,raw_manifest_id)
      REFERENCES analytics.fv_current_assessment_source_v1(
        assessment_id,source_ordinal,raw_manifest_id),
    CONSTRAINT ck_fv_current_assessment_parent_v1 CHECK (parent_ordinal=1)
);

CREATE TABLE analytics.fv_current_assessment_operand_reason_v1 (
    assessment_id UUID NOT NULL,
    operand_ordinal INTEGER NOT NULL,
    reason_ordinal INTEGER NOT NULL,
    reason_code VARCHAR(128) NOT NULL,
    PRIMARY KEY (assessment_id,operand_ordinal,reason_ordinal),
    UNIQUE (assessment_id,operand_ordinal,reason_code),
    FOREIGN KEY (assessment_id,operand_ordinal)
      REFERENCES analytics.fv_current_assessment_operand_v1(assessment_id,operand_ordinal),
    CONSTRAINT ck_fv_current_assessment_reason_v1 CHECK (
      reason_ordinal > 0 AND btrim(reason_code)<>''
    )
);

CREATE TABLE analytics.fv_current_assessment_seal_v1 (
    assessment_id UUID PRIMARY KEY REFERENCES analytics.fv_current_assessment_v1(assessment_id),
    source_count INTEGER NOT NULL,
    operand_count INTEGER NOT NULL,
    parent_count INTEGER NOT NULL,
    reason_count INTEGER NOT NULL,
    assessment_content_hash VARCHAR(71) NOT NULL,
    payload_sha256 VARCHAR(71) NOT NULL,
    creator_xid8 XID8 NOT NULL DEFAULT pg_current_xact_id(),
    sealed_at TIMESTAMPTZ NOT NULL DEFAULT date_trunc('second',CURRENT_TIMESTAMP),
    CONSTRAINT ck_fv_current_assessment_seal_v1 CHECK (
      source_count=2 AND operand_count=34 AND parent_count=32 AND reason_count=1
      AND assessment_content_hash ~ '^sha256:[0-9a-f]{64}$'
      AND payload_sha256 ~ '^sha256:[0-9a-f]{64}$'
      AND date_trunc('second',sealed_at)=sealed_at
    )
);

CREATE FUNCTION analytics.set_fv_current_assessment_creator_xid8_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.creator_xid8:=pg_current_xact_id();
  NEW.sealed_at:=date_trunc('second',CURRENT_TIMESTAMP);
  RETURN NEW;
END;
$$;
CREATE TRIGGER tr_set_fv_current_assessment_creator_xid8_v1
BEFORE INSERT ON analytics.fv_current_assessment_seal_v1
FOR EACH ROW EXECUTE FUNCTION analytics.set_fv_current_assessment_creator_xid8_v1();

CREATE FUNCTION analytics.set_fv_current_assessment_recorded_at_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.recorded_at:=date_trunc('second',CURRENT_TIMESTAMP); RETURN NEW; END;
$$;
CREATE TRIGGER tr_set_fv_current_assessment_recorded_at_v1
BEFORE INSERT ON analytics.fv_current_assessment_v1
FOR EACH ROW EXECUTE FUNCTION analytics.set_fv_current_assessment_recorded_at_v1();

CREATE FUNCTION analytics.set_fv_current_assessment_authority_recorded_at_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.recorded_at:=date_trunc('second',CURRENT_TIMESTAMP); RETURN NEW; END;
$$;
CREATE TRIGGER tr_set_fv_current_assessment_authority_recorded_at_v1
BEFORE INSERT ON analytics.fv_current_assessment_authority_v1
FOR EACH ROW EXECUTE FUNCTION analytics.set_fv_current_assessment_authority_recorded_at_v1();

CREATE FUNCTION analytics.reject_fv_current_assessment_late_child_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM analytics.fv_current_assessment_seal_v1 s
    WHERE s.assessment_id=NEW.assessment_id
      AND s.creator_xid8<>pg_current_xact_id()) THEN
    RAISE EXCEPTION 'Current Fundamental Value assessment is sealed';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER tr_fv_current_source_late_v1 BEFORE INSERT ON analytics.fv_current_assessment_source_v1
FOR EACH ROW EXECUTE FUNCTION analytics.reject_fv_current_assessment_late_child_v1();
CREATE TRIGGER tr_fv_current_operand_late_v1 BEFORE INSERT ON analytics.fv_current_assessment_operand_v1
FOR EACH ROW EXECUTE FUNCTION analytics.reject_fv_current_assessment_late_child_v1();
CREATE TRIGGER tr_fv_current_parent_late_v1 BEFORE INSERT ON analytics.fv_current_assessment_operand_parent_v1
FOR EACH ROW EXECUTE FUNCTION analytics.reject_fv_current_assessment_late_child_v1();
CREATE TRIGGER tr_fv_current_reason_late_v1 BEFORE INSERT ON analytics.fv_current_assessment_operand_reason_v1
FOR EACH ROW EXECUTE FUNCTION analytics.reject_fv_current_assessment_late_child_v1();

CREATE FUNCTION analytics.validate_fv_current_assessment_complete_v1()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  target UUID:=NEW.assessment_id;
  root analytics.fv_current_assessment_v1%ROWTYPE;
  seal analytics.fv_current_assessment_seal_v1%ROWTYPE;
  source_total INTEGER; operand_total INTEGER; parent_total INTEGER; reason_total INTEGER;
  bad INTEGER;
BEGIN
  SELECT * INTO root FROM analytics.fv_current_assessment_v1 WHERE assessment_id=target;
  SELECT * INTO seal FROM analytics.fv_current_assessment_seal_v1 WHERE assessment_id=target;
  IF root.assessment_id IS NULL OR seal.assessment_id IS NULL THEN
    RAISE EXCEPTION 'Current Fundamental Value assessment graph is incomplete';
  END IF;
  IF TG_TABLE_NAME<>'fv_current_assessment_v1'
     AND seal.creator_xid8<>pg_current_xact_id() THEN
    RAISE EXCEPTION 'Current Fundamental Value assessment changed after sealing';
  END IF;
  SELECT count(*) INTO source_total FROM analytics.fv_current_assessment_source_v1 WHERE assessment_id=target;
  SELECT count(*) INTO operand_total FROM analytics.fv_current_assessment_operand_v1 WHERE assessment_id=target;
  SELECT count(*) INTO parent_total FROM analytics.fv_current_assessment_operand_parent_v1 WHERE assessment_id=target;
  SELECT count(*) INTO reason_total FROM analytics.fv_current_assessment_operand_reason_v1 WHERE assessment_id=target;
  IF (source_total,operand_total,parent_total,reason_total)<>(2,34,32,1)
    OR (root.source_count,root.operand_count,root.parent_count,root.reason_count)<>(2,34,32,1)
    OR (seal.source_count,seal.operand_count,seal.parent_count,seal.reason_count)<>(2,34,32,1)
    OR seal.assessment_content_hash<>root.assessment_content_hash
    OR seal.payload_sha256<>root.payload_sha256 THEN
    RAISE EXCEPTION 'Current Fundamental Value assessment cardinality or seal drift';
  END IF;

  SELECT count(*) INTO bad
  FROM analytics.fv_current_assessment_authority_v1 auth
  JOIN analytics.fv_identity_authority_v2 identity
    ON identity.authority_id=auth.identity_authority_id
  WHERE auth.authority_id=root.current_assessment_authority_id
    AND auth.identity_authority_id=root.identity_authority_id
    AND auth.identity_projection_content_hash=identity.projection_content_hash
    AND root.symbol=ANY(ARRAY(SELECT jsonb_array_elements_text(auth.authorized_symbols)))
    AND auth.assessment_persistence_authorized
    AND auth.read_only_publication_authorized
    AND NOT auth.deterministic_action_authorized
    AND NOT auth.deterministic_ranking_authorized
    AND NOT auth.final_portfolio_weight_authorized
    AND NOT auth.automatic_brokerage_execution_authorized
    AND NOT auth.evidence_label_upgrade_authorized;
  IF bad<>1 THEN RAISE EXCEPTION 'Current assessment explicit authority missing'; END IF;

  SELECT count(*) INTO bad
  FROM analytics.fv_identity_authority_member_v2 m
  JOIN analytics.fv_identity_authority_v2 a ON a.authority_id=m.authority_id
  WHERE m.authority_id=root.identity_authority_id
    AND m.member_ordinal=root.identity_authority_member_ordinal
    AND (m.security_id,m.company_id,m.instrument_id,m.share_class_id,m.listing_id,
         m.ticker_assignment_id,m.ticker,m.mic,m.currency)=
        (root.security_id,root.company_id,root.instrument_id,root.share_class_id,
         root.listing_id,root.ticker_assignment_id,root.symbol,root.mic,root.currency)
    AND a.model_evidence_label='NOT_VALIDATED';
  IF bad<>1 THEN RAISE EXCEPTION 'Current assessment V25 identity provenance drift'; END IF;

  IF jsonb_typeof(root.canonical_payload->'source_seals') IS DISTINCT FROM 'array'
    OR jsonb_array_length(root.canonical_payload->'source_seals')<>2
    OR jsonb_typeof(root.canonical_payload->'input_evidence') IS DISTINCT FROM 'array'
    OR jsonb_array_length(root.canonical_payload->'input_evidence')<>34 THEN
    RAISE EXCEPTION 'Current assessment payload collection cardinality drift';
  END IF;

  IF root.contract_version IS DISTINCT FROM root.canonical_payload->>'contract_version'
    OR root.producer_version IS DISTINCT FROM root.canonical_payload->>'producer_version'
    OR root.policy_version IS DISTINCT FROM root.canonical_payload->>'policy_version'
    OR root.evidence_track IS DISTINCT FROM root.canonical_payload->>'evidence_track'
    OR root.claim_ceiling IS DISTINCT FROM root.canonical_payload->>'claim_ceiling'
    OR root.model_evidence_label IS DISTINCT FROM root.canonical_payload->>'model_evidence_label'
    OR root.security_id::text IS DISTINCT FROM root.canonical_payload->>'security_id'
    OR root.company_id::text IS DISTINCT FROM root.canonical_payload->>'company_id'
    OR root.instrument_id::text IS DISTINCT FROM root.canonical_payload->>'instrument_id'
    OR root.share_class_id::text IS DISTINCT FROM root.canonical_payload->>'share_class_id'
    OR root.listing_id::text IS DISTINCT FROM root.canonical_payload->>'listing_id'
    OR root.ticker_assignment_id::text IS DISTINCT FROM root.canonical_payload->>'ticker_assignment_id'
    OR root.symbol IS DISTINCT FROM root.canonical_payload->>'symbol'
    OR root.mic IS DISTINCT FROM root.canonical_payload->>'mic'
    OR root.currency IS DISTINCT FROM root.canonical_payload->>'currency'
    OR root.decision_cutoff IS DISTINCT FROM
       (root.canonical_payload->>'decision_cutoff')::timestamptz
    OR root.price_session_date IS DISTINCT FROM
       (root.canonical_payload->>'price_session_date')::date
    OR root.latest_fundamental_period_end IS DISTINCT FROM
       (root.canonical_payload->>'latest_fundamental_period_end')::date
    OR root.completed_session_id::text IS DISTINCT FROM
       root.canonical_payload#>>'{completed_session,completed_session_id}'
    OR root.completed_session_hash IS DISTINCT FROM
       root.canonical_payload#>>'{completed_session,session_content_hash}'
    OR root.classification_routing_id::text IS DISTINCT FROM
       root.canonical_payload#>>'{applicability_seal,routing_id}'
    OR root.classification_routing_hash IS DISTINCT FROM
       root.canonical_payload#>>'{applicability_seal,routing_content_hash}'
    OR root.classification_request_id::text IS DISTINCT FROM
       root.canonical_payload#>>'{applicability_seal,classification_request_id}'
    OR root.classification_request_hash IS DISTINCT FROM
       root.canonical_payload#>>'{applicability_seal,classification_request_content_hash}'
    OR root.classification_result_hash IS DISTINCT FROM
       root.canonical_payload#>>'{applicability_seal,classification_result_content_hash}'
    OR root.classification_policy_hash IS DISTINCT FROM
       root.canonical_payload#>>'{applicability_seal,classification_policy_content_hash}'
    OR root.classification_evidence_id::text IS DISTINCT FROM
       root.canonical_payload#>>'{applicability_seal,classification_evidence_id}'
    OR root.classification_evidence_hash IS DISTINCT FROM
       root.canonical_payload#>>'{applicability_seal,classification_normalized_record_hash}'
    OR root.price_request_id::text IS DISTINCT FROM
       root.canonical_payload#>>'{price_selection_seal,request_id}'
    OR root.price_request_hash IS DISTINCT FROM
       root.canonical_payload#>>'{price_selection_seal,request_content_hash}'
    OR root.price_result_hash IS DISTINCT FROM
       root.canonical_payload#>>'{price_selection_seal,result_content_hash}'
    OR root.price_policy_hash IS DISTINCT FROM
       root.canonical_payload#>>'{price_selection_seal,policy_content_hash}'
    OR root.price_evidence_id::text IS DISTINCT FROM
       root.canonical_payload#>>'{price_selection_seal,selected_evidence_id}'
    OR root.price_evidence_hash IS DISTINCT FROM
       root.canonical_payload#>>'{price_selection_seal,selected_evidence_normalized_record_hash}'
    OR root.state IS DISTINCT FROM root.canonical_payload#>>'{investment_view,state}'
    OR root.investment_category IS DISTINCT FROM
       root.canonical_payload#>>'{investment_view,category}'
    OR root.company_quality IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,company_quality,score}')::numeric
    OR root.financial_resilience IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,financial_resilience,score}')::numeric
    OR root.earnings_cash_flow_quality IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,earnings_and_cash_flow_quality,score}')::numeric
    OR root.capital_allocation_quality IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,capital_allocation_quality,score}')::numeric
    OR root.downside_risk IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,downside_risk,score}')::numeric
    OR root.fair_value_low IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,fair_value,low}')::numeric
    OR root.fair_value_central IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,fair_value,central}')::numeric
    OR root.fair_value_high IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,fair_value,high}')::numeric
    OR root.margin_of_safety_low IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,margin_of_safety,low}')::numeric
    OR root.margin_of_safety_central IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,margin_of_safety,central}')::numeric
    OR root.margin_of_safety_high IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,margin_of_safety,high}')::numeric
    OR root.expected_return_low IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,expected_return,low}')::numeric
    OR root.expected_return_central IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,expected_return,central}')::numeric
    OR root.expected_return_high IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,expected_return,high}')::numeric
    OR root.risk_cap_ceiling IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,risk_cap,ceiling}')::numeric
    OR root.deterministic_action_authorized IS DISTINCT FROM
       (root.canonical_payload#>>'{investment_view,deterministic_action_authorized}')::boolean
    OR root.deterministic_ranking_authorized IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,deterministic_ranking_authorized}')::boolean
    OR root.final_portfolio_weight_authorized IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,final_portfolio_weight_authorized}')::boolean
    OR root.automatic_brokerage_execution_authorized IS DISTINCT FROM
       (root.canonical_payload#>>'{assessment,automatic_brokerage_execution_authorized}')::boolean
    OR root.automatic_brokerage_execution_authorized IS DISTINCT FROM
       (root.canonical_payload#>>'{investment_view,automatic_brokerage_execution_authorized}')::boolean
    OR root.final_portfolio_weight_authorized IS DISTINCT FROM
       (root.canonical_payload#>>'{investment_view,final_portfolio_weight_authorized}')::boolean
  THEN RAISE EXCEPTION 'Current assessment root projection drift'; END IF;

  SELECT count(*) INTO bad FROM analytics.evidence_completed_session_v1 s
  WHERE s.id=root.completed_session_id AND s.session_content_hash=root.completed_session_hash
    AND s.session_date=root.price_session_date AND s.mic=root.mic
    AND s.completed_at<=root.decision_cutoff;
  IF bad<>1 THEN RAISE EXCEPTION 'Current assessment completed-session drift'; END IF;

  SELECT count(*) INTO bad
  FROM analytics.model_applicability_routing_v1 r
  JOIN analytics.canonical_evidence_v1 ce ON ce.evidence_id=r.classification_evidence_id
  JOIN analytics.evidence_selection_request_v1 q ON q.request_id=root.classification_request_id
  JOIN analytics.evidence_selector_policy_v1 p ON p.id=q.policy_id
  JOIN analytics.evidence_selection_result_v1 sr ON sr.request_id=q.request_id
  WHERE r.routing_id=root.classification_routing_id
    AND r.routing_content_hash=root.classification_routing_hash
    AND r.company_id=root.company_id AND r.classification_evidence_id=root.classification_evidence_id
    AND r.model_family='FUNDAMENTAL_VALUE'
    AND r.company_type='MATURE_OPERATING_COMPANY' AND r.applicability='APPLICABLE'
    AND r.routing_version='FV-CURRENT-APPLICABILITY-ROUTING-v1.0.0'
    AND q.request_content_hash=root.classification_request_hash
    AND q.security_id=root.security_id AND q.company_id=root.company_id
    AND q.instrument_id=root.instrument_id AND q.share_class_id=root.share_class_id
    AND q.listing_id=root.listing_id AND q.ticker_assignment_id=root.ticker_assignment_id
    AND q.completed_session_id=root.completed_session_id
    AND q.decision_cutoff=root.decision_cutoff AND q.sealed_ingestion_cutoff=root.decision_cutoff
    AND p.policy_content_hash=root.classification_policy_hash
    AND sr.result_content_hash=root.classification_result_hash
    AND sr.state='VALID' AND sr.selected_evidence_id=root.classification_evidence_id
    AND ce.domain='CLASSIFICATION' AND ce.state='VALID'
    AND ce.normalized_record_hash=root.classification_evidence_hash
    AND ce.raw_manifest_id=(SELECT raw_manifest_id FROM analytics.fv_current_assessment_source_v1
      WHERE assessment_id=target AND source_ordinal=1)
    AND ce.strictness_class='STRICT_IDENTITY_AND_CHRONOLOGY' AND ce.claim_class='CURRENT_ONLY';
  IF bad<>1 THEN RAISE EXCEPTION 'Current assessment classification/routing drift'; END IF;

  SELECT count(*) INTO bad
  FROM analytics.evidence_selection_request_v1 q
  JOIN analytics.evidence_selector_policy_v1 p ON p.id=q.policy_id
  JOIN analytics.evidence_selection_result_v1 sr ON sr.request_id=q.request_id
  JOIN analytics.canonical_evidence_v1 ce ON ce.evidence_id=sr.selected_evidence_id
  WHERE q.request_id=root.price_request_id AND q.request_content_hash=root.price_request_hash
    AND q.security_id=root.security_id AND q.company_id=root.company_id
    AND q.instrument_id=root.instrument_id AND q.share_class_id=root.share_class_id
    AND q.listing_id=root.listing_id AND q.ticker_assignment_id=root.ticker_assignment_id
    AND q.completed_session_id=root.completed_session_id
    AND q.decision_cutoff=root.decision_cutoff AND q.sealed_ingestion_cutoff=root.decision_cutoff
    AND p.policy_content_hash=root.price_policy_hash
    AND sr.result_content_hash=root.price_result_hash AND sr.state='VALID'
    AND sr.selected_evidence_id=root.price_evidence_id
    AND ce.domain='DAILY_PRICE' AND ce.state='VALID'
    AND ce.normalized_record_hash=root.price_evidence_hash
    AND ce.raw_manifest_id=(SELECT raw_manifest_id FROM analytics.fv_current_assessment_source_v1
      WHERE assessment_id=target AND source_ordinal=2)
    AND ce.strictness_class='STRICT_IDENTITY_AND_CHRONOLOGY' AND ce.claim_class='CURRENT_ONLY';
  IF bad<>1 THEN RAISE EXCEPTION 'Current assessment price-selection drift'; END IF;

  SELECT count(*) INTO bad
  FROM analytics.fv_current_assessment_source_v1 s
  WHERE s.assessment_id=target AND (
    s.raw_manifest_id::text IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'raw_manifest_id']
    OR s.provider_code IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'provider_code']
    OR s.schema_version IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'schema_version']
    OR s.source_reference IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'source_reference']
    OR s.file_sha256 IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'file_sha256']
    OR s.source_content_hash IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'source_content_hash']
    OR s.normalized_record_hash IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'normalized_record_hash']
    OR s.normalized_record_hash IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'content_hash']
    OR s.available_at IS DISTINCT FROM
      (root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'available_at'])::timestamptz
    OR s.retrieved_at IS DISTINCT FROM
      (root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'retrieved_at'])::timestamptz
    OR s.ingested_at IS DISTINCT FROM
      (root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'ingested_at'])::timestamptz
    OR s.source_revision IS DISTINCT FROM
      (root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'source_revision'])::integer
    OR s.adapter_version IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'adapter_version']
    OR s.normalization_version IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'normalization_version']
    OR s.freshness_policy_version IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'freshness_policy_version']
    OR s.source_record_id::text IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'source_record_id']
    OR s.request_identity IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'request_identity']
    OR s.plan_hash IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'plan_hash']
    OR s.checkpoint_reference IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['source_seals',(s.source_ordinal-1)::text,'checkpoint_reference']);
  IF bad<>0 THEN RAISE EXCEPTION 'Current assessment source payload projection drift'; END IF;

  SELECT count(*) INTO bad FROM analytics.fv_current_assessment_source_v1 s
  JOIN analytics.evidence_raw_manifest_v1 rm ON rm.id=s.raw_manifest_id
  WHERE s.assessment_id=target AND (
    rm.provider_code<>s.provider_code OR rm.provider_schema_version<>s.schema_version
    OR rm.source_record_id<>s.source_record_id::text OR rm.source_revision<>s.source_revision
    OR rm.source_content_hash<>s.source_content_hash OR rm.available_at<>s.available_at
    OR rm.ingested_at<>s.ingested_at OR rm.retrieved_at IS DISTINCT FROM s.retrieved_at);
  IF bad<>0 THEN RAISE EXCEPTION 'Current assessment raw source drift'; END IF;

  SELECT count(*) INTO bad
  FROM analytics.fv_current_assessment_source_v1 s
  JOIN analytics.canonical_evidence_v1 ce ON ce.raw_manifest_id=s.raw_manifest_id
  WHERE s.assessment_id=target
    AND ((s.source_ordinal=1 AND ce.evidence_id=root.classification_evidence_id)
      OR (s.source_ordinal=2 AND ce.evidence_id=root.price_evidence_id))
    AND (ce.provider_code<>s.provider_code
      OR ce.provider_schema_version<>s.schema_version
      OR ce.adapter_version<>s.adapter_version
      OR ce.source_record_id<>s.source_record_id::text
      OR ce.source_revision<>s.source_revision
      OR ce.source_content_hash<>s.source_content_hash
      OR ce.available_at<>s.available_at
      OR ce.ingested_at<>s.ingested_at
      OR ce.retrieved_at IS DISTINCT FROM s.retrieved_at);
  IF bad<>0 THEN RAISE EXCEPTION 'Current assessment selected source lineage drift'; END IF;

  SELECT count(*) INTO bad
  FROM analytics.fv_current_assessment_operand_v1 o
  JOIN analytics.canonical_evidence_v1 ce ON ce.evidence_id=root.price_evidence_id
  WHERE o.assessment_id=target AND o.operand_code='reference_price'
    AND o.numeric_value IS DISTINCT FROM (ce.canonical_data->>'close')::numeric;
  IF bad<>0 THEN RAISE EXCEPTION 'Current assessment reference-price evidence drift'; END IF;

  SELECT count(*) INTO bad
  FROM analytics.fv_current_assessment_operand_parent_v1 parent
  JOIN analytics.fv_current_assessment_operand_v1 operand
    ON operand.assessment_id=parent.assessment_id
   AND operand.operand_ordinal=parent.operand_ordinal
  WHERE parent.assessment_id=target AND (
    (operand.operand_code='reference_price' AND parent.source_ordinal<>2)
    OR (operand.operand_code<>'reference_price' AND parent.source_ordinal<>1));
  IF bad<>0 THEN RAISE EXCEPTION 'Current assessment operand source binding drift'; END IF;

  SELECT count(*) INTO bad
  FROM analytics.fv_current_assessment_operand_v1 o
  WHERE o.assessment_id=target AND (
    jsonb_typeof(root.canonical_payload#>ARRAY[
      'input_evidence',(o.operand_ordinal-1)::text,'source_parent_ids'])
      IS DISTINCT FROM 'array'
    OR jsonb_typeof(root.canonical_payload#>ARRAY[
      'input_evidence',(o.operand_ordinal-1)::text,'reason_codes'])
      IS DISTINCT FROM 'array'
    OR o.parent_count IS DISTINCT FROM jsonb_array_length(
      root.canonical_payload#>ARRAY[
        'input_evidence',(o.operand_ordinal-1)::text,'source_parent_ids'])
    OR o.reason_count IS DISTINCT FROM jsonb_array_length(
      root.canonical_payload#>ARRAY[
        'input_evidence',(o.operand_ordinal-1)::text,'reason_codes'])
    OR
    o.numeric_value IS DISTINCT FROM
      (root.canonical_payload#>>ARRAY['input_evidence',(o.operand_ordinal-1)::text,'value'])::numeric
    OR o.operand_code IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['input_evidence',(o.operand_ordinal-1)::text,'operand_code']
    OR o.state IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['input_evidence',(o.operand_ordinal-1)::text,'state']
    OR o.evidence_kind IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['input_evidence',(o.operand_ordinal-1)::text,'evidence_kind']
    OR o.source_roles IS DISTINCT FROM
      root.canonical_payload#>ARRAY['input_evidence',(o.operand_ordinal-1)::text,'source_roles']
    OR o.producer_contract_hash IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['input_evidence',(o.operand_ordinal-1)::text,'producer_contract_hash']
    OR o.output_content_hash IS DISTINCT FROM
      root.canonical_payload#>>ARRAY['input_evidence',(o.operand_ordinal-1)::text,'output_content_hash']);
  IF bad<>0 THEN RAISE EXCEPTION 'Current assessment operand payload projection drift'; END IF;

  SELECT count(*) INTO bad
  FROM analytics.fv_current_assessment_operand_parent_v1 parent
  WHERE parent.assessment_id=target AND parent.raw_manifest_id::text IS DISTINCT FROM
    root.canonical_payload#>>ARRAY['input_evidence',(parent.operand_ordinal-1)::text,
      'source_parent_ids',(parent.parent_ordinal-1)::text];
  IF bad<>0 THEN RAISE EXCEPTION 'Current assessment parent payload projection drift'; END IF;

  SELECT count(*) INTO bad
  FROM analytics.fv_current_assessment_operand_reason_v1 reason
  WHERE reason.assessment_id=target AND reason.reason_code IS DISTINCT FROM
    root.canonical_payload#>>ARRAY['input_evidence',(reason.operand_ordinal-1)::text,
      'reason_codes',(reason.reason_ordinal-1)::text];
  IF bad<>0 THEN RAISE EXCEPTION 'Current assessment reason payload projection drift'; END IF;

  SELECT count(*) INTO bad
  FROM analytics.fv_current_assessment_operand_v1 o
  JOIN analytics.fv_current_producer_contract_v1 p
    ON p.operand_code=o.operand_code AND p.producer_contract_hash=o.producer_contract_hash
  WHERE o.assessment_id=target AND (o.operand_ordinal<>p.operand_ordinal
    OR o.evidence_kind<>p.evidence_kind OR o.source_roles<>p.source_roles);
  IF bad<>0 THEN RAISE EXCEPTION 'Current assessment producer contract drift'; END IF;
  SELECT count(*) INTO bad
  FROM analytics.fv_current_assessment_operand_v1 o
  WHERE o.assessment_id=target AND NOT (
    (o.operand_code='terminal_growth_rate' AND o.state='VALID'
      AND o.numeric_value IS NOT NULL AND o.parent_count=0 AND o.reason_count=0)
    OR (o.operand_code='debt_maturity_schedule' AND o.state='MISSING'
      AND o.numeric_value IS NULL AND o.parent_count=0 AND o.reason_count=1
      AND EXISTS (SELECT 1
        FROM analytics.fv_current_assessment_operand_reason_v1 reason
        WHERE reason.assessment_id=o.assessment_id
          AND reason.operand_ordinal=o.operand_ordinal
          AND reason.reason_ordinal=1
          AND reason.reason_code='DEBT_MATURITY_SCHEDULE_NOT_AVAILABLE'))
    OR (o.operand_code NOT IN ('terminal_growth_rate','debt_maturity_schedule')
      AND o.state='VALID' AND o.numeric_value IS NOT NULL
      AND o.parent_count=1 AND o.reason_count=0));
  IF bad<>0 THEN RAISE EXCEPTION 'Current assessment frozen operand state drift'; END IF;
  IF EXISTS (SELECT 1 FROM analytics.fv_current_assessment_operand_v1 o
    WHERE o.assessment_id=target AND o.parent_count<>(SELECT count(*)
      FROM analytics.fv_current_assessment_operand_parent_v1 x
      WHERE x.assessment_id=target AND x.operand_ordinal=o.operand_ordinal))
    OR EXISTS (SELECT 1 FROM analytics.fv_current_assessment_operand_v1 o
    WHERE o.assessment_id=target AND o.reason_count<>(SELECT count(*)
      FROM analytics.fv_current_assessment_operand_reason_v1 x
      WHERE x.assessment_id=target AND x.operand_ordinal=o.operand_ordinal)) THEN
    RAISE EXCEPTION 'Current assessment operand child cardinality drift';
  END IF;
  RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER tr_validate_fv_current_root_v1 AFTER INSERT ON analytics.fv_current_assessment_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analytics.validate_fv_current_assessment_complete_v1();
CREATE CONSTRAINT TRIGGER tr_validate_fv_current_source_v1 AFTER INSERT ON analytics.fv_current_assessment_source_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analytics.validate_fv_current_assessment_complete_v1();
CREATE CONSTRAINT TRIGGER tr_validate_fv_current_operand_v1 AFTER INSERT ON analytics.fv_current_assessment_operand_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analytics.validate_fv_current_assessment_complete_v1();
CREATE CONSTRAINT TRIGGER tr_validate_fv_current_parent_v1 AFTER INSERT ON analytics.fv_current_assessment_operand_parent_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analytics.validate_fv_current_assessment_complete_v1();
CREATE CONSTRAINT TRIGGER tr_validate_fv_current_reason_v1 AFTER INSERT ON analytics.fv_current_assessment_operand_reason_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analytics.validate_fv_current_assessment_complete_v1();
CREATE CONSTRAINT TRIGGER tr_validate_fv_current_seal_v1 AFTER INSERT ON analytics.fv_current_assessment_seal_v1
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analytics.validate_fv_current_assessment_complete_v1();

CREATE TRIGGER tr_fv_current_producer_immutable_v1 BEFORE UPDATE OR DELETE ON analytics.fv_current_producer_contract_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_fv_current_authority_immutable_v1 BEFORE UPDATE OR DELETE ON analytics.fv_current_assessment_authority_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_fv_current_root_immutable_v1 BEFORE UPDATE OR DELETE ON analytics.fv_current_assessment_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_fv_current_source_immutable_v1 BEFORE UPDATE OR DELETE ON analytics.fv_current_assessment_source_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_fv_current_operand_immutable_v1 BEFORE UPDATE OR DELETE ON analytics.fv_current_assessment_operand_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_fv_current_parent_immutable_v1 BEFORE UPDATE OR DELETE ON analytics.fv_current_assessment_operand_parent_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_fv_current_reason_immutable_v1 BEFORE UPDATE OR DELETE ON analytics.fv_current_assessment_operand_reason_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();
CREATE TRIGGER tr_fv_current_seal_immutable_v1 BEFORE UPDATE OR DELETE ON analytics.fv_current_assessment_seal_v1
FOR EACH ROW EXECUTE FUNCTION app.reject_immutable_change();

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='analytics_fv_current_assessment_authority_writer_v1') THEN
    CREATE ROLE analytics_fv_current_assessment_authority_writer_v1 NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='analytics_fv_current_assessment_writer_v1') THEN
    CREATE ROLE analytics_fv_current_assessment_writer_v1 NOLOGIN;
  END IF;
END $$;

GRANT USAGE ON SCHEMA analytics TO analytics_fv_current_assessment_authority_writer_v1;
GRANT USAGE ON SCHEMA analytics TO analytics_fv_current_assessment_writer_v1;
REVOKE ALL ON analytics.fv_current_producer_contract_v1,
 analytics.fv_current_assessment_authority_v1,
 analytics.fv_current_assessment_v1,analytics.fv_current_assessment_source_v1,
 analytics.fv_current_assessment_operand_v1,analytics.fv_current_assessment_operand_parent_v1,
 analytics.fv_current_assessment_operand_reason_v1,analytics.fv_current_assessment_seal_v1 FROM PUBLIC;
GRANT SELECT,INSERT ON analytics.fv_current_assessment_authority_v1
 TO analytics_fv_current_assessment_authority_writer_v1;
REVOKE UPDATE,DELETE,TRUNCATE ON analytics.fv_current_assessment_authority_v1
 FROM analytics_fv_current_assessment_authority_writer_v1;
GRANT SELECT ON analytics.fv_identity_authority_v2
 TO analytics_fv_current_assessment_authority_writer_v1;
GRANT SELECT ON analytics.fv_current_producer_contract_v1,
 analytics.fv_current_assessment_authority_v1
 TO analytics_fv_current_assessment_writer_v1;
GRANT SELECT,INSERT ON analytics.fv_current_assessment_v1,
 analytics.fv_current_assessment_source_v1,analytics.fv_current_assessment_operand_v1,
 analytics.fv_current_assessment_operand_parent_v1,
 analytics.fv_current_assessment_operand_reason_v1,
 analytics.fv_current_assessment_seal_v1 TO analytics_fv_current_assessment_writer_v1;
GRANT SELECT ON analytics.security,analytics.evidence_company_identity_v1,
 analytics.evidence_instrument_identity_v1,analytics.evidence_share_class_identity_v1,
 analytics.evidence_listing_identity_v1,analytics.evidence_ticker_assignment_v1,
 analytics.evidence_completed_session_v1,analytics.evidence_raw_manifest_v1,
 analytics.canonical_evidence_v1,analytics.evidence_selector_policy_v1,
 analytics.evidence_selection_request_v1,analytics.evidence_selection_result_v1,
 analytics.model_applicability_routing_v1,analytics.fv_identity_authority_v2,
 analytics.fv_identity_authority_member_v2 TO analytics_fv_current_assessment_writer_v1;
GRANT SELECT ON analytics.fv_current_producer_contract_v1,
 analytics.fv_current_assessment_authority_v1,
 analytics.fv_current_assessment_v1,analytics.fv_current_assessment_source_v1,
 analytics.fv_current_assessment_operand_v1,analytics.fv_current_assessment_operand_parent_v1,
 analytics.fv_current_assessment_operand_reason_v1,analytics.fv_current_assessment_seal_v1
 TO analytics_reader;
GRANT analytics_fv_current_assessment_writer_v1
 TO analytics_fundamental_value_writer_v1;
REVOKE analytics_fv_current_assessment_authority_writer_v1
 FROM analytics_fundamental_value_writer_v1;

COMMENT ON TABLE analytics.fv_current_assessment_v1 IS
 'Immutable current-revision Fundamental Value research assessment. NOT_VALIDATED and no trade authority.';
