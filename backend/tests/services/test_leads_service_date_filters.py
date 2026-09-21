"""Tests for leads_service checkin/booked date filters -- Leads360 restructure Phase 2."""
import uuid
from datetime import datetime, timezone
import pytest

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.inquiry_360 import InquiryStageLog
from app.models.pipeline_stage import PipelineStage
from app.services import leads_service


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_inquiry(db, tenant_id, check_in=None, check_out=None):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone="")
    db.add(g)
    db.flush()
    inq = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id,
        stage=InquiryStage.NEW, source=InquirySource.WA_DIRECT,
        check_in=check_in, check_out=check_out,
    )
    db.add(inq)
    db.flush()
    return inq


def test_checkin_date_range_filters(db):
    t = _make_tenant(db)
    in_range = _make_inquiry(db, t.id, check_in="2026-08-05", check_out="2026-08-10")
    out_of_range = _make_inquiry(db, t.id, check_in="2026-09-01", check_out="2026-09-05")

    result = leads_service.get_leads_pipeline(
        db, t.id, checkin_date_from="2026-08-01", checkin_date_to="2026-08-31",
    )
    ids = {l.inquiry_id for l in result.leads}
    assert in_range.id in ids
    assert out_of_range.id not in ids


def test_booked_date_filter(db):
    t = _make_tenant(db)
    won_stage = PipelineStage(id=str(uuid.uuid4()), tenant_id=t.id, key="booked", label="Booked", order=5, is_closed_won=True)
    db.add(won_stage)
    db.flush()

    booked = _make_inquiry(db, t.id)
    not_booked = _make_inquiry(db, t.id)

    db.add(InquiryStageLog(
        id=str(uuid.uuid4()), tenant_id=t.id, inquiry_id=booked.id,
        from_stage="quoted", to_stage="booked",
        changed_by="u1", changed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    ))
    db.flush()

    result = leads_service.get_leads_pipeline(
        db, t.id, booked_date_from="2026-06-25", booked_date_to="2026-07-05",
    )
    ids = {l.inquiry_id for l in result.leads}
    assert booked.id in ids
    assert not_booked.id not in ids


def test_booked_date_filter_tenant_isolation(db):
    t1 = _make_tenant(db)
    t2 = _make_tenant(db)
    for t in (t1, t2):
        db.add(PipelineStage(id=str(uuid.uuid4()), tenant_id=t.id, key="booked", label="Booked", order=5, is_closed_won=True))
    db.flush()

    inq_t1 = _make_inquiry(db, t1.id)
    db.add(InquiryStageLog(
        id=str(uuid.uuid4()), tenant_id=t1.id, inquiry_id=inq_t1.id,
        from_stage="quoted", to_stage="booked",
        changed_by="u1", changed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    ))
    db.flush()

    result_t2 = leads_service.get_leads_pipeline(
        db, t2.id, booked_date_from="2026-06-01", booked_date_to="2026-08-01",
    )
    assert len(result_t2.leads) == 0


def test_unassigned_filter_returns_only_unowned_leads(db):
    from app.models.user import User, UserRole
    t = _make_tenant(db)
    u = User(id=str(uuid.uuid4()), tenant_id=t.id, name="A", email=f"a-{uuid.uuid4().hex[:6]}@t.com",
             role=UserRole.CONCIERGE, is_active=True)
    db.add(u)
    db.flush()
    owned = _make_inquiry(db, t.id)
    owned.assigned_to = u.id
    free = _make_inquiry(db, t.id)
    other_tenant_free = _make_inquiry(db, _make_tenant(db).id)
    db.flush()

    ids = {l.inquiry_id for l in leads_service.get_leads_pipeline(db, t.id, assigned_to="unassigned").leads}
    assert free.id in ids
    assert owned.id not in ids
    assert other_tenant_free.id not in ids
