"""The impact view endpoints and the public case study.

Pinned: owner and manager see the view, other roles are refused; baselines are owner-only, audited with before/after, and never
cross workspaces; money needs revenue.read (``{"restricted": true}``, the amounts absent from the payload); a missing or zero
baseline never produces a change; the PDF renders without guest data; the public case study says "coming soon" until the owner
publishes, shows only the frozen aggregate snapshot (no guest data, money only when asked), and goes back on withdraw.
Runs on SQLite and PostgreSQL (no PostgreSQL-only SQL; the public read uses the SECURITY DEFINER function on PostgreSQL).
"""
import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.audit_event import AuditEvent
from app.models.capability import RoleCapability
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.guest import Guest
from app.models.property import Property, Stay
from app.models.stay_finance import StayPayment
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.date_presets import today_ist
from tests.conftest import seed_capabilities

URL = "/api/v1/dashboard/impact"
SECRET_NAME = "Zorbatron Guestperson"
SECRET_PHONE = "+919812345678"


def _tenant(db, name="Ratha"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"ip-{uuid.uuid4().hex[:6]}", plan="growth", timezone="Asia/Kolkata")
    db.add(t); db.commit()
    seed_capabilities(db, t.id)
    return t


def _user(db, tid, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name=role.value, email=f"{role.value}-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password=get_password_hash("pw"), role=role, is_active=True)
    db.add(u); db.commit()
    return u, {"Authorization": f"Bearer {create_access_token({'sub': u.id, 'tenant_id': tid, 'role': role.value})}"}


def _at(days_ago: int, hh: int = 12) -> datetime:
    d = today_ist() - timedelta(days=days_ago)
    return datetime.fromisoformat(f"{d.isoformat()}T{hh:02d}:00:00+05:30").astimezone(timezone.utc)


@pytest.fixture()
def world(db):
    t = _tenant(db)
    owner, h_owner = _user(db, t.id, UserRole.OWNER)
    _, h_manager = _user(db, t.id, UserRole.MANAGER)
    _, h_concierge = _user(db, t.id, UserRole.CONCIERGE)
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name=SECRET_NAME, phone=SECRET_PHONE, lead_identified_at=_at(5))
    db.add(g); db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(c); db.flush()
    for when, direction, delay in ((_at(5, 11), MessageDirection.INBOUND, 0), (_at(5, 11) + timedelta(minutes=3), MessageDirection.OUTBOUND, 0)):
        db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, channel=ChannelType.WHATSAPP, direction=direction,
                       body=f"hello from {SECRET_NAME}", created_at=when, is_ai_generated=direction == MessageDirection.OUTBOUND,
                       sent_autonomously=direction == MessageDirection.OUTBOUND,
                       delivery_state=MessageDeliveryState.SENT if direction == MessageDirection.OUTBOUND else None))
    prop = Property(id=str(uuid.uuid4()), tenant_id=t.id, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:4]}", type="caravan", is_active=True)
    db.add(prop); db.flush()
    stay = Stay(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, property_id=prop.id, check_in=today_ist() + timedelta(days=20),
                check_out=today_ist() + timedelta(days=22), status="confirmed", total_amount=87654, created_at=_at(4))
    db.add(stay); db.flush()
    db.add(StayPayment(tenant_id=t.id, stay_id=stay.id, kind="payment", amount=43210, method="upi", paid_on=today_ist() - timedelta(days=3)))
    db.commit()
    return dict(t=t, owner=owner, h_owner=h_owner, h_manager=h_manager, h_concierge=h_concierge)


def _go_live(client, h, days_ago=20, window=30):
    return client.put(f"{URL}/settings", json={"go_live_date": (today_ist() - timedelta(days=days_ago)).isoformat(), "window_days": window},
                      headers=h)


def _tile(view, key):
    return next(t for t in view["tiles"] if t["key"] == key)


def test_owner_sees_the_view_with_periods_and_definitions(client, world):
    assert _go_live(client, world["h_owner"]).status_code == 200
    r = client.get(URL, headers=world["h_owner"])
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["needs_go_live"] is False and v["can_edit"] is True and v["can_revenue"] is True
    assert v["windows"]["with"]["days"] == 21 and v["windows"]["before"]["days"] == 30
    tile = _tile(v, "first_reply_median_minutes")
    assert tile["with"]["value"] == 3.0 and tile["with"]["n"] == 1 and tile["with"]["period"]["from"]
    assert tile["definition"] and tile["before"]["owner"] is None
    assert tile["change"] is None                                         # no baseline and nothing measured before
    assert v["with"]["replies"]["by_responder"]["ai"]["answered"] == 1
    assert _tile(v, "revenue_booked_per_30d")["with"]["value"] == round(87654 * 30 / 21, 2)
    assert v["revenue"]["restricted"] is False


def test_without_a_go_live_date_the_view_asks_for_one(client, world):
    v = client.get(URL, headers=world["h_manager"]).json()
    assert v["needs_go_live"] is True and v["can_edit"] is False


def test_other_roles_are_refused(client, world):
    assert client.get(URL, headers=world["h_concierge"]).status_code == 403
    assert client.get(f"{URL}/baselines", headers=world["h_concierge"]).status_code == 403
    assert client.get(f"{URL}/export.pdf", headers=world["h_concierge"]).status_code == 403


def test_baseline_crud_is_owner_only_and_audited(client, db, world):
    body = {"value": 240, "period_label": "Jan-Mar 2026", "source_note": "WhatsApp export"}
    assert client.put(f"{URL}/baselines/first_reply_median_minutes", json=body, headers=world["h_manager"]).status_code == 403
    r = client.put(f"{URL}/baselines/first_reply_median_minutes", json=body, headers=world["h_owner"])
    assert r.status_code == 200 and r.json()["value"] == 240 and r.json()["source"] == "owner_entered"
    r = client.put(f"{URL}/baselines/first_reply_median_minutes", json={**body, "value": 180}, headers=world["h_owner"])
    assert r.json()["value"] == 180
    assert client.put(f"{URL}/baselines/not_a_metric", json=body, headers=world["h_owner"]).status_code == 404
    assert client.put(f"{URL}/baselines/first_reply_median_minutes", json={**body, "period_label": " "}, headers=world["h_owner"]).status_code == 422
    listed = client.get(f"{URL}/baselines", headers=world["h_manager"]).json()
    item = next(m for m in listed["metrics"] if m["metric"] == "first_reply_median_minutes")
    assert item["baseline"]["value"] == 180 and listed["can_edit"] is False
    assert client.delete(f"{URL}/baselines/first_reply_median_minutes", headers=world["h_manager"]).status_code == 403
    assert client.delete(f"{URL}/baselines/first_reply_median_minutes", headers=world["h_owner"]).status_code == 204
    assert client.delete(f"{URL}/baselines/first_reply_median_minutes", headers=world["h_owner"]).status_code == 404
    events = db.query(AuditEvent).filter_by(tenant_id=world["t"].id).order_by(AuditEvent.created_at).all()
    actions = [e.action for e in events if e.action.startswith("impact.baseline")]
    assert actions == ["impact.baseline_saved", "impact.baseline_saved", "impact.baseline_deleted"]
    second = [e for e in events if e.action == "impact.baseline_saved"][1]
    assert second.payload["before"]["value"] == 240 and second.payload["after"]["value"] == 180


def test_the_change_uses_the_owner_baseline_and_says_so(client, world):
    _go_live(client, world["h_owner"])
    client.put(f"{URL}/baselines/first_reply_median_minutes", json={"value": 240, "period_label": "Q1 2026"}, headers=world["h_owner"])
    client.put(f"{URL}/baselines/answered_within_15_pct", json={"value": 0, "period_label": "Q1 2026"}, headers=world["h_owner"])
    v = client.get(URL, headers=world["h_owner"]).json()
    t = _tile(v, "first_reply_median_minutes")
    assert t["before"]["owner"]["period_label"] == "Q1 2026" and t["change_against"] == "owner_entered"
    assert t["change"] == {"kind": "pct", "value": -98.8, "better": True}
    assert _tile(v, "answered_within_15_pct")["change"] is None          # a zero baseline is not a baseline


def test_baselines_and_numbers_never_cross_workspaces(client, db, world):
    client.put(f"{URL}/baselines/first_reply_median_minutes", json={"value": 240, "period_label": "Q1"}, headers=world["h_owner"])
    other = _tenant(db, "Other")
    _, h_other = _user(db, other.id, UserRole.OWNER)
    listed = client.get(f"{URL}/baselines", headers=h_other).json()
    assert all(m.get("baseline") is None for m in listed["metrics"])
    _go_live(client, h_other)
    v = client.get(URL, headers=h_other).json()
    assert v["with"]["replies"]["all"]["turns"] == 0 and _tile(v, "revenue_booked_per_30d")["with"]["value"] == 0
    assert client.delete(f"{URL}/baselines/first_reply_median_minutes", headers=h_other).status_code == 404
    assert client.get(URL, headers=world["h_owner"]).json()["saved"]["go_live"] is None   # B's settings are not A's


def test_money_needs_revenue_read(client, db, world):
    _go_live(client, world["h_owner"])
    client.put(f"{URL}/baselines/revenue_booked_per_30d", json={"value": 555555, "period_label": "2025"}, headers=world["h_owner"])
    db.query(RoleCapability).filter_by(tenant_id=world["t"].id, role="manager", capability_key="revenue.read").update({"allowed": False})
    db.commit()
    from app.core.cache import _rdel      # the capability cache (Redis, when running) may hold the old answer
    _rdel(f"cap:{world['t'].id}:manager")
    v = client.get(URL, headers=world["h_manager"]).json()
    assert v["revenue"] == {"restricted": True} and v["can_revenue"] is False
    money = _tile(v, "revenue_booked_per_30d")
    assert money["restricted"] is True and "with" not in money and "before" not in money
    text = json.dumps(v)
    for amount in ("87654", "43210", "555555"):
        assert amount not in text
    listed = client.get(f"{URL}/baselines", headers=world["h_manager"]).json()
    assert "555555" not in json.dumps(listed)
    pdf = client.get(f"{URL}/export.pdf", headers=world["h_manager"])
    assert pdf.status_code == 200 and b"Revenue per month" not in pdf.content


def test_pdf_renders_without_guest_data(client, world):
    assert client.get(f"{URL}/export.pdf", headers=world["h_owner"]).status_code == 422     # no go-live date yet
    _go_live(client, world["h_owner"])
    r = client.get(f"{URL}/export.pdf", headers=world["h_owner"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and len(r.content) > 1500
    assert SECRET_NAME.encode() not in r.content and SECRET_PHONE.encode() not in r.content


def test_settings_validate_and_are_owner_only(client, world):
    assert _go_live(client, world["h_manager"]).status_code == 403
    assert _go_live(client, world["h_owner"], days_ago=-3).status_code == 422             # in the future
    assert _go_live(client, world["h_owner"], window=3).status_code == 422


# ── the public case study ────────────────────────────────────────────────────────────────────────────────────

def _publish(client, h, **kw):
    body = {"slug": "ratha-test", "brand_name": "Ratha", "headline": "Every enquiry answered", "include_revenue": False, **kw}
    return client.post(f"{URL}/case-study/publish", json=body, headers=h)


def test_case_study_is_coming_soon_until_the_owner_publishes(client, db, world):
    assert client.get("/api/v1/case-studies/ratha-test").json() == {"status": "coming_soon", "slug": "ratha-test"}
    assert _publish(client, world["h_owner"]).status_code == 422                          # no go-live date yet
    _go_live(client, world["h_owner"])
    client.put(f"{URL}/baselines/first_reply_median_minutes", json={"value": 240, "period_label": "Q1 2026",
               "source_note": f"told by {SECRET_NAME}"}, headers=world["h_owner"])
    assert _publish(client, world["h_manager"]).status_code == 403
    assert client.get("/api/v1/case-studies/ratha-test").json()["status"] == "coming_soon"
    r = _publish(client, world["h_owner"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"
    pub = client.get("/api/v1/case-studies/ratha-test").json()
    assert pub["status"] == "published" and pub["snapshot"]["brand_name"] == "Ratha"
    tile = next(t for t in pub["snapshot"]["tiles"] if t["key"] == "first_reply_median_minutes")
    assert tile["before"] == {"value": 240.0, "source": "owner_entered", "period": "Q1 2026"} and tile["with"]["value"] == 3.0
    text = json.dumps(pub)
    for secret in (SECRET_NAME, SECRET_PHONE, "87654", "43210", "hello from"):
        assert secret not in text                                                         # no guest data, no money unless asked
    assert any(i["slug"] == "ratha-test" for i in client.get("/api/v1/case-studies").json()["items"])
    actions = [e.action for e in db.query(AuditEvent).filter_by(tenant_id=world["t"].id).all()]
    assert "impact.case_study_published" in actions


def test_the_snapshot_is_frozen_and_withdraw_takes_it_down(client, db, world):
    _go_live(client, world["h_owner"])
    _publish(client, world["h_owner"], include_revenue=True)
    first = client.get("/api/v1/case-studies/ratha-test").json()["snapshot"]
    assert first["includes_revenue"] is True and any(t["unit"] == "inr" for t in first["tiles"])
    client.put(f"{URL}/baselines/first_reply_median_minutes", json={"value": 999, "period_label": "later"}, headers=world["h_owner"])
    assert client.get("/api/v1/case-studies/ratha-test").json()["snapshot"] == first     # a later edit never changes the page
    assert client.post(f"{URL}/case-study/withdraw", headers=world["h_manager"]).status_code == 403
    assert client.post(f"{URL}/case-study/withdraw", headers=world["h_owner"]).json()["status"] == "withdrawn"
    assert client.get("/api/v1/case-studies/ratha-test").json()["status"] == "coming_soon"
    assert client.post(f"{URL}/case-study/withdraw", headers=world["h_owner"]).status_code == 409


def test_a_slug_belongs_to_one_workspace_and_must_be_clean(client, db, world):
    _go_live(client, world["h_owner"])
    assert _publish(client, world["h_owner"], slug="Not OK!").status_code == 422
    assert _publish(client, world["h_owner"]).status_code == 200
    other = _tenant(db, "Other")
    _, h_other = _user(db, other.id, UserRole.OWNER)
    _go_live(client, h_other)
    assert _publish(client, h_other).status_code == 409
    status = client.get(f"{URL}/case-study", headers=h_other).json()
    assert status["status"] == "draft" and status["snapshot"] is None                     # B never sees A's snapshot
    assert client.get("/api/v1/case-studies/Bad_Slug!").json()["status"] == "coming_soon"
