"""GET /knowledge/freshness, POST /knowledge/refresh, PUT /knowledge/source-settings: owner/manager only, own workspace only,
every change audited. Celery is never really called."""
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.models.audit_event import AuditEvent
from app.models.business_record import BusinessRecord
from app.models.knowledge import KnowledgeEntry
from app.models.tenant import Tenant
from app.services import knowledge_service as ks
from tests.test_business_data import _workspace
from tests.test_increment1_defect_specs import _h


@pytest.fixture(autouse=True)
def _no_celery():
    with patch("app.services.knowledge_freshness.enqueue_refresh", MagicMock()) as enqueue:
        yield enqueue


def _entry(db, tid, **kw):
    base = dict(id=str(uuid.uuid4()), tenant_id=tid, category="routes", content="Coorg route", source="manual",
                review_status="approved", embedding_status="done", is_active=True)
    base.update(kw)
    e = KnowledgeEntry(**base)
    if e.embedding_status == "done" and "content_hash" not in kw:
        e.content_hash = ks.content_hash(e.question, e.content)
    db.add(e)
    db.commit()
    return e


def _draft(db, tid):
    db.add(BusinessRecord(id=str(uuid.uuid4()), tenant_id=tid, kind="destination", key="mysore", version=1, status="draft",
                          data={"name": "Mysore"}))
    db.commit()


def test_freshness_shows_what_the_bot_uses_and_why_the_rest_is_not_used(db, client):
    w = _workspace(db)
    _entry(db, w.t.id)                                                                   # used
    _entry(db, w.t.id, source="instagram", review_status="pending", content="Mysore Dasara route")   # waiting approval
    _entry(db, w.t.id, embedding_status="failed", embedding_attempts=ks.MAX_AUTO_ATTEMPTS, content="old")  # gave up
    _entry(db, w.t.id, source="website", stale_since=w.t.created_at, content="removed from site", source_url="https://x.example/")
    _draft(db, w.t.id)

    r = client.get("/api/v1/knowledge/freshness", headers=_h(w.owner))
    assert r.status_code == 200, r.text
    body = r.json()
    by = {s["source"]: s for s in body["sources"]}
    assert by["manual"]["used_by_bot"] == 1 and by["manual"]["failed"] == 1 and by["manual"]["gave_up"] == 1
    assert by["instagram"]["waiting_approval"] == 1 and by["instagram"]["label"] == "Instagram posts"
    assert by["website"]["out_of_date"] == 1 and body["website"]["pages"] == 1
    assert body["business_data"]["drafts"] == 1
    codes = {x["code"] for x in body["warnings"]}
    assert {"unpublished_drafts", "waiting_approval", "failed", "out_of_date", "price_handoff", "instagram_not_connected"} <= codes
    assert body["settings"] == {"auto_approve_social": False, "social_sync": True, "website_recrawl": False, "social_max_age_days": 180}

    assert client.get("/api/v1/knowledge/freshness", headers=_h(w.mgr)).status_code == 200


def test_freshness_is_refused_to_other_roles(db, client):
    w = _workspace(db)
    assert client.get("/api/v1/knowledge/freshness", headers=_h(w.ro)).status_code == 403
    assert client.post("/api/v1/knowledge/refresh", headers=_h(w.ro)).status_code == 403
    assert client.put("/api/v1/knowledge/source-settings", json={"auto_approve_social": True}, headers=_h(w.ro)).status_code == 403


def test_freshness_counts_only_the_callers_workspace(db, client):
    a, b = _workspace(db), _workspace(db)
    _entry(db, b.t.id)
    _entry(db, b.t.id, source="instagram", review_status="pending")
    _draft(db, b.t.id)
    body = client.get("/api/v1/knowledge/freshness", headers=_h(a.owner)).json()
    assert body["sources"] == [] and body["business_data"]["drafts"] == 0


def test_refresh_requeues_unindexed_and_drifted_entries_and_is_audited(db, client, _no_celery):
    w, other = _workspace(db), _workspace(db)
    failed = _entry(db, w.t.id, embedding_status="failed", embedding_attempts=9)
    drifted = _entry(db, w.t.id, content_hash="0" * 64)                                  # indexed from older wording
    fine = _entry(db, w.t.id)
    theirs = _entry(db, other.t.id, embedding_status="failed", embedding_attempts=9)

    r = client.post("/api/v1/knowledge/refresh", headers=_h(w.owner))
    assert r.status_code == 200 and r.json() == {"queued_for_indexing": 2, "instagram_sync_queued": False}
    for e in (failed, drifted, fine, theirs):
        db.refresh(e)
    assert failed.embedding_status == "pending" and failed.embedding_attempts == 0
    assert drifted.embedding_status == "pending" and fine.embedding_status == "done"
    assert theirs.embedding_status == "failed"                                           # another workspace untouched
    assert _no_celery.call_args.args == (w.t.id,) and _no_celery.call_args.kwargs == {"reindex": True, "social": False}
    ev = db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="kb.refresh_requested").one()
    assert ev.actor_user_id == w.owner.id and ev.payload["entries"] == 2


def test_settings_change_is_audited_and_stays_in_its_workspace(db, client):
    a, b = _workspace(db), _workspace(db)
    r = client.put("/api/v1/knowledge/source-settings", json={"auto_approve_social": True, "website_recrawl": True}, headers=_h(a.mgr))
    assert r.status_code == 200 and r.json()["auto_approve_social"] is True and r.json()["social_sync"] is True
    db.expire_all()
    assert db.query(Tenant).filter_by(id=a.t.id).one().brand_config["knowledge"]["website_recrawl"] is True
    assert "knowledge" not in (db.query(Tenant).filter_by(id=b.t.id).one().brand_config or {})
    ev = db.query(AuditEvent).filter_by(tenant_id=a.t.id, action="kb.settings_updated").one()
    assert ev.payload["changes"]["auto_approve_social"] == {"from": False, "to": True} and ev.actor_user_id == a.mgr.id
    assert client.put("/api/v1/knowledge/source-settings", json={"auto_approve_social": "yes please"}, headers=_h(a.owner)).status_code == 422
