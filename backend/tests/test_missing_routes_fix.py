"""Screens that called routes which did not exist: Compliance > Consents (GET /guests/consents was swallowed by
/guests/{guest_id}) and Profile > Change password (POST /auth/change-password)."""
import json
import uuid
from datetime import UTC, datetime

from app.core.security import get_password_hash, verify_password
from app.models.audit_event import AuditEvent
from app.models.consent import Consent
from app.models.guest import Guest
from app.models.user import RefreshToken, User, UserRole


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _auth(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _consent(db, tenant_id, phone, granted=True):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="G", phone=phone)
    db.add(g)
    db.flush()
    db.add(Consent(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, channel="whatsapp", scope="marketing",
                   granted=granted, recorded_at=datetime.now(UTC).isoformat()))
    db.commit()


def test_consents_list_is_masked_and_stays_in_the_workspace(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _consent(db, tid, "+919812345678", granted=False)
    _consent(db, str(_other(db)), "+919800000000")
    r = client.get("/api/v1/guests/consents", headers=_auth(tenant_and_user))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1 and rows[0]["guest_phone"] == "•••• 5678" and rows[0]["granted"] is False
    assert "9812345678" not in r.text


def test_consents_need_owner_or_compliance(client, db, tenant_and_user):
    for u in db.query(User).filter_by(tenant_id=_tid(tenant_and_user)):
        u.role = UserRole.CONCIERGE
    db.commit()
    assert client.get("/api/v1/guests/consents", headers=_auth(tenant_and_user)).status_code == 403


def _other(db):
    from app.models.tenant import Tenant

    t = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    return t.id


def test_change_password_checks_the_old_one_revokes_sessions_and_audits(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    user = db.query(User).filter_by(tenant_id=tid).first()
    user.hashed_password = get_password_hash("old-password-1")
    db.add(RefreshToken(id=str(uuid.uuid4()), user_id=user.id, tenant_id=tid, token_hash=uuid.uuid4().hex,
                        is_revoked=False))
    db.commit()
    h = _auth(tenant_and_user)
    url = "/api/v1/auth/change-password"
    assert client.post(url, json={"current_password": "wrong", "new_password": "new-password-1"}, headers=h).status_code == 400
    assert client.post(url, json={"current_password": "old-password-1", "new_password": "short"}, headers=h).status_code == 400
    r = client.post(url, json={"current_password": "old-password-1", "new_password": "new-password-1"}, headers=h)
    assert r.status_code == 200
    db.expire_all()
    user = db.get(User, user.id)
    assert verify_password("new-password-1", user.hashed_password)
    assert db.query(RefreshToken).filter_by(user_id=user.id, is_revoked=False).count() == 0
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="auth.password_changed").count() == 1
    assert client.post(url, json={"current_password": "x", "new_password": "y" * 9}).status_code == 401


def test_pasted_transcript_creates_a_call_and_queues_the_ai_read(client, db, tenant_and_user):
    from unittest.mock import patch

    from app.models.call import Call
    from app.models.transcript import Transcript

    text = "Agent: Good morning, Ratha caravans.\nGuest: Hi, is the caravan free on 12 Dec?\nfor four people\nAgent: Yes it is."
    with patch("app.workers.tasks.call_analysis.analyze_call.delay") as read:
        r = client.post("/api/v1/calls/transcript", data={"transcript": text, "agent_name": "Ravi"}, headers=_auth(tenant_and_user))
    assert r.status_code == 200 and r.json()["turns"] == 3 and read.call_count == 1
    call = db.get(Call, r.json()["call_id"])
    assert call.tenant_id == _tid(tenant_and_user) and call.transcription_status == "done"
    turns = json.loads(db.query(Transcript).filter_by(call_id=call.id).one().turns)
    assert [t["speaker"] for t in turns] == ["agent", "guest", "agent"] and turns[1]["text"].endswith("for four people")
    assert client.post("/api/v1/calls/transcript", data={"transcript": "too short"}, headers=_auth(tenant_and_user)).status_code == 422
