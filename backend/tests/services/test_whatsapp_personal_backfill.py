"""Mirrored chats show their phone number and real name (display only, never a lead), going forward and for chats already imported."""
import importlib.util
import os
import uuid
from datetime import datetime, timezone

import pytest

from tests.conftest import *  # noqa: F401,F403
from tests.services.test_whatsapp_personal_service import _make_agent, _make_session, _make_tenant

from app.models.conversation import Conversation
from app.models.guest import Guest
from app.services import whatsapp_personal_service as svc

_SPEC = importlib.util.spec_from_file_location("bf", os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "backfill_personal_whatsapp_numbers.py"))
bf = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bf)


@pytest.fixture()
def world(db):
    t = _make_tenant(db)
    a = _make_agent(db, t.id)
    return {"t": t, "s": _make_session(db, t.id, a.id)}


def _hist(db, w, jid, **kw):
    return svc.ingest_chat_message(db, w["s"], bridge_message_id=f"m-{uuid.uuid4().hex[:8]}", body="old", chat_jid=jid, history=True,
                                   occurred_at=datetime.now(timezone.utc), **kw)


def test_a_mirrored_chat_shows_its_number_and_name_but_is_not_a_lead(db, world):
    m = _hist(db, world, "919811100001@s.whatsapp.net", from_phone="+919811100001", chat_name="Priya Sharma")
    g = db.query(Guest).filter_by(id=db.query(Conversation).filter_by(id=m.conversation_id).one().guest_id).one()
    assert g.phone == "+919811100001" and g.name == "Priya Sharma" and g.lead_identified_at is None


def test_a_real_name_or_phone_is_never_overwritten(db, world):
    g = Guest(id=str(uuid.uuid4()), tenant_id=world["t"].id, name="Real Name", phone="+911111111111")
    svc.fill_mirror_identity(g, "+912222222222", "Other Name")
    assert (g.name, g.phone) == ("Real Name", "+911111111111")


def test_the_backfill_resolves_hidden_ids_from_the_bridge_tables(db, world):
    _hist(db, world, "1234567890123@lid", from_name="")                          # imported with no number and no name
    _hist(db, world, "555555555555@lid")                                          # not in the bridge map
    _hist(db, world, "120363000000000007@g.us", chat_type="group", chat_name="Trip group")
    lid_to_pn = {"1234567890123": "919822200002"}
    names = {"919822200002@s.whatsapp.net": "Arun (saved)", "1234567890123@lid": "arun push"}
    out = bf.run(db, world["t"].id, lid_to_pn, names)
    assert out == {"chats": 2, "phone_set": 1, "name_set": 1, "moved_to_existing_guest": 0, "merged_into_open_conversation": 0, "unresolved": 1}
    conv = db.query(Conversation).filter_by(tenant_id=world["t"].id, channel_conversation_id="1234567890123@lid").one()
    g = db.query(Guest).filter_by(id=conv.guest_id).one()
    assert g.phone == "+919822200002" and g.name == "Arun (saved)" and g.lead_identified_at is None


def test_a_chat_with_a_known_lead_whose_thread_is_closed_is_moved_onto_that_lead(db, world):
    lead = svc.ingest_chat_message(db, world["s"], bridge_message_id="live1", from_phone="+919833300003", from_name="Known Lead", body="Hi",
                                   chat_jid="919833300003@s.whatsapp.net")
    lead_conv = db.query(Conversation).filter_by(id=lead.conversation_id).one()
    lead_guest = lead_conv.guest_id
    lead_conv.is_open = False                                                     # no open thread to clash with: the chat just moves across
    db.commit()
    _hist(db, world, "9988776655@lid")                                            # imported under a hidden id: looks like a stranger
    out = bf.run(db, world["t"].id, {"9988776655": "919833300003"}, {})
    assert out["moved_to_existing_guest"] == 1 and out["merged_into_open_conversation"] == 0
    assert db.query(Conversation).filter_by(channel_conversation_id="9988776655@lid").one().guest_id == lead_guest


def test_an_imported_chat_is_merged_into_the_leads_open_conversation_instead_of_clashing(db, world):
    """The unique index allows ONE open WhatsApp conversation per guest: moving the chat across must merge, not fail."""
    from app.models.conversation import Message

    lead = svc.ingest_chat_message(db, world["s"], bridge_message_id="live2", from_phone="+919844400004", from_name="Lead", body="Hi",
                                   chat_jid="919844400004@s.whatsapp.net")
    lead_conv = db.query(Conversation).filter_by(id=lead.conversation_id).one()
    m = _hist(db, world, "4455667788@lid")                                         # imported under a hidden id: a separate stranger
    imported_conv = db.query(Conversation).filter_by(id=m.conversation_id).one()
    out = bf.run(db, world["t"].id, {"4455667788": "919844400004"}, {})
    db.expire_all()
    assert out["merged_into_open_conversation"] == 1
    assert {x.conversation_id for x in db.query(Message).filter(Message.id == m.id)} == {lead_conv.id}
    assert imported_conv.is_open is False and imported_conv.channel_conversation_id is None


def test_history_for_a_known_lead_joins_the_leads_open_conversation(db, world):
    """Importing history for someone who already has an open conversation must not create a second one (the unique index refuses it)."""
    live = svc.ingest_chat_message(db, world["s"], bridge_message_id="live3", from_phone="+919855500005", from_name="Lead", body="Hi",
                                   chat_jid="919855500005@s.whatsapp.net")
    old = svc.ingest_chat_message(db, world["s"], bridge_message_id="hist-lead", from_phone="+919855500005", body="older message",
                                  chat_jid="99887766@lid", history=True, occurred_at=datetime.now(timezone.utc))
    assert old.conversation_id == live.conversation_id


def test_resolve_handles_each_jid_kind():
    assert bf.resolve("919800000001@s.whatsapp.net", {}, {"919800000001@s.whatsapp.net": "Saved"}) == ("+919800000001", "Saved")
    assert bf.resolve("77@lid", {"77": "919800000002"}, {}) == ("+919800000002", None)
    assert bf.resolve("77@lid", {}, {"77@lid": "Push"}) == (None, "Push")
    assert bf.resolve("garbage", {}, {}) == (None, None)
