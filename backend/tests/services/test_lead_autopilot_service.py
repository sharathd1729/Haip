"""Lead autopilot service: modes, guards, applying through inquiry_service (audited), Undo, pinning, the stage hook on
BOTH transition paths, the AI classifier with a mocked router, and the daily sweep."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.audit_event import AuditEvent
from app.models.inquiry import Inquiry, InquiryStage, LostReason
from app.models.inquiry_360 import InquiryStageLog
from app.models.lead_autopilot import LeadAutopilotEvent
from app.services import inquiry_service, lead_autopilot_service as svc
from tests.services._autopilot_fixtures import NOW, booking, lead, msg, quote, tenant


def _eval(db, t, inq, **kw):
    ev = svc.evaluate(db, t.id, inq.id, now=NOW, **kw)
    db.commit()
    db.refresh(inq)
    return ev


def _declined_lead(db, mode="autopilot", **settings):
    t, s = tenant(db, mode=mode, **settings)
    g, inq, conv = lead(db, t.id, s["active"])
    msg(db, t.id, conv, "We have cancelled the trip, thanks")
    return t, s, g, inq, conv


class TestModes:
    def test_default_mode_is_suggest_and_nothing_moves(self, db):
        t, s, _, inq, _ = _declined_lead(db, mode=None)
        assert svc.get_settings(db, t.id)["mode"] == "suggest"
        ev = _eval(db, t, inq)
        assert ev.status == "suggested" and inq.stage_id == s["active"].id
        assert db.query(InquiryStageLog).filter_by(inquiry_id=inq.id).count() == 0

    def test_off_records_nothing(self, db):
        t, s, _, inq, _ = _declined_lead(db, mode="off")
        assert _eval(db, t, inq) is None
        assert db.query(LeadAutopilotEvent).filter_by(inquiry_id=inq.id).count() == 0

    def test_autopilot_applies_through_inquiry_service_and_audits_with_evidence(self, db):
        t, s, _, inq, _ = _declined_lead(db)
        ev = _eval(db, t, inq)
        assert ev.status == "applied" and inq.stage_id == s["lost"].id
        assert inq.stage == InquiryStage.LOST and inq.lost_reason == LostReason.OTHER
        assert inq.lost_note.startswith("Autopilot (Other)")
        log_row = db.query(InquiryStageLog).filter_by(inquiry_id=inq.id).one()
        assert (log_row.from_stage, log_row.to_stage, log_row.changed_by) == ("active", "lost", "system")
        audit = db.query(AuditEvent).filter_by(tenant_id=t.id, action="lead_autopilot.stage_moved").one()
        assert audit.payload["actor"] == "autopilot" and audit.payload["rule"] == "explicit_decline"
        assert audit.payload["evidence"][0]["kind"] == "message"

    def test_evaluation_is_idempotent(self, db):
        t, s, _, inq, _ = _declined_lead(db, mode="suggest")
        first = _eval(db, t, inq)
        second = _eval(db, t, inq)
        assert first.id == second.id
        assert db.query(LeadAutopilotEvent).filter_by(inquiry_id=inq.id).count() == 1


class TestGuards:
    def test_pinned_lead_is_left_alone(self, db):
        t, s, _, inq, _ = _declined_lead(db)
        svc.set_pinned(db, t.id, inq, None, True)
        db.commit()
        assert _eval(db, t, inq) is None and inq.stage_id == s["active"].id

    def test_never_moves_out_of_sold(self, db):
        t, s = tenant(db, mode="autopilot")
        _, inq, conv = lead(db, t.id, s["sold"], check_in="2026-10-01")
        msg(db, t.id, conv, "not interested")
        assert _eval(db, t, inq) is None

    def test_live_payment_link_blocks_auto_lost(self, db):
        t, s = tenant(db, mode="autopilot")
        _, inq, conv = lead(db, t.id, s["active"], check_in="2026-10-26")
        quote(db, t.id, inq.id, ago=timedelta(days=9), link_status="created")
        ev = _eval(db, t, inq)
        assert ev.status == "blocked" and "payment link" in ev.blocked_reason and inq.stage_id == s["active"].id

    def test_future_check_in_with_a_live_quote_blocks_auto_lost(self, db):
        t, s = tenant(db, mode="autopilot")
        _, inq, conv = lead(db, t.id, s["active"], check_in="2026-10-26")
        quote(db, t.id, inq.id, ago=timedelta(days=9), valid_days=5)
        ev = _eval(db, t, inq)
        assert ev.status == "blocked" and inq.stage_id == s["active"].id

    def test_booking_still_moves_to_sold_with_a_live_quote(self, db):
        t, s = tenant(db, mode="autopilot")
        g, inq, _ = lead(db, t.id, s["active"], check_in="2026-10-26")
        quote(db, t.id, inq.id, valid_days=5, link_status="created")
        booking(db, t.id, g.id, inq.id)
        assert _eval(db, t, inq).status == "applied" and inq.stage_id == s["sold"].id


class TestUndo:
    def test_undo_restores_the_stage_and_lost_reason_and_is_never_reapplied(self, db):
        t, s, _, inq, _ = _declined_lead(db)
        inq.lost_reason, inq.lost_note = LostReason.BUDGET_MISMATCH, "earlier note"
        db.commit()
        ev = _eval(db, t, inq)
        svc.undo(db, t.id, inq, ev.id, None)
        db.commit()
        db.refresh(inq)
        db.refresh(ev)
        assert inq.stage_id == s["active"].id and inq.stage != InquiryStage.LOST
        assert inq.lost_reason == LostReason.BUDGET_MISMATCH and inq.lost_note == "earlier note"
        assert ev.status == "undone"
        assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="lead_autopilot.undone").count() == 1
        # The old decline predates the undo (the stage was re-entered), so nothing fires again...
        assert _eval(db, t, inq) is None and inq.stage_id == s["active"].id
        # ...and even a NEW decline is only suggested: a move a person undid is never re-applied to the same stage.
        after_undo = datetime.now(timezone.utc) + timedelta(minutes=1)
        msg(db, t.id, inq.conversations.first(), "not interested", ago=NOW - after_undo)
        again = _eval(db, t, inq)
        assert again.status == "suggested" and inq.stage_id == s["active"].id

    def test_undo_after_a_person_moved_the_lead_is_refused(self, db):
        t, s, _, inq, _ = _declined_lead(db, mode="autopilot")
        _, inq2, _ = lead(db, t.id, s["general_enquiry"], check_in="2026-10-24", adults=4)
        ev = _eval(db, t, inq2)                          # -> active
        inquiry_service.update_stage_by_id(db, tenant_id=t.id, inquiry_id=inq2.id, new_stage_id=s["unsuitable"].id,
                                           actor_user_id=None, actor_role="owner")
        db.commit()
        db.refresh(ev)
        assert ev.status == "superseded"
        with pytest.raises(svc.AutopilotActionError) as err:
            svc.undo(db, t.id, inq2, ev.id, None)
        assert err.value.status_code == 409

    def test_a_sold_move_cannot_be_undone(self, db):
        t, s = tenant(db, mode="autopilot")
        g, inq, _ = lead(db, t.id, s["active"])
        booking(db, t.id, g.id, inq.id)
        ev = _eval(db, t, inq)
        with pytest.raises(svc.AutopilotActionError) as err:
            svc.undo(db, t.id, inq, ev.id, None)
        assert err.value.status_code == 409 and "booking" in err.value.detail


class TestStageHookOnBothPaths:
    def test_stage_id_path_accepts_a_followed_suggestion(self, db):
        t, s, _, inq, _ = _declined_lead(db, mode="suggest")
        ev = _eval(db, t, inq)
        inquiry_service.update_stage_by_id(db, tenant_id=t.id, inquiry_id=inq.id, new_stage_id=s["lost"].id,
                                           actor_user_id=None, actor_role="owner", reason="agreed")
        db.commit()
        db.refresh(ev)
        assert ev.status == "accepted"

    def test_legacy_enum_path_supersedes_open_decisions(self, db):
        t, s, _, inq, _ = _declined_lead(db, mode="suggest")
        inq.stage = InquiryStage.NEW
        db.commit()
        ev = _eval(db, t, inq)
        inquiry_service.update_stage(db, tenant_id=t.id, inquiry_id=inq.id, new_stage=InquiryStage.RESPONDING,
                                     actor_user_id=None, actor_role="owner")
        db.commit()
        db.refresh(ev)
        assert ev.status == "superseded"


def _fake_llm(payload):
    class _LLM:
        async def complete(self, **kwargs):
            _LLM.seen = kwargs
            return {"content": payload if isinstance(payload, str) else json.dumps(payload), "model": "fake-20b"}
    return lambda task, tenant_id=None: _LLM()


class TestAiClassifier:
    def _ambiguous(self, db, mode="autopilot"):
        t, s = tenant(db, mode=mode)
        _, inq, conv = lead(db, t.id, s["active"], check_in="2026-10-30")
        msg(db, t.id, conv, "Rate for 2 nights Coorg, 4 adults?", ago=timedelta(hours=5))
        msg(db, t.id, conv, "It is ₹42,000 for 2 nights", inbound=False, ago=timedelta(hours=4))
        m = msg(db, t.id, conv, "Honestly that is beyond what we can spend, we will skip this time", ago=timedelta(hours=3))
        return t, s, inq, m

    def _run(self, db, t, inq, payload):
        with patch("app.adapters.llm.get_llm", _fake_llm(payload)), \
             patch("app.core.cache.get_cached", return_value=None), patch("app.core.cache.set_cached"):
            return _eval(db, t, inq, allow_ai=True)

    def test_confident_ai_with_real_evidence_is_applied(self, db):
        t, s, inq, m = self._ambiguous(db)
        ev = self._run(db, t, inq, {"decision": "lost", "lost_reason": "price", "confidence": 0.91,
                                    "reason": "Guest says the price is beyond budget and will skip",
                                    "evidence": [{"ref": f"m:{m.id}", "quote": "beyond what we can spend"}]})
        assert ev.source == "ai" and ev.status == "applied" and inq.stage_id == s["lost"].id
        assert inq.lost_reason == LostReason.BUDGET_MISMATCH
        assert ev.prompt_version == "lead-autopilot-classify-v1" and ev.evidence[0]["id"] == m.id

    def test_below_threshold_stays_a_suggestion(self, db):
        t, s, inq, m = self._ambiguous(db)
        ev = self._run(db, t, inq, {"decision": "lost", "lost_reason": "price", "confidence": 0.7, "reason": "x",
                                    "evidence": [{"ref": f"m:{m.id}", "quote": "beyond what we can spend"}]})
        assert ev.status == "suggested" and inq.stage_id == s["active"].id

    def test_invented_evidence_is_never_applied(self, db):
        t, s, inq, m = self._ambiguous(db)
        ev = self._run(db, t, inq, {"decision": "lost", "lost_reason": "price", "confidence": 0.99, "reason": "x",
                                    "evidence": [{"ref": f"m:{m.id}", "quote": "we booked with a competitor"},
                                                 {"ref": "m:not-a-real-id", "quote": "beyond"}]})
        assert ev.status == "suggested" and ev.evidence == []

    def test_ai_never_marks_sold(self, db):
        t, s, inq, m = self._ambiguous(db)
        ev = self._run(db, t, inq, {"decision": "booked", "confidence": 0.99, "reason": "x",
                                    "evidence": [{"ref": f"m:{m.id}", "quote": "skip this time"}]})
        assert ev.status == "suggested" and inq.stage_id == s["active"].id

    @pytest.mark.parametrize("raw", ["not json at all", '{"decision": "maybe"}', '{"decision": "lost", "conf', ""])
    def test_malformed_output_moves_nothing(self, db, raw):
        t, s, inq, _ = self._ambiguous(db)
        assert self._run(db, t, inq, raw) is None and inq.stage_id == s["active"].id

    def test_provider_error_moves_nothing(self, db):
        t, s, inq, _ = self._ambiguous(db)

        class _Boom:
            async def complete(self, **kw):
                raise TimeoutError("nim 504")
        with patch("app.adapters.llm.get_llm", lambda task, tenant_id=None: _Boom()), \
             patch("app.core.cache.get_cached", return_value=None), patch("app.core.cache.set_cached"):
            assert _eval(db, t, inq, allow_ai=True) is None

    def test_the_prompt_carries_references_and_no_phone_numbers(self, db):
        t, s, inq, m = self._ambiguous(db)
        conv_msg = msg(db, t.id, inq.conversations.first(), "call me on 9845012345", ago=timedelta(hours=2))
        captured = {}

        class _LLM:
            async def complete(self, **kw):
                captured.update(kw)
                return {"content": '{"decision": "none", "confidence": 0.2, "reason": "", "evidence": []}'}
        with patch("app.adapters.llm.get_llm", lambda task, tenant_id=None: _LLM()), \
             patch("app.core.cache.get_cached", return_value=None), patch("app.core.cache.set_cached"):
            _eval(db, t, inq, allow_ai=True)
        assert f"[m:{conv_msg.id}]" in captured["user_message"] and "9845012345" not in captured["user_message"]

    def test_the_sweep_never_calls_the_llm(self, db):
        t, s, inq, _ = self._ambiguous(db)
        with patch("app.services.lead_autopilot_ai.classify") as classify:
            svc.sweep_tenant(db, t.id)
        classify.assert_not_called()


def test_sweep_is_tenant_scoped(db):
    ta, sa = tenant(db, mode="autopilot")
    tb, sb = tenant(db, mode="autopilot")
    _, inq_a, _ = lead(db, ta.id, sa["active"], check_in="2026-10-01")
    _, inq_b, _ = lead(db, tb.id, sb["active"], check_in="2026-10-01")
    with patch("app.services.lead_autopilot_rules.datetime") as dt:
        dt.now.return_value = NOW
        svc.sweep_tenant(db, ta.id)
    assert db.query(Inquiry).get(inq_a.id).stage_id == sa["lost"].id
    assert db.query(Inquiry).get(inq_b.id).stage_id == sb["active"].id


def test_settings_update_is_audited_and_validated(db):
    t, _ = tenant(db)
    after = svc.update_settings(db, t.id, None, {"mode": "autopilot", "ai_threshold": 0.9})
    db.commit()
    assert after["mode"] == "autopilot" and after["ai_threshold"] == 0.9 and after["silence_days"] == 14
    audit = db.query(AuditEvent).filter_by(tenant_id=t.id, action="lead_autopilot.settings_changed").one()
    assert audit.payload["changed"]["mode"] == {"from": "suggest", "to": "autopilot"}
    with pytest.raises(Exception):
        svc.update_settings(db, t.id, None, {"ai_threshold": 0.2})
