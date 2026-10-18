"""WhatsApp booking templates: per-message document header, dynamic URL buttons, the booking pack (drafts only)."""
import uuid
from unittest.mock import patch

from app.api.v1.endpoints.messaging import TemplateCategory, TemplateStatus, WATemplate
from app.core.security import create_access_token
from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.user import User, UserRole
from app.services import wa_booking_pack
from app.services import wa_template_service as wts
from app.services.template_linter import lint_template
from app.services.wa_booking_messages import rzp_suffix
from app.workers.tasks.send_whatsapp import _template_components

CONFIRMED = wa_booking_pack.BY_NAME[wa_booking_pack.BOOKING_CONFIRMED]["components"]
BALANCE = wa_booking_pack.BY_NAME[wa_booking_pack.BALANCE_DUE]["components"]
QUOTE = wa_booking_pack.BY_NAME[wa_booking_pack.QUOTE_PAYMENT]["components"]


def _vmap(n):
    return {"body": {str(i): {"source": "static", "value": f"v{i}"} for i in range(1, n + 1)}}


def test_document_header_override_and_url_button_components():
    out = wts.build_send_components(QUOTE, _vmap(8), None, header_media_link="https://files.example/q.pdf",
                                    header_document_filename="Quote Q-1.pdf", button_params={0: "i/AbC"})
    assert out[0] == {"type": "header", "parameters": [{"type": "document", "document": {"link": "https://files.example/q.pdf", "filename": "Quote Q-1.pdf"}}]}
    assert out[1]["type"] == "body" and len(out[1]["parameters"]) == 8
    assert out[2] == {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": "i/AbC"}]}
    assert len(out) == 3                                       # the quick reply needs nothing at send time
    try:
        wts.build_send_components(BALANCE, _vmap(4), None)
        raise AssertionError("a dynamic link with no ending must not be sent")
    except wts.TemplateError as exc:
        assert "Pay balance" in str(exc)


def test_existing_template_sends_are_unchanged():
    comps = [{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "Hi {{1}}"},
             {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "Site", "url": "https://ratha.in"}, {"type": "QUICK_REPLY", "text": "Ok"}]}]
    out = wts.build_send_components(comps, _vmap(1), None, header_media_link="https://files.example/a.jpg")
    assert out == [{"type": "header", "parameters": [{"type": "image", "image": {"link": "https://files.example/a.jpg"}}]},
                   {"type": "body", "parameters": [{"type": "text", "text": "v1"}]}]


def test_dynamic_url_validation():
    def problems(url, example=None):
        b = {"type": "URL", "text": "Pay", "url": url}
        if example is not None:
            b["example"] = example
        return wts.validate_components([{"type": "BODY", "text": "x"}, {"type": "BUTTONS", "buttons": [b]}])
    assert problems("https://rzp.io/{{1}}", ["https://rzp.io/i/AbC"]) == []
    assert problems("https://rzp.io/{{1}}") == ["A link with {{1}} needs an example: the full link with a sample ending."]
    assert problems("https://rzp.io/{{1}}/x", ["https://rzp.io/a/x"]) == ["A link can only have one variable, {{1}}, at the very end."]
    assert problems("https://rzp.io/{{2}}", ["https://rzp.io/a"]) == ["A link can only have one variable, {{1}}, at the very end."]


def test_pack_is_lint_clean_and_structurally_valid():
    for t in wa_booking_pack.PACK:
        body = next(c for c in t["components"] if c["type"] == "BODY")
        samples = {str(i + 1): v for i, v in enumerate(body["example"]["body_text"][0])}
        findings = lint_template(body=body["text"], header=None, category="UTILITY", sample_values=samples)
        assert not [f for f in findings if f.level == "error"], (t["name"], findings)
        # The approved texts for the quote and the confirmation carry 8 values; the linter only advises <= 4.
        assert all("variables. Meta recommends" in f.message for f in findings), (t["name"], findings)
        problems = wts.validate_components(t["components"])
        has_doc = any(c.get("format") == "DOCUMENT" for c in t["components"])
        # Only the sample PDF is missing; the owner uploads it in the template editor before submitting to Meta.
        assert problems == (["Upload a sample document for the header."] if has_doc else []), (t["name"], problems)
        assert len(wts.template_variables(t["components"])["body"]) == len(body["example"]["body_text"][0])


def test_rzp_suffix():
    assert rzp_suffix("https://rzp.io/i/AbC123") == "i/AbC123"
    assert rzp_suffix("https://rzp.io/rzp/x_Y-1") == "rzp/x_Y-1"
    assert rzp_suffix("https://evil.example/i/AbC") is None
    assert rzp_suffix("https://rzp.io/i/a?b=c") is None


def test_send_task_uses_message_document_and_button(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    tmpl = WATemplate(tenant_id=tid, name=wa_booking_pack.QUOTE_PAYMENT, language="en", category=TemplateCategory.UTILITY,
                      status=TemplateStatus.APPROVED, components=QUOTE, header_media_key=f"{tid}/wa_templates/sample.pdf")
    guest = Guest(tenant_id=tid, name="K", phone="+919812345678")
    db.add_all([tmpl, guest])
    db.flush()
    conv = Conversation(tenant_id=tid, guest_id=guest.id, channel=ChannelType.WHATSAPP)
    db.add(conv)
    db.flush()
    msg = Message(tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
                  channel_metadata={"template_id": tmpl.id, "document": {"key": f"{tid}/invoices/q.pdf", "filename": "Quote.pdf"},
                                    "button_params": {"0": "i/Pay1"}})
    plain = Message(tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
                    channel_metadata={"template_id": tmpl.id, "button_params": {"0": "i/Pay2"}})
    db.add_all([msg, plain])
    db.commit()
    with patch("app.services.media_storage.get_presigned_media_url", side_effect=lambda key, expires_in=0: f"https://signed/{key}"):
        out = _template_components(db, tid, msg, [f"v{i}" for i in range(8)])
        fixed = _template_components(db, tid, plain, [f"v{i}" for i in range(8)])
    assert out[0]["parameters"][0]["document"] == {"link": f"https://signed/{tid}/invoices/q.pdf", "filename": "Quote.pdf"}
    assert out[-1]["parameters"][0]["text"] == "i/Pay1"
    assert fixed[0]["parameters"][0]["document"] == {"link": f"https://signed/{tid}/wa_templates/sample.pdf"}   # template's own file


def _tok(db, tid, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name=role.value, email=f"{uuid.uuid4().hex[:8]}@t.com", hashed_password="x",
             role=role, is_active=True)
    db.add(u)
    db.commit()
    return {"Authorization": "Bearer " + create_access_token({"sub": u.id, "tenant_id": tid, "role": role.value})}


def test_booking_pack_endpoint_creates_drafts_once(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    listed = client.get("/api/v1/messaging/templates/booking-pack", headers=h).json()["templates"]
    assert [t["status"] for t in listed] == [None] * 4
    with patch("httpx.post") as meta:                      # nothing may reach Meta
        r = client.post("/api/v1/messaging/templates/booking-pack", headers=h).json()
        again = client.post("/api/v1/messaging/templates/booking-pack", headers=h).json()
    meta.assert_not_called()
    assert sorted(r["created"]) == sorted(t["name"] for t in wa_booking_pack.PACK) and again["created"] == []
    rows = db.query(WATemplate).filter_by(tenant_id=tid).all()
    assert len(rows) == 4 and {r.status for r in rows} == {TemplateStatus.DRAFT} and {r.category for r in rows} == {TemplateCategory.UTILITY}
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="messaging.booking_pack_created").count() == 1
    assert {t["status"] for t in again["templates"]} == {"draft"}


def test_booking_pack_endpoint_forbidden_and_per_tenant(client, db, tenant_and_user):
    from app.models.tenant import Tenant
    tid = tenant_and_user["tenant"].id
    res = _tok(db, tid, UserRole.RESERVATIONS)
    assert client.post("/api/v1/messaging/templates/booking-pack", headers=res).status_code == 403
    assert client.get("/api/v1/messaging/templates/booking-pack", headers=res).status_code == 403
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    client.post("/api/v1/messaging/templates/booking-pack", headers=h)
    oh = _tok(db, other.id, UserRole.OWNER)
    assert {t["status"] for t in client.get("/api/v1/messaging/templates/booking-pack", headers=oh).json()["templates"]} == {None}
    assert db.query(WATemplate).filter_by(tenant_id=other.id).count() == 0
