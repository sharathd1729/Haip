"""Autonomous-send audit rows.

Before this, drafts the AI sent by itself wrote no outcome row at all --
so precisely the messages with no human oversight were the ones missing
from the trust scorecard.
"""
import uuid

from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.conversation import Conversation, Message, ChannelType
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.services import ai_draft_outcomes_service as svc


def _setup(db):
    t = Tenant(name="AO", slug=f"ao-{uuid.uuid4().hex[:8]}")
    db.add(t); db.flush()
    g = Guest(tenant_id=t.id, name="Arjun")
    db.add(g); db.flush()
    c = Conversation(tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(c); db.commit()
    return t, c


def _draft(db, t, c, *, autonomous, intent="faq_answer", body="Check-in is at 2 PM."):
    m = Message(
        tenant_id=t.id, conversation_id=c.id, direction="outbound",
        channel=ChannelType.WHATSAPP, body=body, is_ai_generated=True,
        ai_confidence="0.91", sent_autonomously=autonomous, ai_intent=intent,
        was_approved=True if autonomous else None,
    )
    db.add(m); db.commit()
    return m


def test_autonomous_send_records_an_outcome_row(db):
    t, c = _setup(db)
    m = _draft(db, t, c, autonomous=True)
    svc.record_outcome(db, tenant_id=t.id, draft=m, outcome="sent_autonomous",
                       actor_user_id=None, intent=m.ai_intent)
    db.commit()

    row = db.query(AIDraftOutcome).filter_by(draft_message_id=m.id).one()
    assert row.outcome == "sent_autonomous"
    # Nobody reviewed it, by definition.
    assert row.actor_user_id is None
    assert row.ai_confidence == "0.91"


def test_intent_is_persisted_on_the_outcome(db):
    """ai_draft_outcomes.intent existed since migration 058 and no caller
    ever populated it, so per-intent accuracy could not be computed."""
    t, c = _setup(db)
    m = _draft(db, t, c, autonomous=True, intent="price_quote")
    svc.record_outcome(db, tenant_id=t.id, draft=m, outcome="sent_autonomous", intent=m.ai_intent)
    db.commit()
    assert db.query(AIDraftOutcome).filter_by(draft_message_id=m.id).one().intent == "price_quote"


def test_human_reviewed_outcomes_also_carry_intent(db):
    t, c = _setup(db)
    m = _draft(db, t, c, autonomous=False, intent="availability_check")
    svc.record_outcome(db, tenant_id=t.id, draft=m, outcome="sent_verbatim",
                       actor_user_id=None, intent=m.ai_intent)
    db.commit()
    assert db.query(AIDraftOutcome).filter_by(draft_message_id=m.id).one().intent == "availability_check"


def test_autonomous_outcome_excluded_from_human_review_set(db):
    """The dilution bug this guards: verbatim/reject rates divide by every
    outcome, so autonomous rows would sit in the denominator and never the
    numerator -- dragging both rates down the more the AI was trusted."""
    t, c = _setup(db)
    for _ in range(3):
        m = _draft(db, t, c, autonomous=False)
        svc.record_outcome(db, tenant_id=t.id, draft=m, outcome="sent_verbatim", intent="faq_answer")
    for _ in range(7):
        m = _draft(db, t, c, autonomous=True)
        svc.record_outcome(db, tenant_id=t.id, draft=m, outcome="sent_autonomous", intent="faq_answer")
    db.commit()

    rows = db.query(AIDraftOutcome).filter_by(tenant_id=t.id).all()
    human = [r for r in rows if r.outcome in svc.HUMAN_REVIEWED_OUTCOMES]
    assert len(rows) == 10
    assert len(human) == 3
    # Scoped to human review the rate is 100%; over all rows it would read 30%.
    verbatim = [r for r in human if r.outcome == "sent_verbatim"]
    assert round(100.0 * len(verbatim) / len(human)) == 100


def test_edit_distance_not_computed_for_autonomous(db):
    t, c = _setup(db)
    m = _draft(db, t, c, autonomous=True)
    svc.record_outcome(db, tenant_id=t.id, draft=m, outcome="sent_autonomous", intent="faq_answer")
    db.commit()
    assert db.query(AIDraftOutcome).filter_by(draft_message_id=m.id).one().edit_distance_pct is None
