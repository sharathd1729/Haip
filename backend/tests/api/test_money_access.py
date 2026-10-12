"""Who may read booking amounts, targets and executive revenue.

These endpoints used to answer any signed-in user (reproduced for all eight roles in the Owner Dashboard audit,
docs/analytics/OWNER_DASHBOARD_AUDIT.md section 5). They now sit behind the capabilities the product already defines:
  bookings.read -> GET /bookings, GET /bookings/{id}      (owner, manager, reservations, concierge, foh, read_only)
  revenue.read  -> GET /targets*, GET /analytics/executive (owner, manager, marketing)
and the dashboard overview and the MCP dashboard tool stop handing revenue to anyone without revenue.read.

The matrices below are written out by hand on purpose: if a default grant changes, these tests must be changed on
purpose too. SQLite results only; PostgreSQL has not been run for this file.
"""
import uuid
from datetime import date, timedelta

import pytest

from app.api.v1.endpoints import dashboard_overview as overview_module
from app.core.security import create_access_token, get_password_hash
from app.mcp import tools as mcp_tools
from app.models.capability import RoleCapability
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage
from app.models.module import Module, WorkspaceModule
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, Stay
from app.models.stay_finance import StayPayment
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from tests.conftest import seed_capabilities

ROLES = [r.value for r in UserRole]
BOOKINGS_READ = {"owner", "manager", "reservations", "concierge", "foh", "read_only"}
REVENUE_READ = {"owner", "manager", "marketing"}
MONEY = ("48500", "48,500", "20000")


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"m-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush()
    m = db.query(Module).filter_by(code="analytics").first() or Module(id=str(uuid.uuid4()), code="analytics", name="Analytics")
    db.add(m); db.flush()
    db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=t.id, module_id=m.id, enabled=True))
    db.commit()
    seed_capabilities(db, t.id)
    return t


def _user(db, tid, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name=role, email=f"{role}-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password=get_password_hash("pw"), role=UserRole(role), is_active=True)
    db.add(u); db.commit()
    return u, {"Authorization": "Bearer " + create_access_token({"sub": u.id, "tenant_id": tid, "role": role})}


def _booking(db, tid, assigned_to=None, amount=48500):
    p = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Villa", slug=f"v-{uuid.uuid4().hex[:4]}", type="villa", is_active=True)
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Guest", phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add_all([p, g]); db.flush()
    inquiry_id = None
    if assigned_to:
        st = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key="active", label="Active", category="valid", order=1)
        db.add(st); db.flush()
        i = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, stage=InquiryStage.NEW, stage_id=st.id, assigned_to=assigned_to)
        db.add(i); db.flush()
        inquiry_id = i.id
    today = date.today()
    s = Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, property_id=p.id, inquiry_id=inquiry_id, check_in=today + timedelta(days=5),
             check_out=today + timedelta(days=7), status="confirmed", total_amount=amount)
    db.add(s); db.flush()
    db.add(StayPayment(tenant_id=tid, stay_id=s.id, kind="payment", amount=20000, method="upi", paid_on=today))
    db.commit()
    return s


@pytest.fixture()
def world(db):
    t = _tenant(db)
    users = {role: _user(db, t.id, role) for role in ROLES}
    stay = _booking(db, t.id)
    return {"tid": t.id, "users": users, "stay": stay}


def _endpoints(stay):
    month = date.today().strftime("%Y-%m")
    return {
        "bookings": (f"/api/v1/bookings", BOOKINGS_READ),
        "booking detail": (f"/api/v1/bookings/{stay.id}", BOOKINGS_READ),
        "targets list": (f"/api/v1/targets?month={month}", REVENUE_READ),
        "targets pickup": (f"/api/v1/targets/pickup?month={month}", REVENUE_READ),
        "targets agents": (f"/api/v1/targets/agents?month={month}", REVENUE_READ),
        "targets properties": (f"/api/v1/targets/properties?month={month}", REVENUE_READ),
        "targets scopes": ("/api/v1/targets/scopes", REVENUE_READ),
        "executive": ("/api/v1/analytics/executive", REVENUE_READ),
    }


@pytest.mark.parametrize("name", ["bookings", "booking detail", "targets list", "targets pickup", "targets agents",
                                  "targets properties", "targets scopes", "executive"])
def test_each_money_endpoint_answers_exactly_the_roles_that_hold_the_capability(client, world, name):
    path, allowed = _endpoints(world["stay"])[name]
    for role, (_, headers) in world["users"].items():
        r = client.get(path, headers=headers)
        expected = 200 if role in allowed else 403
        assert r.status_code == expected, f"{name} as {role}: expected {expected}, got {r.status_code}"


def test_a_signed_out_caller_gets_nothing(client, world):
    for name, (path, _) in _endpoints(world["stay"]).items():
        assert client.get(path).status_code in (401, 403), name


def test_a_refused_role_receives_no_amounts_in_the_error(client, world):
    _, headers = world["users"]["compliance"]
    for name in ("bookings", "booking detail", "executive", "targets agents"):
        r = client.get(_endpoints(world["stay"])[name][0], headers=headers)
        assert r.status_code == 403 and not any(m in r.text for m in MONEY)


def test_the_workspace_owner_can_take_a_capability_away_from_a_role(client, db, world):
    """The matrix is per workspace data, not code: revoking revenue.read from managers closes the endpoints to them."""
    row = db.query(RoleCapability).filter_by(tenant_id=world["tid"], role="manager", capability_key="revenue.read").one()
    row.allowed = False
    db.commit()
    _, headers = world["users"]["manager"]
    assert client.get("/api/v1/analytics/executive", headers=headers).status_code == 403
    assert client.get(f"/api/v1/targets/pickup?month={date.today():%Y-%m}", headers=headers).status_code == 403
    assert client.get("/api/v1/bookings", headers=headers).status_code == 200      # a different capability, untouched


def test_another_workspaces_booking_is_not_found_even_for_its_owner(client, db, world):
    other = _tenant(db)
    _, h_other_owner = _user(db, other.id, "owner")
    assert client.get(f"/api/v1/bookings/{world['stay'].id}", headers=h_other_owner).status_code == 404
    body = client.get("/api/v1/bookings", headers=h_other_owner).text
    assert not any(m in body for m in MONEY)


# ── the dashboard overview and the MCP dashboard tool ────────────────────────────────────────────────────────

@pytest.fixture()
def overview_world(db, monkeypatch):
    """Two bookings: one linked to the agent's lead, one the workspace's own. The overview's PostgreSQL-only
    response-time helpers are faked; every number asserted comes from the real queries."""
    monkeypatch.setattr(overview_module, "chat_response_avg_seconds", lambda *a, **k: 0.0)
    monkeypatch.setattr(overview_module, "get_agent_scorecard_rows", lambda *a, **k: [])
    t = _tenant(db)
    owner, h_owner = _user(db, t.id, "owner")
    agent, h_agent = _user(db, t.id, "concierge")
    _booking(db, t.id, assigned_to=agent.id, amount=48500)       # the agent's
    _booking(db, t.id, amount=111111)                            # not linked to anyone
    return {"tid": t.id, "owner": owner, "h_owner": h_owner, "agent": agent, "h_agent": h_agent}


def _overview(client, headers):
    today = date.today().isoformat()
    # check_in is 5 days out, so widen the window to cover it
    return client.get("/api/v1/dashboard/overview", params={"date_preset": "custom", "date_from": today,
                      "date_to": (date.today() + timedelta(days=30)).isoformat()}, headers=headers)


def test_the_overview_gives_the_owner_workspace_wide_revenue(client, overview_world):
    j = _overview(client, overview_world["h_owner"]).json()
    assert j["revenue_restricted"] is False
    assert j["kpi"]["bookings"] == 2 and j["kpi"]["revenue"] == 48500 + 111111
    assert j["series"]["revenue"] is not None


def test_the_overview_gives_an_agent_no_revenue_and_only_their_own_bookings(client, overview_world):
    r = _overview(client, overview_world["h_agent"])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["revenue_restricted"] is True
    assert j["kpi"]["revenue"] is None                       # withheld, not 0
    assert "revenue" not in j["kpi_deltas"]
    assert j["kpi"]["bookings"] == 1                         # theirs, not the workspace's two
    assert j["series"]["revenue"] is None and j["series"]["prev_revenue"] is None and j["series"]["bookings"] is None
    assert "111111" not in r.text and "159611" not in r.text


def test_the_mcp_dashboard_tool_withholds_revenue_without_revenue_read(db, overview_world):
    owner, agent = overview_world["owner"], overview_world["agent"]
    seen_by_owner = mcp_tools._get_dashboard_metrics(db, owner, owner.tenant_id, {})
    assert seen_by_owner["revenue_mtd"] is not None and "revenue_restricted" not in seen_by_owner
    seen_by_agent = mcp_tools._get_dashboard_metrics(db, agent, agent.tenant_id, {})
    assert seen_by_agent["revenue_restricted"] is True
    assert seen_by_agent["revenue_mtd"] is None and seen_by_agent["revenue_mtd_prev"] is None and seen_by_agent["revenue_chart"] is None
    assert seen_by_agent["occupancy_pct"] is not None        # the non-money KPIs are still delivered


# ── the portfolio calendar and the revenue report ────────────────────────────────────────────────────────────

def _calendar_path():
    today = date.today()
    return f"/api/v1/calendar?from_date={today}&to_date={today + timedelta(days=8)}"


def test_the_calendar_is_a_bookings_view_and_shows_amounts_only_with_revenue_read(client, world):
    path = _calendar_path()
    for role, (_, headers) in world["users"].items():
        r = client.get(path, headers=headers)
        if role not in BOOKINGS_READ:
            assert r.status_code == 403, f"calendar as {role}"
            assert not any(m in r.text for m in MONEY)
            continue
        assert r.status_code == 200, f"calendar as {role}"
        body, text = r.json(), r.text
        stay = next(s for row in body["properties"] for s in row["stays"])
        assert stay["guest_name"]                                           # operations data is still there
        if role in REVENUE_READ:
            assert stay["total_amount"] == 48500.0 and body["stats"]["revenue_restricted"] is False
            assert body["stats"]["revenue_locked"] == 48500.0
        else:
            assert stay["total_amount"] is None and body["stats"]["revenue_restricted"] is True
            assert body["stats"]["revenue_locked"] is None and body["stats"]["revenue_quoted"] is None
            assert all(row["monthly_revenue"] is None for row in body["properties"])
            assert not any(m in text for m in MONEY), f"amount leaked to {role}"


def test_another_workspaces_owner_sees_none_of_this_calendar(client, db, world):
    other = _tenant(db)
    _, h = _user(db, other.id, "owner")
    r = client.get(_calendar_path(), headers=h)
    assert r.status_code == 200 and not any(m in r.text for m in MONEY) and "Guest" not in r.text


def test_a_signed_out_caller_gets_no_calendar(client, world):
    assert client.get(_calendar_path()).status_code in (401, 403)


def _report(client, headers, how="preview"):
    body = {"report_id": "revenue", "fields": ["booking_date", "guest_name", "total_revenue"]}
    if how == "preview":
        return client.post("/api/v1/reports/preview", json=body, headers=headers)
    if how == "download":
        return client.post("/api/v1/reports/download?format=json", json=body, headers=headers)
    return client.get("/api/v1/reports/export?report_id=revenue&format=json", headers=headers)


@pytest.mark.parametrize("how", ["preview", "download", "export"])
def test_the_revenue_report_needs_revenue_read_on_top_of_report_access(client, world, how):
    for role, (_, headers) in world["users"].items():
        r = _report(client, headers, how)
        if role in ("owner", "manager"):
            assert r.status_code == 200, f"{how} as {role}: {r.text[:200]}"
        else:
            assert r.status_code == 403, f"{how} as {role}: expected 403, got {r.status_code}"
            assert not any(m in r.text for m in MONEY)


def test_the_revenue_report_is_missing_from_the_catalog_of_roles_without_revenue_read(client, world):
    def ids(role):
        return {e["id"] for e in client.get("/api/v1/reports/catalog", headers=world["users"][role][1]).json()}
    assert "revenue" in ids("owner") and "revenue" in ids("manager")
    assert "revenue" not in ids("compliance")           # compliance runs most reports but holds no revenue capability
    assert "calls" in ids("compliance")                  # ...and keeps the rest
