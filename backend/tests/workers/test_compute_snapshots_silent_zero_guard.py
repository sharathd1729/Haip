"""Dashboard Metrics Plan Phase 2, step 2.1 (F1) -- compute_for_tenant must
fail loudly when a tenant with real data computes zero metrics, instead of
logging success (the exact bug class: migration 032's INSERT omitted
sql_template, so compute_for_tenant always computed 0 and logged success
regardless of how much data existed).
"""
import uuid
import pytest

from app.models.tenant import Tenant
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.guest import Guest
from app.models.metric_registry import MetricRegistry
from app.workers.tasks import compute_snapshots as mod


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_guest(db, tenant_id):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="G", phone="+919876500001")
    db.add(g)
    db.flush()
    return g


def test_raises_when_tenant_has_data_but_zero_metrics_computed(db, monkeypatch):
    """The core F1 bug: every metrics_registry row had sql_template=NULL,
    so the loop body never ran even for a tenant with real inquiries."""
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    db.add(Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id,
        stage=InquiryStage.NEW, source=InquirySource.WA_DIRECT,
    ))
    db.commit()

    # No metrics_registry rows with a sql_template at all -- reproduces the
    # exact pre-fix state (F1).
    assert db.query(MetricRegistry).filter(MetricRegistry.sql_template.isnot(None)).count() == 0

    monkeypatch.setattr(mod, "SessionLocal", lambda: db)
    with pytest.raises(RuntimeError, match="computed 0 metrics"):
        mod.compute_for_tenant.run(tenant.id)


def test_genuinely_empty_tenant_does_not_raise(db, monkeypatch):
    """A tenant with no calls/inquiries/messages at all computing 0 metrics
    is correct, not a bug -- must not raise."""
    tenant = _make_tenant(db)
    db.commit()

    monkeypatch.setattr(mod, "SessionLocal", lambda: db)
    result = mod.compute_for_tenant.run(tenant.id)
    assert result["computed"] == 0


def test_tenant_has_any_data_true_for_calls_inquiries_or_messages(db):
    tenant_with_inquiry = _make_tenant(db)
    guest = _make_guest(db, tenant_with_inquiry.id)
    db.add(Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_with_inquiry.id, guest_id=guest.id,
        stage=InquiryStage.NEW, source=InquirySource.WA_DIRECT,
    ))
    tenant_empty = _make_tenant(db)
    db.commit()

    assert mod._tenant_has_any_data(db, tenant_with_inquiry.id) is True
    assert mod._tenant_has_any_data(db, tenant_empty.id) is False
