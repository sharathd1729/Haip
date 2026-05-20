"""
K14 — Round-robin auto-assignment service.

On inquiry creation, if no explicit assignee, assign to the next available
concierge/agent in the tenant's team.

State: `tenant.last_assigned_user_id` (string FK → users.id).
Algorithm: sort available users by email alphabetically; pick the one after
the last-assigned. Wraps around.
"""
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.tenant import Tenant
import structlog

log = structlog.get_logger()


def get_next_assignee(db: Session, tenant_id: str) -> str | None:
    """
    Return the user_id of the next assignee using round-robin, or None if
    no available agents exist.
    """
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    if not tenant:
        return None

    # Eligible roles: concierge, manager, owner
    eligible = (
        db.query(User)
        .filter_by(tenant_id=tenant_id, is_active=True, is_deleted=False)
        .filter(User.role.in_(["concierge", "manager", "owner"]))
        .filter(User.is_available_for_assignment == True)  # noqa: E712
        .order_by(User.email.asc())
        .all()
    )

    if not eligible:
        log.warning("round_robin_no_eligible_users", tenant_id=tenant_id)
        return None

    last_id = getattr(tenant, "last_assigned_user_id", None)

    if not last_id:
        chosen = eligible[0]
    else:
        ids = [u.id for u in eligible]
        try:
            idx = ids.index(last_id)
            chosen = eligible[(idx + 1) % len(eligible)]
        except ValueError:
            chosen = eligible[0]

    # Persist the last-assigned state
    tenant.last_assigned_user_id = chosen.id
    db.flush()   # don't commit here — let caller own the transaction

    log.info("round_robin_assigned", tenant_id=tenant_id, user_id=chosen.id)
    return chosen.id
