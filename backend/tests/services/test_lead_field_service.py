"""Tests for lead_field_service.py — Leads360 restructure Phase 3."""
import uuid
import pytest

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.lead_field_definition import LeadFieldDefinition
from app.services import lead_field_service as svc


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_inquiry(db, tenant_id, **kwargs):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Test Guest", phone="+911234567890")
    db.add(g)
    db.flush()
    inq = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id,
        stage=InquiryStage.NEW, source=InquirySource.WA_DIRECT, **kwargs,
    )
    db.add(inq)
    db.flush()
    inq.guest = g
    return inq


def test_create_and_list_field_definitions(db):
    t = _make_tenant(db)
    field = svc.create_field_definition(
        db, t.id, field_key="loyalty_tier", label="Loyalty Tier", data_type="text",
        required_for_lead=False, show_in_detail=True,
    )
    assert field.source == "custom"
    fields = svc.list_field_definitions(db, t.id)
    assert len(fields) == 1
    assert fields[0].field_key == "loyalty_tier"


def test_create_duplicate_key_rejected(db):
    t = _make_tenant(db)
    svc.create_field_definition(db, t.id, field_key="x", label="X", data_type="text", required_for_lead=False, show_in_detail=True)
    with pytest.raises(svc.LeadFieldError):
        svc.create_field_definition(db, t.id, field_key="x", label="X2", data_type="text", required_for_lead=False, show_in_detail=True)


def test_tenant_isolation(db):
    t1 = _make_tenant(db)
    t2 = _make_tenant(db)
    svc.create_field_definition(db, t1.id, field_key="x", label="X", data_type="text", required_for_lead=False, show_in_detail=True)
    assert len(svc.list_field_definitions(db, t1.id)) == 1
    assert len(svc.list_field_definitions(db, t2.id)) == 0


def test_get_field_value_column_source(db):
    t = _make_tenant(db)
    inq = _make_inquiry(db, t.id, adults=4, budget=50000)
    field = LeadFieldDefinition(
        id=str(uuid.uuid4()), tenant_id=t.id, field_key="adults", label="Adults",
        data_type="number", source="column", column_name="adults",
    )
    db.add(field)
    db.flush()
    assert svc.get_field_value(db, t.id, inq, field) == 4


def test_get_field_value_guest_derived(db):
    t = _make_tenant(db)
    inq = _make_inquiry(db, t.id)
    field = LeadFieldDefinition(
        id=str(uuid.uuid4()), tenant_id=t.id, field_key="guest_name", label="Guest Name",
        data_type="text", source="column", column_name=None,
    )
    db.add(field)
    db.flush()
    assert svc.get_field_value(db, t.id, inq, field) == "Test Guest"


def test_get_field_value_custom_source(db):
    t = _make_tenant(db)
    inq = _make_inquiry(db, t.id, custom_fields={"loyalty_tier": "gold"})
    field = LeadFieldDefinition(
        id=str(uuid.uuid4()), tenant_id=t.id, field_key="loyalty_tier", label="Loyalty Tier",
        data_type="text", source="custom",
    )
    db.add(field)
    db.flush()
    assert svc.get_field_value(db, t.id, inq, field) == "gold"
