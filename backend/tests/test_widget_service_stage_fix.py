"""
Regression tests: widget_service.py's _missed_revenue, _inquiry_funnel, and
_attribution builders used to group/filter on the legacy Inquiry.stage enum.
Every inquiry created via the chat/call auto-create flow (this session)
permanently leaves that enum at NEW -- real routing lives in stage_id /
pipeline_stages, so these builders silently read zero for exactly the data
a demo needs to show. Fixed to resolve won/lost via
pipeline_stage_service.get_stage_ids_by_flag() instead.
"""
import uuid
from datetime import datetime, timezone
import pytest

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.pipeline_stage import PipelineStage
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.services.widget_service import _missed_revenue, _inquiry_funnel, _attribution


def _make_tenant(db, name="TenantWidget"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"wsf-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_guest(db, tenant_id):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone="")
    db.add(g)
    db.flush()
    return g


def _make_stage(db, tenant_id, key, order, **kwargs):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key=key, label=key.title(), order=order, **kwargs)
    db.add(s)
    db.flush()
    return s


def _make_inquiry(db, tenant_id, guest_id, stage_id=None, budget=None, source=InquirySource.WA_DIRECT):
    inq = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
        stage=InquiryStage.NEW,  # every auto-created inquiry stays here -- the whole point of the bug
        stage_id=stage_id, source=source, budget=budget,
    )
    db.add(inq)
    db.flush()
    return inq


def test_missed_revenue_counts_via_stage_id_not_legacy_enum(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    lost_stage = _make_stage(db, tenant.id, "lost", 0, category="valid", is_closed_lost=True)
    active_stage = _make_stage(db, tenant.id, "active", 1, category="valid", is_valid_lead_entry=True)

    _make_inquiry(db, tenant.id, guest.id, stage_id=lost_stage.id, budget=5000)
    _make_inquiry(db, tenant.id, guest.id, stage_id=active_stage.id, budget=3000)

    now = datetime.now(timezone.utc)
    start = now.replace(year=now.year - 1)
    data, summary = _missed_revenue(db, tenant.id, start, now, now)

    assert data["lost_inquiries"] == 1
    assert data["revenue_at_risk"] == 5000


def test_inquiry_funnel_uses_tenant_taxonomy_and_is_closed_won(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    general = _make_stage(db, tenant.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    active = _make_stage(db, tenant.id, "active", 1, category="valid", is_valid_lead_entry=True)
    sold = _make_stage(db, tenant.id, "sold", 2, category="valid", is_closed_won=True)

    _make_inquiry(db, tenant.id, guest.id, stage_id=general.id)
    _make_inquiry(db, tenant.id, guest.id, stage_id=active.id)
    _make_inquiry(db, tenant.id, guest.id, stage_id=active.id)
    _make_inquiry(db, tenant.id, guest.id, stage_id=sold.id)

    now = datetime.now(timezone.utc)
    data, summary = _inquiry_funnel(db, tenant.id, now, now, now)

    by_key = {s["stage"]: s["count"] for s in data["stages"]}
    assert by_key["general_enquiry"] == 1
    assert by_key["active"] == 2
    assert by_key["sold"] == 1
    assert data["conversion_rate"] == 25.0  # 1 sold / 4 total


def test_attribution_counts_won_via_stage_id(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    active = _make_stage(db, tenant.id, "active", 0, category="valid", is_valid_lead_entry=True)
    sold = _make_stage(db, tenant.id, "sold", 1, category="valid", is_closed_won=True)

    _make_inquiry(db, tenant.id, guest.id, stage_id=active.id, source=InquirySource.WA_DIRECT)
    _make_inquiry(db, tenant.id, guest.id, stage_id=sold.id, source=InquirySource.WA_DIRECT)
    _make_inquiry(db, tenant.id, guest.id, stage_id=sold.id, source=InquirySource.META_IG)

    now = datetime.now(timezone.utc)
    data, summary = _attribution(db, tenant.id, now, now, now)

    by_source = {s["source"]: s["booked"] for s in data["sources"]}
    assert by_source.get("wa_direct") == 1
    assert by_source.get("meta_ig") == 1


def test_widgets_return_zero_when_no_won_lost_stages_tagged(db):
    """A tenant with no is_closed_won/is_closed_lost stage tagged yet
    (e.g. mid pipeline setup) must read zero, not silently count
    everything as won/lost."""
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    general = _make_stage(db, tenant.id, "general_enquiry", 0, category="invalid", is_default_entry=True)
    _make_inquiry(db, tenant.id, guest.id, stage_id=general.id, budget=9999)

    now = datetime.now(timezone.utc)
    start = now.replace(year=now.year - 1)

    missed_data, _ = _missed_revenue(db, tenant.id, start, now, now)
    assert missed_data["lost_inquiries"] == 0
    assert missed_data["revenue_at_risk"] == 0

    funnel_data, _ = _inquiry_funnel(db, tenant.id, now, now, now)
    assert funnel_data["conversion_rate"] == 0

    attribution_data, _ = _attribution(db, tenant.id, now, now, now)
    assert attribution_data["sources"] == []
