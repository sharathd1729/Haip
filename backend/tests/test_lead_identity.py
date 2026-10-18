"""The canonical lead definition, cross-platform identity resolution and the metrics built on them.

A LEAD is a person (Guest) HAIP holds a usable phone number for. These tests pin: a DM alone is not a lead; capturing a number
makes exactly one lead; the same number across Instagram, WhatsApp and calls is one person; names never merge anyone; repeat
enquiries and conversations are not extra people; conversion is a cohort figure; workspaces never mix; old data with no
identity evidence stays unidentified; merges are logged and can be undone; first touch is never overwritten.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import create_access_token, get_password_hash
from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity
from app.models.guest_merge_event import GuestMergeEvent
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, Stay
from app.models.stay_finance import StayPayment
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import identity_resolution, identity_service, lead_backfill, lead_metrics, phone_identity
from tests.conftest import seed_capabilities

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

NOW = datetime.now(timezone.utc)
WINDOW = (NOW - timedelta(days=1), NOW + timedelta(days=1))
PHONE = "+919845612345"


def _tenant(db, tz="Asia/Kolkata"):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"li-{uuid.uuid4().hex[:6]}", plan="growth", timezone=tz)
    db.add(t)
    db.commit()
    seed_capabilities(db, t.id)
    return t


def _guest(db, tid, value, itype="instagram_user_id", source="instagram", name="G"):
    gid, _ = identity_service.resolve_gid(db, tid, itype, value, source=source, guest_fields={"name": name})
    return db.query(Guest).filter_by(id=gid).one()


def _leads(db, tid, **f):
    return lead_metrics.count_new_leads(db, tid, *WINDOW, **f)


def _contacts(db, tid):
    return lead_metrics.count_unidentified_contacts(db, tid, *WINDOW)


def _stage(db, tid, key, category, order, won=False):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key=key, label=key, category=category, order=order, is_closed_won=won)
    db.add(s)
    db.flush()
    return s


def _inquiry(db, tid, guest, stage=None, when=None, source=InquirySource.META_IG):
    q = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, stage=InquiryStage.NEW, stage_id=stage.id if stage else None,
                source=source, created_at=when or NOW)
    db.add(q)
    db.flush()
    return q


# ── 1-3: what makes a lead ───────────────────────────────────────────────────────────────────────────────────

def test_a_dm_without_a_phone_number_is_a_contact_not_a_lead(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    g = _guest(db, tid, "ig-100")
    _inquiry(db, tid, g)                                      # the chat even opened an enquiry record
    db.commit()
    assert g.lead_identified_at is None
    assert g.first_touch_channel == "instagram" and g.first_touch_at is not None
    assert _leads(db, tid) == 0
    assert _contacts(db, tid) == 1
    assert lead_metrics.enquiry_counts(db, tid, *WINDOW)["created"] == 1          # an enquiry exists, a lead does not


def test_capturing_a_valid_phone_number_makes_the_contact_one_lead(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    g = _guest(db, tid, "ig-101")
    identity_service.add_signal(db, tid, g.id, "phone", PHONE, source="message_text")
    db.commit()
    db.refresh(g)
    assert g.lead_identified_at is not None and g.lead_identified_via == "message_text"
    assert g.first_touch_channel == "instagram"               # first touch is untouched by the number arriving later
    assert _leads(db, tid) == 1
    assert _contacts(db, tid) == 0                            # no longer an unidentified contact


def test_many_dms_from_one_contact_are_still_one_lead(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    ids = {identity_service.resolve_gid(db, tid, "instagram_user_id", "ig-102", source="instagram")[0] for _ in range(5)}
    assert len(ids) == 1
    gid = ids.pop()
    db.add(Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=gid, channel=ChannelType.INSTAGRAM))
    # One OPEN conversation per guest and channel is a database rule (migration 099); the earlier one is closed.
    db.add(Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=gid, channel=ChannelType.INSTAGRAM, is_open=False))
    identity_service.add_signal(db, tid, gid, "phone", PHONE, source="message_text")
    db.commit()
    assert _leads(db, tid) == 1
    assert lead_metrics.count_conversations(db, tid, *WINDOW) == 2        # two conversations, one person


# ── 4-5: one person across platforms ─────────────────────────────────────────────────────────────────────────

def test_the_same_number_across_whatsapp_calls_and_instagram_is_one_lead(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    wa = _guest(db, tid, PHONE, "whatsapp_number", "whatsapp", name="Asha")
    caller_gid, created = identity_service.resolve_gid(db, tid, "phone", "9845612345", source="ivr_call")
    assert not created and caller_gid == wa.id                # a call from the same number lands on the same person
    ig = _guest(db, tid, "ig-103", name="IG User 103")
    assert _leads(db, tid) == 1 and _contacts(db, tid) == 1   # WhatsApp lead + an Instagram contact without a number

    identity_service.add_signal(db, tid, ig.id, "phone", "+91 98456 12345", source="message_text")      # the DM shares the number
    db.commit()
    assert _leads(db, tid) == 1                                # still one person
    assert _contacts(db, tid) == 0
    live = db.query(Guest).filter_by(tenant_id=tid, is_deleted=False).all()
    assert len(live) == 1


def test_a_person_who_shares_a_number_later_keeps_the_earlier_lead_date_and_the_first_touch(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    ig = _guest(db, tid, "ig-104", name="IG User 104")
    wa = _guest(db, tid, PHONE, "whatsapp_number", "whatsapp", name="Asha")
    wa_identified = wa.lead_identified_at
    ig_first = ig.first_touch_at
    identity_service.add_signal(db, tid, ig.id, "phone", PHONE, source="message_text")
    db.commit()
    db.refresh(ig)
    assert ig.lead_identified_at == wa_identified              # the person was a lead from the WhatsApp number on
    assert ig.first_touch_channel == "instagram" and ig.first_touch_at == ig_first      # earlier touch wins, and is not rewritten


# ── 6-7: separate people stay separate ───────────────────────────────────────────────────────────────────────

def test_different_numbers_stay_separate_until_a_person_links_them_and_the_link_can_be_undone(db, tenant_and_user):
    tid, uid = tenant_and_user["tenant"].id, tenant_and_user["user"].id
    a = _guest(db, tid, "+919845612345", "whatsapp_number", "whatsapp")
    b = _guest(db, tid, "+919845699999", "whatsapp_number", "whatsapp")
    assert a.id != b.id and _leads(db, tid) == 2
    identity_service.merge_guests(db, tid, a.id, b.id, actor_user_id=uid, reason="manual")
    event = db.query(GuestMergeEvent).filter_by(tenant_id=tid).one()
    assert event.reason == "manual" and event.actor_user_id == uid and len(event.moved["identities"]) == 1
    assert _leads(db, tid) == 1
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="guest.merged").count() == 1

    identity_resolution.unmerge_guests(db, tid, event.id, actor_user_id=uid)
    db.refresh(event)
    assert event.unmerged_at is not None and _leads(db, tid) == 2
    assert db.query(GuestIdentity).filter_by(tenant_id=tid, guest_id=b.id).count() == 1        # b has its number back
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="guest.unmerged").count() == 1
    with pytest.raises(ValueError):
        identity_resolution.unmerge_guests(db, tid, event.id, actor_user_id=uid)               # not twice


def test_a_merge_folds_two_open_threads_on_one_channel_and_unmerge_puts_them_back(db, tenant_and_user):
    """Found live in the phone backfill: both records of one person had an OPEN Instagram conversation. Re-pointing broke
    the one-open-per-guest-and-channel rule (migration 099) and, on PostgreSQL, aborted the rest of the merge. Now the two
    are folded with 099's rule (keep the one with the enquiry) and undoing the merge splits them again."""
    tid, uid = tenant_and_user["tenant"].id, tenant_and_user["user"].id
    a = _guest(db, tid, "ig-201", name="A")
    b = _guest(db, tid, "ig-202", name="B")
    inq = _inquiry(db, tid, b)
    conv_a = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=a.id, channel=ChannelType.INSTAGRAM)
    conv_b = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=b.id, channel=ChannelType.INSTAGRAM, inquiry_id=inq.id)
    db.add_all([conv_a, conv_b])
    db.flush()
    msgs = {}
    for conv, text_ in ((conv_a, "hi from a"), (conv_b, "dates 24-25 Oct")):
        m = Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, channel=ChannelType.INSTAGRAM,
                    direction="inbound", body=text_)
        db.add(m)
        msgs[conv.id] = m.id
    stay_prop = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:6]}", type="caravan")
    db.add(stay_prop)
    db.flush()
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=b.id, property_id=stay_prop.id,
                check_in=date.today(), check_out=date.today() + timedelta(days=1), status="confirmed"))
    db.commit()

    event = identity_resolution.merge_guests(db, tid, a.id, b.id, actor_user_id=uid, reason="manual")
    open_threads = db.query(Conversation).filter_by(tenant_id=tid, guest_id=a.id, channel=ChannelType.INSTAGRAM, is_open=True).all()
    assert [c.id for c in open_threads] == [conv_b.id]                      # the thread with the enquiry is kept
    assert {m.conversation_id for m in db.query(Message).filter(Message.id.in_(list(msgs.values())))} == {conv_b.id}
    assert db.get(Conversation, conv_a.id).is_open is False
    assert db.query(Stay).filter_by(tenant_id=tid, guest_id=a.id).count() == 1   # later tables were still re-pointed
    assert event.moved["folded_conversations"] == [{"kept": conv_b.id, "closed": conv_a.id, "messages": [msgs[conv_a.id]]}]

    identity_resolution.unmerge_guests(db, tid, event.id, actor_user_id=uid)
    assert db.get(Message, msgs[conv_a.id]).conversation_id == conv_a.id     # a's message is back in a's thread
    assert db.get(Conversation, conv_a.id).is_open is True and db.get(Conversation, conv_a.id).guest_id == a.id
    assert db.get(Conversation, conv_b.id).guest_id == b.id and db.get(Conversation, conv_b.id).is_open is True


def test_similar_names_alone_never_merge_anyone(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    a = _guest(db, tid, "ig-201", name="Asha Rao")
    b = _guest(db, tid, "ig-202", name="Asha Rao")
    c = _guest(db, tid, "+919845611111", "whatsapp_number", "whatsapp", name="Asha Rao")
    d = _guest(db, tid, "+919845622222", "whatsapp_number", "whatsapp", name="asha  rao")
    assert len({a.id, b.id, c.id, d.id}) == 4
    assert _leads(db, tid) == 2 and _contacts(db, tid) == 2


def test_the_same_number_in_two_workspaces_is_two_leads_and_never_linked(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    other = _tenant(db).id
    a = _guest(db, tid, PHONE, "whatsapp_number", "whatsapp")
    b = _guest(db, other, PHONE, "whatsapp_number", "whatsapp")
    assert a.id != b.id and a.tenant_id == tid and b.tenant_id == other
    assert _leads(db, tid) == 1 and _leads(db, other) == 1
    with pytest.raises(ValueError):
        identity_resolution.merge_guests(db, tid, a.id, b.id)                              # a guest of another workspace cannot be merged in


# ── 8: enquiries are not people ──────────────────────────────────────────────────────────────────────────────

def test_repeat_enquiries_from_one_person_do_not_inflate_the_lead_count(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    g = _guest(db, tid, PHONE, "whatsapp_number", "whatsapp")
    for hours in (30, 20, 10):
        _inquiry(db, tid, g, when=NOW - timedelta(hours=hours), source=InquirySource.WA_DIRECT)
    db.commit()
    enq = lead_metrics.enquiry_counts(db, tid, NOW - timedelta(days=3), NOW)
    assert enq == {"created": 3, "repeat": 2}
    assert _leads(db, tid) == 1


# ── 9: conversion is a cohort ────────────────────────────────────────────────────────────────────────────────

def test_conversion_uses_the_cohort_of_leads_identified_in_the_period_not_todays_bookings(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Villa", slug=f"v-{uuid.uuid4().hex[:4]}", type="villa", is_active=True)
    db.add(prop)
    db.flush()

    def lead(day):
        g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone=f"+9198{uuid.uuid4().int % 10**8:08d}",
                  lead_identified_at=day, first_touch_channel="whatsapp", first_touch_at=day)
        db.add(g)
        db.flush()
        return g

    sep_a, sep_b, oct_c = lead(datetime(2026, 9, 5, tzinfo=timezone.utc)), lead(datetime(2026, 9, 6, tzinfo=timezone.utc)), lead(datetime(2026, 10, 2, tzinfo=timezone.utc))
    ci = date.today() + timedelta(days=40)
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=sep_a.id, property_id=prop.id, check_in=ci, check_out=ci + timedelta(days=2),
                status="confirmed", total_amount=40000, created_at=datetime(2026, 10, 3, tzinfo=timezone.utc)))     # booked in OCTOBER
    db.commit()
    sep = (datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc))
    octo = (datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc))

    c_sep = lead_metrics.cohort(db, tid, *sep)
    assert (c_sep["identified"], c_sep["booked"]) == (2, 1)
    assert lead_metrics.lead_to_booking(c_sep) == {"numerator": 1, "denominator": 2, "rate": 50.0,
                                                   "basis": "cohort: of the people who became leads in this period, the share that has a booking so far"}
    c_oct = lead_metrics.cohort(db, tid, *octo)
    assert (c_oct["identified"], c_oct["booked"]) == (1, 0)
    assert lead_metrics.lead_to_booking(c_oct)["rate"] == 0.0           # never "1 booking today / 1 lead today = 100%"
    split = lead_metrics.bookings_by_lead_cohort(db, tid, *octo)
    assert split["from_earlier_leads"]["count"] == 1 and split["from_new_leads"]["count"] == 0     # the October booking came from a September lead
    assert lead_metrics.lead_to_booking(lead_metrics.cohort(db, tid, datetime(2026, 11, 1, tzinfo=timezone.utc), datetime(2026, 11, 30, tzinfo=timezone.utc)))["rate"] is None


# ── phone rules ──────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,region,expected", [
    ("+919845612345", None, "+919845612345"),
    ("98456 12345", "IN", "+919845612345"),
    ("919845612345@s.whatsapp.net", None, "+919845612345"),      # a WhatsApp id: international digits without the "+"
    ("00919845612345", None, "+919845612345"),
    ("0501234567", "AE", "+971501234567"),
    ("9845612345", None, None),                                  # no country, no default: not assumed to be India
    ("+91", None, None), ("", None, None), (None, "IN", None), ("abc", "IN", None),
    ("9999999999", "IN", None), ("+910000000000", None, None), ("1234567890", "IN", None),   # placeholders
    ("+91 12345", None, None),                                   # too short to be a real number
])
def test_what_counts_as_a_usable_phone_number(raw, region, expected):
    assert phone_identity.normalize(raw, region) == expected


def test_india_is_assumed_only_for_a_workspace_whose_timezone_says_so(db, tenant_and_user):
    india = tenant_and_user["tenant"].id
    unknown = _tenant(db, tz="UTC").id
    dubai = _tenant(db, tz="Asia/Dubai").id
    in_g = _guest(db, india, "9845612345", "phone", "ivr_call")
    un_g = _guest(db, unknown, "9845612345", "phone", "ivr_call")
    ae_g = _guest(db, dubai, "0501234567", "phone", "ivr_call")
    assert in_g.lead_identified_at is not None and in_g.phone == "+919845612345"
    assert un_g.lead_identified_at is None                        # a bare local number with no known country is not a lead
    assert ae_g.lead_identified_at is not None and ae_g.phone == "+971501234567"


def test_an_invalid_or_placeholder_number_never_makes_a_lead(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    g = _guest(db, tid, "ig-300")
    for bad in ("+910000000000", "9999999999", "12345"):
        identity_service.add_signal(db, tid, g.id, "phone", bad, source="message_text")
    db.commit()
    db.refresh(g)
    assert g.lead_identified_at is None and _leads(db, tid) == 0


# ── first touch, the journey, concurrency ────────────────────────────────────────────────────────────────────

def test_returning_through_another_platform_never_overwrites_first_touch(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    g = _guest(db, tid, "ig-400")
    first_at = g.first_touch_at
    identity_service.add_signal(db, tid, g.id, "phone", PHONE, source="ivr_call")        # they phone in later
    identity_service.add_signal(db, tid, g.id, "whatsapp_number", PHONE, source="whatsapp")
    db.commit()
    db.refresh(g)
    assert g.first_touch_channel == "instagram" and g.first_touch_at == first_at
    assert g.lead_identified_via == "call"


def test_an_unknown_first_touch_is_reported_as_unknown_not_invented(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    g = _guest(db, tid, PHONE, "phone", source="system")
    assert g.first_touch_channel is None and g.lead_identified_at is not None
    row = {r["key"]: r for r in lead_metrics.by_first_touch(db, tid, *WINDOW, with_bookings=False)}
    assert row["unknown"]["leads"] == 1 and row["unknown"]["label"] == "Unknown"


def test_a_request_that_loses_the_creation_race_resolves_to_the_winner(db, tenant_and_user, monkeypatch):
    """Two requests meet the same new contact at once; the unique (tenant, type, value) index lets one win and the other must
    return the winner's person, not fail and not create a second one. The branch is driven directly here: the SQLite test session
    shares one transaction, so a real rollback would also remove the winner. A real concurrent race needs PostgreSQL."""
    tid = tenant_and_user["tenant"].id
    winner = _guest(db, tid, PHONE, "whatsapp_number", "whatsapp")
    real_lookup = identity_resolution._lookup_signal
    seen = {"n": 0}

    def blind_first(*a, **k):                         # the loser did not see the winner's row yet
        seen["n"] += 1
        return None if seen["n"] == 1 else real_lookup(*a, **k)

    def lost_the_race(*a, **k):
        raise IntegrityError("INSERT INTO guest_identities", {}, Exception("UNIQUE constraint failed"))

    monkeypatch.setattr(identity_resolution, "_lookup_signal", blind_first)
    monkeypatch.setattr(identity_resolution, "_create_guest", lost_the_race)
    monkeypatch.setattr(db, "rollback", lambda: None)
    gid, created = identity_resolution.resolve_or_create(db, tid, "whatsapp_number", PHONE, source="whatsapp")
    assert gid == winner.id and created is False


def test_the_lead_state_endpoint_shows_the_path_and_hides_money_from_roles_without_it(db, client, tenant_and_user):
    tid, tu = tenant_and_user["tenant"].id, tenant_and_user
    prop = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Villa", slug=f"v-{uuid.uuid4().hex[:4]}", type="villa", is_active=True)
    db.add(prop)
    g = _guest(db, tid, "ig-500")
    identity_service.add_signal(db, tid, g.id, "phone", PHONE, source="ivr_call")
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.INSTAGRAM)
    db.add(conv)
    db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction="inbound", channel="instagram", body="hi"))
    ci = date.today() + timedelta(days=30)
    stay = Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, property_id=prop.id, check_in=ci, check_out=ci + timedelta(days=2),
                status="confirmed", total_amount=25000)
    db.add(stay)
    db.flush()
    db.add(StayPayment(tenant_id=tid, stay_id=stay.id, kind="payment", amount=10000, method="upi", paid_on=date.today()))
    db.commit()

    owner = client.get(f"/api/v1/guests/{g.id}/lead-state", headers={"Authorization": f"Bearer {tu['access_token']}"})
    assert owner.status_code == 200, owner.text
    j = owner.json()
    assert j["is_lead"] is True and j["first_touch"]["channel"] == "instagram" and j["identified_via"] == "call"
    assert j["latest_touch"]["channel"] == "instagram" and j["messages"] == 1
    assert j["bookings"][0]["total"] == 25000.0 and j["paid"] == 10000.0

    res = User(id=str(uuid.uuid4()), tenant_id=tid, name="R", email=f"r-{uuid.uuid4().hex[:5]}@t.com",
               hashed_password=get_password_hash("pw"), role=UserRole.RESERVATIONS, is_active=True)
    db.add(res)
    db.commit()
    h = {"Authorization": "Bearer " + create_access_token({"sub": res.id, "tenant_id": tid, "role": "reservations"})}
    r = client.get(f"/api/v1/guests/{g.id}/lead-state", headers=h).json()
    assert r["bookings"][0]["total"] is None and r["paid"] is None and len(r["bookings"]) == 1       # bookings yes, money no
    assert "25000" not in str(r) and "10000" not in str(r)

    other = User(id=str(uuid.uuid4()), tenant_id=_tenant(db).id, name="O", email=f"o-{uuid.uuid4().hex[:5]}@t.com",
                 hashed_password=get_password_hash("pw"), role=UserRole.OWNER, is_active=True)
    db.add(other)
    db.commit()
    ho = {"Authorization": "Bearer " + create_access_token({"sub": other.id, "tenant_id": other.tenant_id, "role": "owner"})}
    assert client.get(f"/api/v1/guests/{g.id}/lead-state", headers=ho).status_code == 404


# ── historical data ──────────────────────────────────────────────────────────────────────────────────────────

def test_old_records_with_no_identity_evidence_stay_unidentified_and_the_backfill_is_repeatable(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    old = datetime(2026, 1, 10, tzinfo=timezone.utc)

    def raw_guest(phone="", created=old):
        g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Old", phone=phone, created_at=created)
        db.add(g)
        db.flush()
        return g

    def signal(g, itype, value, source, seen):
        db.add(GuestIdentity(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, identity_type=itype, identity_value=value,
                             source=source, confidence=0.8, first_seen_at=seen, last_seen_at=seen))

    ig_only = raw_guest()
    signal(ig_only, "instagram_user_id", "ig-old", "instagram", old)
    wa = raw_guest(phone=PHONE)
    signal(wa, "whatsapp_number", PHONE, "whatsapp", old + timedelta(days=2))
    later = raw_guest()                                                      # Instagram first, number added three weeks later
    signal(later, "instagram_user_id", "ig-old-2", "instagram", old)
    signal(later, "phone", "+919845677777", "message_text", old + timedelta(days=21))
    phone_col = raw_guest(phone="+919845688888")                              # only Guest.phone, no signal row
    placeholder = raw_guest(phone="+910000000000")
    nothing = raw_guest()
    db.commit()

    stats = lead_backfill.backfill(db, tid, dry_run=True)
    assert stats["identified"] == 3 and stats["left_unidentified"] == 3
    db.expire_all()
    assert db.query(Guest).filter_by(id=wa.id).one().lead_identified_at is None             # a dry run changes nothing

    stats = lead_backfill.backfill(db, tid)
    db.commit()
    db.expire_all()
    rows = {g.id: g for g in db.query(Guest).filter_by(tenant_id=tid).all()}
    assert rows[ig_only.id].lead_identified_at is None and rows[ig_only.id].first_touch_channel == "instagram"
    assert rows[wa.id].lead_identified_at is not None and rows[wa.id].lead_identified_via == "whatsapp"
    assert rows[later.id].lead_identified_at.replace(tzinfo=timezone.utc) == old + timedelta(days=21)    # the day the number arrived, not the first DM
    assert rows[phone_col.id].lead_identified_at is not None                                  # best available evidence: Guest.phone + creation date
    assert rows[placeholder.id].lead_identified_at is None and rows[nothing.id].lead_identified_at is None
    assert rows[nothing.id].first_touch_channel is None                                       # no evidence of a channel: unknown, not guessed
    assert stats["channel_unknown"] >= 3

    again = lead_backfill.backfill(db, tid)
    assert again["identified"] == 0 and again["first_touch_set"] == 0                         # nothing is rewritten the second time
