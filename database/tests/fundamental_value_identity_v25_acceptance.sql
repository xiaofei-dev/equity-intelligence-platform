\set ON_ERROR_STOP on

DO $$
BEGIN
    IF to_regclass('analytics.fv_identity_authority_v2') IS NULL
       OR to_regclass('analytics.fv_identity_authority_member_v2') IS NULL
       OR to_regclass('analytics.fv_identity_authority_seal_v2') IS NULL THEN
        RAISE EXCEPTION 'V25 identity-authority tables are missing';
    END IF;
END;
$$;

BEGIN;

SELECT public_id AS msft_public_id,
       '25000000-0000-4000-8000-000000000302'::uuid AS msft_company_id,
       '25000000-0000-4000-8000-000000000303'::uuid AS msft_instrument_id,
       '25000000-0000-4000-8000-000000000304'::uuid AS msft_share_class_id,
       '25000000-0000-4000-8000-000000000305'::uuid AS msft_listing_id,
       '25000000-0000-4000-8000-000000000306'::uuid AS msft_ticker_assignment_id
FROM analytics.security
WHERE symbol='MSFT'
\gset

INSERT INTO analytics.security (
    public_id, symbol, exchange, name, instrument_type, currency, active
) VALUES
    ('25000000-0000-4000-8000-000000000101','GOOG','XNAS','Alphabet Inc.',
     'COMMON_STOCK','USD',true),
    ('25000000-0000-4000-8000-000000000201','FOX','XNAS','Fox Corp',
     'COMMON_STOCK','USD',true);

INSERT INTO analytics.fv_identity_authority_v2 (
    authority_id,contract_version,authority_version,registry_version,
    inventory_as_of_date,evidence_claim,model_evidence_label,
    openfigi_result_hash,openfigi_review_hash,sec_result_hash,
    sec_acceptance_hash,sec_review_hash,inventory_authorization_hash,
    inventory_review_hash,inventory_receipt_hash,projection_content_hash,
    member_set_hash,member_count,v22_write_authorized,
    v24_enrollment_authorized,investment_assessment_authorized,
    evidence_label_upgrade_authorized,idempotency_key,revision,
    supersedes_authority_id
) VALUES (
    '25000000-0000-4000-8000-000000000001',
    'FV-STAGE8C-FORWARD-IDENTITY-PROJECTION-v2.0.0',
    'FV-STAGE8C-IDENTITY-AUTHORITY-v1.0.0',
    'security-identity-registry-v1.0.0',DATE '2026-08-02',
    'ENGINEERING_IDENTITY_AUTHORITY_ONLY','NOT_VALIDATED',
    'AD83ACD175AFA01D706D689EE48B93233BB8D95D6B494655B7E15337B5FDC6B7',
    'E53CF93A88523B8F91F5F84AB59FD230F5335E218970B87FB77321BF1AA57747',
    '826041EEBFFF3C135DBC6C5154E3CB7F8F0B0D9F6FBCB797549DF1A57DB50050',
    'FF4286FBC31CB413BF92C3ECBBDC618F7913E80622CC211A4B46E8A16EFB169A',
    '8060C22C1D911BF6108A9AD0BB407EED80B81CE6E2089C45AF4F3A19398E4745',
    '6AC4E9A95F727AA6D96850771F52A610662D0C96DBDF8C56D1CFFFC97DDE2C3D',
    '8AC0DC15E6D0FABC89C2F42DC1D7D929F0AF54C6FB4F37803849F81740ED5FCE',
    'F1BEDECEE6343F4CC7D0F4C674066C75F44EE6DA979C61EB799B4D068667776B',
    'sha256:1111111111111111111111111111111111111111111111111111111111111111',
    'sha256:2222222222222222222222222222222222222222222222222222222222222222',
    3,true,false,false,false,'FV-STAGE8C-V25-ACCEPTANCE-001',1,NULL
);

INSERT INTO analytics.fv_identity_authority_member_v2 (
    authority_id,member_ordinal,ticker,security_id,company_id,instrument_id,
    share_class_id,listing_id,ticker_assignment_id,adoption_state,
    existing_public_id,company_name,sec_cik,mic,currency,instrument_type,
    ticker_valid_from,isin,cusip,figi,composite_figi,share_class_figi,
    openfigi_provider_identity_hash,openfigi_source_hash,sec_source_hash,
    inventory_decision_hash,member_content_hash
) VALUES
    ('25000000-0000-4000-8000-000000000001',1,'GOOG',
     '25000000-0000-4000-8000-000000000101',
     '25000000-0000-4000-8000-000000000102',
     '25000000-0000-4000-8000-000000000103',
     '25000000-0000-4000-8000-000000000104',
     '25000000-0000-4000-8000-000000000105',
     '25000000-0000-4000-8000-000000000106','NEW_ID_CANDIDATE',NULL,
     'Alphabet Inc.','1652044','XNAS','USD','COMMON_STOCK',DATE '2026-08-02',
     'US02079K1079','02079K107','BBG009S3NB30','BBG009S3NB30','BBG009S3NB21',
     repeat('A',64),'sha256:'||repeat('a',64),'sha256:'||repeat('b',64),
     'sha256:'||repeat('c',64),'sha256:'||repeat('d',64)),
    ('25000000-0000-4000-8000-000000000001',2,'FOX',
     '25000000-0000-4000-8000-000000000201',
     '25000000-0000-4000-8000-000000000202',
     '25000000-0000-4000-8000-000000000203',
     '25000000-0000-4000-8000-000000000204',
     '25000000-0000-4000-8000-000000000205',
     '25000000-0000-4000-8000-000000000206','NEW_ID_CANDIDATE',NULL,
     'Fox Corp','1754301','XNAS','USD','COMMON_STOCK',DATE '2026-08-02',
     'US35137L2043','35137L204','BBG00JHNKJY8','BBG00JHNKJY8','BBG00JHNKKR3',
     repeat('B',64),'sha256:'||repeat('e',64),'sha256:'||repeat('f',64),
     'sha256:'||repeat('0',64),'sha256:'||repeat('1',64)),
    ('25000000-0000-4000-8000-000000000001',3,'MSFT',
     :'msft_public_id',
     :'msft_company_id',:'msft_instrument_id',:'msft_share_class_id',
     :'msft_listing_id',:'msft_ticker_assignment_id',
     'ADOPT_EXISTING_PUBLIC_ID_V22_GRAPH_REQUIRED',
     :'msft_public_id','Microsoft Corporation','789019',
     'XNAS','USD','COMMON_STOCK',DATE '2026-08-02','US5949181045','594918104',
     'BBG000BPH459','BBG000BPH459','BBG001S5TD05',repeat('C',64),
     'sha256:'||repeat('2',64),'sha256:'||repeat('3',64),
     'sha256:'||repeat('4',64),'sha256:'||repeat('5',64));

INSERT INTO analytics.evidence_company_identity_v1 VALUES
    ('25000000-0000-4000-8000-000000000102','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP),
    ('25000000-0000-4000-8000-000000000202','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP),
    (:'msft_company_id','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP)
ON CONFLICT DO NOTHING;
INSERT INTO analytics.evidence_instrument_identity_v1 VALUES
    ('25000000-0000-4000-8000-000000000103','25000000-0000-4000-8000-000000000102','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP),
    ('25000000-0000-4000-8000-000000000203','25000000-0000-4000-8000-000000000202','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP),
    (:'msft_instrument_id',:'msft_company_id','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP)
ON CONFLICT DO NOTHING;
INSERT INTO analytics.evidence_share_class_identity_v1 VALUES
    ('25000000-0000-4000-8000-000000000104','25000000-0000-4000-8000-000000000103','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP),
    ('25000000-0000-4000-8000-000000000204','25000000-0000-4000-8000-000000000203','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP),
    (:'msft_share_class_id',:'msft_instrument_id','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP)
ON CONFLICT DO NOTHING;
INSERT INTO analytics.evidence_listing_identity_v1 VALUES
    ('25000000-0000-4000-8000-000000000105','25000000-0000-4000-8000-000000000104','25000000-0000-4000-8000-000000000101','XNAS','USD','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP),
    ('25000000-0000-4000-8000-000000000205','25000000-0000-4000-8000-000000000204','25000000-0000-4000-8000-000000000201','XNAS','USD','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP),
    (:'msft_listing_id',:'msft_share_class_id',:'msft_public_id','XNAS','USD','security-identity-registry-v1.0.0',CURRENT_TIMESTAMP)
ON CONFLICT DO NOTHING;
INSERT INTO analytics.evidence_ticker_assignment_v1 VALUES
    ('25000000-0000-4000-8000-000000000106','25000000-0000-4000-8000-000000000105','GOOG',DATE '2026-08-02',NULL,'security-identity-registry-v1.0.0',CURRENT_TIMESTAMP),
    ('25000000-0000-4000-8000-000000000206','25000000-0000-4000-8000-000000000205','FOX',DATE '2026-08-02',NULL,'security-identity-registry-v1.0.0',CURRENT_TIMESTAMP)
ON CONFLICT DO NOTHING;
INSERT INTO analytics.evidence_ticker_assignment_v1
  (ticker_assignment_id,listing_id,ticker,valid_from,valid_to,registry_version,
   recorded_at)
SELECT :'msft_ticker_assignment_id',:'msft_listing_id','MSFT',DATE '2026-08-02',
       NULL,'security-identity-registry-v1.0.0',CURRENT_TIMESTAMP
WHERE NOT EXISTS (
  SELECT 1 FROM analytics.evidence_ticker_assignment_v1
  WHERE ticker_assignment_id=:'msft_ticker_assignment_id'
);

INSERT INTO analytics.fv_identity_authority_seal_v2 (
    authority_id,projection_content_hash,member_set_hash,member_count,
    seal_content_hash,creator_xid8
) VALUES (
    '25000000-0000-4000-8000-000000000001',
    'sha256:'||repeat('1',64),'sha256:'||repeat('2',64),3,
    'sha256:'||repeat('6',64),'1'::xid8
);

COMMIT;

DO $$
DECLARE
    count_members INTEGER;
    stored_creator xid8;
BEGIN
    SELECT count(*) INTO count_members
    FROM analytics.fv_identity_authority_member_v2
    WHERE authority_id='25000000-0000-4000-8000-000000000001';
    SELECT creator_xid8 INTO stored_creator
    FROM analytics.fv_identity_authority_seal_v2
    WHERE authority_id='25000000-0000-4000-8000-000000000001';
    IF count_members <> 3 OR stored_creator = '1'::xid8 THEN
        RAISE EXCEPTION 'V25 representative identity authority did not seal';
    END IF;
END;
$$;

DO $$
BEGIN
    BEGIN
        UPDATE analytics.fv_identity_authority_v2
        SET evidence_claim='ALTERED'
        WHERE authority_id='25000000-0000-4000-8000-000000000001';
        RAISE EXCEPTION 'V25 authority update unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM NOT LIKE '%append-only%' THEN RAISE; END IF;
    END;
    BEGIN
        DELETE FROM analytics.fv_identity_authority_member_v2
        WHERE authority_id='25000000-0000-4000-8000-000000000001'
          AND member_ordinal=1;
        RAISE EXCEPTION 'V25 member delete unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM NOT LIKE '%append-only%' THEN RAISE; END IF;
    END;
    BEGIN
        INSERT INTO analytics.fv_identity_authority_member_v2
        SELECT member.* FROM analytics.fv_identity_authority_member_v2 member
        WHERE false;
        RAISE EXCEPTION 'sentinel';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM <> 'sentinel' THEN RAISE; END IF;
    END;
END;
$$;

SELECT 'Fundamental Value identity V25 acceptance passed.' AS acceptance_result;
