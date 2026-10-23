"""A small seeded workspace for the analyst + learning tests: owner / manager / foh, contacts (some became leads), enquiries,
a booking, an inbound missed call. Everything dated inside YESTERDAY (IST) so the daily pulse covers it."""
import uuid
from datetime import date, datetime, time, timedelta, timezone

from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.property import Property, Stay
from app.models.user import UserRole
from app.services.date_presets import IST
from tests.test_increment1_defect_specs import _tenant, _user


class W:
    pass


def yesterday_at(hour: int, today: date | None = None) -> datetime:
    d = (today or datetime.now(IST).date()) - timedelta(days=1)
    return datetime.combine(d, time(hour, 0), tzinfo=IST).astimezone(timezone.utc)


def world(db, *, contacts: int = 4, leads: int = 2, brand_config: dict | None = None) -> W:
    w = W()
    from app.models.capability import Capability
    from app.services import authz_service
    for key in authz_service._DEFAULT_GRANTS:          # the catalogue first, so the tenant's matrix includes revenue.read
        if db.query(Capability).filter_by(key=key).first() is None:
            db.add(Capability(key=key, label=key, category=key.split(".")[0], is_write=False, risk="medium"))
    db.flush()
    w.t = _tenant(db)
    w.t.brand_name = "Rathaa Test"
    w.t.brand_config = brand_config or {}
    w.owner = _user(db, w.t.id, UserRole.OWNER)
    w.mgr = _user(db, w.t.id, UserRole.MANAGER)
    w.foh = _user(db, w.t.id, UserRole.FOH)
    w.prop = Property(id=str(uuid.uuid4()), tenant_id=w.t.id, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:6]}", type="caravan",
                      max_adults=6, max_children=0)
    db.add(w.prop)
    w.guests, w.convs, w.inqs = [], [], []
    at = yesterday_at(11)
    for i in range(contacts):
        is_lead = i < leads
        g = Guest(id=str(uuid.uuid4()), tenant_id=w.t.id, name=f"Guest{i} Kumar", phone=f"+91984560{i:04d}" if is_lead else "",
                  created_at=at, lead_identified_at=at if is_lead else None)
        db.add(g)
        db.flush()
        c = Conversation(id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True,
                         created_at=at)
        db.add(c)
        db.flush()
        db.add(Message(id=str(uuid.uuid4()), tenant_id=w.t.id, conversation_id=c.id, direction="inbound", channel="whatsapp",
                       body=f"Hi, price for Goa trip? call me on 98456 1234{i}", created_at=at))
        w.guests.append(g)
        w.convs.append(c)
        if is_lead:
            inq = Inquiry(id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=g.id, adults=4, created_at=at, route_mentioned="Goa",
                          assigned_to=w.mgr.id)
            db.add(inq)
            w.inqs.append(inq)
    db.flush()
    w.stay = Stay(id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=w.guests[0].id, property_id=w.prop.id,
                  inquiry_id=w.inqs[0].id if w.inqs else None, check_in=date.today() + timedelta(days=20),
                  check_out=date.today() + timedelta(days=22), status="confirmed", total_amount=125000, created_at=at)
    db.add(w.stay)
    db.add(Call(id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=w.guests[0].id, agent_id=w.mgr.id, ivr_provider="vobiz",
                ivr_call_id=uuid.uuid4().hex, direction=CallDirection.INBOUND, from_number="+919845600000", to_number="+918000000000",
                duration_seconds=0, human_disposition="no_answer", created_at=at))
    db.commit()
    return w
