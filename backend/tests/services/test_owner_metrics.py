"""The two canonical metrics added for the owner dashboard (19 Oct 2026) and the first-touch fix, each with two workspaces:
``stays.booked_value`` (rental + add-ons, D-24), ``leads.qualified_dated`` (phone + check-in date) and the organic-call source."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.property import Property, Stay
from app.models.stay_finance import StayAddOn
from app.models.tenant import Tenant
from app.services import kpi_metrics, lead_metrics
from app.services.lead_state import channel_for_source

NOW = datetime.now(timezone.utc)
START, END = NOW - timedelta(days=1), NOW + timedelta(minutes=1)


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"om-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush()
    return t


def _guest(db, tid, phone=True, first_touch="whatsapp"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone="+919800000000" if phone else "", first_touch_channel=first_touch,
              lead_identified_at=NOW - timedelta(hours=1) if phone else None)
    db.add(g); db.flush()
    return g


def _booking(db, tid, amount, addons=(), status="confirmed"):
    p = Property(id=str(uuid.uuid4()), tenant_id=tid, name="P", slug=f"p-{uuid.uuid4().hex[:4]}", type="villa")
    db.add(p); db.flush()
    g = _guest(db, tid)
    s = Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, property_id=p.id, check_in=NOW.date(), check_out=NOW.date() + timedelta(days=1),
             status=status, total_amount=amount, created_at=NOW - timedelta(hours=1))
    db.add(s); db.flush()
    for qty, price in addons:
        db.add(StayAddOn(tenant_id=tid, stay_id=s.id, name="x", quantity=qty, unit_price=price))
    db.flush()
    return s


def test_booked_value_is_rental_plus_add_ons_for_one_workspace(db):
    a, b = _tenant(db), _tenant(db)
    _booking(db, a.id, 10000, addons=[(2, 500), (1, 1000)])
    _booking(db, a.id, 5000)
    _booking(db, a.id, 9999, addons=[(1, 1)], status="cancelled")      # cancelled: not booked
    _booking(db, b.id, 77777, addons=[(1, 23)])
    db.commit()
    assert kpi_metrics.booked_value(db, a.id, START, END) == {"count": 2, "rental": 15000.0, "add_ons": 2000.0, "total": 17000.0}
    assert kpi_metrics.booked_value(db, b.id, START, END)["total"] == 77800.0
    assert kpi_metrics.booked_value(db, a.id, NOW + timedelta(days=1), NOW + timedelta(days=2))["count"] == 0


def test_a_qualified_lead_has_a_phone_and_a_check_in_date(db):
    a, b = _tenant(db), _tenant(db)
    for tid, check_in, status in ((a.id, "2026-12-01", "qualified"), (a.id, None, "qualified"), (a.id, "2026-12-01", "unqualified"),
                                  (b.id, "2026-12-01", "qualified")):
        g = _guest(db, tid)
        db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, stage=InquiryStage.NEW, check_in=check_in,
                       qualification_status=status, created_at=NOW))
    no_phone = _guest(db, a.id, phone=False)
    db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=a.id, guest_id=no_phone.id, stage=InquiryStage.NEW, check_in="2026-12-01", created_at=NOW))
    db.commit()
    assert lead_metrics.count_qualified_dated(db, a.id, START, END) == 1
    assert lead_metrics.count_qualified_dated(db, b.id, START, END) == 1


def test_organic_calls_are_a_first_touch_of_their_own(db):
    a, b = _tenant(db), _tenant(db)
    for tid, touch, source in ((a.id, "call", InquirySource.ORGANIC_CALL), (a.id, None, InquirySource.ORGANIC_CALL),
                               (a.id, "call", InquirySource.PHONE), (a.id, None, None), (b.id, "call", InquirySource.ORGANIC_CALL)):
        g = _guest(db, tid, first_touch=touch)
        if source is not None:
            db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, stage=InquiryStage.NEW, source=source, created_at=NOW))
    db.commit()
    rows = {r["key"]: r["leads"] for r in lead_metrics.by_first_touch(db, a.id, START, END, with_bookings=False)}
    assert rows == {"organic_call": 2, "call": 1, "unknown": 1}
    assert lead_metrics.count_new_leads(db, a.id, START, END, channel="organic_call") == 2
    assert lead_metrics.count_new_leads(db, a.id, START, END, channel="call") == 3      # calls include the organic ones
    assert {r["key"]: r["leads"] for r in lead_metrics.by_first_touch(db, b.id, START, END, with_bookings=False)} == {"organic_call": 1}
    assert channel_for_source("organic_call") == "organic_call" and channel_for_source("web_form") == "website"
