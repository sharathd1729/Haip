"""scripts/mark_booked_leads_sold.py: leads with a live booking end up in Sold through the audited stage paths (Lost leads are
reopened first), unlinked bookings are tied only when the guest has exactly one candidate lead, and a second run changes
nothing. Other workspaces are never touched."""
import importlib.util
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.models.audit_event import AuditEvent
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, Stay
from app.models.tenant import Tenant

_spec = importlib.util.spec_from_file_location(
    "mark_sold", Path(__file__).resolve().parents[1] / "scripts" / "mark_booked_leads_sold.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _workspace(db, tid):
    stages = {
        "general_enquiry": PipelineStage(tenant_id=tid, key="general_enquiry", label="General Enquiry", category="invalid", order=1, is_default_entry=True),
        "active": PipelineStage(tenant_id=tid, key="active", label="Active", category="valid", order=3, is_valid_lead_entry=True),
        "lost": PipelineStage(tenant_id=tid, key="lost", label="Lost", category="valid", order=8, is_closed_lost=True),
        "sold": PipelineStage(tenant_id=tid, key="sold", label="Sold", category="valid", order=9, is_closed_won=True),
    }
    db.add_all(stages.values())
    prop = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Ratha 1", slug=f"ratha-1-{uuid.uuid4().hex[:6]}")
    db.add(prop)
    db.commit()
    return stages, prop


def _lead(db, tid, stage, lost_reason=None):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Guest", phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(guest)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, stage_id=stage.id, lost_reason=lost_reason)
    db.add(inq)
    db.commit()
    return guest, inq


def _stay(db, tid, prop, guest, inquiry=None, status="confirmed"):
    s = Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, property_id=prop.id, inquiry_id=inquiry.id if inquiry else None,
             check_in=date.today() - timedelta(days=10), check_out=date.today() - timedelta(days=8), status=status)
    db.add(s)
    db.commit()
    return s


def test_open_and_lost_leads_with_bookings_become_sold(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    st, prop = _workspace(db, tid)
    g1, open_lead = _lead(db, tid, st["active"])
    g2, lost_lead = _lead(db, tid, st["lost"], lost_reason="no_response")
    g3, sold_lead = _lead(db, tid, st["sold"])
    g4, cancelled_lead = _lead(db, tid, st["active"])
    for g, i in ((g1, open_lead), (g2, lost_lead), (g3, sold_lead)):
        _stay(db, tid, prop, g, i)
    _stay(db, tid, prop, g4, cancelled_lead, status="cancelled")

    out = script.run(db, tid)
    db.commit()
    assert (out["moved"], out["reopened_from_lost"], out["already_sold"], out["refused"]) == (1, 1, 1, [])
    for inq in (open_lead, lost_lead, sold_lead):
        db.refresh(inq)
        assert inq.stage_id == st["sold"].id
    db.refresh(cancelled_lead)
    assert cancelled_lead.stage_id == st["active"].id                       # a cancelled booking is not a sale
    assert lost_lead.lost_reason is None
    assert db.query(AuditEvent).filter(AuditEvent.tenant_id == tid, AuditEvent.action.like("inquiry.%")).count() >= 3

    again = script.run(db, tid)
    assert (again["moved"], again["reopened_from_lost"], again["already_sold"]) == (0, 0, 3)


def test_unlinked_bookings_only_with_one_clear_candidate(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    st, prop = _workspace(db, tid)
    g1, only_lead = _lead(db, tid, st["active"])
    one = _stay(db, tid, prop, g1)
    g2, first = _lead(db, tid, st["active"])
    db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g2.id, stage_id=st["active"].id))   # a second enquiry
    db.commit()
    two = _stay(db, tid, prop, g2)

    plain = script.run(db, tid)
    assert plain["unlinked_left"] == 2 and plain["linked"] == 0      # without the flag nothing is tied

    out = script.run(db, tid, link_unlinked=True)
    db.commit()
    assert out["linked"] == 1 and out["unlinked_no_candidate"] == 1
    db.refresh(one)
    db.refresh(two)
    db.refresh(only_lead)
    assert one.inquiry_id == only_lead.id and only_lead.stage_id == st["sold"].id
    assert two.inquiry_id is None                                         # two candidates: nothing guessed
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="booking.lead_linked").count() == 1


def test_other_workspace_is_untouched(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    st, prop = _workspace(db, tid)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    ost, oprop = _workspace(db, other.id)
    og, olead = _lead(db, other.id, ost["active"])
    _stay(db, other.id, oprop, og, olead)
    out = script.run(db, tid)
    assert out["bookings"] == 0
    db.refresh(olead)
    assert olead.stage_id == ost["active"].id


def test_workspace_without_sold_stage_stops():
    class _Q:
        def filter_by(self, **_k): return self
        def order_by(self, *_a): return self
        def all(self): return []
    class _Db:
        def query(self, *_a): return _Q()
    with pytest.raises(SystemExit):
        script._stages(_Db(), "t")
