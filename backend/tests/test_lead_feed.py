"""GET /leads/{id}/feed (the lead page's one thread) and POST /leads/{id}/contact/reveal.

Pinned: every kind lands in one list, oldest first, capped; drafts are marked and rejected drafts left out; the
facts the next-step helper reads come from the same rows; message text and booking amounts follow the caller's
capabilities; another workspace's lead is a 404 (endpoint) / None (service); a role without leads.read gets 403;
the reveal endpoint is audited and needs guests.pii.reveal. Also PATCH /inquiries for the new trip fields.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from app.core.security import create_access_token, get_password_hash
from app.models.audit_event import AuditEvent
from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.guest_merge_event import GuestMergeEvent
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.inquiry_360 import InquiryQuote, InquiryStageLog
from app.models.property import Property, Stay
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import lead_feed_service
from tests.conftest import seed_capabilities

T0 = datetime(2026, 10, 17, 13, 0, tzinfo=timezone.utc)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _user(db, tenant_id, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name=f"{role.value} person", email=f"{uuid.uuid4().hex[:8]}@t.test",
             hashed_password=get_password_hash("x-test-pass"), role=role, is_active=True)
    db.add(u)
    db.commit()
    token = create_access_token({"sub": u.id, "tenant_id": tenant_id, "role": role.value})
    return u, {"Authorization": f"Bearer {token}"}


def _lead(db, tenant_id, owner_id, phone="+919845012321"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Sharath N", phone=phone, email="sharath@example.test")
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, stage=InquiryStage.NEW, source=InquirySource.PHONE,
                  check_in="2026-11-01", check_out="2026-11-02", adults=8, route_mentioned="Kabini, via Mysuru",
                  custom_fields={"pickup": "Whitefield"})
    db.add(inq)
    db.commit()
    return g, inq


def _thread(db, tenant_id, owner, g, inq):
    """One of each kind, at known times."""
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, inquiry_id=inq.id, channel=ChannelType.WHATSAPP)
    db.add(conv)
    db.flush()
    db.add_all([
        Call(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, inquiry_id=inq.id, ivr_provider="vobiz",
             ivr_call_id=uuid.uuid4().hex, direction=CallDirection.INBOUND, from_number="+919845012321", to_number="+918000000000",
             duration_seconds=252, ai_summary="Wants Ratha for 8 friends to Kabini.", transcript_json=[{"speaker": "agent", "text": "hi"}],
             recording_s3_key="rec/1.mp3", ivr_dial_status="completed", created_at=at(0)),
        InquiryStageLog(id=str(uuid.uuid4()), tenant_id=tenant_id, inquiry_id=inq.id, from_stage="general_enquiry", to_stage="active",
                        changed_by=owner.id, changed_at=at(5), reason=""),
        Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                channel=ChannelType.WHATSAPP, body="Namaskara Sharath", sender_name="Jishanth", created_at=at(7)),
        Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                channel=ChannelType.WHATSAPP, body="Send the price for 8", created_at=at(20)),
        InquiryQuote(id=str(uuid.uuid4()), tenant_id=tenant_id, inquiry_id=inq.id, amount=65000, shared_via="sent", status="issued",
                     shared_at=at(35), created_at=at(34), valid_until=at(60 * 48), created_by=owner.id, option_rank=1),
        # an AI draft nobody sent yet, and one a person rejected (left out)
        Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                channel=ChannelType.WHATSAPP, body="Draft reply", is_ai_generated=True, was_approved=None, created_at=at(40)),
        Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                channel=ChannelType.WHATSAPP, body="Rejected draft", is_ai_generated=True, was_approved=False, created_at=at(41)),
        Task(id=str(uuid.uuid4()), tenant_id=tenant_id, inquiry_id=inq.id, title="Call about the counter-offer",
             created_by=owner.id, assigned_to=owner.id, created_at=at(45)),
        Call(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, inquiry_id=inq.id, ivr_provider="vobiz",
             ivr_call_id=uuid.uuid4().hex, direction=CallDirection.OUTBOUND, from_number="+918000000000", to_number="+919845012321",
             duration_seconds=38, ivr_dial_status="no-answer", created_at=at(50)),
        GuestMergeEvent(id=str(uuid.uuid4()), tenant_id=tenant_id, survivor_id=g.id, deprecated_id=str(uuid.uuid4()),
                        actor_user_id=owner.id, reason="manual", moved={"conversations": ["c1"]}, created_at=at(55)),
    ])
    prop = Property(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Ratha 1", slug=f"r1-{uuid.uuid4().hex[:5]}", type="caravan")
    db.add(prop)
    db.flush()
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, property_id=prop.id, inquiry_id=None,
                check_in=date(2026, 2, 14), check_out=date(2026, 2, 15), adults=4, status="checked_out", total_amount=42000,
                created_at=at(-60 * 24 * 200)))
    db.commit()
    return conv, prop


def _get(client, inquiry_id, headers):
    return client.get(f"/api/v1/leads/{inquiry_id}/feed", headers=headers)


def _owner_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def test_feed_puts_every_kind_in_one_list_oldest_first(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    _thread(db, tenant.id, owner, g, inq)

    res = _get(client, inq.id, _owner_headers(tenant_and_user))

    assert res.status_code == 200, res.text
    body = res.json()
    kinds = [i["kind"] for i in body["items"]]
    assert kinds == ["booking", "call", "stage", "message", "message", "quote", "message", "task", "call", "merge"]
    assert "Rejected draft" not in [i.get("text") for i in body["items"]]
    draft = [i for i in body["items"] if i["kind"] == "message" and i["is_draft"]]
    assert [d["text"] for d in draft] == ["Draft reply"]
    first_call, second_call = [i for i in body["items"] if i["kind"] == "call"]
    assert first_call["answered"] is True and first_call["summary"].startswith("Wants Ratha")
    assert first_call["has_recording"] and first_call["has_transcript"]
    assert second_call["answered"] is False and second_call["direction"] == "outbound"
    stage = next(i for i in body["items"] if i["kind"] == "stage")
    assert stage["to_label"] == "Active" and stage["by_name"] == owner.name
    quote = next(i for i in body["items"] if i["kind"] == "quote")
    assert quote["amount"] == 65000 and quote["shared_via"] == "sent"
    booking = next(i for i in body["items"] if i["kind"] == "booking")
    assert booking["label"] == "Ratha 1" and booking["amount"] == 42000
    # facts for the next step, from the same rows
    assert body["facts"]["unanswered_outbound_calls"] == 1
    assert body["facts"]["missed_inbound_unreturned"] is False
    assert body["facts"]["pending_drafts"] == 1
    assert body["facts"]["last_inbound_at"].startswith("2026-10-17T13:20")
    assert body["facts"]["last_outbound_at"].startswith("2026-10-17T13:07")   # the unsent draft is not "we replied"
    # the composer's channel, contact (masked), trip and availability
    assert [c["channel"] for c in body["channels"]] == ["whatsapp"] and body["channels"][0]["can_send"] is True
    assert body["contact"]["phone_masked"] == "+91 ••••• ••321" and "9845012321" not in res.text
    assert body["trip"] == {"route": "Kabini, via Mysuru", "pickup": "Whitefield", "special_requests": None,
                            "lost_reason": None, "lost_note": None}
    assert [(v["name"], v["free"]) for v in body["availability"]] == [("Ratha 1", True)]
    assert body["merges"][0]["joined"] == ["1 conversation"] and body["capped"] is False


def test_feed_caps_at_fifty_newest(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=g.id, inquiry_id=inq.id, channel=ChannelType.INSTAGRAM)
    db.add(conv)
    db.add_all([Message(id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                        channel=ChannelType.INSTAGRAM, body=f"m{n}", created_at=at(n)) for n in range(70)])
    db.commit()

    body = _get(client, inq.id, _owner_headers(tenant_and_user)).json()

    assert len(body["items"]) == 50 and body["capped"] is True
    assert body["items"][0]["text"] == "m20" and body["items"][-1]["text"] == "m69"


def test_service_never_returns_another_tenants_lead(db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    g, inq = _lead(db, tenant.id, owner.id)
    _thread(db, tenant.id, owner, g, inq)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()

    assert lead_feed_service.get_lead_feed(db, other.id, inq.id, capabilities={"conversations.read"}) is None
    mine = lead_feed_service.get_lead_feed(db, tenant.id, inq.id, capabilities={"conversations.read"})
    assert mine is not None and len(mine.items) == 10


def test_another_workspace_lead_is_a_404(client, db, tenant_and_user):
    seed_capabilities(db, tenant_and_user["tenant"].id)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    other_owner, _ = _user(db, other.id, UserRole.OWNER)
    g, inq = _lead(db, other.id, other_owner.id)
    _thread(db, other.id, other_owner, g, inq)

    headers = _owner_headers(tenant_and_user)
    assert _get(client, inq.id, headers).status_code == 404
    assert client.post(f"/api/v1/leads/{inq.id}/contact/reveal", headers=headers).status_code == 404


def test_a_role_without_leads_read_is_forbidden(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    _, headers = _user(db, tenant.id, UserRole.COMPLIANCE)

    assert _get(client, inq.id, headers).status_code == 403


def test_scoped_role_cannot_open_a_teammates_lead(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    inq.assigned_to = owner.id
    db.commit()
    _, headers = _user(db, tenant.id, UserRole.CONCIERGE)

    assert _get(client, inq.id, headers).status_code == 404


def test_marketing_sees_the_thread_without_message_text_or_booking_amounts(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    _thread(db, tenant.id, owner, g, inq)
    _, headers = _user(db, tenant.id, UserRole.MARKETING)

    body = _get(client, inq.id, headers).json()

    assert body["messages_restricted"] is True
    assert "message" not in [i["kind"] for i in body["items"]]
    assert "Send the price" not in str(body)
    assert body["bookings"][0]["total"] is None and body["bookings"][0]["amount_restricted"] is True


def test_reveal_returns_the_number_and_writes_an_audit_row(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)

    res = client.post(f"/api/v1/leads/{inq.id}/contact/reveal", headers=_owner_headers(tenant_and_user))

    assert res.status_code == 200, res.text
    assert res.json() == {"phone": "+919845012321", "email": "sharath@example.test"}
    row = db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="guest.pii.reveal").one()
    assert row.target_id == g.id and row.actor_user_id == owner.id


def test_reveal_needs_the_pii_capability(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    _, headers = _user(db, tenant.id, UserRole.FOH)

    assert client.post(f"/api/v1/leads/{inq.id}/contact/reveal", headers=headers).status_code == 403
    assert db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="guest.pii.reveal").count() == 0


def test_patch_inquiry_saves_route_pickup_and_special_requests(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    g, inq = _lead(db, tenant.id, owner.id)
    headers = _owner_headers(tenant_and_user)

    res = client.patch(f"/api/v1/inquiries/{inq.id}", headers=headers,
                       json={"route_mentioned": " Coorg ", "pickup": "Indiranagar", "special_requests": "Stop at JSS"})
    assert res.status_code == 200, res.text
    db.refresh(inq)
    assert (inq.route_mentioned, inq.special_requests, inq.custom_fields["pickup"]) == ("Coorg", "Stop at JSS", "Indiranagar")

    client.patch(f"/api/v1/inquiries/{inq.id}", headers=headers, json={"pickup": "", "special_requests": ""})
    db.refresh(inq)
    assert "pickup" not in (inq.custom_fields or {}) and inq.special_requests is None
