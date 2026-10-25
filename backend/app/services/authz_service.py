"""Capability-based authorization (HAIP_MCP_Connector_Plan.md Phase 1,
target architecture §1). This is the *only* place that reads
`role_capabilities` -- REST endpoints and the MCP layer must both call
through here so they can never disagree (plan's invariant #2: "the MCP
layer owns zero permission rules").

A tenant with zero `role_capabilities` rows at all is unprovisioned (the
backfill in migration 057 should have prevented this for every tenant
that existed at deploy time, but a tenant created after a rollback/restore
gap could still land here) -- fails closed, same lesson as
get_workspace_context's zero-row handling for modules.
"""
import structlog
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.cache import _rget, _rset
from app.core.database import get_db
from app.models.capability import Capability, RoleCapability
from app.models.user import User
from app.api.v1.deps import get_current_user

log = structlog.get_logger()

_CACHE_TTL = 300  # seconds

# Default role matrix (HAIP_MCP_Connector_Plan.md §2.3, "finance" column
# dropped per product decision 2026-08-02 -- UserRole has no FINANCE
# member). Duplicated from migration 057's one-time backfill copy rather
# than imported from it -- same convention as pipeline_stage_service's
# _DEFAULT_TAXONOMY vs. migrations 043/049's own inline seed SQL: a
# migration is a frozen snapshot of "what to do at that revision" and must
# not import live app code that can change after the migration ships.
# This copy is the one used for provisioning *new* tenants going forward.
_ROLES = ("owner", "manager", "reservations", "concierge", "foh", "marketing", "compliance", "read_only")

_DEFAULT_GRANTS: dict[str, set[str]] = {
    "leads.read": {"owner", "manager", "reservations", "concierge", "foh", "marketing", "read_only"},
    "leads.write": {"owner", "manager", "reservations", "concierge"},
    "leads.merge": {"owner", "manager"},
    "conversations.read": {"owner", "manager", "reservations", "concierge", "foh", "read_only"},
    "conversations.send": {"owner", "manager", "reservations", "concierge", "foh"},
    "calls.read": {"owner", "manager", "reservations", "concierge", "marketing", "read_only"},
    "calls.transcript.read": {"owner", "manager", "reservations", "concierge", "compliance"},
    "calls.recording.read": {"owner", "manager", "compliance"},
    "guests.read": {"owner", "manager", "reservations", "concierge", "foh", "marketing", "compliance", "read_only"},
    "guests.pii.reveal": {"owner", "manager", "reservations", "concierge", "compliance"},
    "bookings.read": {"owner", "manager", "reservations", "concierge", "foh", "read_only"},
    "revenue.read": {"owner", "manager", "marketing"},
    # Role-aware dashboard rebuild: agent-facing roles get their own scoped
    # view (endpoint scopes internally by current_user.id, this capability
    # just admits them past the door) instead of being locked out entirely.
    "analytics.read": {"owner", "manager", "reservations", "concierge", "foh", "marketing", "read_only"},
    "qa.read": {"owner", "manager", "concierge", "compliance", "read_only"},
    "qa.override": {"owner", "manager"},
    "compliance.export": {"owner", "compliance"},
    "users.read": {"owner", "manager", "compliance"},
    "users.manage": {"owner"},
    "settings.manage": {"owner"},
    # Quote builder (migration 140 adds these cells for existing tenants).
    "quotes.write": {"owner", "manager", "reservations", "concierge"},
    "business_data.draft": {"owner", "manager", "reservations"},
    "business_data.publish": {"owner", "manager"},
    # Marketing Studio (migration 153). Approve is owner + manager by owner decision D3
    # (docs/marketing-website/PHASE0_AUDIT.md); nobody may approve a version they wrote or asked the AI for, except the owner.
    "marketing.read": {"owner", "manager", "marketing"},
    "marketing.edit": {"owner", "manager", "marketing"},
    "marketing.approve": {"owner", "manager"},
    # Website builder (migration 158). Same split as Marketing Studio: approve/publish = owner + manager, and nobody but
    # the owner may approve a version they wrote or asked the AI developer for.
    "website.read": {"owner", "manager", "marketing"},
    "website.edit": {"owner", "manager", "marketing"},
    "website.approve": {"owner", "manager"},
    # Operations module (migration 178 grants these to existing tenants).
    "ops.read": {"owner", "manager", "reservations", "concierge", "foh"},
    "ops.write": {"owner", "manager", "concierge", "foh"},
    "ops.manage": {"owner", "manager"},
}


def seed_default_capabilities(db: Session, tenant_id: str) -> None:
    """Seed the full role_capabilities matrix for a new tenant from the
    default grants above. Idempotent -- a tenant that already has rows is
    left untouched (safe to call from both /auth/register and any future
    one-off backfill)."""
    existing = db.query(RoleCapability.id).filter_by(tenant_id=tenant_id).first()
    if existing is not None:
        return

    cap_keys = [k for (k,) in db.query(Capability.key).all()]
    if not cap_keys:
        # Catalogue itself is unseeded (e.g. a fresh install whose migration
        # 057 hasn't run yet) -- nothing to grant against. Log and bail
        # rather than silently creating a matrix with unknown keys.
        log.error("capability_catalogue_empty", tenant_id=tenant_id)
        return

    rows = [
        RoleCapability(tenant_id=tenant_id, role=role, capability_key=key, allowed=role in _DEFAULT_GRANTS.get(key, set()))
        for key in cap_keys
        for role in _ROLES
    ]
    db.add_all(rows)
    db.commit()


def _cache_key(tenant_id: str, role: str) -> str:
    return f"cap:{tenant_id}:{role}"


def get_capabilities(db: Session, user: User) -> set[str]:
    """Returns the set of capability keys granted to this user's role in
    their tenant. Empty set means "no capabilities" -- callers must treat
    that as a real denial, not a fallback-to-permissive case."""
    tenant_id = user.tenant_id
    role = user.role.value if hasattr(user.role, "value") else user.role

    cached = _rget(_cache_key(tenant_id, role))
    if cached is not None:
        return set(cached)

    # Distinguish "unprovisioned tenant" (zero rows at all) from "this role
    # legitimately has zero granted capabilities" (rows exist, all denied).
    any_row = db.query(RoleCapability.id).filter_by(tenant_id=tenant_id).first()
    if any_row is None:
        log.error("tenant_capabilities_unprovisioned", tenant_id=tenant_id)
        return set()

    rows = (
        db.query(RoleCapability.capability_key)
        .filter_by(tenant_id=tenant_id, role=role, allowed=True)
        .all()
    )
    capabilities = {r[0] for r in rows}
    _rset(_cache_key(tenant_id, role), list(capabilities), _CACHE_TTL)
    return capabilities


def has_capability(db: Session, user: User, key: str) -> bool:
    return key in get_capabilities(db, user)


def require_capability(*keys: str):
    """FastAPI dependency: 403s unless the current user's role has at least
    one of the given capabilities. Mirrors require_roles()'s shape in
    deps.py so it can be dropped into any endpoint the same way."""
    def _check(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        granted = get_capabilities(db, current_user)
        if not any(k in granted for k in keys):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user
    return _check
