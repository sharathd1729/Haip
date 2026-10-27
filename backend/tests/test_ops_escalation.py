"""Escalation engine: alert, acknowledge, decline, escalate, quiet hours, exhaustion, resolve breach (ops_escalation_service)."""
from datetime import timedelta

from app.models.ops import OpsAlertSend, OpsEscalationEvent, OpsItem, OpsSettings
from app.models.user import UserRole
from app.services import ops_escalation_service as esc
from tests.ops_helpers import ist, prop, shift, staff, tenant, user

MON = 0
NOON = ist(2026, 10, 19, 12)


def _events(db, item):
    db.flush()
    return [e.event for e in db.query(OpsEscalationEvent).filter_by(item_id=item.id).order_by(OpsEscalationEvent.created_at).all()]


def _sends(db, item, step=None):
    db.flush()
    q = db.query(OpsAlertSend).filter_by(item_id=item.id)
    if step is not None:
        q = q.filter_by(step=step)
    return q.all()


def _a(dt):
    return esc._aware(dt)


def _delivered(db):
    """Stand-in for the Celery sender: every queued alert went out."""
    for s in db.query(OpsAlertSend).filter_by(status="queued").all():
        s.status = "sent"
    db.flush()


def _team(db):
    t = tenant(db)
    p = prop(db, t.id)
    tech = staff(db, t.id, "Tech", "maintenance")
    boss = staff(db, t.id, "Boss", "ops_manager")
    shift(db, t.id, tech.id, "maintenance", MON, 0, 24)
    shift(db, t.id, boss.id, "ops_manager", MON, 0, 24)
    owner = user(db, t.id, UserRole.OWNER, phone_number="+919845099999")
    return t, p, tech, boss, owner


def _new(db, t, p, severity="high", now=NOON):
    item, ids = esc.create_item(db, t.id, title="AC not working", severity=severity, duty="maintenance",
                                property_id=p.id, summary="Guest says AC stopped", now=now)
    db.commit()
    return item, ids


def test_create_alerts_on_shift_staff_with_whatsapp_template(db):
    t, p, tech, _, _ = _team(db)
    item, ids = _new(db, t, p)
    sends = _sends(db, item)
    assert [s.staff_id for s in sends] == [tech.id] and sends[0].channel == "whatsapp"
    assert sends[0].template == "ops_alert_v1" and sends[0].status == "queued" and ids == [sends[0].id]
    assert item.current_step == 0 and _a(item.ack_due_at) == NOON + timedelta(minutes=15)
    assert _events(db, item) == ["created", "alerted"]


def test_button_ack_acknowledges_and_starts_resolve_clock(db):
    t, p, tech, _, _ = _team(db)
    item, _ = _new(db, t, p)
    send = _sends(db, item)[0]
    later = NOON + timedelta(minutes=3)
    esc.handle_staff_inbound(db, t.id, tech, payload=esc.button_payload(send, "ack"), now=later)
    assert item.status == "acknowledged" and item.acknowledged_by_staff_id == tech.id
    assert _a(item.resolve_due_at) == later + timedelta(minutes=240) and item.ack_due_at is None


def test_button_with_wrong_nonce_or_wrong_staff_is_ignored(db):
    t, p, tech, boss, _ = _team(db)
    item, _ = _new(db, t, p)
    send = _sends(db, item)[0]
    esc.handle_staff_inbound(db, t.id, tech, payload=f"ops:ack:{send.id}:forged")
    esc.handle_staff_inbound(db, t.id, boss, payload=esc.button_payload(send, "ack"))   # not boss's alert
    assert item.status == "open"


def test_unacknowledged_item_escalates_to_next_step_on_tick(db):
    t, p, _, boss, _ = _team(db)
    item, _ = _new(db, t, p)
    _delivered(db)
    assert esc.tick(db, t.id, NOON + timedelta(minutes=10)) == []                       # still inside the window
    ids = esc.tick(db, t.id, NOON + timedelta(minutes=16))
    step1 = _sends(db, item, step=1)
    assert item.current_step == 1 and [s.staff_id for s in step1] == [boss.id]
    assert step1[0].template == "ops_escalation_v1" and set(ids) == {s.id for s in step1}
    assert _events(db, item)[-1] == "escalated"


def test_sole_recipient_decline_escalates_at_once(db):
    t, p, tech, boss, _ = _team(db)
    item, _ = _new(db, t, p)
    ids = esc.handle_staff_inbound(db, t.id, tech, payload=esc.button_payload(_sends(db, item)[0], "decline"), now=NOON)
    assert item.current_step == 1 and ids and _sends(db, item, step=1)[0].staff_id == boss.id
    assert "declined" in _events(db, item)


def test_empty_steps_are_roster_gaps_and_owner_gets_it(db):
    t = tenant(db)
    p = prop(db, t.id)
    owner = user(db, t.id, UserRole.OWNER, phone_number="+919845011111")
    item, ids = esc.create_item(db, t.id, title="No water", severity="critical", duty="maintenance", property_id=p.id, now=NOON)
    db.commit()
    events = _events(db, item)
    assert events.count("roster_gap") == 3 and events[-1] == "escalated"                 # steps 0,1,2 empty (no manager either)
    sends = _sends(db, item)
    assert {s.channel for s in sends} == {"whatsapp", "push"} and all(s.user_id == owner.id for s in sends)
    assert len(ids) == 2


def test_quiet_hours_hold_normal_items_but_not_critical(db):
    t, p, _, _, _ = _team(db)
    late = ist(2026, 10, 19, 23)
    normal, ids = _new(db, t, p, severity="normal", now=late)
    assert ids == [] and _a(normal.dispatch_after) == ist(2026, 10, 20, 7) and normal.dispatched_step is None
    assert esc.tick(db, t.id, ist(2026, 10, 20, 6, 59)) == []
    critical, cids = _new(db, t, p, severity="critical", now=late)
    assert cids
    _delivered(db)
    out = esc.tick(db, t.id, ist(2026, 10, 20, 7, 1))
    assert normal.dispatched_step is not None and any(s.id in out for s in _sends(db, normal))


def test_chain_exhausts_after_repeats_and_stays_open(db):
    t, p, _, _, _ = _team(db)
    item, _ = _new(db, t, p, severity="critical")
    now = NOON
    for _ in range(12):
        now += timedelta(minutes=6)
        esc.tick(db, t.id, now)
    assert item.escalation_exhausted and item.status == "open" and item.repeat_count == esc.MAX_REPEATS
    assert "exhausted" in _events(db, item)


def test_resolve_breach_alerts_managers_once(db):
    t, p, tech, _, owner = _team(db)
    item, _ = _new(db, t, p)
    esc.acknowledge(db, item, staff_id=tech.id, now=NOON)
    ids = esc.tick(db, t.id, NOON + timedelta(minutes=241))
    breach = _sends(db, item, step=esc.RESOLVE_BREACH_STEP)
    assert ids and item.resolve_breached_at is not None and {s.user_id for s in breach if s.user_id} == {owner.id}
    _delivered(db)
    assert esc.tick(db, t.id, NOON + timedelta(minutes=300)) == []                       # only once


def test_resolve_and_cancel_are_final(db):
    t, p, tech, _, owner = _team(db)
    item, _ = _new(db, t, p)
    _delivered(db)
    assert esc.resolve(db, item, staff_id=tech.id, note="Reset the breaker")
    assert not esc.resolve(db, item, staff_id=tech.id) and not esc.cancel(db, item, user_id=owner.id)
    assert item.acknowledged_at is not None and esc.tick(db, t.id, NOON + timedelta(days=1)) == []


def test_tenant_sla_override_and_alerts_off(db):
    t, p, tech, _, _ = _team(db)
    db.add(OpsSettings(tenant_id=t.id, sla={"high": [3, 30]}, alerts_enabled=False))
    db.commit()
    item, ids = _new(db, t, p)
    assert _a(item.ack_due_at) == NOON + timedelta(minutes=3)
    sends = _sends(db, item, step=0)
    assert sends[0].status == "skipped" and "off" in sends[0].error              # tech has no login: no push either
    assert "undeliverable" in _events(db, item)


def test_tick_is_tenant_isolated(db):
    t1, p1, _, _, _ = _team(db)
    t2 = tenant(db)
    item, _ = _new(db, t1, p1)
    assert esc.tick(db, t2.id, NOON + timedelta(hours=2)) == []
    assert item.current_step == 0
    assert db.query(OpsItem).filter_by(tenant_id=t2.id).count() == 0
