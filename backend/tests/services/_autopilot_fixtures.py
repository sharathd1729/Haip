"""Shared builders for the lead autopilot tests: a tenant with the real default pipeline taxonomy, a Ratha-shaped lead
(Kiran, WhatsApp, Bangalore -> Coorg caravan), messages, calls, quotes and bookings."""
import uuid
from datetime import date, datetime, timedelta, timezone

from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.tenant import Tenant
from app.services.pipeline_stage_service import seed_default_pipeline_stages

NOW = datetime(2026, 10, 18, 6, 30, tzinfo=timezone.utc)    # 12:00 IST


def tenant(db, mode=None, **settings):
    t = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"ap-{uuid.uuid4().hex[:8]}", plan="growth", is_active=True)
    if mode:
        t.brand_config = {"lead_autopilot": {"mode": mode, **settings}}
    db.add(t)
    db.flush()
    stages = {s.key: s for s in seed_default_pipeline_stages(db, t.id)}
    db.commit()
    return t, stages


def lead(db, tenant_id, stage, *, phone=True, entered=None, **kw):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Kiran", phone="+919845012345" if phone else None,
              lead_identified_at=NOW - timedelta(days=20) if phone else None)
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, stage_id=stage.id,
                  source=InquirySource.WA_DIRECT, created_at=NOW - timedelta(days=20),
                  current_stage_entered_at=entered or NOW - timedelta(days=20), **kw)
    db.add(inq)
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, inquiry_id=inq.id,
                        channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.commit()
    return g, inq, conv


def msg(db, tenant_id, conv, body, *, inbound=True, ago=timedelta(hours=1), **kw):
    m = Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
                direction=MessageDirection.INBOUND if inbound else MessageDirection.OUTBOUND,
                channel=ChannelType.WHATSAPP, body=body, created_at=NOW - ago, **kw)
    db.add(m)
    db.commit()
    return m


def call(db, tenant_id, guest_id, *, outbound=True, ago=timedelta(hours=2), **kw):
    defaults = dict(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id, ivr_provider="vobiz",
                    ivr_call_id=f"c-{uuid.uuid4().hex[:10]}",
                    direction=CallDirection.OUTBOUND if outbound else CallDirection.INBOUND,
                    from_number="+912271264296", to_number="+919845012345", duration_seconds=0,
                    created_at=NOW - ago)
    defaults.update(kw)
    c = Call(**defaults)
    db.add(c)
    db.commit()
    return c


def booking(db, tenant_id, guest_id, inquiry_id, days_ahead=10, status="confirmed"):
    from app.models.property import Property, Stay
    prop = Property(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Ratha 1", slug=f"r1-{uuid.uuid4().hex[:6]}")
    db.add(prop)
    db.flush()
    s = Stay(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id, property_id=prop.id, inquiry_id=inquiry_id,
             check_in=date(2026, 10, 18) + timedelta(days=days_ahead),
             check_out=date(2026, 10, 18) + timedelta(days=days_ahead + 2), status=status, total_amount=42000)
    db.add(s)
    db.commit()
    return s


def quote(db, tenant_id, inquiry_id, *, ago=timedelta(days=9), valid_days=None, link_status=None):
    from app.models.inquiry_360 import InquiryQuote
    from app.models.stay_finance import StayPaymentLink
    q = InquiryQuote(id=str(uuid.uuid4()), tenant_id=tenant_id, inquiry_id=inquiry_id, amount=42000, status="issued",
                     is_active=True, created_at=NOW - ago,
                     valid_until=(NOW + timedelta(days=valid_days)) if valid_days is not None else None)
    db.add(q)
    db.flush()
    if link_status:
        db.add(StayPaymentLink(id=str(uuid.uuid4()), tenant_id=tenant_id, inquiry_quote_id=q.id, external_id="plink_t1",
                               short_url="https://rzp.io/i/t1", amount=21000, status=link_status))
    db.commit()
    return q


def settings(**over):
    from app.schemas.lead_autopilot import AutopilotSettings
    return AutopilotSettings(**over).model_dump()
