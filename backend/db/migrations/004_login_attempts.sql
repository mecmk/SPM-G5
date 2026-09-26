-- =====================================================================
-- Migration 004 - temporary sign-in lockout after repeated failures.
--
-- Bug f1.1.2 (story 1.1 AC6): after LOGIN_MAX_FAILURES failed sign-ins for the same e-mail
-- within LOGIN_FAILURE_WINDOW_MINUTES, sign-in for that e-mail is refused for
-- LOGIN_LOCK_MINUTES (backend/app/config.py). Failures are counted by the e-mail typed, whether
-- or not an account exists, so a lock never reveals which accounts exist (story 1.1 AC2). That
-- is why this is its own table rather than columns on users, and why it has no FK to users.
-- =====================================================================

CREATE TABLE login_attempts (
    email             CITEXT PRIMARY KEY,
    failure_count     INTEGER NOT NULL DEFAULT 0,
    window_started_at TIMESTAMPTZ NOT NULL,
    locked_until      TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_login_attempts_count_non_negative CHECK (failure_count >= 0)
);
COMMENT ON TABLE login_attempts IS
    'Stories: 1.1 (AC6). Failed sign-in counter per e-mail address, used to lock sign-in for a while after repeated failures. Keyed by the e-mail as typed, with no FK to users on purpose: unknown e-mails are tracked and locked exactly like real ones, so a lock never reveals whether an account exists (story 1.1 AC2). A successful sign-in deletes the row.';
COMMENT ON COLUMN login_attempts.email IS 'E-mail address typed at sign-in, trimmed. Case-insensitive; may not belong to any account.';
COMMENT ON COLUMN login_attempts.failure_count IS 'Failed sign-ins in the current window. Reset to 0 when a lock starts.';
COMMENT ON COLUMN login_attempts.window_started_at IS 'Time of the first failure in the current counting window.';
COMMENT ON COLUMN login_attempts.locked_until IS 'Sign-in for this e-mail is refused until this instant. NULL when no lock has been applied.';
COMMENT ON COLUMN login_attempts.updated_at IS 'Last modification time (maintained by trigger).';

CREATE TRIGGER trg_login_attempts_set_updated_at BEFORE UPDATE ON login_attempts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
