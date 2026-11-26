"""WhatsApp contacts page: lists, bulk actions, drip enrolment, export and 30-day growth (services/wa_contacts.py)."""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.api.v1.endpoints.messaging import WAFlow, WASubscriber
from app.core.security import create_access_token
from app.models.audit_event import AuditEvent as AuditLog
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import wa_contacts as svc


def _tid(tu):
    return tu["tenant"].id


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _role_headers(db, tenant_id, role):
    user = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name="U", email=f"u-{uuid.uuid4().hex[:6]}@t.com",
                hashed_password="x", role=role, is_active=True)
    db.add(user)
    db.commit()
    return {"Authorization": "Bearer " + create_access_token({"sub": user.id, "tenant_id": tenant_id, "role": role.value})}


def _other_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    return t.id


def _sub(db, tid, phone, name=None, opted_in=True, tags=None, list_ids=None, guest_id=None, **kw):
    s = WASubscriber(id=str(uuid.uuid4()), tenant_id=tid, phone=phone, name=name, opted_in=opted_in, tags=tags or [],
                     list_ids=list_ids or [], guest_id=guest_id, **kw)
    db.add(s)
    db.commit()
    return s


def _flow(db, tid, active=True):
    f = WAFlow(id=str(uuid.uuid4()), tenant_id=tid, name="Wedding drip", nodes=[{"id": "t", "type": "trigger"}],
               edges=[], is_active=active, trigger="manual")
    db.add(f)
    db.commit()
    return f


def _audits(db, tid, action):
    return db.query(AuditLog).filter_by(tenant_id=tid, action=action).all()


# ─── Service ─────────────────────────────────────────────────────────────────

def test_lists_filter_and_counts(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    wedding = svc.create_list(db, tid, "  Wedding   enquiries 2026 ", None)
    assert wedding.name == "Wedding enquiries 2026"
    corp = svc.create_list(db, tid, "Corporate HR contacts", None)
    _sub(db, tid, "+919800000001", list_ids=[wedding.id])
    _sub(db, tid, "+919800000002", list_ids=[wedding.id, corp.id], tags=["vip"])
    _sub(db, tid, "+919800000003")

    counts = {r["name"]: r["count"] for r in svc.lists_with_counts(db, tid)}
    assert counts == {"Corporate HR contacts": 1, "Wedding enquiries 2026": 2}
    assert svc.matching(db, tid, list_id=wedding.id).count() == 2
    assert svc.matching(db, tid, list_id=corp.id, tag="vip").count() == 1
    with pytest.raises(svc.ContactsError):
        svc.create_list(db, tid, "Wedding enquiries 2026", None)

    assert svc.delete_list(db, tid, wedding) == 2
    assert svc.matching(db, tid, list_id=wedding.id).count() == 0
    assert db.query(WASubscriber).filter_by(tenant_id=tid).count() == 3   # contacts are kept


def test_lists_are_tenant_isolated(db, tenant_and_user):
    tid, other = _tid(tenant_and_user), _other_tenant(db)
    mine = svc.create_list(db, tid, "Wedding", None)
    svc.create_list(db, other, "Wedding", None)   # same name in another workspace is fine
    _sub(db, other, "+919800000009", list_ids=[mine.id])
    assert [r["count"] for r in svc.lists_with_counts(db, tid)] == [0]
    assert svc.get_list(db, other, mine.id) is None
    assert svc.matching(db, tid, list_id=mine.id).count() == 0


def test_tag_filter_escapes_like_wildcards(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _sub(db, tid, "+919800000001", tags=["50%_off"])
    _sub(db, tid, "+919800000002", tags=["50xxoff"])
    assert svc.matching(db, tid, tag="50%_off").count() == 1


def test_apply_counts_only_real_changes(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    lst = svc.create_list(db, tid, "Corporate", None)
    a = _sub(db, tid, "+919800000001", tags=["vip"])
    b = _sub(db, tid, "+919800000002", opted_in=False)
    assert svc.apply(db, tid, [a, b], "add_tag", "vip") == 1
    assert svc.apply(db, tid, [a, b], "add_to_list", lst.id) == 2
    assert svc.apply(db, tid, [a, b], "opt_out") == 1
    assert a.opted_in is False and a.opt_out_at
    with pytest.raises(svc.ContactsError):
        svc.apply(db, tid, [a], "add_to_list", "missing")


def test_growth_buckets_by_workspace_day(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    today = date(2026, 11, 26)
    # 20:00 UTC on the 25th is 01:30 IST on the 26th
    _sub(db, tid, "+919800000001", created_at=datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc))
    _sub(db, tid, "+919800000002", created_at=datetime(2026, 10, 1, tzinfo=timezone.utc))   # outside 30 days
    _sub(db, tid, "+919800000003", opted_in=False, opt_out_at="2026-11-20T06:00:00+00:00",
         created_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    g = svc.growth(db, tid, today=today)
    assert g["from"] == "2026-10-28" and g["to"] == "2026-11-26" and len(g["daily"]) == 30
    by_day = {r["date"]: r for r in g["daily"]}
    assert by_day["2026-11-26"]["new"] == 1 and g["new_total"] == 1
    assert by_day["2026-11-20"]["opted_out"] == 1 and g["opted_out_total"] == 1


def test_enrol_plan_skips_opted_out_and_non_guests(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Asha", phone="+919800000002")
    db.add(g)
    db.commit()
    subs = [_sub(db, tid, "+919800000001", guest_id=None), _sub(db, tid, "+919800000002"),
            _sub(db, tid, "+919800000003", opted_in=False)]
    gids, skipped = svc.enrol_plan(db, tid, subs)
    assert gids == [g.id] and skipped == {"opted_out": 1, "not_a_guest": 1}


# ─── Endpoints ───────────────────────────────────────────────────────────────

def test_list_endpoints_and_filtering(client, db, tenant_and_user):
    tid, h = _tid(tenant_and_user), _h(tenant_and_user)
    r = client.post("/api/v1/messaging/contact-lists", json={"name": "Wedding enquiries 2026"}, headers=h)
    assert r.status_code == 201
    lid = r.json()["id"]
    assert client.post("/api/v1/messaging/contact-lists", json={"name": "Wedding enquiries 2026"}, headers=h).status_code == 422
    _sub(db, tid, "+919800000001", list_ids=[lid])
    _sub(db, tid, "+919800000002")
    assert client.get("/api/v1/messaging/contact-lists", headers=h).json()[0]["count"] == 1
    assert len(client.get(f"/api/v1/messaging/subscribers?list_id={lid}", headers=h).json()) == 1
    assert client.get(f"/api/v1/messaging/subscribers/count?list_id={lid}", headers=h).json() == {"count": 1}
    assert client.patch(f"/api/v1/messaging/contact-lists/{lid}", json={"name": "Weddings"}, headers=h).json()["name"] == "Weddings"
    assert client.delete(f"/api/v1/messaging/contact-lists/{lid}", headers=h).json() == {"deleted": True, "members": 1}
    assert len(_audits(db, tid, "contact_lists.delete")) == 1


def test_bulk_tag_by_selection_and_by_filter_is_audited(client, db, tenant_and_user):
    tid, h = _tid(tenant_and_user), _h(tenant_and_user)
    a = _sub(db, tid, "+919800000001", name="Asha")
    _sub(db, tid, "+919800000002", name="Ravi")
    _sub(db, tid, "+919800000003", name="Meera", opted_in=False)
    r = client.post("/api/v1/messaging/subscribers/bulk", json={"ids": [a.id], "action": "add_tag", "value": "vip"}, headers=h)
    assert r.json() == {"action": "add_tag", "selected": 1, "changed": 1}
    r = client.post("/api/v1/messaging/subscribers/bulk",
                    json={"filter": {"opted_in": True}, "action": "add_tag", "value": "wedding"}, headers=h)
    assert r.json()["changed"] == 2
    log = _audits(db, tid, "subscribers.bulk_add_tag")
    assert len(log) == 2 and {e.payload["by"] for e in log} == {"selection", "filter"}
    assert "+9198" not in str([e.payload for e in log])   # no phone numbers on the audit trail
    assert client.post("/api/v1/messaging/subscribers/bulk", json={"action": "add_tag", "value": "x"}, headers=h).status_code == 422


def test_bulk_opt_out(client, db, tenant_and_user):
    tid, h = _tid(tenant_and_user), _h(tenant_and_user)
    subs = [_sub(db, tid, f"+91980000001{i}") for i in range(3)]
    r = client.post("/api/v1/messaging/subscribers/bulk", json={"ids": [s.id for s in subs], "action": "opt_out"}, headers=h)
    assert r.json()["changed"] == 3
    db.expire_all()
    assert all(not s.opted_in for s in db.query(WASubscriber).filter_by(tenant_id=tid))


def test_bulk_wrong_role_is_forbidden(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    a = _sub(db, tid, "+919800000001")
    h = _role_headers(db, tid, UserRole.CONCIERGE)
    assert client.post("/api/v1/messaging/subscribers/bulk", json={"ids": [a.id], "action": "opt_out"}, headers=h).status_code == 403
    assert client.post("/api/v1/messaging/contact-lists", json={"name": "X"}, headers=h).status_code == 403
    assert client.get("/api/v1/messaging/subscribers/growth", headers=h).status_code == 403


def test_bulk_cannot_touch_another_workspace(client, db, tenant_and_user):
    tid, h = _tid(tenant_and_user), _h(tenant_and_user)
    other = _other_tenant(db)
    theirs = _sub(db, other, "+919800000001")
    their_list = svc.create_list(db, other, "Theirs", None)
    db.commit()
    r = client.post("/api/v1/messaging/subscribers/bulk", json={"ids": [theirs.id], "action": "opt_out"}, headers=h)
    assert r.json()["selected"] == 0
    db.refresh(theirs)
    assert theirs.opted_in is True
    mine = _sub(db, tid, "+919800000002")
    r = client.post("/api/v1/messaging/subscribers/bulk",
                    json={"ids": [mine.id], "action": "add_to_list", "value": their_list.id}, headers=h)
    assert r.status_code == 422
    assert client.delete(f"/api/v1/messaging/contact-lists/{their_list.id}", headers=h).status_code == 404


def test_enrol_inline_and_queued(client, db, tenant_and_user):
    tid, h = _tid(tenant_and_user), _h(tenant_and_user)
    flow = _flow(db, tid)
    guests = [Guest(id=str(uuid.uuid4()), tenant_id=tid, name=f"G{i}", phone=f"+9198000{i:05d}") for i in range(60)]
    db.add_all(guests)
    db.commit()
    subs = [_sub(db, tid, g.phone, guest_id=g.id) for g in guests]
    with patch("app.services.flow_engine.run_flow") as run:
        r = client.post("/api/v1/messaging/subscribers/enrol", json={"ids": [s.id for s in subs[:3]], "flow_id": flow.id}, headers=h)
    assert r.json()["started"] == 3 and r.json()["queued"] is False and run.call_count == 3
    with patch("app.workers.tasks.wa_contacts.enrol_flow_batch.apply_async") as queue:
        r = client.post("/api/v1/messaging/subscribers/enrol", json={"filter": {}, "flow_id": flow.id}, headers=h)
    assert r.json()["queued"] is True and r.json()["enrolled"] == 60 and queue.call_count == 2
    assert queue.call_args_list[1].kwargs["countdown"] == svc.ENROL_BATCH_GAP_S
    assert len(_audits(db, tid, "subscribers.bulk_enrol")) == 2

    off = _flow(db, tid, active=False)
    assert client.post("/api/v1/messaging/subscribers/enrol", json={"ids": [subs[0].id], "flow_id": off.id}, headers=h).status_code == 422
    theirs = _flow(db, _other_tenant(db))
    assert client.post("/api/v1/messaging/subscribers/enrol", json={"ids": [subs[0].id], "flow_id": theirs.id}, headers=h).status_code == 422


def test_enrol_task_runs_the_batch(db, tenant_and_user):
    from app.workers.tasks import wa_contacts as task
    tid = _tid(tenant_and_user)
    flow = _flow(db, tid)
    with patch.object(task, "SessionLocal", return_value=db), patch.object(db, "close"), \
            patch("app.services.flow_engine.run_flow") as run:
        assert task.enrol_flow_batch(tid, flow.id, ["g1", "g2"]) == 2
    assert run.call_count == 2


def test_export_and_growth_endpoints(client, db, tenant_and_user):
    tid, h = _tid(tenant_and_user), _h(tenant_and_user)
    lst = svc.create_list(db, tid, "Corporate", None)
    db.commit()
    a = _sub(db, tid, "+919800000001", name="=HYPERLINK(1)", list_ids=[lst.id])
    r = client.post("/api/v1/messaging/subscribers/export", json={"ids": [a.id]}, headers=h)
    body = r.content.decode("utf-8-sig")
    assert "+919800000001" in body and "'=HYPERLINK(1)" in body and "Corporate" in body
    assert _audits(db, tid, "subscribers.export")[0].payload["row_count"] == 1
    g = client.get("/api/v1/messaging/subscribers/growth", headers=h).json()
    assert len(g["daily"]) == 30 and g["new_total"] == 1
