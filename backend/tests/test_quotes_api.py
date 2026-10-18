"""/quotes (the staff quote builder) and the quote-builder permissions on /business-data.

Per endpoint: a happy path, a role without the capability (403) and another tenant's data (404 / not visible). Also: a preview
writes nothing; issuing re-prices from published records only (a draft route is refused); the fallback is stored as its own,
linked option; the next step becomes the lead's follow-up task; lead visibility follows /leads; drafters cannot publish and
nobody but the owner can approve their own draft.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.audit_event import AuditEvent
from app.models.business_record import BusinessRecord
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.inquiry_360 import InquiryQuote
from app.models.task import Task
from app.models.user import UserRole
from app.services import business_data_service as bds
from tests.test_business_data import _tenant, _workspace
from tests.test_increment1_defect_specs import _h, _user
from tests.test_quote_builder_pricing import START, krs_route, ratha

API = "/api/v1/quotes"


@pytest.fixture()
def r(db):
    w = ratha(db)
    w.res = _user(db, w.t.id, UserRole.RESERVATIONS)
    w.con = _user(db, w.t.id, UserRole.CONCIERGE)
    w.foh = _user(db, w.t.id, UserRole.FOH)
    w.comp = _user(db, w.t.id, UserRole.COMPLIANCE)
    return w


def lead(db, tenant_id, name="Kiran Reddy", assigned_to=None, phone=None):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone=phone or f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, source=InquirySource.WA_DIRECT, assigned_to=assigned_to)
    db.add(inq)
    db.commit()
    return inq


def coorg_option(**over):
    o = {"package_key": "coorg-48", "start_date": START.isoformat(), "nights": 2, "adults": 5, "children": 1,
         "destination_key": "coorg", "sights": ["Raja's Seat"], "kits": ["Culinary"]}
    o.update(over)
    return o


def day_option(**over):
    o = {"package_key": "day-rate", "start_date": START.isoformat(), "nights": 1, "adults": 6, "destination_key": "krs"}
    o.update(over)
    return o


# ─── preview ──────────────────────────────────────────────────────────────────────────────────────────────

def test_preview_prices_both_options_and_writes_nothing(client, db, r):
    before = (db.query(InquiryQuote).count(), db.query(AuditEvent).count(), db.query(Task).count())
    res = client.post(f"{API}/preview", json={"primary": coorg_option(), "fallback": day_option()}, headers=_h(r.res))
    assert res.status_code == 200, res.text
    body = res.json()
    p, f = body["primary"], body["fallback"]
    assert p["status"] == "ok" and p["total"] == "89880.00" and p["advance"] == "44940" and p["at_actuals"] == ["Tolls and parking"]
    assert p["km"]["extra_km"] == "75" and p["km"]["applied_rate"] == "70.00"
    assert {v["property_name"]: v["status"] for v in p["availability"]} == {"Ratha 1": "available", "Ratha 2": "available"}
    assert f["status"] == "ok" and f["total"] == "41440.00" and f["km"]["suggested_rate"] == "100.00"
    assert body["can_save"] is True and "Confirm the overnight stay before sending the price." in body["send_blockers"]
    db.expire_all()
    assert (db.query(InquiryQuote).count(), db.query(AuditEvent).count(), db.query(Task).count()) == before


def test_preview_returns_a_refusal_with_its_fix_and_still_shows_the_vehicles(client, db, r):
    res = client.post(f"{API}/preview", json={"primary": day_option(package_key="travel-only")}, headers=_h(r.owner)).json()
    p = res["primary"]
    assert p["status"] == "refused" and p["reason"] == "below_min_days" and p["fix"] == {"nights": 3} and p["total"] is None
    assert len(p["availability"]) == 2 and res["can_save"] is False


def test_preview_needs_quotes_write(client, db, r):
    for user in (r.foh, r.ro, r.comp):
        assert client.post(f"{API}/preview", json={"primary": coorg_option()}, headers=_h(user)).status_code == 403


def test_preview_never_sees_another_tenants_packages(client, db, r):
    other = _workspace(db)
    res = client.post(f"{API}/preview", json={"primary": coorg_option()}, headers=_h(other.owner)).json()
    assert res["primary"]["reason"] == "package_not_published" and res["primary"]["total"] is None


def test_a_draft_route_previews_but_cannot_be_saved(client, db, r):
    bds.create_draft(db, r.t.id, "destination", "chikmagalur", krs_route(km=250) | {"name": "Chikmagalur"}, r.res.id)
    db.commit()
    opt = day_option(destination_key="chikmagalur")
    prev = client.post(f"{API}/preview", json={"primary": opt}, headers=_h(r.res)).json()
    assert prev["primary"]["status"] == "ok" and prev["primary"]["uses_drafts"] is True and prev["can_save"] is False
    inq = lead(db, r.t.id)
    res = client.post(API, json={"inquiry_id": inq.id, "primary": opt}, headers=_h(r.res))
    assert res.status_code == 422 and res.json()["detail"]["code"] == "destination_not_published"
    assert db.query(InquiryQuote).filter_by(inquiry_id=inq.id).count() == 0


# ─── issue / list / get ───────────────────────────────────────────────────────────────────────────────────

def test_save_to_lead_stores_both_options_audits_and_sets_the_next_step(client, db, r):
    inq = lead(db, r.t.id, assigned_to=r.con.id)
    when = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    body = {"inquiry_id": inq.id, "primary": coorg_option(), "fallback": day_option(), "stay_check": "confirmed",
            "stay_name": "Twisted Tree", "next_step_at": when.isoformat(), "note": "Guest prefers Coorg"}
    res = client.post(API, json=body, headers=_h(r.con))
    assert res.status_code == 201, res.text
    out = res.json()
    first, second = out["quotes"]
    assert first["option_rank"] == 1 and second["option_rank"] == 2 and second["option_group_id"] == first["id"]
    assert first["amount"] == "89880.00" and second["amount"] == "41440.00" and first["notes"] == "Guest prefers Coorg"
    assert first["snapshot"]["meta"] == {"stay_check": "confirmed", "stay_name": "Twisted Tree", "channel": "direct"}
    assert first["snapshot"]["km"]["applied_rate"] == "70.00"
    db.expire_all()
    assert db.query(AuditEvent).filter_by(tenant_id=r.t.id, action="quote.issued").count() == 2
    task = db.query(Task).filter_by(id=out["next_step"]["task_id"]).one()
    assert task.inquiry_id == inq.id and task.assigned_to == r.con.id and task.title.startswith("Follow up on the quote")
    # saving again moves the same follow-up instead of adding another
    later = when + timedelta(days=1)
    again = client.post(API, json={**body, "next_step_at": later.isoformat()}, headers=_h(r.con)).json()
    assert [q["id"] for q in again["quotes"]] == [first["id"], second["id"]] and again["next_step"]["task_id"] == task.id
    db.expire_all()
    assert db.query(Task).filter_by(inquiry_id=inq.id).count() == 1

    assert client.get(API, params={"inquiry_id": inq.id}, headers=_h(r.ro)).status_code == 404     # not their lead
    listed = client.get(API, params={"inquiry_id": inq.id}, headers=_h(r.mgr))
    assert listed.status_code == 200 and {q["id"] for q in listed.json()} == {first["id"], second["id"]}
    one = client.get(f"{API}/{first['id']}", headers=_h(r.owner)).json()
    assert one["still_valid"]["valid"] is True and one["package_key"] == "coorg-48"


def test_save_needs_quotes_write_and_a_visible_lead(client, db, r):
    inq = lead(db, r.t.id, assigned_to=r.res.id)
    body = {"inquiry_id": inq.id, "primary": coorg_option()}
    assert client.post(API, json=body, headers=_h(r.foh)).status_code == 403
    # a concierge cannot quote another agent's lead (same visibility as /leads)
    assert client.post(API, json=body, headers=_h(r.con)).status_code == 404
    assert client.post(API, json=body, headers=_h(r.res)).status_code == 201


def test_another_tenants_lead_and_quotes_are_not_found(client, db, r):
    other = _tenant(db)
    other_owner = _user(db, other.id, UserRole.OWNER)
    inq = lead(db, r.t.id)
    saved = client.post(API, json={"inquiry_id": inq.id, "primary": coorg_option()}, headers=_h(r.owner)).json()["quotes"][0]
    h = _h(other_owner)
    assert client.get(API, params={"inquiry_id": inq.id}, headers=h).status_code == 404
    assert client.get(f"{API}/{saved['id']}", headers=h).status_code == 404
    res = client.post(API, json={"inquiry_id": inq.id, "primary": coorg_option()}, headers=h)
    assert res.status_code == 404


def test_reading_quotes_needs_leads_or_bookings_read(client, db, r):
    inq = lead(db, r.t.id)
    saved = client.post(API, json={"inquiry_id": inq.id, "primary": coorg_option()}, headers=_h(r.owner)).json()["quotes"][0]
    assert client.get(API, params={"inquiry_id": inq.id}, headers=_h(r.comp)).status_code == 403
    assert client.get(f"{API}/{saved['id']}", headers=_h(r.comp)).status_code == 403


# ─── catalogue and lead picker ────────────────────────────────────────────────────────────────────────────

def test_catalog_lists_plans_routes_drafts_kits_and_permissions(client, db, r):
    bds.create_draft(db, r.t.id, "destination", "chikmagalur", krs_route(km=250) | {"name": "Chikmagalur"}, r.res.id)
    db.commit()
    cat = client.get(f"{API}/catalog", headers=_h(r.res))
    assert cat.status_code == 200
    c = cat.json()
    assert {p["key"] for p in c["packages"]} == {"day-rate", "coorg-48", "all-inclusive", "travel-only"}
    dest = {d["key"]: d for d in c["destinations"]}
    assert dest["chikmagalur"]["live"] is None and dest["chikmagalur"]["draft"]["created_by"] == r.res.id
    assert dest["coorg"]["live"]["version"] == 1 and dest["coorg"]["draft"] is None
    assert [k["name"] for k in c["kits"]] == ["Adventure", "Culinary", "Entertainment", "Wellness"]
    assert c["reseller_terms"]["data"]["tiers"][0]["name"] == "Travel agents" and c["advance_percent"] == "50.00"
    assert [v["name"] for v in c["vehicles"]] == ["Ratha 1", "Ratha 2"]
    assert c["permissions"] == {"user_id": r.res.id, "is_owner": False, "can_quote": True, "can_draft": True, "can_publish": False,
                                "can_manage_templates": False}
    assert client.get(f"{API}/catalog", headers=_h(r.foh)).status_code == 403


def test_catalog_is_per_tenant_and_works_without_the_ai_module(client, db, r):
    bare = _tenant(db)                                 # no ai_concierge module at all
    owner = _user(db, bare.id, UserRole.OWNER)
    c = client.get(f"{API}/catalog", headers=_h(owner))
    assert c.status_code == 200 and c.json()["packages"] == [] and c.json()["destinations"] == []


def test_lead_picker_searches_names_and_respects_visibility(client, db, r):
    mine = lead(db, r.t.id, "Kiran Reddy", assigned_to=r.con.id, phone="+919812345678")
    lead(db, r.t.id, "Kiran Someone", assigned_to=r.res.id)
    free = lead(db, r.t.id, "Divya Narayan")
    got = client.get(f"{API}/leads", params={"q": "kiran"}, headers=_h(r.con)).json()
    assert [x["inquiry_id"] for x in got] == [mine.id] and got[0]["phone_last4"] == "5678"
    assert client.get(f"{API}/leads", params={"q": "5678"}, headers=_h(r.owner)).json()[0]["inquiry_id"] == mine.id
    assert {x["inquiry_id"] for x in client.get(f"{API}/leads", headers=_h(r.con)).json()} == {mine.id, free.id}
    other = _tenant(db)
    assert client.get(f"{API}/leads", params={"q": "kiran"}, headers=_h(_user(db, other.id, UserRole.OWNER))).json() == []
    assert client.get(f"{API}/leads", headers=_h(r.foh)).status_code == 403


# ─── /business-data: drafting, approving, four eyes ───────────────────────────────────────────────────────

BD = "/api/v1/business-data"


def test_reservations_drafts_a_route_and_a_manager_approves_it(client, db, r):
    made = client.post(f"{BD}/records", json={"kind": "destination", "key": "chikmagalur", "data": krs_route(km=250)}, headers=_h(r.res))
    assert made.status_code == 201, made.text
    rid = made.json()["id"]
    assert client.post(f"{BD}/records/{rid}/validate", headers=_h(r.res)).status_code == 200
    assert client.post(f"{BD}/records/{rid}/publish", json={}, headers=_h(r.res)).status_code == 403        # drafters cannot publish
    assert client.post(f"{BD}/records/{rid}/publish", json={}, headers=_h(r.mgr)).status_code == 200
    assert bds.get_effective(db, r.t.id, "destination", "chikmagalur") is not None


def test_routes_save_without_the_ai_module_but_others_still_need_it(client, db, r):
    bare = _tenant(db)                                 # no ai_concierge module at all
    res, foh = _user(db, bare.id, UserRole.RESERVATIONS), _user(db, bare.id, UserRole.FOH)
    made = client.post(f"{BD}/records", json={"kind": "destination", "key": "shoolagiri", "data": krs_route(km=200)}, headers=_h(res))
    assert made.status_code == 201, made.text          # a quote-builder role drafts a route with no AI module
    blocked = client.get(f"{BD}/effective/package", headers=_h(foh))   # bookings.read, but no quote-builder capability
    assert blocked.status_code == 403 and blocked.json()["detail"]["error"] == "module_not_enabled"


def test_nobody_but_the_owner_approves_their_own_draft(client, db, r):
    own = client.post(f"{BD}/records", json={"kind": "destination", "key": "hampi", "data": krs_route(km=300)}, headers=_h(r.mgr)).json()
    res = client.post(f"{BD}/records/{own['id']}/publish", json={}, headers=_h(r.mgr))
    assert res.status_code == 403 and res.json()["detail"]["code"] == "self_approval"
    # editing someone else's draft also makes it yours to not approve
    theirs = client.post(f"{BD}/records", json={"kind": "destination", "key": "gokarna", "data": krs_route(km=280)}, headers=_h(r.res)).json()
    assert client.patch(f"{BD}/records/{theirs['id']}", json={"data": krs_route(km=290)}, headers=_h(r.mgr)).status_code == 200
    assert client.post(f"{BD}/records/{theirs['id']}/publish", json={}, headers=_h(r.mgr)).json()["detail"]["code"] == "self_approval"
    # the owner may publish their own
    mine = client.post(f"{BD}/records", json={"kind": "destination", "key": "ooty", "data": krs_route(km=270)}, headers=_h(r.owner)).json()
    assert client.post(f"{BD}/records/{mine['id']}/publish", json={}, headers=_h(r.owner)).status_code == 200
    # roll back and publish in one step is also a self-approval for a manager
    rb = client.post(f"{BD}/records/destination/krs/rollback", json={"to_version": 1, "publish": True}, headers=_h(r.mgr))
    assert rb.status_code == 403 and rb.json()["detail"]["code"] == "self_approval"


def test_policies_stay_with_the_owner(client, db, r):
    body = {"kind": "payment_policy", "data": {"advance_percent": 30, "balance_due_days_before_checkin": 1}}
    res = client.post(f"{BD}/records", json=body, headers=_h(r.res))
    assert res.status_code == 403 and res.json()["detail"]["code"] == "forbidden_kind"
    assert client.post(f"{BD}/records", json=body, headers=_h(r.mgr)).status_code == 403
    pending = db.query(BusinessRecord).filter_by(tenant_id=r.t.id, kind="payment_policy").count()
    assert pending == 1                                                     # only the published one from the fixture
    listed = client.get(f"{BD}/records", headers=_h(r.res)).json()
    assert {g["kind"] for g in listed} <= {"destination", "package", "itinerary"}
    assert client.post(f"{BD}/records", json={"kind": "destination", "key": "x", "data": krs_route()}, headers=_h(r.foh)).status_code == 403


def test_another_tenants_draft_cannot_be_published(client, db, r):
    other = _tenant(db)
    rec = bds.create_draft(db, other.id, "destination", "secret", krs_route(), None)
    db.commit()
    assert client.post(f"{BD}/records/{rec.id}/publish", json={}, headers=_h(r.mgr)).status_code == 404
    assert client.patch(f"{BD}/records/{rec.id}", json={"note": "x"}, headers=_h(r.res)).status_code == 404
