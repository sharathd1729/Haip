"""Tests for the two new insight_detector.py detectors added alongside
the AI Insights feed reactivation, both consuming this session's Phase 2.5
agent-accountability columns (HAIP_Agent_Analytics_Dashboard_Plan_1.md):

- detect_A4: missed calls never recovered by a callback within 24h
  (calls.recovered_by_call_id, #2.5.3)
- detect_D4: per-agent AI-draft rejection rate spike
  (ai_draft_outcomes.actor_user_id, #2.5.4)

No prior test file exists for insight_detector.py at all -- these
establish first coverage for the module, not an extension of existing
patterns.
"""
import uuid
from datetime import datetime, timezone, timedelta

from app.models.guest import Guest
from app.models.call import Call, CallDirection
from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.conversation import Conversation, Message, ChannelType
from app.models.insight import Insight
from app.services.insight_detector import detect_A4, detect_D4


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_guest(db, tenant_id, phone_suffix="0"):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Insight Guest", phone=f"+91999903{phone_suffix}")
    db.add(guest); db.commit()
    return guest


def _make_call(db, tenant_id, guest_id, direction, duration_seconds, created_at, recovered_by_call_id=None):
    call = Call(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
        ivr_provider="acefone", ivr_call_id=str(uuid.uuid4()),
        direction=direction, from_number="+910000000000", to_number="+910000000001",
        duration_seconds=duration_seconds, recovered_by_call_id=recovered_by_call_id,
    )
    db.add(call)
    db.flush()
    call.created_at = created_at
    db.commit()
    return call


class TestDetectA4MissedCallRecovery:
    def test_flags_missed_call_never_recovered(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id)
        now = datetime.now(timezone.utc)

        _make_call(db, tenant_id, guest.id, CallDirection.INBOUND, 0, now - timedelta(hours=48))

        detect_A4(db, tenant_id)
        db.commit()

        insight = db.query(Insight).filter_by(tenant_id=tenant_id, category_code="A4").first()
        assert insight is not None
        assert insight.is_auto_resolved is False
        assert insight.data_snapshot["count"] == 1

    def test_auto_resolves_once_call_is_recovered(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id)
        now = datetime.now(timezone.utc)

        missed = _make_call(db, tenant_id, guest.id, CallDirection.INBOUND, 0, now - timedelta(hours=48))
        detect_A4(db, tenant_id)
        db.commit()
        assert db.query(Insight).filter_by(tenant_id=tenant_id, category_code="A4", is_auto_resolved=False).count() == 1

        recovery = _make_call(db, tenant_id, guest.id, CallDirection.OUTBOUND, 30, now)
        missed.recovered_by_call_id = recovery.id
        db.commit()

        detect_A4(db, tenant_id)
        db.commit()

        assert db.query(Insight).filter_by(tenant_id=tenant_id, category_code="A4", is_auto_resolved=False).count() == 0

    def test_does_not_flag_missed_call_still_inside_recovery_window(self, db, tenant_and_user):
        """A call missed 1h ago hasn't failed the 24h recovery window yet --
        shouldn't be flagged prematurely."""
        tenant_id = _tenant_id(tenant_and_user)
        guest = _make_guest(db, tenant_id)
        now = datetime.now(timezone.utc)

        _make_call(db, tenant_id, guest.id, CallDirection.INBOUND, 0, now - timedelta(hours=1))

        detect_A4(db, tenant_id)
        db.commit()

        assert db.query(Insight).filter_by(tenant_id=tenant_id, category_code="A4").count() == 0

    def test_tenant_isolation(self, db, tenant_and_user):
        from app.models.tenant import Tenant

        tenant_id = _tenant_id(tenant_and_user)
        other_tenant = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(other_tenant); db.commit()

        other_guest = _make_guest(db, other_tenant.id, phone_suffix="1")
        now = datetime.now(timezone.utc)
        _make_call(db, other_tenant.id, other_guest.id, CallDirection.INBOUND, 0, now - timedelta(hours=48))

        detect_A4(db, tenant_id)
        db.commit()

        assert db.query(Insight).filter_by(tenant_id=tenant_id, category_code="A4").count() == 0


def _make_conversation(db, tenant_id, guest_id):
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.commit()
    return conv


def _make_outcome(db, tenant_id, conv_id, actor_user_id, outcome, created_at):
    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv_id,
        direction="outbound", channel="whatsapp", body="draft", is_ai_generated=True,
    )
    db.add(msg); db.flush()
    row = AIDraftOutcome(
        id=str(uuid.uuid4()), tenant_id=tenant_id, draft_message_id=msg.id,
        outcome=outcome, actor_user_id=actor_user_id,
    )
    db.add(row)
    db.flush()
    row.created_at = created_at
    db.commit()
    return row


class TestDetectD4AgentRejectionRate:
    def test_flags_agent_over_threshold_with_min_sample(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        actor_id = tenant_and_user["user"]["id"] if isinstance(tenant_and_user["user"], dict) else tenant_and_user["user"].id
        guest = _make_guest(db, tenant_id)
        conv = _make_conversation(db, tenant_id, guest.id)
        now = datetime.now(timezone.utc)

        # 3 rejected, 2 sent_verbatim = 60% rejection rate, 5 total (meets min sample)
        for i in range(3):
            _make_outcome(db, tenant_id, conv.id, actor_id, "rejected", now - timedelta(days=1))
        for i in range(2):
            _make_outcome(db, tenant_id, conv.id, actor_id, "sent_verbatim", now - timedelta(days=1))

        detect_D4(db, tenant_id)
        db.commit()

        insight = db.query(Insight).filter_by(tenant_id=tenant_id, category_code="D4", target_id=actor_id).first()
        assert insight is not None
        assert insight.data_snapshot["rejected"] == 3
        assert insight.data_snapshot["total"] == 5

    def test_does_not_flag_below_minimum_sample_size(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        actor_id = tenant_and_user["user"]["id"] if isinstance(tenant_and_user["user"], dict) else tenant_and_user["user"].id
        guest = _make_guest(db, tenant_id)
        conv = _make_conversation(db, tenant_id, guest.id)
        now = datetime.now(timezone.utc)

        # 2 rejected, 0 sent -- 100% rejection but only 2 samples, below min of 5
        for i in range(2):
            _make_outcome(db, tenant_id, conv.id, actor_id, "rejected", now - timedelta(days=1))

        detect_D4(db, tenant_id)
        db.commit()

        assert db.query(Insight).filter_by(tenant_id=tenant_id, category_code="D4").count() == 0

    def test_auto_resolves_once_rate_improves(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        actor_id = tenant_and_user["user"]["id"] if isinstance(tenant_and_user["user"], dict) else tenant_and_user["user"].id
        guest = _make_guest(db, tenant_id)
        conv = _make_conversation(db, tenant_id, guest.id)
        now = datetime.now(timezone.utc)

        for i in range(3):
            _make_outcome(db, tenant_id, conv.id, actor_id, "rejected", now - timedelta(days=1))
        for i in range(2):
            _make_outcome(db, tenant_id, conv.id, actor_id, "sent_verbatim", now - timedelta(days=1))
        detect_D4(db, tenant_id)
        db.commit()
        assert db.query(Insight).filter_by(tenant_id=tenant_id, category_code="D4", target_id=actor_id, is_auto_resolved=False).count() == 1

        # Agent improves: add many more accepted drafts, dropping the ratio well under 40%
        for i in range(10):
            _make_outcome(db, tenant_id, conv.id, actor_id, "sent_verbatim", now - timedelta(hours=1))

        detect_D4(db, tenant_id)
        db.commit()

        assert db.query(Insight).filter_by(tenant_id=tenant_id, category_code="D4", target_id=actor_id, is_auto_resolved=False).count() == 0

    def test_tenant_isolation(self, db, tenant_and_user):
        from app.models.tenant import Tenant
        from app.models.user import User, UserRole
        from app.core.security import get_password_hash

        tenant_id = _tenant_id(tenant_and_user)
        other_tenant = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
        db.add(other_tenant); db.flush()
        other_user = User(
            id=str(uuid.uuid4()), tenant_id=other_tenant.id, name="Other Agent",
            email=f"o-{uuid.uuid4().hex[:6]}@test.com", hashed_password=get_password_hash("pw"),
            role=UserRole.CONCIERGE, is_active=True,
        )
        db.add(other_user); db.commit()

        other_guest = _make_guest(db, other_tenant.id, phone_suffix="2")
        other_conv = _make_conversation(db, other_tenant.id, other_guest.id)
        now = datetime.now(timezone.utc)
        for i in range(5):
            _make_outcome(db, other_tenant.id, other_conv.id, other_user.id, "rejected", now - timedelta(days=1))

        detect_D4(db, tenant_id)
        db.commit()

        assert db.query(Insight).filter_by(tenant_id=tenant_id, category_code="D4").count() == 0
