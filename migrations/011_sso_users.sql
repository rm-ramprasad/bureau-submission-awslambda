-- 011: sign-in moves to Cognito SSO (company identity provider). The app no longer holds passwords.
-- app_user stays the list of who may use the app (active flag, admin role), matched on the e-mail address
-- from the company identity. Manage with: python -m submissions.users add|disable|enable|list

ALTER TABLE app_user
    ADD COLUMN email VARCHAR(254) NULL AFTER display_name,
    DROP COLUMN password_hash,
    DROP COLUMN failed_attempts,
    DROP COLUMN locked_until,
    DROP COLUMN password_changed_at;

CREATE UNIQUE INDEX ux_app_user_email ON app_user (email);
