"""WhatsApp module Phase 2, T2.1 — Beat drain claim logic tests."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.flow_execution import FlowPendingExecution
from app.workers.tasks import flow_engine as mod


class _NoCloseSessionWrapper:
    def __init__(self, real_db):
        self._real_db = real_db

    def __getattr__(self, name):
        return getattr(self._real_db, name)

    def close(self):
        pass


def _make_pending(db, tenant_id, guest_id, resume_at, status="pending"):
    row = FlowPendingExecution(
        id=str(uuid.uuid4()), tenant_id=tenant_id, flow_id=str(uuid.uuid4()),
        node_id="n1", guest_id=guest_id, resume_at=resume_at, status=status,
        context={"guest_id": guest_id},
    )
    db.add(row)
    db.flush()
    return row


def test_drain_only_claims_due_pending_rows(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="G", phone="+911111111111")
    db.add(g)
    db.flush()

    due = _make_pending(db, t.id, g.id, datetime.now(timezone.utc) - timedelta(minutes=1))
    not_due = _make_pending(db, t.id, g.id, datetime.now(timezone.utc) + timedelta(hours=1))
    already_claimed = _make_pending(db, t.id, g.id, datetime.now(timezone.utc) - timedelta(minutes=5), status="claimed")
    db.commit()

    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch.object(mod, "resume_flow_execution") as mock_resume:
        mod.drain_pending_executions.run()

    db.refresh(due)
    db.refresh(not_due)
    db.refresh(already_claimed)

    assert due.status == "claimed"
    assert not_due.status == "pending"
    assert already_claimed.status == "claimed"
    mock_resume.delay.assert_called_once_with(execution_id=due.id)
