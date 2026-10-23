"""Evidence on a lead (lead_evidence_service, POST/GET /leads/{id}/evidence). Pinned: Android and iOS chat exports parse
(dd/mm and mm/dd, 12 h and 24 h, multi-line, media omitted, system lines); a zip's media is stored and a zip path that
escapes is refused; the guest side is found by number or name (else HAIP asks); a re-upload and an overlap with the bridge
mirror add nothing; imported messages never queue AI work, never open the 24 h window, but a staff reply counts as contact;
a recording becomes a connected upload Call queued for the same transcription pipeline; 403 for read_only, 404 for another
workspace's lead."""
import io
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from app.models.audit_event import AuditEvent
from app.models.call import Call
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.lead_evidence import LeadEvidenceImport
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import chat_export_parser as parser
from tests.conftest import seed_capabilities
from tests.test_lead_feed import _lead, _owner_headers, _user

ANDROID = (
    "12/10/26, 2:35 pm - Messages and calls are end-to-end encrypted. Only people in this chat can read them.\n"
    "12/10/26, 2:35 pm - Sharath N: Hi, is Ratha free on 1 Nov?\n"
    "We are 8 people\n"
    "12/10/26, 2:40 pm - Rathaa Sales: Yes it is! Shall I share the plan?\n"
    "13/10/26, 9:01 am - Sharath N: <Media omitted>\n"
    "13/10/26, 9:02 am - Rathaa Sales: IMG-20261013-WA0001.jpg (file attached)\n"
    "Route map\n"
)
IOS = (
    "‎[10/12/26, 2:35:12 PM] Sharath N: ‎Messages and calls are end-to-end encrypted.\n"
    "[10/12/26, 2:35:12 PM] Sharath N: Hello, the price is too high for us\n"
    "[10/13/26, 9:01:00 AM] Rathaa: ‎<attached: 00000012-PHOTO-2026-10-13-09-01-00.jpg>\n"
    "[10/13/26, 21:05:00] Sharath N: ‎Missed voice call\n"
)
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64


def test_android_export_parses_multiline_media_and_skips_system_lines():
    r = parser.parse(ANDROID)
    assert r.fmt == "android" and r.date_order == "dmy" and r.system_lines == 1
    assert [m.sender for m in r.messages] == ["Sharath N", "Rathaa Sales", "Sharath N", "Rathaa Sales"]
    assert r.messages[0].text == "Hi, is Ratha free on 1 Nov?\nWe are 8 people"
    assert r.messages[0].at == datetime(2026, 10, 12, 14, 35)
    assert r.messages[2].media_omitted and r.messages[2].text == ""
    assert r.messages[3].media_file == "IMG-20261013-WA0001.jpg" and r.messages[3].text == "Route map"


def test_ios_export_month_first_with_seconds_and_attachments():
    r = parser.parse(IOS)
    assert r.fmt == "ios" and r.date_order == "mdy" and r.system_lines == 2
    assert r.messages[0].at == datetime(2026, 10, 12, 14, 35, 12)
    assert r.messages[1].media_file == "00000012-PHOTO-2026-10-13-09-01-00.jpg"


def test_24h_android_and_four_digit_years():
    r = parser.parse("23/10/2026, 18:05 - Asha: Booked?\n23/10/2026, 18:06 - Team: Yes\n")
    assert [m.at.hour for m in r.messages] == [18, 18] and r.messages[0].at.year == 2026
    assert parser.parse("not a chat at all").messages == []


def _zip(chat: str, extra: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("WhatsApp Chat with Sharath N.txt", chat)
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def stored(monkeypatch):
    keys = []

    def fake(tenant_id, import_id, name, content, content_type):
        keys.append((name, content_type, len(content)))
        return f"{tenant_id}/lead_evidence/{import_id}/{name}"
    monkeypatch.setattr("app.services.media_storage.upload_lead_evidence", fake)
    return keys


@pytest.fixture
def no_tasks(monkeypatch):
    """Every Celery send is recorded: an import must not queue the concierge, a summary, the autopilot or a playbook."""
    sent = []
    from celery.app.task import Task as CeleryTask
    monkeypatch.setattr(CeleryTask, "apply_async", lambda self, *a, **k: sent.append(self.name))
    return sent


def _post(client, inquiry_id, headers, *, kind="chat_export", name="chat.txt", data: bytes = b"", **form):
    return client.post(f"/api/v1/leads/{inquiry_id}/evidence", headers=headers, data={"kind": kind, **form},
                       files={"file": (name, data, "application/octet-stream")})


def test_chat_export_is_written_to_the_leads_thread_without_any_ai(client, db, tenant_and_user, stored, no_tasks):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    h = _owner_headers(tenant_and_user)

    res = _post(client, inq.id, h, name="chat.zip", data=_zip(ANDROID, {"IMG-20261013-WA0001.jpg": JPEG, "evil.exe": b"MZ"}))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["message_count"] == 4 and body["duplicate_count"] == 0 and body["media_count"] == 1
    assert body["detail"]["guest_sender"] == "Sharath N"
    assert [n for n, _, _ in stored] == ["IMG-20261013-WA0001.jpg"]          # the .exe is ignored

    conv = db.query(Conversation).filter_by(id=body["conversation_id"]).one()
    assert conv.source == "personal_bridge" and conv.ai_mode == "off" and conv.guest_id == g.id
    msgs = db.query(Message).filter_by(conversation_id=conv.id).order_by(Message.created_at).all()
    assert [m.direction for m in msgs] == [MessageDirection.INBOUND, MessageDirection.OUTBOUND, MessageDirection.INBOUND, MessageDirection.OUTBOUND]
    assert all(m.sender_kind == "chat_export" and m.is_ai_generated is False and m.channel_metadata["source"] == "chat_export" for m in msgs)
    assert msgs[1].sender_name == "Rathaa Sales" and msgs[1].sender_id is None
    assert msgs[0].created_at.replace(tzinfo=timezone.utc) == datetime(2026, 10, 12, 9, 5, tzinfo=timezone.utc)   # 14:35 IST
    assert msgs[3].media_url.endswith("IMG-20261013-WA0001.jpg") and msgs[3].media_type == "image"
    assert no_tasks == []                                                    # nothing queued: no concierge, summary, autopilot
    assert db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="lead.evidence_imported").count() == 1

    from app.services.booking_agenda_service import whatsapp_state
    assert whatsapp_state(db, tenant.id, g.id)["window_open"] is False       # a personal-phone chat never opens the window

    from app.services.work_queue_signals import touch_rows
    rows = touch_rows(db, tenant.id, {g.id: datetime(2026, 10, 1, tzinfo=timezone.utc)})
    assert any(kind == "contact" for _, _, kind, _ in rows)                  # the staff reply counts as contact

    again = _post(client, inq.id, h, name="chat.txt", data=ANDROID.encode())
    assert again.status_code == 201 and again.json()["message_count"] == 0 and again.json()["duplicate_count"] == 4


def test_overlap_with_the_bridge_mirror_is_not_duplicated(client, db, tenant_and_user, stored, no_tasks):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=g.id, channel=ChannelType.WHATSAPP, source="personal_bridge")
    db.add(conv)
    db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                   channel=ChannelType.WHATSAPP, body="Hello, the price is too high for us", channel_message_id="bridge-1",
                   created_at=datetime(2026, 10, 12, 9, 5, 40, tzinfo=timezone.utc)))
    db.commit()
    res = _post(client, inq.id, _owner_headers(tenant_and_user), data=IOS.encode())
    assert res.status_code == 201, res.text
    assert res.json()["duplicate_count"] == 1 and res.json()["message_count"] == 1
    assert res.json()["conversation_id"] == conv.id


def test_unknown_guest_side_asks_which_name_then_accepts_the_pick(client, db, tenant_and_user, stored, no_tasks):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    g.name = "Unknown"
    db.commit()
    chat = "23/10/2026, 18:05 - +91 98450 99999: Booked?\n23/10/2026, 18:06 - Team: Yes\n"
    h = _owner_headers(tenant_and_user)
    res = _post(client, inq.id, h, data=chat.encode())
    assert res.status_code == 422 and res.json()["detail"]["code"] == "pick_guest_sender"
    assert {s["name"] for s in res.json()["detail"]["senders"]} == {"+91 98450 99999", "Team"}
    ok = _post(client, inq.id, h, data=chat.encode(), guest_sender="+91 98450 99999")
    assert ok.status_code == 201 and ok.json()["message_count"] == 2
    g.phone = "+919845088888"
    db.commit()
    by_number = "23/10/2026, 19:05 - +91 98450 88888: Still there?\n23/10/2026, 19:06 - Team: Yes\n"
    assert _post(client, inq.id, h, data=by_number.encode()).json()["detail"]["guest_sender"] == "+91 98450 88888"


def test_unsafe_zip_and_wrong_files_are_refused(client, db, tenant_and_user, stored, no_tasks):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    h = _owner_headers(tenant_and_user)
    assert _post(client, inq.id, h, name="c.zip", data=_zip(ANDROID, {"../../etc/passwd.jpg": JPEG})).status_code == 422
    assert _post(client, inq.id, h, name="c.pdf", data=b"%PDF").status_code == 415
    assert _post(client, inq.id, h, data=b"hello there").status_code == 422
    assert db.query(Message).count() == 0 and stored == []


def test_call_recording_becomes_a_connected_upload_call_on_the_ivr_pipeline(client, db, tenant_and_user, stored, monkeypatch):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    db.add(Task(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=g.id, inquiry_id=inq.id, title="Call back — missed call from Sharath",
                is_done=False, due_date=datetime.now(timezone.utc) - timedelta(hours=1)))
    db.commit()
    monkeypatch.setattr("app.services.lead_evidence_service.probe_seconds", lambda content, ext: 312)
    queued = []
    monkeypatch.setattr("app.workers.tasks.transcribe.transcribe.delay", lambda **kw: queued.append(kw))
    res = _post(client, inq.id, _owner_headers(tenant_and_user), kind="call_recording", name="call.m4a", data=b"audio-bytes",
                direction="outbound", note="Called from my phone")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["kind"] == "call_recording" and body["duration_seconds"] == 312 and body["status"] == "transcribing"
    call = db.query(Call).filter_by(id=body["call_id"]).one()
    assert call.ivr_provider == "upload" and call.agent_id == owner.id and call.guest_id == g.id and call.ivr_dial_status == "completed"
    assert call.recording_s3_key.endswith("recording.m4a") and call.transcription_status == "queued"
    assert queued == [{"call_id": call.id, "tenant_id": tenant.id}]
    assert db.query(Task).filter_by(tenant_id=tenant.id, guest_id=g.id, is_done=False).count() == 0   # call-back closed
    listed = client.get(f"/api/v1/leads/{inq.id}/evidence", headers=_owner_headers(tenant_and_user)).json()["items"]
    assert [i["id"] for i in listed] == [body["id"]] and listed[0]["uploaded_by_name"] == owner.name
    feed = client.get(f"/api/v1/leads/{inq.id}/feed", headers=_owner_headers(tenant_and_user)).json()
    item = [i for i in feed["items"] if i["kind"] == "call" and i["call_id"] == call.id][0]
    assert item["imported"] is True and item["summary_pending"] is True
    assert _post(client, inq.id, _owner_headers(tenant_and_user), kind="call_recording", name="x.exe", data=b"MZ").status_code == 415


def test_read_only_is_refused_and_another_workspaces_lead_is_not_found(client, db, tenant_and_user, stored, no_tasks):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    _, ro = _user(db, tenant.id, UserRole.READ_ONLY)
    assert _post(client, inq.id, ro, data=ANDROID.encode()).status_code == 403
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    seed_capabilities(db, other.id)
    _, oinq = _lead(db, other.id, None, phone="+919845099999")
    h = _owner_headers(tenant_and_user)
    assert _post(client, oinq.id, h, data=ANDROID.encode()).status_code == 404
    assert client.get(f"/api/v1/leads/{oinq.id}/evidence", headers=h).status_code == 404
    assert db.query(LeadEvidenceImport).count() == 0 and db.query(Message).count() == 0
