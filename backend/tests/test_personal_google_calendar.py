"""Yaad -> Google Calendar: only events the person switched on go to Google; edits update the copy, switching off /
dismissing / deleting removes it; nothing happens without a connection; Google refusing is stored on the event. A fake
Google stands in for the API. Made-up data only."""

from datetime import date
from unittest.mock import patch

from sqlalchemy.orm import Session as SASession

from app.adapters import google_calendar as gcal
from app.adapters.instagram.publishing import PublishError
from app.core.security import create_access_token
from app.models.yaad_folder import YaadEvent
from app.services import personal_calendar as cal
from app.services import personal_google_calendar as gsync
from tests.test_personal_calls import _auth, _personal, _tid
from tests.workers import call_analysis_harness as h


class FakeGoogle:
    def __init__(self, fail=None):
        self.calls, self.fail, self.n = [], fail, 0

    def insert(self, body):
        self._maybe_fail()
        self.n += 1
        self.calls.append(("insert", body))
        return f"g{self.n}"

    def update(self, event_id, body):
        self._maybe_fail()
        self.calls.append(("update", event_id, body))

    def delete(self, event_id):
        self._maybe_fail()
        self.calls.append(("delete", event_id))

    def _maybe_fail(self):
        if self.fail:
            raise self.fail


def test_event_body_all_day_and_timed():
    allday = gcal.event_body(
        title="Site visit",
        day=date(2026, 11, 24),
        start_time=None,
        place="",
        notes="Bring plan",
        people=[{"name": "Kavya", "role": "architect"}],
        tz="Asia/Kolkata",
    )
    assert allday["start"] == {"date": "2026-11-24"} and allday["end"] == {"date": "2026-11-25"}
    assert "Bring plan" in allday["description"] and "Kavya (architect)" in allday["description"]
    timed = gcal.event_body(
        title="Call", day=date(2026, 11, 24), start_time="09:30", place="Home", notes="", people=[], tz="Asia/Kolkata"
    )
    assert timed["start"] == {"dateTime": "2026-11-24T09:30:00", "timeZone": "Asia/Kolkata"}
    assert timed["end"]["dateTime"] == "2026-11-24T10:30:00" and timed["location"] == "Home"


def test_sync_creates_updates_and_removes_only_what_the_person_chose(db):
    t = h.tenant(db)
    _personal(db, t.id)
    g = FakeGoogle()
    e = cal.create(db, t.id, None, {"title": "Tile shop", "day": "2026-11-24", "start_time": "16:00"})
    assert gsync.sync_event(db, t.id, e.id, api=g) == "skipped" and g.calls == []  # not switched on = not sent
    cal.update(e, {"google": True})
    assert gsync.sync_event(db, t.id, e.id, api=g) == "created" and e.google_event_id == "g1"
    cal.update(e, {"notes": "Matte grey samples"})
    assert gsync.sync_event(db, t.id, e.id, api=g) == "updated" and g.calls[-1][1] == "g1"
    cal.update(e, {"google": False})
    assert gsync.sync_event(db, t.id, e.id, api=g) == "deleted" and g.calls[-1] == ("delete", "g1")
    assert e.google_event_id is None

    s = cal.create(db, t.id, None, {"title": "Suggested", "day": "2026-11-25", "status": "suggested", "google": True})
    assert gsync.sync_event(db, t.id, s.id, api=g) == "skipped"  # a suggestion never goes to Google
    assert gsync.sync_event(db, t.id, e.id) == "skipped"
    cal.update(e, {"google": True})
    assert gsync.sync_event(db, t.id, e.id) == "not_connected"  # no Google connection: nothing happens


def test_changes_queue_the_sync_and_a_delete_removes_the_copy(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    headers = _auth(tenant_and_user)
    sent = []
    with patch("app.workers.tasks.personal_folders.google_sync.delay", side_effect=lambda *a: sent.append(a)):
        made = client.post(
            "/api/v1/me/calendar", json={"title": "Dentist", "day": "2026-11-24"}, headers=headers
        ).json()
        assert sent == []  # not in Google: nothing queued
        client.patch(f"/api/v1/me/calendar/{made['id']}", json={"google": True}, headers=headers)
        assert sent == [(tid, made["id"], None)]
        db.query(YaadEvent).filter_by(id=made["id"]).update({"google_event_id": "g7"})
        db.commit()
        client.delete(f"/api/v1/me/calendar/{made['id']}", headers=headers)
        assert sent[-1] == (tid, None, "g7")


def test_google_refusing_is_stored_on_the_event(db, monkeypatch):
    from app.workers.tasks import personal_folders as task_mod

    t = h.tenant(db)
    _personal(db, t.id)
    e = cal.create(db, t.id, None, {"title": "Visa office", "day": "2026-11-24", "google": True})
    db.commit()
    monkeypatch.setattr(
        gsync, "client", lambda *_a, **_k: FakeGoogle(PublishError("Google 400", transient=False, status=400))
    )
    monkeypatch.setattr(task_mod, "SessionLocal", lambda: SASession(bind=db.connection()))
    assert task_mod.google_sync.run(t.id, e.id) == "failed"
    db.expire_all()
    assert db.get(YaadEvent, e.id).google_error == "Google refused this event."


def test_disconnect_forgets_copies_and_connecting_is_personal_only(client, db, tenant_and_user):
    headers = _auth(tenant_and_user)
    assert client.get("/api/v1/me/calendar/google", headers=headers).status_code == 403  # business workspace
    tid = _tid(tenant_and_user)
    token = create_access_token(
        {
            "sub": tenant_and_user["user"]["id"]
            if isinstance(tenant_and_user["user"], dict)
            else tenant_and_user["user"].id,
            "tenant_id": tid,
            "role": "owner",
        }
    )
    assert (
        client.get(f"/api/v1/me/calendar/google/oauth-start?token={token}", follow_redirects=False).status_code == 403
    )
    _personal(db, tid)
    with patch.object(gsync, "available", return_value=False):
        r = client.get(f"/api/v1/me/calendar/google/oauth-start?token={token}", follow_redirects=False)
    assert r.status_code == 503
    assert client.get("/api/v1/me/calendar/google", headers=headers).json()["connected"] is False

    from app.models.integration import Integration

    db.add(Integration(tenant_id=tid, kind=gsync.KIND, status="active"))
    e = cal.create(db, tid, None, {"title": "Pushed", "day": "2026-11-24", "google": True})
    e.google_event_id = "g9"
    other = h.tenant(db)
    theirs = cal.create(db, other.id, None, {"title": "Theirs", "day": "2026-11-24", "google": True})
    theirs.google_event_id = "g10"
    db.commit()
    assert client.get("/api/v1/me/calendar/google", headers=headers).json()["connected"] is True
    assert client.delete("/api/v1/me/calendar/google", headers=headers).json() == {"disconnected": True}
    db.expire_all()
    assert db.get(YaadEvent, e.id).google_event_id is None and db.get(YaadEvent, theirs.id).google_event_id == "g10"
