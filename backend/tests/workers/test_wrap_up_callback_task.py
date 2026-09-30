"""The AI wrap-up already detects when a guest asked to be called back
(CallDisposition.CALLBACK) -- confirmed live gap (Ratha, Sep 2026,
"autopilot" pass): call_status_service.py correctly classifies this as
ANSWERED, so it's excluded from the missed-call queue by definition, and
nothing else ever read it. Mirrors test_wrap_up_disposition_fallback.py's
harness exactly.
"""
import uuid
from unittest.mock import patch

from sqlalchemy.orm import Session as SASession

from app.models.call import Call, CallDirection, CallDisposition
from app.models.guest import Guest
from app.models.task import Task
from app.models.tenant import Tenant
from app.workers.tasks import wrap_up as wrap_up_module
from app.workers.tasks.wrap_up import wrap_up


def _make_call(db, tenant_id, **overrides):
    defaults = dict(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        ivr_provider="vobiz", ivr_call_id=f"call-{uuid.uuid4().hex[:8]}",
        direction=CallDirection.INBOUND,
        from_number="+919845663366", to_number="+912271264296",
        duration_seconds=45,
    )
    defaults.update(overrides)
    call = Call(**defaults)
    db.add(call); db.commit()
    return call


def _setup(db, **call_overrides):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant); db.commit()
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Kiran")
    db.add(guest); db.commit()
    call_overrides.setdefault("guest_id", guest.id)
    call = _make_call(db, tenant.id, **call_overrides)
    return tenant, guest, call


def _fake_llm(tool_use: dict):
    class _Fake:
        async def complete(self, **kwargs):
            return {"tool_use": tool_use, "model": "fake"}
    return _Fake()


def _run(db, tenant_id, call, tool_use):
    with patch.object(wrap_up_module, "get_llm", return_value=_fake_llm(tool_use)), \
         patch.object(wrap_up_module, "SessionLocal", return_value=SASession(bind=db.connection())), \
         patch("app.services.push_service.send_to_tenant"):
        wrap_up.run(call_id=call.id, tenant_id=tenant_id)
    db.refresh(call)
    return call


class TestCallbackRequestedTask:
    def test_callback_disposition_creates_a_task_with_a_due_date(self, db):
        tenant, guest, call = _setup(db)
        result = _run(db, tenant.id, call, {
            "summary": "Guest asked to be called back tomorrow.",
            "suggested_disposition": "callback",
            "next_action": "Call back tomorrow",
        })
        assert result.ai_disposition == CallDisposition.CALLBACK

        task = db.query(Task).filter_by(tenant_id=tenant.id, guest_id=guest.id).first()
        assert task is not None
        assert task.title == "Callback requested — Kiran"
        assert task.priority == "high"
        assert task.due_date is not None
        assert task.is_done is False

    def test_no_task_for_a_non_callback_disposition(self, db):
        tenant, guest, call = _setup(db)
        _run(db, tenant.id, call, {
            "summary": "Guest booked directly.",
            "suggested_disposition": "booked",
            "next_action": "Send confirmation",
        })
        assert db.query(Task).filter_by(tenant_id=tenant.id, guest_id=guest.id).first() is None

    def test_no_task_without_a_guest(self, db):
        tenant, guest, call = _setup(db, guest_id=None)
        _run(db, tenant.id, call, {
            "summary": "Guest asked to be called back.",
            "suggested_disposition": "callback",
            "next_action": "Call back",
        })
        assert db.query(Task).filter_by(tenant_id=tenant.id).first() is None

    def test_deduplicates_repeated_callback_dispositions(self, db):
        tenant, guest, call1 = _setup(db)
        _run(db, tenant.id, call1, {
            "summary": "Asked to be called back.",
            "suggested_disposition": "callback", "next_action": "Call back",
        })
        call2 = _make_call(db, tenant.id, guest_id=guest.id)
        _run(db, tenant.id, call2, {
            "summary": "Asked again to be called back.",
            "suggested_disposition": "callback", "next_action": "Call back",
        })

        tasks = db.query(Task).filter_by(tenant_id=tenant.id, guest_id=guest.id).all()
        assert len(tasks) == 1
