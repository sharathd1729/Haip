"""Send package (package_share_service). Pinned: only published retail packages (a b2b package is never listed or sent); no
price in handoff mode, "From ₹X + GST" in grounded mode; the bio-page link only when the workspace has a live site; window
open = plain text (a person's contact), once per lead + package + day; window closed + no approved template = refused with the
reason and the text to copy; never into a personal-bridge thread; conversations.send; another workspace's lead is 404."""
import uuid
from datetime import datetime, timedelta, timezone

from app.core.security import create_access_token
from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.user import User, UserRole
from app.services import agent_bench
from tests.conftest import seed_capabilities


def _world(db):
    w = agent_bench.build_world(db, playbook=False)
    seed_capabilities(db, w.tenant.id)
    return w


def _h(user):
    role = getattr(user.role, "value", user.role)
    return {"Authorization": f"Bearer {create_access_token({'sub': user.id, 'tenant_id': user.tenant_id, 'role': role})}"}


def _lead(db, tid, *, inbound_ago=None, bridge=False):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Kiran Rao", phone=f"+9198450{uuid.uuid4().int % 100000:05d}")
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, stage=InquiryStage.NEW, source=InquirySource.WA_DIRECT)
    db.add(inq)
    if inbound_ago is not None:
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, inquiry_id=inq.id, channel=ChannelType.WHATSAPP,
                            source="personal_bridge" if bridge else None, last_message_at=datetime.now(timezone.utc).isoformat())
        db.add(conv)
        db.flush()
        db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                       channel=ChannelType.WHATSAPP, body="Hi, which trips do you have?", created_at=datetime.now(timezone.utc) - inbound_ago))
    db.commit()
    return g, inq


def _url(inq):
    return f"/api/v1/leads/{inq.id}/package-share"


def test_options_list_published_retail_packages_without_prices_in_handoff_mode(client, db):
    w = _world(db)
    _, inq = _lead(db, w.tenant.id, inbound_ago=timedelta(hours=1))
    res = client.get(_url(inq), headers=_h(w.owner))
    assert res.status_code == 200, res.text
    body = res.json()
    keys = [p["key"] for p in body["packages"]]
    assert "mysuru-coorg" in keys and "rathaa-base-b2b" not in keys
    coorg = next(p for p in body["packages"] if p["key"] == "mysuru-coorg")
    assert coorg["price"] is None and "₹" not in coorg["text"] and "Day 1:" in coorg["text"] and coorg["link"] is None
    assert coorg["text"].startswith("Hi Kiran, here is Mysuru and Coorg")
    assert body["window_open"] is True and body["template_approved"] is False


def test_grounded_mode_shows_the_from_price(client, db):
    w = _world(db)
    w.tenant.brand_config = {**(w.tenant.brand_config or {}), "price_disclosure": "grounded"}
    _, inq = _lead(db, w.tenant.id, inbound_ago=timedelta(hours=1))
    coorg = next(p for p in client.get(_url(inq), headers=_h(w.owner)).json()["packages"] if p["key"] == "mysuru-coorg")
    assert coorg["price"] == "From ₹65,000 + GST" and "From ₹65,000 + GST" in coorg["text"]


def test_window_open_sends_text_once_per_day_and_b2b_is_refused(client, db, monkeypatch):
    sent = []
    monkeypatch.setattr("app.workers.tasks.send_whatsapp.send_whatsapp.delay", lambda **kw: sent.append(kw))
    w = _world(db)
    _, inq = _lead(db, w.tenant.id, inbound_ago=timedelta(hours=2))
    res = client.post(_url(inq), headers=_h(w.owner), json={"package_key": "mysuru-coorg"})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "queued" and res.json()["how"] == "text" and len(sent) == 1
    msg = db.query(Message).filter_by(id=res.json()["message_id"]).one()
    assert msg.sender_kind == "human" and msg.sender_id == w.owner.id and msg.is_ai_generated is not True
    assert msg.idempotency_key.startswith(f"pkg:{inq.id}:")
    again = client.post(_url(inq), headers=_h(w.owner), json={"package_key": "mysuru-coorg"})
    assert again.json()["status"] == "duplicate" and len(sent) == 1
    assert db.query(AuditEvent).filter_by(tenant_id=w.tenant.id, action="lead.package_shared").count() == 1
    b2b = client.post(_url(inq), headers=_h(w.owner), json={"package_key": "rathaa-base-b2b"})
    assert b2b.status_code == 422 and b2b.json()["detail"]["code"] == "package_not_available"


def test_window_closed_without_an_approved_template_is_refused_with_text_to_copy(client, db, monkeypatch):
    monkeypatch.setattr("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay", lambda **kw: (_ for _ in ()).throw(AssertionError("sent")))
    w = _world(db)
    _, inq = _lead(db, w.tenant.id, inbound_ago=timedelta(days=3))
    res = client.post(_url(inq), headers=_h(w.owner), json={"package_key": "mysuru-coorg"})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "template_not_approved"
    assert "Mysuru and Coorg" in res.json()["detail"]["text"]
    _, bridged = _lead(db, w.tenant.id, inbound_ago=timedelta(hours=1), bridge=True)
    r2 = client.post(_url(bridged), headers=_h(w.owner), json={"package_key": "mysuru-coorg"})
    assert r2.status_code == 409 and r2.json()["detail"]["code"] == "personal_bridge"      # never into a bridge thread
    assert db.query(Message).filter(Message.idempotency_key.like("pkg:%")).count() == 0


def test_permission_and_tenant_isolation(client, db):
    w = _world(db)
    other = _world(db)
    _, inq = _lead(db, w.tenant.id, inbound_ago=timedelta(hours=1))
    ro = User(id=str(uuid.uuid4()), tenant_id=w.tenant.id, name="RO", email=f"ro-{uuid.uuid4().hex[:6]}@t.test",
              hashed_password="x", role=UserRole.READ_ONLY, is_active=True)
    db.add(ro)
    db.commit()
    assert client.post(_url(inq), headers=_h(ro), json={"package_key": "mysuru-coorg"}).status_code == 403
    assert client.get(_url(inq), headers=_h(other.owner)).status_code == 404
    assert client.post(_url(inq), headers=_h(other.owner), json={"package_key": "mysuru-coorg"}).status_code == 404
