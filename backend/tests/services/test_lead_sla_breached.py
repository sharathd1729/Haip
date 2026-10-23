"""GET /api/v1/leads ``sla_breached`` follows the work queue's SLA, not a dead column.

Bug (Oct 2026, live): every lead showed sla_breached=false, including guests waiting 3-5.6 days
(response_time_status "waiting", 270876 s and 485824 s). _build_lead_card read Inquiry.sla_breached, a column no code
writes. It is now computed from the batch response time with work_queue_service.severity_for("reply", ...), the same
SLA_MINUTES rule My day and the alerts use.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.tenant import Tenant
from app.services import leads_service, work_queue_service

REPLY_SLA_SECONDS = work_queue_service.SLA_MINUTES["reply"][0] * 60


@pytest.mark.parametrize("response_time,expected", [
    ((270876, "waiting"), True),             # the live 3-day wait
    ((485824, "waiting"), True),             # the live 5.6-day wait
    ((REPLY_SLA_SECONDS + 60, "waiting"), True),
    ((REPLY_SLA_SECONDS - 60, "waiting"), False),
    ((60, "waiting"), False),
    ((485824, "responded"), False),          # answered: no longer breaching
    (None, False),                           # no messages at all
])
def test_sla_breached_uses_the_work_queue_reply_sla(response_time, expected):
    now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    assert leads_service._sla_breached(response_time, now) is expected


def test_matches_severity_for_exactly():
    now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    for seconds in (0, REPLY_SLA_SECONDS - 1, REPLY_SLA_SECONDS, 3 * 3600, 5 * 86400):
        expected = work_queue_service.severity_for("reply", now - timedelta(seconds=seconds), now) != "fresh"
        assert leads_service._sla_breached((seconds, "waiting"), now) is expected


def _lead(db, *, waited: timedelta, answered: bool = False):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(tenant)
    db.flush()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Meera", phone=f"+91{uuid.uuid4().int % 10**10:010d}")
    db.add(guest)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, source=InquirySource.WA_DIRECT)
    db.add(inq)
    db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, inquiry_id=inq.id,
                        channel=ChannelType.WHATSAPP)
    db.add(conv)
    db.flush()
    at = datetime.now(timezone.utc) - waited
    msgs = [(MessageDirection.INBOUND, at)]
    if answered:
        msgs.append((MessageDirection.OUTBOUND, at + timedelta(minutes=5)))
    for direction, created in msgs:
        m = Message(id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id, direction=direction,
                    channel=ChannelType.WHATSAPP, body="hi")
        db.add(m)
        db.flush()
        m.created_at = created
    db.flush()
    return tenant.id, inq.id


def _card(db, tenant_id, inquiry_id):
    return next((c for c in leads_service.get_leads_pipeline(db, tenant_id).leads if c.inquiry_id == inquiry_id), None)


def test_a_lead_waiting_five_days_is_breached_in_the_list(db):
    tid, iid = _lead(db, waited=timedelta(days=5))
    card = _card(db, tid, iid)
    assert card.response_time_status == "waiting" and card.sla_breached is True


def test_a_fresh_or_answered_lead_is_not_breached(db):
    tid, iid = _lead(db, waited=timedelta(minutes=5))
    assert _card(db, tid, iid).sla_breached is False
    tid2, iid2 = _lead(db, waited=timedelta(days=5), answered=True)
    card = _card(db, tid2, iid2)
    assert card.response_time_status == "responded" and card.sla_breached is False


def test_the_detail_card_agrees(db):
    tid, iid = _lead(db, waited=timedelta(days=5))
    assert leads_service.get_lead_detail(db, tid, iid).sla_breached is True


def test_another_tenant_never_sees_the_breached_lead(db):
    tid, iid = _lead(db, waited=timedelta(days=5))
    other, other_iid = _lead(db, waited=timedelta(minutes=5))
    ids = [c.inquiry_id for c in leads_service.get_leads_pipeline(db, other).leads]
    assert iid not in ids and other_iid in ids
    assert all(c.sla_breached is False for c in leads_service.get_leads_pipeline(db, other).leads)
