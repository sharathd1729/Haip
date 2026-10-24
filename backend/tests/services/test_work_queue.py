"""The one work queue (work_queue_service).

It is organised around PEOPLE we hold a phone number for (a lead), so these tests pin: who counts as "nobody has contacted them
yet" (a person did, the bot alone did not), that a person is listed once, how urgent each item is, and that the dashboard cards
read the same numbers as the queue.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.pipeline_stage import PipelineStage
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import dashboard_service, work_queue_service as wq

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_now():
    """NOW is set at import (collection); a full run reaches these tests 30+ min later, ageing every "N minutes ago" past
    its threshold. Re-read the clock per test."""
    global NOW
    NOW = datetime.now(timezone.utc)


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"wq-{uuid.uuid4().hex[:6]}", plan="growth",
               ivr_provider="vobiz")
    db.add(t); db.flush(); return t


def _user(db, tid):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name="Agent", email=f"a-{uuid.uuid4().hex[:6]}@t.com",
             role=UserRole.CONCIERGE, is_active=True)
    db.add(u); db.flush(); return u


def _guest(db, tid, name="Guest", lead_minutes_ago=None, channel="whatsapp"):
    """A lead when lead_minutes_ago is given (the number arrived that long ago); a plain contact (no number yet) otherwise."""
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name=name, phone=f"+9198{uuid.uuid4().int % 10**8:08d}",
              first_touch_channel=channel,
              lead_identified_at=(NOW - timedelta(minutes=lead_minutes_ago)) if lead_minutes_ago is not None else None)
    db.add(g); db.flush(); return g


def _inquiry(db, tid, guest, assigned_to=None, stage=InquiryStage.NEW, **kw):
    i = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, stage=stage, assigned_to=assigned_to,
                source=InquirySource.WA_DIRECT, created_at=NOW - timedelta(days=1), **kw)
    db.add(i); db.flush(); return i


def _conv(db, tid, guest, channel=ChannelType.WHATSAPP, assigned_to=None):
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, channel=channel, is_open=True, assigned_to=assigned_to)
    db.add(c); db.flush(); return c


def _msg(db, tid, conv, direction, minutes_ago, body="hello?", **kw):
    m = Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=direction, channel=conv.channel,
                body=body, created_at=NOW - timedelta(minutes=minutes_ago), **kw)
    db.add(m); db.flush(); return m


def _lead(db, tid, minutes=30, name="Lead", assigned_to=None, **kw):
    """A lead whose number arrived `minutes` ago, with an open enquiry and a WhatsApp chat saying hello."""
    g = _guest(db, tid, name, lead_minutes_ago=minutes)
    inq = _inquiry(db, tid, g, assigned_to=assigned_to, **kw)
    c = _conv(db, tid, g, assigned_to=assigned_to)
    _msg(db, tid, c, "inbound", minutes, body="Is the caravan free this weekend?")
    return g, inq, c


def _call(db, tid, guest, direction, status, minutes_ago=5, duration=60):
    db.add(Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, ivr_provider="vobiz",
                ivr_call_id=f"c-{uuid.uuid4().hex[:8]}", direction=direction, from_number=guest.phone, to_number="+918000000000",
                duration_seconds=duration, ivr_dial_status=status, created_at=NOW - timedelta(minutes=minutes_ago)))
    db.flush()


def _missed(db, tid, minutes=20, guest=None):
    g = guest or _guest(db, tid, "Caller")
    _call(db, tid, g, CallDirection.INBOUND, "no-answer", minutes_ago=minutes, duration=0)
    return g


def _kinds(res):
    return {i["title"]: i["kind"] for i in res["items"]}


# ── new leads ────────────────────────────────────────────────────────────────

def test_a_lead_nobody_has_contacted_is_a_new_lead_with_what_they_said(db):
    t = _tenant(db)
    g, inq, _ = _lead(db, t.id, minutes=10, name="Asha", check_in="2026-12-12", check_out="2026-12-14", adults=2)
    db.commit()

    res = wq.build(db, t, scope_user_id=None)
    item = next(i for i in res["items"] if i["title"] == "Asha")
    assert item["kind"] == "new_lead" and item["action"] == "Call"
    assert "free this weekend" in item["detail"]
    assert item["guest_phone"] == g.phone and item["inquiry_id"] == inq.id
    assert item["facts"] == ["12–14 Dec", "2 adults"]
    assert item["channels"] == ["whatsapp"]
    assert res["counts"]["new_lead"] == 1 and res["unowned"] == 1


def test_a_contact_without_a_number_is_not_a_lead(db):
    """An Instagram DM that never produced a number is a conversation, not someone to chase."""
    t = _tenant(db)
    g = _guest(db, t.id, "DM only", lead_minutes_ago=None, channel="instagram")
    c = _conv(db, t.id, g, ChannelType.INSTAGRAM)
    _msg(db, t.id, c, "inbound", 120)
    db.commit()
    res = wq.build(db, t, scope_user_id=None)
    assert res["total"] == 0 and res["items"] == []


def test_a_message_a_person_sent_clears_the_lead(db):
    t = _tenant(db)
    g, _, c = _lead(db, t.id, minutes=60)
    _msg(db, t.id, c, "outbound", 5, body="Hi, calling you shortly", is_internal=False)
    db.commit()
    assert wq.build(db, t, scope_user_id=None)["counts"]["new_lead"] == 0


def test_the_bots_own_reply_does_not_count_as_contact(db):
    """The AI answered by itself: the guest got an answer, but no person has reached out, so the lead stays open."""
    t = _tenant(db)
    g, _, c = _lead(db, t.id, minutes=60)
    _msg(db, t.id, c, "outbound", 55, body="Thanks for reaching out!", is_ai_generated=True, was_approved=True, sent_autonomously=True)
    db.commit()
    res = wq.build(db, t, scope_user_id=None)
    assert res["counts"]["new_lead"] == 1
    assert res["counts"]["reply"] == 0          # ...but nobody is "waiting for a reply": the bot answered


def test_an_ai_draft_a_person_approved_counts_as_contact(db):
    t = _tenant(db)
    g, _, c = _lead(db, t.id, minutes=60)
    _msg(db, t.id, c, "outbound", 5, is_ai_generated=True, was_approved=True, sent_autonomously=False)
    db.commit()
    assert wq.build(db, t, scope_user_id=None)["counts"]["new_lead"] == 0


def test_an_answered_call_clears_the_lead_but_an_unanswered_attempt_does_not(db):
    t = _tenant(db)
    tried, _, _ = _lead(db, t.id, minutes=120, name="Tried")
    spoke, _, _ = _lead(db, t.id, minutes=120, name="Spoke")
    heard, _, _ = _lead(db, t.id, minutes=120, name="Heard")
    _call(db, t.id, tried, CallDirection.OUTBOUND, "no-answer", minutes_ago=30, duration=22)
    _call(db, t.id, tried, CallDirection.OUTBOUND, "no-answer", minutes_ago=10, duration=18)
    _call(db, t.id, spoke, CallDirection.OUTBOUND, "completed", minutes_ago=30, duration=140)
    _call(db, t.id, heard, CallDirection.INBOUND, "completed", minutes_ago=30, duration=90)
    db.commit()

    res = wq.build(db, t, scope_user_id=None)
    assert _kinds(res) == {"Tried": "new_lead"}
    item = res["items"][0]
    assert item["attempts"] == 2 and item["detail"].startswith("Tried 2×, no answer")


def test_contact_from_before_the_number_arrived_does_not_count(db):
    t = _tenant(db)
    g, _, c = _lead(db, t.id, minutes=30)
    _msg(db, t.id, c, "outbound", 90, body="An older chat message")          # before lead_identified_at
    db.commit()
    assert wq.build(db, t, scope_user_id=None)["counts"]["new_lead"] == 1


def test_closed_unsuitable_and_old_leads_are_left_out(db):
    t = _tenant(db)
    _lead(db, t.id, minutes=60, name="Lost one", stage=InquiryStage.LOST)
    stage = PipelineStage(id=str(uuid.uuid4()), tenant_id=t.id, key="unsuitable", label="Unsuitable", category="valid")
    db.add(stage); db.flush()
    _lead(db, t.id, minutes=60, name="Unsuitable one", stage_id=stage.id)
    _lead(db, t.id, minutes=60 * 24 * 20, name="Three weeks ago")
    _lead(db, t.id, minutes=60, name="Spam", qualification_status="unqualified")
    _lead(db, t.id, minutes=60, name="Keeper")
    db.commit()
    assert list(_kinds(wq.build(db, t, scope_user_id=None))) == ["Keeper"]


def test_a_lead_with_no_enquiry_yet_is_still_listed(db):
    t = _tenant(db)
    g = _guest(db, t.id, "No enquiry", lead_minutes_ago=3, channel="call")
    db.commit()
    item = wq.build(db, t, scope_user_id=None)["items"][0]
    assert item["kind"] == "new_lead" and item["inquiry_id"] is None and item["channels"] == ["call"]


# ── urgency ──────────────────────────────────────────────────────────────────

def test_severity_follows_the_sla_and_the_list_is_best_chance_first(db):
    t = _tenant(db)
    _lead(db, t.id, minutes=5, name="Fresh")
    _lead(db, t.id, minutes=40, name="Late")
    _lead(db, t.id, minutes=150, name="Urgent")
    _lead(db, t.id, minutes=60 * 10, name="Critical")
    _lead(db, t.id, minutes=60 * 24 * 5, name="Cold")
    db.commit()

    res = wq.build(db, t, scope_user_id=None)
    sev = {i["title"]: i["severity"] for i in res["items"]}
    assert sev == {"Fresh": "fresh", "Late": "late", "Urgent": "urgent", "Critical": "critical", "Cold": "stale"}
    # Order is lead_priority's, not the SLA's (owner, 20 Oct 2026): leads under a day old are "Call now", freshest (highest
    # score) first, a tie goes to whoever waited longest; the cold one is "Chase when free", last.
    assert [i["title"] for i in res["items"]] == ["Fresh", "Late", "Critical", "Urgent", "Cold"]
    assert [i["lane"] for i in res["items"]] == ["now", "now", "now", "now", "chase"]
    assert res["severity"]["critical"] == 1 and res["severity"]["stale"] == 1
    assert [i["overdue"] for i in res["items"]] == [False, True, True, True, True]


# ── one row per person ───────────────────────────────────────────────────────

def test_a_person_is_listed_once_under_the_most_specific_reason(db):
    t = _tenant(db)
    g, _, c = _lead(db, t.id, minutes=90, name="Everything")
    _missed(db, t.id, minutes=60, guest=g)
    db.commit()

    res = wq.build(db, t, scope_user_id=None)
    assert [(i["title"], i["kind"]) for i in res["items"]] == [("Everything", "callback")]
    assert res["total"] == 1 and res["people"] == 1


def test_the_badge_counts_people_waiting_not_rows_and_not_the_cold_tail(db):
    t, other = _tenant(db), _tenant(db)
    g, inq, _ = _lead(db, t.id, minutes=90, name="Missed and tasked")
    _missed(db, t.id, minutes=60, guest=g)
    db.add(Task(id=str(uuid.uuid4()), tenant_id=t.id, title="Send the brochure", guest_id=g.id, inquiry_id=inq.id,
                is_done=False, due_date=NOW - timedelta(hours=1)))
    _lead(db, t.id, minutes=60 * 24 * 5, name="Cold")             # stale: not in the badge
    _lead(db, other.id, name="Theirs")
    db.commit()
    res = wq.build(db, t, scope_user_id=None)
    assert res["total"] == 3                                      # callback + task + cold lead: rows
    assert res["people"] == 2 and res["people_waiting"] == 1
    assert wq.counts(db, t, scope_user_id=None)["people_waiting"] == 1
    assert wq.counts(db, other, scope_user_id=None)["people_waiting"] == 1


def test_three_missed_calls_from_one_person_is_one_callback(db):
    t = _tenant(db)
    g = _missed(db, t.id, minutes=300)
    _missed(db, t.id, minutes=200, guest=g)
    _missed(db, t.id, minutes=100, guest=g)
    db.commit()
    assert wq.build(db, t, scope_user_id=None)["counts"]["callback"] == 1


# ── waiting replies ──────────────────────────────────────────────────────────

def test_a_lead_waiting_on_a_person_is_a_reply_and_shows_a_waiting_ai_draft(db):
    t = _tenant(db)
    g, inq, c = _lead(db, t.id, minutes=200, name="Waiting")
    _call(db, t.id, g, CallDirection.OUTBOUND, "completed", minutes_ago=100, duration=120)   # a person already spoke to them
    _msg(db, t.id, c, "inbound", 20, body="Hello? anyone there?")
    _msg(db, t.id, c, "outbound", 19, body="Draft: yes it is free", is_ai_generated=True, was_approved=None)   # held, unsent
    db.commit()

    res = wq.build(db, t, scope_user_id=None)
    item = next(i for i in res["items"] if i["title"] == "Waiting")
    assert item["kind"] == "reply" and item["has_draft"] is True and "anyone there" in item["detail"]


def test_the_bot_gets_a_few_minutes_before_a_person_is_asked(db):
    t = _tenant(db)
    g, _, c = _lead(db, t.id, minutes=1, name="Just wrote")
    _call(db, t.id, g, CallDirection.OUTBOUND, "completed", minutes_ago=0, duration=60)   # keep them out of new_lead
    db.commit()
    assert wq.build(db, t, scope_user_id=None)["counts"]["reply"] == 0


def test_a_chat_without_a_number_is_never_a_waiting_reply(db):
    t = _tenant(db)
    g = _guest(db, t.id, "Just a DM", lead_minutes_ago=None, channel="instagram")
    c = _conv(db, t.id, g, ChannelType.INSTAGRAM)
    _msg(db, t.id, c, "inbound", 600)
    db.commit()
    assert wq.build(db, t, scope_user_id=None)["counts"]["reply"] == 0


# ── scope, tenants, followups ────────────────────────────────────────────────

def test_an_agent_sees_their_own_leads_and_unowned_ones_only(db):
    t = _tenant(db)
    me, peer = _user(db, t.id), _user(db, t.id)
    _lead(db, t.id, name="Mine", assigned_to=me.id)
    _lead(db, t.id, name="Peers", assigned_to=peer.id)
    _lead(db, t.id, name="Nobodys")
    db.add(Task(id=str(uuid.uuid4()), tenant_id=t.id, title="peer task", is_done=False,
                assigned_to=peer.id, due_date=NOW - timedelta(hours=1)))
    db.commit()

    mine = wq.build(db, t, scope_user_id=me.id)
    assert set(_kinds(mine)) == {"Mine", "Nobodys"}
    assert mine["counts"]["followup"] == 0 and mine["scope"] == "mine"
    team = wq.build(db, t, scope_user_id=None)
    assert {i["title"] for i in team["items"] if i["kind"] == "new_lead"} == {"Mine", "Peers", "Nobodys"}


def test_followups_overdue_and_due_soon_but_not_future_or_done(db):
    t = _tenant(db)
    me = _user(db, t.id)
    for title, due, done in [("overdue", NOW - timedelta(days=3), False), ("soon", NOW + timedelta(minutes=20), False),
                             ("next week", NOW + timedelta(days=5), False), ("done", NOW - timedelta(hours=2), True)]:
        db.add(Task(id=str(uuid.uuid4()), tenant_id=t.id, title=title, is_done=done, assigned_to=me.id, due_date=due))
    _missed(db, t.id, minutes=60 * 24 * 10)           # older than the call-back window
    db.commit()
    res = wq.build(db, t, scope_user_id=me.id)
    assert {i["title"]: i["severity"] for i in res["items"]} == {"overdue": "critical", "soon": "fresh"}
    assert res["counts"]["callback"] == 0


def test_kinds_narrows_the_items_but_not_the_counts_and_tenants_are_separate(db):
    t, other = _tenant(db), _tenant(db)
    _lead(db, t.id, name="Mine")
    _missed(db, t.id)
    _lead(db, other.id, name="Theirs")
    _missed(db, other.id)
    db.commit()

    only_calls = wq.build(db, t, scope_user_id=None, kinds=["callback"])
    assert {i["kind"] for i in only_calls["items"]} == {"callback"}
    assert only_calls["counts"]["callback"] == 1 and only_calls["counts"]["new_lead"] == 1
    assert "Theirs" not in {i["title"] for i in wq.build(db, t, scope_user_id=None)["items"]}


def test_dashboard_cards_read_the_same_numbers(db):
    t = _tenant(db)
    _lead(db, t.id, minutes=90)
    _lead(db, t.id, minutes=5)
    _missed(db, t.id, minutes=40)
    db.commit()

    q = wq.counts(db, t, None)
    cards = dashboard_service.needs_you_now(db, t, scope_user_id=None)
    assert cards["new_leads"] == q["counts"]["new_lead"] == 2
    assert cards["missed_not_called_back"] == q["counts"]["callback"] == 1
    assert cards["new_leads_oldest_at"] == q["oldest"]["new_lead"]
    assert cards["breached"] == 2 and cards["people"] == 3 and cards["unassigned"] == 2


def test_endpoint_returns_the_queue(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    _lead(db, tid, minutes=45, name="Via API")
    db.commit()
    h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    r = client.get("/api/v1/work-queue", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["new_lead"] == 1 and body["scope"] == "team" and body["items"][0]["severity"] == "late"
    assert client.get("/api/v1/work-queue?mine_only=true", headers=h).json()["scope"] == "mine"
    assert client.get("/api/v1/work-queue/counts", headers=h).json()["counts"]["new_lead"] == 1
    assert client.get("/api/v1/work-queue?kinds=unassigned", headers=h).status_code == 422
