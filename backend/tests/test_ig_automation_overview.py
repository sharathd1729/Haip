"""Instagram automations dashboard (services/ig_automation_overview.py, GET /instagram/automations/overview) and the
"opened" tracking behind it (workers/tasks/process_instagram_seen.py).

Comment to booking for a period with the period before; top posts; posts and ads getting comments with no automation;
another app answering first; money only with revenue.read; workspaces never mix.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from app.models.automation import AutomationRule
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.ig_automation import IgAutomationEvent
from app.models.property import Stay
from app.models.tenant import Tenant
from app.services import ig_automation_overview as ov

NOW = datetime.now(timezone.utc)


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="Neelgiri", slug=f"n-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    return t


def _rule(db, tid, **tc):
    r = AutomationRule(id=str(uuid.uuid4()), tenant_id=tid, name="PRICE reel", trigger="ig_comment_received",
                       trigger_config={"keywords": ["price"], **tc}, action="send_instagram_quick_reply",
                       action_config={"message": "Hi"}, is_active=True, run_count=0)
    db.add(r)
    db.commit()
    return r


def _guest(db, tid):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Ananya")
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.INSTAGRAM)
    db.add_all([g, c])
    db.commit()
    return g, c


def _ev(db, tid, rule, kind, guest=None, media=None, detail=None):
    db.add(IgAutomationEvent(tenant_id=tid, rule_id=rule.id, guest_id=guest and guest.id, kind=kind, media_id=media,
                             detail=detail))


def _comment(db, tid, conv, media, ad=None):
    meta = {"source": "comment", "media_id": media, **({"media_ad_id": ad, "media_ad_title": "Monsoon ad"} if ad else {})}
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                   channel=ChannelType.INSTAGRAM, body="price", channel_message_id=f"comment_{uuid.uuid4().hex[:10]}",
                   channel_metadata=meta))


def _world(db):
    t = _tenant(db)
    r = _rule(db, t.id, scope="post", media_id="m1")
    g1, c1 = _guest(db, t.id)
    g2, c2 = _guest(db, t.id)
    for _ in range(3):
        _ev(db, t.id, r, "triggered", media="m1")
    _ev(db, t.id, r, "dm_sent", g1, "m1")
    _ev(db, t.id, r, "dm_sent", g2, "m1")
    _ev(db, t.id, r, "opened", g1)
    _ev(db, t.id, r, "clicked")
    _ev(db, t.id, r, "form_started", g1)
    _ev(db, t.id, r, "skipped", g2, detail="comment_already_answered")
    _ev(db, t.id, r, "dm_failed", g2, detail="Instagram 500")
    g1.lead_identified_at = NOW + timedelta(minutes=1)
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g1.id, property_id=str(uuid.uuid4()),
                check_in=date.today() + timedelta(days=20), check_out=date.today() + timedelta(days=22),
                status="confirmed", total_amount=50000, created_at=NOW + timedelta(minutes=2)))
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g1.id, property_id=str(uuid.uuid4()),
                check_in=date.today() + timedelta(days=30), check_out=date.today() + timedelta(days=31),
                status="cancelled", total_amount=99999, created_at=NOW + timedelta(minutes=3)))
    _comment(db, t.id, c1, "m1")
    _comment(db, t.id, c1, "m2")
    _comment(db, t.id, c2, "m2")
    _comment(db, t.id, c2, "m3", ad="ad9")
    db.commit()
    return t, r


def test_windows_compare_like_with_like():
    (f, t, s, e), (pf, pt, _, _) = ov.windows("last_7d")
    assert (t - f).days == 6 and pt == f - timedelta(days=1) and (pt - pf).days == 6
    (f, t, _, _), (pf, pt, _, _) = ov.windows("this_month")
    assert f.day == 1 and pf.day == 1 and pf.month != f.month and (pt - pf) <= (t - f)
    assert s < e


def test_the_period_from_comment_to_booking(db):
    t, r = _world(db)
    out = ov.overview(db, t.id, "last_7d", money=True)
    k = out["kpis"]
    assert (k["comments_answered"], k["dms_sent"], k["opened"], k["clicked"], k["forms_started"]) == (2, 2, 1, 1, 1)
    assert (k["leads"], k["bookings"], k["booked_amount"]) == (1, 1, 50000.0)      # the cancelled stay is left out
    assert out["previous_kpis"]["dms_sent"] == 0
    top = out["top_posts"][0]
    assert (top["media_id"], top["people"], top["opened"], top["leads"], top["bookings"]) == ("m1", 2, 1, 1, 1)
    assert [p["media_id"] for p in out["posts_without_automation"]] == ["m2"]          # m1 has a rule, m3 is an ad
    assert out["posts_without_automation"][0]["comments"] == 2
    kinds = {a["kind"]: a for a in out["alerts"]}
    assert kinds["ads_without_automation"]["count"] == 1 and kinds["other_app_answered_first"]["count"] == 1
    assert kinds["sends_failed"]["count"] == 1 and kinds["post_without_automation"]["media_id"] == "m2"
    assert out["opens_tracked"] is True
    assert [f["value"] for f in out["funnel"]] == [3, 2, 1, 1, 1, 1]


def test_money_is_null_not_zero_without_revenue_access(db):
    t, r = _world(db)
    out = ov.overview(db, t.id, "last_7d", money=False)
    assert out["money_restricted"] is True and out["kpis"]["booked_amount"] is None
    assert out["top_posts"][0]["booked_amount"] is None and out["kpis"]["bookings"] == 1


def test_an_any_post_rule_covers_every_post(db):
    t, r = _world(db)
    _rule(db, t.id, scope="any")
    out = ov.overview(db, t.id, "last_7d", money=True)
    assert out["posts_without_automation"] == []
    assert "ads_without_automation" not in {a["kind"] for a in out["alerts"]}


def test_workspaces_never_mix(db):
    t, r = _world(db)
    other = _tenant(db)
    out = ov.overview(db, other.id, "last_7d", money=True)
    assert out["kpis"]["dms_sent"] == 0 and out["top_posts"] == [] and out["posts_without_automation"] == []


def test_seen_marks_automation_dms_opened_once(db):
    from app.services import identity_service
    from app.workers.tasks.process_instagram_seen import record_seen

    t = _tenant(db)
    r = _rule(db, t.id, scope="any")
    g, c = _guest(db, t.id)
    identity_service.add_signal(db, t.id, g.id, "instagram_user_id", "igsid-7", source="test")
    db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction=MessageDirection.OUTBOUND,
                   channel=ChannelType.INSTAGRAM, body="Hi", sender_kind="automation",
                   channel_metadata={"automation_rule_id": r.id}, created_at=NOW - timedelta(minutes=5)))
    db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction=MessageDirection.OUTBOUND,
                   channel=ChannelType.INSTAGRAM, body="From staff", created_at=NOW - timedelta(minutes=4)))
    db.commit()
    assert record_seen(db, t.id, "igsid-7", NOW) == 1
    db.commit()
    assert record_seen(db, t.id, "igsid-7", NOW) == 0                     # once per automation and person
    assert record_seen(db, t.id, "unknown", NOW) == 0
    other = _tenant(db)
    assert record_seen(db, other.id, "igsid-7", NOW) == 0                 # another workspace's guest is never touched
    assert db.query(IgAutomationEvent).filter_by(tenant_id=t.id, kind="opened").count() == 1


def test_webhook_queues_a_seen_event(monkeypatch):
    from app.api.v1.endpoints import webhooks_instagram as wh
    from app.workers.tasks import process_instagram_seen as task

    queued = []
    monkeypatch.setattr(task.process_instagram_seen, "delay", lambda payload: queued.append(payload))
    wh._handle_messaging_event("1784", {"sender": {"id": "igsid"}, "recipient": {"id": "1784"},
                                        "timestamp": 1763200000000, "read": {"mid": "mid.1"}})
    assert queued == [{"ig_account_id": "1784", "sender_id": "igsid", "timestamp": 1763200000000}]


# ── endpoints ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def test_overview_endpoint_happy_path_and_bad_period(client, db, tenant_and_user):
    t = tenant_and_user["tenant"]
    r = _rule(db, t.id, scope="any")
    g, _ = _guest(db, t.id)
    _ev(db, t.id, r, "dm_sent", g, "m1")
    db.commit()
    res = client.get("/api/v1/instagram/automations/overview", params={"period": "last_7d"}, headers=_h(tenant_and_user))
    assert res.status_code == 200 and res.json()["kpis"]["dms_sent"] == 1
    assert client.get("/api/v1/instagram/automations/overview", params={"period": "forever"},
                      headers=_h(tenant_and_user)).status_code == 422
    stats = client.get("/api/v1/instagram/automations/stats", params={"period": "last_7d"}, headers=_h(tenant_and_user))
    assert stats.status_code == 200 and stats.json()["automations"][0]["dm_sent"] == 1
    assert client.get("/api/v1/instagram/automations/stats", params={"period": "x"},
                      headers=_h(tenant_and_user)).status_code == 422


def test_overview_needs_owner_or_manager(client, db, tenant_and_user):
    from app.core.security import create_access_token
    from app.models.user import User, UserRole

    t = tenant_and_user["tenant"]
    u = User(id=str(uuid.uuid4()), tenant_id=t.id, name="FOH", email=f"f{uuid.uuid4().hex[:6]}@x.in",
             hashed_password="x", role=UserRole.FOH, is_active=True)
    db.add(u)
    db.commit()
    h = {"Authorization": f"Bearer {create_access_token({'sub': u.id, 'tenant_id': t.id, 'role': u.role.value})}"}
    assert client.get("/api/v1/instagram/automations/overview", headers=h).status_code == 403


def test_overview_endpoint_stays_in_the_callers_workspace(client, db, tenant_and_user):
    other = _tenant(db)
    r = _rule(db, other.id, scope="any")
    g, _ = _guest(db, other.id)
    _ev(db, other.id, r, "dm_sent", g, "m1")
    db.commit()
    res = client.get("/api/v1/instagram/automations/overview", params={"period": "last_7d"}, headers=_h(tenant_and_user))
    assert res.status_code == 200 and res.json()["kpis"]["dms_sent"] == 0
