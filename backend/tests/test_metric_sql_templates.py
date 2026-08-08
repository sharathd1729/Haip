"""Dashboard Metrics Plan Phase 2, steps 2.3/2.5 -- every sql_template
written in migration 069 must execute without error, filter tenant_id,
and (for calls) exclude a non-active ivr_provider, and (for leads) exclude
non-'valid' pipeline_stages categories.

Uses Postgres-only syntax (::timestamptz casts, FILTER (WHERE ...),
EXTRACT(EPOCH FROM ...)) -- skipped under the default local SQLite run,
same as test_dashboard_hides_disconnected_provider_calls.py and
test_dashboard_stage_fix.py; CI's Postgres testcontainer runs these for
real.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import text

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.models.call import Call, CallDirection
from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.metric_registry import MetricRegistry
from app.models.base import gen_uuid

pytestmark = pytest.mark.skipif(
    "sqlite" in os.environ.get("DATABASE_URL", "sqlite"),
    reason="requires Postgres (::timestamptz casts, FILTER, EXTRACT)",
)

_NOW = datetime.now(timezone.utc)
_START = _NOW - timedelta(days=1)
_END = _NOW + timedelta(days=1)
_PARAMS_BASE = {"start_date": _START, "end_date": _END, "property_ids": None}


def _make_tenant(db, ivr_provider=None):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:8]}",
               plan="growth", ivr_provider=ivr_provider)
    db.add(t)
    db.flush()
    return t


def _make_guest(db, tenant_id):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="G", phone="+919876500001")
    db.add(g)
    db.flush()
    return g


def _run(db, metric_key, tenant_id):
    row = db.query(MetricRegistry).filter_by(metric_key=metric_key).first()
    assert row is not None, f"{metric_key} missing from metrics_registry"
    assert row.sql_template, f"{metric_key} has no sql_template"
    return db.execute(text(row.sql_template), {"tenant_id": tenant_id, **_PARAMS_BASE}).scalar()


def test_every_new_or_updated_template_executes_without_error(db):
    tenant = _make_tenant(db, ivr_provider="vobiz")
    db.commit()
    for key in (
        "calls_volume", "calls_missed", "calls_qa_avg", "leads_valid_active",
        "msg_first_response_avg", "msg_sla_breach_count",
        "ai_draft_verbatim_rate", "ai_draft_edit_distance_avg",
        "ai_draft_reject_rate", "ai_fact_accuracy",
    ):
        _run(db, key, tenant.id)  # must not raise


def test_calls_volume_filters_tenant_id(db):
    tenant_a = _make_tenant(db)
    tenant_b = _make_tenant(db)
    db.add(Call(
        id=gen_uuid(), tenant_id=tenant_a.id, ivr_provider="vobiz",
        ivr_call_id=str(uuid.uuid4()), direction=CallDirection.INBOUND,
        from_number="+919000000001", to_number="+919000000002",
        started_at=_NOW.isoformat(),
    ))
    db.commit()

    assert _run(db, "calls_volume", tenant_a.id) == 1
    assert _run(db, "calls_volume", tenant_b.id) == 0


def test_calls_volume_excludes_non_active_ivr_provider(db):
    """Mcube exclusion, migration 064 -- a tenant now on vobiz must not
    count historical mcube-sourced calls."""
    tenant = _make_tenant(db, ivr_provider="vobiz")
    db.add(Call(
        id=gen_uuid(), tenant_id=tenant.id, ivr_provider="mcube",
        ivr_call_id=str(uuid.uuid4()), direction=CallDirection.INBOUND,
        from_number="+919000000001", to_number="+919000000002",
        started_at=_NOW.isoformat(),
    ))
    db.add(Call(
        id=gen_uuid(), tenant_id=tenant.id, ivr_provider="vobiz",
        ivr_call_id=str(uuid.uuid4()), direction=CallDirection.INBOUND,
        from_number="+919000000003", to_number="+919000000002",
        started_at=_NOW.isoformat(),
    ))
    db.commit()

    assert _run(db, "calls_volume", tenant.id) == 1


def test_calls_missed_matches_calls_py_definition(db):
    """Same semantics as calls.py's is_missed: inbound + zero duration."""
    tenant = _make_tenant(db, ivr_provider="vobiz")
    db.add(Call(
        id=gen_uuid(), tenant_id=tenant.id, ivr_provider="vobiz",
        ivr_call_id=str(uuid.uuid4()), direction=CallDirection.INBOUND,
        from_number="+919000000001", to_number="+919000000002",
        duration_seconds=0, started_at=_NOW.isoformat(),
    ))
    db.add(Call(
        id=gen_uuid(), tenant_id=tenant.id, ivr_provider="vobiz",
        ivr_call_id=str(uuid.uuid4()), direction=CallDirection.INBOUND,
        from_number="+919000000003", to_number="+919000000002",
        duration_seconds=45, started_at=_NOW.isoformat(),
    ))
    db.add(Call(
        id=gen_uuid(), tenant_id=tenant.id, ivr_provider="vobiz",
        ivr_call_id=str(uuid.uuid4()), direction=CallDirection.OUTBOUND,
        from_number="+919000000002", to_number="+919000000004",
        duration_seconds=0, started_at=_NOW.isoformat(),
    ))
    db.commit()

    assert _run(db, "calls_missed", tenant.id) == 1


def _seed_stages(db, tenant_id):
    valid = PipelineStage(
        id=str(uuid.uuid4()), tenant_id=tenant_id, key="active", label="Active",
        order=0, category="valid",
    )
    invalid = PipelineStage(
        id=str(uuid.uuid4()), tenant_id=tenant_id, key="unqualified", label="Unqualified",
        order=1, category="invalid",
    )
    db.add_all([valid, invalid])
    db.flush()
    return valid, invalid


def test_leads_valid_active_excludes_non_valid_category(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    valid, invalid = _seed_stages(db, tenant.id)
    db.add(Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
        stage=InquiryStage.NEW, source=InquirySource.WA_DIRECT, stage_id=valid.id,
    ))
    db.add(Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
        stage=InquiryStage.NEW, source=InquirySource.WA_DIRECT, stage_id=invalid.id,
    ))
    db.commit()

    assert _run(db, "leads_valid_active", tenant.id) == 1


def test_ai_draft_verbatim_rate_computes_percentage(db):
    tenant = _make_tenant(db)
    db.add_all([
        AIDraftOutcome(id=gen_uuid(), tenant_id=tenant.id, draft_message_id=gen_uuid(), outcome="sent_verbatim"),
        AIDraftOutcome(id=gen_uuid(), tenant_id=tenant.id, draft_message_id=gen_uuid(), outcome="sent_verbatim"),
        AIDraftOutcome(id=gen_uuid(), tenant_id=tenant.id, draft_message_id=gen_uuid(), outcome="rejected"),
        AIDraftOutcome(id=gen_uuid(), tenant_id=tenant.id, draft_message_id=gen_uuid(), outcome="sent_edited", edit_distance_pct=12.5),
    ])
    db.commit()

    verbatim_pct = _run(db, "ai_draft_verbatim_rate", tenant.id)
    reject_pct = _run(db, "ai_draft_reject_rate", tenant.id)
    edit_avg = _run(db, "ai_draft_edit_distance_avg", tenant.id)
    assert float(verbatim_pct) == 50.0
    assert float(reject_pct) == 25.0
    assert float(edit_avg) == 12.5
