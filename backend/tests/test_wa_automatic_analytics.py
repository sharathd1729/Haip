"""WhatsApp overview, automatic part: team alerts and the playbooks' guest WhatsApps (wa_automatic_analytics)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.guest import Guest
from app.models.lead_workflow import PlaybookAction
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import lead_alert_sender
from app.services import wa_automatic_analytics as svc

# 25 Sep 2026, 15:30 IST
NOW = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _user(db, tid, role, name):
    u = User(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        name=name,
        email=f"{uuid.uuid4().hex[:8]}@t.com",
        hashed_password=get_password_hash("pw-123456789"),
        role=role,
        is_active=True,
    )
    db.add(u)
    db.commit()
    return u, create_access_token({"sub": u.id, "tenant_id": tid, "role": role.value})


def _act(
    db,
    tid,
    action,
    status,
    *,
    who=None,
    reason=None,
    wamid=None,
    delivery=None,
    key="new_lead_alert",
    message_id=None,
    at=NOW,
):
    a = PlaybookAction(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        playbook_key=key,
        action=action,
        status=status,
        reason=reason,
        recipient_user_id=who,
        wa_message_id=wamid,
        message_id=message_id,
        payload={"delivery": delivery} if delivery else {},
        created_at=at,
    )
    db.add(a)
    return a


def _guest_msg(db, tid, state, error=None):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Meera", phone="+919876500011")
    db.add(g)
    db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    m = Message(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        conversation_id=conv.id,
        direction=MessageDirection.OUTBOUND,
        channel=ChannelType.WHATSAPP,
        body="Sorry we missed your call",
        delivery_state=state,
        delivery_error=error,
    )
    db.add(m)
    db.flush()
    return m.id


@pytest.fixture()
def world(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    manager, _ = _user(db, tid, UserRole.MANAGER, "Jishanth")
    owner, _ = _user(db, tid, UserRole.OWNER, "Asha")
    # Team alerts: 3 WhatsApps to the manager (read, delivered, sent), 2 failed with 131049, 1 push; owner: 1 WhatsApp + 1 push.
    _act(db, tid, "staff_wa", "done", who=manager.id, wamid="w1", delivery="read")
    _act(db, tid, "staff_wa", "done", who=manager.id, wamid="w2", delivery="delivered", at=NOW - timedelta(hours=2))
    _act(db, tid, "staff_wa", "done", who=manager.id, wamid="w3", delivery="sent", key="sla_escalation")
    for _ in range(2):
        _act(
            db,
            tid,
            "staff_wa",
            "failed",
            who=manager.id,
            reason="Meta 131049: This message was not delivered to maintain healthy ecosystem engagement.",
        )
    _act(db, tid, "push", "done", who=manager.id)
    _act(db, tid, "staff_wa", "done", who=owner.id, wamid="w4", delivery="sent", at=NOW - timedelta(days=1))
    _act(db, tid, "push", "done", who=owner.id)
    _act(db, tid, "staff_wa", "held", who=owner.id)
    # Outside the 7-day period: not counted.
    _act(db, tid, "staff_wa", "done", who=owner.id, wamid="old", at=NOW - timedelta(days=20))
    # Guest playbook messages.
    _act(
        db,
        tid,
        "wa_template",
        "queued",
        key="missed_inbound_call",
        message_id=_guest_msg(db, tid, MessageDeliveryState.READ),
    )
    _act(
        db,
        tid,
        "wa_text",
        "queued",
        key="missed_inbound_call",
        message_id=_guest_msg(db, tid, MessageDeliveryState.DELIVERED),
    )
    _act(
        db,
        tid,
        "wa_template",
        "queued",
        key="unanswered_outbound",
        message_id=_guest_msg(db, tid, MessageDeliveryState.FAILED, error="131026: Message undeliverable"),
    )
    _act(
        db,
        tid,
        "wa_template",
        "skipped",
        key="unanswered_outbound",
        reason="template haip_tried_calling_v1 is not approved",
    )
    _act(
        db,
        tid,
        "wa_text",
        "skipped",
        key="missed_inbound_call",
        reason="template haip_tried_calling_v1 is not approved",
    )
    _act(
        db,
        tid,
        "wa_text",
        "queued",
        key="proposal_followup",
        message_id=_guest_msg(db, tid, MessageDeliveryState.QUEUED),
    )
    db.commit()
    return type("W", (), {"tid": tid, "manager": manager, "owner": owner})


def test_team_alert_totals_people_and_failures(db, world):
    d = svc.automatic(db, world.tid, days=7, now=NOW)
    assert (d["range"]["from"], d["range"]["to"]) == ("2026-09-19", "2026-09-25")
    wa = d["team_alerts"]["whatsapp"]
    assert (wa["sent"], wa["delivered"], wa["read"], wa["failed"], wa["waiting"]) == (4, 2, 1, 2, 1)
    assert wa["delivery_tracked"] is True and wa["delivery_rate"] == 50.0
    assert d["team_alerts"]["push"] == {"sent": 2, "failed": 0}
    people = {p["name"]: p for p in d["team_alerts"]["people"]}
    j = people["Jishanth"]
    assert (j["role"], j["received"], j["whatsapp"], j["push"], j["failed"]) == ("manager", 4, 3, 1, 2)
    assert j["last_at"].startswith("2026-09-25T10:00")
    assert (people["Asha"]["received"], people["Asha"]["failed"]) == (2, 0)
    [f] = d["team_alerts"]["failures"]
    assert f["count"] == 2 and f["reason"] == "Meta limited messages to this person; alerts fell back to the app."


def test_delivery_not_tracked_when_sent_alerts_have_no_message_id(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _act(db, tid, "staff_wa", "done")
    db.commit()
    wa = svc.automatic(db, tid, days=7, now=NOW)["team_alerts"]["whatsapp"]
    assert wa["sent"] == 1 and wa["delivery_tracked"] is False


def test_guest_messages_delivery_skips_and_failures(db, world):
    g = svc.automatic(db, world.tid, days=7, now=NOW)["guest_messages"]
    t = g["totals"]
    assert (t["sent"], t["delivered"], t["read"], t["failed"], t["skipped"], t["waiting"]) == (2, 2, 1, 1, 2, 1)
    by = {p["playbook"]: p for p in g["playbooks"]}
    assert by["missed_inbound_call"]["sent"] == 2 and by["missed_inbound_call"]["skipped"] == 1
    assert by["missed_inbound_call"]["name"].startswith("Missed call")
    assert by["unanswered_outbound"]["failed"] == 1
    assert g["skip_reasons"] == [{"reason": "template haip_tried_calling_v1 is not approved", "count": 2}]
    [f] = g["failures"]
    assert f["count"] == 1 and f["group"] != "other"


def test_other_workspaces_are_invisible(db, world):
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    d = svc.automatic(db, other.id, days=7, now=NOW)
    assert d["team_alerts"]["whatsapp"]["sent"] == 0 and d["team_alerts"]["people"] == []
    assert d["guest_messages"]["totals"]["sent"] == 0 and d["guest_messages"]["playbooks"] == []


def test_a_read_receipt_for_a_team_alert_moves_its_delivery_forward(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    a = _act(db, tid, "staff_wa", "done", wamid="wamid.X", delivery="sent")
    db.commit()
    assert lead_alert_sender.apply_status_callback(db, tid, {"id": "wamid.X", "status": "read"}) is True
    assert lead_alert_sender.apply_status_callback(db, tid, {"id": "wamid.X", "status": "delivered"}) is True
    db.refresh(a)
    assert a.payload["delivery"] == "read"


# ── Endpoint ────────────────────────────────────────────────────────────────


def test_endpoint_roles_and_cross_tenant(client, db, world, tenant_and_user):
    owner_h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    r = client.get("/api/v1/messaging/analytics/automatic", params={"days": 365}, headers=owner_h)
    assert r.status_code == 200
    body = r.json()
    assert body["range"]["days"] == 365 and "team_alerts" in body and "guest_messages" in body

    _, marketing = _user(db, world.tid, UserRole.MARKETING, "M")
    _, concierge = _user(db, world.tid, UserRole.CONCIERGE, "C")
    for tok in (marketing, concierge):
        assert (
            client.get("/api/v1/messaging/analytics/automatic", headers={"Authorization": f"Bearer {tok}"}).status_code
            == 403
        )

    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    _, other_owner = _user(db, other.id, UserRole.OWNER, "Other owner")
    r = client.get(
        "/api/v1/messaging/analytics/automatic",
        params={"days": 365},
        headers={"Authorization": f"Bearer {other_owner}"},
    )
    assert r.status_code == 200
    assert r.json()["team_alerts"]["people"] == [] and r.json()["guest_messages"]["totals"]["skipped"] == 0


def test_workflow_activity_filters_by_action(client, db, world, tenant_and_user):
    owner_h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    r = client.get("/api/v1/workflows/activity", params={"action": "staff_wa,push", "limit": 200}, headers=owner_h)
    assert r.status_code == 200
    assert {i["action"] for i in r.json()["items"]} == {"staff_wa", "push"}
