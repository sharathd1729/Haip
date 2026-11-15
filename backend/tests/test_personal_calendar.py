"""Yaad calendar: plans said on calls arrive once as suggestions (notes from the call, people = participants), the person
accepts / edits / dismisses them or adds events by hand with notes and stakeholders; a dismissed plan never comes back;
nothing crosses workspaces. Made-up data only."""

from datetime import timedelta

from app.models.audit_event import AuditEvent
from app.models.yaad_folder import YaadEvent
from app.services import personal_calendar as cal
from app.services import personal_calls as pc
from app.services.booking_agenda_service import tenant_today
from tests.test_personal_calls import _auth, _personal, _remembered_call, _tid
from tests.workers import call_analysis_harness as h


def _planned(db, tid, day):
    c = _remembered_call(db, tid)
    m = pc.memory_of(c)
    pc.store(
        c,
        {
            **m,
            "upcoming": [
                {"what": "Site visit at the new flat", "date": day.isoformat(), "time": "10:30", "place": "Jayanagar"}
            ],
        },
    )
    db.commit()
    return c


def test_call_plans_become_suggestions_once_and_a_dismissed_one_stays_gone(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    headers = _auth(tenant_and_user)
    day = tenant_today(db, tid) + timedelta(days=3)
    c = _planned(db, tid, day)
    month = day.strftime("%Y-%m")
    events = client.get(f"/api/v1/me/calendar?month={month}", headers=headers).json()["events"]
    plan = next(e for e in events if e["title"] == "Site visit at the new flat")
    assert plan["status"] == "suggested" and plan["start_time"] == "10:30" and plan["call_id"] == c.id
    assert plan["people"][0]["name"] == "Rishu" and "Host the delegation" in plan["notes"] and plan["google"] is False
    again = client.get(f"/api/v1/me/calendar?month={month}", headers=headers).json()["events"]
    assert sum(e["title"] == plan["title"] for e in again) == 1  # never twice

    r = client.patch(f"/api/v1/me/calendar/{plan['id']}", json={"status": "dismissed"}, headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    after = client.get(f"/api/v1/me/calendar?month={month}", headers=headers).json()["events"]
    assert all(e["id"] != plan["id"] for e in after)
    assert cal.refresh_suggestions(db, tid, tenant_today(db, tid)) == 0  # a dismissed plan never comes back


def test_edit_accepts_a_suggestion_and_hand_made_events_keep_notes_and_people(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    headers = _auth(tenant_and_user)
    day = tenant_today(db, tid) + timedelta(days=5)
    _planned(db, tid, day)
    month = day.strftime("%Y-%m")
    plan = client.get(f"/api/v1/me/calendar?month={month}", headers=headers).json()["events"][0]
    edited = client.patch(
        f"/api/v1/me/calendar/{plan['id']}",
        headers=headers,
        json={"notes": "Bring the floor plan", "people": [{"name": "Kavya", "role": "architect"}]},
    ).json()
    assert (
        edited["status"] == "accepted"
        and edited["notes"] == "Bring the floor plan"
        and edited["people"][0]["name"] == "Kavya"
    )
    toggled = client.patch(f"/api/v1/me/calendar/{plan['id']}", json={"google": True}, headers=headers).json()
    assert toggled["google"] is True and toggled["google_synced"] is False

    made = client.post(
        "/api/v1/me/calendar",
        headers=headers,
        json={
            "title": "Tile shop",
            "day": day.isoformat(),
            "start_time": "16:00",
            "notes": "Matte grey samples",
            "people": [{"name": "Suresh", "role": "dealer"}],
        },
    )
    assert (
        made.status_code == 201 and made.json()["status"] == "accepted" and made.json()["notes"] == "Matte grey samples"
    )
    assert (
        client.post(
            "/api/v1/me/calendar", json={"title": "x", "day": day.isoformat(), "start_time": "25:00"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post("/api/v1/me/calendar", json={"title": " ", "day": day.isoformat()}, headers=headers).status_code
        == 422
    )
    assert client.delete(f"/api/v1/me/calendar/{made.json()['id']}", headers=headers).json() == {"deleted": True}
    events = db.query(AuditEvent).filter(AuditEvent.tenant_id == tid, AuditEvent.action.like("yaad_event.%")).all()
    assert {e.action for e in events} == {"yaad_event.updated", "yaad_event.created", "yaad_event.deleted"}
    assert all("floor plan" not in str(e.payload) and "Tile" not in str(e.payload) for e in events)


def test_calendar_stays_in_its_workspace_and_is_personal_only(client, db, tenant_and_user):
    headers = _auth(tenant_and_user)
    assert client.get("/api/v1/me/calendar?month=2026-11", headers=headers).status_code == 403
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    other = h.tenant(db)
    theirs = cal.create(db, other.id, None, {"title": "Their meeting", "day": "2026-11-20"})
    db.commit()
    assert client.get("/api/v1/me/calendar?month=2026-11", headers=headers).json()["events"] == []
    assert client.patch(f"/api/v1/me/calendar/{theirs.id}", json={"title": "x"}, headers=headers).status_code == 404
    assert client.delete(f"/api/v1/me/calendar/{theirs.id}", headers=headers).status_code == 404
    assert db.get(YaadEvent, theirs.id).title == "Their meeting"
    assert client.get("/api/v1/me/calendar?month=2026-13", headers=headers).status_code == 422
