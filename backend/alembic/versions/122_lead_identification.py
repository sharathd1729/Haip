"""Canonical lead definition: record when a contact became an identified lead, and keep a merge history.

A lead is a person HAIP has captured a usable phone number for. This adds, to ``guests``:
  lead_identified_at / lead_identified_via   when and through which channel the number was captured (NULL = not a lead yet)
  first_touch_channel / first_touch_at       how and when HAIP first heard from them (NULL channel = unknown)
and a new table ``guest_merge_events`` that records every identity merge (what moved) so it can be audited and undone.

Additive only: nullable columns, one new table (RLS + tenant policy, like every tenant table), nothing dropped or rewritten.
Existing guests are filled in conservatively by app.services.lead_backfill (a guest with no usable phone number is NOT turned
into a lead; see that module for exactly what is and is not claimed). The backfill runs in a savepoint: if it fails, the columns
are still added and the scripted backfill (scripts/backfill_lead_state.py) can be run later.

Locking: ADD COLUMN with no default is metadata-only on PostgreSQL; a transaction-local lock_timeout stops it queueing behind a
long transaction (the migration then fails and is retried on the next start, like 117).

Revision ID: 122
Revises: 121
"""
import logging

from alembic import op

revision = "122"
down_revision = "121"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")
TABLE = "guest_merge_events"


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    for col, kind in (("lead_identified_at", "TIMESTAMPTZ"), ("lead_identified_via", "VARCHAR(30)"),
                      ("first_touch_channel", "VARCHAR(30)"), ("first_touch_at", "TIMESTAMPTZ")):
        op.execute(f"ALTER TABLE guests ADD COLUMN IF NOT EXISTS {col} {kind}")
    op.execute("CREATE INDEX IF NOT EXISTS ix_guests_lead_identified_at ON guests (lead_identified_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_guests_tenant_lead_identified ON guests (tenant_id, lead_identified_at)")

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id                    VARCHAR PRIMARY KEY,
            tenant_id             VARCHAR NOT NULL,
            survivor_id           VARCHAR NOT NULL,
            deprecated_id         VARCHAR NOT NULL,
            actor_user_id         VARCHAR,
            reason                VARCHAR(40) NOT NULL DEFAULT 'exact_identity_match',
            moved                 JSON NOT NULL,
            deprecated_lead_state JSON,
            survivor_lead_state   JSON,
            unmerged_at           TIMESTAMPTZ,
            unmerged_by           VARCHAR,
            note                  TEXT,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    for col in ("tenant_id", "survivor_id", "deprecated_id"):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_{col} ON {TABLE} ({col})")
    if postgres:
        op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies WHERE tablename = '{TABLE}' AND policyname = '{TABLE}_tenant_isolation'
                ) THEN
                    CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
                    USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$
        """)

    # Conservative backfill, in a savepoint so a problem here cannot undo the schema change.
    try:
        from app.services import lead_backfill
        with bind.begin_nested():
            stats = lead_backfill.backfill(bind)
        log.info("lead_backfill_done %s", stats)
    except Exception as exc:  # noqa: BLE001
        log.error("lead_backfill_failed (columns are in place; run scripts/backfill_lead_state.py): %s", exc)


def downgrade():
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
    op.execute("DROP INDEX IF EXISTS ix_guests_tenant_lead_identified")
    op.execute("DROP INDEX IF EXISTS ix_guests_lead_identified_at")
    for col in ("first_touch_at", "first_touch_channel", "lead_identified_via", "lead_identified_at"):
        op.execute(f"ALTER TABLE guests DROP COLUMN IF EXISTS {col}")
