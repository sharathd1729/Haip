"""WhatsApp step 4: drips that stop when the guest replies, the lead.created webhook (Google Sheets / Zapier), the
Apps Script redirect counted as delivered, and inbox analytics."""
import uuid
from datetime import UTC, datetime, timedelta

from app.core.security import create_access_token
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.webhook import WebhookDelivery
from app.services import flow_engine, wa_costs, wa_inbox_analytics, webhook_service


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _role_headers(db, tenant_id, role):
    user = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Meera", email=f"u-{uuid.uuid4().hex[:6]}@t.com",
                hashed_password="x", role=role, is_active=True)
    db.add(user)
    db.commit()
    return user, {"Authorization": "Bearer " + create_access_token({"sub": user.id, "tenant_id": tenant_id, "role": role.value})}


def _chat(db, tid):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Ananya Rao", phone="+919886140372")
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(c)
    db.commit()
    return g, c


def _msg(db, c, direction, minutes_ago, **kw):
    db.add(Message(id=str(uuid.uuid4()), tenant_id=c.tenant_id, conversation_id=c.id, direction=direction,
                   channel=ChannelType.WHATSAPP, body="x", created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago), **kw))
    db.commit()


# ─── drips ───────────────────────────────────────────────────────────────────

def test_not_replied_keeps_a_drip_going_until_the_guest_answers(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g, c = _chat(db, tid)
    node = {"type": "condition", "condition": "not_replied"}
    _msg(db, c, "outbound", 60)
    assert flow_engine._evaluate_condition(db, tid, g.id, None, node) is True      # finds the guest's chat itself
    _msg(db, c, "inbound", 30)
    assert flow_engine._evaluate_condition(db, tid, g.id, None, node) is False
    assert flow_engine._evaluate_condition(db, tid, g.id, c.id, node) is False


# ─── lead.created webhook ────────────────────────────────────────────────────

def _endpoint(db, tid, events, url="https://hooks.example.com/x"):
    from app.core.encryption import encrypt_credentials
    from app.models.webhook import WebhookEndpoint
    ep = WebhookEndpoint(id=str(uuid.uuid4()), tenant_id=tid, url=url, events=events, is_active=True,
                         secret_enc=encrypt_credentials({"secret": "whsec_test"}))
    db.add(ep)
    db.commit()
    return ep


def test_a_new_lead_sends_lead_created_once(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _endpoint(db, tid, ["lead.created"])
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Kiran Shetty", phone=None)
    db.add(g)
    db.commit()
    assert db.query(WebhookDelivery).filter_by(tenant_id=tid, event_type="lead.created").count() == 0
    g.phone = "+919845012345"
    g.lead_identified_at = datetime.now(UTC)
    db.commit()
    rows = db.query(WebhookDelivery).filter_by(tenant_id=tid, event_type="lead.created").all()
    assert len(rows) == 1 and rows[0].payload["data"]["phone"] == "+919845012345"
    g.name = "Kiran S."
    db.commit()
    assert db.query(WebhookDelivery).filter_by(tenant_id=tid, event_type="lead.created").count() == 1


def test_another_workspaces_lead_never_reaches_my_endpoint(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _endpoint(db, tid, ["lead.created"])
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.flush()
    db.add(Guest(id=str(uuid.uuid4()), tenant_id=other.id, name="X", phone="+919800000009", lead_identified_at=datetime.now(UTC)))
    db.commit()
    assert db.query(WebhookDelivery).filter_by(tenant_id=tid, event_type="lead.created").count() == 0


def test_google_apps_script_redirect_counts_as_delivered():
    assert webhook_service._delivered("https://script.google.com/macros/s/abc/exec?key=k", 302) is True
    assert webhook_service._delivered("https://evil.example/redirect", 302) is False
    assert webhook_service._delivered("https://hooks.zapier.com/hooks/catch/1/2", 200) is True
    assert "lead.created" in webhook_service.EVENTS


# ─── inbox analytics ─────────────────────────────────────────────────────────

def test_inbox_analytics_counts_people_and_cost(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    agent, _ = _role_headers(db, tid, UserRole.RESERVATIONS)
    g, c = _chat(db, tid)
    _msg(db, c, "inbound", 120)
    _msg(db, c, "outbound", 110, sender_id=agent.id, channel_metadata={})
    _msg(db, c, "outbound", 100, sender_id=agent.id, is_internal=True)        # a note is not a reply
    wa_costs.record(db, tid, {"id": "wamid.z", "pricing": {"category": "marketing", "billable": True}})
    db.commit()
    r = client.get("/api/v1/messaging/inbox-analytics", params={"days": 7}, headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["people"] == [{"user_id": agent.id, "name": "Meera", "conversations": 1, "messages": 1}]
    assert body["cost"]["messages"] == 1 and body["period"]["days"] == 7
    assert client.get("/api/v1/messaging/inbox-analytics", params={"days": 12}, headers=_h(tenant_and_user)).status_code == 422
    _, foh = _role_headers(db, tid, UserRole.FOH)
    assert client.get("/api/v1/messaging/inbox-analytics", headers=foh).status_code == 403


def test_inbox_analytics_stays_in_its_workspace(db, tenant_and_user):
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    user, _ = _role_headers(db, other.id, UserRole.RESERVATIONS)
    _, c = _chat(db, other.id)
    _msg(db, c, "outbound", 10, sender_id=user.id)
    mine = db.query(Tenant).filter_by(id=_tid(tenant_and_user)).first()
    assert wa_inbox_analytics.report(db, mine, 7)["people"] == []
