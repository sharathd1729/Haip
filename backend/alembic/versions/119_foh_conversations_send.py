"""Grant 'conversations.send' to the front-of-house (foh) role for existing tenants.

Product policy (Oct 2026): front-of-house staff reply to guests and use the AI rewrite buttons.
authz_service._DEFAULT_GRANTS now includes foh for conversations.send, but that dict only provisions NEW tenants:
existing tenants' role_capabilities rows were seeded at migration 057 (foh = denied) and never pick up dict changes
(the same situation as migration 076, which granted analytics.read). The REST send routes now require this capability,
so without this migration front-of-house staff of every existing tenant would be refused when replying to guests.

What it does, per tenant (portable SQL; no PostgreSQL-only features, so the logic is tested on SQLite too):
  * foh / conversations.send is DENIED  -> set to allowed, UNLESS the tenant's owner ever edited that exact cell.
    Every owner edit goes through PUT /capabilities/matrix, which writes an audit event 'role_capabilities.change'
    whose payload lists the cells touched. A tenant with such an event for (foh, conversations.send) made a deliberate
    choice and is left exactly as it is. Edits made directly in the database leave no trace and cannot be detected.
  * the tenant is provisioned (has other role_capabilities rows) but has NO foh / conversations.send row -> insert it as
    allowed (the cell is missing; there is nothing to customise).
  * a tenant with no role_capabilities rows at all is unprovisioned and is NOT touched (it keeps failing closed).
  * no other role or capability is changed, and one tenant's rows or audit events never affect another's.
Idempotent: a second run finds nothing denied and nothing missing, and changes nothing.

Row-level security: role_capabilities has FORCE row-level security, so this migration only sees rows when the database
role running it bypasses RLS (as the earlier data migrations 057 and 076 already assume). If it ran under a role that is
subject to RLS it would silently see nothing and change nothing; it therefore logs the counts it saw and warns when
tenants exist but no capability rows are visible. Operators can confirm the result per tenant with this read-only query
(set the tenant context first, because of FORCE RLS):
    SELECT set_config('app.tenant_id', '<tenant id>', true);
    SELECT role, allowed FROM role_capabilities WHERE capability_key = 'conversations.send' ORDER BY role;
Expected by default: owner, manager, reservations, concierge and foh allowed; marketing, compliance, read_only denied.

Downgrade: a version-marker move only. It deliberately does not re-deny foh (that could undo an owner's later decision,
and code that predates the policy ignores the extra grant). To roll the code back run `alembic downgrade 117` with THIS
image first, then start the older image (an older image does not contain revision 119).

Numbering: 118 is reserved for the PROPOSED row-level-security migration in alembic/proposed/, which is deliberately not
in this chain. This revision therefore follows 117 directly. When 118 is promoted, change its down_revision to '119'
(otherwise Alembic reports two heads).

Revision ID: 119
Revises: 117
"""
import json
import logging
import uuid

import sqlalchemy as sa
from alembic import op

revision = "119"
down_revision = "117"
branch_labels = None
depends_on = None

ROLE = "foh"
CAPABILITY = "conversations.send"
AUDIT_ACTION = "role_capabilities.change"

log = logging.getLogger("alembic.runtime.migration")


def _owner_edited_this_cell(payload) -> bool:
    """True if an audit payload ({"edits": [{"role", "capability_key", "allowed"}, ...]}) touched (foh, conversations.send)."""
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except ValueError:
            return False
    if not isinstance(payload, dict):
        return False
    return any(
        isinstance(e, dict) and e.get("role") == ROLE and e.get("capability_key") == CAPABILITY
        for e in (payload.get("edits") or [])
    )


def apply_grant(bind) -> dict:
    """Grant foh conversations.send where appropriate. Returns counts; safe to call repeatedly."""
    result = {"granted": 0, "inserted": 0, "preserved_customised": 0, "skipped_no_catalogue": 0}

    if bind.execute(sa.text("SELECT 1 FROM capabilities WHERE key = :k"), {"k": CAPABILITY}).first() is None:
        log.warning("119: capability %r is not in the catalogue; nothing to grant", CAPABILITY)
        result["skipped_no_catalogue"] = 1
        return result

    customised = {
        tenant_id
        for tenant_id, payload in bind.execute(
            sa.text("SELECT tenant_id, payload FROM audit_events WHERE action = :a"), {"a": AUDIT_ACTION}
        )
        if _owner_edited_this_cell(payload)
    }

    denied = bind.execute(
        sa.text("SELECT id, tenant_id FROM role_capabilities WHERE role = :r AND capability_key = :k AND allowed = :no"),
        {"r": ROLE, "k": CAPABILITY, "no": False},
    ).all()
    for row_id, tenant_id in denied:
        if tenant_id in customised:
            result["preserved_customised"] += 1
            continue
        bind.execute(
            sa.text("UPDATE role_capabilities SET allowed = :yes, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = :id AND allowed = :no"),
            {"yes": True, "no": False, "id": row_id},
        )
        result["granted"] += 1

    missing = bind.execute(
        sa.text(
            "SELECT DISTINCT tenant_id FROM role_capabilities WHERE tenant_id NOT IN "
            "(SELECT tenant_id FROM role_capabilities WHERE role = :r AND capability_key = :k)"
        ),
        {"r": ROLE, "k": CAPABILITY},
    ).all()
    for (tenant_id,) in missing:
        if tenant_id in customised:
            result["preserved_customised"] += 1
            continue
        bind.execute(
            sa.text("INSERT INTO role_capabilities (id, tenant_id, role, capability_key, allowed, created_at, updated_at) "
                    "VALUES (:id, :t, :r, :k, :yes, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
            {"id": str(uuid.uuid4()), "t": tenant_id, "r": ROLE, "k": CAPABILITY, "yes": True},
        )
        result["inserted"] += 1
    return result


def upgrade():
    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT count(*) FROM tenants")).scalar() or 0
    visible = bind.execute(sa.text("SELECT count(*) FROM role_capabilities")).scalar() or 0
    if tenants and not visible:
        log.warning("119: %s tenant(s) exist but no role_capabilities rows are visible to this database role "
                    "(unprovisioned tenants, or the role is subject to row-level security). Nothing will be changed.", tenants)
    result = apply_grant(bind)
    log.info("119: foh conversations.send -> %s (tenants=%s, capability rows visible=%s)", result, tenants, visible)


def downgrade():
    # Deliberately a marker move only; see the module docstring.
    pass
