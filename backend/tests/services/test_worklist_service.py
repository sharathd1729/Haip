"""Agent worklist tests.

The section that matters most is awaiting_reply -- it is the one the
dashboard previously approximated with `automation_outcome ==
"no_match_no_response"`, which means "no automation replied", not "no human
replied". These pin the real semantics.
"""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity, IdentityType
from app.models.tenant import Tenant
from app.services import worklist_service as ws


def _tenant(db):
    t = Tenant(name="W", slug=f"w-{uuid.uuid4().hex[:8]}")
    db.add(t); db.commit()
    return t


def _conv(db, t, *, name="Arjun", assigned_to=None):
    g = Guest(tenant_id=t.id, name=name)
    db.add(g); db.flush()
    c = Conversation(
        tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP,
        is_open=True, assigned_to=assigned_to,
    )
    db.add(c); db.commit()
    return g, c


def _msg(db, t, c, direction, *, body="hi", minutes_ago=5, internal=False):
    m = Message(
        tenant_id=t.id, conversation_id=c.id, direction=direction,
        channel=ChannelType.WHATSAPP, body=body, is_internal=internal,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(m); db.commit()
    return m


# ─── awaiting_reply ──────────────────────────────────────────────────────────

def test_guest_last_message_means_awaiting_reply(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND, body="are you there?")
    rows = ws.awaiting_reply(db, t.id)
    assert len(rows) == 1
    assert rows[0]["last_message"] == "are you there?"
    assert rows[0]["lead"]["name"] == "Arjun"


def test_our_reply_clears_it(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND, minutes_ago=10)
    _msg(db, t, c, MessageDirection.OUTBOUND, minutes_ago=2)
    assert ws.awaiting_reply(db, t.id) == []


def test_guest_replying_after_us_reopens_it(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND, minutes_ago=30)
    _msg(db, t, c, MessageDirection.OUTBOUND, minutes_ago=20)
    _msg(db, t, c, MessageDirection.INBOUND, body="one more thing", minutes_ago=5)
    rows = ws.awaiting_reply(db, t.id)
    assert len(rows) == 1
    assert rows[0]["last_message"] == "one more thing"


def test_closed_conversations_are_excluded(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND)
    c.is_open = False
    db.commit()
    assert ws.awaiting_reply(db, t.id) == []


def test_internal_notes_do_not_count_as_a_reply(db):
    """An internal note is never delivered to the guest, so it must not make
    the thread look answered."""
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND, minutes_ago=10)
    _msg(db, t, c, MessageDirection.OUTBOUND, body="note to self", minutes_ago=2, internal=True)
    assert len(ws.awaiting_reply(db, t.id)) == 1


def test_waiting_minutes_is_reported(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND, minutes_ago=90)
    assert ws.awaiting_reply(db, t.id)[0]["waiting_minutes"] >= 89


def test_agent_scope_filters_to_own_conversations(db):
    t = _tenant(db)
    _, mine = _conv(db, t, name="Mine", assigned_to="user-1")
    _, theirs = _conv(db, t, name="Theirs", assigned_to="user-2")
    _msg(db, t, mine, MessageDirection.INBOUND)
    _msg(db, t, theirs, MessageDirection.INBOUND)
    rows = ws.awaiting_reply(db, t.id, scope_user_id="user-1")
    assert [r["lead"]["name"] for r in rows] == ["Mine"]


def test_tenant_isolation(db):
    t1, t2 = _tenant(db), _tenant(db)
    _, c1 = _conv(db, t1, name="T1 lead")
    _, c2 = _conv(db, t2, name="T2 lead")
    _msg(db, t1, c1, MessageDirection.INBOUND)
    _msg(db, t2, c2, MessageDirection.INBOUND)
    assert [r["lead"]["name"] for r in ws.awaiting_reply(db, t1.id)] == ["T1 lead"]


# ─── shared contact details ──────────────────────────────────────────────────

def test_shared_details_picks_up_phone_and_email(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    now = datetime.now(timezone.utc)
    for itype, val in ((IdentityType.PHONE.value, "+919876500001"),
                       (IdentityType.EMAIL.value, "a@b.com")):
        db.add(GuestIdentity(
            tenant_id=t.id, guest_id=g.id, identity_type=itype,
            identity_value=val, confidence=0.9, first_seen_at=now,
        ))
    db.commit()
    rows = ws.shared_contact_details(db, t.id, now - timedelta(hours=1))
    assert len(rows) == 1
    assert len(rows[0]["shared"]) == 2


def test_shared_details_ignores_internal_identity_types(db):
    """device_fingerprint isn't something a guest 'shared'."""
    t = _tenant(db)
    g, c = _conv(db, t)
    now = datetime.now(timezone.utc)
    db.add(GuestIdentity(
        tenant_id=t.id, guest_id=g.id,
        identity_type=IdentityType.DEVICE_FINGERPRINT.value,
        identity_value="abc123", confidence=0.3, first_seen_at=now,
    ))
    db.commit()
    assert ws.shared_contact_details(db, t.id, now - timedelta(hours=1)) == []


# ─── lead context ────────────────────────────────────────────────────────────

def test_placeholder_names_are_labelled_unnamed(db):
    t = _tenant(db)
    g, c = _conv(db, t, name="Instagram User")
    _msg(db, t, c, MessageDirection.INBOUND)
    assert ws.awaiting_reply(db, t.id)[0]["lead"]["name"] == "Unnamed lead"


def test_has_contact_is_false_without_details(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND)
    assert ws.awaiting_reply(db, t.id)[0]["lead"]["has_contact"] is False


# ─── totals vs row cap ───────────────────────────────────────────────────────

def test_counts_are_true_totals_not_row_counts(db):
    """Reporting len(rows) understates a backlog past the cap -- verified
    against real data where the true figure was 206 and the cap 50."""
    t = _tenant(db)
    for i in range(4):
        _, c = _conv(db, t, name=f"Lead {i}")
        _msg(db, t, c, MessageDirection.INBOUND)

    original = ws.SECTION_LIMIT
    try:
        ws.SECTION_LIMIT = 2
        out = ws.build_worklist(db, t.id, hours=24)
        assert len(out["awaiting_reply"]) == 2
        assert out["counts"]["awaiting_reply"] == 4
        assert out["truncated"]["awaiting_reply"] is True
    finally:
        ws.SECTION_LIMIT = original
