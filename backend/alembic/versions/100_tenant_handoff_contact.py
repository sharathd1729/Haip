"""Tenant handoff contact details for AI conversations.

When a guest asks to be called or to move to WhatsApp, the bot has to hand
over a real phone number and WhatsApp link. Until now those only existed as
free text inside one Instagram automation rule's canned message -- so the AI
path had no access to them, and a guest who phrased the request in a way the
rule's keywords missed got an AI reply with no way to reach anyone.

Storing them on the tenant makes them a first-class setting the concierge
can read on any channel, rather than something buried in one rule's body.

`handoff_enabled` is deliberately separate from "are the fields filled in":
a tenant may want to stage the details before letting the bot volunteer them.

Revision ID: 100
Revises: 099
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa

revision = "100"
down_revision = "099"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    return column in [c["name"] for c in sa.inspect(conn).get_columns(table)]


COLUMNS = (
    # E.164, shown to guests and used for "call us" handoffs
    ("handoff_phone", sa.String(32)),
    # full wa.me / wa link -- a URL, not a number, since tenants commonly use
    # a click-to-chat short link rather than the raw WABA number
    ("handoff_whatsapp_url", sa.String(500)),
)


def upgrade() -> None:
    for name, type_ in COLUMNS:
        if not _has_column("tenants", name):
            op.add_column("tenants", sa.Column(name, type_, nullable=True))
    if not _has_column("tenants", "handoff_enabled"):
        op.add_column(
            "tenants",
            sa.Column("handoff_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    for name, _type in COLUMNS:
        if _has_column("tenants", name):
            op.drop_column("tenants", name)
    if _has_column("tenants", "handoff_enabled"):
        op.drop_column("tenants", "handoff_enabled")
