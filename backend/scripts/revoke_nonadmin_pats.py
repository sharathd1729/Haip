"""
0.8 (HAIP_MCP_Connector_Plan.md, Phase 0): revoke every existing PAT whose
user's current role is not owner/manager.

Ticket 0.6 (issuance gate) only blocks *new* tokens from being minted by a
non-owner/manager user -- any PAT issued before this phase, or held by a
user who has since been demoted, stays valid until this runs once. Not a
migration (no schema change), a one-off data fix -- see the plan's own
"do not skip" note on this exact ticket.

Run once after Phase 0's code changes are deployed:
  cd backend && python scripts/revoke_nonadmin_pats.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.core.audit import append_audit
from app.models.mcp_token import PersonalAccessToken
from app.models.user import User, UserRole

_ALLOWED_ROLES = {UserRole.OWNER, UserRole.MANAGER}


def main():
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        # Join to User for the role check -- PersonalAccessToken has no RLS
        # (migration 055's own docstring: token lookup happens before tenant
        # is known), so this query is intentionally not tenant_id-scoped;
        # it needs to see every tenant's tokens in one pass.
        rows = (
            db.query(PersonalAccessToken, User)
            .join(User, User.id == PersonalAccessToken.user_id)
            .filter(PersonalAccessToken.revoked_at.is_(None))
            .all()
        )

        revoked = 0
        for token, user in rows:
            if user.role in _ALLOWED_ROLES:
                continue
            token.revoked_at = now
            # append_audit filters/writes by the tenant_id argument directly
            # (not session-level RLS context), so no set_tenant_context()
            # needed even though this script walks every tenant in one pass.
            append_audit(
                db,
                tenant_id=token.tenant_id,
                action="mcp_token.revoked_nonadmin_backfill",
                actor_user_id=None,  # system action, not a human actor
                target_type="personal_access_token",
                target_id=token.id,
                payload={"token_user_id": user.id, "token_user_role": user.role.value, "token_name": token.name},
            )
            revoked += 1
            print(f"  revoked token {token.id!r} ({token.name!r}) — user {user.email} is role={user.role.value}")

        db.commit()
        print(f"Done. Revoked {revoked} of {len(rows)} active PAT(s) held by non-owner/manager users.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
