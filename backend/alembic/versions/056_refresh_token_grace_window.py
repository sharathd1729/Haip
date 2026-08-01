"""refresh_token grace window -- distinguish concurrent-request races from
genuine token theft on refresh-token reuse.

Previously /auth/refresh hard-401'd on ANY second presentation of an
already-rotated token. Dashboard pages fire several requests in parallel;
if two of them both trigger a proactive refresh at once, the second one
in used to look like theft even though it's the same legitimate client.

Adds two nullable columns to refresh_tokens:
- revoked_at: when this row was rotated out (NULL while still active).
  Superset of is_revoked (kept for backward compat / cheap filtering).
- replaced_by_token_hash: hash of the token this row was rotated into,
  so a reused old token can be answered with the same successor it
  already produced, instead of minting a second one.

Reuse within GRACE_WINDOW_SECONDS (60s, see auth.py) of revoked_at is
treated as a race and re-served the existing successor. Reuse after that
window is treated as theft: the whole user's active refresh tokens are
revoked and an audit event is written.

No RLS -- same reasoning as migration 001 (refresh_tokens) and 055
(personal_access_tokens): looking up a token by hash happens BEFORE the
tenant is known, so an RLS policy keyed on app.tenant_id would make the
row unfindable at the point it needs to be looked up.

Revision ID: 056
Revises: 055
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("refresh_tokens", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("refresh_tokens", sa.Column("replaced_by_token_hash", sa.String(255), nullable=True))

    # Backfill revoked_at for rows already marked is_revoked under the old
    # scheme, so the grace-window comparison has something sane to compare
    # against instead of NULL (which would make them look "revoked just now").
    # Pushed far enough in the past that no in-flight grace window can span it.
    op.execute(
        "UPDATE refresh_tokens SET revoked_at = updated_at "
        "WHERE is_revoked = true AND revoked_at IS NULL"
    )

    op.create_index(
        "ix_refresh_tokens_replaced_by_token_hash",
        "refresh_tokens",
        ["replaced_by_token_hash"],
    )


def downgrade():
    op.drop_index("ix_refresh_tokens_replaced_by_token_hash", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "replaced_by_token_hash")
    op.drop_column("refresh_tokens", "revoked_at")
