"""Leads360 restructure Phase 3: Lead Field Registry + special_requests

Revision ID: 044
Revises: 043
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None

# field_key, label, data_type, source, column_name, show_in_detail, required_for_lead, display_order
_SEED_FIELDS = [
    ("guest_name",   "Guest Name",       "text",   "column", None,        True,  True,  0),
    ("phone",        "Phone",            "phone",  "column", None,        True,  False, 1),
    ("adults",       "Adults",           "number", "column", "adults",    True,  False, 2),
    ("children",     "Children",         "number", "column", "children",  True,  False, 3),
    ("check_in",     "Check-in",         "date",   "column", "check_in",  True,  True,  4),
    ("check_out",    "Check-out",        "date",   "column", "check_out", True,  False, 5),
    ("budget",       "Budget",           "currency", "column", "budget",  True,  False, 6),
    ("occasion",     "Occasion",         "text",   "column", "occasion",  True,  False, 7),
    ("special_requests", "Special Requests", "text", "column", "special_requests", True, False, 8),
]


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
    if not _column_exists("inquiries", "special_requests"):
        op.add_column("inquiries", sa.Column("special_requests", sa.Text(), nullable=True))

    if not _table_exists("lead_field_definitions"):
        op.create_table(
            "lead_field_definitions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("field_key", sa.String(40), nullable=False),
            sa.Column("label", sa.String(80), nullable=False),
            sa.Column("data_type", sa.String(20), nullable=False, server_default="text"),
            sa.Column("source", sa.String(20), nullable=False, server_default="custom"),
            sa.Column("column_name", sa.String(40), nullable=True),
            sa.Column("show_in_detail", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("required_for_lead", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("tenant_id", "field_key", name="uq_lead_field_tenant_key"),
        )
    if not _index_exists("lead_field_definitions", "ix_lead_field_definitions_tenant"):
        op.create_index("ix_lead_field_definitions_tenant", "lead_field_definitions", ["tenant_id"])

    op.execute("ALTER TABLE lead_field_definitions ENABLE ROW LEVEL SECURITY")
    if not _policy_exists("lead_field_definitions_tenant_iso", "lead_field_definitions"):
        op.execute("""
            CREATE POLICY lead_field_definitions_tenant_iso ON lead_field_definitions
            USING (tenant_id = current_setting('app.tenant_id', true)::text)
        """)

    values_sql = ", ".join(
        "('%s','%s','%s','%s',%s,%s,%s,%s)" % (
            key, label, dtype, source,
            f"'{col}'" if col else "NULL",
            "true" if show else "false",
            "true" if req else "false",
            order,
        )
        for key, label, dtype, source, col, show, req, order in _SEED_FIELDS
    )
    op.execute(f"""
        INSERT INTO lead_field_definitions
            (id, tenant_id, field_key, label, data_type, source, column_name, show_in_detail, required_for_lead, display_order, created_at, updated_at)
        SELECT gen_random_uuid()::text, t.id, d.field_key, d.label, d.data_type, d.source, d.column_name, d.show_in_detail, d.required_for_lead, d.display_order, now(), now()
        FROM tenants t
        CROSS JOIN (VALUES {values_sql})
            AS d(field_key, label, data_type, source, column_name, show_in_detail, required_for_lead, display_order)
        ON CONFLICT (tenant_id, field_key) DO NOTHING
    """)


def downgrade():
    op.execute("DROP POLICY IF EXISTS lead_field_definitions_tenant_iso ON lead_field_definitions")
    op.drop_index("ix_lead_field_definitions_tenant", table_name="lead_field_definitions")
    op.drop_table("lead_field_definitions")
    op.drop_column("inquiries", "special_requests")
