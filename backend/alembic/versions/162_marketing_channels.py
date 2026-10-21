"""Marketing agency M3: more channels.

  * marketing_content.targets (JSON, nullable: None means Instagram only)
  * marketing_publish_attempts.channel (VARCHAR(20) NOT NULL DEFAULT 'instagram'); the unique key becomes
    (content_id, version_id, channel), so one approved version can be posted once per channel
  * marketing_guest_reviews: Google reviews and HAIP's replies (tenant_id, ENABLE + FORCE RLS, tenant policy)
Idempotent (ADD COLUMN IF NOT EXISTS, guarded constraint swap, CREATE TABLE IF NOT EXISTS). Downgrade restores the
previous unique key (fails loudly if two channels were posted for one version) and drops the new objects.

Revision ID: 162
Revises: 161
"""
from alembic import op

revision = "162"
down_revision = "161"
branch_labels = None
depends_on = None

REVIEWS = "marketing_guest_reviews"


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    ts = "TIMESTAMPTZ" if postgres else "TIMESTAMP"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
        op.execute("ALTER TABLE marketing_content ADD COLUMN IF NOT EXISTS targets JSON")
        op.execute("ALTER TABLE marketing_publish_attempts ADD COLUMN IF NOT EXISTS channel VARCHAR(20) NOT NULL DEFAULT 'instagram'")
        op.execute("ALTER TABLE marketing_publish_attempts DROP CONSTRAINT IF EXISTS uq_marketing_publish_attempts_version")
        op.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_marketing_publish_attempts_channel') THEN
                    ALTER TABLE marketing_publish_attempts
                        ADD CONSTRAINT uq_marketing_publish_attempts_channel UNIQUE (content_id, version_id, channel);
                END IF;
            END
            $$
        """)
    else:
        cols = {r[1] for r in bind.exec_driver_sql("PRAGMA table_info(marketing_content)")}
        if "targets" not in cols:
            op.execute("ALTER TABLE marketing_content ADD COLUMN targets JSON")
        cols = {r[1] for r in bind.exec_driver_sql("PRAGMA table_info(marketing_publish_attempts)")}
        if "channel" not in cols:
            op.execute("ALTER TABLE marketing_publish_attempts ADD COLUMN channel VARCHAR(20) NOT NULL DEFAULT 'instagram'")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {REVIEWS} (
            id             VARCHAR PRIMARY KEY,
            tenant_id      VARCHAR NOT NULL REFERENCES tenants(id),
            source         VARCHAR(20) NOT NULL DEFAULT 'google',
            external_id    VARCHAR(300) NOT NULL,
            location       VARCHAR(200),
            rating         INTEGER,
            reviewer       VARCHAR(200),
            comment        TEXT,
            reviewed_at    VARCHAR(40),
            reply_status   VARCHAR(20) NOT NULL DEFAULT 'none',
            reply_draft    TEXT,
            reply_origin   VARCHAR(10),
            reply_posted   TEXT,
            reply_error    TEXT,
            drafted_by     VARCHAR,
            approved_by    VARCHAR,
            posted_at      {ts},
            created_at     {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at     {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_marketing_guest_reviews_ext UNIQUE (tenant_id, source, external_id)
        )
    """)
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{REVIEWS}_tenant_id ON {REVIEWS} (tenant_id)")
    if postgres:
        op.execute(f"ALTER TABLE {REVIEWS} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {REVIEWS} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies WHERE tablename = '{REVIEWS}' AND policyname = '{REVIEWS}_tenant_isolation'
                ) THEN
                    CREATE POLICY {REVIEWS}_tenant_isolation ON {REVIEWS}
                    USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$
        """)


def downgrade():
    bind = op.get_bind()
    op.execute(f"DROP TABLE IF EXISTS {REVIEWS}")
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE marketing_publish_attempts DROP CONSTRAINT IF EXISTS uq_marketing_publish_attempts_channel")
        op.execute("ALTER TABLE marketing_publish_attempts ADD CONSTRAINT uq_marketing_publish_attempts_version "
                   "UNIQUE (content_id, version_id)")
        op.execute("ALTER TABLE marketing_publish_attempts DROP COLUMN IF EXISTS channel")
        op.execute("ALTER TABLE marketing_content DROP COLUMN IF EXISTS targets")
    else:
        op.drop_column("marketing_publish_attempts", "channel")
        op.drop_column("marketing_content", "targets")
