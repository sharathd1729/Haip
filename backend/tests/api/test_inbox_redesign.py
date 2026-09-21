"""Inbox redesign backend: guest channel icons, server-side filter chips
(needs reply / unassigned / mine) with counts, and pausing the AI for one
conversation."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.services import inbox_service

NOW = datetime.now(timezone.utc)


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _uid(tu):
    u = tu["user"]
    return u["id"] if isinstance(u, dict) else u.id


def _auth(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _guest(db, tenant_id, name="Guest"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone=f"+9199{uuid.uuid4().int % 10**8:08d}")
    db.add(g); db.flush(); return g


def _conv(db, tenant_id, guest, channel=ChannelType.INSTAGRAM, assigned_to=None, is_open=True):
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=channel,
                     is_open=is_open, assigned_to=assigned_to, last_message_at=NOW.isoformat())
    db.add(c); db.flush(); return c


def _msg(db, conv, direction, minutes_ago, **kw):
    db.add(Message(id=str(uuid.uuid4()), tenant_id=conv.tenant_id, conversation_id=conv.id,
                   direction=direction, channel=conv.channel, body="hi",
                   created_at=NOW - timedelta(minutes=minutes_ago), **kw))
    db.flush()


def _call(db, tenant_id, guest):
    db.add(Call(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, ivr_provider="vobiz",
                ivr_call_id=f"c-{uuid.uuid4().hex[:8]}", direction=CallDirection.OUTBOUND,
                from_number="+918000000000", to_number=guest.phone, duration_seconds=120))
    db.flush()


# ── guest channel icons ───────────────────────────────────────────────────────

def test_guest_channels_combine_conversations_and_calls(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    multi = _guest(db, tid, "Multi")
    _conv(db, tid, multi, ChannelType.INSTAGRAM)
    _call(db, tid, multi)
    wa_only = _guest(db, tid, "WA")
    _conv(db, tid, wa_only, ChannelType.WHATSAPP)
    db.commit()

    got = inbox_service.guest_channels(db, tid, [multi.id, wa_only.id])
    assert got[multi.id] == ["instagram", "call"]
    assert got[wa_only.id] == ["whatsapp"]


def test_list_returns_guest_channels_and_ai_flag(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g = _guest(db, tid)
    c = _conv(db, tid, g, ChannelType.INSTAGRAM)
    _call(db, tid, g)
    c.ai_mode = "off"
    db.commit()

    rows = client.get("/api/v1/conversations", headers=_auth(tenant_and_user)).json()
    row = next(r for r in rows if r["id"] == c.id)
    assert row["guest_channels"] == ["instagram", "call"]
    assert row["ai_enabled"] is False


# ── filter chips ──────────────────────────────────────────────────────────────

def _seed_views(db, tid, me):
    waiting = _conv(db, tid, _guest(db, tid, "Waiting"))
    _msg(db, waiting, "inbound", 5)

    replied = _conv(db, tid, _guest(db, tid, "Replied"))
    _msg(db, replied, "inbound", 10)
    _msg(db, replied, "outbound", 9)

    only_draft = _conv(db, tid, _guest(db, tid, "Draft only"))
    _msg(db, only_draft, "inbound", 10)
    _msg(db, only_draft, "outbound", 9, is_ai_generated=True, was_approved=None)

    mine = _conv(db, tid, _guest(db, tid, "Mine"), assigned_to=me)
    _msg(db, mine, "inbound", 20)
    _msg(db, mine, "outbound", 19, is_ai_generated=True, was_approved=True)

    closed = _conv(db, tid, _guest(db, tid, "Closed"), is_open=False)
    _msg(db, closed, "inbound", 3)
    db.commit()
    return waiting, replied, only_draft, mine, closed


def test_needs_reply_view(client, db, tenant_and_user):
    tid, me = _tid(tenant_and_user), _uid(tenant_and_user)
    waiting, replied, only_draft, mine, closed = _seed_views(db, tid, me)

    ids = {r["id"] for r in client.get("/api/v1/conversations?view=needs_reply", headers=_auth(tenant_and_user)).json()}
    # An unsent AI draft is not a reply; a closed thread isn't in the queue.
    assert ids == {waiting.id, only_draft.id}


def test_mine_and_unassigned_views(client, db, tenant_and_user):
    tid, me = _tid(tenant_and_user), _uid(tenant_and_user)
    waiting, replied, only_draft, mine, closed = _seed_views(db, tid, me)
    h = _auth(tenant_and_user)
    assert {r["id"] for r in client.get("/api/v1/conversations?view=mine", headers=h).json()} == {mine.id}
    unassigned = {r["id"] for r in client.get("/api/v1/conversations?view=unassigned", headers=h).json()}
    assert unassigned == {waiting.id, replied.id, only_draft.id}


def test_counts_match_views_and_ignore_other_tenants(client, db, tenant_and_user):
    tid, me = _tid(tenant_and_user), _uid(tenant_and_user)
    _seed_views(db, tid, me)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other); db.flush()
    oc = _conv(db, other.id, _guest(db, other.id))
    _msg(db, oc, "inbound", 1)
    db.commit()

    res = client.get("/api/v1/conversations/counts", headers=_auth(tenant_and_user))
    assert res.status_code == 200
    assert res.json() == {"needs_reply": 2, "unassigned": 3, "mine": 1}


def test_invalid_view_rejected(client, tenant_and_user):
    res = client.get("/api/v1/conversations?view=everything", headers=_auth(tenant_and_user))
    assert res.status_code == 422


def test_counts_require_auth(client):
    assert client.get("/api/v1/conversations/counts").status_code in (401, 403)


# ── pause AI for one guest ────────────────────────────────────────────────────

def test_ai_toggle_round_trip(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _conv(db, tid, _guest(db, tid))
    db.commit()
    h = _auth(tenant_and_user)

    res = client.patch(f"/api/v1/conversations/{c.id}", json={"ai_enabled": False}, headers=h)
    assert res.status_code == 200 and res.json()["ai_enabled"] is False
    db.refresh(c)
    assert c.ai_mode == "off"

    from app.services.ai_mode_service import resolve_mode
    assert resolve_mode(None, c) == "off"

    res = client.patch(f"/api/v1/conversations/{c.id}", json={"ai_enabled": True}, headers=h)
    assert res.json()["ai_enabled"] is True
    db.refresh(c)
    assert c.ai_mode != "off"


def test_ai_toggle_rejects_non_boolean(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    c = _conv(db, tid, _guest(db, tid))
    db.commit()
    res = client.patch(f"/api/v1/conversations/{c.id}", json={"ai_enabled": "no"}, headers=_auth(tenant_and_user))
    assert res.status_code == 422


def test_ai_toggle_cross_tenant_404(client, db, tenant_and_user):
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other); db.flush()
    oc = _conv(db, other.id, _guest(db, other.id))
    db.commit()
    res = client.patch(f"/api/v1/conversations/{oc.id}", json={"ai_enabled": False}, headers=_auth(tenant_and_user))
    assert res.status_code == 404


def test_detail_carries_channels_ai_flag_and_owner(client, db, tenant_and_user):
    tid, me = _tid(tenant_and_user), _uid(tenant_and_user)
    g = _guest(db, tid)
    c = _conv(db, tid, g, ChannelType.WHATSAPP, assigned_to=me)
    _conv(db, tid, g, ChannelType.INSTAGRAM)
    db.commit()
    body = client.get(f"/api/v1/conversations/{c.id}", headers=_auth(tenant_and_user)).json()
    assert body["guest_channels"] == ["instagram", "whatsapp"]
    assert body["ai_enabled"] is True
    assert body["assigned_to"] == me
