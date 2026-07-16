"""IAM Phase 0: user signup consent columns, invitation expires_at as real timestamp

Revision ID: 035
Revises: 034
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect as _inspect
    bind = op.get_bind()

    # user_invitations was never created by any migration in this repo's
    # history (only ever created out-of-band on already-provisioned
    # databases) -- guard so a genuinely fresh install doesn't fail here.
    if "user_invitations" not in _inspect(bind).get_table_names():
        op.create_table(
            "user_invitations",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
            sa.Column("invited_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("email", sa.String(255), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("role", sa.String(50), nullable=False),
            sa.Column("token", sa.String(255), nullable=False, unique=True, index=True),
            sa.Column("is_accepted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )

    existing_cols = {c["name"] for c in _inspect(bind).get_columns("users")}

    # ── Platform-level signup consent on users ────────────────────────────────
    # Guarded (unlike when first written) — this migration was renumbered
    # 034→035 during a merge with upstream work that also claimed "034", and
    # some environments already had these columns applied under the old
    # numbering before the renumber. Idempotent either way.
    if "consent_transactional" not in existing_cols:
        op.add_column("users", sa.Column("consent_transactional", sa.Boolean(), nullable=False, server_default="true"))
    if "consent_marketing" not in existing_cols:
        op.add_column("users", sa.Column("consent_marketing", sa.Boolean(), nullable=False, server_default="false"))
    if "consent_analytics" not in existing_cols:
        op.add_column("users", sa.Column("consent_analytics", sa.Boolean(), nullable=False, server_default="false"))
    if "consent_recorded_at" not in existing_cols:
        op.add_column("users", sa.Column("consent_recorded_at", sa.DateTime(timezone=True), nullable=True))

    # ── UserInvitation.expires_at: fragile ISO string → real timestamptz ──────
    # Existing values are all `.isoformat()` output, so a direct cast is safe.
    # Guarded — skip if already converted (see note above).
    invitation_cols = {c["name"]: c["type"] for c in _inspect(bind).get_columns("user_invitations")}
    if "expires_at" in invitation_cols and str(invitation_cols["expires_at"]).upper().startswith("VARCHAR"):
        op.execute(
            "ALTER TABLE user_invitations "
            "ALTER COLUMN expires_at TYPE TIMESTAMPTZ USING expires_at::timestamptz"
        )


def downgrade():
    op.execute(
        "ALTER TABLE user_invitations "
        "ALTER COLUMN expires_at TYPE VARCHAR(50) USING expires_at::text"
    )
    op.drop_column("users", "consent_recorded_at")
    op.drop_column("users", "consent_analytics")
    op.drop_column("users", "consent_marketing")
    op.drop_column("users", "consent_transactional")
