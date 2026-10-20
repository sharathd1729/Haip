"""GET /dashboard/impact/since-haip -- the "Since HAIP" card on the Owner Command Center.

Pinned: owner and manager see it, other roles are refused; both windows have the same length; every "before" figure says
where it came from and an empty baseline is "no data" with no change (never -100%); bookings need bookings.read and money
revenue.read (``{"restricted": true}``, the amounts absent); another workspace's numbers never show.
The reply-time SQL is PostgreSQL-only (message_metrics.chat_response_by_agent_source, own tests), so on SQLite it is replaced
by a fixed answer; on PostgreSQL the real query runs and the last test checks it end to end.
"""
import json
import os
import uuid
from datetime import timedelta

import pytest

from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.capability import RoleCapability
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.property import Property, Stay
from app.models.user import UserRole
from app.services import impact_since
from app.services.date_presets import today_ist
from tests.api.test_impact import _at, _go_live, _tenant, _user, world  # noqa: F401  (world is a fixture)

URL = "/api/v1/dashboard/impact/since-haip"
SQLITE = "sqlite" in os.environ.get("DATABASE_URL", "sqlite")
_EMPTY = {"by_agent": [], "by_source": {"personal_whatsapp": None, "whatsapp_cloud": None, "instagram": None}, "all": None}


@pytest.fixture(autouse=True)
def _replies(monkeypatch):
    if SQLITE:
        monkeypatch.setattr(impact_since, "chat_response_by_agent_source", lambda *a, **k: _EMPTY)


def _tile(view, key):
    return next(t for t in view["tiles"] if t["key"] == key)


def _stay_before_go_live(db, world, days_ago=25, amount=50000, source="google_calendar"):
    t = world["t"]
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Calendar guest")
    db.add(g); db.flush()
    prop = db.query(Property).filter_by(tenant_id=t.id).first()
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, property_id=prop.id, check_in=today_ist() + timedelta(days=40),
                check_out=today_ist() + timedelta(days=42), status="confirmed", total_amount=amount, channel_source=source,
                created_at=_at(days_ago)))
    db.commit()


def test_owner_sees_equal_windows_sources_and_no_change_against_nothing(client, db, world):
    _stay_before_go_live(db, world)
    msg = db.query(Message).filter_by(tenant_id=world["t"].id).first()
    db.add(AIDraftOutcome(tenant_id=world["t"].id, draft_message_id=msg.id, outcome="sent_edited", actor_user_id=world["owner"].id,
                          created_at=_at(3)))
    db.commit()
    assert _go_live(client, world["h_owner"], days_ago=20, window=30).status_code == 200
    r = client.get(URL, headers=world["h_owner"])
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["needs_go_live"] is False and v["can_edit"] is True
    assert v["windows"]["with"]["days"] == 21 and v["windows"]["before"]["days"] == 21          # same length, always
    assert v["windows"]["before"]["to"] == (today_ist() - timedelta(days=21)).isoformat()

    leads = _tile(v, "leads")
    assert leads["with"]["value"] == 1 and leads["before"]["value"] == 0
    assert leads["before"]["has_data"] is False and leads["change"] is None and leads["before"]["source"]

    bookings = _tile(v, "bookings")
    assert bookings["before"]["value"] == 1 and bookings["with"]["value"] == 1
    assert "1 from the shared calendar" in bookings["before"]["source"]
    assert bookings["change"] == {"kind": "pct", "value": 0.0, "better": None}

    value = _tile(v, "booked_value")
    assert value["before"]["value"] == 50000 and value["with"]["value"] == 87654
    assert value["change"]["better"] is True

    drafts = _tile(v, "ai_drafts_sent")
    assert drafts["with"]["value"] == 1 and drafts["before"]["has_data"] is False and drafts["change"] is None
    reply = _tile(v, "first_reply_minutes")
    assert reply["lower_is_better"] is True and reply["definition"]
    if SQLITE:
        assert reply["before"]["has_data"] is False and reply["with"]["value"] is None and reply["change"] is None


def test_without_a_go_live_date_the_card_asks_for_one(client, world):
    v = client.get(URL, headers=world["h_manager"]).json()
    assert v["needs_go_live"] is True and v["can_edit"] is False and "tiles" not in v


def test_other_roles_are_refused(client, world):
    _go_live(client, world["h_owner"])
    assert client.get(URL, headers=world["h_concierge"]).status_code == 403


def test_another_workspace_sees_only_its_own_numbers(client, db, world):
    _go_live(client, world["h_owner"])
    other = _tenant(db, "Other")
    _, h_other = _user(db, other.id, UserRole.OWNER)
    assert client.get(URL, headers=h_other).json()["needs_go_live"] is True        # A's go-live date is not B's
    _go_live(client, h_other)
    v = client.get(URL, headers=h_other).json()
    assert _tile(v, "leads")["with"]["value"] == 0 and _tile(v, "bookings")["with"]["value"] == 0
    assert _tile(v, "booked_value")["with"]["value"] == 0
    assert "87654" not in json.dumps(v)


def test_bookings_and_money_need_their_capabilities(client, db, world):
    _stay_before_go_live(db, world, amount=55555)
    _go_live(client, world["h_owner"])
    db.query(RoleCapability).filter(RoleCapability.tenant_id == world["t"].id, RoleCapability.role == "manager",
                                    RoleCapability.capability_key.in_(["revenue.read", "bookings.read"])).update(
        {"allowed": False}, synchronize_session=False)
    db.commit()
    from app.core.cache import _rdel      # the capability cache (Redis, when running) may hold the old answer
    _rdel(f"cap:{world['t'].id}:manager")
    v = client.get(URL, headers=world["h_manager"]).json()
    assert _tile(v, "bookings") == {"key": "bookings", "label": "Bookings made", "restricted": True}
    assert _tile(v, "booked_value") == {"key": "booked_value", "label": "Bookings value", "restricted": True}
    text = json.dumps(v)
    assert "87654" not in text and "55555" not in text and "shared calendar" not in text
    assert _tile(v, "leads")["restricted"] is False


@pytest.mark.skipif(SQLITE, reason="the reply-time SQL is PostgreSQL-only")
def test_reply_time_uses_mirrored_history_before_go_live(client, db, world):
    t, owner = world["t"], world["owner"]
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Mirror guest")
    db.add(g); db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, source="personal_bridge",
                     is_open=False)
    db.add(c); db.flush()
    meta = {"source": "personal_bridge", "chat_type": "user", "history": True}
    at = _at(25, 10)
    db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction=MessageDirection.INBOUND, channel="whatsapp",
                   body="hi", created_at=at, channel_metadata=meta))
    db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction=MessageDirection.OUTBOUND, channel="whatsapp",
                   body="hello", sender_id=owner.id, created_at=at + timedelta(minutes=90), channel_metadata=meta))
    db.commit()
    _go_live(client, world["h_owner"], days_ago=20, window=30)
    v = client.get(URL, headers=world["h_owner"]).json()
    reply = _tile(v, "first_reply_minutes")
    assert reply["before"]["value"] == 90.0 and reply["before"]["n"] == 1
    assert "personal WhatsApp (1 reply)" in reply["before"]["source"]
    assert v["replies_by_source"]["before"]["personal_whatsapp"] == {"avg_minutes": 90.0, "replies": 1}
