"""Shared KPI calculations (app/services/kpi_metrics.py).

Two things are pinned:
  1. each shared metric behaves as the catalogue says: period boundaries (including the IST day edge), empty data,
     filters, and tenant isolation;
  2. every dashboard / report that shows the metric returns the SAME number for the same data. That second part is
     the point of a shared layer: the "New leads" tile, its sparkline, the lead-source split and the daily owner
     email used to be four copies of one query.

Runs on SQLite and PostgreSQL alike (nothing here is PostgreSQL-specific). The dashboard overview endpoint itself
calls PostgreSQL-only response-time SQL, so its two helpers are replaced with fakes in the parity test; every number
asserted there comes from the real lead query.
"""
import pathlib
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.api.v1.endpoints import dashboard_overview as overview_module
from app.core.security import create_access_token, get_password_hash
from app.models.capability import Capability, RoleCapability
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.module import Module, WorkspaceModule
from app.models.property import Property, Stay
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import daily_report_service, dashboard_service, kpi_metrics
from app.services.date_presets import IST, ist_range_to_utc


# ── helpers ────────────────────────────────────────────────────────────────────────────────────────────────

def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"k-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush()
    return t


def _guest(db, tid):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone=f"+9197{uuid.uuid4().int % 10**8:08d}")
    db.add(g); db.flush()
    return g


def _user(db, tid, role=UserRole.CONCIERGE):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name="U", email=f"u-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password=get_password_hash("pw"), role=role, is_active=True)
    db.add(u); db.flush()
    return u


def _lead(db, tid, when, *, qualification="qualified", assigned_to=None, property_id=None,
          source=InquirySource.WA_DIRECT):
    g = _guest(db, tid)
    i = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, stage=InquiryStage.NEW, source=source,
                created_at=when, qualification_status=qualification, assigned_to=assigned_to, property_id=property_id)
    db.add(i); db.flush()
    return i


def _prop(db, tid, name="Villa"):
    p = Property(id=str(uuid.uuid4()), tenant_id=tid, name=name, slug=f"{name.lower()}-{uuid.uuid4().hex[:4]}",
                 type="villa", is_active=True)
    db.add(p); db.flush()
    return p


def _stay(db, tid, prop, check_in, nights, status="confirmed"):
    g = _guest(db, tid)
    s = Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, property_id=prop.id, check_in=check_in,
             check_out=check_in + timedelta(days=nights), status=status, total_amount=1000)
    db.add(s); db.flush()
    return s


def _ist_day_bounds(day: date):
    start_iso, end_iso, start_dt, end_dt = ist_range_to_utc(day.isoformat(), day.isoformat())
    return start_iso, end_iso, start_dt, end_dt


DAY = date(2026, 10, 11)                       # a fixed IST calendar day
NOON_IST = datetime(2026, 10, 11, 12, 0, tzinfo=IST).astimezone(timezone.utc)


# ── leads.new ──────────────────────────────────────────────────────────────────────────────────────────────

def test_leads_inside_the_period_are_counted_and_empty_data_is_zero(db):
    t = _tenant(db)
    _, _, start, end = _ist_day_bounds(DAY)
    assert kpi_metrics.count_leads(db, t.id, start, end) == 0
    _lead(db, t.id, NOON_IST)
    _lead(db, t.id, NOON_IST + timedelta(hours=3))
    db.commit()
    assert kpi_metrics.count_leads(db, t.id, start, end) == 2


def test_the_ist_day_edges_decide_which_day_a_lead_belongs_to(db):
    """23:59 IST on the 11th is in the 11th; 00:00 IST on the 12th is not. (UTC would put them on other days.)"""
    t = _tenant(db)
    last_minute = datetime(2026, 10, 11, 23, 59, tzinfo=IST).astimezone(timezone.utc)
    next_midnight = datetime(2026, 10, 12, 0, 0, tzinfo=IST).astimezone(timezone.utc)
    first_minute = datetime(2026, 10, 11, 0, 0, tzinfo=IST).astimezone(timezone.utc)
    before = first_minute - timedelta(minutes=1)
    for when in (last_minute, next_midnight, first_minute, before):
        _lead(db, t.id, when)
    db.commit()
    _, _, start, end = _ist_day_bounds(DAY)
    assert kpi_metrics.count_leads(db, t.id, start, end) == 2      # first_minute and last_minute only


def test_iso_string_bounds_and_datetime_bounds_give_the_same_answer(db):
    """Callers pass both forms (ist_range_to_utc returns both); a string must not be compared as text."""
    t = _tenant(db)
    _lead(db, t.id, NOON_IST)
    db.commit()
    start_iso, end_iso, start_dt, end_dt = _ist_day_bounds(DAY)
    assert kpi_metrics.count_leads(db, t.id, start_iso, end_iso) == kpi_metrics.count_leads(db, t.id, start_dt, end_dt) == 1


def test_unqualified_enquiries_are_not_leads(db):
    t = _tenant(db)
    _lead(db, t.id, NOON_IST)
    _lead(db, t.id, NOON_IST, qualification="unqualified")
    db.commit()
    _, _, start, end = _ist_day_bounds(DAY)
    assert kpi_metrics.count_leads(db, t.id, start, end) == 1


def test_an_agent_sees_only_their_own_leads_and_a_property_filter_narrows(db):
    t = _tenant(db)
    mine, theirs = _user(db, t.id), _user(db, t.id)
    p1, p2 = _prop(db, t.id, "A"), _prop(db, t.id, "B")
    _lead(db, t.id, NOON_IST, assigned_to=mine.id, property_id=p1.id)
    _lead(db, t.id, NOON_IST, assigned_to=mine.id, property_id=p2.id)
    _lead(db, t.id, NOON_IST, assigned_to=theirs.id, property_id=p1.id)
    _lead(db, t.id, NOON_IST)                                                   # unassigned
    db.commit()
    _, _, start, end = _ist_day_bounds(DAY)
    assert kpi_metrics.count_leads(db, t.id, start, end) == 4
    assert kpi_metrics.count_leads(db, t.id, start, end, scope_user_id=mine.id) == 2
    assert kpi_metrics.count_leads(db, t.id, start, end, property_id=p1.id) == 2
    assert kpi_metrics.count_leads(db, t.id, start, end, scope_user_id=mine.id, property_id=p1.id) == 1


def test_leads_never_cross_tenants(db):
    a, b = _tenant(db), _tenant(db)
    _lead(db, a.id, NOON_IST)
    _lead(db, a.id, NOON_IST)
    _lead(db, b.id, NOON_IST)
    db.commit()
    _, _, start, end = _ist_day_bounds(DAY)
    assert kpi_metrics.count_leads(db, a.id, start, end) == 2
    assert kpi_metrics.count_leads(db, b.id, start, end) == 1
    assert kpi_metrics.count_leads(db, str(uuid.uuid4()), start, end) == 0


# ── every consumer of leads.new agrees ─────────────────────────────────────────────────────────────────────

def _seed_a_day_of_leads(db):
    t = _tenant(db)
    sources = [InquirySource.META_IG, InquirySource.WA_DIRECT, InquirySource.PHONE, InquirySource.WEBSITE, InquirySource.META_IG]
    for n, src in enumerate(sources):
        _lead(db, t.id, NOON_IST + timedelta(minutes=n), source=src)
    _lead(db, t.id, NOON_IST, qualification="unqualified")                                       # must be ignored everywhere
    _lead(db, t.id, NOON_IST + timedelta(days=1))                                                # a different IST day
    other = _tenant(db)
    _lead(db, other.id, NOON_IST)                                                                # another tenant
    db.commit()
    return t, len(sources)


def test_dashboard_sources_series_and_daily_report_return_the_same_lead_count(db):
    t, expected = _seed_a_day_of_leads(db)
    start_iso, end_iso, start_dt, end_dt = _ist_day_bounds(DAY)

    shared = kpi_metrics.count_leads(db, t.id, start_dt, end_dt)
    by_source = sum(r["count"] for r in dashboard_service.lead_sources(db, t.id, None, start_iso, end_iso))
    series = dashboard_service.daily_series(db, t, None, DAY.isoformat(), DAY.isoformat())
    in_series = series["leads"][series["days"].index(DAY.isoformat())]
    report = daily_report_service.build_daily_report(db, t.id, day=DAY.isoformat())["metrics"]["new_leads"]

    assert shared == by_source == in_series == report == expected


def test_the_dashboard_overview_endpoint_reports_the_same_lead_count(client, db, monkeypatch):
    """GET /dashboard/overview -> kpi.total_leads. Its response-time helpers are PostgreSQL-only SQL, so they are
    replaced with fakes; the lead number comes from the real query."""
    t, expected = _seed_a_day_of_leads(db)
    owner = _user(db, t.id, UserRole.OWNER)
    module = db.query(Module).filter_by(code="analytics").first()
    if not module:
        module = Module(id=str(uuid.uuid4()), code="analytics", name="Analytics"); db.add(module); db.flush()
    db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=t.id, module_id=module.id, enabled=True))
    cap = db.query(Capability).filter_by(key="analytics.read").first()
    if not cap:
        cap = Capability(key="analytics.read", label="analytics.read", category="analytics", is_write=False, risk="low")
        db.add(cap); db.flush()
    db.add(RoleCapability(id=str(uuid.uuid4()), tenant_id=t.id, role="owner", capability_key="analytics.read", allowed=True))
    db.commit()
    monkeypatch.setattr(overview_module, "chat_response_avg_seconds", lambda *a, **k: 0.0)
    monkeypatch.setattr(overview_module, "get_agent_scorecard_rows", lambda *a, **k: [])
    headers = {"Authorization": "Bearer " + create_access_token({"sub": owner.id, "tenant_id": t.id, "role": "owner"})}

    resp = client.get(f"/api/v1/dashboard/overview?date_preset=custom&date_from={DAY.isoformat()}&date_to={DAY.isoformat()}",
                      headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["kpi"]["total_leads"] == expected


# ── stays.occupied_nights ──────────────────────────────────────────────────────────────────────────────────

D1 = date(2026, 10, 1)
D31 = date(2026, 10, 31)


def test_nights_are_counted_without_the_checkout_day(db):
    t = _tenant(db); p = _prop(db, t.id)
    _stay(db, t.id, p, date(2026, 10, 10), 3)          # nights of the 10th, 11th, 12th
    db.commit()
    assert kpi_metrics.occupied_nights(db, t.id, D1, D31) == 3


def test_a_stay_is_clipped_to_the_window_on_both_sides(db):
    t = _tenant(db); p = _prop(db, t.id)
    _stay(db, t.id, p, date(2026, 9, 28), 6)           # 28 Sep .. 4 Oct: only 1, 2, 3 Oct are inside
    _stay(db, t.id, p, date(2026, 10, 29), 5)          # 29 Oct .. 3 Nov: only 29 and 30 Oct are inside [1 Oct, 31 Oct)
    db.commit()
    assert kpi_metrics.occupied_nights(db, t.id, D1, D31) == 3 + 2


def test_a_stay_ending_on_the_first_day_of_the_window_contributes_nothing(db):
    t = _tenant(db); p = _prop(db, t.id)
    _stay(db, t.id, p, date(2026, 9, 29), 2)           # checks out on 1 Oct: its nights were 29 and 30 Sep
    _stay(db, t.id, p, date(2026, 10, 31), 2)          # checks in on the window's (exclusive) end day
    db.commit()
    assert kpi_metrics.occupied_nights(db, t.id, D1, D31) == 0


def test_cancelled_stays_do_not_occupy_and_the_caller_can_choose_the_statuses(db):
    t = _tenant(db); p = _prop(db, t.id)
    _stay(db, t.id, p, date(2026, 10, 5), 2, status="confirmed")
    _stay(db, t.id, p, date(2026, 10, 8), 2, status="cancelled")
    _stay(db, t.id, p, date(2026, 10, 12), 2, status="checked_out")
    db.commit()
    assert kpi_metrics.occupied_nights(db, t.id, D1, D31) == 4                                  # confirmed + checked_out
    assert kpi_metrics.occupied_nights(db, t.id, D1, D31, statuses=("confirmed",)) == 2


def test_occupied_nights_can_be_limited_to_properties_and_never_cross_tenants(db):
    a, b = _tenant(db), _tenant(db)
    p1, p2, pb = _prop(db, a.id, "One"), _prop(db, a.id, "Two"), _prop(db, b.id, "Other")
    _stay(db, a.id, p1, date(2026, 10, 5), 2)
    _stay(db, a.id, p2, date(2026, 10, 5), 3)
    _stay(db, b.id, pb, date(2026, 10, 5), 4)
    db.commit()
    assert kpi_metrics.occupied_nights(db, a.id, D1, D31) == 5
    assert kpi_metrics.occupied_nights(db, a.id, D1, D31, property_ids=[p1.id]) == 2
    assert kpi_metrics.occupied_nights(db, a.id, D1, D31, property_ids=[pb.id]) == 0     # another tenant's property: nothing
    assert kpi_metrics.occupied_nights(db, b.id, D1, D31) == 4


def test_empty_and_inverted_windows_are_zero(db):
    t = _tenant(db); p = _prop(db, t.id)
    _stay(db, t.id, p, date(2026, 10, 5), 2)
    db.commit()
    assert kpi_metrics.occupied_nights(db, t.id, D31, D1) == 0
    assert kpi_metrics.occupied_nights(db, t.id, D1, D1) == 0
    assert kpi_metrics.occupied_nights(db, str(uuid.uuid4()), D1, D31) == 0


# ── the registry and the catalogue cannot drift apart ──────────────────────────────────────────────────────

CATALOGUE = pathlib.Path(__file__).resolve().parents[3] / "docs" / "analytics" / "KPI_METRIC_CATALOGUE.md"


@pytest.mark.skipif(not CATALOGUE.exists(), reason="docs are not part of the deployed image")
def test_every_shared_metric_is_documented_in_the_catalogue():
    text = CATALOGUE.read_text(encoding="utf-8")
    missing = [m for m in kpi_metrics.CANONICAL_METRICS if f"`{m}`" not in text]
    assert not missing, f"add these shared metrics to docs/analytics/KPI_METRIC_CATALOGUE.md: {missing}"
