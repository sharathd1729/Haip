"""Lead type + the human "Valid enquiry?" review + paid/organic (CRM reporting, 22 Oct 2026; migration 169).

Pinned: b2b is set from the guest's OWN words at chat auto-create (word boundaries, never a name); staff change the type and
record a review through audited endpoints (leads.write; read_only 403; another workspace 404); b2b / partner people and
enquiries leave the guest lead KPIs and the new-lead queue; the Leads list filters by type and "came from" and says whose leads
it shows; paid / organic / unknown follows the attribution rows, never the stored source alone for an ad.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.audit_event import AuditEvent
from app.models.conversation import Conversation
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.lead_attribution import LeadAttribution
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import inquiry_service, kpi_metrics, lead_metrics, lead_paid, work_queue_service as wq
from app.services.lead_auto_create import lead_type_for_message
from tests.api.test_reports_leads import _headers, _lead, _preview, _tenant, _user

NOW = datetime.now(timezone.utc)


# ── b2b at auto-create ────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("Hi, I'm a wedding planner looking for a caravan for my clients", "b2b"),
    ("We are a DMC in Bangalore", "b2b"),
    ("Travel agency here, do you give commission?", "b2b"),
    ("Tour operators welcome?", "b2b"),
    ("Interested in a collab with your brand", "b2b"),        # the existing collaboration routing
    ("Is Ratha free on 24 Oct for 4 adults?", "guest"),
    ("It's for my wife's birthday event", "guest"),            # "event" alone is not trade
    ("Our regency apartment pickup please", "guest"),          # no match inside a word
    ("", "guest"),
])
def test_b2b_comes_from_the_message_words(text, expected):
    assert lead_type_for_message(text) == expected


def test_a_chat_enquiry_is_typed_from_the_message_never_the_name(db):
    t = _tenant(db)
    g1 = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Travel Agent Ravi", phone="+919800000001")
    g2 = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Meena", phone="+919800000002")
    db.add_all([g1, g2]); db.flush()
    by_name = inquiry_service.get_or_create_from_chat(db, t.id, g1.id, source="wa_direct", message_text="Free this Saturday?")
    by_words = inquiry_service.get_or_create_from_chat(db, t.id, g2.id, source="wa_direct",
                                                       message_text="I run an event management company")
    assert by_name.lead_type == "guest" and by_words.lead_type == "b2b"


# ── staff set the type and the review ─────────────────────────────────────────────────────────────────────────

def test_staff_change_the_type_and_record_a_review_both_audited(client, db):
    t = _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER, "Sharath")
    inq = _lead(db, t.id, name="Kavya", phone="+919811100000")
    db.commit()
    h = _headers(owner)
    r = client.put(f"/api/v1/leads/{inq.id}/lead-type", headers=h, json={"lead_type": "partner"})
    assert r.status_code == 200 and r.json()["lead_type"] == "partner"
    r = client.put(f"/api/v1/leads/{inq.id}/validation", headers=h,
                   json={"valid": True, "dates_confirmed": True, "budget_fits": False, "clear_intent": True, "note": "Asked for 2 nights"})
    assert r.status_code == 200, r.text
    v = r.json()["validation"]
    assert v["status"] == "valid" and v["dates_confirmed"] is True and v["budget_fits"] is False and v["by_name"] == "Sharath"
    db.refresh(inq)
    assert inq.validated_by == owner.id and inq.validated_at is not None
    actions = [e.action for e in db.query(AuditEvent).filter_by(tenant_id=t.id, target_id=inq.id)]
    assert "lead.type_changed" in actions and "lead.validation_recorded" in actions

    cleared = client.put(f"/api/v1/leads/{inq.id}/validation", headers=h, json={"valid": None}).json()
    assert cleared["validation"]["status"] is None
    assert client.put(f"/api/v1/leads/{inq.id}/lead-type", headers=h, json={"lead_type": "vip"}).status_code == 422


def test_read_only_is_refused_and_another_workspace_is_not_found(client, db):
    t, other = _tenant(db), _tenant(db)
    ro = _user(db, t.id, UserRole.READ_ONLY)
    owner = _user(db, t.id, UserRole.OWNER)
    theirs = _lead(db, other.id, name="Elsewhere", phone="+919822200000")
    mine = _lead(db, t.id, name="Mine", phone="+919833300000")
    db.commit()
    assert client.put(f"/api/v1/leads/{mine.id}/lead-type", headers=_headers(ro), json={"lead_type": "b2b"}).status_code == 403
    assert client.put(f"/api/v1/leads/{mine.id}/validation", headers=_headers(ro), json={"valid": True}).status_code == 403
    assert client.put(f"/api/v1/leads/{theirs.id}/lead-type", headers=_headers(owner), json={"lead_type": "b2b"}).status_code == 404
    assert client.put(f"/api/v1/leads/{theirs.id}/validation", headers=_headers(owner), json={"valid": False}).status_code == 404
    db.refresh(theirs)
    assert theirs.lead_type == "guest" and theirs.validation_status is None


# ── guest KPIs leave b2b / partner out ────────────────────────────────────────────────────────────────────────

def _person(db, tid, name, types, minutes_ago=30):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name=name, phone=f"+9197{uuid.uuid4().int % 10**8:08d}",
              lead_identified_at=NOW - timedelta(minutes=minutes_ago), first_touch_channel="whatsapp")
    db.add(g); db.flush()
    for n, lt in enumerate(types):          # the last type listed is the newest enquiry
        db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, stage=InquiryStage.NEW, source=InquirySource.WA_DIRECT,
                       lead_type=lt, created_at=NOW - timedelta(minutes=minutes_ago, seconds=len(types) - n)))
    db.flush()
    return g


def test_guest_lead_kpis_count_guests_only(db):
    t, other = _tenant(db), _tenant(db)
    _person(db, t.id, "Guest", ["guest"])
    _person(db, t.id, "Agency", ["b2b"])
    _person(db, t.id, "Both", ["b2b", "guest"])          # also a guest (newest enquiry): counted once
    _person(db, t.id, "No enquiry yet", [])
    _person(db, other.id, "Elsewhere", ["guest"])
    db.commit()
    start, end = NOW - timedelta(days=1), NOW + timedelta(minutes=1)
    assert lead_metrics.count_new_leads(db, t.id, start, end) == 3
    assert kpi_metrics.count_leads(db, t.id, start, end) == 2              # enquiry records: guest type only
    assert lead_metrics.enquiry_counts(db, t.id, start, end)["created"] == 2
    tenant = db.query(Tenant).filter_by(id=t.id).one()
    titles = {i["title"] for i in wq.build(db, tenant, scope_user_id=None)["items"] if i["kind"] == "new_lead"}
    assert "Agency" not in titles and {"Guest", "Both"} <= titles


# ── the Leads list: type, came from, scope ────────────────────────────────────────────────────────────────────

def _attribution(db, tid, inq, source_type, ad_id=None, on_guest_only=False):
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=inq.guest_id, channel="whatsapp")
    db.add(conv); db.flush()
    db.add(LeadAttribution(tenant_id=tid, inquiry_id=None if on_guest_only else inq.id, conversation_id=conv.id,
                           guest_id=inq.guest_id, destination_channel="whatsapp", source_type=source_type, ad_id=ad_id,
                           first_message_at=NOW))
    db.flush()


def test_paid_organic_unknown_follow_the_attribution_rows(db):
    t, other = _tenant(db), _tenant(db)
    ad = _lead(db, t.id, name="Ad", phone="+919844400001", source=InquirySource.CLICK_TO_WA)
    _attribution(db, t.id, ad, "ad", ad_id="a1")
    late_ad = _lead(db, t.id, name="Ad on guest", phone="+919844400002", source=InquirySource.CLICK_TO_WA)
    _attribution(db, t.id, late_ad, None, ad_id="a2", on_guest_only=True)            # older row: no type, an ad id
    post = _lead(db, t.id, name="Post", phone="+919844400003", source=InquirySource.META_IG)
    _attribution(db, t.id, post, "post")
    direct = _lead(db, t.id, name="Direct", phone="+919844400004", source=InquirySource.WA_DIRECT)
    call = _lead(db, t.id, name="Call", phone="+919844400005", source=InquirySource.PHONE)
    _attribution(db, other.id, call, "ad", ad_id="x")                                # another workspace's row: ignored
    db.commit()
    got = lead_paid.classify(db, t.id, [ad, late_ad, post, direct, call])
    assert got == {ad.id: "paid", late_ad.id: "paid", post.id: "organic", direct.id: "organic", call.id: "unknown"}
    for value in lead_paid.VALUES:
        ids = {i for (i,) in db.query(Inquiry.id).filter(Inquiry.tenant_id == t.id, lead_paid.filter_sql(db, t.id, value))}
        assert ids == {k for k, v in got.items() if v == value}, value


def test_the_leads_list_filters_by_type_and_came_from_and_says_whose_leads(client, db):
    t = _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER)
    asha = _user(db, t.id, UserRole.CONCIERGE, "Asha")
    trade = _lead(db, t.id, name="Trade", phone="+919855500001", lead_type="b2b")
    ad = _lead(db, t.id, name="Ad", phone="+919855500002", source=InquirySource.CLICK_TO_WA, owner=asha)
    _attribution(db, t.id, ad, "ad", ad_id="a1")
    _lead(db, t.id, name="Organic", phone="+919855500003", source=InquirySource.WA_DIRECT, owner=owner)
    db.commit()
    h = _headers(owner)
    res = client.get("/api/v1/leads", headers=h).json()
    assert res["scope"] == "team" and res["total"] == 3
    cards = {c["display_name"]: c for c in res["leads"]}
    assert cards["Trade"]["lead_type"] == "b2b" and cards["Ad"]["came_from"] == "paid" and cards["Organic"]["came_from"] == "organic"
    assert [c["display_name"] for c in client.get("/api/v1/leads?lead_type=b2b", headers=h).json()["leads"]] == ["Trade"]
    assert [c["display_name"] for c in client.get("/api/v1/leads?came_from=paid", headers=h).json()["leads"]] == ["Ad"]
    assert client.get("/api/v1/leads?lead_type=vip", headers=h).status_code == 422
    assert client.get("/api/v1/leads?came_from=tv", headers=h).status_code == 422
    mine = client.get("/api/v1/leads", headers=_headers(asha)).json()
    assert mine["scope"] == "mine_and_unassigned" and {c["display_name"] for c in mine["leads"]} == {"Ad", "Trade"}
    trade_id = trade.id
    assert client.get(f"/api/v1/leads/{trade_id}", headers=h).json()["lead_type"] == "b2b"


def test_lead_report_is_guests_by_default_and_can_pick_types(client, db):
    t = _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER)
    _lead(db, t.id, name="Guest one", phone="+919866600001")
    _lead(db, t.id, name="Agency", phone="+919866600002", lead_type="b2b")
    db.commit()
    default = _preview(client, owner, ["guest_name", "lead_type"]).json()
    assert [r["guest_name"] for r in default["rows"]] == ["Guest one"] and default["rows"][0]["lead_type"] == "Guest"
    trade = _preview(client, owner, ["guest_name", "lead_type", "came_from", "validation"], {"lead_types": ["b2b"]}).json()
    assert trade["rows"] == [{"guest_name": "Agency", "lead_type": "B2B / trade", "came_from": "Organic", "validation": "Not reviewed"}]   # an Instagram DM, no ad
    assert _preview(client, owner, ["guest_name"], {"lead_types": ["vip"]}).status_code == 422
