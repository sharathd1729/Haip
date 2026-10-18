"""Lead autopilot Celery tasks: exact-name routes on a consumed queue, the daily beat entry, the per-lead task, the
sweep (rules only, never the LLM) and the triggers from the lead summary and the call wrap-up."""
import json
from unittest.mock import patch

from app.models.inquiry import Inquiry
from app.models.lead_autopilot import LeadAutopilotEvent
from app.workers.celery_app import celery_app
from app.workers.tasks import lead_autopilot as tasks
from tests.services._autopilot_fixtures import lead, msg, tenant


def _no_close(db):
    return patch.object(db, "close")


def test_routes_and_beat():
    routes = celery_app.conf.task_routes
    assert routes["lead_autopilot.evaluate_inquiry"] == {"queue": "ai_scoring"}
    assert routes["lead_autopilot.sweep_all_tenants"] == {"queue": "ai_scoring"}
    beat = celery_app.conf.beat_schedule["lead-autopilot-daily-sweep"]
    assert beat["task"] == "lead_autopilot.sweep_all_tenants"
    assert "lead_autopilot.evaluate_inquiry" in celery_app.tasks and "lead_autopilot.sweep_all_tenants" in celery_app.tasks


def test_evaluate_task_applies_in_autopilot_mode(db):
    t, s = tenant(db, mode="autopilot")
    _, inq, conv = lead(db, t.id, s["active"])
    msg(db, t.id, conv, "we are not interested anymore")
    with patch.object(tasks, "SessionLocal", return_value=db), _no_close(db), \
         patch("app.core.cache.get_cached", return_value=None), patch("app.core.cache.set_cached"), \
         patch("app.services.lead_autopilot_ai.classify") as classify:
        tasks.evaluate_inquiry.run(inquiry_id=inq.id, tenant_id=t.id, trigger="call")
    db.expire_all()
    assert db.query(Inquiry).get(inq.id).stage_id == s["lost"].id
    classify.assert_not_called()                                # a rule decided: no LLM call


def test_sweep_task_covers_every_active_tenant_rules_only(db):
    ta, sa = tenant(db, mode="autopilot")
    tb, sb = tenant(db, mode="off")
    _, inq_a, _ = lead(db, ta.id, sa["active"], check_in="2026-10-01")
    _, inq_b, _ = lead(db, tb.id, sb["active"], check_in="2026-10-01")
    with patch.object(tasks, "SessionLocal", return_value=db), _no_close(db), \
         patch("app.services.lead_autopilot_ai.classify") as classify:
        tasks.sweep_all_tenants.run()
    db.expire_all()
    assert db.query(Inquiry).get(inq_a.id).stage_id == sa["lost"].id
    assert db.query(Inquiry).get(inq_b.id).stage_id == sb["active"].id            # mode off: untouched
    assert db.query(LeadAutopilotEvent).filter_by(tenant_id=tb.id).count() == 0
    classify.assert_not_called()


def test_the_lead_summary_queues_an_evaluation(db):
    from app.workers.tasks import generate_ai_summary as gas
    t, s = tenant(db)
    _, inq, conv = lead(db, t.id, s["active"])
    msg(db, t.id, conv, "4 of us, 24-25 Oct")

    class _LLM:
        async def complete(self, **kw):
            return {"content": json.dumps({"summary": "Kiran wants 24-25 Oct.", "analysis": {}, "extracted": {}}), "model": "f"}
    with patch.object(gas, "get_llm", return_value=_LLM()), patch.object(gas, "SessionLocal", return_value=db), \
         _no_close(db), patch("app.services.lead_autopilot_service.queue_evaluation") as queued:
        gas.generate_ai_summary.run(inquiry_id=inq.id, tenant_id=t.id)
    queued.assert_called_once_with(inq.id, t.id, trigger="summary")
