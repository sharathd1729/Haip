"""Capability registry (HAIP_MCP_Connector_Plan.md Phase 1)

Adds the global `capabilities` catalogue and the tenant-scoped
`role_capabilities` override matrix, seeds the v1 catalogue (plan §2.2),
and backfills the default role matrix (plan §2.3) for every existing
tenant. "finance" role dropped from the matrix per product decision
2026-08-02 (UserRole has no FINANCE member; ticket 1.5 in the plan
called this out as a decision to make before seeding, not a default).

Revision ID: 057
Revises: 056
Create Date: 2026-08-02
"""
from alembic import op
import sqlalchemy as sa

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None

# (key, label, category, is_write, risk) -- plan §2.2 catalogue.
_CAPABILITIES = [
    ("leads.read", "View leads", "leads", False, "low"),
    ("leads.write", "Edit leads (stage, notes, assignment)", "leads", True, "medium"),
    ("leads.merge", "Merge guest identities", "leads", True, "high"),
    ("conversations.read", "View inbox conversations", "conversations", False, "low"),
    ("conversations.send", "Send guest-facing messages", "conversations", True, "medium"),
    ("calls.read", "View call list, scores, AI analysis", "calls", False, "low"),
    ("calls.transcript.read", "View full call transcripts", "calls", False, "medium"),
    ("calls.recording.read", "Access call recording URLs", "calls", False, "medium"),
    ("guests.read", "Search and view guest profiles (masked contact)", "guests", False, "low"),
    ("guests.pii.reveal", "Reveal unmasked guest phone/email", "guests", False, "high"),
    ("bookings.read", "View bookings and stays", "bookings", False, "low"),
    ("revenue.read", "View revenue, ADR, RevPAR, quote values", "revenue", False, "medium"),
    ("analytics.read", "View dashboard metrics and funnels", "analytics", False, "low"),
    ("qa.read", "View auto-QA scorecards", "qa", False, "low"),
    ("qa.override", "Manually override a QA score", "qa", True, "medium"),
    ("compliance.export", "DPDP export / deletion requests", "admin", True, "high"),
    ("users.read", "View team roster and scorecards", "admin", False, "low"),
    ("users.manage", "Invite, change role, deactivate users", "admin", True, "high"),
    ("settings.manage", "Edit tenant config, integrations, pipeline stages", "admin", True, "high"),
]

# (role, capability_key, allowed) -- plan §2.3 default matrix, finance column dropped.
_ROLES = ("owner", "manager", "reservations", "concierge", "foh", "marketing", "compliance", "read_only")

# For each capability key: the subset of _ROLES that get allowed=true.
_GRANTS = {
    "leads.read": {"owner", "manager", "reservations", "concierge", "foh", "marketing", "read_only"},
    "leads.write": {"owner", "manager", "reservations", "concierge"},
    "leads.merge": {"owner", "manager"},
    "conversations.read": {"owner", "manager", "reservations", "concierge", "foh", "read_only"},
    "conversations.send": {"owner", "manager", "reservations", "concierge"},
    "calls.read": {"owner", "manager", "reservations", "concierge", "marketing", "read_only"},
    "calls.transcript.read": {"owner", "manager", "reservations", "concierge", "compliance"},
    "calls.recording.read": {"owner", "manager", "compliance"},
    "guests.read": {"owner", "manager", "reservations", "concierge", "foh", "marketing", "compliance", "read_only"},
    "guests.pii.reveal": {"owner", "manager", "reservations", "concierge", "compliance"},
    "bookings.read": {"owner", "manager", "reservations", "concierge", "foh", "read_only"},
    "revenue.read": {"owner", "manager", "marketing"},
    "analytics.read": {"owner", "manager", "reservations", "marketing", "read_only"},
    "qa.read": {"owner", "manager", "concierge", "compliance", "read_only"},
    "qa.override": {"owner", "manager"},
    "compliance.export": {"owner", "compliance"},
    "users.read": {"owner", "manager", "compliance"},
    "users.manage": {"owner"},
    "settings.manage": {"owner"},
}


def upgrade():
    op.create_table(
        "capabilities",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("is_write", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("module_code", sa.String(50), nullable=True),
        sa.Column("risk", sa.String(10), nullable=False, server_default="low"),
    )

    op.create_table(
        "role_capabilities",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("capability_key", sa.String(64), sa.ForeignKey("capabilities.key"), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "role", "capability_key", name="uq_role_capabilities_tenant_role_key"),
    )
    op.create_index("ix_role_capabilities_tenant_role", "role_capabilities", ["tenant_id", "role"])

    op.execute("ALTER TABLE role_capabilities ENABLE ROW LEVEL SECURITY")
    # FORCE too -- without it the table owner bypasses the policy entirely,
    # same reasoning as migration 053 (guest_events): this table gates PII
    # and revenue access, so the table owner must not get a silent bypass.
    op.execute("ALTER TABLE role_capabilities FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY role_capabilities_tenant_iso ON role_capabilities
        USING (tenant_id = current_setting('app.tenant_id', true)::text)
    """)

    # ── seed: capability catalogue ────────────────────────────────────────────
    conn = op.get_bind()
    cap_table = sa.table(
        "capabilities",
        sa.column("key", sa.String), sa.column("label", sa.String),
        sa.column("category", sa.String), sa.column("is_write", sa.Boolean),
        sa.column("risk", sa.String),
    )
    conn.execute(
        cap_table.insert(),
        [
            {"key": key, "label": label, "category": category, "is_write": is_write, "risk": risk}
            for key, label, category, is_write, risk in _CAPABILITIES
        ],
    )

    # ── backfill: default role matrix for every existing tenant ──────────────
    # Full matrix (both allowed=true and allowed=false rows), not sparse --
    # the settings UI needs every cell present to render toggles, and a
    # missing row must never silently mean "denied" vs. "not yet decided"
    # (get_capabilities/authz_service treats a wholly-unprovisioned tenant --
    # zero rows -- as the fail-closed case; a tenant with the seeded matrix
    # always has an explicit true/false per cell).
    rc_table = sa.table(
        "role_capabilities",
        sa.column("id", sa.String), sa.column("tenant_id", sa.String),
        sa.column("role", sa.String), sa.column("capability_key", sa.String),
        sa.column("allowed", sa.Boolean),
    )
    tenant_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM tenants")).fetchall()]

    import uuid
    rows = []
    for tenant_id in tenant_ids:
        for key, *_rest in _CAPABILITIES:
            grants = _GRANTS[key]
            for role in _ROLES:
                rows.append({
                    "id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "role": role,
                    "capability_key": key,
                    "allowed": role in grants,
                })
    if rows:
        conn.execute(rc_table.insert(), rows)


def downgrade():
    op.drop_index("ix_role_capabilities_tenant_role", table_name="role_capabilities")
    op.drop_table("role_capabilities")
    op.drop_table("capabilities")
