"""Regression test: analytics_executive.py's owner_daily funnel/active_inq
used to query the legacy Inquiry.stage enum (permanently stuck at NEW for
every auto-created inquiry since migration 049 replaced that flow) --
claude-fable-5-lovely-biscuit.md #3 rewired both to the tenant's real
pipeline_stages catalog via stage_id, matching the pattern
analytics_sections.py's channels endpoint already used.
"""
import uuid

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.module import Module, WorkspaceModule
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.core.security import create_access_token, get_password_hash


def _make_tenant_and_user(db):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(tenant)
    db.flush()
    user = User(
        id=str(uuid.uuid4()), tenant_id=tenant.id, name="Owner",
        email=f"o-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("pw"), role=UserRole.OWNER, is_active=True,
    )
    db.add(user)
    db.commit()
    token = create_access_token({"sub": user.id, "tenant_id": tenant.id, "role": user.role.value})
    return tenant, user, token


def _grant_module(db, tenant_id, code):
    module = db.query(Module).filter_by(code=code).first()
    if not module:
        module = Module(id=str(uuid.uuid4()), code=code, name=code.title())
        db.add(module)
        db.flush()
    db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=tenant_id, module_id=module.id, enabled=True))
    db.commit()


def test_funnel_groups_by_real_pipeline_stage_not_legacy_enum(client, db):
    tenant, user, token = _make_tenant_and_user(db)
    _grant_module(db, tenant.id, "analytics")

    active = PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant.id, key="active", label="Active", order=1)
    sold = PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant.id, key="sold", label="Sold", order=2, is_closed_won=True, category="valid")
    db.add_all([active, sold])
    db.flush()

    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="G", phone=f"+9199990{uuid.uuid4().hex[:5]}")
    db.add(guest)
    db.flush()
    # Every auto-created inquiry leaves the legacy Inquiry.stage enum
    # permanently at NEW -- this is the exact case the old code silently
    # miscounted (grouped everything under one "NEW" bucket regardless of
    # real stage_id).
    inquiry = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, stage_id=sold.id)
    db.add(inquiry)
    db.commit()

    resp = client.get("/api/v1/analytics/executive", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    funnel = resp.json()["funnel"]
    labels = [f["stage"] for f in funnel]
    assert "Sold" in labels
    sold_row = next(f for f in funnel if f["stage"] == "Sold")
    assert sold_row["count"] == 1
