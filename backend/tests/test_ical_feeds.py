"""iCal calendar links: parsing, export, import reconcile, endpoints, task routing."""
import os
import uuid
from datetime import date, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.core.encryption import encrypt_credentials  # noqa: E402
from app.models.base import gen_uuid  # noqa: E402
from app.models.ical_feed import ICalFeed  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.property import BlockedDate, Property, Stay  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.services import ical_sync_service as svc  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def _d(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def _ics(*events: str) -> str:
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(events) + "END:VCALENDAR\r\n"


def _ev(uid: str, start: str, end: str, extra: str = "") -> str:
    return (f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTART;VALUE=DATE:{start.replace('-', '')}\r\n"
            f"DTEND;VALUE=DATE:{end.replace('-', '')}\r\n{extra}END:VEVENT\r\n")


def _tenant(db, slug_prefix="other"):
    """A real second tenant: properties.tenant_id is a foreign key and PostgreSQL enforces it."""
    t = Tenant(id=str(uuid.uuid4()), name=f"{slug_prefix} tenant", slug=f"{slug_prefix}-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t.id


def _guest(db, tenant_id):
    """A real guest of `tenant_id`: stays.guest_id is a foreign key (the tests used the owner's user id)."""
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Stay Guest")
    db.add(g)
    db.flush()
    return g.id


def _prop(db, tenant_id, name="Caravan 1"):
    p = Property(id=gen_uuid(), tenant_id=tenant_id, name=name, slug=f"p-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
    db.add(p)
    db.flush()
    return p


def _feed(db, tenant_id, prop_id, name="Airbnb", url="https://example.com/a.ics"):
    f = ICalFeed(tenant_id=tenant_id, property_id=prop_id, name=name, export_token=svc.new_export_token(),
                 import_url_enc=encrypt_credentials({"url": url}) if url else None, is_active=True)
    db.add(f)
    db.flush()
    return f


def _auth(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


# ─── parse / build ────────────────────────────────────────────────────────────

def test_parse_all_day_cancelled_and_dtend_less():
    text = _ics(
        _ev("a@airbnb", "2026-11-01", "2026-11-04"),
        _ev("b@airbnb", "2026-11-10", "2026-11-12", "STATUS:CANCELLED\r\n"),
        "BEGIN:VEVENT\r\nUID:c@airbnb\r\nDTSTART;VALUE=DATE:20261120\r\nEND:VEVENT\r\n",
    )
    out = {e["uid"]: e for e in svc.parse_ics(text, IST)}
    assert out["a@airbnb"]["start"] == "2026-11-01" and out["a@airbnb"]["end"] == "2026-11-04"
    assert "b@airbnb" not in out
    assert out["c@airbnb"]["end"] == "2026-11-21"


def test_build_ics_has_no_guest_detail_and_crlf():
    body = svc.build_ics("Caravan 1 (HAIP)", [{"uid": "stay-1@haip", "start": "2026-11-01", "end": "2026-11-03",
                                              "summary": "Reserved", "modified": None}])
    assert body.startswith("BEGIN:VCALENDAR\r\n") and "\r\n" in body
    assert "SUMMARY:Reserved" in body and "DTSTART;VALUE=DATE:20261101" in body


# ─── import ───────────────────────────────────────────────────────────────────

def test_sync_adds_updates_and_lifts(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = _prop(db, tid)
    feed = _feed(db, tid, prop.id)

    r = svc.sync_feed(db, feed, fetcher=lambda u: _ics(_ev("a@x", _d(5), _d(8)), _ev("b@x", _d(20), _d(22))))
    assert r["status"] == "ok" and r["added"] == 2
    rows = db.query(BlockedDate).filter_by(tenant_id=tid, property_id=prop.id).all()
    assert len(rows) == 2 and all(b.notes.startswith(f"ical:{feed.id}:") and b.is_active for b in rows)

    # a moves, b disappears (cancelled upstream)
    r = svc.sync_feed(db, feed, fetcher=lambda u: _ics(_ev("a@x", _d(5), _d(9))))
    assert r["changed"] == 1 and r["lifted"] == 1
    by_note = {b.notes.split(":", 2)[2]: b for b in db.query(BlockedDate).filter_by(tenant_id=tid).all()}
    assert by_note["a@x"].blocked_to == _d(9) and by_note["a@x"].is_active
    assert by_note["b@x"].is_active is False


def test_sync_skips_our_own_events_echoed_back(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = _prop(db, tid)
    feed = _feed(db, tid, prop.id)
    svc.sync_feed(db, feed, fetcher=lambda u: _ics(_ev("stay-1@haip", _d(3), _d(5))))
    assert db.query(BlockedDate).filter_by(tenant_id=tid).count() == 0


def test_sync_records_error_and_never_raises(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    feed = _feed(db, tid, _prop(db, tid).id)

    def boom(_u):
        raise ValueError("HTTP 404")
    r = svc.sync_feed(db, feed, fetcher=boom)
    assert r["status"] == "error" and feed.last_status == "error" and "404" in feed.last_error


def test_sync_flags_double_booking_once(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = _prop(db, tid)
    feed = _feed(db, tid, prop.id)
    db.add(Stay(id=gen_uuid(), tenant_id=tid, guest_id=_guest(db, tid), property_id=prop.id,
                check_in=date.today() + timedelta(days=5), check_out=date.today() + timedelta(days=7), status="confirmed"))
    db.flush()
    fetch = lambda u: _ics(_ev("a@x", _d(6), _d(9)))  # noqa: E731
    assert svc.sync_feed(db, feed, fetcher=fetch)["conflicts"] == 1
    assert svc.sync_feed(db, feed, fetcher=fetch)["conflicts"] == 1
    tasks = db.query(Task).filter(Task.tenant_id == tid, Task.title.like("Double booking%")).all()
    assert len(tasks) == 1 and tasks[0].priority == "high"


def test_sync_isolated_by_tenant(db, tenant_and_user):
    """Blocks land only on the feed's own property/tenant."""
    tid = tenant_and_user["tenant"].id
    other = _prop(db, _tenant(db, "other"))
    feed = _feed(db, tid, _prop(db, tid).id)
    svc.sync_feed(db, feed, fetcher=lambda u: _ics(_ev("a@x", _d(2), _d(4))))
    assert db.query(BlockedDate).filter_by(property_id=other.id).count() == 0


# ─── export ───────────────────────────────────────────────────────────────────

def test_export_content_and_exclusions(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = _prop(db, tid)
    airbnb = _feed(db, tid, prop.id, "Airbnb")
    booking = _feed(db, tid, prop.id, "Booking.com", url="https://example.com/b.ics")
    guest = _guest(db, tid)
    db.add_all([
        Stay(id="s-direct", tenant_id=tid, guest_id=guest, property_id=prop.id, check_in=date.today() + timedelta(days=2),
             check_out=date.today() + timedelta(days=4), status="confirmed"),
        Stay(id="s-pms", tenant_id=tid, guest_id=guest, property_id=prop.id, check_in=date.today() + timedelta(days=2),
             check_out=date.today() + timedelta(days=4), status="confirmed", hostaway_booking_id="h1"),
        Stay(id="s-cancelled", tenant_id=tid, guest_id=guest, property_id=prop.id, check_in=date.today() + timedelta(days=2),
             check_out=date.today() + timedelta(days=4), status="cancelled"),
        BlockedDate(tenant_id=tid, property_id=prop.id, blocked_from=_d(10), blocked_to=_d(12), reason="maintenance", is_active=True),
        BlockedDate(tenant_id=tid, property_id=prop.id, blocked_from=_d(20), blocked_to=_d(22), reason="offline_booking",
                    notes=f"ical:{airbnb.id}:u1", is_active=True),
        BlockedDate(tenant_id=tid, property_id=prop.id, blocked_from=_d(30), blocked_to=_d(32), reason="offline_booking",
                    notes=f"ical:{booking.id}:u2", is_active=True),
    ])
    db.flush()

    uids = [e["uid"] for e in svc.export_events(db, airbnb)]
    assert "stay-s-direct@haip" in uids
    assert "stay-s-pms@haip" not in uids and "stay-s-cancelled@haip" not in uids
    assert sum(u.startswith("block-") for u in uids) == 2       # manual block + Booking.com's import, not Airbnb's own
    summaries = {e["summary"] for e in svc.export_events(db, airbnb)}
    assert summaries <= {"Reserved", "Blocked"}


# ─── endpoints ────────────────────────────────────────────────────────────────

def test_create_list_sync_regenerate_delete(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = _prop(db, tid)
    db.commit()
    url = "https://example.com/cal.ics"
    with patch("app.api.v1.endpoints.ical_feeds.assert_public_url"), \
            patch.object(svc, "fetch_ics", return_value=_ics(_ev("a@x", _d(3), _d(5)))):
        r = client.post("/api/v1/ical-feeds", json={"property_id": prop.id, "name": "Airbnb", "import_url": url},
                        headers=_auth(tenant_and_user))
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["sync"]["added"] == 1 and body["has_import"] is True
        assert url not in r.text and body["export_url"].endswith(".ics")
        fid, old_url = body["id"], body["export_url"]

        assert len(client.get("/api/v1/ical-feeds", headers=_auth(tenant_and_user)).json()) == 1
        assert client.post(f"/api/v1/ical-feeds/{fid}/sync", headers=_auth(tenant_and_user)).status_code == 200

        new = client.post(f"/api/v1/ical-feeds/{fid}/regenerate", headers=_auth(tenant_and_user)).json()
        assert new["export_url"] != old_url

        assert client.delete(f"/api/v1/ical-feeds/{fid}", headers=_auth(tenant_and_user)).status_code == 204
    assert db.query(BlockedDate).filter_by(tenant_id=tid, is_active=True).count() == 0


def test_create_rejects_private_url(client, db, tenant_and_user):
    prop = _prop(db, tenant_and_user["tenant"].id)
    db.commit()
    r = client.post("/api/v1/ical-feeds", json={"property_id": prop.id, "name": "x", "import_url": "http://127.0.0.1/a.ics"},
                    headers=_auth(tenant_and_user))
    assert r.status_code == 422


def test_forbidden_for_wrong_role(client, db, tenant_and_user):
    from app.core.security import create_access_token
    from app.models.user import User, UserRole
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_and_user["tenant"].id, name="Viewer", email=f"v-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password="x", role=UserRole.READ_ONLY, is_active=True)
    db.add(u)
    db.commit()
    tok = create_access_token({"sub": u.id, "tenant_id": u.tenant_id, "role": u.role.value})
    assert client.get("/api/v1/ical-feeds", headers={"Authorization": f"Bearer {tok}"}).status_code == 403


def test_cross_tenant_feed_is_404(client, db, tenant_and_user):
    other_tid = _tenant(db, "someone-else")
    other = _feed(db, other_tid, _prop(db, other_tid).id)
    db.commit()
    h = _auth(tenant_and_user)
    assert client.post(f"/api/v1/ical-feeds/{other.id}/sync", headers=h).status_code == 404
    assert client.patch(f"/api/v1/ical-feeds/{other.id}", json={"name": "x"}, headers=h).status_code == 404
    assert client.delete(f"/api/v1/ical-feeds/{other.id}", headers=h).status_code == 404
    assert client.post(f"/api/v1/ical-feeds/{other.id}/regenerate", headers=h).status_code == 404
    assert client.post("/api/v1/ical-feeds", json={"property_id": _prop(db, other_tid).id, "name": "x"}, headers=h).status_code == 404


def test_public_export_serves_ics_and_404s(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = _prop(db, tid)
    feed = _feed(db, tid, prop.id, url=None)
    db.add(Stay(id="s1", tenant_id=tid, guest_id=_guest(db, tid), property_id=prop.id,
                check_in=date.today() + timedelta(days=2), check_out=date.today() + timedelta(days=4), status="confirmed"))
    db.commit()

    r = client.get(f"/api/v1/ical/{feed.export_token}.ics")        # no auth header
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in r.text and "stay-s1@haip" in r.text

    assert client.get("/api/v1/ical/" + "x" * 43 + ".ics").status_code == 404
    assert client.get("/api/v1/ical/short.ics").status_code == 404
    feed.is_active = False
    db.commit()
    assert client.get(f"/api/v1/ical/{feed.export_token}.ics").status_code == 404


def test_regenerated_token_kills_old_url(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    feed = _feed(db, tid, _prop(db, tid).id, url=None)
    db.commit()
    old = feed.export_token
    assert client.post(f"/api/v1/ical-feeds/{feed.id}/regenerate", headers=_auth(tenant_and_user)).status_code == 200
    assert client.get(f"/api/v1/ical/{old}.ics").status_code == 404


def test_per_property_feed_cap(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = _prop(db, tid)
    for i in range(svc.feed_cap()):
        _feed(db, tid, prop.id, name=f"f{i}", url=None)
    db.commit()
    r = client.post("/api/v1/ical-feeds", json={"property_id": prop.id, "name": "one too many"}, headers=_auth(tenant_and_user))
    assert r.status_code == 422


# ─── task wiring ──────────────────────────────────────────────────────────────

def test_beat_and_routes_registered():
    from app.workers.celery_app import celery_app
    assert celery_app.conf.beat_schedule["ical-sync-30min"]["task"] == "ical.sync_all_feeds"
    assert celery_app.conf.task_routes["ical.sync_feed"]["queue"] == "call_ingest"
    assert celery_app.conf.task_routes["ical.sync_all_feeds"]["queue"] == "call_ingest"
