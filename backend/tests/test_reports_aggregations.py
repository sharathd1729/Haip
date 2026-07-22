"""
New aggregate report functions: leads_service.get_source_breakdown(),
leads_service.get_daily_lead_funnel(), and calendar.get_occupancy_summary().
These back the "Lead source", "Day-wise lead funnel", and "Occupancy" report
requests -- see the July 2026 reports plan.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.services.leads_service import get_source_breakdown, get_daily_lead_funnel


def _make_tenant(db, slug=None):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=slug or f"t-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_guest(db, tenant_id):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, phone=f"+91{uuid.uuid4().int % 10**10}")
    db.add(g)
    db.flush()
    return g


def _make_stage(db, tenant_id, key, category=None, is_closed_won=False):
    s = PipelineStage(
        id=str(uuid.uuid4()), tenant_id=tenant_id, key=key, label=key,
        order=0, category=category, is_closed_won=is_closed_won,
    )
    db.add(s)
    db.flush()
    return s


def _make_inquiry(db, tenant_id, guest_id, source, stage_id=None, created_at=None):
    inq = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
        source=source, stage_id=stage_id,
    )
    db.add(inq)
    db.flush()
    if created_at:
        inq.created_at = created_at
        db.flush()
    return inq


def test_source_breakdown_counts_and_conversion(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    won_stage = _make_stage(db, tenant.id, "won", category="valid", is_closed_won=True)
    open_stage = _make_stage(db, tenant.id, "open", category="valid")

    _make_inquiry(db, tenant.id, guest.id, InquirySource.WA_DIRECT, stage_id=won_stage.id)
    _make_inquiry(db, tenant.id, guest.id, InquirySource.WA_DIRECT, stage_id=open_stage.id)
    _make_inquiry(db, tenant.id, guest.id, InquirySource.META_IG, stage_id=open_stage.id)
    db.commit()

    rows = {r["source"]: r for r in get_source_breakdown(db, tenant.id)}
    assert rows["wa_direct"]["total_leads"] == 2
    assert rows["wa_direct"]["converted"] == 1
    assert rows["wa_direct"]["conversion_rate"] == 0.5
    assert rows["meta_ig"]["total_leads"] == 1
    assert rows["meta_ig"]["converted"] == 0


def test_source_breakdown_tenant_isolated(db):
    t1 = _make_tenant(db)
    t2 = _make_tenant(db)
    g1 = _make_guest(db, t1.id)
    g2 = _make_guest(db, t2.id)
    _make_inquiry(db, t1.id, g1.id, InquirySource.WA_DIRECT)
    _make_inquiry(db, t2.id, g2.id, InquirySource.WA_DIRECT)
    _make_inquiry(db, t2.id, g2.id, InquirySource.WA_DIRECT)
    db.commit()

    rows_t1 = {r["source"]: r for r in get_source_breakdown(db, t1.id)}
    rows_t2 = {r["source"]: r for r in get_source_breakdown(db, t2.id)}
    assert rows_t1["wa_direct"]["total_leads"] == 1
    assert rows_t2["wa_direct"]["total_leads"] == 2


def test_daily_lead_funnel_valid_invalid_converted(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    valid_stage = _make_stage(db, tenant.id, "active", category="valid")
    invalid_stage = _make_stage(db, tenant.id, "rnr", category="invalid")
    won_stage = _make_stage(db, tenant.id, "won", category="valid", is_closed_won=True)

    today = datetime.now(timezone.utc)
    _make_inquiry(db, tenant.id, guest.id, InquirySource.WA_DIRECT, stage_id=valid_stage.id, created_at=today)
    _make_inquiry(db, tenant.id, guest.id, InquirySource.WA_DIRECT, stage_id=invalid_stage.id, created_at=today)
    _make_inquiry(db, tenant.id, guest.id, InquirySource.WA_DIRECT, stage_id=won_stage.id, created_at=today)
    db.commit()

    rows = get_daily_lead_funnel(db, tenant.id, today - timedelta(days=1), today + timedelta(days=1))
    assert len(rows) == 1
    day = rows[0]
    assert day["total_leads"] == 3
    assert day["valid"] == 2  # active + won, both category="valid"
    assert day["invalid"] == 1
    assert day["converted"] == 1


def test_daily_lead_funnel_tenant_isolated(db):
    t1 = _make_tenant(db)
    t2 = _make_tenant(db)
    g1 = _make_guest(db, t1.id)
    g2 = _make_guest(db, t2.id)
    today = datetime.now(timezone.utc)
    _make_inquiry(db, t1.id, g1.id, InquirySource.WA_DIRECT, created_at=today)
    _make_inquiry(db, t2.id, g2.id, InquirySource.WA_DIRECT, created_at=today)
    _make_inquiry(db, t2.id, g2.id, InquirySource.WA_DIRECT, created_at=today)
    db.commit()

    rows_t1 = get_daily_lead_funnel(db, t1.id, today - timedelta(days=1), today + timedelta(days=1))
    rows_t2 = get_daily_lead_funnel(db, t2.id, today - timedelta(days=1), today + timedelta(days=1))
    assert rows_t1[0]["total_leads"] == 1
    assert rows_t2[0]["total_leads"] == 2


class _FakeUser:
    def __init__(self, tenant_id):
        self.tenant_id = tenant_id


def test_occupancy_summary_empty_portfolio(db):
    """No properties -> occupancy is 0%, not a divide-by-zero crash."""
    from app.api.v1.endpoints.calendar import get_occupancy_summary
    tenant = _make_tenant(db)
    db.commit()

    today = datetime.now(timezone.utc).date()
    resp = get_occupancy_summary(
        from_date=today.isoformat(),
        to_date=(today + timedelta(days=3)).isoformat(),
        db=db,
        current_user=_FakeUser(tenant.id),
    )
    assert resp["summary"]["total_properties"] == 0
    assert resp["summary"]["avg_occupancy_pct"] == 0
    assert len(resp["daily"]) == 3


def test_lead_vs_conversation_widget_counts_leads(db):
    from app.services.widget_service import build_widget_data

    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    today = datetime.now(timezone.utc)
    _make_inquiry(db, tenant.id, guest.id, InquirySource.WA_DIRECT, created_at=today)
    _make_inquiry(db, tenant.id, guest.id, InquirySource.WA_DIRECT, created_at=today)
    db.commit()

    data, summary = build_widget_data(db, tenant, "lead_vs_conversation", range_days=30)
    assert data is not None
    assert data["total_leads"] == 2
    assert "leads" in summary
