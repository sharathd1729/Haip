"""Yaad settings (custom words + switches), phone notifications (GET /devices/updates) and delete my account."""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from app.models.audit_event import AuditEvent
from app.models.call import Call
from app.models.guest import Guest
from app.models.mobile_device import MobileCallPending, MobileDevice
from app.models.tenant import Tenant
from app.models.transcript import Transcript
from app.models.user import User, UserRole
from app.services import personal_calls as pc
from app.services import personal_notify
from tests.test_personal_calls import MEMORY, _auth, _personal, _run, _tid
from tests.workers import call_analysis_harness as h

NOW = datetime(2026, 11, 14, 17, 0, tzinfo=UTC)  # 22:30 IST


def _remembered(db, tenant_id, created_at=NOW, analysed_at="2026-11-14T16:55:00+00:00", **kw):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Meera Iyer")
    db.add(g)
    db.commit()
    c = h.call(
        db, tenant_id, ivr_provider="mobile_app", guest_id=g.id, with_transcript=False, created_at=created_at, **kw
    )
    memory = pc.normalise({**MEMORY, "action_items": [{"text": "Book the venue", "owner": "me", "due": "2026-11-14"}]})
    pc.store(c, {**memory, "analysed_at": analysed_at})
    db.commit()
    return c


# ─── Settings ────────────────────────────────────────────────────────────────


def test_settings_clean_the_words_save_the_switches_and_audit(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    headers = _auth(tenant_and_user)
    r = client.get("/api/v1/me/settings", headers=headers)
    assert r.json() == {
        "custom_words": [],
        "daily_email": True,
        "notify_summary": True,
        "notify_due": True,
        "notify_day": True,
    }
    r = client.put(
        "/api/v1/me/settings",
        json={"custom_words": [" Ratha ", "ratha", "Doddaballapur", ""], "daily_email": False},
        headers=headers,
    )
    assert (
        r.status_code == 200
        and r.json()["custom_words"] == ["Ratha", "Doddaballapur"]
        and r.json()["daily_email"] is False
    )
    assert r.json()["notify_due"] is True
    db.expire_all()
    assert db.get(Tenant, tid).brand_config["personal_custom_words"] == ["Ratha", "Doddaballapur"]
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="personal.settings_changed").count() == 1
    assert client.put("/api/v1/me/settings", json={"custom_words": ["x" * 41]}, headers=headers).status_code == 422


def test_settings_are_only_for_personal_workspaces(client, tenant_and_user):
    assert client.get("/api/v1/me/settings", headers=_auth(tenant_and_user)).status_code == 403


def test_custom_words_reach_the_call_read(db):
    t = h.tenant(db)
    _personal(db, t.id)
    t.brand_config = {**t.brand_config, "personal_custom_words": ["Doddaballapur", "Launchfly"]}
    db.commit()
    c = h.call(db, t.id, ivr_provider="mobile_app")
    llm = h.ScriptedLLM(tool_use=MEMORY)
    _run(db, t.id, c.id, llm)
    assert "write it exactly as listed: Doddaballapur, Launchfly" in llm.calls[0][1]["system_prompt"]
    plain = h.tenant(db)
    _personal(db, plain.id)
    c2 = h.call(db, plain.id, ivr_provider="mobile_app")
    llm2 = h.ScriptedLLM(tool_use=MEMORY)
    _run(db, plain.id, c2.id, llm2)
    assert "Custom words" not in llm2.calls[0][1]["system_prompt"]


# ─── Phone notifications ─────────────────────────────────────────────────────


def _owner(db, tenant_id, **prefs):
    u = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        email=f"{uuid.uuid4().hex[:6]}@example.com",
        name="Arjun",
        role=UserRole.OWNER,
        notification_prefs=prefs,
    )
    db.add(u)
    db.commit()
    return u


def test_updates_summary_due_today_and_day(db):
    t = h.tenant(db)
    _personal(db, t.id)
    u = _owner(db, t.id)
    c = _remembered(db, t.id)
    _remembered(db, t.id, analysed_at="2026-11-14T10:00:00+00:00")  # summarised before the app last asked
    items = personal_notify.updates(db, t, u, datetime(2026, 11, 14, 16, 0, tzinfo=UTC), NOW)
    ids = [i["id"] for i in items]
    assert ids == [f"sum:{c.id}", "due:2026-11-14", "day:2026-11-14"]
    assert items[0]["body"] == "Summary ready · Meera Iyer" and items[0]["path"] == f"/dashboard/me/calls/{c.id}"
    assert items[1]["title"] == "2 reminders due today" and items[2]["body"].startswith("2 calls today")
    morning = datetime(2026, 11, 14, 2, 0, tzinfo=UTC)  # 07:30 IST: too early for "due today" and "day"
    assert [i["id"] for i in personal_notify.updates(db, t, u, NOW, morning)] == []


def test_updates_respect_the_switches_and_the_workspace(db):
    t = h.tenant(db)
    _personal(db, t.id)
    quiet = _owner(db, t.id, yaad_notify_summary=False, yaad_notify_due=False, yaad_notify_day=False)
    _remembered(db, t.id)
    assert personal_notify.updates(db, t, quiet, None, NOW) == []
    business = h.tenant(db)
    _remembered(db, business.id)
    assert personal_notify.updates(db, business, _owner(db, business.id), None, NOW) == []


def test_updates_endpoint_needs_a_device_token(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    r = client.post("/api/v1/devices/register", json={"device_id": uuid.uuid4().hex}, headers=_auth(tenant_and_user))
    token = r.json()["token"]
    r = client.get("/api/v1/devices/updates", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and "now" in r.json() and r.json()["notifications"] == []
    assert client.get("/api/v1/devices/updates", headers={"Authorization": "Bearer haip_dev_nope"}).status_code == 401


# ─── Delete my account ───────────────────────────────────────────────────────


def test_delete_account_erases_the_workspace_and_signs_everyone_out(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    headers = _auth(tenant_and_user)
    with_contact = _remembered(db, tid, recording_s3_key=f"{tid}/calls/a.m4a")
    hidden = h.call(
        db, tid, ivr_provider="mobile_app", recording_s3_key=f"{tid}/calls/b.m4a"
    )  # no contact, has a transcript
    dev = client.post("/api/v1/devices/register", json={"device_id": uuid.uuid4().hex}, headers=headers).json()
    db.add(
        MobileCallPending(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            device_pk=dev["id"],
            ivr_call_id="x1",
            recording_key=f"{tid}/calls/c.m4a",
        )
    )
    db.commit()
    other = h.tenant(db)
    keep = h.call(db, other.id)
    gone_ids, keep_id = [with_contact.id, hidden.id], keep.id

    assert (
        client.request("DELETE", "/api/v1/me/account", json={"confirm": "delete me"}, headers=headers).status_code
        == 422
    )
    with patch("app.services.media_storage.delete_tenant_objects", return_value=3) as files:
        r = client.request("DELETE", "/api/v1/me/account", json={"confirm": "DELETE"}, headers=headers)
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert sorted(files.call_args.args[1]) == sorted([f"{tid}/calls/a.m4a", f"{tid}/calls/b.m4a", f"{tid}/calls/c.m4a"])
    db.expire_all()
    assert db.query(Call).filter_by(tenant_id=tid).count() == 0
    assert db.query(Transcript).filter(Transcript.call_id.in_(gone_ids)).count() == 0
    assert db.query(MobileCallPending).filter_by(tenant_id=tid).count() == 0
    assert all(d.revoked_at for d in db.query(MobileDevice).filter_by(tenant_id=tid))
    users = db.query(User).filter_by(tenant_id=tid).all()
    assert users and all(not u.is_active and u.is_deleted and u.email.endswith("@deleted.invalid") for u in users)
    t = db.get(Tenant, tid)
    assert t.is_active is False and "personal_custom_words" not in t.brand_config
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="account.deleted").count() == 1
    assert db.get(Call, keep_id) is not None  # another workspace untouched
    assert client.get("/api/v1/me/calls", headers=headers).status_code == 401  # signed out


def test_only_the_owner_of_a_personal_workspace_can_delete_it(client, db, tenant_and_user):
    headers = _auth(tenant_and_user)
    assert (
        client.request("DELETE", "/api/v1/me/account", json={"confirm": "DELETE"}, headers=headers).status_code == 403
    )
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    for u in db.query(User).filter_by(tenant_id=tid):
        u.role = UserRole.CONCIERGE
    db.commit()
    assert (
        client.request("DELETE", "/api/v1/me/account", json={"confirm": "DELETE"}, headers=headers).status_code == 403
    )
    assert db.get(Tenant, tid).is_active is not False


# ─── Yaad sign-up (POST /auth/register, workspace_mode=personal) ─────────────


def test_yaad_signup_makes_a_personal_workspace_without_business_details(client, db):
    r = client.post("/api/v1/auth/register", json={"name": "Arjun Rao", "email": "arjun.yaad@example.com",
                                                   "password": "Secure123!", "workspace_mode": "personal"})
    assert r.status_code == 201, r.text
    t = db.get(Tenant, r.json()["user"]["tenant_id"])
    assert t.name == "Arjun Rao" and t.slug.startswith("me-") and t.business_type is None
    assert pc.is_personal_tenant(t)
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="workspace.mode_changed").count() == 1
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/v1/me/calls", headers=h).status_code == 200            # straight into Yaad
    assert client.get("/api/v1/workspace/context", headers=h).json()["mode"] == "personal"


def test_business_signup_still_needs_its_details_and_a_real_password(client):
    base = {"name": "B", "email": "b.biz@example.com", "password": "Secure123!"}
    assert client.post("/api/v1/auth/register", json=base).status_code == 422          # no workspace name / URL
    assert client.post("/api/v1/auth/register", json={**base, "email": "c@example.com", "password": "short",
                                                      "workspace_mode": "personal"}).status_code == 400
