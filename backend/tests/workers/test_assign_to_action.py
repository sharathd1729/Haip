"""assign_to one-click action -- lead-overlap prevention: a peer agent's
self-assign ("Assign to me") must not steal a lead another agent already
owns, or both agents end up contacting the same guest. Owners/managers keep
unrestricted reassignment via the explicit dropdown.
"""
import uuid

import pytest

from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.core.security import get_password_hash
from app.workers.tasks.automation_engine import dispatch_action


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.commit()
    return t


def _user(db, tenant_id, role=UserRole.CONCIERGE, name="Agent"):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
        email=f"{uuid.uuid4().hex[:8]}@test.com", hashed_password=get_password_hash("pw"),
        role=role, is_active=True,
    )
    db.add(u); db.commit()
    return u


def _inquiry(db, tenant_id, assigned_to=None):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest")
    db.add(guest); db.flush()
    inq = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
        source=list(InquirySource)[0], assigned_to=assigned_to,
    )
    db.add(inq); db.commit()
    return inq


class TestSelfAssignOverlapGuard:
    def test_agent_cannot_self_assign_a_lead_owned_by_someone_else(self, db):
        t = _tenant(db)
        owner_agent = _user(db, t.id, name="Krishna")
        other_agent = _user(db, t.id, name="Jishanth")
        inq = _inquiry(db, t.id, assigned_to=owner_agent.id)

        detail = dispatch_action(
            db, "assign_to", {"user_id": other_agent.id}, {"inquiry_id": inq.id}, t.id, actor=other_agent,
        )

        assert "skipped" in detail
        assert "Krishna" in detail
        db.expire_all()
        assert db.get(Inquiry, inq.id).assigned_to == owner_agent.id  # unchanged

    def test_agent_can_self_assign_an_unassigned_lead(self, db):
        t = _tenant(db)
        agent = _user(db, t.id)
        inq = _inquiry(db, t.id, assigned_to=None)

        detail = dispatch_action(
            db, "assign_to", {"user_id": agent.id}, {"inquiry_id": inq.id}, t.id, actor=agent,
        )

        assert "skipped" not in detail
        db.expire_all()
        assert db.get(Inquiry, inq.id).assigned_to == agent.id

    def test_agent_can_reclaim_their_own_lead(self, db):
        """Self-assigning a lead already assigned to yourself is a no-op
        allow, not a conflict."""
        t = _tenant(db)
        agent = _user(db, t.id)
        inq = _inquiry(db, t.id, assigned_to=agent.id)

        detail = dispatch_action(
            db, "assign_to", {"user_id": agent.id}, {"inquiry_id": inq.id}, t.id, actor=agent,
        )

        assert "skipped" not in detail

    def test_owner_can_reassign_a_lead_someone_else_already_owns(self, db):
        t = _tenant(db)
        owner_user = _user(db, t.id, role=UserRole.OWNER, name="Owner")
        first_agent = _user(db, t.id, name="Krishna")
        inq = _inquiry(db, t.id, assigned_to=first_agent.id)

        # Owner deliberately reassigns the lead to themselves via the dropdown.
        detail = dispatch_action(
            db, "assign_to", {"user_id": owner_user.id}, {"inquiry_id": inq.id}, t.id, actor=owner_user,
        )

        assert "skipped" not in detail
        db.expire_all()
        assert db.get(Inquiry, inq.id).assigned_to == owner_user.id

    def test_owner_can_reassign_between_two_other_agents(self, db):
        """The guard only fires on a SELF-assign click; an owner assigning
        the lead to a third party is unrestricted regardless of current owner."""
        t = _tenant(db)
        owner_user = _user(db, t.id, role=UserRole.OWNER, name="Owner")
        first_agent = _user(db, t.id, name="Krishna")
        second_agent = _user(db, t.id, name="Jishanth")
        inq = _inquiry(db, t.id, assigned_to=first_agent.id)

        detail = dispatch_action(
            db, "assign_to", {"user_id": second_agent.id}, {"inquiry_id": inq.id}, t.id, actor=owner_user,
        )

        assert "skipped" not in detail
        db.expire_all()
        assert db.get(Inquiry, inq.id).assigned_to == second_agent.id
