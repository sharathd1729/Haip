"""The automatic valid-lead rule (lead_validity; KPI D-28). Pinned: name / phone / location Bengaluru decide it, each one
configurable; a missing check-in date (and an unknown location) is a NOTE, not an invalid reason, unless required; a known
other city is invalid; B2B / partner is never valid; a person's review overrides the rule; the Leads list filters and badges
by the effective validity; the daily report and check-in coverage use it (undated valid leads counted apart); the settings
are owner/manager only, audited, and PATCH /tenants/me refuses them; another workspace's leads never match."""
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.audit_event import AuditEvent
from app.models.guest import Guest
from app.models.pipeline_stage import PipelineStage
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import checkin_coverage, lead_validity as lv
from tests.api.test_reports_leads import _headers, _lead, _tenant, _user

RATHAA = {"enabled": True, "require_name": True, "require_phone": True, "require_check_in": False, "require_location": False,
          "allowed_locations": ["Bengaluru", "Bangalore"], "location_field": "guest_location"}
IST = timezone(timedelta(hours=5, minutes=30))


def _inq(**kw):
    base = dict(lead_type="guest", validation_status=None, check_in="2026-11-14", guest_location="bangalore ", custom_fields={})
    return SimpleNamespace(**{**base, **kw})


def _guest(**kw):
    base = dict(name="Ravi Kumar", phone="+919845012345", lead_identified_at=datetime.now(timezone.utc), city=None)
    return SimpleNamespace(**{**base, **kw})


def test_rule_reasons_and_notes():
    cfg = lv.settings_of(SimpleNamespace(brand_config={"lead_validity": RATHAA}))
    ok = lv.evaluate(_inq(), _guest(), cfg)
    assert ok == {"auto_valid": True, "reasons": [], "notes": [], "location": "bangalore"}
    undated = lv.evaluate(_inq(check_in=None, guest_location=None), _guest(), cfg)
    assert undated["auto_valid"] is True and undated["notes"] == ["No check-in date yet", "Location not known yet"]
    bad = lv.evaluate(_inq(guest_location="Hyderabad"), _guest(name="9845012345", phone="", lead_identified_at=None), cfg)
    assert bad["auto_valid"] is False
    assert bad["reasons"] == ["No name", "No phone", "Location: Hyderabad (not Bengaluru)"]
    strict = lv.settings_of(SimpleNamespace(brand_config={"lead_validity": {**RATHAA, "require_check_in": True, "require_location": True}}))
    assert lv.evaluate(_inq(check_in="soon", guest_location=None), _guest(), strict)["reasons"] == ["No check-in date", "No location"]
    assert lv.evaluate(_inq(lead_type="b2b"), _guest(), cfg)["auto_valid"] is False
    assert lv.evaluate(_inq(), _guest(), lv.settings_of(SimpleNamespace(brand_config={})))["auto_valid"] is None   # rule off


def test_person_overrides_rule_and_b2b_is_never_valid():
    auto_bad = {"auto_valid": False}
    assert lv.effective(_inq(validation_status="valid"), auto_bad) == {"status": "valid", "source": "person"}
    assert lv.effective(_inq(validation_status=None), auto_bad) == {"status": "invalid", "source": "rule"}
    assert lv.effective(_inq(validation_status=None), {"auto_valid": None}) == {"status": None, "source": None}
    assert lv.effective(_inq(lead_type="partner", validation_status="valid"), {"auto_valid": True})["status"] == "invalid"


def test_location_field_choices_and_route_origin():
    assert lv.location_of(_inq(custom_fields={"pickup": "Whitefield"}), _guest(), "pickup") == "Whitefield"
    assert lv.location_of(_inq(), _guest(city="Mysuru"), "guest_city") == "Mysuru"
    assert lv.origin_of_route("Bangalore to Coorg") == "Bangalore"
    assert lv.origin_of_route("from Bengaluru -> Mysuru") == "Bengaluru"
    assert lv.origin_of_route("Coorg") is None


def _rathaa(db, t):
    t.brand_config = {"lead_validity": RATHAA}
    db.flush()


def _identified(db, inq):
    g = db.query(Guest).filter_by(id=inq.guest_id).one()
    g.lead_identified_at = datetime.now(timezone.utc)


def test_leads_list_filters_and_badges_by_effective_validity(client, db):
    t, other = _tenant(db), _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER, "Owner")
    _rathaa(db, t)
    _rathaa(db, other)
    good = _lead(db, t.id, name="Ravi", phone="+919845000001", check_in="2026-11-14", guest_location="Bengaluru")
    away = _lead(db, t.id, name="Meera", phone="+919845000002", guest_location="Hyderabad")
    saved = _lead(db, t.id, name="Unknown", phone="", guest_location="Hyderabad")
    saved.validation_status = "valid"
    elsewhere = _lead(db, other.id, name="Asha", phone="+919845000003", guest_location="Bengaluru")
    for i in (good, away, elsewhere):
        _identified(db, i)
    db.commit()
    res = client.get("/api/v1/leads?validity=valid", headers=_headers(owner))
    assert res.status_code == 200, res.text
    cards = {c["inquiry_id"]: c for c in res.json()["leads"]}
    assert set(cards) == {good.id, saved.id}
    assert cards[saved.id]["validity"]["source"] == "person" and cards[saved.id]["validity"]["auto_valid"] is False
    invalid = client.get("/api/v1/leads?validity=invalid", headers=_headers(owner)).json()["leads"]
    assert [c["inquiry_id"] for c in invalid] == [away.id]
    assert invalid[0]["validity"]["reasons"] == ["Location: Hyderabad (not Bengaluru)"]
    assert client.get("/api/v1/leads?validity=maybe", headers=_headers(owner)).status_code == 422


def test_daily_report_and_coverage_use_the_rule_and_count_undated_apart(client, db):
    t = _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER, "Owner")
    _rathaa(db, t)
    stage = PipelineStage(id=str(uuid.uuid4()), tenant_id=t.id, key="general_enquiry", label="Enquiry", category="invalid", order=1)
    db.add(stage)
    today = date.today()
    dated = _lead(db, t.id, name="Ravi", phone="+919845000001", check_in=(today + timedelta(days=2)).isoformat(),
                  guest_location="Bangalore", stage=stage, owner=owner)
    undated = _lead(db, t.id, name="Kiran", phone="+919845000004", stage=stage, owner=owner)
    for i in (dated, undated):
        _identified(db, i)
    db.commit()
    cov = checkin_coverage.build(db, t.id, today, today + timedelta(days=6))
    assert cov["basis_kind"] == "rule" and cov["no_date_valid"] == 1
    assert sum(d["stage_valid"] for d in cov["days"]) == 1          # valid by the rule though its stage is "invalid"
    day = datetime.now(IST).date().isoformat()
    rep = client.get(f"/api/v1/reports/daily-validation?date={day}", headers=_headers(owner)).json()
    assert rep["validity_rule"]["enabled"] is True and rep["total"]["automatic"]["valid_now"] == 2


def test_settings_are_owner_manager_only_audited_and_not_via_tenants_me(client, db):
    t = _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER, "Owner")
    concierge = _user(db, t.id, UserRole.CONCIERGE)
    db.commit()
    assert client.get("/api/v1/lead-validity/settings", headers=_headers(owner)).json()["enabled"] is False
    assert client.put("/api/v1/lead-validity/settings", headers=_headers(concierge), json={"enabled": True}).status_code == 403
    res = client.put("/api/v1/lead-validity/settings", headers=_headers(owner),
                     json={"enabled": True, "allowed_locations": [" Bengaluru ", "Bangalore", ""], "location_field": "pickup"})
    assert res.status_code == 200 and res.json()["allowed_locations"] == ["Bengaluru", "Bangalore"]
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="lead_validity.settings_changed").count() == 1
    db.expire_all()
    assert db.query(Tenant).filter_by(id=t.id).one().brand_config["lead_validity"]["location_field"] == "pickup"
    bad = client.patch("/api/v1/tenants/me", headers=_headers(owner), json={"brand_config": {"lead_validity": {"enabled": False}}})
    assert bad.status_code == 422


def test_guest_location_is_editable_on_the_lead(client, db):
    t = _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER, "Owner")
    inq = _lead(db, t.id, name="Ravi", phone="+919845000001")
    db.commit()
    res = client.patch(f"/api/v1/inquiries/{inq.id}", headers=_headers(owner), json={"guest_location": " Bengaluru "})
    assert res.status_code == 200, res.text
    db.refresh(inq)
    assert inq.guest_location == "Bengaluru"
