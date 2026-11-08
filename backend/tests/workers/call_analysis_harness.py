"""Shared harness for tasks.analyze_call tests: a scripted model (no real LLM), the task's session on the test
connection, an in-memory stand-in for the Redis answer cache, and the after-call effects captured."""

import json
import uuid
from contextlib import ExitStack
from unittest.mock import patch

from sqlalchemy.orm import Session as SASession

from app.models.call import Call, CallDirection
from app.models.tenant import Tenant
from app.models.transcript import Transcript
from app.services.qa_service import DEFAULT_RUBRIC_CRITERIA
from app.workers.tasks import call_analysis as task_mod

SPEECH = [
    {"speaker": "agent", "t0": 0.0, "t1": 2.0, "text": "Hello, thanks for calling Ratha caravans."},
    {"speaker": "guest", "t0": 2.0, "t1": 6.0, "text": "I'd like to book for a family of four next weekend."},
]


def tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"ca-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    return t


def call(db, tenant_id, *, turns=SPEECH, with_transcript=True, **overrides):
    fields = dict(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        ivr_provider="vobiz",
        ivr_call_id=f"c-{uuid.uuid4().hex[:8]}",
        direction=CallDirection.INBOUND,
        from_number="+919800000001",
        to_number="+912200000000",
        duration_seconds=120,
    )
    fields.update(overrides)
    c = Call(**fields)
    db.add(c)
    db.commit()
    if with_transcript:
        db.add(
            Transcript(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                call_id=c.id,
                provider="sarvam",
                language="en",
                turns=json.dumps(turns),
                raw_text=" ".join(t["text"] for t in turns),
            )
        )
        db.commit()
    return c


def scores(**overrides):
    """Every default-rubric criterion at full marks (100%), with per-id overrides."""
    full = {"YES_NO": 1, "ZERO_THREE": 3, "AUTO_FAIL": 1}
    return [
        {"id": c["id"], "score": overrides.get(c["id"], full[c["method"]]), "evidence": "quoted turn"}
        for c in DEFAULT_RUBRIC_CRITERIA
    ]


def answer(**overrides):
    """A complete call-analysis-v6 tool answer."""
    base = {
        "criterion_scores": scores(),
        "has_auto_fail": False,
        "confidence": 0.9,
        "agent_strengths": ["Warm greeting"],
        "agent_growth_areas": ["Ask for the dates earlier"],
        "summary": "Guest wants to book for 4 next weekend.",
        "suggested_disposition": "hot",
        "next_action": "Send the quote",
        "outcome": "negotiating",
        "language": "en",
        "is_code_mixed": False,
        "occasion": "family",
        "budget_signal": "",
        "decision_stage": "ready_to_book",
        "competitor_mentioned": "",
        "conversion_probability": 70,
        "lost_reason": "",
        "guest_name": "",
    }
    base.update(overrides)
    return base


class ScriptedLLM:
    """get_llm stand-in: records (task, kwargs) per model call; answers per task key, or raises."""

    def __init__(self, tool_use=None, recheck=None, error=None, recheck_error=None):
        self.calls = []
        self._answers = {"call_analysis": tool_use, "deep_reason": recheck}
        self._errors = {"call_analysis": error, "deep_reason": recheck_error}

    def get_llm(self, task, tenant_id=None):
        llm = self

        class _Adapter:
            async def complete(self, **kw):
                llm.calls.append((task, kw))
                if llm._errors.get(task):
                    raise llm._errors[task]
                return {"tool_use": llm._answers.get(task), "model": f"fake-{task}"}

        return _Adapter()

    def tasks(self):
        return [t for t, _ in self.calls]


class Effects:
    def __init__(self):
        self.store = {}
        self.autopilot = []
        self.triggers = []
        self.sse = []
        self.pushes = []


def run(db, tenant_id, call_id, llm, effects=None):
    """Run tasks.analyze_call synchronously. Returns the Effects (shared across runs when passed in)."""
    effects = effects or Effects()
    with ExitStack() as stack:
        stack.enter_context(patch("app.services.call_analysis.get_llm", llm.get_llm))
        stack.enter_context(patch.object(task_mod, "SessionLocal", return_value=SASession(bind=db.connection())))
        stack.enter_context(patch("app.core.cache.get_cached", side_effect=lambda k: effects.store.get(k)))
        stack.enter_context(
            patch(
                "app.core.cache.set_cached",
                side_effect=lambda k, v, ttl=300: effects.store.__setitem__(k, json.loads(json.dumps(v))),
            )
        )
        stack.enter_context(
            patch(
                "app.services.push_service.send_to_tenant",
                side_effect=lambda *a, **kw: effects.pushes.append(kw.get("title")),
            )
        )
        stack.enter_context(patch.object(task_mod, "_emit_sse", side_effect=lambda **kw: effects.sse.append(kw)))
        stack.enter_context(
            patch(
                "app.services.lead_autopilot_service.queue_evaluation",
                side_effect=lambda *a, **kw: effects.autopilot.append(a),
            )
        )
        stack.enter_context(
            patch(
                "app.workers.tasks.automation_engine.fire_trigger.apply_async",
                side_effect=lambda **kw: effects.triggers.append(kw),
            )
        )
        task_mod.analyze_call.run(call_id=call_id, tenant_id=tenant_id)
    db.expire_all()
    return effects
