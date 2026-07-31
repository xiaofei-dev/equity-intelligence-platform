DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM analytics.forward_dqv_enrollment_v2
    ) THEN
        RAISE EXCEPTION
            'V19 refuses to reinterpret existing Forward DQV v2.1.0 enrollments';
    END IF;
END;
$$;

ALTER TABLE analytics.forward_dqv_enrollment_v2
    DROP CONSTRAINT ck_forward_dqv_enrollment_contract,
    DROP CONSTRAINT ck_forward_dqv_enrollment_chronology;

ALTER TABLE analytics.forward_dqv_enrollment_v2
    ADD CONSTRAINT ck_forward_dqv_enrollment_contract CHECK (
        contract_version = 'FORWARD-DQV-ENROLLMENT-v2.1.1'
    ),
    ADD CONSTRAINT ck_forward_dqv_enrollment_chronology CHECK (
        decision_as_of <= sealed_at
        AND sealed_at <= effective_at_completed_session_open
    );

COMMENT ON TABLE analytics.forward_dqv_enrollment_v2 IS
    'Append-only prospective Forward DQV enrollment. V19 requires the decision '
    'and immutable seal to exist no later than the next completed-session open.';
