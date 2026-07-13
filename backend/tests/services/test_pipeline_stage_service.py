"""Tests for pipeline_stage_service.py — Leads360 restructure Phase 1."""
import uuid
import pytest

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.services import pipeline_stage_service as svc


def _make_tenant(db, name="TenantPipeline"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"pipe-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_stage(db, tenant_id, key, order, **kwargs):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key=key, label=key.title(), order=order, **kwargs)
    db.add(s)
    db.flush()
    return s


def _make_inquiry(db, tenant_id, stage_id=None):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone="")
    db.add(g)
    db.flush()
    inq = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id,
        stage=InquiryStage.NEW, stage_id=stage_id, source=InquirySource.WA_DIRECT,
    )
    db.add(inq)
    db.flush()
    return inq


def test_create_stage_happy_path(db):
    t = _make_tenant(db)
    stage = svc.create_stage(
        db, t.id, key="negotiation", label="Negotiation", color="#123456",
        order=None, is_closed_won=False, is_closed_lost=False, created_by=None,
    )
    assert stage.key == "negotiation"
    assert stage.order == 0

    duplicate_tenant_stage = _make_stage(db, t.id, "new", 0)
    with pytest.raises(svc.PipelineStageError):
        svc.create_stage(
            db, t.id, key="new", label="New Again", color="#111111",
            order=None, is_closed_won=False, is_closed_lost=False, created_by=None,
        )


def test_create_stage_tenant_isolation(db):
    t1 = _make_tenant(db, "T1")
    t2 = _make_tenant(db, "T2")
    _make_stage(db, t1.id, "new", 0)
    # Same key is fine in a different tenant — uniqueness is per-tenant
    stage = svc.create_stage(
        db, t2.id, key="new", label="New", color="#111111",
        order=None, is_closed_won=False, is_closed_lost=False, created_by=None,
    )
    assert stage.tenant_id == t2.id
    assert svc.list_stages(db, t1.id)[0].tenant_id == t1.id
    assert svc.list_stages(db, t2.id)[0].tenant_id == t2.id


def test_delete_stage_requires_reassignment_when_leads_present(db):
    t = _make_tenant(db)
    s1 = _make_stage(db, t.id, "new", 0, is_default_entry=True)
    s2 = _make_stage(db, t.id, "responding", 1)
    _make_stage(db, t.id, "quoted", 2)
    _make_inquiry(db, t.id, stage_id=s2.id)

    with pytest.raises(svc.PipelineStageError):
        svc.delete_stage(db, t.id, s2.id)

    svc.delete_stage(db, t.id, s2.id, reassign_to_stage_id=s1.id)
    remaining = svc.list_stages(db, t.id)
    assert len(remaining) == 2
    assert s2.id not in [s.id for s in remaining]


def test_delete_stage_blocks_default_entry(db):
    t = _make_tenant(db)
    s1 = _make_stage(db, t.id, "new", 0, is_default_entry=True)
    _make_stage(db, t.id, "responding", 1)
    with pytest.raises(svc.PipelineStageError):
        svc.delete_stage(db, t.id, s1.id)


def test_reorder_stages(db):
    t = _make_tenant(db)
    s1 = _make_stage(db, t.id, "new", 0)
    s2 = _make_stage(db, t.id, "responding", 1)
    reordered = svc.reorder_stages(db, t.id, [s2.id, s1.id])
    assert [s.id for s in reordered] == [s2.id, s1.id]
    assert reordered[0].order == 0
    assert reordered[1].order == 1
