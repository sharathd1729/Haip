"""scripts/purge_personal_whatsapp_session.py: delete what one personal WhatsApp number mirrored, and nothing else."""

import sys
import uuid
from unittest.mock import patch

import pytest

from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.models.whatsapp_personal_session import WhatsAppPersonalSessionStatus
from tests.services.test_whatsapp_personal_service import _make_agent, _make_session, _make_tenant

sys.path.insert(0, "scripts")
import purge_personal_whatsapp_session as purge  # noqa: E402

PHONE = "+919900000000"


def _conv(db, tid, guest_id, source):
    c = Conversation(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        guest_id=guest_id,
        channel=ChannelType.WHATSAPP,
        is_open=True,
        source=source,
    )
    db.add(c)
    db.flush()
    return c


def _msg(db, tid, conv, session_id=None, media=None):
    meta = {"source": "personal_bridge", "session_id": session_id} if session_id else None
    m = Message(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        conversation_id=conv.id,
        direction="inbound",
        channel=ChannelType.WHATSAPP,
        body="hi",
        channel_metadata=meta,
        media_url=media,
    )
    db.add(m)
    db.flush()
    return m


def _guest(db, tid):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Friend")
    db.add(g)
    db.flush()
    return g


@pytest.fixture()
def world(db):
    t = _make_tenant(db)
    s = _make_session(db, t.id, _make_agent(db, t.id, "Test Owner").id)
    s.status, s.phone_number = WhatsAppPersonalSessionStatus.LOGGED_OUT, PHONE
    other = _make_session(db, t.id, _make_agent(db, t.id, "Krisha").id)
    other.phone_number = "+919811111111"
    only = _guest(db, t.id)  # exists only because of the test number
    c_only = _conv(db, t.id, only.id, "personal_bridge")
    _msg(db, t.id, c_only, s.id)
    _msg(db, t.id, c_only, s.id, media=f"{t.id}/wa_personal/{s.id}/m1.jpg")
    db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=only.id))
    shared = _guest(db, t.id)  # also writes to the official number
    c_shared = _conv(db, t.id, shared.id, None)
    official = _msg(db, t.id, c_shared)
    from_test = _msg(db, t.id, c_shared, s.id)
    stranger = _guest(db, t.id)  # another agent's personal WhatsApp
    c_other = _conv(db, t.id, stranger.id, "personal_bridge")
    others = _msg(db, t.id, c_other, other.id)
    db.commit()
    return dict(
        t=t,
        s=s,
        only=only,
        c_only=c_only,
        shared=shared,
        c_shared=c_shared,
        official=official,
        from_test=from_test,
        c_other=c_other,
        others=others,
    )


def test_dry_run_counts_and_deletes_nothing(db, world):
    report = purge.run(db, world["t"].slug, PHONE, apply=False)
    assert report == {
        "session_status": "logged_out",
        "messages": 3,
        "chats": 2,
        "empty_chats": 0,
        "people_erased": 1,
        "people_kept_other_messages_only": 1,
        "people_kept_quoted": 0,
        "files": 1,
        "applied": False,
    }
    assert db.query(Message).filter_by(tenant_id=world["t"].id).count() == 5


def test_apply_erases_the_test_numbers_people_and_messages_only(db, world):
    world = {k: getattr(v, "id", v) for k, v in world.items()} | {
        "t": world["t"],
        "s": world["s"],
    }  # ids survive deletes
    with patch("app.services.media_storage.delete_tenant_objects", return_value=1) as files:
        report = purge.run(db, world["t"].slug, PHONE, apply=True)
    assert report["applied"] is True
    tid = world["t"].id
    # the person known only through the test number: chats, messages and the auto-created lead are gone
    assert db.get(Conversation, world["c_only"]) is None
    assert db.query(Inquiry).filter_by(tenant_id=tid, guest_id=world["only"]).count() == 0
    # the person also on the official number keeps that thread, minus the test number's message
    assert db.get(Conversation, world["c_shared"]) is not None
    assert db.get(Message, world["official"]) is not None and db.get(Message, world["from_test"]) is None
    # another agent's mirror is untouched
    assert db.get(Message, world["others"]) is not None
    assert f"{tid}/wa_personal/{world['s'].id}/m1.jpg" in files.call_args.args[1]
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="personal_whatsapp.session_purged").count() == 1


def test_someone_the_team_quoted_keeps_the_lead_and_quote_only_the_chats_go(db, world):
    # Production dry run: one "test-only" person had a quote with a live payment link from the day before.
    t, only = world["t"], world["only"]
    inq = db.query(Inquiry).filter_by(tenant_id=t.id, guest_id=only.id).one()
    db.add(InquiryQuote(tenant_id=t.id, inquiry_id=inq.id, amount=45000))
    db.commit()
    inq_id, c_only = inq.id, world["c_only"].id
    assert purge.run(db, t.slug, PHONE, apply=False)["people_kept_quoted"] == 1
    with patch("app.services.media_storage.delete_tenant_objects", return_value=1):
        report = purge.run(db, t.slug, PHONE, apply=True)
    assert report["people_erased"] == 0 and report["applied"] is True
    assert db.get(Inquiry, inq_id) is not None and db.query(InquiryQuote).filter_by(inquiry_id=inq_id).count() == 1
    assert db.get(Conversation, c_only) is None  # the test number's chat with them is gone


def test_empty_mirrored_chats_of_the_paired_agent_go_too(db, world):
    # Production: the number backfill moved an imported chat's messages into the person's open chat and closed the
    # emptied one; no message named the session, so the purge never saw it ("No messages yet" in the Inbox).
    t = world["t"]
    contact = _guest(db, t.id)
    left = _conv(db, t.id, contact.id, "personal_bridge")
    left.is_open, left.assigned_to = False, world["s"].user_id
    others = _conv(db, t.id, _guest(db, t.id).id, "personal_bridge")  # an empty mirror not assigned to this agent stays
    db.commit()
    left_id, others_id, contact_id = left.id, others.id, contact.id
    report = purge.run(db, t.slug, PHONE, apply=False)
    assert report["empty_chats"] == 1 and report["chats"] == 3 and report["people_erased"] == 2
    with patch("app.services.media_storage.delete_tenant_objects", return_value=1):
        purge.run(db, t.slug, PHONE, apply=True)
    assert db.get(Conversation, left_id) is None and db.get(Conversation, others_id) is not None
    assert db.get(Guest, contact_id).name == "[Deleted]"


def test_a_connected_number_is_refused(db, world):
    world["s"].status = WhatsAppPersonalSessionStatus.CONNECTED
    db.commit()
    with pytest.raises(SystemExit, match="still connected"):
        purge.run(db, world["t"].slug, PHONE, apply=True)
    assert db.query(Message).filter_by(tenant_id=world["t"].id).count() == 5
