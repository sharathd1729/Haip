"""WhatsApp step 3: click-to-chat links (taps, chats, QR, website button), packages in chat, and the booking form
(a WhatsApp Flow)."""
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.core.security import create_access_token
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.integration import Integration
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.wa_entry_link import WaEntryLink
from app.services import wa_booking_form, wa_catalog, wa_entry_links, wa_interactive
from app.services.sales_gateway import GatewayResult
from tests._wa_window import open_window

pytestmark = pytest.mark.usefixtures("capabilities_seeded")


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _role_headers(db, tenant_id, role):
    user = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name="U", email=f"u-{uuid.uuid4().hex[:6]}@t.com",
                hashed_password="x", role=role, is_active=True)
    db.add(user)
    db.commit()
    return {"Authorization": "Bearer " + create_access_token({"sub": user.id, "tenant_id": tenant_id, "role": role.value})}


def _other_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    return t.id


def _wa(db, tid, **config):
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=tid, kind="whatsapp_meta", status="active",
                       config={"waba_id": "waba1", "phone_number_id": "pn", "display_phone": "+91 98861 40372", **config}))
    db.commit()


def _chat(db, tid, window=True):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Ananya Rao", phone="+919886140372")
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id)
    db.add(inq)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, inquiry_id=inq.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(c)
    db.flush()
    if window:
        open_window(db, c)
    db.commit()
    return g, c, inq


# ─── entry links ─────────────────────────────────────────────────────────────

def test_create_list_and_follow_a_link(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _wa(db, tid)
    r = client.post("/api/v1/messaging/entry-links", json={"name": "Instagram bio", "prefill_text": "Hi! Dates for Coorg?"},
                    headers=_h(tenant_and_user))
    assert r.status_code == 201, r.text
    link = r.json()
    assert link["phone"] == "919886140372" and link["url"].endswith(f"/api/v1/w/{link['url'].rsplit('/', 1)[1]}")
    code = link["url"].rsplit("/", 1)[1]
    assert "%28ref%20w-" + code in link["wa_me"]
    go = client.get(f"/api/v1/w/{code}", follow_redirects=False)
    assert go.status_code == 302 and go.headers["location"].startswith("https://wa.me/919886140372?text=Hi%21")
    db.expire_all()
    row = db.query(WaEntryLink).filter_by(code=code).one()
    assert row.clicks == 1 and row.last_clicked_at is not None
    listed = client.get("/api/v1/messaging/entry-links", headers=_h(tenant_and_user)).json()
    assert listed["links"][0]["clicks"] == 1 and listed["workspace_phone"] == "919886140372"


def test_a_switched_off_or_unknown_link_does_not_redirect(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    link = wa_entry_links.create(db, tid, None, name="Flyer", phone="+919886140372")
    link.active = False
    db.commit()
    assert client.get(f"/api/v1/w/{link.code}", follow_redirects=False).status_code == 404
    assert client.get("/api/v1/w/zzzzzzzz", follow_redirects=False).status_code == 404


def test_qr_and_website_button(client, db, tenant_and_user):
    link = wa_entry_links.create(db, _tid(tenant_and_user), None, name="Reception", phone="+919886140372")
    qr = client.get(f"/api/v1/w/{link.code}/qr.svg")
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg+xml") and b"<svg" in qr.content
    js = client.get(f"/api/v1/w/{link.code}/widget.js", params={"label": 'Say "hi"'})
    assert js.status_code == 200 and f"/api/v1/w/{link.code}" in js.text and '\\"hi\\"' in js.text   # JSON-escaped, not code


def test_links_need_a_number_and_a_marketer(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    with pytest.raises(wa_entry_links.EntryLinkError):
        wa_entry_links.create(db, tid, None, name="No number")          # WhatsApp not connected, no number given
    assert client.post("/api/v1/messaging/entry-links", json={"name": "x", "phone": "+919886140372"},
                       headers=_role_headers(db, tid, UserRole.FOH)).status_code == 403


def test_another_workspaces_link_is_not_found(client, db, tenant_and_user):
    theirs = wa_entry_links.create(db, _other_tenant(db), None, name="Theirs", phone="+919886140372")
    r = client.patch(f"/api/v1/messaging/entry-links/{theirs.id}", json={"active": False}, headers=_h(tenant_and_user))
    assert r.status_code == 404


def test_a_chat_is_counted_only_for_the_same_workspace(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    link = wa_entry_links.create(db, tid, None, name="Bio", phone="+919886140372")
    msg = f"Hi! Dates for Coorg? (ref w-{link.code})"
    assert wa_entry_links.count_chat(db, _other_tenant(db), msg) is False
    assert wa_entry_links.count_chat(db, tid, msg) is True
    db.commit()
    db.expire_all()
    assert db.query(WaEntryLink).get(link.id).chats == 1


# ─── packages in chat ────────────────────────────────────────────────────────

PKGS = [{"key": "coorg-3n", "name": "Coorg Coffee Trail 3N", "summary": "Estates, waterfalls and a campfire night",
         "min_nights": 3, "max_nights": 5, "max_guests": 4, "inclusions": ["Caravan", "Fuel up to 600 km"]},
        {"key": "kabini", "name": "Kabini Wild Weekend", "summary": None, "min_nights": 2, "max_nights": None,
         "max_guests": 6, "inclusions": []}]


def test_the_packages_list_never_carries_a_price(db, tenant_and_user):
    with patch("app.services.sales_gateway.list_packages", return_value=GatewayResult(True, PKGS)) as lp:
        text, spec = wa_catalog.list_message(db, _tid(tenant_and_user))
    assert lp.call_args.kwargs["include_rates"] is False
    rows = spec["sections"][0]["rows"]
    assert [r["id"] for r in rows] == ["pkg:coorg-3n", "pkg:kabini"] and len(rows[0]["title"]) <= 24
    assert rows[1]["description"] == "2+ nights · up to 6 guests"
    wa_interactive.validate(spec)                                      # within Meta's limits
    with patch("app.services.sales_gateway.list_packages", return_value=GatewayResult(False, [])):
        with pytest.raises(wa_catalog.CatalogError):
            wa_catalog.list_message(db, _tid(tenant_and_user))


def _tap(reply_id, kind="list_reply"):
    return {"type": "interactive", "interactive": {"type": kind, kind: {"id": reply_id, "title": "x"}}}


def test_a_pick_answers_with_details_and_book_buttons(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g, c, _ = _chat(db, tid)
    with patch("app.services.sales_gateway.get_package", return_value=GatewayResult(True, PKGS[0])), \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as send:
        assert wa_catalog.handle(db, tid, g, c, _tap("pkg:coorg-3n")) is True
    out = db.query(Message).filter_by(conversation_id=c.id, direction="outbound").one()
    assert "Coorg Coffee Trail 3N" in out.body and "3-5 nights" in out.body and "₹" not in out.body
    assert out.channel_metadata["interactive"]["button_ids"] == ["pkgbook:coorg-3n", "pkgtalk:coorg-3n"]
    send.assert_called_once()


def test_book_this_makes_a_task_for_the_team(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g, c, inq = _chat(db, tid)
    with patch("app.services.sales_gateway.get_package", return_value=GatewayResult(True, PKGS[0])), \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"):
        assert wa_catalog.handle(db, tid, g, c, _tap("pkgbook:coorg-3n", "button_reply")) is True
    task = db.query(Task).filter_by(tenant_id=tid, guest_id=g.id).one()
    assert "payment link" in task.title and task.inquiry_id == inq.id
    assert wa_catalog.handle(db, tid, g, c, _tap("btn_0", "button_reply")) is False       # not ours


def test_send_packages_endpoint(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _, c, _ = _chat(db, tid)
    _, closed, _ = _chat(db, tid, window=False)
    with patch("app.services.sales_gateway.list_packages", return_value=GatewayResult(True, PKGS)), \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"):
        ok = client.post(f"/api/v1/conversations/{c.id}/send-packages", headers=_h(tenant_and_user))
        shut = client.post(f"/api/v1/conversations/{closed.id}/send-packages", headers=_h(tenant_and_user))
    assert ok.status_code == 201, ok.text
    assert shut.status_code == 409
    _, theirs, _ = _chat(db, _other_tenant(db))
    assert client.post(f"/api/v1/conversations/{theirs.id}/send-packages", headers=_h(tenant_and_user)).status_code == 404


# ─── booking form ────────────────────────────────────────────────────────────

def _nfm(data):
    return {"type": "interactive", "interactive": {"type": "nfm_reply", "nfm_reply": {
        "name": "flow", "body": "Sent", "response_json": json.dumps(data)}}}


def test_form_answers_are_saved_on_the_enquiry(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g, c, inq = _chat(db, tid)
    msg = _nfm({"flow_token": f"haip-booking:{c.id}", "check_in": "2026-12-20", "check_out": "2026-12-23",
                "adults": "2", "children": "1", "notes": "Anniversary"})
    assert wa_booking_form.describe(msg) == "📝 Booking form: 20 Dec → 23 Dec · 2 adults, 1 child\nAnniversary"
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"):
        assert wa_booking_form.apply(db, tid, g, c, msg) is True
    db.refresh(inq)
    assert (inq.check_in, inq.check_out, inq.adults, inq.children) == ("2026-12-20", "2026-12-23", 2, 1)
    assert "Anniversary" in inq.special_requests and inq.dates_from_chat is True


def test_someone_elses_form_or_bad_dates_are_ignored(db, tenant_and_user):
    assert wa_booking_form.answers(_nfm({"flow_token": "other-app:1", "check_in": "2026-12-20"})) is None
    p = wa_booking_form.parsed({"check_in": "2026-12-20", "check_out": "2026-12-19", "adults": "-3"})
    assert p["check_out"] is None and p["adults"] is None


def test_publish_creates_uploads_and_publishes_once(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _wa(db, tid)
    calls = []

    def post(url, **kw):
        calls.append(url)
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"id": "flow-77"} if url.endswith("/flows") else {"success": True}
        return resp
    client_mock = MagicMock()
    client_mock.__enter__.return_value.post.side_effect = post
    with patch("app.services.wa_booking_form.httpx.Client", return_value=client_mock), \
         patch("app.workers.tasks.whatsapp._get_wa_access_token", return_value="tok"):
        r = client.post("/api/v1/messaging/booking-form/publish", headers=_h(tenant_and_user))
        again = client.post("/api/v1/messaging/booking-form/publish", headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    assert r.json() == {"connected": True, "flow_id": "flow-77", "published": True, "error": None}
    assert [u.rsplit("/", 1)[1] for u in calls] == ["flows", "assets", "publish"]       # the second call did nothing
    assert again.status_code == 200
    assert client.post("/api/v1/messaging/booking-form/publish",
                       headers=_role_headers(db, tid, UserRole.MARKETING)).status_code == 403


def test_send_booking_form_needs_it_published(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _wa(db, tid)
    _, c, _ = _chat(db, tid)
    assert client.post(f"/api/v1/conversations/{c.id}/send-booking-form", headers=_h(tenant_and_user)).status_code == 422
    row = db.query(Integration).filter_by(tenant_id=tid).one()
    row.config = {**row.config, "booking_flow": {"id": "flow-77", "status": "PUBLISHED"}}
    db.commit()
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"):
        r = client.post(f"/api/v1/conversations/{c.id}/send-booking-form", headers=_h(tenant_and_user))
    assert r.status_code == 201, r.text
    spec = db.query(Message).get(r.json()["message_id"]).channel_metadata["interactive"]
    meta = wa_interactive.payload(spec, "Share your dates")
    assert meta["type"] == "flow" and meta["action"]["parameters"]["flow_token"] == f"haip-booking:{c.id}"
