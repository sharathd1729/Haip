"""Guest ops tickets (services/guest_ops_tickets.py): a guest's in-stay problem and a booking's service request become ONE
ops item, alerted through the roster; it closes only on the guest's YES (or after 24 h), a NO reopens and escalates."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.models.agent_consult import AgentConsult
from app.models.audit_event import AuditEvent
from app.models.conversation import Conversation, Message
from app.models.ops import OpsAlertSend, OpsEscalationEvent, OpsItem
from app.models.property import Property, Stay
from app.models.stay_finance import StayServiceRequest
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import booking_agenda_service
from app.services import guest_ops_tickets as got
from app.services import ops_escalation_service as esc
from tests.conftest import seed_capabilities
from tests.ops_helpers import shift, staff
from tests.ops_helpers import tenant as ops_tenant
from tests.test_increment1_defect_specs import _h, _tenant, _user
from tests.workers.test_agent_consult_flow import _draft, add_inbound, run_turn, setup_thread


@pytest.fixture(autouse=True)
def _no_celery():
    with (
        patch("app.workers.tasks.ops_escalation.queue_delivery") as q,
        patch("app.api.v1.endpoints.ops.queue_delivery"),
        patch("app.api.v1.endpoints.booking_extras.queue_delivery"),
        patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"),
    ):
        yield q


def _live(db, t, g, *, days_in=-1, days_out=1, status="confirmed"):
    today = booking_agenda_service.tenant_today(db, t.id)
    p = Property(id=str(uuid.uuid4()), tenant_id=t.id, name="Ratha 1", slug=f"p-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(p)
    db.flush()
    s = Stay(
        id=str(uuid.uuid4()),
        tenant_id=t.id,
        guest_id=g.id,
        property_id=p.id,
        check_in=today + timedelta(days=days_in),
        check_out=today + timedelta(days=days_out),
        status=status,
    )
    db.add(s)
    db.commit()
    return p, s


def _tech(db, t, p, duty="maintenance"):
    tech = staff(db, t.id, "Tech", duty)
    for day in range(7):
        shift(db, t.id, tech.id, duty, day, 0, 24)
    return tech


def _turn(db, t, c, m, **kw):
    """run_turn closes the session; hand back fresh tenant + conversation rows."""
    t_id, c_id = t.id, c.id
    sent, push = run_turn(db, t, c, m, **kw)
    return sent, db.get(Tenant, t_id), db.get(Conversation, c_id)


def _items(db, t):
    db.flush()
    return db.query(OpsItem).filter_by(tenant_id=t.id).all()


def _events(db, item):
    db.flush()
    return [
        e.event for e in db.query(OpsEscalationEvent).filter_by(item_id=item.id).order_by(OpsEscalationEvent.created_at)
    ]


# ── Concierge ─────────────────────────────────────────────────────────────────


def test_in_stay_problem_opens_one_ticket_alerts_the_roster_and_tells_the_guest_honestly(db):
    t, g, c, m = setup_thread(db, "The AC in the caravan is not working at all")
    p, s = _live(db, t, g)
    tech = _tech(db, t, p)
    ids = (s.id, g.id, c.id, f"msg:{m.id}", tech.id, t.id)
    sent, _ = run_turn(
        db,
        t,
        c,
        m,
        reply="A technician will be there in 10 minutes!",
        intent={"intent": "complaint", "stay_issue": "maintenance"},
    )
    t, c = db.get(Tenant, ids[5]), db.get(Conversation, ids[2])
    (item,) = _items(db, t)
    assert (item.source, item.category, item.severity, item.duty) == (
        "guest_chat",
        "maintenance",
        "high",
        "maintenance",
    )
    assert (item.stay_id, item.guest_id, item.conversation_id, item.source_ref) == ids[:4]
    assert item.title == "Ratha 1: Guest reports a maintenance problem" and "AC" in item.summary
    alert = db.query(OpsAlertSend).filter_by(item_id=item.id, staff_id=ids[4], channel="whatsapp").one()
    assert alert.status == "queued" and alert.step == 0
    draft = _draft(db, c)
    assert (
        draft.sent_autonomously is False and "ops ticket" in draft.ai_needs_human_reason
    )  # the "10 minutes" guess is held
    ack = db.query(Message).filter_by(conversation_id=c.id, sender_kind="ai_holding").one()
    assert sent == [ack.id] and "alerted them now" in ack.body and "minute" not in ack.body
    assert db.query(AgentConsult).filter_by(tenant_id=t.id).count() == 0  # not an ask-a-manager
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="ops.item.guest_ticket_opened").count() == 1


def test_no_live_stay_means_no_ticket_and_the_consult_path_runs(db):
    t, g, c, m = setup_thread(db, "This is unacceptable, the service was horrible")
    _live(db, t, g, days_in=5, days_out=7)  # a future booking is not a live stay
    _, t, c = _turn(db, t, c, m, reply="Sorry!", intent={"intent": "complaint", "stay_issue": "complaint"})
    assert _items(db, t) == []
    consult = db.query(AgentConsult).filter_by(tenant_id=t.id).one()
    assert "complaint" in consult.reason_codes


def test_a_sales_question_mid_stay_still_goes_to_a_consult(db):
    t, g, c, m = setup_thread(db, "Any discount if we extend by two days?")
    _live(db, t, g)
    _, t, c = _turn(db, t, c, m, reply="Sure!", intent={"intent": "price_quote", "stay_issue": "none"})
    assert _items(db, t) == []
    assert "discount_request" in db.query(AgentConsult).filter_by(tenant_id=t.id).one().reason_codes


def test_in_stay_complaint_with_a_discount_ask_keeps_only_the_sales_reason_on_the_consult(db):
    t, g, c, m = setup_thread(db, "The room is filthy, unacceptable. I want a discount")
    _live(db, t, g)
    _, t, c = _turn(db, t, c, m, reply="Sorry!", intent={"intent": "complaint", "stay_issue": "housekeeping"})
    assert len(_items(db, t)) == 1
    consult = db.query(AgentConsult).filter_by(tenant_id=t.id).one()
    assert consult.reason_codes == ["discount_request"]


def test_the_same_message_twice_and_a_follow_up_never_duplicate_the_ticket(db):
    t, g, c, m = setup_thread(db, "No hot water in the shower")
    _live(db, t, g)
    intent = {"intent": "complaint", "stay_issue": "maintenance"}
    g_id, m_id = g.id, m.id
    _, t, c = _turn(db, t, c, m, intent=intent)
    item = _items(db, t)[0]
    item_id = item.id
    assert (
        got.open_for_chat(
            db,
            t,
            c,
            g_id,
            message_id=m_id,
            burst_text="No hot water",
            details={"stay_issue": "maintenance"},
            escalation=None,
        ).created
        is False
    )
    m2 = add_inbound(db, t, c, "Still no hot water, please help")
    _, t, c = _turn(db, t, c, m2, intent=intent)
    item = db.get(OpsItem, item_id)
    assert [i.id for i in _items(db, t)] == [item.id]
    assert _events(db, item).count("guest_message") == 1
    acks = db.query(Message).filter_by(conversation_id=c.id, sender_kind="ai_holding").all()
    assert len(acks) == 1  # never two holding lines in a row


def test_safety_is_critical_and_alerts_the_owner_at_once_even_if_the_model_says_none(db):
    t, g, c, m = setup_thread(db, "There was an accident, someone is injured")
    _live(db, t, g)
    owner_id = _user(db, t.id, UserRole.OWNER).id
    sent, t, c = _turn(db, t, c, m, intent={"intent": "general", "stay_issue": "none"})
    (item,) = _items(db, t)
    assert item.severity == "critical" and item.category == "safety"
    assert "owner_notified" in _events(db, item)
    assert db.query(OpsAlertSend).filter_by(item_id=item.id, step=esc.OWNER_COPY_STEP, user_id=owner_id).count() >= 1
    assert "112" in db.query(Message).filter_by(conversation_id=c.id, sender_kind="ai_holding").one().body


def test_draft_mode_opens_the_ticket_but_sends_nothing_on_its_own(db):
    t, g, c, m = setup_thread(db, "The fridge stopped working", mode="shadow")
    _live(db, t, g)
    sent, t, c = _turn(db, t, c, m, intent={"intent": "complaint", "stay_issue": "maintenance"})
    assert len(_items(db, t)) == 1 and sent == []


# ── Close on the guest's word ─────────────────────────────────────────────────


def _ticket(db, t, g, c, s, category="maintenance"):
    item, _ = esc.create_item(
        db,
        t.id,
        title="Ratha 1: Guest reports a maintenance problem",
        severity="high",
        duty="maintenance",
        category=category,
        property_id=s.property_id,
        stay_id=s.id,
        guest_id=g.id,
        conversation_id=c.id,
        source="guest_chat",
        source_ref=f"msg:{uuid.uuid4()}",
    )
    db.commit()
    return item


def _seeded(db):
    t = ops_tenant(db)
    seed_capabilities(db, t.id)
    return t


def test_resolve_asks_the_guest_and_yes_closes_it(client, db):
    t, g, c, m = setup_thread(db, "AC broken", tenant=_seeded(db))
    p, s = _live(db, t, g)
    item = _ticket(db, t, g, c, s)
    foh = _user(db, t.id, UserRole.FOH)
    r = client.post(f"/api/v1/ops/items/{item.id}/resolve", json={"note": "Gas refilled"}, headers=_h(foh))
    assert r.status_code == 200 and r.json()["status"] == "confirming"
    ask = db.query(Message).filter(Message.conversation_id == c.id, Message.idempotency_key.like("opi:%")).one()
    assert "YES or NO" in ask.body and ask.sender_kind == "system"
    assert client.post(f"/api/v1/ops/items/{item.id}/resolve", json={}, headers=_h(foh)).status_code == 409
    assert got.on_guest_message(db, t.id, g.id, "Yes it's working now, thanks") == "confirmed"
    db.refresh(item)
    assert item.status == "resolved" and "guest_confirmed" in _events(db, item)
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="ops.item.guest_confirmed").count() == 1


def test_no_reopens_and_escalates_one_level(db):
    t, g, c, m = setup_thread(db, "AC broken")
    p, s = _live(db, t, g)
    _tech(db, t, p)
    _user(db, t.id, UserRole.OWNER)  # the chain's last step: someone to escalate to
    item = _ticket(db, t, g, c, s)
    step = item.current_step
    esc.resolve(db, item, note="fixed")
    db.commit()
    assert got.ask_confirmation(db, item) == "asked"
    assert got.on_guest_message(db, t.id, g.id, "No, still not cooling") == "reopened"
    db.refresh(item)
    assert item.status == "open" and item.resolved_at is None and item.current_step > step
    assert "reopened" in _events(db, item)
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="ops.item.guest_reopened").count() == 1


def test_no_window_closes_at_once_and_no_reply_times_out(db):
    t, g, c, m = setup_thread(db, "AC broken", inbound_at=datetime.now(UTC) - timedelta(days=2))
    p, s = _live(db, t, g)
    item = _ticket(db, t, g, c, s)
    esc.resolve(db, item)
    db.commit()
    assert got.ask_confirmation(db, item) == "closed" and item.status == "resolved"  # window closed: cannot ask

    c2 = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=c.channel, is_open=False)
    db.add(c2)
    db.commit()
    other = _ticket(db, t, g, c2, s, category="food")
    esc.resolve(db, other)
    other.resolved_at = datetime.now(UTC) - got.GUEST_CONFIRM_TIMEOUT - timedelta(minutes=1)
    db.commit()
    assert got.expire_confirmations(db, t.id) == 1
    assert other.status == "resolved" and "closed" in _events(db, other)


def test_guest_answer_reads_only_a_clear_yes_or_no():
    assert got.guest_answer("yes") == "yes" and got.guest_answer("👍") == "yes"
    assert got.guest_answer("no problem, all good now") == "yes"
    assert got.guest_answer("not working") == "no" and got.guest_answer("still the same") == "no"
    assert got.guest_answer("Can we also book a cab to the airport tomorrow at 6 in the morning please?") is None
    assert got.guest_answer("what time is checkout") is None


# ── Service requests ──────────────────────────────────────────────────────────


def _booking(db, t, g, **kw):
    p, s = _live(db, t, g, **kw)
    return p, s, f"/api/v1/bookings/{s.id}/service-requests"


def test_service_request_opens_its_ticket_and_done_waits_for_the_guest(client, db):
    t, g, c, m = setup_thread(db, "hi")
    _, s, base = _booking(db, t, g)
    mgr = _user(db, t.id, UserRole.MANAGER)
    assert client.post(base, json={"title": "Extra bed"}, headers=_h(mgr)).status_code == 201
    req = db.query(StayServiceRequest).filter_by(stay_id=s.id).one()
    (item,) = _items(db, t)
    assert (item.source, item.service_request_id, item.source_ref, item.category) == (
        "service_request",
        req.id,
        f"ssr:{req.id}",
        "service_request",
    )
    assert item.dispatch_after is None or item.dispatched_step is None  # live stay: alerted now (or quiet hours)
    assert got.link_service_request(db, t.id, s, req) == []  # never a second ticket

    assert client.patch(f"{base}/{req.id}", json={"status": "done"}, headers=_h(mgr)).status_code == 200
    db.refresh(item)
    assert item.status == "confirming"
    assert got.on_guest_message(db, t.id, g.id, "yes sorted") == "confirmed"
    db.refresh(item)
    assert item.status == "resolved"

    assert client.delete(f"{base}/{req.id}", headers=_h(mgr)).status_code == 200
    db.refresh(item)
    assert item.status == "resolved"  # a closed ticket stays closed


def test_a_guest_no_reopens_the_service_request(client, db):
    t, g, c, m = setup_thread(db, "hi")
    _, s, base = _booking(db, t, g)
    mgr = _user(db, t.id, UserRole.MANAGER)
    client.post(base, json={"title": "Extra towels"}, headers=_h(mgr))
    req = db.query(StayServiceRequest).filter_by(stay_id=s.id).one()
    client.patch(f"{base}/{req.id}", json={"status": "done"}, headers=_h(mgr))
    assert got.on_guest_message(db, t.id, g.id, "no, nobody came") == "reopened"
    db.refresh(req)
    assert req.status == "open"


def test_a_future_request_is_held_until_its_day_and_removing_it_cancels_the_ticket(client, db):
    t, g, c, m = setup_thread(db, "hi")
    _, s, base = _booking(db, t, g, days_in=10, days_out=12)
    mgr = _user(db, t.id, UserRole.MANAGER)
    client.post(base, json={"title": "Cab from the airport"}, headers=_h(mgr))
    (item,) = _items(db, t)
    assert item.dispatched_step is None and esc._aware(item.dispatch_after) > datetime.now(UTC) + timedelta(days=8)
    assert db.query(OpsAlertSend).filter_by(item_id=item.id).count() == 0
    req = db.query(StayServiceRequest).filter_by(stay_id=s.id).one()
    assert client.delete(f"{base}/{req.id}", headers=_h(mgr)).status_code == 200
    db.refresh(item)
    assert item.status == "cancelled"


def test_service_request_endpoints_role_and_cross_tenant(client, db):
    t, g, c, m = setup_thread(db, "hi")
    _, s, base = _booking(db, t, g)
    mkt = _user(db, t.id, UserRole.MARKETING)
    assert client.post(base, json={"title": "x"}, headers=_h(mkt)).status_code == 403
    other = _tenant(db)
    stranger = _user(db, other.id, UserRole.OWNER)
    assert client.post(base, json={"title": "x"}, headers=_h(stranger)).status_code == 404
    assert _items(db, t) == []


# ── Tenant isolation ──────────────────────────────────────────────────────────


def test_tenant_isolation(client, db):
    t, g, c, m = setup_thread(db, "AC broken", tenant=_seeded(db))
    p, s = _live(db, t, g)
    item = _ticket(db, t, g, c, s)
    esc.resolve(db, item)
    db.commit()
    other = _seeded(db)
    assert got.live_stay(db, other.id, g.id) is None
    assert got.on_guest_message(db, other.id, g.id, "yes") is None
    db.refresh(item)
    assert item.status == "confirming"
    stranger = _user(db, other.id, UserRole.OWNER)
    assert client.post(f"/api/v1/ops/items/{item.id}/resolve", json={}, headers=_h(stranger)).status_code == 404
    assert (
        client.post(
            f"/api/v1/ops/items/{item.id}/resolve", json={}, headers=_h(_user(db, t.id, UserRole.MARKETING))
        ).status_code
        == 403
    )


@pytest.mark.parametrize("business_type", ["caravan", "villa"])
def test_ops_today_shows_guest_tickets_but_not_ones_held_for_a_later_day(db, business_type):
    from app.services import ops_today_service

    t, g, c, m = setup_thread(db, "hi")
    t.business_type = business_type
    p, s = _live(db, t, g)
    now = _ticket(db, t, g, c, s)
    later, _ = esc.create_item(
        db,
        t.id,
        title="Ratha 1: Cab",
        severity="normal",
        duty="front_desk",
        property_id=p.id,
        stay_id=s.id,
        guest_id=g.id,
        source="service_request",
        dispatch_after=datetime.now(UTC) + timedelta(days=5),
    )
    db.commit()
    keys = {n.get("key") for n in ops_today_service.build(db, t.id)["needs"]}
    assert f"item:{now.id}" in keys and f"item:{later.id}" not in keys
