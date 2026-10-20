"""scripts/mark_past_bookings_paid.py: an ended, not-cancelled booking that still owes money gets ONE manual payment for exactly
the balance (audited, nothing sent to the guest), a dry run writes nothing, upcoming / cancelled / paid bookings and other
workspaces are untouched, and a second run finds nothing."""
import importlib.util
import uuid
from datetime import date, timedelta
from pathlib import Path

from app.models.audit_event import AuditEvent
from app.models.guest import Guest
from app.models.property import Property, Stay
from app.models.stay_finance import StayPayment
from app.models.tenant import Tenant

_spec = importlib.util.spec_from_file_location(
    "mark_paid", Path(__file__).resolve().parents[1] / "scripts" / "mark_past_bookings_paid.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

TODAY = date(2026, 10, 20)


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _stay(db, tid, days_ago_in, days_ago_out, status="checked_out", total=25000, paid=0):
    prop = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:6]}")
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Sample Guest")
    db.add_all([prop, g])
    db.flush()
    s = Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, property_id=prop.id, status=status, total_amount=total,
             check_in=TODAY - timedelta(days=days_ago_in), check_out=TODAY - timedelta(days=days_ago_out))
    db.add(s)
    db.flush()
    if paid:
        db.add(StayPayment(tenant_id=tid, stay_id=s.id, kind="payment", amount=paid, method="upi", paid_on=s.check_in))
    db.commit()
    return s


def _payments(db, stay):
    return db.query(StayPayment).filter_by(stay_id=stay.id).all()


def test_dry_run_lists_and_writes_nothing(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    s = _stay(db, tid, 10, 8)
    rows = script.mark_paid(db, tid, apply=False, today=TODAY)
    assert [(r[0].id, float(r[1])) for r in rows] == [(s.id, 25000.0)]
    assert _payments(db, s) == []


def test_apply_records_exactly_the_balance_once_and_only_for_ended_bookings(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    owing = _stay(db, tid, 10, 8, total=50000, paid=20000)
    confirmed_past = _stay(db, tid, 5, 5, status="confirmed")
    upcoming = _stay(db, tid, -3, -5)
    in_progress = _stay(db, tid, 1, -1, status="checked_in")
    cancelled = _stay(db, tid, 20, 18, status="cancelled")
    settled = _stay(db, tid, 30, 28, total=25000, paid=25000)
    rows = script.mark_paid(db, tid, apply=True, today=TODAY)
    db.commit()
    assert {r[0].id for r in rows} == {owing.id, confirmed_past.id}
    new = [p for p in _payments(db, owing) if p.reference == script.REFERENCE]
    assert len(new) == 1 and float(new[0].amount) == 30000 and new[0].method == "other" and new[0].paid_on == owing.check_out
    assert len(_payments(db, confirmed_past)) == 1
    for s in (upcoming, in_progress, cancelled):
        assert _payments(db, s) == []
    assert len(_payments(db, settled)) == 1
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="booking.payment_recorded", target_id=owing.id).count() == 1
    assert script.mark_paid(db, tid, apply=True, today=TODAY) == []           # a second run finds nothing


def test_other_workspaces_are_never_touched(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    theirs = _stay(db, other.id, 10, 8)
    assert script.mark_paid(db, tid, apply=True, today=TODAY) == []
    db.commit()
    assert _payments(db, theirs) == []
