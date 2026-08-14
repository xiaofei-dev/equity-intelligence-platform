CREATE TABLE analytics.fv_identity_authority_v2 (
    authority_id UUID PRIMARY KEY,
    contract_version VARCHAR(128) NOT NULL,
    authority_version VARCHAR(128) NOT NULL,
    registry_version VARCHAR(128) NOT NULL,
    inventory_as_of_date DATE NOT NULL,
    evidence_claim VARCHAR(64) NOT NULL,
    model_evidence_label VARCHAR(32) NOT NULL,
    openfigi_result_hash CHAR(64) NOT NULL,
    openfigi_review_hash CHAR(64) NOT NULL,
    sec_result_hash CHAR(64) NOT NULL,
    sec_acceptance_hash CHAR(64) NOT NULL,
    sec_review_hash CHAR(64) NOT NULL,
    inventory_authorization_hash CHAR(64) NOT NULL,
    inventory_review_hash CHAR(64) NOT NULL,
    inventory_receipt_hash CHAR(64) NOT NULL,
    projection_content_hash VARCHAR(71) NOT NULL UNIQUE,
    member_set_hash VARCHAR(71) NOT NULL,
    member_count INTEGER NOT NULL,
    v22_write_authorized BOOLEAN NOT NULL,
    v24_enrollment_authorized BOOLEAN NOT NULL,
    investment_assessment_authorized BOOLEAN NOT NULL,
    evidence_label_upgrade_authorized BOOLEAN NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    revision INTEGER NOT NULL,
    supersedes_authority_id UUID,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_fv_identity_authority_v2_contract CHECK (
        contract_version = 'FV-STAGE8C-FORWARD-IDENTITY-PROJECTION-v2.0.0'
        AND authority_version = 'FV-STAGE8C-IDENTITY-AUTHORITY-v1.0.0'
        AND registry_version = 'security-identity-registry-v1.0.0'
        AND inventory_as_of_date = DATE '2026-08-02'
        AND evidence_claim = 'ENGINEERING_IDENTITY_AUTHORITY_ONLY'
        AND model_evidence_label = 'NOT_VALIDATED'
        AND member_count = 3
        AND v22_write_authorized
        AND NOT v24_enrollment_authorized
        AND NOT investment_assessment_authorized
        AND NOT evidence_label_upgrade_authorized
        AND revision = 1
        AND supersedes_authority_id IS NULL
    ),
    CONSTRAINT ck_fv_identity_authority_v2_accepted_evidence CHECK (
        openfigi_result_hash =
            'AD83ACD175AFA01D706D689EE48B93233BB8D95D6B494655B7E15337B5FDC6B7'
        AND openfigi_review_hash =
            'E53CF93A88523B8F91F5F84AB59FD230F5335E218970B87FB77321BF1AA57747'
        AND sec_result_hash =
            '826041EEBFFF3C135DBC6C5154E3CB7F8F0B0D9F6FBCB797549DF1A57DB50050'
        AND sec_acceptance_hash =
            'FF4286FBC31CB413BF92C3ECBBDC618F7913E80622CC211A4B46E8A16EFB169A'
        AND sec_review_hash =
            '8060C22C1D911BF6108A9AD0BB407EED80B81CE6E2089C45AF4F3A19398E4745'
        AND inventory_authorization_hash =
            '6AC4E9A95F727AA6D96850771F52A610662D0C96DBDF8C56D1CFFFC97DDE2C3D'
        AND inventory_review_hash =
            '8AC0DC15E6D0FABC89C2F42DC1D7D929F0AF54C6FB4F37803849F81740ED5FCE'
        AND inventory_receipt_hash =
            'F1BEDECEE6343F4CC7D0F4C674066C75F44EE6DA979C61EB799B4D068667776B'
    ),
    CONSTRAINT ck_fv_identity_authority_v2_hashes CHECK (
        projection_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND member_set_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_fv_identity_authority_v2_idempotency CHECK (
        idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'
    )
);

CREATE TABLE analytics.fv_identity_authority_member_v2 (
    authority_id UUID NOT NULL
        REFERENCES analytics.fv_identity_authority_v2 (authority_id),
    member_ordinal INTEGER NOT NULL,
    ticker VARCHAR(32) NOT NULL,
    security_id UUID NOT NULL,
    company_id UUID NOT NULL,
    instrument_id UUID NOT NULL,
    share_class_id UUID NOT NULL,
    listing_id UUID NOT NULL,
    ticker_assignment_id UUID NOT NULL,
    adoption_state VARCHAR(64) NOT NULL,
    existing_public_id UUID,
    company_name VARCHAR(255) NOT NULL,
    sec_cik VARCHAR(10) NOT NULL,
    mic CHAR(4) NOT NULL,
    currency CHAR(3) NOT NULL,
    instrument_type VARCHAR(32) NOT NULL,
    ticker_valid_from DATE NOT NULL,
    isin VARCHAR(12) NOT NULL,
    cusip VARCHAR(9) NOT NULL,
    figi VARCHAR(12) NOT NULL,
    composite_figi VARCHAR(12) NOT NULL,
    share_class_figi VARCHAR(12) NOT NULL,
    openfigi_provider_identity_hash CHAR(64) NOT NULL,
    openfigi_source_hash VARCHAR(71) NOT NULL,
    sec_source_hash VARCHAR(71) NOT NULL,
    inventory_decision_hash VARCHAR(71) NOT NULL,
    member_content_hash VARCHAR(71) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (authority_id, member_ordinal),
    UNIQUE (authority_id, ticker),
    UNIQUE (authority_id, security_id),
    UNIQUE (authority_id, listing_id),
    UNIQUE (authority_id, ticker_assignment_id),
    CONSTRAINT ck_fv_identity_authority_member_v2_ordinal
        CHECK (member_ordinal BETWEEN 1 AND 3),
    CONSTRAINT ck_fv_identity_authority_member_v2_identity CHECK (
        ticker ~ '^[A-Z][A-Z0-9.-]{0,31}$'
        AND sec_cik ~ '^[0-9]{1,10}$'
        AND mic = 'XNAS'
        AND currency = 'USD'
        AND instrument_type = 'COMMON_STOCK'
        AND ticker_valid_from = DATE '2026-08-02'
        AND figi ~ '^BBG[A-Z0-9]{9}$'
        AND composite_figi ~ '^BBG[A-Z0-9]{9}$'
        AND share_class_figi ~ '^BBG[A-Z0-9]{9}$'
        AND isin ~ '^[A-Z]{2}[A-Z0-9]{10}$'
        AND cusip ~ '^[A-Z0-9*@#]{9}$'
    ),
    CONSTRAINT ck_fv_identity_authority_member_v2_adoption CHECK (
        (ticker IN ('GOOG', 'FOX')
            AND adoption_state = 'NEW_ID_CANDIDATE'
            AND existing_public_id IS NULL)
        OR
        (ticker = 'MSFT'
            AND adoption_state =
                'ADOPT_EXISTING_PUBLIC_ID_V22_GRAPH_REQUIRED'
            AND existing_public_id = security_id
        )
    ),
    CONSTRAINT ck_fv_identity_authority_member_v2_hashes CHECK (
        openfigi_provider_identity_hash ~ '^[0-9A-F]{64}$'
        AND openfigi_source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND sec_source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND inventory_decision_hash ~ '^sha256:[0-9a-f]{64}$'
        AND member_content_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE TABLE analytics.fv_identity_authority_seal_v2 (
    authority_id UUID PRIMARY KEY
        REFERENCES analytics.fv_identity_authority_v2 (authority_id),
    projection_content_hash VARCHAR(71) NOT NULL UNIQUE,
    member_set_hash VARCHAR(71) NOT NULL,
    member_count INTEGER NOT NULL,
    seal_content_hash VARCHAR(71) NOT NULL UNIQUE,
    sealed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    creator_xid8 xid8 NOT NULL DEFAULT pg_current_xact_id(),
    CONSTRAINT ck_fv_identity_authority_seal_v2 CHECK (
        projection_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND member_set_hash ~ '^sha256:[0-9a-f]{64}$'
        AND seal_content_hash ~ '^sha256:[0-9a-f]{64}$'
        AND member_count = 3
    )
);

CREATE FUNCTION analytics.set_fv_identity_authority_seal_creator_xid8_v2()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.creator_xid8 := pg_current_xact_id();
    RETURN NEW;
END;
$$;

CREATE TRIGGER tr_set_fv_identity_authority_seal_creator_xid8_v2
BEFORE INSERT ON analytics.fv_identity_authority_seal_v2
FOR EACH ROW EXECUTE FUNCTION
    analytics.set_fv_identity_authority_seal_creator_xid8_v2();

CREATE FUNCTION analytics.reject_fv_identity_authority_change_v2()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Fundamental Value identity authority v2 is append-only';
END;
$$;

CREATE FUNCTION analytics.validate_fv_identity_authority_member_insert_v2()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM analytics.fv_identity_authority_seal_v2 seal
        WHERE seal.authority_id = NEW.authority_id
    ) THEN
        RAISE EXCEPTION 'Fundamental Value identity authority v2 is already sealed';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION analytics.validate_fv_identity_authority_complete_v2()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    target_id UUID := COALESCE(NEW.authority_id, OLD.authority_id);
    parent analytics.fv_identity_authority_v2%ROWTYPE;
    seal analytics.fv_identity_authority_seal_v2%ROWTYPE;
    member_count INTEGER;
    bad_graph_count INTEGER;
BEGIN
    SELECT * INTO parent
    FROM analytics.fv_identity_authority_v2
    WHERE authority_id = target_id;
    SELECT * INTO seal
    FROM analytics.fv_identity_authority_seal_v2
    WHERE authority_id = target_id;

    IF parent.authority_id IS NULL OR seal.authority_id IS NULL THEN
        RAISE EXCEPTION 'Fundamental Value identity authority v2 must be sealed';
    END IF;
    IF seal.creator_xid8 = pg_current_xact_id()
       AND TG_TABLE_NAME <> 'fv_identity_authority_v2' THEN
        RETURN NULL;
    END IF;

    SELECT count(*) INTO member_count
    FROM analytics.fv_identity_authority_member_v2 member
    WHERE member.authority_id = target_id;
    IF member_count <> 3
       OR seal.member_count <> member_count
       OR parent.member_count <> member_count
       OR seal.projection_content_hash <> parent.projection_content_hash
       OR seal.member_set_hash <> parent.member_set_hash THEN
        RAISE EXCEPTION 'Fundamental Value identity authority v2 cardinality or seal drift';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM analytics.fv_identity_authority_member_v2 member
        WHERE member.authority_id = target_id
        GROUP BY member.authority_id
        HAVING array_agg(member.ticker ORDER BY member.member_ordinal)
            = ARRAY['GOOG','FOX','MSFT']::VARCHAR[]
           AND array_agg(member.member_ordinal ORDER BY member.member_ordinal)
            = ARRAY[1,2,3]::INTEGER[]
    ) THEN
        RAISE EXCEPTION 'Fundamental Value identity authority v2 target set drift';
    END IF;

    SELECT count(*) INTO bad_graph_count
    FROM analytics.fv_identity_authority_member_v2 member
    LEFT JOIN analytics.security security
      ON security.public_id = member.security_id
    LEFT JOIN analytics.evidence_company_identity_v1 company
      ON company.company_id = member.company_id
    LEFT JOIN analytics.evidence_instrument_identity_v1 instrument
      ON instrument.instrument_id = member.instrument_id
     AND instrument.company_id = member.company_id
    LEFT JOIN analytics.evidence_share_class_identity_v1 share_class
      ON share_class.share_class_id = member.share_class_id
     AND share_class.instrument_id = member.instrument_id
    LEFT JOIN analytics.evidence_listing_identity_v1 listing
      ON listing.listing_id = member.listing_id
     AND listing.share_class_id = member.share_class_id
     AND listing.security_id = member.security_id
     AND listing.mic = member.mic
     AND listing.currency = member.currency
    LEFT JOIN analytics.evidence_ticker_assignment_v1 ticker
      ON ticker.ticker_assignment_id = member.ticker_assignment_id
     AND ticker.listing_id = member.listing_id
     AND ticker.ticker = member.ticker
     AND ticker.valid_from = member.ticker_valid_from
     AND ticker.valid_to IS NULL
    WHERE member.authority_id = target_id
      AND (
        security.id IS NULL
        OR security.symbol <> member.ticker
        OR security.exchange NOT IN ('NASDAQ','XNAS')
        OR security.instrument_type <> member.instrument_type
        OR security.currency <> member.currency
        OR NOT security.active
        OR company.company_id IS NULL
        OR company.registry_version <> parent.registry_version
        OR instrument.instrument_id IS NULL
        OR instrument.registry_version <> parent.registry_version
        OR share_class.share_class_id IS NULL
        OR share_class.registry_version <> parent.registry_version
        OR listing.listing_id IS NULL
        OR listing.registry_version <> parent.registry_version
        OR ticker.ticker_assignment_id IS NULL
        OR ticker.registry_version <> parent.registry_version
      );
    IF bad_graph_count <> 0 THEN
        RAISE EXCEPTION 'Fundamental Value identity authority v2 V22 graph mismatch';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER tr_validate_fv_identity_authority_member_insert_v2
BEFORE INSERT ON analytics.fv_identity_authority_member_v2
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_fv_identity_authority_member_insert_v2();

CREATE CONSTRAINT TRIGGER tr_validate_fv_identity_authority_header_v2
AFTER INSERT ON analytics.fv_identity_authority_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_fv_identity_authority_complete_v2();

CREATE CONSTRAINT TRIGGER tr_validate_fv_identity_authority_member_v2
AFTER INSERT ON analytics.fv_identity_authority_member_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_fv_identity_authority_complete_v2();

CREATE CONSTRAINT TRIGGER tr_validate_fv_identity_authority_seal_v2
AFTER INSERT ON analytics.fv_identity_authority_seal_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION
    analytics.validate_fv_identity_authority_complete_v2();

CREATE TRIGGER tr_fv_identity_authority_v2_append_only
BEFORE UPDATE OR DELETE ON analytics.fv_identity_authority_v2
FOR EACH ROW EXECUTE FUNCTION analytics.reject_fv_identity_authority_change_v2();

CREATE TRIGGER tr_fv_identity_authority_member_v2_append_only
BEFORE UPDATE OR DELETE ON analytics.fv_identity_authority_member_v2
FOR EACH ROW EXECUTE FUNCTION analytics.reject_fv_identity_authority_change_v2();

CREATE TRIGGER tr_fv_identity_authority_seal_v2_append_only
BEFORE UPDATE OR DELETE ON analytics.fv_identity_authority_seal_v2
FOR EACH ROW EXECUTE FUNCTION analytics.reject_fv_identity_authority_change_v2();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'analytics_fv_identity_authority_writer_v2'
    ) THEN
        CREATE ROLE analytics_fv_identity_authority_writer_v2 NOLOGIN;
    END IF;
END;
$$;

REVOKE ALL ON analytics.fv_identity_authority_v2,
    analytics.fv_identity_authority_member_v2,
    analytics.fv_identity_authority_seal_v2
FROM PUBLIC, analytics_writer;

GRANT SELECT, INSERT ON analytics.fv_identity_authority_v2,
    analytics.fv_identity_authority_member_v2,
    analytics.fv_identity_authority_seal_v2
TO analytics_fv_identity_authority_writer_v2;

GRANT SELECT, INSERT ON analytics.security,
    analytics.evidence_company_identity_v1,
    analytics.evidence_instrument_identity_v1,
    analytics.evidence_share_class_identity_v1,
    analytics.evidence_listing_identity_v1,
    analytics.evidence_ticker_assignment_v1
TO analytics_fv_identity_authority_writer_v2;

GRANT USAGE, SELECT ON SEQUENCE analytics.security_id_seq
TO analytics_fv_identity_authority_writer_v2;

GRANT SELECT ON analytics.fv_identity_authority_v2,
    analytics.fv_identity_authority_member_v2,
    analytics.fv_identity_authority_seal_v2
TO analytics_reader;

COMMENT ON TABLE analytics.fv_identity_authority_v2 IS
    'Append-only engineering identity authority for the governed Stage 8C projection v2. It does not authorize V24 enrollment, an investment assessment, or an evidence-label upgrade.';
