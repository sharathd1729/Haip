"""Suggested lead actions -- "autopilot" pass (Ratha, Sep 2026). A human
always clicks "Apply"; nothing here moves the pipeline on its own. See
lead_recommendation_service.py.
"""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.call import Call, CallDirection, CallDisposition
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.tenant import Tenant
from app.services.lead_recommendation_service import get_lead_recommendation

NOW = datetime.now(timezone.utc)


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"lr-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush()
    return t


def _stages(db, tenant_id):
    stages = {
        "new": PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key="new", label="New", order=1),
        "active": PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key="active", label="Active", order=2),
        "quoted": PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key="quoted", label="Quoted", order=3),
        "sold": PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key="sold", label="Sold", order=4, is_closed_won=True),
        "lost": PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key="lost", label="Lost", order=5, is_closed_lost=True),
    }
    for s in stages.values():
        db.add(s)
    db.flush()
    return stages


def _guest_and_inquiry(db, tenant_id, stage):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Kiran")
    db.add(g); db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, stage_id=stage.id)
    db.add(inq); db.flush()
    return g, inq


def _call(db, tenant_id, guest_id, *, direction=CallDirection.OUTBOUND, minutes_ago=10, **overrides):
    defaults = dict(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
        ivr_provider="vobiz", ivr_call_id=f"c-{uuid.uuid4().hex[:8]}",
        direction=direction, from_number="+912271264296", to_number="+917249066854",
        duration_seconds=0, created_at=NOW - timedelta(minutes=minutes_ago),
    )
    defaults.update(overrides)
    call = Call(**defaults)
    db.add(call); db.flush()
    return call


class TestNoSignalIsTheCommonCase:
    def test_no_suggestion_with_nothing_to_go_on(self, db):
        t = _tenant(db)
        stages = _stages(db, t.id)
        _, inq = _guest_and_inquiry(db, t.id, stages["active"])
        db.commit()

        assert get_lead_recommendation(db, t.id, inq) is None

    def test_no_suggestion_when_the_inquiry_is_already_in_a_terminal_stage(self, db):
        t = _tenant(db)
        stages = _stages(db, t.id)
        g, inq = _guest_and_inquiry(db, t.id, stages["lost"])
        _call(db, t.id, g.id, human_disposition=CallDisposition.LOST)
        db.commit()

        assert get_lead_recommendation(db, t.id, inq) is None


class TestMarkLostSuggestion:
    def test_suggests_mark_lost_when_the_latest_call_was_scored_lost(self, db):
        t = _tenant(db)
        stages = _stages(db, t.id)
        g, inq = _guest_and_inquiry(db, t.id, stages["active"])
        _call(db, t.id, g.id, ai_disposition=CallDisposition.LOST, lost_reason="budget_mismatch")
        db.commit()

        rec = get_lead_recommendation(db, t.id, inq)
        assert rec is not None
        assert rec["action_type"] == "move_stage"
        assert rec["action_config"]["new_stage_id"] == stages["lost"].id
        assert "budget_mismatch" in rec["reason"] or "budget_mismatch" in rec["action_config"]["reason"]
        assert rec["confirm"] is True

    def test_suggests_mark_lost_after_enough_consecutive_unanswered_outbound_calls(self, db):
        t = _tenant(db)
        stages = _stages(db, t.id)
        g, inq = _guest_and_inquiry(db, t.id, stages["active"])
        for i in range(3):
            _call(db, t.id, g.id, ivr_dial_status="no-answer", minutes_ago=30 - i * 5)
        db.commit()

        rec = get_lead_recommendation(db, t.id, inq)
        assert rec is not None
        assert rec["action_config"]["new_stage_id"] == stages["lost"].id
        assert "3 calls" in rec["reason"]

    def test_fewer_than_the_threshold_suggests_nothing(self, db):
        t = _tenant(db)
        stages = _stages(db, t.id)
        g, inq = _guest_and_inquiry(db, t.id, stages["active"])
        _call(db, t.id, g.id, ivr_dial_status="no-answer", minutes_ago=10)
        _call(db, t.id, g.id, ivr_dial_status="no-answer", minutes_ago=20)
        db.commit()

        assert get_lead_recommendation(db, t.id, inq) is None

    def test_a_reply_since_the_streak_started_cancels_the_suggestion(self, db):
        """The guest is still engaged (replied on WhatsApp), even though
        calls keep going unanswered -- don't suggest giving up on them."""
        t = _tenant(db)
        stages = _stages(db, t.id)
        g, inq = _guest_and_inquiry(db, t.id, stages["active"])
        for i in range(3):
            _call(db, t.id, g.id, ivr_dial_status="no-answer", minutes_ago=60 - i * 10)
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
        db.add(conv); db.flush()
        db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id,
                       direction=MessageDirection.INBOUND, channel=ChannelType.WHATSAPP.value,
                       body="Sorry, been busy, can we talk tomorrow?", created_at=NOW - timedelta(minutes=15)))
        db.commit()

        assert get_lead_recommendation(db, t.id, inq) is None

    def test_an_answered_call_breaks_the_streak(self, db):
        t = _tenant(db)
        stages = _stages(db, t.id)
        g, inq = _guest_and_inquiry(db, t.id, stages["active"])
        _call(db, t.id, g.id, ivr_dial_status="completed", duration_seconds=120, minutes_ago=5)
        _call(db, t.id, g.id, ivr_dial_status="no-answer", minutes_ago=15)
        _call(db, t.id, g.id, ivr_dial_status="no-answer", minutes_ago=25)
        _call(db, t.id, g.id, ivr_dial_status="no-answer", minutes_ago=35)
        db.commit()

        # Newest call answered -> streak counting stops immediately at 0.
        assert get_lead_recommendation(db, t.id, inq) is None

    def test_inbound_calls_never_count_toward_the_streak(self, db):
        t = _tenant(db)
        stages = _stages(db, t.id)
        g, inq = _guest_and_inquiry(db, t.id, stages["active"])
        for i in range(3):
            _call(db, t.id, g.id, direction=CallDirection.INBOUND, duration_seconds=0, minutes_ago=10 + i * 5)
        db.commit()

        assert get_lead_recommendation(db, t.id, inq) is None


class TestMoveForwardSuggestion:
    def test_suggests_moving_one_step_forward_on_booking_intent(self, db):
        t = _tenant(db)
        stages = _stages(db, t.id)
        g, inq = _guest_and_inquiry(db, t.id, stages["active"])
        _call(db, t.id, g.id, direction=CallDirection.INBOUND, duration_seconds=180, decision_stage="ready_to_book")
        db.commit()

        rec = get_lead_recommendation(db, t.id, inq)
        assert rec is not None
        assert rec["action_config"]["new_stage_id"] == stages["quoted"].id   # one step, not straight to Sold

    def test_never_suggests_a_terminal_stage_as_the_forward_move(self, db):
        """Marking Sold outright needs more than a heuristic read on one
        call summary -- that step stays a manual Kanban drag."""
        t = _tenant(db)
        stages = _stages(db, t.id)
        g, inq = _guest_and_inquiry(db, t.id, stages["quoted"])
        _call(db, t.id, g.id, direction=CallDirection.INBOUND, duration_seconds=180, decision_stage="ready_to_book")
        db.commit()

        rec = get_lead_recommendation(db, t.id, inq)
        target_id = rec["action_config"]["new_stage_id"] if rec else None
        assert target_id != stages["sold"].id
        assert target_id is None or target_id not in (stages["sold"].id, stages["lost"].id)

    def test_no_suggestion_without_a_booking_intent_signal(self, db):
        t = _tenant(db)
        stages = _stages(db, t.id)
        g, inq = _guest_and_inquiry(db, t.id, stages["active"])
        _call(db, t.id, g.id, direction=CallDirection.INBOUND, duration_seconds=90, decision_stage="comparing")
        db.commit()

        assert get_lead_recommendation(db, t.id, inq) is None


class TestApplyingReusesTheExistingAuditedMoveStageAction:
    def test_the_suggested_action_type_is_one_click_executable(self):
        from app.api.v1.endpoints.automations import ONE_CLICK_ACTIONS
        assert "move_stage" in ONE_CLICK_ACTIONS
