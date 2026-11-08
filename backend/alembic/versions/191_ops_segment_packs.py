"""Packs for every segment (Ops 2, gap 7): per-property checklists, the business's pack data, self check-in.

ops_checklist_templates.property_id  NULL = the business's default checklist (one per tenant + pack + kind, as before);
                                     a property's own copy otherwise. The old UNIQUE (tenant_id, pack, kind) becomes two
                                     partial unique indexes (default rows / property rows).
ops_settings.pack_config             the business's copy of its pack's data (duties, issue types, paperwork, add-ons,
                                     automatic-message timings, flow), seeded by ops_pack_seed, never over an edit.
properties.self_check_in             nobody meets the guest (whole_unit packs).
properties.self_check_in_enc         Fernet token: check-in steps, lock code, key box (ops_self_check_in). Never logged.

No new table: all three tables already have tenant_id + forced RLS (properties since the start, 178, 179).
Idempotent (prod also runs create_all, which never adds a column to an existing table): ADD COLUMN IF NOT EXISTS,
DROP CONSTRAINT IF EXISTS, CREATE UNIQUE INDEX IF NOT EXISTS.

Revision ID: 191
Revises: 190
"""

from alembic import op

revision = "191"
down_revision = "190"
branch_labels = None
depends_on = None


COLUMNS = (
    ("ops_checklist_templates", "property_id", "VARCHAR REFERENCES properties(id) ON DELETE CASCADE", "VARCHAR"),
    ("ops_settings", "pack_config", "JSON", "JSON"),
    ("properties", "self_check_in", "BOOLEAN NOT NULL DEFAULT FALSE", "BOOLEAN NOT NULL DEFAULT 0"),
    ("properties", "self_check_in_enc", "TEXT", "TEXT"),
)
INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_ops_checklist_templates_default "
    "ON ops_checklist_templates (tenant_id, pack, kind) WHERE property_id IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_ops_checklist_templates_property "
    "ON ops_checklist_templates (tenant_id, pack, kind, property_id) WHERE property_id IS NOT NULL",
)


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    for table, column, pg_kind, lite_kind in COLUMNS:
        if postgres:
            op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {pg_kind}")
        elif column not in {r[1] for r in bind.exec_driver_sql(f"PRAGMA table_info({table})")}:
            op.execute(f"ALTER TABLE {table} ADD COLUMN {column} {lite_kind}")
    if postgres:
        op.execute("ALTER TABLE ops_checklist_templates DROP CONSTRAINT IF EXISTS uq_ops_checklist_templates_kind")
    for sql in INDEXES:
        op.execute(sql)


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ux_ops_checklist_templates_property")
    # A property's own checklists cannot live under the old one-per-kind rule: drop them before restoring it.
    op.execute("DELETE FROM ops_checklist_templates WHERE property_id IS NOT NULL")
    op.execute("DROP INDEX IF EXISTS ux_ops_checklist_templates_default")
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_ops_checklist_templates_kind') THEN "
        "ALTER TABLE ops_checklist_templates ADD CONSTRAINT uq_ops_checklist_templates_kind UNIQUE (tenant_id, pack, kind); "
        "END IF; END $$"
    )
    for table, column, _pg, _lite in reversed(COLUMNS):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
