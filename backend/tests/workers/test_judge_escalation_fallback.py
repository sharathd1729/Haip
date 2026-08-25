"""Regression: judge.py's escalation to the stronger deep_reason model
(triggered whenever the first-pass call_scoring confidence is below 0.78 --
the common case, not rare) had no error handling. Confirmed live: NVIDIA's
deep_reason endpoint returned a raw 500, which propagated unhandled out of
judge(), crashing the whole task before it ever reached wrap_up.delay() --
meaning ai_disposition never got set for any call whose first-pass
confidence merely came in low, not just ones the escalated model actually
struggled with. The fix falls back to the first-pass (lower-confidence but
real) result and continues, rather than losing the call entirely."""
import json
import uuid
from unittest.mock import MagicMock, patch

from app.models.call import Call, CallDirection
from app.models.tenant import Tenant
from app.models.transcript import Transcript
from app.workers.tasks.judge import judge


def _setup(db):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant); db.commit()

    call = Call(
        id=str(uuid.uuid4()), tenant_id=tenant.id,
        ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()),
        direction=CallDirection.INBOUND, from_number="+919876543210", to_number="+911234567890",
        duration_seconds=16,
    )
    db.add(call); db.commit()

    transcript = Transcript(
        id=str(uuid.uuid4()), tenant_id=tenant.id, call_id=call.id,
        provider="sarvam", language="en",
        turns=json.dumps([{"speaker": "unknown", "t0": 0.0, "t1": 5.0, "text": "Greeting audio only."}]),
        raw_text="Greeting audio only.",
    )
    db.add(transcript); db.commit()

    return tenant, call


_FIRST_PASS_RESULT = {
    "criterion_scores": [{"id": "greeting", "score": 1, "evidence": "Played greeting"}],
    "confidence": 0.6,  # below CONFIDENCE_THRESHOLD (0.78) -- triggers escalation
    "sentiment": "neutral",
}


class _FirstPassLLM:
    async def complete(self, **kwargs):
        return {"tool_use": dict(_FIRST_PASS_RESULT), "model": "call_scoring_model"}


class _FailingEscalationLLM:
    async def complete(self, **kwargs):
        raise RuntimeError("error code: 500 - {'error': {'message': 'Internal server error'}}")


def _run(db, tenant, call):
    def _fake_get_llm(task):
        return _FailingEscalationLLM() if task == "deep_reason" else _FirstPassLLM()

    wrap_up_mock = MagicMock()
    with patch("app.workers.tasks.judge.get_llm", _fake_get_llm), \
         patch("app.workers.tasks.judge.SessionLocal", return_value=db), \
         patch("app.workers.tasks.wrap_up.wrap_up.delay", wrap_up_mock):
        judge.run(call_id=call.id, tenant_id=tenant.id)
    return wrap_up_mock


class TestJudgeEscalationFallback:
    def test_escalation_failure_falls_back_to_first_pass_and_still_completes(self, db):
        tenant, call = _setup(db)
        call_id = call.id  # capture before judge.run() closes the session

        wrap_up_mock = _run(db, tenant, call)

        # judge.run() closes the db session it was given (its own `finally`
        # block) -- re-query rather than db.refresh() the now-detached
        # instance.
        refreshed = db.query(Call).filter_by(id=call_id).first()
        assert refreshed.ai_score_status == "done"
        wrap_up_mock.assert_called_once()

    def test_escalation_failure_does_not_raise(self, db):
        """judge.run() must not propagate the escalated model's error --
        this is the exact live crash (unhandled 500) that blocked
        wrap_up/ai_disposition for every low-confidence call."""
        tenant, call = _setup(db)
        _run(db, tenant, call)  # would raise before the fix
