"""Widen calls.ai_score_status to 40 characters.

judge() writes "skipped_no_transcript" (21 characters) for a call that has no usable transcript. The column was
created as varchar(20) (migration 001), so on PostgreSQL that UPDATE raised "value too long for type character
varying(20)". The write is the October fix that stops call_recovery re-dispatching transcript-less calls
forever; with the column too narrow the fix failed, judge() fell into its error handler and marked the call
"failed" without counting the attempt, and call_recovery kept picking it up every 30 minutes (for 14 days).
SQLite does not enforce the width, which is why the tests never caught it.

Widening a varchar is a metadata-only change in PostgreSQL (no table rewrite). It is idempotent and only ever
widens: a column that is already 40 or wider, or has no length limit, is left alone. Existing rows are untouched.
Calls that were already marked "failed" because of this bug are NOT rewritten here: recovery retries them as
before, and once the column is wide enough judge() skips them correctly.

Locking: ALTER COLUMN TYPE takes an ACCESS EXCLUSIVE lock on "calls". If a long transaction already touches
"calls", the ALTER would queue behind it and, because PostgreSQL queues later lock requests behind a waiting
ACCESS EXCLUSIVE, every query on "calls" would stall too. The migration therefore sets a transaction-local
lock_timeout: if it cannot get the lock within LOCK_TIMEOUT it fails and rolls back, nothing changes, and the API
container exits and is restarted by docker (restart: unless-stopped), which retries the migration. Forward
recovery is simply to let it retry once the blocking transaction ends (or run `alembic upgrade head` by hand).

Rollback / downgrade: forward-only. downgrade() does NOT narrow the column (narrowing could truncate or fail on rows
that now hold the longer value, and the wider column is harmless to older code). It exists so `alembic downgrade 116`
works: it only moves alembic_version back to 116. That matters because an OLDER image does not contain revision 117,
so `alembic upgrade head` in that image would fail with "Can't locate revision identified by '117'" if the database is
left at 117. To roll the code back: run `alembic downgrade 116` with THIS image first, then start the older image.

Revision ID: 117
Revises: 116
"""
from alembic import op

revision = "117"
down_revision = "116"
branch_labels = None
depends_on = None

# How long the ALTER may wait for the lock on "calls" before the migration gives up (and is retried on restart).
LOCK_TIMEOUT = "10s"


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite does not enforce varchar length
    op.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
    op.execute("""
        DO $$
        DECLARE current_len integer;
        BEGIN
            SELECT character_maximum_length INTO current_len
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'calls' AND column_name = 'ai_score_status';
            IF current_len IS NOT NULL AND current_len < 40 THEN
                ALTER TABLE calls ALTER COLUMN ai_score_status TYPE VARCHAR(40);
            END IF;
        END
        $$
    """)


def downgrade():
    # Deliberately does not narrow the column; see the module docstring. Only the version marker moves back.
    pass
