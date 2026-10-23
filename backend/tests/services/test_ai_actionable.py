"""Actionable AI output (services/ai_actionable.py) in the three analyses: call wrap-up v5 (calls.ai_insights), lead
summary v8 (inquiries.ai_analysis) and daily briefing v2. Mocked LLM JSON shaped like real Ratha answers, including
malformed output, which must degrade to empty fields -- never a crash, never an invented rupee figure."""
import json
import uuid
from unittest.mock import patch

from sqlalchemy.orm import Session as SASession

from app.core.prompt_versions import get_version
from app.models.call import Call, CallDirection
from app.models.tenant import Tenant
from app.services import ai_actionable as aa
from app.services.daily_briefing_service import _parse_response
from app.workers.tasks import generate_ai_summary as gas
from app.workers.tasks import wrap_up as wrap_up_module

KIRAN = {
    "next_best_action": {"action": "Call Kiran: confirm 24-25 Oct for 4 adults, offer the Coorg route as fallback",
                         "owner": "Ananya", "channel": "Call", "deadline": "today before 6 PM", "why": "Asked for a callback"},
    "blocking_objection": {"objection": "Price feels high for 2 nights", "counter": "Offer the weekday rate on 22-23 Oct"},
    "missed_revenue": [
        {"kind": "extra_night", "what": "Guest hinted at a third night", "est_inr": 21000, "grounded": True,
         "evidence": "a third night would be ₹21,000"},
        {"kind": "add_on", "what": "No bonfire add-on offered", "est_inr": 5000, "grounded": False, "evidence": ""},
    ],
    "temperature": {"value": "Warm", "reason": "Engaged, comparing options"},
    "haip_updates": [{"field": "check_in", "value": "2026-10-24", "why": "Guest confirmed on the call"},
                     {"field": "", "value": "x"}],
}


class TestCleaner:
    def test_real_shaped_answer_is_kept_and_normalised(self):
        out = aa.clean_actionable(KIRAN)
        assert out["next_best_action"]["channel"] == "call" and out["next_best_action"]["owner"] == "Ananya"
        assert out["blocking_objection"]["counter"].startswith("Offer the weekday rate")
        assert out["temperature"] == {"value": "warm", "reason": "Engaged, comparing options"}
        assert [m["est_inr"] for m in out["missed_revenue"]] == [21000.0, None]   # ungrounded estimate dropped
        assert out["haip_updates"] == [{"field": "check_in", "value": "2026-10-24", "why": "Guest confirmed on the call"}]

    def test_malformed_values_degrade_to_empty(self):
        out = aa.clean_actionable({"next_best_action": ["call"], "temperature": "boiling", "missed_revenue": "lots",
                                   "blocking_objection": "price", "haip_updates": {"field": "x"}})
        assert out["next_best_action"] is None
        assert aa.clean_next_action("Call Kiran today")["action"] == "Call Kiran today"   # plain text still usable
        assert out["temperature"] is None and out["missed_revenue"] == [] and out["blocking_objection"] is None
        assert aa.clean_actionable("not a dict") == {"next_best_action": None, "blocking_objection": None,
                                                     "missed_revenue": [], "temperature": None, "haip_updates": []}

    def test_grounded_needs_evidence(self):
        out = aa.clean_missed_revenue([{"what": "x", "est_inr": "₹12,500", "grounded": True, "evidence": None}])
        assert out[0]["est_inr"] is None and out[0]["grounded"] is False

    def test_one_line_next_action(self):
        assert aa.next_action_text(aa.clean_next_action(KIRAN["next_best_action"])) == \
            "Call Kiran: confirm 24-25 Oct for 4 adults, offer the Coorg route as fallback (call, today before 6 PM)"


def _call(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    c = Call(id=str(uuid.uuid4()), tenant_id=t.id, ivr_provider="vobiz", ivr_call_id=f"c-{uuid.uuid4().hex[:8]}",
             direction=CallDirection.OUTBOUND, from_number="+912271264296", to_number="+919845012345", duration_seconds=240)
    db.add(c)
    db.commit()
    return t, c


def _run_wrap_up(db, t, c, tool_use):
    captured = {}

    class _LLM:
        async def complete(self, **kw):
            captured.update(kw)
            return {"tool_use": tool_use, "model": "fake"}
    with patch.object(wrap_up_module, "get_llm", return_value=_LLM()), \
         patch.object(wrap_up_module, "SessionLocal", return_value=SASession(bind=db.connection())), \
         patch("app.services.lead_autopilot_service.queue_evaluation") as queued, \
         patch.object(wrap_up_module, "_emit_sse"):
        wrap_up_module.wrap_up.run(call_id=c.id, tenant_id=t.id)
    db.refresh(c)
    return c, captured, queued


class TestWrapUpV5:
    def test_insights_are_stored_and_the_autopilot_is_queued(self, db):
        t, c = _call(db)
        c, captured, queued = _run_wrap_up(db, t, c, {
            "summary": "Kiran wants Coorg 24-25 Oct for 4 adults; price feels high.", "suggested_disposition": "hot",
            "next_action": "", "confidence": 0.82, "outcome": "negotiating", **KIRAN})
        assert c.ai_insights["outcome"] == "negotiating" and c.ai_insights["decline_reason"] is None
        assert c.ai_insights["next_best_action"]["deadline"] == "today before 6 PM"
        assert c.ai_next_action.startswith("Call Kiran: confirm 24-25 Oct")       # filled from next_best_action
        assert "next_best_action" in captured["system_prompt"] and "outcome" in captured["system_prompt"]
        queued.assert_called_once()

    def test_a_decline_keeps_its_reason_and_quote(self, db):
        t, c = _call(db)
        c, _, _ = _run_wrap_up(db, t, c, {"summary": "Declined.", "suggested_disposition": "lost", "next_action": "None",
                                          "outcome": "declined", "decline_reason": "booked_elsewhere",
                                          "decline_quote": "We already booked another caravan", "confidence": 0.9})
        assert (c.ai_insights["decline_reason"], c.ai_insights["decline_quote"], c.ai_insights["confidence"]) == \
               ("booked_elsewhere", "We already booked another caravan", 0.9)

    def test_an_old_shaped_answer_still_works(self, db):
        t, c = _call(db)
        c, _, _ = _run_wrap_up(db, t, c, {"summary": "Short call.", "suggested_disposition": "callback",
                                          "next_action": "Call back tomorrow"})
        assert c.ai_insights is None and c.ai_next_action == "Call back tomorrow"


class TestLeadSummaryV8:
    def test_actionable_fields_land_in_ai_analysis_with_old_keys_intact(self):
        raw = json.dumps({"summary": "Kiran wants Coorg.", "analysis": {"intent": "Coorg trip", "sentiment": "hesitant",
                                                                         "reply_urgency": "high", **KIRAN},
                          "extracted": {}, "lead_analysis": "Warm."})
        _, analysis, _, _ = gas._parse_summary_response(raw)
        assert analysis["intent"] == "Coorg trip" and analysis["sentiment"] == "hesitant"
        assert analysis["next_best_action"]["channel"] == "call" and analysis["temperature"]["value"] == "warm"
        assert analysis["next_action"].startswith("Call Kiran")                   # derived when the model left it out

    def test_truncated_json_keeps_the_old_salvage_path(self):
        summary, analysis, _, _ = gas._parse_summary_response('{"summary": "Kiran wants Coorg.", "analysis": {"next_best')
        assert summary == "Kiran wants Coorg." and analysis is None

    def test_prompt_asks_for_the_block_and_is_versioned(self):
        assert '"next_best_action"' in gas.SYSTEM_PROMPT and "__ACTIONABLE__" not in gas.SYSTEM_PROMPT
        assert get_version("leads360_summary") == "leads360-summary-v9"
        assert get_version("call_wrap_up") == "call-wrap-up-v5" and get_version("call_judge") == "call-judge-v3"


class TestDailyBriefingV2:
    def test_actions_are_parsed(self):
        out = _parse_response(json.dumps({"narrative": "3 guests waiting since morning.", "flags": [],
                                          "actions": [{"lead": "Priya", "action": "Reply on the Nandi Hills route",
                                                       "owner": "team", "channel": "whatsapp", "deadline": "within 1 hour"},
                                                      {"lead": "", "action": "x"}, "junk"]}))
        assert out["actions"] == [{"lead": "Priya", "action": "Reply on the Nandi Hills route", "owner": "team",
                                   "channel": "whatsapp", "deadline": "within 1 hour", "why": None}]
        assert get_version("daily_briefing") == "daily-briefing-v2"

    def test_v1_shaped_answer_still_parses(self):
        out = _parse_response(json.dumps({"narrative": "All quiet.", "flags": [{"type": "pattern", "text": "x"}]}))
        assert out["narrative"] == "All quiet." and out["actions"] == []
