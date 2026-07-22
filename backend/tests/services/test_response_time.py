"""
Response time computed on read (Leads360 UI rework):
leads_service._batch_response_time() — waiting / responded / tenant
isolation, plus the multi-conversation urgency rule (waiting beats
responded, longest wait wins). Also the v2 summary-response parser.
"""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.conversation import Conversation, Message, MessageDirection, ChannelType
from app.services.leads_service import _batch_response_time


def _mk_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _mk_inquiry(db, tenant_id):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, phone=f"+91{uuid.uuid4().int % 10**10}")
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, source=InquirySource.WA_DIRECT)
    db.add(inq)
    db.flush()
    return inq


def _mk_conversation(db, tenant_id, inquiry, channel=ChannelType.WHATSAPP):
    c = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=inquiry.guest_id,
        inquiry_id=inquiry.id, channel=channel,
    )
    db.add(c)
    db.flush()
    return c


def _mk_message(db, tenant_id, conv, direction, at):
    m = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
        direction=direction, channel=conv.channel, body="hi",
    )
    db.add(m)
    db.flush()
    m.created_at = at
    db.flush()
    return m


NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc)


def test_waiting_when_latest_inbound_unanswered(db):
    t = _mk_tenant(db)
    inq = _mk_inquiry(db, t.id)
    conv = _mk_conversation(db, t.id, inq)
    _mk_message(db, t.id, conv, MessageDirection.INBOUND, NOW - timedelta(minutes=30))
    db.commit()

    result = _batch_response_time(db, t.id, [inq.id], now=NOW)
    seconds, status = result[inq.id]
    assert status == "waiting"
    assert seconds == 30 * 60


def test_responded_measures_inbound_to_reply_gap(db):
    t = _mk_tenant(db)
    inq = _mk_inquiry(db, t.id)
    conv = _mk_conversation(db, t.id, inq)
    _mk_message(db, t.id, conv, MessageDirection.INBOUND, NOW - timedelta(minutes=20))
    _mk_message(db, t.id, conv, MessageDirection.OUTBOUND, NOW - timedelta(minutes=15))
    db.commit()

    result = _batch_response_time(db, t.id, [inq.id], now=NOW)
    seconds, status = result[inq.id]
    assert status == "responded"
    assert seconds == 5 * 60


def test_waiting_conversation_outranks_responded_one(db):
    """A guest with WhatsApp already answered but Instagram still waiting
    reports the Instagram wait — waiting beats responded."""
    t = _mk_tenant(db)
    inq = _mk_inquiry(db, t.id)
    wa = _mk_conversation(db, t.id, inq, ChannelType.WHATSAPP)
    _mk_message(db, t.id, wa, MessageDirection.INBOUND, NOW - timedelta(hours=2))
    _mk_message(db, t.id, wa, MessageDirection.OUTBOUND, NOW - timedelta(hours=1, minutes=58))
    ig = _mk_conversation(db, t.id, inq, ChannelType.INSTAGRAM)
    _mk_message(db, t.id, ig, MessageDirection.INBOUND, NOW - timedelta(minutes=10))
    db.commit()

    seconds, status = _batch_response_time(db, t.id, [inq.id], now=NOW)[inq.id]
    assert status == "waiting"
    assert seconds == 10 * 60


def test_no_messages_absent_from_result(db):
    t = _mk_tenant(db)
    inq = _mk_inquiry(db, t.id)
    db.commit()
    assert inq.id not in _batch_response_time(db, t.id, [inq.id], now=NOW)


def test_tenant_isolation(db):
    t1 = _mk_tenant(db)
    t2 = _mk_tenant(db)
    inq1 = _mk_inquiry(db, t1.id)
    conv1 = _mk_conversation(db, t1.id, inq1)
    _mk_message(db, t1.id, conv1, MessageDirection.INBOUND, NOW - timedelta(minutes=5))
    db.commit()

    # Tenant 2 querying tenant 1's inquiry id gets nothing
    assert _batch_response_time(db, t2.id, [inq1.id], now=NOW) == {}
    # Tenant 1 sees its own
    assert inq1.id in _batch_response_time(db, t1.id, [inq1.id], now=NOW)


# ── v2 summary response parser ───────────────────────────────────────────────

def test_parse_summary_valid_json():
    from app.workers.tasks.generate_ai_summary import _parse_summary_response
    raw = (
        '{"summary": "Guest wants a villa. Budget unclear. Call them.",'
        ' "analysis": {"intent": "villa stay", "sentiment": "positive",'
        ' "objection": null, "reply_urgency": "high", "next_action": "Call back"}}'
    )
    summary, analysis = _parse_summary_response(raw)
    assert summary.startswith("Guest wants a villa")
    assert analysis["sentiment"] == "positive"
    assert analysis["objection"] is None
    assert set(analysis.keys()) == {"intent", "sentiment", "objection", "reply_urgency", "next_action"}


def test_parse_summary_markdown_fenced():
    from app.workers.tasks.generate_ai_summary import _parse_summary_response
    raw = '```json\n{"summary": "S1. S2. S3.", "analysis": {"intent": "x", "sentiment": "neutral", "objection": null, "reply_urgency": "low", "next_action": "y"}}\n```'
    summary, analysis = _parse_summary_response(raw)
    assert summary == "S1. S2. S3."
    assert analysis["reply_urgency"] == "low"


def test_parse_summary_prose_fallback():
    from app.workers.tasks.generate_ai_summary import _parse_summary_response
    raw = "Guest wants a caravan trip. No budget stated. Send quote."
    summary, analysis = _parse_summary_response(raw)
    assert summary == raw
    assert analysis is None
