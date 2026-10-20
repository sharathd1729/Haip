"""Lead workflows, phase 3: what a task is for, and which playbook made it

* ``tasks.kind`` VARCHAR(30) NULL: followup | call | decide | ... for tasks the lead playbooks create. NULL on every
  older task (those are still told apart by their title, as before).
* ``tasks.playbook_run_id`` VARCHAR NULL: the playbook run (playbook_runs.id) that created the task.

Additive and idempotent (production builds tables with create_all at startup). No new table, so no new RLS policy: tasks
keeps its tenant policy.

Revision ID: 152
Revises: 151
Create Date: 2026-10-20
"""
from alembic import op

revision = "152"
down_revision = "151"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS kind VARCHAR(30)")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS playbook_run_id VARCHAR")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_tenant_kind ON tasks (tenant_id, kind)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_playbook_run_id ON tasks (playbook_run_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_tasks_playbook_run_id")
    op.execute("DROP INDEX IF EXISTS ix_tasks_tenant_kind")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS playbook_run_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS kind")
