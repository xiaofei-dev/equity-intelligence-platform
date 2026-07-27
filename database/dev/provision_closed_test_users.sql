\set ON_ERROR_STOP on

\if :{?first_subject}
\else
\echo 'Required variable missing: first_subject'
\quit
\endif

\if :{?second_subject}
\else
\echo 'Required variable missing: second_subject'
\quit
\endif

\if :{?issuer}
\else
\set issuer 'equity-local'
\endif

WITH first_user AS (
    INSERT INTO app.user_account (display_name, locale, time_zone)
    VALUES ('Closed Tester One', 'en-US', 'America/Phoenix')
    RETURNING id
)
INSERT INTO app.authentication_identity (
    user_id, provider, issuer, subject
)
SELECT id, 'LOCAL_TEST', :'issuer', :'first_subject'
FROM first_user;

WITH second_user AS (
    INSERT INTO app.user_account (display_name, locale, time_zone)
    VALUES ('Closed Tester Two', 'en-US', 'America/Phoenix')
    RETURNING id
)
INSERT INTO app.authentication_identity (
    user_id, provider, issuer, subject
)
SELECT id, 'LOCAL_TEST', :'issuer', :'second_subject'
FROM second_user;

\echo 'Provisioned two closed-test users and LOCAL_TEST identities.'
