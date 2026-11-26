"""WhatsApp flow canvas (docs/whatsapp/FLOW_CANVAS_SPEC.md): the new steps, waiting for the guest's reply, the keyword
trigger, the file upload and the save-time checks."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.api.v1.endpoints.messaging import WAFlow
from app.core.security import create_access_token
from app.models.automation import AutomationRule
from app.models.conversation import ChannelType, Conversation, Message
from app.models.flow_execution import FlowPendingExecution, WAFlowRun
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import flow_nodes
from app.services.flow_engine import run_flow

PHONE = "+919886140372"


@pytest.fixture
def queued(monkeypatch):
    out = []
    monkeypatch.setattr("app.workers.tasks.send_whatsapp.send_whatsapp.delay", lambda **kw: out.append(kw))
    return out


@pytest.fixture
def no_ai(monkeypatch):
    monkeypatch.setattr("app.workers.tasks.concierge_draft.concierge_draft.apply_async",
                        lambda *a, **k: pytest.fail("the AI must not answer a message a flow took"))


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="Jade", slug=f"j-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _world(db):
    """A tenant, a guest and their WhatsApp chat with a guest message a minute ago (window open)."""
    t = _tenant(db)
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Ananya Rao", phone=PHONE)
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add_all([g, c])
    db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction="inbound",
                   channel=ChannelType.WHATSAPP, body="Hi", created_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    db.commit()
    return t, g, c


def _flow(db, tenant_id, steps, edges=None, trigger="new_inquiry", keywords=None, match="exact"):
    """trigger -> steps in a line, unless edges are given."""
    nodes = [{"id": "t", "type": "trigger", "trigger": trigger, "keywords": keywords or [], "match": match}, *steps]
    if edges is None:
        edges = [{"id": f"e{i}", "from": a["id"], "to": b["id"], "label": None} for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]
    f = WAFlow(id=str(uuid.uuid4()), tenant_id=tenant_id, name="F", nodes=nodes, edges=edges, trigger=trigger, is_active=True)
    db.add(f)
    db.commit()
    return f


def _sent(db, tenant_id):
    return db.query(Message).filter_by(tenant_id=tenant_id, direction="outbound").order_by(Message.created_at).all()


def _menu(db, tenant_id, other=False):
    steps = [{"id": "b", "type": "buttons", "content": "Hi {first_name}, what are you planning?",
              "buttons": [{"id": "v", "title": "Villas"}, {"id": "w", "title": "Weddings"}]},
             {"id": "mv", "type": "message", "content": "Our villas"},
             {"id": "mw", "type": "message", "content": "Our wedding lawns"},
             {"id": "mo", "type": "message", "content": "Pick one of the buttons please"}]
    edges = [{"id": "e0", "from": "t", "to": "b"}, {"id": "e1", "from": "b", "to": "mv", "label": "btn:v"},
             {"id": "e2", "from": "b", "to": "mw", "label": "btn:w"}]
    if other:
        edges.append({"id": "e3", "from": "b", "to": "mo", "label": "other"})
    return _flow(db, tenant_id, steps, edges, trigger="keyword", keywords=["hi", "hello"])


def _waiting(db, tenant_id):
    return db.query(FlowPendingExecution).filter_by(tenant_id=tenant_id, status="awaiting_reply").all()


# ── sending steps ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_media_step_sends_the_uploaded_file(db, queued):
    t, g, c = _world(db)
    key = f"{t.id}/wa_flows/abc.pdf"
    f = _flow(db, t.id, [{"id": "m", "type": "media", "media_kind": "document", "file_key": key,
                          "filename": "Jade brochure.pdf", "caption": "For you, {first_name}"}, {"id": "x", "type": "end"}])
    run_flow(db, t.id, f, g.id)
    (msg,) = _sent(db, t.id)
    assert (msg.media_type, msg.media_url, msg.body) == ("document", key, "For you, Ananya")
    assert msg.channel_metadata == {"filename": "Jade brochure.pdf"} and msg.sender_kind == "system"
    assert len(queued) == 1


def test_media_step_never_sends_another_workspaces_file(db, queued):
    t, g, c = _world(db)
    f = _flow(db, t.id, [{"id": "m", "type": "media", "media_kind": "image", "file_key": "other-tenant/wa_flows/x.jpg"}])
    run_flow(db, t.id, f, g.id)
    assert _sent(db, t.id) == [] and not queued
    assert db.query(WAFlowRun).filter_by(flow_id=f.id, node_id="m").one().status == "skipped"


def test_location_step_queues_a_map_pin_and_the_send_task_sends_it(db, queued):
    t, g, c = _world(db)
    f = _flow(db, t.id, [{"id": "l", "type": "location", "latitude": 12.97, "longitude": 77.59,
                          "name": "Jade Villas", "address": "Whitefield, Bengaluru"}])
    run_flow(db, t.id, f, g.id)
    (msg,) = _sent(db, t.id)
    assert msg.media_type == "location" and msg.channel_metadata["location"]["latitude"] == 12.97

    from app.workers.tasks.send_whatsapp import send_whatsapp
    fake = MagicMock()
    fake.query.return_value.filter_by.return_value.first.side_effect = iter(
        [msg, MagicMock(guest_id=g.id), MagicMock(config={"phone_number_id": "p"}), MagicMock(phone=PHONE)])
    calls = []

    async def send_location(**kw):
        calls.append(kw)
        return {"messages": [{"id": "wamid.loc"}]}

    with patch("app.workers.tasks.send_whatsapp.SessionLocal", return_value=fake), \
            patch("app.workers.tasks.send_whatsapp.get_wa_adapter", return_value=MagicMock(send_location=send_location)), \
            patch("app.workers.tasks.whatsapp._get_wa_access_token", return_value="tok"), \
            patch("app.services.ai_draft_expiry.after_send"):
        send_whatsapp.run(message_id=msg.id, tenant_id=t.id)
    assert calls == [{"to": PHONE, "latitude": 12.97, "longitude": 77.59, "name": "Jade Villas", "address": "Whitefield, Bengaluru"}]


def test_adapter_location_payload():
    from app.adapters.whatsapp.meta_cloud import MetaCloudAdapter
    a = MetaCloudAdapter("pnid", "tok")
    with patch.object(MetaCloudAdapter, "_post", side_effect=lambda url, payload: payload):   # an AsyncMock
        out = asyncio.run(a.send_location(PHONE, 12.9, 77.5, name="Jade"))
    assert out["type"] == "location" and out["location"] == {"latitude": 12.9, "longitude": 77.5, "name": "Jade"}


def test_cta_url_and_list_steps_send_interactive_messages(db, queued):
    t, g, c = _world(db)
    f = _flow(db, t.id, [{"id": "c", "type": "cta_url", "content": "Our brochure", "button_label": "Open", "url": "https://jade.example/b"},
                         {"id": "l", "type": "list", "content": "Pick a villa", "button_label": "Villas",
                          "rows": [{"id": "r1", "title": "Pool villa", "description": "Sleeps 6"}, {"id": "r2", "title": "Garden villa"}]}])
    run_flow(db, t.id, f, g.id)
    cta, lst = _sent(db, t.id)
    assert cta.channel_metadata["interactive"] == {"kind": "cta_url", "title": "Open", "url": "https://jade.example/b",
                                                   "buttons": [], "button_ids": [], "sections": []}
    (pending,) = _waiting(db, t.id)
    rows = lst.channel_metadata["interactive"]["sections"][0]["rows"]
    assert [r["id"] for r in rows] == [f"wfl:{pending.id}:r1", f"wfl:{pending.id}:r2"] and rows[0]["description"] == "Sleeps 6"
    assert pending.node_id == "l" and pending.resume_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) + timedelta(hours=23)


def test_http_step_calls_public_https_only(db, queued):
    t, g, c = _world(db)
    f = _flow(db, t.id, [{"id": "h", "type": "http", "method": "POST", "url": "https://hooks.jade.example/lead",
                          "body": '{"name": "{first_name}", "phone": "{phone}"}'},
                         {"id": "h2", "type": "http", "method": "GET", "url": "https://127.0.0.1/admin"},
                         {"id": "m", "type": "message", "content": "Thanks"}])
    public = [(2, 1, 6, "", ("93.184.216.34", 443))]
    with patch("app.core.url_safety.socket.getaddrinfo", side_effect=lambda h, p: public if h != "127.0.0.1" else [(2, 1, 6, "", ("127.0.0.1", 443))]), \
            patch("httpx.Client.request", return_value=MagicMock(status_code=200)) as req:
        run_flow(db, t.id, f, g.id)
    assert req.call_count == 1
    method, url = req.call_args.args
    assert (method, url) == ("POST", "https://hooks.jade.example/lead")
    assert req.call_args.kwargs["content"] == f'{{"name": "Ananya", "phone": "{PHONE}"}}'.encode()
    runs = {r.node_id: r.status for r in db.query(WAFlowRun).filter_by(flow_id=f.id)}
    assert runs == {"h": "success", "h2": "failed", "m": "success"}   # a failed call never stops the flow


def test_add_label_condition_yes_no_and_legacy_content(db, queued):
    t, g, c = _world(db)
    f = _flow(db, t.id, [{"id": "a", "type": "action", "action": "add_label", "content": "add_label", "label": "Step name", "tag": "Wedding"},
                         {"id": "k", "type": "condition", "condition": "has_booking"},
                         {"id": "y", "type": "message", "content": "yes path"}, {"id": "n", "type": "message", "content": "no path"}],
              edges=[{"from": "t", "to": "a"}, {"from": "a", "to": "k"},
                     {"from": "k", "to": "y", "label": "yes"}, {"from": "k", "to": "n", "label": "no"}])
    run_flow(db, t.id, f, g.id)
    db.refresh(g)
    assert g.tags == ["Wedding"] and [m.body for m in _sent(db, t.id)] == ["no path"]


# ── waiting for the guest ────────────────────────────────────────────────────────────────────────────────────────────

def _inbound(db, t, wamid, text=None, reply=None):
    from app.workers.tasks.whatsapp import _handle_inbound_message
    msg = {"id": wamid, "from": PHONE.lstrip("+")}
    if reply:
        msg.update(type="interactive", interactive={"type": "button_reply", "button_reply": reply})
    else:
        msg.update(type="text", text={"body": text})
    _handle_inbound_message(db, t, msg, contacts=[])
    db.commit()
    return db.query(Message).filter_by(tenant_id=t.id, channel_message_id=wamid).one()


def test_keyword_starts_the_flow_and_a_tap_follows_its_branch(db, queued, no_ai):
    t = _tenant(db)
    db.commit()
    _menu(db, t.id)
    db.add(AutomationRule(id=str(uuid.uuid4()), tenant_id=t.id, name="HI", trigger="wa_message_received",
                          action="send_whatsapp_reply", is_active=True, run_count=0,
                          trigger_config={"keywords": ["hi"]}, action_config={"message": "keyword reply"}))
    db.commit()

    first = _inbound(db, t, "wamid.1", text="Hi")
    assert first.automation_outcome == "flow_started"
    (menu,) = _sent(db, t.id)                                     # the flow's menu, not the keyword reply
    assert menu.body.endswith(", what are you planning?")
    (pending,) = _waiting(db, t.id)
    assert menu.channel_metadata["interactive"]["button_ids"] == [f"wfl:{pending.id}:v", f"wfl:{pending.id}:w"]

    tap = _inbound(db, t, "wamid.2", reply={"id": f"wfl:{pending.id}:w", "title": "Weddings"})
    assert tap.automation_outcome == "flow_reply"
    assert [m.body for m in _sent(db, t.id)][-1] == "Our wedding lawns"
    db.refresh(pending)
    assert pending.status == "done" and not _waiting(db, t.id)


def test_typed_title_counts_unmatched_reply_keeps_waiting_or_takes_other(db, queued):
    t, g, c = _world(db)
    f = _menu(db, t.id)
    run_flow(db, t.id, f, g.id)
    assert not flow_nodes.resume_on_reply(db, t.id, g, c, "what are the prices?", None)   # no "other" edge: keep waiting
    assert len(_waiting(db, t.id)) == 1
    assert flow_nodes.resume_on_reply(db, t.id, g, c, "  villas ", None)                    # the title, any case
    assert _sent(db, t.id)[-1].body == "Our villas"

    t2, g2, c2 = _world(db)
    f2 = _menu(db, t2.id, other=True)
    run_flow(db, t2.id, f2, g2.id)
    assert flow_nodes.resume_on_reply(db, t2.id, g2, c2, "what are the prices?", None)
    assert _sent(db, t2.id)[-1].body == "Pick one of the buttons please" and not _waiting(db, t2.id)


def test_question_saves_the_answer_and_moves_on(db, queued):
    t, g, c = _world(db)
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, custom_fields={})
    db.add(inq)
    db.commit()
    f = _flow(db, t.id, [{"id": "q1", "type": "question", "content": "Your name?", "save_as": "name"},
                         {"id": "q2", "type": "question", "content": "Your budget?", "save_as": "custom:budget"},
                         {"id": "q3", "type": "question", "content": "Anything else?", "save_as": "notes"},
                         {"id": "m", "type": "message", "content": "Thanks {first_name}"}])
    run_flow(db, t.id, f, g.id)
    for answer in ("Meera Iyer", "2 lakh", "Need a DJ"):
        assert flow_nodes.resume_on_reply(db, t.id, g, c, answer, None)
    db.refresh(g)
    db.refresh(inq)
    assert g.name == "Meera Iyer" and inq.custom_fields == {"budget": "2 lakh"} and inq.special_requests == "Need a DJ"
    assert _sent(db, t.id)[-1].body == "Thanks Meera"


def test_expired_wait_is_ignored_and_the_beat_expires_it_without_resuming(db, queued):
    t, g, c = _world(db)
    run_flow(db, t.id, _menu(db, t.id), g.id)
    (pending,) = _waiting(db, t.id)
    pending.resume_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert not flow_nodes.resume_on_reply(db, t.id, g, c, "Villas", None)
    from app.workers.tasks import flow_engine as beat
    with patch.object(beat, "SessionLocal", return_value=db), patch.object(db, "close"), \
            patch.object(beat.resume_flow_execution, "delay") as resume:
        beat.drain_pending_executions()
    db.refresh(pending)
    assert pending.status == "expired" and not resume.called


def test_keyword_flow_runs_once_per_message(db, queued):
    t, g, c = _world(db)
    f = _flow(db, t.id, [{"id": "m", "type": "message", "content": "Welcome"}], trigger="keyword",
              keywords=["wedding", "mehndi"], match="contains")
    assert not flow_nodes.start_keyword_flow(db, t.id, g, c, "weddings", "m1")              # whole words only
    assert flow_nodes.start_keyword_flow(db, t.id, g, c, "Mehndi on Friday?", "m1")
    assert flow_nodes.start_keyword_flow(db, t.id, g, c, "Mehndi on Friday?", "m1")
    assert [m.body for m in _sent(db, t.id)] == ["Welcome"] and f.id


def test_another_workspaces_flow_or_wait_never_runs(db, queued):
    t, g, c = _world(db)
    other = _tenant(db)
    f_other = _menu(db, other.id)                                  # a "hi" keyword flow in another workspace
    db.add(FlowPendingExecution(id=str(uuid.uuid4()), tenant_id=other.id, flow_id=f_other.id, node_id="b",
                                guest_id=g.id, context={}, status="awaiting_reply",
                                resume_at=datetime.now(timezone.utc) + timedelta(hours=1)))
    db.commit()
    assert not flow_nodes.resume_on_reply(db, t.id, g, c, "Villas", None)
    assert not flow_nodes.start_keyword_flow(db, t.id, g, c, "hi", "m9")
    assert _sent(db, t.id) == [] and _sent(db, other.id) == []


# ── upload ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _headers(db, tenant_id, role=UserRole.OWNER):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name="U", email=f"u-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password="x", role=role, is_active=True)
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token({'sub': u.id, 'tenant_id': tenant_id, 'role': role.value})}"}


def test_upload_checks_type_size_and_role(client, db):
    t = _tenant(db)
    db.commit()
    h = _headers(db, t.id, UserRole.MANAGER)
    post = lambda name, data, hh=h: client.post("/api/v1/messaging/flows/media", headers=hh, files={"file": (name, data, "x/y")})
    with patch("app.services.media_storage._put") as put, \
            patch("app.services.media_storage.get_presigned_media_url", return_value="https://files.example/p"):
        pdf = post("../Jade brochure.pdf", b"%PDF-1.7 hi")
        mp4 = post("tour.mp4", b"\x00\x00\x00\x18ftypmp42rest")
        exe = post("x.pdf", b"MZ\x90\x00")
        big = post("big.jpg", b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024))
        concierge = post("a.pdf", b"%PDF-1.7", _headers(db, t.id, UserRole.CONCIERGE))
    assert pdf.status_code == 200, pdf.text
    body = pdf.json()
    assert body["kind"] == "document" and body["key"].startswith(f"{t.id}/wa_flows/") and body["key"].endswith(".pdf")
    assert body["filename"] == "Jade brochure.pdf" and body["preview_url"] == "https://files.example/p"
    assert mp4.json()["kind"] == "video"
    assert exe.status_code == 400 and big.status_code == 400 and concierge.status_code == 403
    assert put.call_count == 2


# ── validation on save ───────────────────────────────────────────────────────────────────────────────────────────────

def _payload(*steps, edges=None, keywords=("hi",)):
    nodes = [{"id": "t", "type": "trigger", "trigger": "keyword", "keywords": list(keywords), "match": "exact",
              "position": {"x": 0, "y": 0}}, *steps]
    if edges is None:
        edges = [{"id": f"e{i}", "from": a["id"], "to": b["id"], "label": None} for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]
    return {"name": "Greeting", "nodes": nodes, "edges": edges}


def test_save_validates_and_mirrors_the_trigger(client, db):
    t = _tenant(db)
    db.commit()
    h = _headers(db, t.id)
    ok = client.post("/api/v1/messaging/flows", headers=h, json=_payload(
        {"id": "b", "type": "buttons", "content": "Pick", "buttons": [{"id": "v", "title": "Villas"}]},
        {"id": "m", "type": "media", "media_kind": "document", "file_key": f"{t.id}/wa_flows/a.pdf"}))
    assert ok.status_code == 201, ok.text
    assert ok.json()["trigger"] == "keyword"
    assert client.post("/api/v1/messaging/flows", headers=h, json={"name": "Draft"}).status_code == 201   # empty draft

    bad = {
        "trigger step": {"name": "x", "nodes": [{"id": "a", "type": "message", "content": "hi"}], "edges": []},
        "keyword": _payload(keywords=()),
        "20 characters": _payload({"id": "b", "type": "buttons", "content": "Pick", "buttons": [{"id": "v", "title": "V" * 21}]}),
        "https": _payload({"id": "h", "type": "http", "method": "POST", "url": "http://hooks.example"}),
        "no longer exists": _payload({"id": "m", "type": "message", "content": "x"}, edges=[{"id": "e", "from": "t", "to": "zz"}]),
        "does not belong": _payload({"id": "m", "type": "media", "media_kind": "image", "file_key": "other/wa_flows/a.jpg"}),
        "same id": _payload({"id": "t", "type": "message", "content": "x"}),
        "1 to 10": _payload({"id": "l", "type": "list", "content": "x", "button_label": "Go", "rows": []}),
    }
    for words, payload in bad.items():
        r = client.post("/api/v1/messaging/flows", headers=h, json=payload)
        assert r.status_code == 422 and words in r.json()["detail"], (words, r.text)


def test_save_needs_owner_or_manager_and_stays_in_its_workspace(client, db):
    t, other = _tenant(db), _tenant(db)
    db.commit()
    mine = _flow(db, t.id, [{"id": "m", "type": "message", "content": "x"}])
    assert client.post("/api/v1/messaging/flows", headers=_headers(db, t.id, UserRole.CONCIERGE),
                       json=_payload()).status_code == 403
    r = client.put(f"/api/v1/messaging/flows/{mine.id}", headers=_headers(db, other.id), json=_payload())
    assert r.status_code == 404
