"""A phone number the guest types in a chat becomes their phone signal (owner report, Oct 2026: "the lead sent the dates AND the
number in one message, but the bot still says no phone number shared").

The old capture regex took only the FIRST run of digits/spaces/dashes and stopped there. Each case marked "was missed" below
returned None from the old code (reproduced against it before the fix)."""
import importlib.util
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity
from app.models.inquiry import Inquiry, InquiryStage
from app.models.pipeline_stage import PipelineStage
from app.models.task import Task
from app.models.tenant import Tenant
from app.services import chat_phone_capture, phone_identity
from app.services import lead_auto_create as lac

PHONE = "+919845012345"   # a real-looking number: 98765 43210 itself is a descending run, which HAIP treats as a placeholder


# ── the matcher ──────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Hi, 4 adults 2 kids, 24-25 Oct, Coorg. My number 98450 12345",
    "call me on +91-98450-12345 for 17th to 19th",
    "9845012345 21/10 to 22/10",                                   # was missed: the date after it was swallowed
    "Contact: 0 98450 12345",
    "98450.12345",                                                 # was missed: dots
    "98450-12345-call after 6",
    "24 10 2026 to 26 10 2026, ph 9845012345",                     # was missed: a date before it matched first
    "Dates 24/10 - 25/10 9845012345",                              # was missed: "10 9845012345" read as one number
    "+91 9845012345 2 adults",                                     # was missed: the head count after it was swallowed
    "on 24 9845012345",                                            # was missed
    "24.10.2026 - 25.10.2026 9845012345",
    "Mera number 98450-12345 hai, 2 log, 20 se 22 tak",            # Hindi
    "ನನ್ನ ನಂಬರ್ 9845012345 📞 Coorg 24-25",                         # Kannada + emoji
    "📱9845012345🙏",
    "mob:9845012345",
    "(+91) 98450 12345",
    "919845012345",
    "98 45 01 23 45",
    "2 adults\n9845012345\n2 kids",
])
def test_a_number_written_any_usual_way_is_found(text):
    assert lac.extract_phone(text) == PHONE
    assert lac.text_contains_phone(text)


@pytest.mark.parametrize("text", [
    "budget 25,000 for 2 nights",
    "Rs 1,25,000 total? 18000 per night",
    "pincode 560064",
    "booking id 1234567890123",
    "24-08-2026 to 26-08-2026",                                     # the old loose check said "has a phone" here
    "24/10/2026 - 26/10/2026, 4 adults 2 kids",
    "Amount 125000 paid ref 20261024123456",
    "9999999999",                                                  # placeholder
    "98765 43210",                                                 # a descending run: placeholder
    "1234567890",                                                  # placeholder
    "1 0 2 4 2 0 2 6",
    "looking for a caravan this weekend",
    "",
])
def test_dates_prices_pincodes_and_references_are_not_phones(text):
    assert lac.extract_phone(text) is None
    assert not lac.text_contains_phone(text)


def test_two_numbers_come_back_in_order_and_the_first_is_the_guests():
    assert phone_identity.find_phones("my no is 9845012345, driver 9900112233", "IN") == [PHONE, "+919900112233"]
    assert lac.extract_phone("my no is 9845012345, driver 9900112233") == PHONE


def test_without_a_region_only_numbers_with_a_country_code_are_found():
    assert phone_identity.find_phones("call 9845012345", None) == []
    assert phone_identity.find_phones("call +91 98450 12345", None) == [PHONE]


# ── capture: signal, lead, stage, decline task ───────────────────────────────────────────────────────────────────────────

def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"cpc-{uuid.uuid4().hex[:6]}", plan="growth", timezone="Asia/Kolkata")
    db.add(t)
    db.flush()
    return t


def _stage(db, tid, key, order=0, **flags):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key=key, label=key, order=order, **flags)
    db.add(s)
    db.flush()
    return s


def _thread(db, tid, *, with_inquiry=True):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="IG guest", phone="")
    db.add(g)
    db.flush()
    inquiry_id = None
    if with_inquiry:
        default = _stage(db, tid, f"unq-{uuid.uuid4().hex[:4]}", category="invalid", is_default_entry=True)
        _stage(db, tid, f"ge-{uuid.uuid4().hex[:4]}", order=1, category="valid", is_valid_lead_entry=True)
        inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, stage=InquiryStage.NEW, stage_id=default.id, source="meta_ig")
        db.add(inq)
        db.flush()
        inquiry_id = inq.id
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.INSTAGRAM, is_open=True, inquiry_id=inquiry_id)
    db.add(c)
    db.flush()
    return g, c


def test_capture_makes_the_guest_a_lead_moves_the_enquiry_and_closes_the_decline_task(db):
    t = _tenant(db)
    g, c = _thread(db, t.id)
    db.add(Task(id=str(uuid.uuid4()), tenant_id=t.id, title="Guest declined phone number — IG guest", conversation_id=c.id, guest_id=g.id))
    db.flush()

    got = chat_phone_capture.capture_from_text(db, t.id, g.id, "4 adults, 24 10 2026 to 26 10 2026, ph 98450 12345",
                                               conversation=c)
    db.flush()
    assert got == PHONE
    sig = db.query(GuestIdentity).filter_by(tenant_id=t.id, guest_id=g.id, identity_type="phone").one()
    assert sig.identity_value == PHONE
    db.refresh(g)
    assert g.lead_identified_at is not None and g.phone == PHONE
    inq = db.query(Inquiry).filter_by(id=c.inquiry_id).one()
    assert db.query(PipelineStage).filter_by(id=inq.stage_id).one().is_valid_lead_entry
    assert db.query(Task).filter_by(conversation_id=c.id).one().is_done is True
    assert chat_phone_capture.guest_has_phone(db, t.id, g.id)


def test_text_without_a_number_changes_nothing(db):
    t = _tenant(db)
    g, c = _thread(db, t.id)
    assert chat_phone_capture.capture_from_text(db, t.id, g.id, "24-10-2026 to 26-10-2026, 4 adults", conversation=c) is None
    assert chat_phone_capture.capture_from_text(db, t.id, g.id, "[ig_post] 9845012345", conversation=c) is None
    db.flush()
    assert db.query(GuestIdentity).filter_by(guest_id=g.id).count() == 0
    assert not chat_phone_capture.guest_has_phone(db, t.id, g.id)


def test_capture_never_reaches_another_workspace(db):
    t1, t2 = _tenant(db), _tenant(db)
    g1, _ = _thread(db, t1.id, with_inquiry=False)
    g2, _ = _thread(db, t2.id, with_inquiry=False)
    db.add(GuestIdentity(id=str(uuid.uuid4()), tenant_id=t2.id, guest_id=g2.id, identity_type="phone", identity_value=PHONE,
                         source="test", confidence=0.9))
    db.flush()
    chat_phone_capture.capture_from_text(db, t1.id, g1.id, "my number 9845012345")
    db.flush()
    assert db.query(GuestIdentity).filter_by(tenant_id=t1.id, identity_value=PHONE).one().guest_id == g1.id
    assert db.query(GuestIdentity).filter_by(tenant_id=t2.id, identity_value=PHONE).one().guest_id == g2.id   # not merged across
    with pytest.raises(ValueError):
        chat_phone_capture.capture_from_text(db, t1.id, g2.id, "my number 9900112233")                          # t2's guest


def test_a_whatsapp_number_counts_as_having_a_phone(db):
    t = _tenant(db)
    g, _ = _thread(db, t.id, with_inquiry=False)
    db.add(GuestIdentity(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, identity_type="whatsapp_number",
                         identity_value=PHONE, source="whatsapp", confidence=0.85))
    db.flush()
    assert chat_phone_capture.guest_has_phone(db, t.id, g.id)


# ── backfill script ──────────────────────────────────────────────────────────────────────────────────────────────────────

_SPEC = importlib.util.spec_from_file_location("backfill_chat_phones", os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "backfill_chat_phones.py"))
bf = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bf)


def _msg(db, c, body, *, inbound=True, days_ago=1):
    m = Message(id=str(uuid.uuid4()), tenant_id=c.tenant_id, conversation_id=c.id, channel=ChannelType.INSTAGRAM, body=body,
                direction=MessageDirection.INBOUND if inbound else MessageDirection.OUTBOUND,
                created_at=datetime.now(timezone.utc) - timedelta(days=days_ago))
    db.add(m)
    db.flush()
    return m


def test_backfill_dry_run_writes_nothing_and_apply_dates_the_lead_at_the_message(db):
    t, other = _tenant(db), _tenant(db)
    g, c = _thread(db, t.id)
    _msg(db, c, "Hi 4 adults, 24-25 Oct", days_ago=5)
    _msg(db, c, "9845012345 21/10 to 22/10", days_ago=4)
    _msg(db, c, "our number is 9900112233", inbound=False, days_ago=3)         # ours: never read
    g_none, c_none = _thread(db, t.id, with_inquiry=False)
    _msg(db, c_none, "budget 25,000, pincode 560064")
    og, oc = _thread(db, other.id, with_inquiry=False)
    _msg(db, oc, "9900112233")
    db.commit()

    dry = bf.run(db, t.id, days=30, apply=False)
    assert dry["phones_found"] == 1 and dry["applied"] == 0 and dry["guests_without_phone"] == 2
    assert all("98450" not in str(r) for r in dry["found"])                     # hashed only
    assert db.query(GuestIdentity).filter_by(tenant_id=t.id).count() == 0

    done = bf.run(db, t.id, days=30, apply=True)
    assert done["applied"] == 1
    sig = db.query(GuestIdentity).filter_by(tenant_id=t.id, guest_id=g.id).one()
    assert sig.identity_value == PHONE and sig.source == "message_text_backfill"
    db.refresh(g)
    first_seen = g.lead_identified_at if g.lead_identified_at.tzinfo else g.lead_identified_at.replace(tzinfo=timezone.utc)
    assert first_seen < datetime.now(timezone.utc) - timedelta(days=3)            # dated at the message, not today
    assert db.query(GuestIdentity).filter_by(tenant_id=other.id).count() == 0     # another workspace untouched
    assert bf.run(db, t.id, days=30, apply=True)["phones_found"] == 0             # idempotent
