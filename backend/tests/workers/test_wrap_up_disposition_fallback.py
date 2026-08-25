"""Regression: wrap_up.py used to default a missing/unrecognized
suggested_disposition straight to CallDisposition.CALLBACK -- an ANSWERED
value. Same real bug as ai_scoring.py's _map_disposition(), confirmed live
on a call whose transcript was pure IVR greeting audio (nobody ever
answered) that still ended up with ai_disposition=CALLBACK and was never
flagged missed. None must be the fallback so is_missed_call() falls
through to the real dial_status/duration signals."""
import json
import uuid
from unittest.mock import patch

from sqlalchemy.orm import Session as SASession

from app.models.call import Call, CallDirection, CallDisposition
from app.models.tenant import Tenant
from app.models.transcript import Transcript
from app.workers.tasks import wrap_up as wrap_up_module
from app.workers.tasks.wrap_up import wrap_up


def _make_call(db, tenant_id, **overrides):
    defaults = dict(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        ivr_provider="vobiz", ivr_call_id=f"call-{uuid.uuid4().hex[:8]}",
        direction=CallDirection.INBOUND,
        from_number="+919845663366", to_number="+912271264296",
        duration_seconds=16,
    )
    defaults.update(overrides)
    call = Call(**defaults)
    db.add(call); db.commit()
    return call


def _fake_llm(tool_use: dict):
    class _Fake:
        async def complete(self, **kwargs):
            return {"tool_use": tool_use, "model": "fake"}
    return _Fake()


def _run(db, tenant_id, call, tool_use):
    with patch.object(wrap_up_module, "get_llm", return_value=_fake_llm(tool_use)), \
         patch.object(wrap_up_module, "SessionLocal", return_value=SASession(bind=db.connection())):
        wrap_up.run(call_id=call.id, tenant_id=tenant_id)
    db.refresh(call)
    return call


class TestWrapUpDispositionFallback:
    def test_valid_no_answer_disposition_maps_correctly(self, db):
        tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(tenant); db.commit()
        call = _make_call(db, tenant.id)

        result = _run(db, tenant.id, call, {
            "summary": "Greeting played, nobody spoke.",
            "suggested_disposition": "no_answer",
            "next_action": "Call back",
        })
        assert result.ai_disposition == CallDisposition.NO_ANSWER

    def test_missing_disposition_field_defaults_to_none_not_callback(self, db):
        tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(tenant); db.commit()
        call = _make_call(db, tenant.id)

        result = _run(db, tenant.id, call, {
            "summary": "Brief inbound call with no clear outcome.",
            "next_action": "Contact guest to clarify.",
            # suggested_disposition deliberately absent -- a malformed/
            # partial tool call, the real shape that produced the live bug.
        })
        assert result.ai_disposition is None

    def test_unrecognized_disposition_defaults_to_none_not_callback(self, db):
        tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(tenant); db.commit()
        call = _make_call(db, tenant.id)

        result = _run(db, tenant.id, call, {
            "summary": "Unclear outcome.",
            "suggested_disposition": "missed",  # not a real key in DISPOSITION_MAP
            "next_action": "Contact guest.",
        })
        assert result.ai_disposition is None

    def test_case_and_whitespace_normalized(self, db):
        tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(tenant); db.commit()
        call = _make_call(db, tenant.id)

        result = _run(db, tenant.id, call, {
            "summary": "Quoted a caravan package.",
            "suggested_disposition": "  Quoted  ",
            "next_action": "Follow up tomorrow.",
        })
        assert result.ai_disposition == CallDisposition.QUOTED


class TestWrapUpUsesRealTranscript:
    """Regression: wrap_up.py used to read Call.ai_summary as "the
    transcript" -- nothing ever populates that field except wrap_up's own
    prior run, so the model has never had real conversation content, ever.
    Now queries Transcript directly, same construction judge.py already
    used correctly."""

    def test_real_transcript_reaches_the_prompt_not_stale_summary(self, db):
        tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(tenant); db.commit()
        # A stale prior-run summary sitting on the row -- must NOT be what
        # reaches the model this time.
        call = _make_call(db, tenant.id, ai_summary="Brief inbound call with no clear outcome.")
        transcript = Transcript(
            id=str(uuid.uuid4()), tenant_id=tenant.id, call_id=call.id,
            provider="sarvam", language="en",
            turns=json.dumps([{"speaker": "guest", "t0": 0.0, "t1": 3.0, "text": "I'd like to book for a family of four next weekend."}]),
            raw_text="I'd like to book for a family of four next weekend.",
        )
        db.add(transcript); db.commit()

        captured = {}

        class _CapturingLLM:
            async def complete(self, **kwargs):
                captured["system_prompt"] = kwargs.get("system_prompt", "")
                return {"tool_use": {
                    "summary": "Guest wants to book for 4 next weekend.",
                    "suggested_disposition": "hot", "next_action": "Send quote",
                }, "model": "fake"}

        with patch.object(wrap_up_module, "get_llm", return_value=_CapturingLLM()), \
             patch.object(wrap_up_module, "SessionLocal", return_value=SASession(bind=db.connection())):
            wrap_up.run(call_id=call.id, tenant_id=tenant.id)

        assert "family of four next weekend" in captured["system_prompt"]
        assert "Brief inbound call with no clear outcome" not in captured["system_prompt"]

    def test_missing_transcript_falls_back_to_placeholder_not_crash(self, db):
        tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(tenant); db.commit()
        call = _make_call(db, tenant.id)  # no Transcript row at all

        result = _run(db, tenant.id, call, {
            "summary": "No transcript available.",
            "suggested_disposition": "no_answer",
            "next_action": "N/A",
        })
        assert result.ai_disposition == CallDisposition.NO_ANSWER
