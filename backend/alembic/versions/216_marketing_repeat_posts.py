"""Marketing Studio repeat posts: a scheduled post can go out again every N days, K more times, with the same approved
version. marketing_publish_attempts gets `run` (0 = the first post, 1.. = repeats), `repeat_every_days` and
`repeat_left`; the one-post-per-version guard becomes one post per (content, version, channel, run). The table already
has tenant_id and its RLS policy. Idempotent (production runs create_all at startup).

Revision ID: 216
Revises: 215
"""

from alembic import op

revision = "216"
down_revision = "215"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketing_publish_attempts ADD COLUMN IF NOT EXISTS run INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE marketing_publish_attempts ADD COLUMN IF NOT EXISTS repeat_every_days INTEGER")
    op.execute("ALTER TABLE marketing_publish_attempts ADD COLUMN IF NOT EXISTS repeat_left INTEGER")
    op.execute("ALTER TABLE marketing_publish_attempts DROP CONSTRAINT IF EXISTS uq_marketing_publish_attempts_channel")
    op.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_marketing_publish_attempts_run') THEN
            ALTER TABLE marketing_publish_attempts
              ADD CONSTRAINT uq_marketing_publish_attempts_run UNIQUE (content_id, version_id, channel, run);
          END IF;
        END $$;
    """)


def downgrade():
    # Repeats (run > 0) cannot fit the old one-per-version guard; drop them before restoring it.
    op.execute("DELETE FROM marketing_publish_attempts WHERE run > 0")
    op.execute("ALTER TABLE marketing_publish_attempts DROP CONSTRAINT IF EXISTS uq_marketing_publish_attempts_run")
    op.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_marketing_publish_attempts_channel') THEN
            ALTER TABLE marketing_publish_attempts
              ADD CONSTRAINT uq_marketing_publish_attempts_channel UNIQUE (content_id, version_id, channel);
          END IF;
        END $$;
    """)
    op.execute("ALTER TABLE marketing_publish_attempts DROP COLUMN IF EXISTS repeat_left")
    op.execute("ALTER TABLE marketing_publish_attempts DROP COLUMN IF EXISTS repeat_every_days")
    op.execute("ALTER TABLE marketing_publish_attempts DROP COLUMN IF EXISTS run")
