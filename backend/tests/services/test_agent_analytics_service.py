"""Tests for Phase 2.5 agent-accountability read helper
(HAIP_Agent_Analytics_Dashboard_Plan_1.md #2.5.5).

get_conversion_actor() reads InquiryStageLog.changed_by rather than needing
a new table -- these tests exercise the real update_stage_by_id() write
path (not a mock) so the read helper is verified against what that path
actually writes.
"""
import uuid

from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.services.inquiry_service import update_stage_by_id
from app.services.agent_analytics_service import get_conversion_actor


def _make_stage(db, tenant_id, key, order, is_closed_won=False):
    stage = PipelineStage(
        id=str(uuid.uuid4()), tenant_id=tenant_id, key=key, label=key.title(),
        order=order, is_closed_won=is_closed_won,
    )
    db.add(stage)
    db.flush()
    return stage


def _make_inquiry(db, tenant_id, stage_id):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Conversion Guest", phone=f"+9199990{uuid.uuid4().hex[:5]}")
    db.add(guest)
    db.flush()
    inquiry = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, stage_id=stage_id)
    db.add(inquiry)
    db.flush()
    return inquiry


def test_returns_actor_who_moved_inquiry_to_closed_won(db, tenant_and_user):
    tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
    actor_id = tenant_and_user["user"]["id"] if isinstance(tenant_and_user["user"], dict) else tenant_and_user["user"].id

    active = _make_stage(db, tenant_id, "active", order=1)
    sold = _make_stage(db, tenant_id, "sold", order=2, is_closed_won=True)
    inquiry = _make_inquiry(db, tenant_id, active.id)
    db.commit()

    update_stage_by_id(
        db, tenant_id=tenant_id, inquiry_id=inquiry.id, new_stage_id=sold.id,
        actor_user_id=actor_id, actor_role="owner",
    )
    db.commit()

    assert get_conversion_actor(db, tenant_id, inquiry.id) == actor_id


def test_returns_none_when_inquiry_never_closed_won(db, tenant_and_user):
    tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
    active = _make_stage(db, tenant_id, "active", order=1)
    _make_stage(db, tenant_id, "sold", order=2, is_closed_won=True)
    inquiry = _make_inquiry(db, tenant_id, active.id)
    db.commit()

    assert get_conversion_actor(db, tenant_id, inquiry.id) is None


def test_tenant_isolation_does_not_leak_across_tenants(db, tenant_and_user):
    from app.models.tenant import Tenant
    from app.models.user import User, UserRole
    from app.core.security import get_password_hash

    tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
    actor_id = tenant_and_user["user"]["id"] if isinstance(tenant_and_user["user"], dict) else tenant_and_user["user"].id

    active = _make_stage(db, tenant_id, "active", order=1)
    sold = _make_stage(db, tenant_id, "sold", order=2, is_closed_won=True)
    inquiry = _make_inquiry(db, tenant_id, active.id)
    db.commit()
    update_stage_by_id(
        db, tenant_id=tenant_id, inquiry_id=inquiry.id, new_stage_id=sold.id,
        actor_user_id=actor_id, actor_role="owner",
    )
    db.commit()

    other_tenant = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other_tenant)
    db.flush()
    other_user = User(
        id=str(uuid.uuid4()), tenant_id=other_tenant.id, name="Other Owner",
        email=f"o-{uuid.uuid4().hex[:6]}@test.com", hashed_password=get_password_hash("pw"),
        role=UserRole.OWNER, is_active=True,
    )
    db.add(other_user)
    db.commit()

    # Same inquiry_id string won't exist for the other tenant at all, but
    # the real isolation guarantee under test is that a query scoped to
    # other_tenant.id can never resolve this tenant's inquiry/log rows.
    assert get_conversion_actor(db, other_tenant.id, inquiry.id) is None
