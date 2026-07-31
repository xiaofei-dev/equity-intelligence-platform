\set ON_ERROR_STOP on

DO $$
DECLARE
    preserved_count INTEGER;
BEGIN
    SELECT
        (
            SELECT COUNT(*)
            FROM app.portfolio_decision_plan_v1
            WHERE id = '22100000-0000-4000-8000-000000000004'
              AND request_hash = 'sha256:' || repeat('1', 64)
              AND content_hash = 'sha256:' || repeat('2', 64)
        )
        + (
            SELECT COUNT(*)
            FROM app.portfolio_sleeve_policy_v1
            WHERE id = '22100000-0000-4000-8000-000000000005'
              AND policy_hash = 'sha256:' || repeat('3', 64)
        )
        + (
            SELECT COUNT(*)
            FROM app.portfolio_sleeve_evidence_binding_v1
            WHERE id = '22100000-0000-4000-8000-000000000006'
              AND evidence_content_hash = 'sha256:' || repeat('4', 64)
        )
        + (
            SELECT COUNT(*)
            FROM app.portfolio_sleeve_pnl_binding_v1
            WHERE id = '22100000-0000-4000-8000-000000000007'
              AND pnl_content_hash = 'sha256:' || repeat('5', 64)
        )
        + (
            SELECT COUNT(*)
            FROM app.suggested_order_v1
            WHERE id = '22100000-0000-4000-8000-000000000008'
              AND content_hash = 'sha256:' || repeat('6', 64)
              AND execution_status = 'NOT_EXECUTED'
        )
    INTO preserved_count;

    IF preserved_count <> 5 THEN
        RAISE EXCEPTION 'V22 changed legacy V21 rows or hashes';
    END IF;
END;
$$;
