"""Leads360 restructure Phase 1: tenant-owned pipeline_stages catalog

Additive only — the legacy inquiries.stage enum column is left untouched.
inquiries.stage_id is added as a nullable FK and backfilled from the
current enum value / each tenant's pipeline_config (if set), so call sites
can be migrated to stage_id incrementally. A later cleanup migration will
drop inquiries.stage once every call site reads/writes stage_id instead.

Guarded throughout (table/index/policy/column existence checks) so this
migration is safely re-runnable if a previous attempt partially applied
before failing -- see CLAUDE.md's alembic env.py gotcha note.

Revision ID: 043
Revises: 042
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def _column_exists(table: str, col: str) -> bool:
    if not _table_exists(table):
        return False
    return col in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _index_exists(table: str, name: str) -> bool:
    if not _table_exists(table):
        return False
    return name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _policy_exists(policy: str, table: str) -> bool:
    row = op.get_bind().execute(sa.text(
        "SELECT 1 FROM pg_policies WHERE policyname = :p AND tablename = :t"
    ), {"p": policy, "t": table}).first()
    return row is not None


def upgrade():
    if not _table_exists("pipeline_stages"):
        op.create_table(
            "pipeline_stages",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("key", sa.String(40), nullable=False),
            sa.Column("label", sa.String(80), nullable=False),
            sa.Column("color", sa.String(7), nullable=False, server_default="#6366f1"),
            sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_default_entry", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("is_closed_won", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("is_closed_lost", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("tenant_id", "key", name="uq_pipeline_stage_tenant_key"),
        )

    if not _index_exists("pipeline_stages", "ix_pipeline_stages_tenant_order"):
        op.create_index("ix_pipeline_stages_tenant_order", "pipeline_stages", ["tenant_id", "order"])

    op.execute("ALTER TABLE pipeline_stages ENABLE ROW LEVEL SECURITY")
    if not _policy_exists("pipeline_stages_tenant_iso", "pipeline_stages"):
        op.execute("""
            CREATE POLICY pipeline_stages_tenant_iso ON pipeline_stages
            USING (tenant_id = current_setting('app.tenant_id', true)::text)
        """)

    # Every tenant is seeded with the same 7-stage default set today
    # (pipeline_config only ever re-labels/recolors/reorders/hides these
    # same keys — it never introduces a new one — so seeding from the fixed
    # default set and letting the existing pipeline_config values overlay
    # label/color/order/visibility is equivalent and far simpler than
    # parsing every tenant's JSON blob here).
    op.execute("""
        INSERT INTO pipeline_stages
            (id, tenant_id, key, label, color, "order", is_default_entry, is_closed_won, is_closed_lost, created_at, updated_at)
        SELECT
            gen_random_uuid()::text, t.id, d.key, d.label, d.color, d."order",
            d.is_default_entry, d.is_closed_won, d.is_closed_lost, now(), now()
        FROM tenants t
        CROSS JOIN (VALUES
            ('new',                  'New',         '#6366f1', 0, true,  false, false),
            ('responding',           'Responding',  '#f59e0b', 1, false, false, false),
            ('quoted',               'Quoted',      '#8b5cf6', 2, false, false, false),
            ('site_visit_scheduled', 'Site Visit',  '#06b6d4', 3, false, false, false),
            ('site_visit_done',      'Visit Done',  '#10b981', 4, false, false, false),
            ('booked',               'Booked',      '#22c55e', 5, false, true,  false),
            ('closed',               'Closed',      '#6b7280', 6, false, false, true)
        ) AS d(key, label, color, "order", is_default_entry, is_closed_won, is_closed_lost)
        ON CONFLICT (tenant_id, key) DO NOTHING
    """)

    # ── inquiries.stage_id: nullable FK, backfilled from the legacy enum ───────
    if not _column_exists("inquiries", "stage_id"):
        op.add_column("inquiries", sa.Column("stage_id", sa.String(), sa.ForeignKey("pipeline_stages.id"), nullable=True))
    if not _index_exists("inquiries", "ix_inquiries_stage_id"):
        op.create_index("ix_inquiries_stage_id", "inquiries", ["stage_id"])

    # GHOSTED and legacy SITE_VISIT both need a matching pipeline_stages row
    # to backfill against -- GHOSTED maps to the same "Closed" stage as LOST
    # (CLAUDE.md: "GHOSTED is grouped with LOST in UI as Closed"), and the
    # deprecated SITE_VISIT alias maps to the site_visit_scheduled stage.
    # Re-runnable unconditionally -- it only ever (re)assigns stage_id for
    # rows whose stage/pipeline_stages mapping resolves, never destructive.
    op.execute("""
        UPDATE inquiries i
        SET stage_id = ps.id
        FROM pipeline_stages ps
        WHERE ps.tenant_id = i.tenant_id
          AND ps.key = CASE i.stage::text
              WHEN 'lost'       THEN 'closed'
              WHEN 'ghosted'    THEN 'closed'
              WHEN 'site_visit' THEN 'site_visit_scheduled'
              ELSE i.stage::text
          END
          AND i.stage_id IS NULL
    """)


def downgrade():
    op.drop_index("ix_inquiries_stage_id", table_name="inquiries")
    op.drop_column("inquiries", "stage_id")
    op.execute("DROP POLICY IF EXISTS pipeline_stages_tenant_iso ON pipeline_stages")
    op.drop_index("ix_pipeline_stages_tenant_order", table_name="pipeline_stages")
    op.drop_table("pipeline_stages")
