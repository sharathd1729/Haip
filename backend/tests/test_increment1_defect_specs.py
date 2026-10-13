"""Executable specifications for the defects listed in docs/ai/SALES_AGENT_INCREMENT_1.md (14 Oct 2026).

Each test states the behaviour that SHOULD hold. Where the code does not do that yet, the test is `xfail(strict=True)` and names
the pull request that fixes it: today the test documents and proves the defect; the day the fix lands it starts passing, strict
mode turns that into a failure, and the fixer deletes the marker. Tests without a marker are controls: they pass today and
must keep passing (they stop an over-eager fix from breaking legitimate behaviour).

Registered, not hidden: these are the only expected failures in the suite (see CLAUDE.md "no known failures").
"""
import os
import threading
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.capability import Capability
from app.models.consent import Consent
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState
from app.models.guest import Guest
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import authz_service
from app.services.opt_out_detector import detect_opt_out
from tests.conftest import TestingSessionLocal, engine

DELAY = "celery.app.task.Task.delay"          # patched on the class: the endpoint runs in a worker thread (see test_knowledge_lifecycle)


def PR(n: int, what: str):
    return pytest.mark.xfail(strict=True, reason=f"PR-{n}: {what}")


# ─── builders ──────────────────────────────────────────────────────────────────────────────────────────────

def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"i1-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    db.flush()
    if db.query(Capability).filter_by(key="conversations.send").first() is None:
        db.add(Capability(key="conversations.send", label="Send", category="conversations", is_write=True, risk="medium"))
        db.flush()
    authz_service.seed_default_capabilities(db, t.id)
    db.commit()
    return t


def _user(db, tenant_id, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name=role.value, email=f"{role.value}-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password=get_password_hash("pw"), role=role, is_active=True)
    db.add(u)
    db.commit()
    return u


def _h(user):
    return {"Authorization": "Bearer " + create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})}


def _conv(db, tenant_id):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="G", phone=f"+9199990{uuid.uuid4().int % 100000:05d}")      # digits only: a hex letter makes the number invalid and the sender refuses it
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(c)
    db.flush()
    return g, c


def _msg(db, tenant_id, conv, **kw):
    base = dict(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id, direction="outbound", channel="whatsapp",
                body="The caravan is free those dates.")
    base.update(kw)
    m = Message(**base)
    db.add(m)
    db.commit()
    return m


def _draft(db, tenant_id, conv):
    return _msg(db, tenant_id, conv, is_ai_generated=True, was_approved=None)


def _sent_human(db, tenant_id, conv, sender_id):
    return _msg(db, tenant_id, conv, body="Booked, see you on the 12th.", is_ai_generated=False, sender_id=sender_id,
                delivery_state=MessageDeliveryState.SENT, channel_message_id="wamid.HUMAN", channel_status="sent")


def _url(conv, msg, verb):
    return f"/api/v1/conversations/{conv.id}/messages/{msg.id}/{verb}"


@pytest.fixture()
def world(db):
    t = _tenant(db)
    return SimpleNamespace(t=t, owner=_user(db, t.id, UserRole.OWNER), ro=_user(db, t.id, UserRole.READ_ONLY))


# ═══ A. AI draft approval and rejection (PR-1) ═════════════════════════════════════════════════════════════

def test_control_a_pending_ai_draft_can_be_approved_once_by_an_authorised_user(db, client, world):
    g, c = _conv(db, world.t.id)
    d = _draft(db, world.t.id, c)
    with patch(DELAY) as send:
        r = client.post(_url(c, d, "approve"), json={}, headers=_h(world.owner))
    assert r.status_code == 200
    assert send.call_count == 1 and send.call_args.kwargs["message_id"] == d.id
    db.expire_all()
    assert db.get(Message, d.id).was_approved is True


@PR(1, "requesting a draft spends provider credit, so it needs conversations.send like the rewrite endpoints")
def test_a_read_only_user_cannot_queue_an_ai_draft(db, client, world):
    g, c = _conv(db, world.t.id)
    db.commit()
    with patch("app.api.v1.endpoints.conversations.concierge_draft.delay") as queued:
        r = client.post(f"/api/v1/conversations/{c.id}/messages/ai-draft", json={}, headers=_h(world.ro))
    assert r.status_code == 403 and queued.call_count == 0


@PR(1, "reject must require conversations.send")
def test_a_read_only_user_cannot_reject_a_draft(db, client, world):
    g, c = _conv(db, world.t.id)
    d = _draft(db, world.t.id, c)
    r = client.post(_url(c, d, "reject"), headers=_h(world.ro))
    assert r.status_code == 403
    db.expire_all()
    assert db.get(Message, d.id).was_approved is None


@PR(1, "reject only acts on a pending AI draft")
def test_rejecting_an_already_sent_human_message_is_refused_and_changes_nothing(db, client, world):
    g, c = _conv(db, world.t.id)
    m = _sent_human(db, world.t.id, c, world.owner.id)
    r = client.post(_url(c, m, "reject"), headers=_h(world.owner))
    assert r.status_code == 409
    db.expire_all()
    after = db.get(Message, m.id)
    assert after.delivery_state == MessageDeliveryState.SENT and after.was_approved is None


@PR(1, "approve only acts on a pending AI draft")
def test_approve_cannot_rewrite_a_message_that_was_already_sent(db, client, world):
    g, c = _conv(db, world.t.id)
    m = _sent_human(db, world.t.id, c, world.owner.id)
    with patch(DELAY) as send:
        r = client.post(_url(c, m, "approve"), json={"text": "Actually the price is Rs 1"}, headers=_h(world.owner))
    assert r.status_code == 409 and send.call_count == 0
    db.expire_all()
    assert db.get(Message, m.id).body == "Booked, see you on the 12th."


@PR(1, "a rejected draft cannot be revived by approve")
def test_a_rejected_draft_cannot_be_approved(db, client, world):
    g, c = _conv(db, world.t.id)
    d = _draft(db, world.t.id, c)
    assert client.post(_url(c, d, "reject"), headers=_h(world.owner)).status_code == 200
    with patch(DELAY) as send:
        r = client.post(_url(c, d, "approve"), json={}, headers=_h(world.owner))
    assert r.status_code == 409 and send.call_count == 0


@PR(1, "an inbound message is not a draft")
def test_an_inbound_guest_message_can_be_neither_approved_nor_rejected(db, client, world):
    g, c = _conv(db, world.t.id)
    m = _msg(db, world.t.id, c, direction="inbound", body="Hi", is_ai_generated=False)
    with patch(DELAY) as send:
        a = client.post(_url(c, m, "approve"), json={}, headers=_h(world.owner))
        r = client.post(_url(c, m, "reject"), headers=_h(world.owner))
    assert a.status_code == 409 and r.status_code == 409 and send.call_count == 0


@PR(1, "approval is idempotent: the second request must not queue a second send")
def test_approving_twice_queues_exactly_one_send(db, client, world):
    g, c = _conv(db, world.t.id)
    d = _draft(db, world.t.id, c)
    with patch(DELAY) as send:
        first = client.post(_url(c, d, "approve"), json={}, headers=_h(world.owner))
        second = client.post(_url(c, d, "approve"), json={}, headers=_h(world.owner))
    assert first.status_code == 200 and second.status_code in (200, 409)
    assert send.call_count == 1


@PR(1, "approval is bound to the text the human saw (expected_body_sha256)")
def test_approving_with_a_stale_view_of_the_draft_is_refused(db, client, world):
    g, c = _conv(db, world.t.id)
    d = _draft(db, world.t.id, c)          # e.g. rewrite_draft changed the body after the agent opened it
    with patch(DELAY) as send:
        r = client.post(_url(c, d, "approve"), json={"expected_body_sha256": "0" * 64}, headers=_h(world.owner))
    assert r.status_code == 409 and send.call_count == 0


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="needs real concurrent transactions (PostgreSQL)")
@PR(1, "concurrent approvals must be serialised by a guarded UPDATE")
def test_concurrent_approvals_queue_exactly_one_send():
    from fastapi import HTTPException
    from app.api.v1.endpoints.conversations import approve_ai_draft
    from app.schemas.conversation import ApproveDraftRequest

    s0 = TestingSessionLocal()
    t = _tenant(s0)
    owner = _user(s0, t.id, UserRole.OWNER)
    g, c = _conv(s0, t.id)
    d = _draft(s0, t.id, c)
    tid, uid, cid, mid = t.id, owner.id, c.id, d.id
    s0.close()

    barrier, results = threading.Barrier(2), []

    def worker():
        s = TestingSessionLocal()
        try:
            user = s.get(User, uid)
            barrier.wait()
            try:
                results.append(approve_ai_draft(cid, mid, ApproveDraftRequest(), user, s, None))
            except HTTPException as exc:
                results.append(exc.status_code)
        finally:
            s.close()

    try:
        with patch(DELAY) as send:
            ts = [threading.Thread(target=worker) for _ in range(2)]
            [x.start() for x in ts]
            [x.join() for x in ts]
        assert send.call_count == 1, results
    finally:                                              # this test commits for real (threads need separate connections): clean up
        from sqlalchemy import text
        s = TestingSessionLocal()
        for tbl in ("ai_draft_outcomes", "messages", "conversations", "guests", "users", "role_capabilities"):
            s.execute(text(f"DELETE FROM {tbl} WHERE tenant_id = :t"), {"t": tid})
        s.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        s.commit()
        s.close()


# ═══ B. Opt-out semantics (PR-2) ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("text", ["STOP", "stop.", "Unsubscribe", "opt out", "बंद करो", "stop messaging me", "stop sending me messages"])
def test_control_clear_requests_to_stop_are_opt_outs(text):
    r = detect_opt_out(text)
    assert r.matched and r.direction == "opt_out"


@pytest.mark.parametrize("text", [
    pytest.param("I want to cancel my booking", marks=PR(2, "booking cancellation is not an opt-out")),
    pytest.param("Please cancel my reservation for Dec 12", marks=PR(2, "booking cancellation is not an opt-out")),
    pytest.param("cancel", marks=PR(2, "a bare ambiguous word is not an opt-out")),
    pytest.param("can we stop by the market on the way", marks=PR(2, "'stop' inside a sentence about travel")),
    pytest.param("remove the bonfire add-on please", marks=PR(2, "'remove' is about an add-on")),
    pytest.param("can you block the dates for us", marks=PR(2, "'block' is about dates")),
    pytest.param("we may end the trip a day early", marks=PR(2, "'end' is about the trip")),
])
def test_ordinary_sentences_and_booking_cancellations_do_not_opt_the_guest_out(text):
    r = detect_opt_out(text)
    assert not (r.matched and r.direction == "opt_out"), r


@pytest.mark.parametrize("text", [
    pytest.param("yes", marks=PR(2, "'yes' answers any question; it is not marketing consent")),
    pytest.param("Yes please send the quote", marks=PR(2, "'yes' answers any question")),
    pytest.param("begin the trip from Bengaluru", marks=PR(2, "'begin' is about the trip")),
    pytest.param("start date is 12 Dec", marks=PR(2, "'start' is about the trip")),
    pytest.param("हाँ", marks=PR(2, "'हाँ' (yes) answers any question")),
])
def test_ambiguous_words_never_record_marketing_consent(text):
    r = detect_opt_out(text)
    assert not (r.matched and r.direction == "opt_in"), r


@pytest.mark.parametrize("text", ["START", "subscribe", "opt in", "resubscribe"])
def test_control_an_explicit_whole_message_keyword_still_opts_in(text):
    r = detect_opt_out(text)
    assert r.matched and r.direction == "opt_in"


@PR(2, "'do not contact me' style requests must be recognised")
@pytest.mark.parametrize("text", ["do not contact me again", "please don't message me"])
def test_explicit_do_not_contact_requests_are_recognised(text):
    assert detect_opt_out(text).matched


@PR(2, "the opt-out confirmation imports send_template_message, which does not exist in send_whatsapp.py")
def test_the_opt_out_confirmation_is_actually_queued(db):
    from app.services import opt_out_responder
    t = _tenant(db)
    g, c = _conv(db, t.id)
    db.commit()
    log = MagicMock()
    with patch.object(opt_out_responder, "log", log), patch(DELAY):
        opt_out_responder.process_opt_out_event(db, t.id, g.id, "+919800000001", "opt_out", "stop")
    assert not any(c.args and c.args[0] == "opt_out_confirm_template_skipped" for c in log.warning.call_args_list)


# ═══ C. Do-not-contact at the delivery step (PR-2) ═════════════════════════════════════════════════════════

class _Adapter:
    def __init__(self):
        self.calls = 0

    async def send_template(self, to, template_name, language_code="en", components=None):
        self.calls += 1
        return {"messages": [{"id": "wamid.OK"}]}


def _template_world(db, category):
    from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate

    t = _tenant(db)
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=t.id, kind="whatsapp_meta", status="active", config={"phone_number_id": "pn1"}))
    tmpl = WATemplate(id=str(uuid.uuid4()), tenant_id=t.id, name="offer", language="en", category=category, status=TemplateStatus.APPROVED,
                      components=[{"type": "BODY", "text": "Hi {{1}}, a note from Ratha."}])
    db.add(tmpl)
    g, c = _conv(db, t.id)
    m = _msg(db, t.id, c, direction="outbound", body="Hi Asha", delivery_state=MessageDeliveryState.QUEUED, channel_status="queued",
             channel_metadata={"template_id": tmpl.id, "template_name": "offer"})
    db.add(Consent(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel="whatsapp", scope="marketing", granted=False,
                   recorded_at=datetime.now(timezone.utc).isoformat(), withdrawn_at=datetime.now(timezone.utc).isoformat(),
                   withdrawal_reason="user_keyword"))
    db.commit()
    return t, m.id


def _send_template(db, t, msg_id):
    from app.workers.tasks import send_whatsapp as mod
    adapter = _Adapter()
    with patch.object(mod, "SessionLocal", return_value=db), patch.object(db, "close"), \
         patch.object(mod, "get_wa_adapter", return_value=adapter), patch("app.workers.tasks.whatsapp._get_wa_access_token", return_value="tok"):
        mod.send_whatsapp_template.apply(kwargs={"message_id": msg_id, "tenant_id": t.id, "template_name": "offer",
                                                   "language_code": "en", "variables": ["Asha"]})
    db.expire_all()
    return adapter, db.get(Message, msg_id)


@PR(2, "a marketing template must not be delivered to a guest who withdrew marketing consent")
def test_a_marketing_template_is_not_sent_to_a_guest_who_opted_out(db):
    from app.api.v1.endpoints.messaging import TemplateCategory
    t, mid = _template_world(db, TemplateCategory.MARKETING)
    adapter, msg = _send_template(db, t, mid)
    assert adapter.calls == 0
    assert msg.delivery_state == MessageDeliveryState.FAILED and "opted out" in (msg.delivery_error or "").lower()


def test_control_a_utility_template_is_still_delivered_after_a_marketing_opt_out(db):
    from app.api.v1.endpoints.messaging import TemplateCategory
    t, mid = _template_world(db, TemplateCategory.UTILITY)       # booking/payment notices are transactional, not marketing
    adapter, msg = _send_template(db, t, mid)
    assert adapter.calls == 1 and msg.delivery_state == MessageDeliveryState.SENT


# ═══ D. Scheduled sends (PR-4) ═════════════════════════════════════════════════════════════════════════════

def test_control_scheduling_a_message_stores_it_and_sends_nothing_now(db, client, world):
    g, c = _conv(db, world.t.id)
    db.commit()
    with patch(DELAY) as send:
        r = client.post(f"/api/v1/conversations/{c.id}/messages",
                        json={"body": "Reminder for tomorrow", "scheduled_for": "2099-01-01T09:00:00Z"}, headers=_h(world.owner))
    assert r.status_code in (200, 201), r.text
    assert send.call_count == 0
    db.expire_all()
    stored = db.query(Message).filter_by(conversation_id=c.id, body="Reminder for tomorrow").one()
    assert stored.scheduled_for and stored.delivery_state is None


@PR(4, "a due scheduled message must be sent by a beat task; none exists today")
def test_a_sender_for_scheduled_messages_exists():
    import importlib.util
    assert importlib.util.find_spec("app.workers.tasks.scheduled_messages") is not None
