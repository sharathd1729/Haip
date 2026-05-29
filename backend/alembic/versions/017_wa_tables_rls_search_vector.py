"""RLS for wa_* messaging tables + search_vector on messages

Covers:
  SEC-1  — Row-level security on wa_templates, wa_campaigns, wa_subscribers, wa_flows
           (these tables are created via Base.metadata.create_all on startup, bypassing
           Alembic, so they never received RLS policies in migration 002)
  SEC-2  — search_vector tsvector column on messages (queried by the search endpoint
           but never created by any prior migration, causing runtime errors)
  IDX-1  — GIN index on messages.search_vector for full-text search performance
  IDX-2  — ix_calls_tenant_id_started_at composite for call-list queries
  IDX-3  — ix_inquiries_tenant_id_stage for Kanban board queries

Revision ID: 017
Revises: 016
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None

# Tables created by create_all but never added to Alembic-managed RLS
_WA_TABLES = ["wa_templates", "wa_campaigns", "wa_subscribers", "wa_flows"]


def upgrade() -> None:
    # ── Ensure wa_* tables exist (create_all may not have run yet in CI) ─────
    # These CREATE TABLE IF NOT EXISTS statements are idempotent.  The engine in
    # production already creates them via lifespan create_all, but the migration
    # needs to ensure they exist before adding RLS policies.
    op.execute("""
        CREATE TABLE IF NOT EXISTS wa_templates (
            id          TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL,
            name        TEXT NOT NULL,
            language    TEXT DEFAULT 'en',
            category    TEXT DEFAULT 'MARKETING',
            status      TEXT DEFAULT 'draft',
            components  JSONB DEFAULT '[]',
            meta_template_id TEXT,
            rejection_reason TEXT,
            created_at  TIMESTAMPTZ DEFAULT now(),
            updated_at  TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS wa_campaigns (
            id              TEXT PRIMARY KEY,
            tenant_id       TEXT NOT NULL,
            name            TEXT NOT NULL,
            template_id     TEXT,
            status          TEXT DEFAULT 'draft',
            audience_filter JSONB DEFAULT '{}',
            scheduled_at    TEXT,
            sent_count      TEXT DEFAULT '0',
            delivered_count TEXT DEFAULT '0',
            read_count      TEXT DEFAULT '0',
            failed_count    TEXT DEFAULT '0',
            created_at      TIMESTAMPTZ DEFAULT now(),
            updated_at      TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS wa_subscribers (
            id          TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL,
            phone       TEXT NOT NULL,
            name        TEXT,
            opted_in    BOOLEAN DEFAULT TRUE,
            opt_in_at   TEXT,
            opt_out_at  TEXT,
            source      TEXT,
            tags        JSONB DEFAULT '[]',
            created_at  TIMESTAMPTZ DEFAULT now(),
            updated_at  TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS wa_flows (
            id          TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL,
            name        TEXT NOT NULL,
            description TEXT,
            nodes       JSONB DEFAULT '[]',
            edges       JSONB DEFAULT '[]',
            is_active   BOOLEAN DEFAULT FALSE,
            trigger     TEXT,
            created_at  TIMESTAMPTZ DEFAULT now(),
            updated_at  TIMESTAMPTZ DEFAULT now()
        )
    """)

    # ── Tenant indexes on wa_* tables ─────────────────────────────────────────
    for tbl in _WA_TABLES:
        op.execute(f"""
            CREATE INDEX IF NOT EXISTS ix_{tbl}_tenant_id ON {tbl} (tenant_id)
        """)

    # ── Row-level security on wa_* tables ────────────────────────────────────
    for tbl in _WA_TABLES:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = '{tbl}' AND policyname = '{tbl}_tenant_isolation'
                ) THEN
                    CREATE POLICY {tbl}_tenant_isolation ON {tbl}
                    USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$
        """)

    # ── search_vector tsvector column on messages ─────────────────────────────
    # The search endpoint references messages.search_vector but no migration
    # ever created it.  Add it now as a generated column populated by a trigger.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'messages' AND column_name = 'search_vector'
            ) THEN
                ALTER TABLE messages ADD COLUMN search_vector tsvector;
            END IF;
        END
        $$
    """)

    # Trigger to keep search_vector up-to-date on insert/update
    op.execute("""
        CREATE OR REPLACE FUNCTION messages_search_vector_update()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('english', coalesce(NEW.body, '')), 'A');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS trig_messages_search_vector ON messages
    """)
    op.execute("""
        CREATE TRIGGER trig_messages_search_vector
        BEFORE INSERT OR UPDATE OF body ON messages
        FOR EACH ROW EXECUTE FUNCTION messages_search_vector_update()
    """)

    # Back-fill existing rows
    op.execute("""
        UPDATE messages
        SET search_vector = setweight(to_tsvector('english', coalesce(body, '')), 'A')
        WHERE search_vector IS NULL
    """)

    # GIN index for full-text search performance
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_messages_search_vector
        ON messages USING GIN (search_vector)
    """)

    # ── Additional performance indexes from audit recommendations ─────────────

    # Calls sorted by started_at (dashboard + call-list queries)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_calls_tenant_id_started_at
        ON calls (tenant_id, started_at DESC)
    """)

    # Inquiries by stage (Kanban board)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_inquiries_tenant_id_stage
        ON inquiries (tenant_id, stage)
    """)

    # Messages idempotency dedup (partial — only rows with idempotency_key set)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_messages_tenant_idempotency
        ON messages (tenant_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_tenant_idempotency")
    op.execute("DROP INDEX IF EXISTS ix_inquiries_tenant_id_stage")
    op.execute("DROP INDEX IF EXISTS ix_calls_tenant_id_started_at")
    op.execute("DROP INDEX IF EXISTS ix_messages_search_vector")
    op.execute("DROP TRIGGER IF EXISTS trig_messages_search_vector ON messages")
    op.execute("DROP FUNCTION IF EXISTS messages_search_vector_update()")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS search_vector")

    for tbl in reversed(_WA_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {tbl}_tenant_isolation ON {tbl}")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP INDEX IF EXISTS ix_{tbl}_tenant_id")
