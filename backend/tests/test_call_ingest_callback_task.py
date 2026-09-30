"""An agent's own outbound call that nobody picked up gets a follow-up
Task -- confirmed live gap (Ratha, Sep 2026, "autopilot" pass):
call_status_service.is_missed_call() is deliberately inbound-only, so an
unanswered outbound call had no reminder anywhere. Mirrors
test_call_ingest_direction_fix.py's harness exactly.
"""
import uuid
from unittest.mock import patch

from sqlalchemy.orm import Session as SASession

from app.adapters.ivr.base import CallWebhookPayload
from app.models.call import Call
from app.models.task import Task
from app.workers.tasks import call_ingest
from app.workers.tasks.call_ingest import ingest_call


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


class _FakeAdapter:
    def __init__(self, payload):
        self._payload = payload

    def parse_call_webhook(self, raw):
        return self._payload


def _run_ingest(monkeypatch, db, tenant_id, payload):
    monkeypatch.setattr(call_ingest, "get_ivr_adapter", lambda provider: _FakeAdapter(payload))
    monkeypatch.setattr(call_ingest.fetch_and_store_recording, "delay", lambda **kw: None)
    monkeypatch.setattr(call_ingest, "SessionLocal", lambda: SASession(bind=db.connection()))
    with patch("app.services.push_service.send_to_tenant"):
        result = ingest_call.run(payload={}, tenant_id=tenant_id, ivr_provider="vobiz")
    return result


def _payload(**overrides):
    defaults = dict(
        ivr_call_id=f"call-{uuid.uuid4().hex[:8]}",
        direction="outbound",
        from_number="+912271264296",   # tenant's own IVR/DID
        to_number="+917249066854",     # the real lead
        duration_seconds=0,
        recording_url="https://media.vobiz.ai/rec.mp3",
        agent_number="+919000000000",
        started_at="2026-09-30T10:00:00+00:00",
        ended_at="2026-09-30T10:00:00+00:00",
        provider="vobiz",
        raw={},
        ivr_dial_status="no-answer",
    )
    defaults.update(overrides)
    return CallWebhookPayload(**defaults)


class TestCallbackTaskOnUnansweredOutbound:
    def test_creates_a_task_when_the_lead_does_not_pick_up(self, db, tenant_and_user, monkeypatch):
        tenant_id = _tenant_id(tenant_and_user)
        result = _run_ingest(monkeypatch, db, tenant_id, _payload())

        call = db.query(Call).filter_by(id=result["call_id"]).one()
        task = db.query(Task).filter_by(tenant_id=tenant_id, guest_id=call.guest_id).first()
        assert task is not None
        assert task.title.startswith("Call back — no answer from")
        assert task.due_date is not None
        assert task.is_done is False

    def test_no_task_when_the_call_was_answered(self, db, tenant_and_user, monkeypatch):
        tenant_id = _tenant_id(tenant_and_user)
        result = _run_ingest(monkeypatch, db, tenant_id, _payload(ivr_dial_status="completed", duration_seconds=90))

        call = db.query(Call).filter_by(id=result["call_id"]).one()
        assert db.query(Task).filter_by(tenant_id=tenant_id, guest_id=call.guest_id).first() is None

    def test_no_task_for_an_inbound_call(self, db, tenant_and_user, monkeypatch):
        """A missed inbound call already has its own queue
        (work_queue_service._callbacks) -- this is scoped to outbound only."""
        tenant_id = _tenant_id(tenant_and_user)
        result = _run_ingest(monkeypatch, db, tenant_id, _payload(
            direction="inbound", from_number="+917249066854", to_number="+912271264296",
            ivr_dial_status="",
        ))

        call = db.query(Call).filter_by(id=result["call_id"]).one()
        assert db.query(Task).filter_by(tenant_id=tenant_id, guest_id=call.guest_id).first() is None

    def test_falls_back_to_duration_with_no_dial_status(self, db, tenant_and_user, monkeypatch):
        tenant_id = _tenant_id(tenant_and_user)
        result = _run_ingest(monkeypatch, db, tenant_id, _payload(ivr_dial_status="", duration_seconds=0))

        call = db.query(Call).filter_by(id=result["call_id"]).one()
        assert db.query(Task).filter_by(tenant_id=tenant_id, guest_id=call.guest_id).first() is not None

    def test_deduplicates_repeated_unanswered_calls_to_the_same_guest(self, db, tenant_and_user, monkeypatch):
        tenant_id = _tenant_id(tenant_and_user)
        _run_ingest(monkeypatch, db, tenant_id, _payload())
        _run_ingest(monkeypatch, db, tenant_id, _payload(ivr_call_id=f"call-{uuid.uuid4().hex[:8]}"))

        tasks = db.query(Task).filter_by(tenant_id=tenant_id).all()
        assert len(tasks) == 1
