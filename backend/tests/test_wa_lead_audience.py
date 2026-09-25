"""CRM-leads audience for WhatsApp campaigns: heat score, filters, exclusions."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1.endpoints.messaging import WASubscriber
from app.models.consent import Consent
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.models.tenant import Tenant
from app.models.wa_campaign_recipient import WACampaignRecipient
from app.services import wa_lead_audience as la

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


# ─── heat ────────────────────────────────────────────────────────────────────

def test_a_lead_with_nothing_is_cold():
    assert la.score_lead() == (0, "cold", [])


def test_a_strong_lead_is_hot_and_every_point_is_explained():
    score, heat, why = la.score_lead(sentiment="positive", urgency="high", quoted_open=True, days_to_checkin=20, adults=4)
    assert heat == "hot" and score == 3 + 2 + 2 + 2 + 1
    assert "Has a quote and hasn't booked yet" in why and "Trip in 20 days" in why and "Needs a quick reply" in why


def test_warm_middle():
    assert la.score_lead(sentiment="positive", urgency="medium", days_to_checkin=60)[1] == "warm"


def test_negative_and_hesitant_pull_it_down():
    assert la.score_lead(sentiment="negative", urgency="high")[0] == 0
    assert la.score_lead(sentiment="hesitant", urgency="high", adults=2)[0] == 2


def test_engagement_counts():
    assert la.score_lead(inbound_messages=2)[0] == 0
    assert la.score_lead(inbound_messages=3)[0] == 1
    assert la.score_lead(inbound_messages=9)[0] == 2


def test_a_lost_lead_is_cold_whatever_else():
    assert la.score_lead(sentiment="positive", urgency="high", quoted_open=True, closed_lost=True)[1] == "cold"


def test_past_dates_earn_nothing():
    assert la.score_lead(days_to_checkin=-3)[0] == 0


# ─── filter hygiene ──────────────────────────────────────────────────────────

def test_normalize_drops_unknown_keys_and_bad_values():
    f = la.normalize_filter({
        "heat": ["hot", "lava"], "stage_ids": ["a", ""], "trip_within_days": "30", "quiet_days_min": -4,
        "not_messaged_days": 14, "created_from": "2026-09-01", "created_to": "garbage",
        "quoted_open": "yes", "past_guests": True, "tenant_id": "hijack", "evil": {"x": 1},
    })
    assert f == {"heat": ["hot"], "stage_ids": ["a"], "trip_within_days": 30, "not_messaged_days": 14,
                 "created_from": "2026-09-01", "past_guests": True}


def test_a_leads_audience_needs_the_senders_confirmation():
    with pytest.raises(la.AudienceError, match="Confirm"):
        la.prepare_audience_filter({"type": "leads", "heat": ["hot"]})
    out = la.prepare_audience_filter({"type": "leads", "consent_confirmed": True, "heat": ["hot"], "junk": 1})
    assert out == {"type": "leads", "heat": ["hot"], "consent_confirmed": True}
    assert la.prepare_audience_filter({"tags": ["vip"]}) == {"tags": ["vip"]}     # subscriber audiences unchanged


# ─── resolving against the CRM ───────────────────────────────────────────────

@pytest.fixture()
def crm(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    stages = {}
    for key, won, lost in (("active", False, False), ("sold", True, False), ("lost", False, True)):
        st = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key=key, label=key.title(), order=len(stages),
                           is_closed_won=won, is_closed_lost=lost, category="valid")
        db.add(st)
        stages[key] = st
    db.commit()
    return type("CRM", (), {"tid": tid, "stages": stages})


def _lead(db, crm, name, phone="+919876500001", stage="active", source=InquirySource.META_IG, analysis=None, days_old=2,
          quiet_days=0, **inq):
    g = Guest(id=str(uuid.uuid4()), tenant_id=crm.tid, name=name, phone=phone)
    db.add(g); db.flush()
    created = NOW - timedelta(days=days_old)
    i = Inquiry(id=str(uuid.uuid4()), tenant_id=crm.tid, guest_id=g.id, source=source,
                stage_id=crm.stages[stage].id, ai_analysis=analysis, created_at=created,
                updated_at=NOW - timedelta(days=quiet_days), **inq)
    db.add(i); db.commit()
    return g, i


def _resolve(db, crm, **f):
    return la.resolve(db, crm.tid, {"type": "leads", **f}, now=NOW)


def test_everyone_with_a_valid_phone_is_reached_and_the_rest_are_counted(db, crm):
    _lead(db, crm, "Priya", "+919876500001")
    _lead(db, crm, "Arjun", "9876500002")                        # local format is fine
    _lead(db, crm, "No number", "")
    _lead(db, crm, "Bad number", "12345")
    r = _resolve(db, crm)
    assert sorted(m.name for m in r.members) == ["Arjun", "Priya"]
    assert r.members[0].phone.startswith("+91")
    assert (r.matched, r.no_phone, r.invalid_phone) == (4, 1, 1)


def test_opted_out_people_are_left_out_by_either_record(db, crm):
    stopped, _ = _lead(db, crm, "Replied STOP", "+919876500001")
    db.add(Consent(id=str(uuid.uuid4()), tenant_id=crm.tid, guest_id=stopped.id, channel="whatsapp", scope="marketing",
                   granted=False, recorded_at=NOW.isoformat()))
    _lead(db, crm, "On the do-not-list", "+919876500002")
    db.add(WASubscriber(id=str(uuid.uuid4()), tenant_id=crm.tid, phone="+919876500002", opted_in=False, tags=[]))
    _lead(db, crm, "Fine", "+919876500003")
    db.commit()
    r = _resolve(db, crm)
    assert [m.name for m in r.members] == ["Fine"] and r.opted_out == 2


def test_a_marketing_consent_that_was_granted_does_not_exclude(db, crm):
    g, _ = _lead(db, crm, "Opted in", "+919876500001")
    db.add(Consent(id=str(uuid.uuid4()), tenant_id=crm.tid, guest_id=g.id, channel="whatsapp", scope="marketing",
                   granted=True, recorded_at=NOW.isoformat()))
    db.commit()
    assert len(_resolve(db, crm).members) == 1


def test_deleted_and_sample_guests_never_appear(db, crm):
    g, _ = _lead(db, crm, "Erased", "+919876500001")
    g.is_deleted = True
    s, _ = _lead(db, crm, "Sample", "+919876500002")
    s.is_sample = True
    p, _ = _lead(db, crm, "Pending deletion", "+919876500003")
    p.deletion_state = "pending"
    db.commit()
    assert _resolve(db, crm).members == []


def test_a_guest_with_two_inquiries_is_one_recipient_scored_on_the_better_one(db, crm):
    g, _ = _lead(db, crm, "Priya", "+919876500001", analysis={"sentiment": "neutral"})
    db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=crm.tid, guest_id=g.id, source=InquirySource.META_IG,
                   stage_id=crm.stages["active"].id, ai_analysis={"sentiment": "positive", "reply_urgency": "high"},
                   created_at=NOW, updated_at=NOW))
    db.commit()
    r = _resolve(db, crm)
    assert len(r.members) == 1 and r.members[0].score == 4


def test_two_guest_records_with_one_number_are_messaged_once(db, crm):
    _lead(db, crm, "Priya A", "+919876500001")
    _lead(db, crm, "Priya B", "98765 00001")
    assert len(_resolve(db, crm).members) == 1


def test_filters_by_stage_source_owner_and_dates(db, crm):
    _lead(db, crm, "IG active", "+919876500001", stage="active", source=InquirySource.META_IG, days_old=2)
    _lead(db, crm, "Call sold", "+919876500002", stage="sold", source=InquirySource.INBOUND_CALL, days_old=40)
    _lead(db, crm, "Web active old", "+919876500003", stage="active", source=InquirySource.WEBSITE, days_old=100)
    names = lambda r: sorted(m.name for m in r.members)
    assert names(_resolve(db, crm, stage_ids=[crm.stages["sold"].id])) == ["Call sold"]
    assert names(_resolve(db, crm, sources=["meta_ig", "website"])) == ["IG active", "Web active old"]
    assert names(_resolve(db, crm, sources=["nonsense"])) == []
    assert names(_resolve(db, crm, created_within_days=7)) == ["IG active"]
    assert names(_resolve(db, crm, created_from="2026-08-01", created_to="2026-09-10")) == ["Call sold"]
    assert names(_resolve(db, crm, assigned_to=["unassigned"])) == ["Call sold", "IG active", "Web active old"]
    assert names(_resolve(db, crm, assigned_to=["someone-else"])) == []


def test_ai_and_trip_signals(db, crm):
    soon = (NOW + timedelta(days=20)).date().isoformat()
    later = (NOW + timedelta(days=200)).date().isoformat()
    _lead(db, crm, "Hot", "+919876500001", analysis={"sentiment": "positive", "reply_urgency": "high"}, check_in=soon, adults=4)
    _lead(db, crm, "Later", "+919876500002", analysis={"sentiment": "neutral", "reply_urgency": "medium"}, check_in=later)
    _lead(db, crm, "Nothing", "+919876500003")
    names = lambda r: sorted(m.name for m in r.members)
    assert names(_resolve(db, crm, heat=["hot"])) == ["Hot"]
    assert names(_resolve(db, crm, heat=["cold"])) == ["Later", "Nothing"]
    assert names(_resolve(db, crm, trip_within_days=45)) == ["Hot"]
    assert names(_resolve(db, crm, trip_within_days=365)) == ["Hot", "Later"]


def test_quoted_not_booked_quiet_and_past_guests(db, crm):
    _lead(db, crm, "Quoted", "+919876500001", quoted_amount=25000)
    _lead(db, crm, "Quoted and sold", "+919876500002", stage="sold", quoted_amount=25000)
    _lead(db, crm, "Quiet", "+919876500003", quiet_days=10)
    g, _ = _lead(db, crm, "Repeat guest", "+919876500004")
    g.total_stays = 2
    db.commit()
    names = lambda r: sorted(m.name for m in r.members)
    assert names(_resolve(db, crm, quoted_open=True)) == ["Quoted"]
    assert names(_resolve(db, crm, quiet_days_min=7)) == ["Quiet"]
    assert names(_resolve(db, crm, past_guests=True)) == ["Quoted and sold", "Repeat guest"]


def test_people_messaged_recently_are_skipped_on_request(db, crm):
    _lead(db, crm, "Just messaged", "+919876500001")
    _lead(db, crm, "Messaged long ago", "+919876500002")
    _lead(db, crm, "Never", "+919876500003")
    for phone, days in (("+919876500001", 3), ("+919876500002", 60)):
        db.add(WACampaignRecipient(id=str(uuid.uuid4()), tenant_id=crm.tid, campaign_id="c1", phone=phone, status="delivered",
                                   sent_at=NOW - timedelta(days=days)))
    db.commit()
    r = _resolve(db, crm, not_messaged_days=14)
    assert sorted(m.name for m in r.members) == ["Messaged long ago", "Never"] and r.recently_messaged == 1
    assert len(_resolve(db, crm).members) == 3                # off unless asked for


def test_members_are_ordered_hottest_first(db, crm):
    _lead(db, crm, "Cold", "+919876500001")
    _lead(db, crm, "Hot", "+919876500002", analysis={"sentiment": "positive", "reply_urgency": "high"}, quoted_amount=1000)
    assert [m.name for m in _resolve(db, crm).members] == ["Hot", "Cold"]


def test_the_audience_is_scoped_to_the_workspace(db, crm):
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other); db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=other.id, name="Theirs", phone="+919876599999")
    db.add(g); db.flush()
    db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=other.id, guest_id=g.id, source=InquirySource.META_IG, created_at=NOW, updated_at=NOW))
    _lead(db, crm, "Ours", "+919876500001")
    db.commit()
    assert [m.name for m in _resolve(db, crm).members] == ["Ours"]


def test_options_count_people_and_phones(db, crm):
    _lead(db, crm, "A", "+919876500001", stage="active", source=InquirySource.META_IG)
    _lead(db, crm, "B", "", stage="active", source=InquirySource.META_IG)
    _lead(db, crm, "C", "+919876500003", stage="sold", source=InquirySource.INBOUND_CALL)
    o = la.options(db, crm.tid)
    assert o["totals"] == {"leads": 3, "with_phone": 2}
    active = next(s for s in o["stages"] if s["key"] == "active")
    assert (active["leads"], active["with_phone"]) == (2, 1)
    ig = next(s for s in o["sources"] if s["value"] == "meta_ig")
    assert (ig["leads"], ig["with_phone"]) == (2, 1)
    assert o["owners"][0]["id"] == "unassigned" and o["owners"][0]["leads"] == 3
    assert {p["id"] for p in o["presets"]} >= {"hot", "quoted", "trip_soon", "went_quiet", "new_week", "past_guests"}
