"""Reports by check-in month (checkin_month_report) and the 11:00 daily lead report email + 10:30 reminder
(lead_report_email). Pinned: per check-in month enquiries / valid (effective rule) / won / lost with top reasons / open,
booked revenue only with revenue.read (else restricted, never 0), an unreadable check-in skipped and counted, undated leads in
their own "Date not given yet" row; owner/manager only; another workspace never counted. The email: off by default, the
reminder at 10:30 to reservations/concierge once, the email at 11:00 to owners/managers once (yesterday's report), not
before its time, nothing for a workspace that did not switch it on; settings audited and owner/manager only."""
import uuid
from datetime import date, datetime, timedelta, timezone

from app.models.audit_event import AuditEvent
from app.models.inquiry import LostReason
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, Stay
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import checkin_month_report as cmr, lead_report_email as lre
from app.services.date_presets import IST
from tests.api.test_reports_leads import _headers, _lead, _tenant, _user


def _stages(db, tid):
    won = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key="sold", label="Sold", category="valid", order=9, is_closed_won=True)
    lost = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key="lost", label="Lost", category="valid", order=8, is_closed_lost=True)
    db.add_all([won, lost])
    db.flush()
    return won, lost


def test_checkin_month_rows(client, db):
    t, other = _tenant(db), _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER, "Owner")
    won, lost = _stages(db, t.id)
    a = _lead(db, t.id, name="A", phone="+919845000001", check_in="2026-11-14", stage=won)
    b = _lead(db, t.id, name="B", phone="+919845000002", check_in="2026-11-20", stage=lost)
    b.outcome_reason = "price"
    c = _lead(db, t.id, name="C", phone="+919845000003", check_in="2026-11-21", stage=lost, lost_reason=LostReason.WRONG_DATES)
    _lead(db, t.id, name="D", phone="+919845000004", check_in="2026-12-02")
    _lead(db, t.id, name="E", phone="+919845000005", check_in="2026-11-xx")
    _lead(db, t.id, name="F", phone="+919845000006")
    _lead(db, t.id, name="G", phone="+919845000007", check_in="2026-11-02", lead_type="b2b")
    _lead(db, other.id, name="H", phone="+919845000008", check_in="2026-11-14")
    a.validation_status = "valid"
    prop = Property(id=str(uuid.uuid4()), tenant_id=t.id, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:5]}", type="caravan")
    db.add(prop)
    db.flush()
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=a.guest_id, property_id=prop.id, inquiry_id=a.id, status="confirmed",
                check_in=date(2026, 11, 14), check_out=date(2026, 11, 16), total_amount=60000))
    db.commit()
    res = client.get("/api/v1/reports/checkin-months?start=2026-11&months=2", headers=_headers(owner))
    assert res.status_code == 200, res.text
    body = res.json()
    nov, dec = body["rows"]
    assert (nov["label"], nov["enquiries"], nov["won"], nov["lost"], nov["open"], nov["valid"]) == ("Nov 2026", 3, 1, 2, 0, 1)
    assert {r["reason"]: r["count"] for r in nov["top_lost_reasons"]} == {"price": 1, "dates_unavailable": 1}
    assert nov["booked_revenue"] == 60000 and dec["enquiries"] == 1 and dec["booked_revenue"] == 0
    assert body["skipped"] == 1 and body["no_date"]["label"] == "Date not given yet" and body["no_date"]["enquiries"] == 1


def test_checkin_months_money_restricted_and_roles(client, db):
    t = _tenant(db)
    manager = _user(db, t.id, UserRole.MANAGER, "Mgr")
    concierge = _user(db, t.id, UserRole.CONCIERGE)
    db.commit()
    from app.services import authz_service
    original = authz_service.has_capability
    try:
        authz_service.has_capability = lambda db_, user, cap: False if cap == "revenue.read" else original(db_, user, cap)
        body = client.get("/api/v1/reports/checkin-months?months=1", headers=_headers(manager)).json()
    finally:
        authz_service.has_capability = original
    assert body["rows"][0]["booked_revenue"] == {"restricted": True} and body["money"] is False
    assert client.get("/api/v1/reports/checkin-months", headers=_headers(concierge)).status_code == 403
    assert client.get("/api/v1/reports/checkin-months?months=13", headers=_headers(manager)).status_code == 422
    assert client.get("/api/v1/reports/checkin-months?start=Nov", headers=_headers(manager)).status_code == 422


def _at(hh, mm, day=date(2026, 10, 23)):
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=IST)


def test_daily_email_reminder_then_email_once_each(db):
    t = _tenant(db)
    t.brand_config = {"reports": {"daily_lead_email": {"enabled": True, "hour": 11, "minute": 0}}}
    owner = _user(db, t.id, UserRole.OWNER, "Owner")
    _user(db, t.id, UserRole.MANAGER, "Mgr")
    agent = _user(db, t.id, UserRole.RESERVATIONS, "Res")
    _user(db, t.id, UserRole.FOH, "Foh")
    db.commit()
    mails, pushes = [], []
    send = lambda **kw: mails.append(kw) or True   # noqa: E731
    assert lre.tick(db, t, now=_at(10, 15), sender=send, pusher=pushes.append)["status"] == "idle"
    assert lre.tick(db, t, now=_at(10, 30), sender=send, pusher=pushes.append)["status"] == "reminded"
    assert pushes == [agent.id]
    assert lre.tick(db, t, now=_at(10, 45), sender=send, pusher=pushes.append)["status"] == "idle"     # once a day
    out = lre.tick(db, t, now=_at(11, 0), sender=send, pusher=pushes.append)
    assert out["status"] == "sent" and out["sent"] == 2 and out["report_day"] == "2026-10-22"
    assert {m["to"] for m in mails} == {owner.email, db.query(type(owner)).filter_by(name="Mgr", tenant_id=t.id).one().email}
    assert "daily lead report for 2026-10-22" in mails[0]["subject"]
    assert lre.tick(db, t, now=_at(11, 5), sender=send, pusher=pushes.append)["status"] == "idle"
    assert len(mails) == 2 and db.query(AuditEvent).filter_by(tenant_id=t.id, action="reports.daily_lead_email_sent").count() == 1
    other = _tenant(db)
    db.commit()
    assert lre.tick(db, other, now=_at(11, 0), sender=send)["status"] == "off"


def test_daily_email_settings_owner_manager_audited(client, db):
    t = _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER, "Owner")
    concierge = _user(db, t.id, UserRole.CONCIERGE)
    db.commit()
    assert client.get("/api/v1/reports/daily-lead-email/settings", headers=_headers(owner)).json()["enabled"] is False
    assert client.put("/api/v1/reports/daily-lead-email/settings", headers=_headers(concierge), json={"enabled": True}).status_code == 403
    r = client.put("/api/v1/reports/daily-lead-email/settings", headers=_headers(owner), json={"enabled": True, "hour": 10, "minute": 45})
    assert r.status_code == 200 and (r.json()["enabled"], r.json()["hour"], r.json()["minute"]) == (True, 10, 45)
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="reports.daily_lead_email_changed").count() == 1
    assert client.put("/api/v1/reports/daily-lead-email/settings", headers=_headers(owner), json={"hour": 25}).status_code == 422


def test_seed_script_is_a_dry_run_until_apply(db):
    import importlib.util
    import pathlib
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "seed_ratha_lead_settings.py"
    spec = importlib.util.spec_from_file_location("seed_ratha_lead_settings", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    t = _tenant(db)
    db.commit()
    assert set(mod.plan(t)) == {"lead_validity", "reports.daily_lead_email"}
    mod.apply(db, t)
    db.commit()
    db.expire_all()
    t = db.query(Tenant).filter_by(id=t.id).one()
    assert mod.plan(t) == {}
    assert t.brand_config["lead_validity"]["require_check_in"] is False
    assert t.brand_config["lead_validity"]["allowed_locations"] == ["Bengaluru", "Bangalore"]
    assert t.brand_config["reports"]["daily_lead_email"]["enabled"] is True
