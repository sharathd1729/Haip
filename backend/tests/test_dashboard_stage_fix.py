"""
Regression tests: GET /dashboard's active_inquiries count used to filter
Inquiry.stage.not_in([BOOKED, LOST, GHOSTED]) -- the legacy enum every
auto-created inquiry permanently leaves at NEW. Fixed to resolve won/lost
via stage_id/pipeline_stages instead. Also covers the new
chat_response_p95_seconds field added to the same response.
"""
import uuid
from datetime import datetime, timezone, timedelta
import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.models.pipeline_stage import PipelineStage
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.api.v1.endpoints.dashboard import get_dashboard

# get_dashboard() always computes chat_response_p95_seconds via a
# Postgres-only percentile_cont() query (same pattern as the pre-existing
# call-duration p95 in analytics.py) -- skip under the default local SQLite
# test run; CI's Postgres testcontainer runs these for real.
pytestmark = pytest.mark.skipif(
    "sqlite" in __import__("os").environ.get("DATABASE_URL", "sqlite"),
    reason="requires Postgres (percentile_cont)",
)


def _make_tenant(db, name="TenantDash"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"dash-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_user(db, tenant_id):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name="Owner", email=f"{uuid.uuid4().hex[:8]}@test.com",
        hashed_password="x", role=UserRole.OWNER, is_active=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_guest(db, tenant_id):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone="")
    db.add(g)
    db.flush()
    return g


def _make_stage(db, tenant_id, key, order, **kwargs):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key=key, label=key.title(), order=order, **kwargs)
    db.add(s)
    db.flush()
    return s


def _make_inquiry(db, tenant_id, guest_id, stage_id):
    inq = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
        stage=InquiryStage.NEW, stage_id=stage_id, source=InquirySource.WA_DIRECT,
    )
    db.add(inq)
    db.flush()
    return inq


def test_active_inquiries_excludes_won_and_lost_via_stage_id(db):
    tenant = _make_tenant(db)
    user = _make_user(db, tenant.id)
    guest = _make_guest(db, tenant.id)
    active_stage = _make_stage(db, tenant.id, "active", 0, category="valid", is_valid_lead_entry=True)
    sold_stage = _make_stage(db, tenant.id, "sold", 1, category="valid", is_closed_won=True)
    lost_stage = _make_stage(db, tenant.id, "lost", 2, category="valid", is_closed_lost=True)

    _make_inquiry(db, tenant.id, guest.id, active_stage.id)
    _make_inquiry(db, tenant.id, guest.id, active_stage.id)
    _make_inquiry(db, tenant.id, guest.id, sold_stage.id)
    _make_inquiry(db, tenant.id, guest.id, lost_stage.id)
    db.commit()

    result = get_dashboard(db=db, current_user=user)

    assert result["active_inquiries"] == 2


def test_chat_response_p95_computed_from_messages(db):
    tenant = _make_tenant(db)
    user = _make_user(db, tenant.id)
    guest = _make_guest(db, tenant.id)
    convo = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, channel=ChannelType.WHATSAPP)
    db.add(convo)
    db.flush()

    inbound_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    outbound_at = inbound_at + timedelta(seconds=90)
    db.add(Message(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=convo.id,
        direction=MessageDirection.INBOUND, channel=ChannelType.WHATSAPP, body="hi",
        created_at=inbound_at,
    ))
    db.add(Message(
        id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=convo.id,
        direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP, body="hello!",
        created_at=outbound_at,
    ))
    db.commit()

    result = get_dashboard(db=db, current_user=user)

    assert result["chat_response_p95_seconds"] == pytest.approx(90, abs=1)
