"""
Tests for GET /guests/{id}/journey — the ledger-backed Guest Journey (Phase 4).

  happy path    : events come back newest-first
  cross-inquiry : the journey spans every inquiry, which /timeline cannot do
  messages      : messages appear here — the legacy /timeline omits them entirely
  cross-tenant  : another tenant's guest is 404, not a data leak
  cap           : limit is honoured and reports capped
  DPDP          : deleting a guest purges their ledger rows (they hold previews)
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.models.guest_event import GuestEvent
from app.schemas.guest_events import GuestEventCreate, GuestEventType, SourceModule
from app.services import guest_events_service as ges
from app.core.security import create_access_token, get_password_hash


def _tenant(db, name="T"):
    t = Tenant(id=str(uuid.uuid4()), name=name,
               slug=f"gj-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _user(db, tenant_id, role=UserRole.OWNER):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name="U",
             email=f"u-{uuid.uuid4().hex[:6]}@test.com",
             hashed_password=get_password_hash("pw"), role=role, is_active=True)
    db.add(u); db.flush(); return u


def _guest(db, tenant_id, name="G"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone="")
    db.add(g); db.flush(); return g


def _auth(user):
    tok = create_access_token(
        {"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value}
    )
    return {"Authorization": f"Bearer {tok}"}


def _event(db, tenant_id, guest_id, **kw):
    base = dict(
        guest_id=guest_id,
        entity_type="message",
        entity_id=str(uuid.uuid4()),
        event_type=GuestEventType.MESSAGE_RECEIVED,
        source_module=SourceModule.INBOX,
        occurred_at=datetime.now(timezone.utc),
        channel="whatsapp",
        direction="inbound",
        preview="hello",
    )
    base.update(kw)
    return ges.record_event(db, tenant_id, GuestEventCreate(**base))


def test_journey_returns_events_newest_first(client, db):
    t = _tenant(db); u = _user(db, t.id); g = _guest(db, t.id)
    now = datetime.now(timezone.utc)
    _event(db, t.id, g.id, preview="older", occurred_at=now - timedelta(hours=2))
    _event(db, t.id, g.id, preview="newer", occurred_at=now)
    db.commit()

    res = client.get(f"/api/v1/guests/{g.id}/journey", headers=_auth(u))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["guest_id"] == g.id
    assert body["total_returned"] == 2
    assert body["capped"] is False
    assert [e["preview"] for e in body["events"]] == ["newer", "older"]


def test_journey_spans_multiple_inquiries(client, db):
    """The gap the per-inquiry timeline could never fill."""
    t = _tenant(db); u = _user(db, t.id); g = _guest(db, t.id)
    inq_a, inq_b = str(uuid.uuid4()), str(uuid.uuid4())
    _event(db, t.id, g.id, inquiry_id=inq_a, preview="first stay")
    _event(db, t.id, g.id, inquiry_id=inq_b, preview="repeat booking")
    db.commit()

    res = client.get(f"/api/v1/guests/{g.id}/journey", headers=_auth(u))
    assert res.status_code == 200
    assert {e["inquiry_id"] for e in res.json()["events"]} == {inq_a, inq_b}


def test_journey_includes_messages_unlike_legacy_timeline(client, db):
    """/timeline queries conversations but never emits them as events, so
    messages are invisible there. They must be visible here."""
    t = _tenant(db); u = _user(db, t.id); g = _guest(db, t.id)
    _event(db, t.id, g.id, preview="guest asked about pricing")
    db.commit()

    journey = client.get(f"/api/v1/guests/{g.id}/journey", headers=_auth(u)).json()
    assert any(e["entity_type"] == "message" for e in journey["events"])

    legacy = client.get(f"/api/v1/guests/{g.id}/timeline", headers=_auth(u)).json()
    assert not any(e.get("type") == "message" for e in legacy["events"])


def test_journey_respects_limit_and_reports_capped(client, db):
    t = _tenant(db); u = _user(db, t.id); g = _guest(db, t.id)
    now = datetime.now(timezone.utc)
    for i in range(5):
        _event(db, t.id, g.id, preview=f"m{i}", occurred_at=now - timedelta(minutes=i))
    db.commit()

    res = client.get(f"/api/v1/guests/{g.id}/journey?limit=3", headers=_auth(u))
    body = res.json()
    assert body["total_returned"] == 3
    assert body["capped"] is True


def test_journey_cross_tenant_is_404(client, db):
    t1 = _tenant(db, "T1"); t2 = _tenant(db, "T2")
    attacker = _user(db, t1.id)
    victim = _guest(db, t2.id)
    _event(db, t2.id, victim.id, preview="private conversation")
    db.commit()

    res = client.get(f"/api/v1/guests/{victim.id}/journey", headers=_auth(attacker))
    assert res.status_code == 404
    assert "private conversation" not in res.text


def test_journey_requires_auth(client, db):
    t = _tenant(db); g = _guest(db, t.id); db.commit()
    res = client.get(f"/api/v1/guests/{g.id}/journey")
    assert res.status_code in (401, 403)


def test_dpdp_delete_purges_ledger(db):
    """guest_events holds message previews — a deletion request must remove
    them, or a readable copy of the conversation survives the erasure."""
    from app.services.guest_service import dpdp_delete

    t = _tenant(db); g = _guest(db, t.id)
    _event(db, t.id, g.id, preview="sensitive guest message")
    db.commit()

    assert db.query(GuestEvent).filter_by(tenant_id=t.id, guest_id=g.id).count() == 1

    dpdp_delete(db, t.id, g.id)
    db.commit()

    remaining = db.query(GuestEvent).filter_by(tenant_id=t.id, guest_id=g.id).count()
    assert remaining == 0, "ledger rows must not survive a DPDP deletion"
