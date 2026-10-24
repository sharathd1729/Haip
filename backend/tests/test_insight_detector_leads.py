"""A1 / A2 ("leads not contacted") read the ONE work queue, not the legacy enquiry stage.

Before: A1 counted every enquiry in the old NEW stage with no first_response_at, so every Instagram / WhatsApp DM that never
gave a phone number counted as a lead "not followed up" (Home showed "2169 leads not followed up in 24h"). A lead is a person
with a usable phone number (guests.lead_identified_at); these tests pin that only those, uncontacted, are counted, per tenant.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.insight import Insight
from app.models.tenant import Tenant
from app.services.insight_detector import detect_A1, detect_A2

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_now():
    """NOW is set at import (collection); a full run reaches these tests 30+ min later, ageing every "N minutes ago" past
    its threshold. Re-read the clock per test."""
    global NOW
    NOW = datetime.now(timezone.utc)


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"ins-{uuid.uuid4().hex[:6]}", plan="growth", ivr_provider="vobiz")
    db.add(t); db.flush(); return t


def _guest(db, tid, name, lead_minutes_ago=None):
    """A lead when lead_minutes_ago is given; otherwise a DM contact with no phone (not a lead)."""
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name=name,
              phone=f"+9198{uuid.uuid4().int % 10**8:08d}" if lead_minutes_ago is not None else None,
              first_touch_channel="instagram",
              lead_identified_at=(NOW - timedelta(minutes=lead_minutes_ago)) if lead_minutes_ago is not None else None)
    db.add(g); db.flush(); return g


def _enquiry(db, tid, guest, days_old=2, budget=None):
    i = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, stage=InquiryStage.NEW, first_response_at=None,
                source=InquirySource.META_IG, budget=budget, created_at=NOW - timedelta(days=days_old))
    db.add(i); db.flush(); return i


def _insight(db, tid, code):
    return db.query(Insight).filter_by(tenant_id=tid, category_code=code, is_auto_resolved=False, is_dismissed=False).first()


def test_old_dms_without_a_phone_are_not_counted_as_leads_not_contacted(db):
    t = _tenant(db)
    for n in range(5):                                   # the legacy NEW-stage DM enquiries the old query counted
        _enquiry(db, t.id, _guest(db, t.id, f"dm{n}"), days_old=3)
    detect_A1(db, t.id); db.commit()
    assert _insight(db, t.id, "A1") is None


def test_a_lead_nobody_contacted_for_a_day_is_counted_once_and_links_to_my_day(db):
    t = _tenant(db)
    g = _guest(db, t.id, "Asha", lead_minutes_ago=30 * 60)           # number arrived 30 h ago, nobody called
    _enquiry(db, t.id, g, days_old=2, budget=150000)
    _enquiry(db, t.id, _guest(db, t.id, "dm-only"), days_old=2)        # a DM: ignored
    fresh = _guest(db, t.id, "Fresh", lead_minutes_ago=60)             # under 24 h: not yet
    _enquiry(db, t.id, fresh, days_old=0)
    detect_A1(db, t.id); db.commit()
    ins = _insight(db, t.id, "A1")
    assert ins is not None
    assert ins.data_snapshot["count"] == 1
    assert ins.title.startswith("1 new lead not contacted in 24h")
    assert ins.cta_href == "/dashboard/my-day?kind=new_lead"


def test_a1_counts_only_its_own_tenant(db):
    a, b = _tenant(db), _tenant(db)
    _enquiry(db, b.id, _guest(db, b.id, "Other tenant lead", lead_minutes_ago=30 * 60))
    detect_A1(db, a.id); detect_A1(db, b.id); db.commit()
    assert _insight(db, a.id, "A1") is None
    assert _insight(db, b.id, "A1").data_snapshot["count"] == 1


def test_a1_resolves_itself_once_the_old_count_no_longer_holds(db):
    t = _tenant(db)
    db.add(Insight(tenant_id=t.id, category_code="A1", target_id=None, category="urgency", severity="critical",
                   title="2169 leads not followed up in 24h"))
    db.flush()
    _enquiry(db, t.id, _guest(db, t.id, "dm"), days_old=5)
    detect_A1(db, t.id); db.commit()
    assert _insight(db, t.id, "A1") is None


def test_a2_flags_leads_past_the_first_call_target_only(db):
    t = _tenant(db)
    _enquiry(db, t.id, _guest(db, t.id, "Late", lead_minutes_ago=20), days_old=0)     # past 15 min, under 60: "late"
    _enquiry(db, t.id, _guest(db, t.id, "Just now", lead_minutes_ago=5), days_old=0)  # still fresh
    _enquiry(db, t.id, _guest(db, t.id, "dm"), days_old=0)                            # not a lead
    detect_A2(db, t.id); db.commit()
    ins = _insight(db, t.id, "A2")
    assert ins is not None and ins.data_snapshot["count"] == 1


def test_a2_counts_only_its_own_tenant(db):
    a, b = _tenant(db), _tenant(db)
    _enquiry(db, b.id, _guest(db, b.id, "Late elsewhere", lead_minutes_ago=20), days_old=0)
    detect_A2(db, a.id); db.commit()
    assert _insight(db, a.id, "A2") is None
