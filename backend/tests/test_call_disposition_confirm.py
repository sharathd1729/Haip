"""POST /calls/{id}/disposition/confirm ("Was the AI right?") and My day's call_checks nudge. Pinned: Yes copies the AI's
outcome into human_disposition, No stores the picked one, both audited with who; No without an outcome = 422; a call the AI
has not read = 409; read_only = 403; another workspace's call = 404; the nudge lists only the person's own unconfirmed
analysed calls, leaves once confirmed, and never adds to the queue's people counts."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.audit_event import AuditEvent
from app.models.call import Call, CallDirection, CallDisposition
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import work_queue_service
from tests.conftest import seed_capabilities
from tests.test_lead_feed import _owner_headers, _user

NOW = datetime.now(timezone.utc)


def _call(db, tid, agent_id=None, ai=CallDisposition.HOT, hours_ago=2):
    c = Call(id=str(uuid.uuid4()), tenant_id=tid, agent_id=agent_id, ivr_provider="manual", ivr_call_id=uuid.uuid4().hex,
             direction=CallDirection.INBOUND, from_number="+919845012321", to_number="+918000000000",
             duration_seconds=120, ai_disposition=ai, created_at=NOW - timedelta(hours=hours_ago))
    db.add(c)
    db.commit()
    return c


def _post(client, call_id, headers, **body):
    return client.post(f"/api/v1/calls/{call_id}/disposition/confirm", headers=headers, json=body)


def test_yes_copies_the_ai_outcome_and_no_stores_the_picked_one(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    h = _owner_headers(tenant_and_user)
    right, wrong = _call(db, tenant.id, owner.id), _call(db, tenant.id, owner.id, ai=CallDisposition.BOOKED)

    res = _post(client, right.id, h, ai_correct=True)
    assert res.status_code == 200, res.text
    assert res.json()["human_disposition"] == "hot" and res.json()["ai_correct"] is True
    res = _post(client, wrong.id, h, ai_correct=False, disposition="callback")
    assert res.status_code == 200 and res.json()["ai_correct"] is False

    db.refresh(right); db.refresh(wrong)
    assert right.human_disposition == CallDisposition.HOT and right.disposition_set_by == owner.id
    assert wrong.human_disposition == CallDisposition.CALLBACK and wrong.ai_disposition == CallDisposition.BOOKED
    ev = db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="call.disposition_confirmed", target_id=wrong.id).one()
    assert ev.actor_user_id == owner.id and ev.payload["ai_disposition"] == "booked" and ev.payload["human_disposition"] == "callback"
    detail = client.get(f"/api/v1/calls/{wrong.id}", headers=h).json()
    assert detail["ai_disposition"] == "booked" and detail["human_disposition"] == "callback"


def test_no_without_an_outcome_and_an_unread_call_are_refused(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    h = _owner_headers(tenant_and_user)
    c = _call(db, tenant.id, owner.id)
    assert _post(client, c.id, h, ai_correct=False).status_code == 422
    assert _post(client, c.id, h, ai_correct=False, disposition="maybe").status_code == 422
    unread = _call(db, tenant.id, owner.id, ai=None)
    assert _post(client, unread.id, h, ai_correct=True).status_code == 409
    db.refresh(c)
    assert c.human_disposition is None


def test_read_only_is_refused_and_another_workspaces_call_is_not_found(client, db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    seed_capabilities(db, tenant.id)
    c = _call(db, tenant.id)
    _, ro = _user(db, tenant.id, UserRole.READ_ONLY)
    assert _post(client, c.id, ro, ai_correct=True).status_code == 403

    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other); db.commit()
    seed_capabilities(db, other.id)
    theirs = _call(db, other.id)
    assert _post(client, theirs.id, _owner_headers(tenant_and_user), ai_correct=True).status_code == 404
    db.refresh(c); db.refresh(theirs)
    assert c.human_disposition is None and theirs.human_disposition is None


def test_my_day_nudge_lists_own_unconfirmed_calls_outside_the_people_counts(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    mate, _ = _user(db, tenant.id, UserRole.CONCIERGE)
    mine = _call(db, tenant.id, owner.id)
    _call(db, tenant.id, owner.id, hours_ago=24 * 9)        # too old
    _call(db, tenant.id, owner.id, ai=None)                 # not read by the AI yet
    _call(db, tenant.id, mate.id)                           # a teammate's call

    res = work_queue_service.build(db, tenant, owner.id)
    assert res["call_checks"]["count"] == 1 and res["call_checks"]["calls"][0]["call_id"] == mine.id
    assert res["call_checks"]["calls"][0]["ai_disposition"] == "hot"
    assert res["people"] == 0 and res["total"] == 0          # a QA chore, not a person waiting
    assert work_queue_service.build(db, tenant, None)["call_checks"]["count"] == 2   # team view: every agent's

    assert _post(client, mine.id, _owner_headers(tenant_and_user), ai_correct=True).status_code == 200
    assert work_queue_service.build(db, tenant, owner.id)["call_checks"]["count"] == 0
