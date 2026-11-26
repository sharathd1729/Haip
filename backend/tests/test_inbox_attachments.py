"""Inbox file attachments (services/inbox_attachments.py, POST /conversations/{id}/attachments) and several files per
WhatsApp keyword reply (services/wa_keyword_replies.py)."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.core.security import create_access_token
from app.models.automation import AutomationRule
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import inbox_attachments, wa_keyword_replies

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

PDF, JPG, PNG = b"%PDF-1.7 x", b"\xff\xd8\xff\xe0x", b"\x89PNG\r\n\x1a\nx"
MP4, M4A = b"\x00\x00\x00\x18ftypisom" + b"x" * 8, b"\x00\x00\x00\x18ftypM4A " + b"x" * 8


def _tid(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _conv(db, tid, channel=ChannelType.WHATSAPP):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Ananya Rao", phone="+919886140372")
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=channel, is_open=True)
    db.add(c)
    db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=c.id, direction="inbound", channel=channel,
                   body="Hi", created_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
    db.commit()
    return c


def _h(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def _upload(client, headers, conv_id, name, content):
    with patch("app.services.media_storage._put") as put, \
            patch("app.services.media_storage.get_presigned_media_url", return_value="https://files.example/p"):
        res = client.post(f"/api/v1/conversations/{conv_id}/attachments", headers=headers,
                          files={"file": (name, content, "application/octet-stream")})
    return res, put


# ── sniffing ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("head,ext", [(PDF, "pdf"), (JPG, "jpg"), (PNG, "png"), (MP4, "mp4"), (M4A, "m4a"),
                                      (b"ID3\x04", "mp3"), (b"OggS\x00", "ogg"), (b"#!AMR\n", "amr"),
                                      (b"MZ\x90\x00", None), (b"GIF89a", None)])
def test_the_type_comes_from_the_first_bytes(head, ext):
    assert inbox_attachments.sniff(head[:16]) == ext


def test_a_key_is_only_ours_when_it_is_this_workspaces_inbox_upload():
    good = f"t1/inbox_uploads/{'a' * 32}.pdf"
    assert inbox_attachments.kind_for_key("t1", good) == "document"
    assert inbox_attachments.kind_for_key("t2", good) is None
    assert inbox_attachments.kind_for_key("t1", f"t1/wa_replies/{'a' * 32}.pdf") is None
    assert inbox_attachments.kind_for_key("t1", f"t1/inbox_uploads/../x/{'a' * 32}.pdf") is None


# ── upload endpoint ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_upload_stores_a_pdf_under_the_workspace_and_names_it(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid)
    res, put = _upload(client, _h(tenant_and_user), conv.id, "../Wedding menu.pdf", PDF)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["key"].startswith(f"{tid}/inbox_uploads/") and body["key"].endswith(".pdf")
    assert (body["kind"], body["filename"], body["size"]) == ("document", "Wedding menu.pdf", len(PDF))
    assert put.call_args.args[2] == "application/pdf"


def test_upload_refuses_other_types_and_oversized_photos(client, db, tenant_and_user):
    conv = _conv(db, _tid(tenant_and_user))
    bad, put = _upload(client, _h(tenant_and_user), conv.id, "x.pdf", b"MZ\x90\x00 not a pdf")
    big, _ = _upload(client, _h(tenant_and_user), conv.id, "big.jpg", JPG + b"x" * (5 * 1024 * 1024))
    assert bad.status_code == 400 and big.status_code == 400 and "5 MB" in big.json()["detail"]
    assert put.call_count == 0


def test_upload_is_whatsapp_only(client, db, tenant_and_user):
    conv = _conv(db, _tid(tenant_and_user), ChannelType.INSTAGRAM)
    res, _ = _upload(client, _h(tenant_and_user), conv.id, "a.jpg", JPG)
    assert res.status_code == 422


def test_upload_needs_the_send_capability(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid)
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name="R", email=f"r-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password="x", role=UserRole.READ_ONLY, is_active=True)
    db.add(u)
    db.commit()
    token = create_access_token({"sub": u.id, "tenant_id": tid, "role": u.role.value})
    res, put = _upload(client, {"Authorization": f"Bearer {token}"}, conv.id, "a.pdf", PDF)
    assert res.status_code == 403 and put.call_count == 0


def test_upload_to_another_workspaces_conversation_is_not_found(client, db, tenant_and_user):
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    conv = _conv(db, other.id)
    res, put = _upload(client, _h(tenant_and_user), conv.id, "a.pdf", PDF)
    assert res.status_code == 404 and put.call_count == 0


# ── sending an attachment ───────────────────────────────────────────────────────────────────────────────────────────

def _send(client, tenant_and_user, conv, **body):
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as delay:
        res = client.post(f"/api/v1/conversations/{conv.id}/messages", json={"body": "", **body}, headers=_h(tenant_and_user))
    return res, delay


def test_a_sent_attachment_keeps_the_key_kind_and_pdf_name(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid)
    key = f"{tid}/inbox_uploads/{uuid.uuid4().hex}.pdf"
    res, delay = _send(client, tenant_and_user, conv, body="Our menu", media_url=key, media_filename="Menu.pdf")
    assert res.status_code == 201, res.text
    msg = db.query(Message).filter_by(id=res.json()["id"]).one()
    assert (msg.media_type, msg.media_url, msg.body) == ("document", key, "Our menu")
    assert msg.channel_metadata == {"filename": "Menu.pdf"} and delay.call_count == 1


def test_sending_refuses_foreign_keys_audio_captions_and_a_closed_window(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid)
    foreign, _ = _send(client, tenant_and_user, conv, media_url=f"other/inbox_uploads/{uuid.uuid4().hex}.pdf")
    caption, _ = _send(client, tenant_and_user, conv, body="listen", media_url=f"{tid}/inbox_uploads/{uuid.uuid4().hex}.m4a")
    assert foreign.status_code == 422 and caption.status_code == 422
    db.query(Message).filter_by(conversation_id=conv.id).delete()
    db.commit()
    closed, delay = _send(client, tenant_and_user, conv, media_url=f"{tid}/inbox_uploads/{uuid.uuid4().hex}.jpg")
    assert closed.status_code == 409 and delay.call_count == 0


# ── several files per keyword reply ─────────────────────────────────────────────────────────────────────────────────

def _rule(db, tid, ac):
    r = AutomationRule(id=str(uuid.uuid4()), tenant_id=tid, name="Wedding bot", trigger="wa_message_received",
                       action="send_whatsapp_reply", is_active=True, run_count=0, trigger_config={"keywords": ["wedding"]},
                       action_config=ac)
    db.add(r)
    db.commit()
    return r


def _pdf(tid, n):
    return {"key": f"{tid}/wa_replies/{n:032x}.pdf", "kind": "document", "filename": f"Brochure {n}.pdf"}


def test_text_then_each_file_in_order_as_one_chain(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid)
    guest = db.get(Guest, conv.guest_id)
    _rule(db, tid, {"message": "Hi {first_name}, our wedding packages:", "files": [_pdf(tid, 1), _pdf(tid, 2), _pdf(tid, 3)]})
    with patch.object(wa_keyword_replies, "_dispatch") as dispatch:
        assert wa_keyword_replies.handle(db, tid, guest, conv, "wedding")
    ids = dispatch.call_args.args[0]
    msgs = {m.id: m for m in db.query(Message).filter_by(conversation_id=conv.id, direction="outbound")}
    sent = [msgs[i] for i in ids]
    assert [m.body for m in sent] == ["Hi Ananya, our wedding packages:", "", "", ""]
    assert [m.media_url for m in sent] == [None, _pdf(tid, 1)["key"], _pdf(tid, 2)["key"], _pdf(tid, 3)["key"]]
    assert [m.channel_metadata.get("filename") for m in sent[1:]] == ["Brochure 1.pdf", "Brochure 2.pdf", "Brochure 3.pdf"]
    for m in sent:
        m.delivery_state = MessageDeliveryState.SENT
    db.commit()
    (s,) = wa_keyword_replies.stats(db, tid, datetime.now(timezone.utc) - timedelta(days=1))
    assert (s["sent"], s["people"]) == (1, 1)  # one reply, not one per file


def test_several_messages_go_as_one_ordered_chain(monkeypatch):
    calls = []

    class _Chain:
        def __init__(self, *sigs):
            self.ids = [s.kwargs["message_id"] for s in sigs]

        def apply_async(self):
            calls.append(self.ids)

    monkeypatch.setattr("celery.chain", _Chain)
    wa_keyword_replies._dispatch(["a", "b", "c"], "t1")
    assert calls == [["a", "b", "c"]]


def test_an_old_single_file_rule_still_sends_one_message(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid)
    _rule(db, tid, {"message": "Here it is", "file": _pdf(tid, 7)})
    with patch.object(wa_keyword_replies, "_dispatch") as dispatch:
        assert wa_keyword_replies.handle(db, tid, db.get(Guest, conv.guest_id), conv, "wedding")
    (only,) = dispatch.call_args.args[0]
    msg = db.get(Message, only)
    assert (msg.body, msg.media_url, msg.channel_metadata["filename"]) == ("Here it is", _pdf(tid, 7)["key"], "Brochure 7.pdf")


def test_files_are_capped_and_must_be_this_workspaces(tenant_and_user):
    tid = _tid(tenant_and_user)
    _, ac = wa_keyword_replies.validate_rule({"keywords": ["x"]}, {"message": "Hi", "file": _pdf(tid, 1)}, tid)
    assert [f["key"] for f in ac["files"]] == [_pdf(tid, 1)["key"]] and "file" not in ac
    with pytest.raises(ValueError):
        wa_keyword_replies.validate_rule({"keywords": ["x"]}, {"message": "Hi", "files": [_pdf(tid, n) for n in range(6)]}, tid)
    with pytest.raises(ValueError):
        wa_keyword_replies.validate_rule({"keywords": ["x"]}, {"message": "Hi", "files": [_pdf(tid, 1), _pdf("other", 2)]}, tid)
