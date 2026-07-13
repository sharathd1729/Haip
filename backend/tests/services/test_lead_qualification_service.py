"""Tests for lead_qualification_service.py — Leads360 restructure Phase 4."""
import uuid

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.lead_field_definition import LeadFieldDefinition
from app.services import lead_qualification_service as svc
from app.services import leads_service


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_inquiry(db, tenant_id, **kwargs):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="", phone="")
    db.add(g)
    db.flush()
    kwargs.setdefault("qualification_status", "qualified")
    inq = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id,
        stage=InquiryStage.NEW, source=InquirySource.WA_DIRECT,
        **kwargs,
    )
    db.add(inq)
    db.flush()
    inq.guest = g
    return inq


def _make_required_field(db, tenant_id, key, column_name):
    f = LeadFieldDefinition(
        id=str(uuid.uuid4()), tenant_id=tenant_id, field_key=key, label=key,
        data_type="text", source="column", column_name=column_name, required_for_lead=True,
    )
    db.add(f)
    db.flush()
    return f


def test_no_required_fields_always_qualified(db):
    t = _make_tenant(db)
    inq = _make_inquiry(db, t.id)
    assert svc.evaluate_qualification(db, t.id, inq) == svc.QUALIFIED


def test_all_required_fields_present_qualified(db):
    t = _make_tenant(db)
    _make_required_field(db, t.id, "check_in", "check_in")
    inq = _make_inquiry(db, t.id, check_in="2026-08-01")
    assert svc.evaluate_qualification(db, t.id, inq) == svc.QUALIFIED


def test_no_required_fields_present_unqualified(db):
    t = _make_tenant(db)
    _make_required_field(db, t.id, "check_in", "check_in")
    inq = _make_inquiry(db, t.id, check_in=None)
    assert svc.evaluate_qualification(db, t.id, inq) == svc.UNQUALIFIED


def test_some_required_fields_present_pending(db):
    t = _make_tenant(db)
    _make_required_field(db, t.id, "check_in", "check_in")
    _make_required_field(db, t.id, "adults", "adults")
    inq = _make_inquiry(db, t.id, check_in="2026-08-01", adults=None)
    assert svc.evaluate_qualification(db, t.id, inq) == svc.PENDING


def test_unqualified_hidden_from_pipeline(db):
    t = _make_tenant(db)
    _make_required_field(db, t.id, "check_in", "check_in")
    qualified = _make_inquiry(db, t.id, check_in="2026-08-01", qualification_status="qualified")
    unqualified = _make_inquiry(db, t.id, check_in=None, qualification_status="unqualified")

    result = leads_service.get_leads_pipeline(db, t.id)
    ids = {l.inquiry_id for l in result.leads}
    assert qualified.id in ids
    assert unqualified.id not in ids


def test_tenant_isolation_on_qualification(db):
    t1 = _make_tenant(db)
    t2 = _make_tenant(db)
    _make_required_field(db, t1.id, "check_in", "check_in")
    inq_t2 = _make_inquiry(db, t2.id, check_in=None)
    # t2 has no required fields configured -- always qualified regardless
    # of t1's config (tenant isolation on the field registry lookup).
    assert svc.evaluate_qualification(db, t2.id, inq_t2) == svc.QUALIFIED
