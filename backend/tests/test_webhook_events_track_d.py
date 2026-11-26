"""SMS9 parity Track D: the new outbound webhook events -- message.sent, conversation.closed, lead.stage_changed (both
stage paths) and task.due. Each fires once, with a minimal payload, only to the right workspace."""
import uuid
from datetime import UTC, datetime, timedelta

from app.core.encryption import encrypt_credentials
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.pipeline_stage import PipelineStage
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.webhook import WebhookDelivery, WebhookEndpoint
from app.services import inquiry_service, webhook_service


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _endpoint(db, tid, events):
    ep = WebhookEndpoint(id=str(uuid.uuid4()), tenant_id=tid, url="https://hooks.example.com/x", events=events,
                         is_active=True, secret_enc=encrypt_credentials({"secret": "whsec_test"}))
    db.add(ep)
    db.commit()
    return ep


def _rows(db, tid, event_type):
    return db.query(WebhookDelivery).filter_by(tenant_id=tid, event_type=event_type).all()


def _chat(db, tid):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Ananya Rao", phone="+919886140372")
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(c)
    db.commit()
    return g, c


def _out(db, c, state, **kw):
    m = Message(id=str(uuid.uuid4()), tenant_id=c.tenant_id, conversation_id=c.id, direction=MessageDirection.OUTBOUND,
                channel=ChannelType.WHATSAPP, body="Your caravan is confirmed", delivery_state=state, **kw)
    db.add(m)
    db.commit()
    return m


# ─── message.sent ────────────────────────────────────────────────────────────

def test_message_sent_fires_once_when_the_message_leaves(db):
    t = _tenant(db)
    _endpoint(db, t.id, ["message.sent"])
    _g, c = _chat(db, t.id)
    m = _out(db, c, MessageDeliveryState.QUEUED, sender_kind="human", sender_name="Meera")
    assert _rows(db, t.id, "message.sent") == []
    m.delivery_state = MessageDeliveryState.SENT
    db.commit()
    m.delivery_state = MessageDeliveryState.DELIVERED
    db.commit()
    m.delivery_state = MessageDeliveryState.READ
    db.commit()
    rows = _rows(db, t.id, "message.sent")
    assert len(rows) == 1
    data = rows[0].payload["data"]
    assert data["id"] == m.id and data["text"] == "Your caravan is confirmed"
    assert data["sender_kind"] == "human" and data["sender_name"] == "Meera"


def test_message_sent_for_ai_and_mirrored_replies_but_not_drafts_or_history(db):
    t = _tenant(db)
    _endpoint(db, t.id, ["message.sent"])
    _g, c = _chat(db, t.id)
    draft = _out(db, c, None, is_ai_generated=True)                                   # an AI draft waiting for a person
    _out(db, c, MessageDeliveryState.SENT, sender_kind="bridge_history")             # old mirrored history
    live = _out(db, c, MessageDeliveryState.SENT, sender_kind="bridge_live")         # agent replied from their phone
    assert [r.payload["data"]["id"] for r in _rows(db, t.id, "message.sent")] == [live.id]
    loaded = db.get(Message, draft.id)
    loaded.delivery_state = MessageDeliveryState.QUEUED
    db.flush()
    loaded.delivery_state = MessageDeliveryState.SENT                                  # old value known: queued
    loaded.sent_autonomously = True
    db.commit()
    rows = _rows(db, t.id, "message.sent")
    assert len(rows) == 2 and rows[-1].payload["data"]["sender_kind"] == "ai_auto"


def test_failed_messages_and_internal_notes_never_send_message_sent(db):
    t = _tenant(db)
    _endpoint(db, t.id, ["message.sent"])
    _g, c = _chat(db, t.id)
    m = _out(db, c, MessageDeliveryState.QUEUED)
    m.delivery_state = MessageDeliveryState.FAILED
    db.commit()
    _out(db, c, MessageDeliveryState.SENT, is_internal=True)
    assert _rows(db, t.id, "message.sent") == []


# ─── conversation.closed ────────────────────────────────────────────────────

def test_conversation_closed_fires_once(db):
    t = _tenant(db)
    _endpoint(db, t.id, ["conversation.closed"])
    g, c = _chat(db, t.id)
    c.is_open = False
    db.commit()
    c.is_open = False
    db.commit()
    rows = _rows(db, t.id, "conversation.closed")
    assert len(rows) == 1
    data = rows[0].payload["data"]
    assert data["id"] == c.id and data["channel"] == "whatsapp" and data["guest"]["id"] == g.id
    c.is_open = True
    db.commit()
    assert len(_rows(db, t.id, "conversation.closed")) == 1


def test_another_workspace_closing_a_chat_never_reaches_my_endpoint(db):
    t, other = _tenant(db), _tenant(db)
    _endpoint(db, t.id, ["conversation.closed"])
    _g, c = _chat(db, other.id)
    c.is_open = False
    db.commit()
    assert _rows(db, t.id, "conversation.closed") == [] and _rows(db, other.id, "conversation.closed") == []


# ─── lead.stage_changed (both paths) ────────────────────────────────────────

def _actor(db, tid):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name="Meera", email=f"m-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password="x", role=UserRole.OWNER, is_active=True)
    db.add(u)
    db.flush()
    return u


def _inquiry(db, tid):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Kiran Shetty", phone="")
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, stage=InquiryStage.NEW, source=InquirySource.META_IG)
    db.add(inq)
    db.flush()
    return g, inq


def test_lead_stage_changed_on_the_legacy_path(db):
    t = _tenant(db)
    _endpoint(db, t.id, ["lead.stage_changed"])
    g, inq = _inquiry(db, t.id)
    inquiry_service.update_stage(db, tenant_id=t.id, inquiry_id=inq.id, new_stage=InquiryStage.RESPONDING,
                                 actor_user_id=_actor(db, t.id).id, actor_role="owner")
    db.commit()
    rows = _rows(db, t.id, "lead.stage_changed")
    assert len(rows) == 1
    data = rows[0].payload["data"]
    assert data["id"] == inq.id and data["guest"] == {"id": g.id, "name": "Kiran Shetty"}
    assert data["from_stage"] == "new" and data["to_stage"] == "responding"
    assert "phone" not in str(data)


def test_lead_stage_changed_on_the_stage_id_path(db):
    t = _tenant(db)
    _endpoint(db, t.id, ["lead.stage_changed"])
    _g, inq = _inquiry(db, t.id)

    def stage(key, label, order, **flags):
        s = PipelineStage(id=str(uuid.uuid4()), tenant_id=t.id, key=key, label=label, color="#000000", order=order,
                          category=flags.pop("category", "valid"), **flags)
        db.add(s)
        db.flush()
        return s

    start = stage("general_enquiry", "General Enquiry", 0, category="invalid", is_default_entry=True)
    active = stage("active", "Active", 1, is_valid_lead_entry=True)
    inq.stage_id = start.id
    db.commit()
    inquiry_service.update_stage_by_id(db, tenant_id=t.id, inquiry_id=inq.id, new_stage_id=active.id,
                                       actor_user_id=_actor(db, t.id).id, actor_role="owner")
    db.commit()
    rows = _rows(db, t.id, "lead.stage_changed")
    assert len(rows) == 1
    data = rows[0].payload["data"]
    assert (data["from_stage"], data["to_stage"], data["to_stage_label"]) == ("general_enquiry", "active", "Active")


# ─── task.due ───────────────────────────────────────────────────────────────

def _task(db, tid, due, **kw):
    task = Task(id=str(uuid.uuid4()), tenant_id=tid, title="Call back Ananya about the Goa trip", due_date=due,
                priority="high", **kw)
    db.add(task)
    db.commit()
    return task


def test_task_due_fires_once_per_due_time(db):
    t = _tenant(db)
    _endpoint(db, t.id, ["task.due"])
    now = datetime.now(UTC)
    task = _task(db, t.id, now - timedelta(minutes=2), kind="followup")
    _task(db, t.id, now + timedelta(hours=2))                                   # not due yet
    _task(db, t.id, now - timedelta(days=2))                                    # long overdue: not news
    _task(db, t.id, now - timedelta(minutes=5), is_done=True)                  # already done
    assert len(webhook_service.queue_due_tasks(db, t.id, now)) == 1
    db.commit()
    assert webhook_service.queue_due_tasks(db, t.id, now + timedelta(minutes=1)) == []
    rows = _rows(db, t.id, "task.due")
    assert len(rows) == 1
    data = rows[0].payload["data"]
    assert data["id"] == task.id and data["kind"] == "followup" and data["priority"] == "high"
    task.due_date = now + timedelta(minutes=1)                                  # rescheduled: fires again when due
    db.commit()
    assert len(webhook_service.queue_due_tasks(db, t.id, now + timedelta(minutes=3))) == 1


def test_task_due_needs_a_subscriber_and_stays_in_its_workspace(db):
    t, other = _tenant(db), _tenant(db)
    _endpoint(db, t.id, ["lead.created"])
    _endpoint(db, other.id, ["task.due"])
    now = datetime.now(UTC)
    _task(db, t.id, now - timedelta(minutes=1))
    assert webhook_service.queue_due_tasks(db, t.id, now) == []
    assert webhook_service.queue_due_tasks(db, other.id, now) == []


def test_new_events_are_listed_for_the_event_picker():
    for e in ("message.sent", "conversation.closed", "lead.stage_changed", "task.due"):
        assert webhook_service.EVENTS[e]
