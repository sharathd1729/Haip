"""Quote options (primary + fallback) and the quote-builder capabilities.

Schema (additive, idempotent: production builds tables with create_all at startup, so every step checks first):
  * inquiry_quotes.option_rank      SMALLINT NOT NULL DEFAULT 1   1 = the primary option, 2 = the fallback option
  * inquiry_quotes.option_group_id  VARCHAR NULL, indexed          the primary quote's id, shared by both options

Capabilities (catalogue rows + role cells), same approach as migrations 119 and 129:
  * quotes.write           price and save quotes for a lead            owner, manager, reservations, concierge
  * business_data.draft    draft routes and packages (no publishing)   owner, manager, reservations
  * business_data.publish  approve and publish routes and packages     owner, manager
A provisioned tenant (any role_capabilities rows) gets every missing cell, allowed per these defaults. An existing cell is never
changed, so an owner's edit of a cell (PUT /capabilities/matrix, audited as role_capabilities.change) always wins; a tenant with no
matrix at all is unprovisioned and is left alone (it keeps failing closed). authz_service._DEFAULT_GRANTS carries the same defaults
for tenants created later. Portable SQL, so apply_capabilities() is tested on SQLite as well.

Row-level security: role_capabilities has FORCE row-level security, so like 057/076/119 this must run as a role that bypasses
RLS; it logs what it saw.

Numbering: revisions 129-139 are taken by unmerged branches; this one follows 128 directly. Downgrade drops the two columns and
the three capabilities (rows and cells).

Revision ID: 140
Revises: 128
"""
import logging
import uuid

import sqlalchemy as sa
from alembic import op

revision = "140"
down_revision = "128"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

_ROLES = ("owner", "manager", "reservations", "concierge", "foh", "marketing", "compliance", "read_only")
CAPABILITIES = [
    # key, label, category, is_write, risk, allowed roles
    ("quotes.write", "Price and save quotes for a lead", "quotes", True, "medium", {"owner", "manager", "reservations", "concierge"}),
    ("business_data.draft", "Draft routes and packages for approval", "business_data", True, "medium", {"owner", "manager", "reservations"}),
    ("business_data.publish", "Approve and publish routes and packages", "business_data", True, "high", {"owner", "manager"}),
]
TABLE = "inquiry_quotes"
INDEX = "ix_inquiry_quotes_option_group_id"


def apply_capabilities(bind) -> dict:
    """Insert missing catalogue rows and, for provisioned tenants, missing role cells. Never edits an existing row."""
    result = {"catalogue": 0, "cells": 0, "kept": 0}
    keys = [c[0] for c in CAPABILITIES]
    for key, label, category, is_write, risk, _ in CAPABILITIES:
        if bind.execute(sa.text("SELECT 1 FROM capabilities WHERE key = :k"), {"k": key}).first() is None:
            bind.execute(
                sa.text("INSERT INTO capabilities (key, label, category, is_write, module_code, risk) VALUES (:k, :l, :c, :w, NULL, :r)"),
                {"k": key, "l": label, "c": category, "w": is_write, "r": risk},
            )
            result["catalogue"] += 1
    tenants = [t for (t,) in bind.execute(sa.text("SELECT DISTINCT tenant_id FROM role_capabilities")).all()]
    for tenant_id in tenants:
        present = {
            (r, k) for r, k in bind.execute(
                sa.text("SELECT role, capability_key FROM role_capabilities WHERE tenant_id = :t AND capability_key IN (:a, :b, :c)"),
                {"t": tenant_id, "a": keys[0], "b": keys[1], "c": keys[2]},
            ).all()
        }
        for key, _l, _c, _w, _r, allowed_roles in CAPABILITIES:
            for role in _ROLES:
                if (role, key) in present:
                    result["kept"] += 1
                    continue
                bind.execute(
                    sa.text("INSERT INTO role_capabilities (id, tenant_id, role, capability_key, allowed, created_at, updated_at) "
                            "VALUES (:id, :t, :r, :k, :a, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                    {"id": str(uuid.uuid4()), "t": tenant_id, "r": role, "k": key, "a": role in allowed_roles},
                )
                result["cells"] += 1
    return result


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns(TABLE)}
    if "option_rank" not in cols:
        op.add_column(TABLE, sa.Column("option_rank", sa.SmallInteger(), nullable=False, server_default="1"))
    if "option_group_id" not in cols:
        op.add_column(TABLE, sa.Column("option_group_id", sa.String(), nullable=True))
    if INDEX not in {i["name"] for i in sa.inspect(bind).get_indexes(TABLE)}:
        op.create_index(INDEX, TABLE, ["option_group_id"])
    visible = bind.execute(sa.text("SELECT count(*) FROM role_capabilities")).scalar() or 0
    tenants = bind.execute(sa.text("SELECT count(*) FROM tenants")).scalar() or 0
    if tenants and not visible:
        log.warning("140: %s tenant(s) but no role_capabilities rows are visible (unprovisioned, or this role is subject to RLS); "
                    "no cells will be added.", tenants)
    log.info("140: quote capabilities -> %s", apply_capabilities(bind))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if INDEX in {i["name"] for i in insp.get_indexes(TABLE)}:
        op.drop_index(INDEX, table_name=TABLE)
    cols = {c["name"] for c in insp.get_columns(TABLE)}
    for col in ("option_group_id", "option_rank"):
        if col in cols:
            op.drop_column(TABLE, col)
    for key, *_ in CAPABILITIES:
        bind.execute(sa.text("DELETE FROM role_capabilities WHERE capability_key = :k"), {"k": key})
        bind.execute(sa.text("DELETE FROM capabilities WHERE key = :k"), {"k": key})
