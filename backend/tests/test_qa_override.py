"""Correcting a QA score (POST /qa/scores/{id}/override, qa_service.override_score): validated against the rubric the call
was scored with, totals recomputed and copied to calls.ai_score (what dashboards read), the AI's original kept, audited,
owner/manager/compliance only, never another workspace's score."""
import uuid

from app.models.audit_event import AuditEvent
from app.models.call import Call
from app.models.score import CallScore, Rubric
from app.models.user import User, UserRole
from tests.workers import call_analysis_harness as h

CRITERIA = [
    {"id": "greet", "name": "Greeting", "weight": 10, "method": "YES_NO"},
    {"id": "probe", "name": "Needs", "weight": 30, "method": "ZERO_THREE"},
    {"id": "rude", "name": "No rudeness", "weight": 10, "method": "AUTO_FAIL"},
]


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _score(db, tid):
    r = Rubric(id=str(uuid.uuid4()), tenant_id=tid, name="QA", criteria=CRITERIA)
    db.add(r)
    c = h.call(db, tid, with_transcript=False)
    s = CallScore(id=str(uuid.uuid4()), tenant_id=tid, call_id=c.id, rubric_id=r.id, rubric_snapshot=CRITERIA,
                  total_score=20, max_score=50, percentage=40, has_auto_fail=False, model_used="fake",
                  criterion_scores=[{"id": "greet", "score": 1, "evidence_span": "Hello"}, {"id": "probe", "score": 0},
                                    {"id": "rude", "score": 1}])
    db.add(s)
    c.ai_score = 40
    db.commit()
    return s, c


def test_a_correction_recomputes_updates_the_call_and_keeps_the_ai_original(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    s, c = _score(db, tid)
    url = f"/api/v1/qa/scores/{s.id}/override"
    r = client.post(url, json={"criterion_scores": [{"id": "probe", "score": 3}], "reason": "She did ask about dates"},
                    headers=_h(tenant_and_user))
    assert r.status_code == 200 and r.json()["is_overridden"] is True
    db.expire_all()
    s = db.get(CallScore, s.id)
    assert float(s.percentage) == 100.0 and float(db.get(Call, c.id).ai_score) == 100.0
    assert s.override_scores["ai_original"]["percentage"] == 40.0 and s.override_scores["human"] == {"probe": 3.0}
    assert next(x for x in s.criterion_scores if x["id"] == "greet")["evidence_span"] == "Hello"
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="score.override").count() == 1
    # a second correction still remembers the AI's original, and an auto-fail is recomputed
    client.post(url, json={"criterion_scores": [{"id": "rude", "score": 0}], "reason": "Was rude at the end"},
                headers=_h(tenant_and_user))
    db.expire_all()
    s = db.get(CallScore, s.id)
    assert s.override_scores["ai_original"]["percentage"] == 40.0 and s.has_auto_fail is True


def test_bad_corrections_are_refused_in_words(client, db, tenant_and_user):
    s, _ = _score(db, _tid(tenant_and_user))
    url = f"/api/v1/qa/scores/{s.id}/override"
    h_ = _h(tenant_and_user)
    assert client.post(url, json={"criterion_scores": [{"id": "nope", "score": 1}], "reason": "x y z"}, headers=h_).status_code == 422
    assert client.post(url, json={"criterion_scores": [{"id": "greet", "score": 2}], "reason": "x y z"}, headers=h_).status_code == 422
    assert client.post(url, json={"criterion_scores": [{"id": "probe", "score": 2}], "reason": " "}, headers=h_).status_code == 422
    assert client.post(url, json={"criterion_scores": [], "reason": "nothing changed"}, headers=h_).status_code == 422


def test_other_workspaces_and_agents_cannot_correct(client, db, tenant_and_user):
    other = h.tenant(db)
    theirs, _ = _score(db, other.id)
    body = {"criterion_scores": [{"id": "probe", "score": 3}], "reason": "not mine"}
    assert client.post(f"/api/v1/qa/scores/{theirs.id}/override", json=body, headers=_h(tenant_and_user)).status_code == 404
    mine, _ = _score(db, _tid(tenant_and_user))
    for u in db.query(User).filter_by(tenant_id=_tid(tenant_and_user)):
        u.role = UserRole.CONCIERGE
    db.commit()
    assert client.post(f"/api/v1/qa/scores/{mine.id}/override", json=body, headers=_h(tenant_and_user)).status_code == 403
