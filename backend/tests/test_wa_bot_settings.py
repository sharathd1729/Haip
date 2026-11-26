"""WhatsApp hours and welcome (SMS9 parity, track C): weekly hours + holidays, first-message welcome, location reply,
editable STOP / START confirmation, the one-reply-per-message order, and the owner/manager endpoints."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate
from app.models.audit_event import AuditEvent
from app.models.automation import AutomationRule
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.schemas.wa_bot import WaBotSettingsIn, Welcome
from app.services import agent_consult_settings, concierge_service, opt_out_responder as oor, wa_bot_replies
from app.services import wa_bot_settings as svc, wa_keyword_replies
from tests.test_increment1_defect_specs import _h, _tenant, _user

IST = ZoneInfo("Asia/Kolkata")
URL = "/api/v1/whatsapp/bot-settings"
WEEK = {d: {"open": "10:00", "close": "19:00"} for d in ("mon", "tue", "wed", "thu", "fri", "sat")} | {"sun": {"closed": True}}


def _at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def _with(t, **sections):
    t.brand_config = {**(t.brand_config or {}), "wa_bot": {**((t.brand_config or {}).get("wa_bot") or {}), **sections}}
    return t


def _world(db, **sections):
    t = Tenant(id=str(uuid.uuid4()), name="Neelgiri", slug=f"wb-{uuid.uuid4().hex[:6]}", plan="growth")
    _with(t, **sections)
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Ananya Rao", phone="+919886140372")
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(t)
    db.flush()
    db.add_all([g, c])
    db.commit()
    return t, g, c


def _inbound(db, t, c, body="Hi, is 20 Dec free?"):
    m = Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction="inbound", channel="whatsapp", body=body)
    db.add(m)
    db.commit()
    return m


def _out(db, c):
    return db.query(Message).filter_by(conversation_id=c.id, direction="outbound").order_by(Message.created_at).all()


@pytest.fixture
def queued(monkeypatch):
    out = []
    monkeypatch.setattr("app.workers.tasks.send_whatsapp.send_whatsapp.delay", lambda **kw: out.append(kw))
    return out


# ── hours ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_off_day_and_holiday_are_closed_and_weekdays_open():
    t = _with(Tenant(id="x", name="x"), hours={"weekly": WEEK, "holidays": [{"date": "2026-12-25", "label": "Christmas"}]})
    assert svc.is_open(t, _at(2026, 11, 26, 11))          # Thursday 11:00
    assert not svc.is_open(t, _at(2026, 11, 26, 19, 30))  # after closing
    assert not svc.is_open(t, _at(2026, 11, 29, 11))      # Sunday: off day
    assert not svc.is_open(t, _at(2026, 12, 25, 11))      # Friday, but a holiday
    assert agent_consult_settings.in_business_hours(t, _at(2026, 11, 29, 11)) is False   # Ask a manager reads the same hours


def test_a_window_past_midnight_spills_into_the_next_morning():
    t = _with(Tenant(id="x", name="x"), hours={"weekly": {"fri": {"open": "18:00", "close": "02:00"}}})
    assert svc.is_open(t, _at(2026, 11, 28, 1, 30))       # Saturday 01:30 = Friday's window
    assert svc.is_open(t, _at(2026, 11, 27, 23))


def test_old_single_window_is_read_into_every_weekday():
    t = Tenant(id="x", name="x", brand_config={"agent_consult": {"business_start": "08:00", "business_end": "20:00"}})
    hours = svc.get(t)["hours"]
    assert {d["open"] for d in hours["weekly"].values()} == {"08:00"} and hours["holidays"] == []
    assert svc.is_open(t, _at(2026, 11, 29, 8, 30)) and not svc.is_open(t, _at(2026, 11, 29, 7, 59))


def test_next_opening_skips_the_off_day_and_the_holiday():
    t = _with(Tenant(id="x", name="x"), hours={"weekly": WEEK, "holidays": [{"date": "2026-11-30"}]})
    # Saturday 20:00 -> Sunday off, Monday holiday -> Tuesday 10:00
    assert svc.next_opening(t, _at(2026, 11, 28, 20)) == _at(2026, 12, 1, 10).astimezone(timezone.utc)
    assert "on Tuesday" in agent_consult_settings.holding_text(t, _at(2026, 11, 28, 20))


def test_summary_groups_days():
    t = _with(Tenant(id="x", name="x"), hours={"weekly": WEEK})
    assert svc.hours_summary(t) == "Mon-Sat 10:00-19:00 · Sun closed"


def test_away_keyword_reply_follows_the_holiday(db, queued):
    t, g, c = _world(db, hours={"weekly": WEEK, "holidays": [{"date": "2026-12-25"}]})
    db.add(AutomationRule(id=str(uuid.uuid4()), tenant_id=t.id, name="Away", trigger="wa_message_received",
                          action="send_whatsapp_reply", is_active=True, run_count=0,
                          trigger_config={"reply_all": True, "hours": "closed"}, action_config={"message": "We're away"}))
    db.commit()
    with patch("app.services.agent_consult_settings.datetime") as dt:
        dt.now.return_value = _at(2026, 12, 25, 11)
        assert wa_keyword_replies.find_rule(db, t.id, "hello") is not None
        dt.now.return_value = _at(2026, 12, 24, 11)
        assert wa_keyword_replies.find_rule(db, t.id, "hello") is None


# ── welcome ─────────────────────────────────────────────────────────────────────────────────────────────────────────

WELCOME = {"enabled": True, "text": "Hi {first_name}, welcome to Neelgiri!", "buttons": ["Check dates"], "also_when_ai_replies": True}


def test_welcome_goes_once_per_contact(db, queued):
    t, g, c = _world(db, welcome=WELCOME)
    m1 = _inbound(db, t, c)
    assert wa_bot_replies.on_inbound(db, t, g, c, m1, "text") == "welcome"
    m2 = _inbound(db, t, c, "Also, pets allowed?")
    assert wa_bot_replies.on_inbound(db, t, g, c, m2, "text") is None
    [w] = _out(db, c)
    assert w.body == "Hi Ananya, welcome to Neelgiri!" and w.sender_kind == "automation_away"
    assert w.channel_metadata["interactive"] == {"kind": "buttons", "buttons": ["Check dates"]} and len(queued) == 1


def test_no_welcome_for_a_contact_we_already_talked_to(db, queued):
    t, g, c = _world(db, welcome=WELCOME)
    db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction="outbound", channel="whatsapp", body="Offer"))
    db.commit()
    assert wa_bot_replies.on_inbound(db, t, g, c, _inbound(db, t, c), "text") is None and queued == []


def test_welcome_waits_for_the_ai_when_the_owner_says_so(db, queued):
    t, g, c = _world(db, welcome={**WELCOME, "also_when_ai_replies": False})
    t.wa_ai_mode_default = "autonomous"
    db.commit()
    assert wa_bot_replies.on_inbound(db, t, g, c, _inbound(db, t, c), "text") is None   # the AI answers by itself
    t.wa_ai_mode_default = "shadow"
    db.commit()
    other = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Ravi", phone="+919886140373")
    c2 = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=other.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add_all([other, c2])
    db.commit()
    assert wa_bot_replies.on_inbound(db, t, other, c2, _inbound(db, t, c2), "text") == "welcome"   # AI only drafts


def test_welcome_off_by_default_and_other_tenant_settings_never_apply(db, queued):
    a, ga, ca = _world(db, welcome=WELCOME)
    b, gb, cb = _world(db)
    assert wa_bot_replies.on_inbound(db, b, gb, cb, _inbound(db, b, cb), "text") is None
    assert _out(db, cb) == [] and _out(db, ca) == []


def test_the_ai_still_sees_the_question_after_a_welcome(db, queued):
    t, g, c = _world(db, welcome=WELCOME)
    m = _inbound(db, t, c, "Is 20 Dec free?")
    wa_bot_replies.on_inbound(db, t, g, c, m, "text")
    assert concierge_service.unanswered_guest_text(db, t.id, c.id) == "Is 20 Dec free?"


def test_bad_buttons_are_refused():
    with pytest.raises(ValidationError):
        Welcome(text="Hi", buttons=["A label that is far too long"])


# ── location reply ──────────────────────────────────────────────────────────────────────────────────────────────────

LOCATION = {"enabled": True, "text": "Thanks! We're 45 minutes from you.", "map_link": "https://maps.app.goo.gl/abc"}


def test_location_reply_wins_over_the_welcome(db, queued):
    t, g, c = _world(db, welcome=WELCOME, location_reply=LOCATION)
    m = _inbound(db, t, c, "Shared a location")
    assert wa_bot_replies.on_inbound(db, t, g, c, m, "location") == "location"
    [r] = _out(db, c)
    assert r.body == "Thanks! We're 45 minutes from you.\nhttps://maps.app.goo.gl/abc" and m.automation_outcome == "location_auto_replied"


def test_location_without_the_setting_is_left_to_the_normal_path(db, queued):
    t, g, c = _world(db)
    assert wa_bot_replies.on_inbound(db, t, g, c, _inbound(db, t, c), "location") is None and queued == []


def test_map_link_must_be_https():
    with pytest.raises(ValidationError):
        WaBotSettingsIn(location_reply={"enabled": True, "text": "x", "map_link": "http://maps.example.com"})


# ── STOP / START confirmation ───────────────────────────────────────────────────────────────────────────────────────

def _stop_world(db, **sections):
    t, g, c = _world(db, **sections)
    for name in (oor.OPT_OUT_REPLY_TEMPLATE, oor.OPT_IN_REPLY_TEMPLATE):
        db.add(WATemplate(id=str(uuid.uuid4()), tenant_id=t.id, name=name, language="en", category="UTILITY",
                          status=TemplateStatus.APPROVED, components=[{"type": "BODY", "text": "Template text"}]))
    db.commit()
    return t, g, c


def _stop(db, t, g, direction="opt_out"):
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as text, \
            patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as tmpl:
        oor.process_opt_out_event(db, t.id, g.id, g.phone, direction, "stop")
    return text, tmpl


def test_stop_sends_the_owners_text_as_a_normal_reply(db):
    t, g, c = _stop_world(db, opt_confirm={"custom": True, "stop_text": "Okay, no more offers.", "start_text": "Welcome back!"})
    _inbound(db, t, c, "STOP")
    text, tmpl = _stop(db, t, g)
    assert text.call_count == 1 and tmpl.call_count == 0
    [m] = _out(db, c)
    assert m.body == "Okay, no more offers." and m.sender_kind == "system" and m.idempotency_key.startswith("oo:")


def test_start_uses_the_start_text_by_default(db):
    t, g, c = _stop_world(db)
    _inbound(db, t, c, "START")
    text, _ = _stop(db, t, g, "opt_in")
    assert text.call_count == 1 and _out(db, c)[0].body == svc.DEFAULTS["opt_confirm"]["start_text"]


def test_falls_back_to_the_template_when_the_text_cannot_go(db):
    t, g, c = _stop_world(db)                       # no inbound in 24 h: the plain reply is refused
    text, tmpl = _stop(db, t, g)
    assert text.call_count == 0 and tmpl.call_count == 1 and tmpl.call_args.kwargs["template_name"] == oor.OPT_OUT_REPLY_TEMPLATE


def test_owner_can_keep_the_template(db):
    t, g, c = _stop_world(db, opt_confirm={"custom": False, "stop_text": "x", "start_text": "y"})
    _inbound(db, t, c, "STOP")
    text, tmpl = _stop(db, t, g)
    assert text.call_count == 0 and tmpl.call_count == 1


# ── endpoints ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_owner_and_manager_read_and_save_audited(client, db):
    t = _tenant(db)
    owner, mgr = _user(db, t.id, UserRole.OWNER), _user(db, t.id, UserRole.MANAGER)
    got = client.get(URL, headers=_h(owner)).json()
    assert got["welcome"]["enabled"] is False and got["hours"]["weekly"]["mon"]["open"] == "09:00" and "hours_summary" in got
    res = client.put(URL, json={"hours": {"weekly": WEEK, "holidays": [{"date": "2026-11-08", "label": "Diwali"}]},
                                "welcome": WELCOME}, headers=_h(mgr))
    assert res.status_code == 200 and res.json()["changed"] == ["hours", "welcome"]
    assert res.json()["hours"]["weekly"]["sun"]["closed"] is True and res.json()["hours"]["holidays"][0]["label"] == "Diwali"
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="whatsapp.bot_settings_changed").count() == 1


def test_wrong_role_is_refused(client, db):
    t = _tenant(db)
    foh = _user(db, t.id, UserRole.FOH)
    assert client.get(URL, headers=_h(foh)).status_code == 403
    assert client.put(URL, json={"welcome": WELCOME}, headers=_h(foh)).status_code == 403


def test_a_save_never_touches_another_tenant(client, db):
    a, b = _tenant(db), _tenant(db)
    client.put(URL, json={"welcome": WELCOME}, headers=_h(_user(db, a.id, UserRole.OWNER)))
    assert client.get(URL, headers=_h(_user(db, b.id, UserRole.OWNER))).json()["welcome"]["enabled"] is False


def test_bad_input_is_422_and_patch_tenants_refuses_the_key(client, db):
    t = _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER)
    assert client.put(URL, json={"hours": {"weekly": {"mon": {"open": "25:00"}}}}, headers=_h(owner)).status_code == 422
    assert client.patch("/api/v1/tenants/me", json={"brand_config": {"wa_bot": {}}}, headers=_h(owner)).status_code == 422
